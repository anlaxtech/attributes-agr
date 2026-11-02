"""
Таблица разметки кода классификатора «Элементы» для обучения.

Запуск (после ifc_to_dataset.py):
    pip install pandas openpyxl
    python build_labels.py out/types.csv Классификатор_Элементы_МГЭ.txt labels.xlsx

Первый запуск создаёт labels.xlsx. Повторные запуски добавляют только новые типы,
а ваши правки (code_final, status, comment) сохраняются.

Что редактировать руками: только колонки code_final, status и comment.
Обучение берёт строки, где заполнен code_final.
"""
from __future__ import annotations  # подсказки типов вида str | None на Python 3.9

import re
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

KEY = ["revit_category", "ifc_class", "parent_class", "type_full"]
USER_COLS = ["code_final", "status", "comment"]
STATUSES = ["проверить", "конфликт", "нет кода", "ок", "проверено", "исключить"]


def load_classifier(path: str) -> pd.DataFrame:
    """Классификатор: код <TAB> наименование <TAB> уровень (файл в UTF-16)."""
    for enc in ("utf-16", "utf-8-sig", "cp1251"):
        try:
            c = pd.read_csv(path, sep="\t", encoding=enc, header=None, dtype=str)
            break
        except (UnicodeError, pd.errors.ParserError):
            continue
    c = c.iloc[:, :3]
    c.columns = ["code", "name", "level"]
    return c.apply(lambda s: s.str.strip()).dropna(subset=["code"])


def norm_name(s: str) -> str:
    """Группа похожих имён: Карниз33:Карниз → карниз:карниз,
    «Дверь однопольная1» → «дверь однопольная», _/-/пробелы → пробел."""
    s = str(s).lower().replace("…", "").replace("ё", "е").replace("c", "с")  # лат. c → кир.
    s = re.sub(r"(?<=[а-яa-z])\d+(?=:)", "", s)
    s = re.sub(r"[\s_\-–]+", " ", s)
    return s.strip(" .")


def resolve_codes(codes: str | float, names: dict) -> tuple[str | None, str, str]:
    """Из «код1, код2» выбирает предложение и статус.
    Общий код, у которого среди вариантов есть более подробный потомок,
    отбрасывается (ЭЛ 30 18 30 + ЭЛ 30 18 30 30 → ЭЛ 30 18 30 30)."""
    if not isinstance(codes, str) or not codes.strip():
        return None, "нет кода", ""
    variants = sorted({c.strip() for c in codes.split(",") if c.strip()})
    unknown = [c for c in variants if c not in names]
    specific = [c for c in variants if not any(o != c and o.startswith(c + " ") for o in variants)]
    note = []
    if unknown:
        note.append("нет в классификаторе: " + ", ".join(unknown))
    if len(specific) < len(variants):
        note.append("общий код уточнён до подробного")
    if len(specific) == 1 and not unknown:
        return specific[0], ("проверить" if note else "ок"), "; ".join(note)
    return None, "конфликт", "; ".join(note + ["варианты: " + ", ".join(specific)])


def build(types_csv: str, clf_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    clf = load_classifier(clf_path)
    names = dict(zip(clf.code, clf.name))
    t = pd.read_csv(types_csv, dtype=str)
    t["parent_class"] = t.parent_class.fillna("")
    if "revit_category" not in t:
        t["revit_category"] = ""
    t["revit_category"] = t.revit_category.fillna("")
    t = t[t.ifc_class.notna()].copy()

    res = t.y_el_code.apply(lambda c: resolve_codes(c, names))
    t["code_proposed"] = [r[0] for r in res]
    t["status"] = [r[1] for r in res]
    t["auto_note"] = [r[2] for r in res]
    t["code_final"] = t.code_proposed
    t["comment"] = ""

    # Группы похожих имён: если внутри группы разные коды — флаг
    t["group"] = (t.revit_category + " | " + t.ifc_class + " | " + t.parent_class + " | "
                  + t.type_full.map(norm_name))
    gcodes = t.groupby("group").code_proposed.agg(lambda s: set(s.dropna()))
    t["group_size"] = t.group.map(t.group.value_counts())
    mixed = t.group.map(lambda g: len(gcodes[g]) > 1)
    t.loc[mixed & (t.status == "ок"), "status"] = "проверить"
    t.loc[mixed, "auto_note"] = (t.loc[mixed, "auto_note"].str.cat(
        t.loc[mixed, "group"].map(lambda g: "в группе похожих разные коды: " + ", ".join(sorted(gcodes[g]))),
        sep="; ").str.strip("; "))

    if "has_door_leaf" not in t:
        t["has_door_leaf"] = ""
    cols = ["status", "code_final", "comment", "revit_category", "ifc_class", "parent_class", "type_full",
            "has_door_leaf", "group", "group_size", "y_el_code", "auto_note", "revit_code", "n_files",
            "n_elements", "materials", "layers_mm", "IsExternal", "LoadBearing", "files"]
    t = t[cols].rename(columns={"y_el_code": "codes_in_ifc"})
    return t, clf


def flag_rules(df: pd.DataFrame, names: dict) -> pd.DataFrame:
    """Сверяет разметку с правилами из rules.py. Где код расходится с правилом —
    статус «проверить» и подсказка в auto_note. Если вы осознанно оставили другой код,
    поставьте «проверено» и напишите причину в comment — такие строки не трогаются."""
    from rules import apply_rules, thickness
    tmp = df.fillna("").copy()
    tmp["thick"] = tmp.apply(thickness, axis=1)
    hits = tmp.apply(apply_rules, axis=1)
    rule_code = hits.map(lambda h: h[0])
    rule_name = hits.map(lambda h: h[1])
    bad = rule_code.notna() & (df.code_final.fillna("") != "") & (rule_code != df.code_final)
    keep = (df.status == "проверено") & (df.comment.fillna("").astype(str).str.strip() != "")
    df.loc[bad & ~keep, "status"] = "проверить"
    note = ("правило «" + rule_name[bad] + "»: ожидается " + rule_code[bad] + " "
            + rule_code[bad].map(names).fillna(""))
    df.loc[bad, "auto_note"] = (df.loc[bad, "auto_note"].fillna("").astype(str)
                                .str.replace(r";?\s*(створки|правило).*$", "", regex=True)
                                + "; " + note).str.strip("; ")
    print(f"строк, где разметка расходится с правилами: {bad.sum()}")
    return df


def merge_with_existing(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    if not path.exists():
        return new
    old = pd.read_excel(path, sheet_name="Разметка", dtype=str).fillna("")
    # Старая разметка без категории Revit: правка типа переносится на все его категории
    key = KEY if "revit_category" in old else [k for k in KEY if k != "revit_category"]
    old = old.drop_duplicates(key)
    m = new.merge(old[key + USER_COLS], on=key, how="left", suffixes=("", "_old"), indicator=True)
    kept = m["_merge"] == "both"
    for c in USER_COLS:
        m.loc[kept, c] = m.loc[kept, c + "_old"]
    if key != KEY:
        # тип разделился на несколько категорий — пометить для проверки
        split = m.duplicated(key, keep=False)
        m.loc[split & m.status.isin(["проверено", "ок"]), "status"] = "проверить"
        m.loc[split, "auto_note"] = "тип встречается в разных категориях Revit — проверьте код для каждой"
    m = m.drop(columns=[c + "_old" for c in USER_COLS] + ["_merge"])
    gone = old.merge(new[key], on=key, how="left", indicator=True)
    gone = gone[gone["_merge"] == "left_only"].drop(columns="_merge")
    if len(gone):
        gone["auto_note"] = "типа больше нет в выгрузке"
        m = pd.concat([m, gone[[c for c in m.columns if c in gone.columns]]], ignore_index=True)
    print(f"сохранено ваших правок: {kept.sum()}, новых строк: {(~kept).sum()}")
    return m


def write_xlsx(df: pd.DataFrame, clf: pd.DataFrame, path: Path):
    order = {s: i for i, s in enumerate(STATUSES)}
    df = df.sort_values(["status", "ifc_class", "group"], key=lambda s: s.map(order) if s.name == "status" else s)

    wb = Workbook()
    ws = wb.active
    ws.title = "Разметка"
    cols = list(df.columns)
    cols.insert(cols.index("code_final") + 1, "name_final")
    ws.append(cols)
    n_clf = len(clf) + 1
    col_of = {name: get_column_letter(j) for j, name in enumerate(cols, start=1)}
    cf, st = col_of["code_final"], col_of["status"]
    for i, row in enumerate(df.itertuples(index=False), start=2):
        vals = list(row)
        vals.insert(cols.index("name_final"),
                    f'=IFERROR(VLOOKUP({cf}{i},Классификатор!$A$2:$B${n_clf},2,FALSE),IF({cf}{i}="","","нет в классификаторе"))')
        ws.append(["" if (isinstance(v, float) and pd.isna(v)) else v for v in vals])

    font, bold = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
    edit_fill = PatternFill("solid", fgColor="FFF2CC")  # жёлтые колонки — редактировать
    for row in ws.iter_rows():
        for cell in row:
            cell.font = font
    for j, name in enumerate(cols, start=1):
        h = ws.cell(1, j)
        h.font = bold
        h.alignment = Alignment(wrap_text=True, vertical="top")
        if name in USER_COLS:
            h.fill = edit_fill
        width = {"type_full": 55, "group": 45, "auto_note": 45, "name_final": 30,
                 "comment": 30, "materials": 35, "files": 40}.get(name, 15)
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    last = ws.max_row

    # Выпадающие списки: статус и код из классификатора
    dv_status = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    dv_code = DataValidation(type="list", formula1=f"Классификатор!$A$2:$A${n_clf}", allow_blank=True,
                             showErrorMessage=True, errorTitle="Код",
                             error="Кода нет в классификаторе МССК")
    ws.add_data_validation(dv_status)
    ws.add_data_validation(dv_code)
    dv_status.add(f"{st}2:{st}{last}")
    dv_code.add(f"{cf}2:{cf}{last}")

    # Подсветка статусов
    for status, color in [("конфликт", "F4CCCC"), ("проверить", "FCE5CD"), ("нет кода", "EFEFEF"),
                          ("проверено", "D9EAD3"), ("исключить", "D9D9D9")]:
        ws.conditional_formatting.add(f"A2:{get_column_letter(len(cols))}{last}",
                                      FormulaRule(formula=[f'${st}2="{status}"'],
                                                  fill=PatternFill("solid", fgColor=color)))

    wc = wb.create_sheet("Классификатор")
    wc.append(["code", "name", "level"])
    for r in clf.itertuples(index=False):
        wc.append([r.code, r.name, int(r.level) if str(r.level).isdigit() else r.level])
    wc.column_dimensions["A"].width = 18
    wc.column_dimensions["B"].width = 70
    for row in wc.iter_rows():
        for cell in row:
            cell.font = font

    wl = wb.create_sheet("Как пользоваться")
    for line in [
        "Редактировать только жёлтые колонки на листе «Разметка»: status, code_final, comment.",
        "code_final — правильный код (выпадающий список из классификатора). name_final подставится сам.",
        "status: «конфликт» и «проверить» — разобрать; после проверки ставьте «проверено».",
        "«исключить» — тип не участвует в обучении (например, сантехника).",
        "group — похожие имена (Карниз1…Карниз51, «Дверь однопольная1» и «Дверь однопольная»).",
        "Отфильтруйте по group, чтобы проставить код сразу всей группе.",
        "Имена типов НЕ исправлять: модель должна учиться на реальных, неаккуратных именах.",
        "При повторном запуске build_labels.py ваши правки сохраняются, добавляются только новые типы.",
    ]:
        wl.append([line])
    wl.column_dimensions["A"].width = 110
    for row in wl.iter_rows():
        for cell in row:
            cell.font = font

    wb.save(path)


def main(types_csv, clf_path, out_path):
    out = Path(out_path)
    df, clf = build(types_csv, clf_path)
    df = merge_with_existing(df, out)
    df = flag_rules(df, dict(zip(clf.code, clf.name)))
    write_xlsx(df, clf, out)
    print(f"{out}: {len(df)} типов")
    print(df.status.value_counts().to_string())


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
