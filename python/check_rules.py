"""
Проверка таблицы правил на выданных IFC: где правила совпадают с тем, что уже выдано,
где расходятся, и что остаётся на обучение.

Запуск:
    python check_rules.py Правила_АГР.xlsx папка_с_ifc  [папка_результата]

Результат — rules_report.xlsx:
    Сводка        — по каждому параметру: сколько элементов покрыли правила и сколько совпало с IFC
    По правилам   — каждое правило: сколько раз сработало, % совпадений, с чем расходится
    Расхождения   — типы, где правило дало не то, что стоит в выданном IFC (их стоит просмотреть)
    Без правила   — что остаётся модели: параметр, класс, тип, значение в IFC
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

from ifc_to_dataset import extract_files
from rules import thickness
from rules_engine import RuleSet, as_bool, norm

SP, ZG, ZN = "IfcSpace (помещение)", "IfcSpace (зона общая)", "IfcSpace (зона ГНС)"

def yesno(v):
    b = as_bool(v)
    return None if b is None else ("да" if b else "нет")


def features(df: pd.DataFrame, rs: RuleSet) -> pd.DataFrame:
    d = df.copy()
    for c in ("space_kind", "space_name", "space_purpose", "zone_type", "parent_class", "has_door_leaf",
              "y_space_code", "y_zone", "y_studio", "y_basement", "y_floating_floor", "y_residential",
              "y_group_number"):
        if c not in d:
            d[c] = None
    d["file_type"] = d.file.map(rs.file_type)
    d["thick"] = d.apply(lambda r: thickness(r.fillna("")), axis=1)
    d["in_curtain_wall"] = (d.parent_class == "IfcCurtainWall").map({True: "да", False: "нет"})
    fam = d.type_full.fillna("").str.split(":").str[0].str.strip("… ").str.lower()
    d["is_curtain_wall"] = (fam == "витраж").map({True: "да", False: "нет"})
    d["has_door_leaf"] = d.has_door_leaf.map(yesno)
    # истинные значения из выданного IFC
    gns = d.type_full.fillna("").str.lower().str.contains("гнс")
    d["t_IfcExportAs"] = d.ifc_class
    d.loc[d.space_kind == "помещение", "t_IfcExportAs"] = SP
    d.loc[(d.space_kind == "зона") & gns, "t_IfcExportAs"] = ZN
    d.loc[(d.space_kind == "зона") & ~gns, "t_IfcExportAs"] = ZG
    for p, col in rs.truth_col.items():
        if p != "IfcExportAs":
            d["t_" + p] = d[col] if col in d else None
    return d


def same(a, b) -> bool:
    if as_bool(a) is not None and as_bool(b) is not None:
        return as_bool(a) == as_bool(b)
    try:
        return abs(float(str(a).replace(",", ".")) - float(str(b).replace(",", "."))) < 0.5
    except ValueError:
        pass
    return norm(a) == norm(b)


def run(rules_path, ifc_dir, out_dir=".", log=print):
    rs = RuleSet(rules_path)
    files = sorted(Path(ifc_dir).rglob("*.ifc")) if Path(ifc_dir).is_dir() else [Path(ifc_dir)]
    out = Path(out_dir)
    df = extract_files(files, out / "cache", log=log, workers=max(1, min(4, (os.cpu_count() or 2) - 1)))
    d = features(df, rs)

    keys = ["file_type", "revit_category", "ifc_class", "parent_class", "type_full", "materials", "layers_mm",
            "thick", "in_curtain_wall", "is_curtain_wall", "has_door_leaf", "space_kind", "space_name",
            "space_purpose"] + [c for c in d.columns if c.startswith("t_")]
    g = d[keys].astype(object).where(d[keys].notna(), None)
    g = g.groupby(keys, dropna=False).size().reset_index(name="n")
    log(f"элементов: {len(d)}, уникальных сочетаний: {len(g)}, правил: {len(rs.rules)}")

    rows = []
    for _, r in g.iterrows():
        f = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        res = rs.apply_all(f)
        for p in rs.order:
            truth = f.get("t_" + p)
            v, q = res.get(p, (None, None))
            if truth is None and v is None:
                continue
            how = "по коду" if p in rs.code_of else (q.label if q else None)
            rows.append({"Параметр": p, "IFC-класс": res.get("IfcExportAs", (None,))[0] or f["ifc_class"],
                         "Категория": f["revit_category"], "Тип файла": f["file_type"], "Тип": f["type_full"],
                         "По правилу": v, "В IFC": truth, "Правило": how,
                         "Строка": q.row if q else None, "Элементов": f["n"],
                         "Совпало": None if (v is None or truth is None) else same(v, truth)})
    res = pd.DataFrame(rows)

    summ = []
    for p in rs.order:
        x = res[res["Параметр"] == p]
        if x.empty:
            continue
        fired = x[x["По правилу"].notna()]
        checked = fired[fired["Совпало"].notna()]
        summ.append({"Параметр": p, "Элементов": x["Элементов"].sum(),
                     "Покрыто правилами": f'{fired["Элементов"].sum() / x["Элементов"].sum():.0%}',
                     "Совпало с IFC": (f'{(checked["Элементов"] * checked["Совпало"]).sum() / checked["Элементов"].sum():.0%}'
                                       if len(checked) else "—"),
                     "Расхождений (типов)": int((checked["Совпало"] == False).sum()),  # noqa: E712
                     "На обучение (элементов)": x[x["По правилу"].isna()]["Элементов"].sum()})
    summ = pd.DataFrame(summ)

    fired = res[res["Строка"].notna()]
    res.loc[res["Правило"] == "по коду", "Строка"] = None
    by_rule = (fired.assign(ok=fired["Совпало"].fillna(False) * fired["Элементов"],
                            chk=fired["Совпало"].notna() * fired["Элементов"])
               .groupby(["Строка", "Параметр", "Правило", "По правилу"])
               .agg(сработало=("Элементов", "sum"), проверено=("chk", "sum"), совпало=("ok", "sum"),
                    расходится_с=("В IFC", lambda s: ", ".join(sorted({str(v) for v in s.dropna()}))[:200]))
               .reset_index())
    by_rule["% совпадений"] = (by_rule.совпало / by_rule.проверено.where(by_rule.проверено > 0)).map(
        lambda v: "—" if pd.isna(v) else f"{v:.0%}")
    by_rule = by_rule.sort_values(["Параметр", "Строка"])

    diffs = res[res["Совпало"] == False].sort_values(["Параметр", "IFC-класс", "Тип"])  # noqa: E712
    nolearn = res[res["По правилу"].isna() & res["В IFC"].notna()].sort_values(["Параметр", "IFC-класс", "Тип"])

    path = out / "rules_report.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="Сводка", index=False)
        by_rule.to_excel(xw, sheet_name="По правилам", index=False)
        diffs.drop(columns=["Совпало"]).to_excel(xw, sheet_name="Расхождения", index=False)
        nolearn.drop(columns=["Совпало", "По правилу", "Правило", "Строка"]).to_excel(xw, sheet_name="Без правила", index=False)
    _widths(path)
    if rs.warnings:
        log("\nПредупреждения по таблице правил:")
        for w in sorted(rs.warnings):
            log("  " + w)
    log("\n" + summ.to_string(index=False))
    log(f"\nотчёт: {path}")
    return path


def _widths(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Font
    wb = load_workbook(path)
    for ws in wb:
        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in col[:200])
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, w + 2))
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    wb.save(path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    run(*sys.argv[1:4])
