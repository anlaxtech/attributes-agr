"""
Разметка помещений и зон для обучения — labels_spaces.xlsx.

Запуск (после ifc_to_dataset.py, программа обучения делает это сама):
    python build_space_labels.py выгрузка/spaces.csv Классификатор_Помещения_и_зоны_МССК.txt labels_spaces.xlsx

Одна строка = помещение или зона с одинаковыми видом, категорией, именем, назначением и типом зоны.
Редактировать: status, code_final, zone_final, residential_final, floating_final, comment.
Повторный запуск сохраняет ваши правки и добавляет новые строки.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

KEY = ["space_kind", "revit_category", "space_name", "space_purpose", "zone_type"]
# целевой столбец разметки ← колонка выгрузки IFC
TARGETS = {
    "code_final": "y_space_code",
    "zone_final": "y_zone",
    "residential_final": "y_residential",
    "floating_final": "y_floating_floor",
}
# какой параметр АГР обучает каждый столбец (для сервиса)
PARAM_OF = {
    "code_final": "RUS_MSSK_SpaceAndZone_Code",
    "zone_final": "RUS_Zone",
    "residential_final": "RUS_ResidentialRoom",
    "floating_final": "RUS_GroundFloor",
}
USER_COLS = ["status", *TARGETS, "comment"]
BOOL_COLS = {"residential_final", "floating_final"}
STATUSES = ["проверить", "нет кода", "ок", "проверено", "исключить"]


def yes_no(v: str) -> str:
    n = str(v).strip().lower()
    return {"true": "Да", "false": "Нет", "да": "Да", "нет": "Нет", "1": "Да", "0": "Нет"}.get(n, str(v).strip())


def load_classifier(path) -> pd.DataFrame:
    if not path or not Path(path).exists():
        return pd.DataFrame(columns=["code", "name", "level"])
    c = pd.read_csv(path, sep="\t", encoding="utf-16", header=None, dtype=str).iloc[:, :3]
    c.columns = ["code", "name", "level"]
    return c.apply(lambda s: s.str.strip()).dropna(subset=["code"])


def build(spaces_csv) -> pd.DataFrame:
    s = pd.read_csv(spaces_csv, dtype=str, encoding="utf-8-sig").fillna("")
    s["n"] = pd.to_numeric(s.get("n", 1), errors="coerce").fillna(1).astype(int)
    for c in KEY + list(TARGETS.values()):
        if c not in s:
            s[c] = ""
    for col in ("y_residential", "y_floating_floor"):
        s[col] = s[col].map(lambda v: yes_no(v) if v else "")

    def variants(x):
        return ", ".join(sorted({v for v in x if v}))

    agg = {"n": ("n", "sum"), "files": ("file", variants)}
    agg.update({f"{t}_ifc": (src, variants) for t, src in TARGETS.items()})
    g = s.groupby(KEY, dropna=False).agg(**agg).reset_index()

    notes = []
    for t in TARGETS:
        vals = g[f"{t}_ifc"].str.split(", ")
        g[t] = vals.map(lambda v: v[0] if len(v) == 1 and v[0] else "")
        bad = vals.map(len) > 1
        notes.append(bad.map(lambda b, t=t: f"{t}: в IFC разные значения" if b else ""))
    g["auto_note"] = pd.concat(notes, axis=1).apply(lambda r: "; ".join(x for x in r if x), axis=1)
    g["status"] = "ок"
    g.loc[g.auto_note != "", "status"] = "проверить"
    g.loc[g.code_final == "", "status"] = g.loc[g.code_final == "", "status"].where(
        g.space_kind == "зона", "нет кода")
    g["comment"] = ""
    return g


def merge_with_existing(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    if not path.exists():
        return new
    old = pd.read_excel(path, sheet_name="Помещения", dtype=str).fillna("")
    old = old.drop_duplicates(KEY)
    m = new.merge(old[KEY + USER_COLS], on=KEY, how="left", suffixes=("", "_old"), indicator=True)
    kept = m["_merge"] == "both"
    for c in USER_COLS:
        m.loc[kept, c] = m.loc[kept, c + "_old"]
    m = m.drop(columns=[c + "_old" for c in USER_COLS] + ["_merge"])
    gone = old.merge(new[KEY], on=KEY, how="left", indicator=True)
    gone = gone[gone["_merge"] == "left_only"].drop(columns="_merge")
    if len(gone):
        gone["auto_note"] = "нет в текущей выгрузке"
        m = pd.concat([m, gone[[c for c in m.columns if c in gone.columns]]], ignore_index=True)
    print(f"помещения: сохранено правок {int(kept.sum())}, новых строк {int((~kept).sum())}")
    return m


def write_xlsx(df: pd.DataFrame, clf: pd.DataFrame, path: Path):
    order = {s: i for i, s in enumerate(STATUSES)}
    df = df.sort_values(["status", "space_kind", "space_purpose", "space_name"],
                        key=lambda s: s.map(order) if s.name == "status" else s)
    cols = ["status", "space_kind", "revit_category", "space_name", "space_purpose", "zone_type",
            "code_final", "code_name", "zone_final", "residential_final", "floating_final", "comment",
            "auto_note", "n", "code_final_ifc", "zone_final_ifc", "residential_final_ifc",
            "floating_final_ifc", "files"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Помещения"
    ws.append(cols)
    n_clf = len(clf) + 1
    for i, r in enumerate(df.to_dict("records"), start=2):
        row = []
        for c in cols:
            if c == "code_name":
                row.append(f'=IFERROR(VLOOKUP(G{i},Классификатор!$A$2:$B${n_clf},2,FALSE),"")')
            else:
                v = r.get(c, "")
                row.append("" if v is None or (isinstance(v, float) and pd.isna(v)) else v)
        ws.append(row)
    last = max(ws.max_row, 2) + 300
    bold = Font(name="Arial", bold=True, size=10)
    edit = PatternFill("solid", fgColor="FFF2CC")
    widths = {"space_name": 32, "space_purpose": 16, "code_name": 32, "auto_note": 40, "files": 40,
              "comment": 28}
    for j, c in enumerate(cols, 1):
        h = ws.cell(1, j)
        h.font = bold
        h.alignment = Alignment(wrap_text=True)
        if c in USER_COLS:
            h.fill = edit
        ws.column_dimensions[get_column_letter(j)].width = widths.get(c, 14)
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions

    def dv(formula, col):
        d = DataValidation(type="list", formula1=formula, allow_blank=True)
        ws.add_data_validation(d)
        d.add(f"{col}2:{col}{last}")
    dv('"' + ",".join(STATUSES) + '"', "A")
    dv(f"Классификатор!$A$2:$A${n_clf}", "G")
    dv('"Да,Нет"', "J")
    dv('"Да,Нет"', "K")
    for st, color in [("проверить", "FCE5CD"), ("нет кода", "EFEFEF"), ("проверено", "D9EAD3"),
                      ("исключить", "D9D9D9")]:
        ws.conditional_formatting.add(f"A2:S{last}", FormulaRule(
            formula=[f'$A2="{st}"'], fill=PatternFill("solid", fgColor=color)))

    wc = wb.create_sheet("Классификатор")
    wc.append(["code", "name", "level"])
    for r in clf.itertuples(index=False):
        wc.append([r.code, r.name, r.level])
    wc.column_dimensions["A"].width = 18
    wc.column_dimensions["B"].width = 70
    wb.save(path)


def main(spaces_csv, clf_path, out_path):
    out = Path(out_path)
    df = merge_with_existing(build(spaces_csv), out)
    write_xlsx(df, load_classifier(clf_path), out)
    print(f"{out}: {len(df)} строк")
    print(df.status.value_counts().to_string())


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
