"""
Сравнение подходов на ваших данных: только правила / только модель / гибрид (как в сервисе).

Запуск:
    python compare_approaches.py Правила_АГР.xlsx labels.xlsx [labels_spaces.xlsx] [--split projects]

Как считается. Данные делятся на 5 частей; каждая по очереди «прячется», модель учится на остальных,
а все три подхода предсказывают спрятанную часть — то есть как будто это новый проект.
    --split types    (по умолчанию) прячутся целые группы похожих имён: «насколько угадываем новые типы»;
    --split projects прячутся целые файлы IFC: «насколько угадываем новый проект»
                     (тут знакомые по другим проектам типы — честная помощь справочнику).

Подходы:
    только правила — таблица правил (жёсткие и «сверить с моделью» — все считаются ответом);
                     для помещений ещё классификатор по имени (это тоже знание, не обучение);
    только модель  — обученная модель, без правил и справочника;
    гибрид         — ровно как сервис: правило → справочник → «сверить с моделью» → модель.

Метрики (для каждого подхода):
    заполнено          — у скольких строк вообще есть ответ;
    точность (все)     — доля правильных среди ВСЕХ строк (нет ответа = ошибка);
    автоматически      — сколько ушло бы в модель без проверки человеком;
    точность автомат.  — сколько из них правильных: главная цифра для доверия;
    ошибок без проверки — неправильные значения, которые никто не увидит: главная цифра риска;
    на проверку        — сколько придётся смотреть глазами.
Результат — compare_report.xlsx (сводка, пороги уверенности, категории, все строки).

Контрольные IFC (честная проверка на отложенных объектах, в разметку они не попадают):
    python compare_approaches.py --control Правила_АГР.xlsx labels.xlsx labels_spaces.xlsx a.ifc b.ifc …
    → control_report.xlsx
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupKFold

warnings.filterwarnings("ignore")

from check_rules import features as rule_features  # noqa: E402
from eval_baseline import load  # noqa: E402
from rules_engine import MODE_SOFT, RuleSet, as_bool, norm  # noqa: E402
from train_model import make_model, predict_masked, prepare  # noqa: E402

EL_CODE, SP_CODE = "RUS_MSSK_Element_Code", "RUS_MSSK_SpaceAndZone_Code"
EXCLUDE = "Исключить элемент"
CONF_OK = 0.95
THRESHOLDS = [0.5, 0.7, 0.8, 0.9, 0.95, 0.99]
MODES = ["только правила", "только модель", "гибрид"]
KEY = ["revit_category", "ifc_class", "parent_class", "type_full"]


def same(a, b) -> bool:
    if a is None or b is None or str(a) == "" or str(b) == "":
        return False
    if as_bool(a) is not None and as_bool(b) is not None:
        return as_bool(a) == as_bool(b)
    return norm(a) == norm(b)


def first_file(files) -> str:
    return str(files or "").split(",")[0].strip()


# ---------------------------------------------------------------- элементы

def element_rows(rs: RuleSet, train: pd.DataFrame, test: pd.DataFrame, rf: pd.DataFrame) -> list[dict]:
    """Ответы трёх подходов для строк test; модель и справочник — по train. rf — признаки правил для test."""
    model = make_model().fit(train, train.code_final)
    preds, confs = predict_masked(model, train, test)
    known = train.drop_duplicates(KEY).set_index(KEY).code_final
    rows = []
    for j, (idx, r) in enumerate(test.iterrows()):
        f = {kk: (None if pd.isna(v) else v) for kk, v in rf.loc[idx].items()}
        res = rs.apply_all(f, fixed={"IfcExportAs": r.ifc_class})   # класс — как в ответах
        ex = res.get(EXCLUDE, (None, None))[0]
        v, q = res.get(EL_CODE, (None, None))
        if q is not None and norm(v) == "исключить":
            v, q = None, None
        mc, conf = preds[j], float(confs[j])
        soft = q is not None and q.mode == MODE_SOFT
        hard = q is not None and not soft
        key = tuple(r[c] for c in KEY)
        kn = known.get(key) if key in known.index else None

        # гибрид — как в сервисе
        if hard:
            h, ha, hs = v, True, f"правило (строка {q.row})"
        elif kn is not None:
            h, ha, hs = kn, (not soft or kn == v), "справочник"
        elif soft:
            h, ha, hs = v, mc == v, f"правило-сверить (строка {q.row})"
        else:
            h, ha, hs = mc, conf >= CONF_OK, "модель"

        rows.append({
            "что": "элементы", "параметр": EL_CODE, "категория": r.revit_category, "класс": r.ifc_class,
            "тип": r.type_full, "файл": r.get("file", ""), "элементов": r.get("n_elements", ""),
            "правильно": r.code_final, "исключён правилом": norm(ex) == "да",
            "только правила": v, "только правила_авто": q is not None,
            "только правила_источник": (f"правило (строка {q.row})" if q else ""),
            "только модель": mc, "только модель_авто": conf >= CONF_OK, "только модель_увер": round(conf, 3),
            "гибрид": h, "гибрид_авто": ha, "гибрид_источник": hs,
            "гибрид_увер": 1.0 if hs.startswith(("правило (", "справочник")) else round(conf, 3),
        })
    return rows


def compare_elements(rs: RuleSet, labels_path, split: str, log=print) -> pd.DataFrame:
    d = load(labels_path)
    d["file"] = d.files.map(first_file) if "files" in d else ""
    d = prepare(d)
    rf = rule_features(d, rs)        # признаки для правил: тип файла, толщина, «в витраже», створки…
    groups = d.files.map(first_file) if split == "projects" else d.group
    k = max(2, min(5, groups.nunique()))
    log(f"\nЭлементы: {len(d)} типов, проверка: {'по проектам' if split == 'projects' else 'новые типы'} ({k} частей)")
    rows = []
    for tr, te in GroupKFold(n_splits=k).split(d, groups=groups):
        rows += element_rows(rs, d.iloc[tr], d.iloc[te], rf)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- помещения и зоны

def space_rows(rs: RuleSet, train: pd.DataFrame, test: pd.DataFrame, col: str, param: str) -> list[dict]:
    """Ответы трёх подходов по одному параметру помещений для test; обучение — на train."""
    import train_spaces as ts
    sheet = rs.clf_sheet.get(SP_CODE, "")
    by_name = rs.clf_by_name.get(sheet, {})
    model = ts.make_space_model().fit(train, train[col]) if train[col].nunique() >= 2 else None
    single = train[col].iloc[0] if train[col].nunique() == 1 else None
    known = {tuple(ts.norm(r[c]) for c in ts.KEY): r[col] for _, r in train.iterrows()}
    if model is not None and len(test):
        proba = model.predict_proba(test)
        mpred = [(model.classes_[p.argmax()], float(p.max())) for p in proba]
    else:
        mpred = [(single, 0.8 if single else 0.0)] * len(test)
    rows = []
    for j, (_, r) in enumerate(test.iterrows()):
        f = {"file": first_file(r.get("files", r.get("file", ""))), "revit_category": r.revit_category,
             "ifc_class": "IfcSpace", "type_full": f"{r.revit_category}:{r.space_name}",
             "space_name": r.space_name, "space_purpose": r.space_purpose, "zone_type": r.zone_type}
        f["file_type"] = rs.file_type(f["file"])
        res = rs.apply_all(f)
        v, q = res.get(param, (None, None))
        soft = q is not None and q.mode == MODE_SOFT
        hard = q is not None and not soft
        codes = by_name.get(norm(r.space_name), []) if param == SP_CODE else []
        by_clf = codes[0] if len(codes) == 1 else None
        mc, conf = mpred[j]
        kn = known.get(tuple(ts.norm(r[c]) for c in ts.KEY))

        # только правила: таблица, затем классификатор по имени
        rv, ra, rsrc = (v, True, f"правило (строка {q.row})") if q is not None else \
            ((by_clf, True, "классификатор по имени") if by_clf else (None, False, ""))
        # гибрид — как в сервисе: правило → разметка → классификатор по имени → модель
        guess = (kn, "разметка", 1.0) if kn is not None else \
            ((by_clf, "классификатор по имени", 1.0) if by_clf else
             ((mc, "модель", conf) if mc is not None else None))
        if hard:
            h, ha, hs, hc = v, True, f"правило (строка {q.row})", 1.0
        elif soft:
            agree = guess is not None and same(guess[0], v)
            h, ha, hs, hc = v, agree, f"правило-сверить (строка {q.row})", 1.0 if agree else 0.8
        elif guess is not None:
            h, hs, hc = guess[0], guess[1], guess[2]
            ha = hc >= CONF_OK
        else:
            h, ha, hs, hc = None, False, "", 0.0
        rows.append({
            "что": "помещения", "параметр": param, "категория": r.revit_category,
            "класс": r.space_kind, "тип": f"{r.space_name} [{r.space_purpose}]",
            "файл": first_file(r.get("files", r.get("file", ""))), "элементов": r.get("n", ""),
            "правильно": r[col], "исключён правилом": False,
            "только правила": rv, "только правила_авто": ra, "только правила_источник": rsrc,
            "только модель": mc, "только модель_авто": conf >= CONF_OK, "только модель_увер": round(conf, 3),
            "гибрид": h, "гибрид_авто": ha, "гибрид_источник": hs, "гибрид_увер": round(hc, 3),
        })
    return rows


def compare_spaces(rs: RuleSet, path, split: str, log=print) -> pd.DataFrame:
    import train_spaces as ts
    d = pd.read_excel(path, sheet_name="Помещения", dtype=str).fillna("")
    d = ts.prepare(d[d.status != "исключить"]).reset_index(drop=True)
    rows = []
    for col, param in ts.TARGETS.items():
        x = ts.train_rows(d, col).reset_index(drop=True)
        if len(x) < 4:
            log(f"  {param}: мало размеченных строк ({len(x)}) — пропущено")
            continue
        groups = x.files.map(first_file) if (split == "projects" and "files" in x) else x.group
        if groups.nunique() < 2:
            log(f"  {param}: все строки из одной группы — проверить нельзя")
            continue
        k = max(2, min(5, groups.nunique()))
        for tr, te in GroupKFold(n_splits=k).split(x, groups=groups):
            rows += space_rows(rs, x.iloc[tr], x.iloc[te], col, param)
    log(f"\nПомещения и зоны: {len(d)} строк разметки")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- метрики

def metrics(r: pd.DataFrame) -> pd.DataFrame:
    out = []
    r = r[~r["исключён правилом"]]
    for (what, param), g in r.groupby(["что", "параметр"], sort=False):
        n = len(g)
        for m in MODES:
            filled = g[m].notna() & (g[m].astype(str) != "")
            ok = pd.Series([same(a, b) for a, b in zip(g[m], g["правильно"])], index=g.index)
            auto = g[m + "_авто"].astype(bool) & filled
            out.append({
                "что": what, "параметр": param, "подход": m, "строк": n,
                "заполнено": filled.mean(), "точность (все)": ok.mean(),
                "автоматически": auto.mean(),
                "точность автомат.": (ok & auto).sum() / auto.sum() if auto.sum() else None,
                "ошибок без проверки": int((auto & ~ok).sum()),
                "на проверку": 1 - auto.mean(),
            })
    return pd.DataFrame(out)


def thresholds(r: pd.DataFrame) -> pd.DataFrame:
    """Что будет при другом пороге «доверять модели» (CONF_OK в service.py)."""
    out = []
    r = r[~r["исключён правилом"]]
    for (what, param), g in r.groupby(["что", "параметр"], sort=False):
        ok = pd.Series([same(a, b) for a, b in zip(g["только модель"], g["правильно"])], index=g.index)
        for t in THRESHOLDS:
            auto = g["только модель_увер"] >= t
            out.append({"что": what, "параметр": param, "порог": t, "модель: автоматически": auto.mean(),
                        "модель: точность автомат.": (ok & auto).sum() / auto.sum() if auto.sum() else None,
                        "модель: ошибок без проверки": int((auto & ~ok).sum())})
    return pd.DataFrame(out)


def by_category(r: pd.DataFrame) -> pd.DataFrame:
    r = r[~r["исключён правилом"]]
    out = []
    for (what, param, cat), g in r.groupby(["что", "параметр", "категория"], sort=False):
        row = {"что": what, "параметр": param, "категория": cat, "строк": len(g)}
        for m in MODES:
            row[m] = sum(same(a, b) for a, b in zip(g[m], g["правильно"])) / len(g)
        out.append(row)
    return pd.DataFrame(out).sort_values(["что", "параметр", "строк"], ascending=[True, True, False])


def report(r: pd.DataFrame, out: Path, title: str, log=print, extra_info: list | None = None):
    excluded = int(r["исключён правилом"].sum()) if len(r) else 0
    summ, thr, cat = metrics(r), thresholds(r), by_category(r)
    pct = lambda v: "—" if v is None or pd.isna(v) else f"{v:.0%}"  # noqa: E731
    log(f"\n=== {title} ===")
    for (what, param), g in summ.groupby(["что", "параметр"], sort=False):
        log(f"\n{what} — {param} ({g['строк'].iloc[0]} строк)")
        log(f"  {'подход':16} {'заполнено':>10} {'точность':>9} {'автомат.':>9} {'точн.авт.':>10} "
            f"{'ошибок без проверки':>20} {'на проверку':>12}")
        for x in g.itertuples():
            log(f"  {x.подход:16} {pct(x.заполнено):>10} {pct(x._6):>9} {pct(x.автоматически):>9} "
                f"{pct(x._8):>10} {x._9:>20} {pct(x._10):>12}")
    if excluded:
        log(f"\nИсключено правилом «{EXCLUDE}» (в метриках не участвуют): {excluded}")
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="Сводка", index=False)
        thr.to_excel(xw, sheet_name="Пороги уверенности", index=False)
        cat.to_excel(xw, sheet_name="По категориям", index=False)
        r.to_excel(xw, sheet_name="Все строки", index=False)
        if extra_info:
            pd.DataFrame(extra_info, columns=["", ""]).to_excel(xw, sheet_name="О проверке", index=False)
    _format(out)
    log(f"\nотчёт: {out}")
    return out


def main(rules_path, labels_path, spaces_path=None, split="types", out_dir=None, log=print):
    rs = RuleSet(rules_path)
    parts = [compare_elements(rs, labels_path, split, log)]
    if spaces_path and Path(spaces_path).exists():
        parts.append(compare_spaces(rs, spaces_path, split, log))
    r = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    out = Path(out_dir or Path(labels_path).parent) / "compare_report.xlsx"
    return report(r, out, "по проектам" if split == "projects" else "новые типы", log)


# ---------------------------------------------------------------- контрольные IFC

def control(rules_path, labels_path, ifc_files, spaces_path=None, out_dir=None, log=print, workers=2):
    """
    Честная проверка на отложенных IFC: правила и модели — из текущей разметки,
    коды из контрольных IFC — только правильные ответы (в разметку не попадают).
    """
    import train_spaces as ts
    from ifc_to_dataset import extract_files
    rs = RuleSet(rules_path)
    out_dir = Path(out_dir or Path(labels_path).parent)
    files = [Path(f) for f in ifc_files]

    # обучение — вся разметка
    train = load(labels_path)
    used = {x.strip() for v in train.get("files", pd.Series(dtype=str)) for x in str(v).split(",") if x.strip()}
    overlap = [f.name for f in files if f.name in used]
    if overlap:
        log("⚠ Эти файлы уже есть в разметке — проверка на них будет нечестной: " + ", ".join(overlap))
    train = prepare(train)

    # ответы — из контрольных IFC (кэш — отдельный, чтобы не путать с обучением)
    df = extract_files(files, out_dir / "cache", log=log, workers=workers)
    df = df.astype(object).where(df.notna(), None)

    # элементы: один «тип» = тип + класс + роль + категория; правильный код — самый частый в IFC
    el = df[(df.ifc_class != "IfcSpace") & df.y_el_code.notna()].copy()
    for c in KEY + ["materials", "layers_mm", "IsExternal", "LoadBearing", "has_door_leaf", "file"]:
        el[c] = el[c].map(lambda v: "" if v is None else str(v)) if c in el else ""
    g = el.groupby(KEY + ["file"], dropna=False)
    test = g.agg(code_final=("y_el_code", lambda s: s.mode().iloc[0]),
                 n_codes=("y_el_code", "nunique"), n_elements=("guid", "size"),
                 **{c: (c, "first") for c in ["materials", "layers_mm", "IsExternal", "LoadBearing",
                                              "has_door_leaf"]}).reset_index()
    test = prepare(test)
    test.index = range(len(test))
    rf = rule_features(test, rs)
    rows = element_rows(rs, train, test, rf)
    log(f"\nКонтрольные IFC: {len(files)} файлов, типов элементов: {len(test)} "
        f"(в разметке для обучения: {len(train)})")

    # помещения и зоны
    if spaces_path and Path(spaces_path).exists():
        sp_train = ts.prepare(pd.read_excel(spaces_path, sheet_name="Помещения", dtype=str).fillna(""))
        sp = df[df.ifc_class == "IfcSpace"].copy()
        if len(sp):
            sp["space_kind"] = sp.get("space_kind")
            for c in ts.KEY:
                sp[c] = sp[c].map(lambda v: "" if v is None else str(v)) if c in sp else ""
            yn = lambda v: "" if v is None else ({"true": "Да", "false": "Нет"}.get(str(v).lower(), str(v)))  # noqa
            src = {"code_final": "y_space_code", "zone_final": "y_zone",
                   "residential_final": "y_residential", "floating_final": "y_floating_floor"}
            for c, y in src.items():
                sp[c] = sp[y].map(yn) if y in sp else ""
            sp_test = sp.groupby(ts.KEY + ["file"], dropna=False).agg(
                n=("guid", "size"), **{c: (c, lambda s: s.mode().iloc[0] if len(s.mode()) else "")
                                       for c in src}).reset_index()
            sp_test = ts.prepare(sp_test)
            for col, param in ts.TARGETS.items():
                tr = ts.train_rows(sp_train, col)
                te = sp_test[sp_test[col] != ""]
                if len(tr) == 0 or len(te) == 0:
                    continue
                rows += space_rows(rs, tr, te, col, param)
            log(f"Помещений и зон (уникальных): {len(sp_test)}")

    info = [["Что это", "Проверка на контрольных IFC: модели и справочник — из разметки, ответы — из этих IFC"],
            ["Файлы", ", ".join(f.name for f in files)],
            ["Уже были в разметке", ", ".join(overlap) or "нет"],
            ["Важно", "Ответы — то, что стоит в выданных IFC. Если IFC размечен по старым правилам, "
                      "«ошибка» может оказаться правильным новым значением — смотрите лист «Все строки»."]]
    return report(pd.DataFrame(rows), out_dir / "control_report.xlsx", "контрольные IFC", log, info)


def _format(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Font
    wb = load_workbook(path)
    for ws in wb:
        head = [c.value for c in ws[1]]
        for i, h in enumerate(head, 1):
            ws.cell(1, i).font = Font(bold=True)
            letter = ws.cell(1, i).column_letter
            ws.column_dimensions[letter].width = 45 if h in ("тип",) else 18
            if ws.title != "Все строки" and h not in ("что", "параметр", "подход", "категория", "строк", "порог") \
                    and not str(h).startswith("ошибок"):
                for c in ws[letter][1:]:
                    c.number_format = "0%"
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)


if __name__ == "__main__":
    if "--control" in sys.argv:
        # python compare_approaches.py --control Правила_АГР.xlsx labels.xlsx labels_spaces.xlsx a.ifc b.ifc …
        a = [x for x in sys.argv[1:] if x != "--control"]
        control(a[0], a[1], a[3:], a[2] if a[2].endswith(".xlsx") else None)
        sys.exit()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    split = "projects" if "--split" in sys.argv and "projects" in sys.argv else "types"
    if len(args) < 2:
        sys.exit(__doc__)
    main(args[0], args[1], args[2] if len(args) > 2 else None, split)
