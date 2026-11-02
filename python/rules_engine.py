"""
Движок правил: читает таблицу «Правила_АГР.xlsx» и определяет значения параметров.

Одна строка таблицы — одно правило: «если все заполненные условия выполнены,
параметр получает значение». Пустая ячейка условия = «неважно».
В ячейке можно перечислить варианты через запятую (любой из них подходит),
а «!» перед вариантом означает «НЕ» (например, «!фасад»).

Параметры заполняются по порядку листа «Параметры»: сначала IfcExportAs,
потом классификатор и т. д. Каждое правило может опираться на уже найденные значения
(колонка «IFC-класс» и колонка «Условие по параметру»).

Как применять:
    правило                    — значение ставится с полной уверенностью
    правило, сверить с моделью — ставится, но если модель не согласна → «проверить»
    только обучение            — правило не срабатывает; строка просто сообщает,
                                 что такое значение возможно (ограничивает модель)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

RULES_SHEET = "Правила"
PARAMS_SHEET = "Параметры"
FILES_SHEET = "Типы файлов"

MODE_RULE = "правило"
MODE_SOFT = "правило, сверить с моделью"
MODE_LEARN = "только обучение"

# колонка таблицы → ключ признака (что проверяем)
COND_COLUMNS = {
    "Категория Revit": "revit_category",
    "Тип файла": "file_type",
    "Тип фасада": "facade_type",
    "Имя типа содержит": "type_full",
    "Имя типа не содержит": "type_full",
    "Материал содержит": "materials",
    "Толщина от": "thick",
    "Толщина до": "thick",
    "Стена-витраж": "is_curtain_wall",
    "Внутри витража": "in_curtain_wall",
    "Створка с дверью": "has_door_leaf",
    "Из помещения": "room_from",
    "В помещение": "room_to",
    "Условие по параметру": None,
}


def norm(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return str(s).strip().lower().replace("ё", "е")


def split_list(cell) -> list[str]:
    return [x.strip() for x in re.split(r"[,;\n]", norm(cell)) if x.strip()]


def as_bool(v):
    n = norm(v)
    if n in ("да", "true", "1", "yes"):
        return True
    if n in ("нет", "false", "0", "no"):
        return False
    return None


@dataclass
class Rule:
    row: int                      # номер строки в Excel — чтобы найти правило
    param: str
    ifc_class: list[str]
    value: str
    mode: str
    priority: float
    conds: dict = field(default_factory=dict)
    comment: str = ""

    @property
    def label(self) -> str:
        return f"строка {self.row}: {self.comment or self.value}"[:120]


class RuleSet:
    def __init__(self, path: str | Path):
        path = Path(path)
        r = pd.read_excel(path, sheet_name=RULES_SHEET, dtype=str).fillna("")
        self.params = pd.read_excel(path, sheet_name=PARAMS_SHEET, dtype=str).fillna("")
        files = pd.read_excel(path, sheet_name=FILES_SHEET, dtype=str).fillna("")
        self.file_patterns = [(norm(a), norm(b)) for a, b in zip(files.iloc[:, 0], files.iloc[:, 1]) if a]
        P = self.params
        self.order = [p for p in P.iloc[:, 0] if p]
        col = lambda i: P.iloc[:, i] if P.shape[1] > i else pd.Series([""] * len(P))
        self.source = dict(zip(P.iloc[:, 0], col(2)))
        self.code_of = {a: b for a, b in zip(P.iloc[:, 0], col(3)) if b}      # Name ← Code
        self.clf_sheet = {a: b for a, b in zip(P.iloc[:, 0], col(4)) if b}
        self.truth_col = {a: b for a, b in zip(P.iloc[:, 0], col(5)) if b}
        # «нет» — старые выданные IFC для этого параметра не годятся как обучающие данные
        self.learn_from_ifc = {a: norm(b) != "нет" for a, b in zip(P.iloc[:, 0], col(7))}
        # классификаторы: код → наименование и наименование → коды
        self.clf_names, self.clf_by_name = {}, {}
        for sheet in set(self.clf_sheet.values()):
            try:
                c = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")
            except ValueError:
                continue
            self.clf_names[sheet] = dict(zip(c.iloc[:, 0].str.strip(), c.iloc[:, 1].str.strip()))
            by = {}
            for code, name in self.clf_names[sheet].items():
                by.setdefault(norm(name), []).append(code)
            self.clf_by_name[sheet] = by
        self.warnings: set[str] = set()
        self.rules: list[Rule] = []
        for i, x in r.iterrows():
            if norm(x.get("Вкл", "да")) in ("нет", "0") or not x.get("Параметр") or not x.get("Значение"):
                continue
            conds = {c: x.get(c, "") for c in COND_COLUMNS if str(x.get(c, "")).strip()}
            try:
                prio = float(str(x.get("Приоритет", "")).replace(",", ".") or 100)
            except ValueError:
                prio = 100
            self.rules.append(Rule(
                row=i + 2, param=x["Параметр"].strip(), ifc_class=split_list(x.get("IFC-класс", "")),
                value=str(x["Значение"]).strip(), mode=norm(x.get("Как применять", "")) or MODE_RULE,
                priority=prio, conds=conds, comment=str(x.get("Комментарий", "")).strip()))
        self.rules.sort(key=lambda q: (q.param, q.priority, q.row))

    # ---------- признаки ----------

    def file_type(self, file_name: str) -> str:
        n = norm(file_name)
        default = ""
        for pattern, kind in self.file_patterns:
            if pattern == "*":
                default = kind          # «*» — тип по умолчанию, если ничего не совпало
            elif pattern and pattern in n:
                return kind
        return default

    def allowed_values(self, param: str, ifc_class: str) -> set[str]:
        """Все значения из таблицы для параметра и класса (в т.ч. «только обучение»)."""
        c = norm(ifc_class)
        return {self.to_code(param, q.value) for q in self.rules
                if q.param == param and "{" not in q.value and q.value.strip()
                and (not q.ifc_class or c in q.ifc_class or c.split(" (")[0] in q.ifc_class)}

    def applies(self, param: str, ifc_class: str) -> bool:
        """Есть ли в таблице хоть одно правило (в т.ч. «только обучение») для параметра и класса."""
        c = norm(ifc_class)
        return any(q.param == param and (not q.ifc_class or c in q.ifc_class or c.split(" (")[0] in q.ifc_class)
                   for q in self.rules)

    # ---------- проверка условий ----------

    @staticmethod
    def _match_list(cell, value) -> bool | None:
        """Список вариантов с «!» для отрицания. None — нет данных для проверки."""
        if value is None or norm(value) == "":
            return None
        v = norm(value)
        items = split_list(cell)
        pos = [i for i in items if not i.startswith("!")]
        neg = [i[1:] for i in items if i.startswith("!")]
        if any(n and n == v for n in neg):
            return False
        return (not pos) or v in pos

    @staticmethod
    def _contains(cell, text) -> bool | None:
        """Варианты через запятую — любой; «гкл+перегородк» — все части сразу."""
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return None
        t = norm(text)
        return any(all(part.strip() in t for part in w.split("+")) for w in split_list(cell))

    def check(self, rule: Rule, f: dict) -> bool | None:
        """True — подходит, False — нет, None — не хватает данных (правило пропускается)."""
        cls = norm(f.get("IfcExportAs") or f.get("ifc_class"))
        if rule.ifc_class and rule.param != "IfcExportAs":
            if cls not in rule.ifc_class and cls.split(" (")[0] not in rule.ifc_class:
                return False
        unknown = False
        for col, cell in rule.conds.items():
            key = COND_COLUMNS[col]
            if col in ("Категория Revit", "Тип файла", "Тип фасада", "Из помещения", "В помещение"):
                ok = self._match_list(cell, f.get(key))
            elif col in ("Имя типа содержит", "Материал содержит"):
                ok = self._contains(cell, f.get(key))
            elif col == "Имя типа не содержит":
                c = self._contains(cell, f.get(key))
                ok = None if c is None else not c
            elif col in ("Толщина от", "Толщина до"):
                try:
                    t = float(f.get("thick") or 0)
                    lim = float(str(cell).replace(",", "."))
                except (TypeError, ValueError):
                    ok = None
                else:
                    ok = None if t <= 0 else (t >= lim if col == "Толщина от" else t <= lim)
            elif col in ("Стена-витраж", "Внутри витража", "Створка с дверью"):
                want, have = as_bool(cell), as_bool(f.get(key))
                ok = None if have is None else (want == have)
            else:  # «Условие по параметру»: «Параметр=значение; Другой=значение»
                ok = True
                for part in re.split(r"[;\n]", str(cell)):
                    if "=" not in part:
                        continue
                    name, val = [x.strip() for x in part.split("=", 1)]
                    r = self._match_list(val.replace("|", ","), f.get(name))
                    if r is False:
                        ok = False
                        break
                    if r is None:
                        ok = None
            if ok is False:
                return False
            if ok is None:
                unknown = True
        return None if unknown else True

    # ---------- применение ----------

    def apply(self, f: dict, param: str):
        """(значение, правило) по первому подходящему правилу или (None, None)."""
        for q in self.rules:
            if q.param != param or q.mode == MODE_LEARN:
                continue
            if self.check(q, f) is True:
                v = self.render(q.value, f)
                if v.strip() == "":   # шаблон {…} без данных — правило не применимо
                    continue
                return self.to_code(param, v, q), q
        return None, None

    def to_code(self, param: str, value: str, rule: Rule | None = None) -> str:
        """Для параметров с классификатором: наименование → код. Код оставляем как есть."""
        sheet = self.clf_sheet.get(param)
        if not sheet or sheet not in self.clf_names or param in self.code_of:
            return value
        if value in self.clf_names[sheet] or value.strip() in ("", "-") or norm(value) == "исключить":
            return value
        codes = self.clf_by_name[sheet].get(norm(value), [])
        where = f" (строка {rule.row})" if rule else ""
        if len(codes) == 1:
            return codes[0]
        if len(codes) > 1:
            self.warnings.add(f"«{value}»{where}: в классификаторе несколько кодов {', '.join(codes)} — взят первый, лучше указать код")
            return codes[0]
        self.warnings.add(f"«{value}»{where}: нет в классификаторе «{sheet}»")
        return value

    def name_of(self, param: str, code) -> str | None:
        """Наименование для параметра-наименования по его коду."""
        sheet = self.clf_sheet.get(param)
        if code is None or not sheet or sheet not in self.clf_names:
            return None
        return self.clf_names[sheet].get(str(code).strip()) or ("-" if str(code).strip() == "-" else None)

    @staticmethod
    def render(value: str, f: dict) -> str:
        """Значение может ссылаться на признак: «{thick}», «{space_name}»."""
        return re.sub(r"\{([^}]+)\}", lambda m: str(f.get(m.group(1).strip(), "")), value)

    def apply_all(self, f: dict, fixed: dict | None = None) -> dict:
        """Проходит параметры по порядку; найденные значения сразу доступны следующим правилам.
        fixed — значения, заданные пользователем (например, исправленный IfcExportAs):
        они не пересчитываются, а следующие шаги опираются на них."""
        f = dict(f)
        fixed = fixed or {}
        out = {}
        for p in self.order:
            if p in fixed and fixed[p] not in (None, ""):
                v, q = fixed[p], "fixed"
            elif p in self.code_of:               # наименование — по коду из классификатора
                v, q = self.name_of(p, f.get(self.code_of[p])), None
            else:
                v, q = self.apply(f, p)
            out[p] = (v, q)
            if v is not None:
                f[p] = v
        return out
