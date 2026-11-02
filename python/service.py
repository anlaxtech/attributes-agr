"""
Сервис предсказаний для плагина Revit (версия 2: таблица правил + обучение).

Запуск (из папки со скриптами):
    pip install fastapi uvicorn
    python service.py Правила_АГР.xlsx labels.xlsx

Правила_АГР.xlsx — ваша таблица правил: порядок параметров, правила, классификаторы.
labels.xlsx      — разметка для модели кода «Элементы» (как раньше).
Поменяли любую из таблиц — POST /reload или перезапуск.

Как определяется каждое значение (по порядку листа «Параметры»):
    1. значение, исправленное пользователем на предыдущем шаге — не трогаем;
    2. «правило»                         — уверенность 1.0;
    3. справочник — тип уже размечен в labels.xlsx (только код «Элементы»);
    4. «правило, сверить с моделью»      — если модель не согласна → «проверить»;
    5. модель (код «Элементы»), классификатор по имени (коды помещений);
    6. ничего не подошло                 — пусто, «проверить».

Автоперезагрузка: сервис раз в AGR_RELOAD_SEC секунд (по умолчанию 30) проверяет,
не изменились ли таблицы, и сам перечитывает их. Если файл открыт или сохранён с ошибкой,
продолжает работать на прежней версии и пишет об этом в консоль и в /health.

Эндпоинты:
    GET  /health, /classifiers, POST /predict_all, POST /reload
    POST /corrections — правки пользователей из плагина → data/corrections.csv

Режим для экспериментов: AGR_MODE = hybrid (по умолчанию) | rules (только правила) | model (только модель).

Защита: AGR_TOKEN — если задан, запросы без заголовка X-AGR-Token: <токен> отклоняются (кроме /health).

Переменные окружения (для Docker): AGR_HOST (127.0.0.1), AGR_PORT (8765), AGR_RELOAD_SEC (30),
AGR_RULES, AGR_LABELS — пути к таблицам, если не заданы аргументами.
"""
from __future__ import annotations

import os
import sys
import threading
import warnings
from contextlib import asynccontextmanager
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# openpyxl предупреждает о выпадающих списках в Excel — на чтение не влияет
warnings.filterwarnings("ignore", message="Data Validation extension is not supported")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import thickness  # noqa: E402
from rules_engine import MODE_SOFT, RuleSet, norm  # noqa: E402
from train_model import make_model, predict_masked, prepare  # noqa: E402
import train_spaces  # noqa: E402

CONF_OK = 0.95
# Режим для экспериментов: hybrid (обычный) | rules (только правила) | model (только модель)
MODE = os.environ.get("AGR_MODE", "hybrid").strip().lower()
EL_CODE, SP_CODE = "RUS_MSSK_Element_Code", "RUS_MSSK_SpaceAndZone_Code"
EXCLUDE = "Исключить элемент"
KEY = ["revit_category", "ifc_class", "parent_class", "type_full"]
RULES_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGR_RULES", "Правила_АГР.xlsx"))
LABELS_PATH = Path(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("AGR_LABELS", "labels.xlsx"))
SPACE_LABELS_PATH = Path(sys.argv[3] if len(sys.argv) > 3 else
                         os.environ.get("AGR_SPACE_LABELS", str(LABELS_PATH.parent / "labels_spaces.xlsx")))
RELOAD_SEC = int(os.environ.get("AGR_RELOAD_SEC", "30"))
SPACE_PARAMS = set(train_spaces.TARGETS.values())


class ItemIn(BaseModel):
    id: str
    features: Dict[str, Optional[str]] = {}
    fixed: Dict[str, str] = {}      # исправлено пользователем — следующие шаги опираются на это


class PredictIn(BaseModel):
    items: List[ItemIn]


class CorrectionsIn(BaseModel):
    rows: List[Dict[str, Optional[str]]]


CORR_COLS = ["received", "date", "user", "project", "edited", "param", "predicted", "value", "name", "source",
             "conf", "status", "n_elements", "revit_category", "ifc_class", "ifc_export", "parent_class",
             "type_full", "materials", "layers_mm", "IsExternal", "has_door_leaf", "room_from", "room_to",
             "space_name", "space_purpose", "zone_type", "file", "facade_type"]
CORR_LOCK = threading.Lock()


class S:
    lock = threading.RLock()
    loaded_at = ""
    stamps: tuple = ()
    last_error = ""
    rules: RuleSet = None
    model = None
    train = None
    known = None
    used: dict = {}
    space: dict = {}


def _stamps():
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in (RULES_PATH, LABELS_PATH, SPACE_LABELS_PATH))


def load_state():
    """Читает таблицы и обучает модель. Новое состояние подменяет старое только целиком и без ошибок."""
    stamps = _stamps()
    with S.lock:
        _load()
        S.stamps = stamps
        S.loaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        S.last_error = ""
    print(f"[{S.loaded_at}] загружено")


def _load():
    # сначала всё строим во временных переменных — при ошибке старое состояние остаётся
    rules = RuleSet(RULES_PATH)
    print(f"правила: {len(rules.rules)}, параметров: {len(rules.order)}")
    model = train = known = None
    used = {}
    if LABELS_PATH.exists():
        lab = pd.read_excel(LABELS_PATH, sheet_name="Разметка", dtype=str).fillna("")
        train = prepare(lab[(lab.code_final != "") & (lab.status != "исключить")])
        model = make_model().fit(train, train.code_final)
        known = train.drop_duplicates(KEY).set_index(KEY).code_final
        used = train.code_final.value_counts().to_dict()
        print(f"модель кода «Элементы»: {len(train)} типов")
    else:
        print(f"нет {LABELS_PATH} — код «Элементы» только по правилам")
    space = {}
    if SPACE_LABELS_PATH.exists():
        space = train_spaces.fit_all(SPACE_LABELS_PATH)
        print("модели помещений: " + ", ".join(f"{p} ({v['rows']} строк)" for p, v in space.items()))
    else:
        print(f"нет {SPACE_LABELS_PATH} — помещения только по правилам и классификатору")
    S.rules, S.model, S.train, S.known, S.used, S.space = rules, model, train, known, used, space


def _watch():
    """Фоновая проверка: изменились таблицы — перечитать. Excel сохраняет файл не мгновенно,
    поэтому ждём, пока время изменения перестанет меняться."""
    while True:
        time.sleep(RELOAD_SEC)
        try:
            now = _stamps()
            if now == S.stamps:
                continue
            time.sleep(3)
            if _stamps() != now:
                continue          # файл ещё сохраняется — проверим в следующий раз
            print("таблицы изменились — перечитываю…")
            load_state()
        except Exception as e:  # открыт в Excel, битый файл и т.п. — работаем на прежней версии
            S.last_error = f"{datetime.now():%H:%M:%S}: {e}"
            S.stamps = _stamps()  # не повторять ту же ошибку каждые 30 секунд
            print("не удалось перечитать, работаю на прежней версии:", e)


@asynccontextmanager
async def lifespan(_app):
    load_state()
    if RELOAD_SEC > 0:
        threading.Thread(target=_watch, daemon=True).start()
    yield


app = FastAPI(title="АтрибутыАГР", lifespan=lifespan)


# Простая защита: если задан AGR_TOKEN, все запросы (кроме /health) должны нести заголовок X-AGR-Token.
TOKEN = os.environ.get("AGR_TOKEN", "").strip()


@app.middleware("http")
async def check_token(request: Request, call_next):
    if TOKEN and request.url.path != "/health" and request.headers.get("X-AGR-Token", "") != TOKEN:
        return JSONResponse({"detail": "нет доступа: неверный или пустой токен (X-AGR-Token)"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": S.rules is not None, "rules": str(RULES_PATH), "labels": str(LABELS_PATH),
            "mode": MODE, "loaded_at": S.loaded_at, "last_error": S.last_error,
            "rules_count": len(S.rules.rules) if S.rules else 0,
            "labels_count": 0 if S.train is None else len(S.train),
            "space_labels": str(SPACE_LABELS_PATH),
            "space_rows": {p: v["rows"] for p, v in S.space.items()},
            "params": S.rules.order if S.rules else []}


@app.post("/reload")
def reload():
    load_state()
    return health()


@app.get("/classifiers")
def classifiers():
    """Классификаторы и какой параметр к какому относится (для окна выбора кода)."""
    r = S.rules
    out = {sheet: [{"code": c, "name": n, "used": int(S.used.get(c, 0))} for c, n in names.items()]
           for sheet, names in r.clf_names.items()}
    params = {p: sh for p, sh in r.clf_sheet.items() if p not in r.code_of}
    name_param = {code_p: name_p for name_p, code_p in r.code_of.items()}
    P = r.params
    desc = dict(zip(P.iloc[:, 0], P.iloc[:, 6])) if P.shape[1] > 6 else {}
    return {"classifiers": out, "param_classifier": params, "name_param": name_param, "order": r.order,
            "descriptions": {k: v for k, v in desc.items() if k and v}}


def base_class(ifc_export: str) -> str:
    return (ifc_export or "").split(" (")[0]


def element_model(rows: list[dict]):
    """Модель кода «Элементы» для пачки элементов: (код, уверенность) по каждому."""
    if S.model is None or not rows:
        return [(None, 0.0)] * len(rows)
    df = prepare(pd.DataFrame(rows).fillna(""))
    preds, confs = predict_masked(S.model, S.train, df)
    return list(zip(preds, [float(c) for c in confs]))


def predict_items(items_in: list[ItemIn]) -> list[dict]:
    r = S.rules
    items = []
    for it in items_in:
        f = {k: v for k, v in it.features.items()}
        f["file_type"] = r.file_type(f.get("file") or "")
        if not f.get("thick"):
            f["thick"] = thickness(pd.Series({"layers_mm": f.get("layers_mm") or "",
                                              "type_full": f.get("type_full") or ""}))
        items.append((it, f, r.apply_all(f, it.fixed)))

    # модель кода «Элементы» — одним вызовом для всех элементов
    rows, idx = [], []
    for i, (it, f, res) in enumerate(items):
        cls = base_class(res.get("IfcExportAs", (None,))[0] or f.get("ifc_class") or "")
        if cls and cls != "IfcSpace":
            row = {k: f.get(k) or "" for k in ["revit_category", "parent_class", "type_full", "materials",
                                               "layers_mm", "IsExternal", "LoadBearing", "has_door_leaf"]}
            row["ifc_class"] = cls
            rows.append(row)
            idx.append(i)
    model_out = dict(zip(idx, element_model(rows)))

    out = []
    for i, (it, f, res) in enumerate(items):
        ex, exq = res.get(EXCLUDE, (None, None))
        if norm(ex) == "да":
            out.append({"id": it.id, "excluded": f"строка {exq.row}" if exq else "правило", "values": {}})
            continue
        ifc_export = res.get("IfcExportAs", (None,))[0] or f.get("ifc_class") or ""
        values = {}
        for p in r.order:
            if p in r.code_of or p == EXCLUDE:
                continue   # наименования отдаются вместе с кодом
            is_space = base_class(ifc_export) == "IfcSpace"
            learnable = (p == EL_CODE and i in model_out) or (p == SP_CODE and is_space) or \
                        (p in SPACE_PARAMS and is_space and S.space.get(p, {}).get("rows", 0) > 0)
            if p != "IfcExportAs" and not r.applies(p, ifc_export) and not learnable:
                continue
            v, q = res.get(p, (None, None))
            if MODE == "model" and learnable and q not in (None, "fixed"):
                v, q = None, None          # «только модель»: правила для обучаемых параметров не применяем
            cell = {"value": v or "", "name": "", "source": "", "conf": 0.0, "status": "проверить",
                    "options": sorted(r.allowed_values(p, "" if p == "IfcExportAs" else ifc_export))}
            if q == "fixed":
                cell.update(source="исправлено", conf=1.0, status="проверено")
            elif q is not None and norm(v) == "исключить":
                cell.update(value="", source=f"исключено правилом (строка {q.row})", conf=1.0, status="исключить")
            elif q is not None and (q.mode != MODE_SOFT or MODE == "rules"):
                cell.update(source=f"правило (строка {q.row})", conf=1.0, status="ок")
            elif MODE == "rules":
                cell = rules_only(p, f, ifc_export, cell)
            else:
                cell = learned(p, f, i, model_out, ifc_export, cell, v, q, model_only=MODE == "model")
            if p in r.clf_sheet:
                cell["name"] = r.clf_names.get(r.clf_sheet[p], {}).get(cell["value"], "")
            values[p] = cell
        out.append({"id": it.id, "values": values})
    return out


def rules_only(p, f, ifc_export, cell):
    """Режим «только правила»: правила не сработали — для кода помещения классификатор по имени, иначе пусто."""
    if p == SP_CODE and base_class(ifc_export) == "IfcSpace":
        sheet = S.rules.clf_sheet.get(p, "")
        codes = S.rules.clf_by_name.get(sheet, {}).get(norm(f.get("space_name")), [])
        if len(codes) == 1:
            return {**cell, "value": codes[0], "source": "классификатор по имени", "conf": 1.0, "status": "ок"}
    return cell


def learned(p, f, i, model_out, ifc_export, cell, v, q, model_only=False):
    """Справочник, мягкие правила и модель. model_only — без справочника (режим «только модель»)."""
    soft = q is not None
    if p == EL_CODE:
        key = (f.get("revit_category") or "", base_class(ifc_export), f.get("parent_class") or "",
               f.get("type_full") or "")
        if not model_only and S.known is not None and key in S.known.index:
            known = S.known[key]
            ok = not soft or known == v
            return {**cell, "value": known, "conf": 1.0, "status": "ок" if ok else "проверить",
                    "source": "справочник" if ok else f"справочник; правило (строка {q.row}): {v}"}
        mc, conf = model_out.get(i, (None, 0.0))
        if soft:
            agree = mc == v
            return {**cell, "value": v, "conf": 1.0 if agree else round(conf, 2),
                    "status": "ок" if agree else "проверить",
                    "source": f"правило (строка {q.row})" + ("" if agree else f"; модель: {mc}")}
        if mc:
            return {**cell, "value": mc, "source": "модель", "conf": round(conf, 2),
                    "status": "ок" if conf >= CONF_OK else "проверить"}
    if p in SPACE_PARAMS and base_class(ifc_export) == "IfcSpace":
        guess = space_guess(p, f, model_only)  # (значение, источник, уверенность) или None
        if soft:
            agree = guess is not None and guess[0] == v
            return {**cell, "value": v, "conf": 1.0 if agree else 0.8, "status": "ок" if agree else "проверить",
                    "source": f"правило (строка {q.row})" + ("" if agree or guess is None else f"; {guess[1]}: {guess[0]}")}
        if guess is not None:
            val, src, conf = guess
            return {**cell, "value": val, "source": src, "conf": round(conf, 2),
                    "status": "ок" if conf >= CONF_OK else "проверить"}
    if soft:
        return {**cell, "value": v, "source": f"правило (строка {q.row}), сверить", "conf": 0.8,
                "status": "проверить"}
    return cell


def space_guess(p, f, model_only=False):
    """Помещения: разметка (точно такое же помещение) → классификатор по имени (для кода) → модель."""
    kind = "зона" if "зон" in (f.get("revit_category") or "").lower() else "помещение"
    key = tuple(train_spaces.norm(x) for x in (kind, f.get("revit_category"), f.get("space_name"),
                                                f.get("space_purpose"), f.get("zone_type")))
    m = S.space.get(p, {})
    if not model_only and key in m.get("known", {}):
        return m["known"][key], "разметка помещений", 1.0
    if p == SP_CODE and not model_only:
        sheet = S.rules.clf_sheet.get(p, "")
        codes = S.rules.clf_by_name.get(sheet, {}).get(norm(f.get("space_name")), [])
        if len(codes) == 1:
            return codes[0], "классификатор по имени", 1.0
    if m.get("model") is not None:
        row = pd.DataFrame([{"space_kind": kind, "revit_category": f.get("revit_category") or "",
                             "space_name": f.get("space_name") or "", "space_purpose": f.get("space_purpose") or "",
                             "zone_type": f.get("zone_type") or ""}])
        proba = m["model"].predict_proba(train_spaces.prepare(row))[0]
        return m["model"].classes_[proba.argmax()], "модель помещений", float(proba.max())
    if m.get("single"):
        return m["single"], "разметка помещений (единственное значение)", 0.8
    return None


@app.post("/corrections")
def corrections(req: CorrectionsIn):
    """Правки из плагина: что пользователь исправил или подтвердил вручную. Дописываются в CSV рядом с labels."""
    import csv
    path = LABELS_PATH.parent / "corrections.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CORR_LOCK:
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CORR_COLS, extrasaction="ignore")
            if new:
                w.writeheader()
            for r in req.rows:
                w.writerow({**{k: (v or "") for k, v in r.items()}, "received": now})
    return {"saved": len(req.rows), "file": str(path)}


@app.post("/predict_all")
def predict_all(req: PredictIn):
    if S.rules is None:
        raise HTTPException(503, "правила не загружены")
    with S.lock:     # во время перезагрузки запросы подождут пару секунд
        return predict_items(req.items)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("AGR_HOST", "127.0.0.1"), port=int(os.environ.get("AGR_PORT", "8765")))
