"""
Сводит правки коллег (data/corrections.csv с сервера) в вашу разметку и отчёт.

Запуск:
    python merge_corrections.py corrections.csv labels.xlsx

Что делает:
    1. Код «Элементы» (RUS_MSSK_Element_Code) — в labels.xlsx:
       • типа ещё нет в разметке → добавляется строка со статусом «проверить»;
       • код коллег отличается от вашего → строка получает «проверить» и подсказку в auto_note.
       Строки, которые вы уже подтвердили («проверено» + комментарий), не трогаются —
       так можно отклонить правку коллег, и она не будет всплывать снова.
    2. Все параметры — в corrections_report.xlsx: что, где и сколько раз люди меняли.
       Это подсказки для таблицы правил (например, где модель или правило систематически ошибаются).

Голос = уникальная пара (пользователь, проект): повторные записи одного человека не множатся.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

EL_CODE = "RUS_MSSK_Element_Code"
KEY = ["revit_category", "ifc_class", "parent_class", "type_full"]


def load(path) -> pd.DataFrame:
    c = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for col in ("user", "project", "edited", "param", "value", "source", "revit_category", "ifc_class",
                "ifc_export", "parent_class", "type_full", "space_name", "space_purpose", "zone_type"):
        if col not in c:
            c[col] = ""
    # IFC-класс — итоговый IfcExportAs (без уточнения в скобках), иначе — как прислал плагин
    c["ifc_class"] = c.ifc_export.str.split(" (", regex=False).str[0].where(c.ifc_export != "", c.ifc_class)
    return c


def votes(c: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Уникальные голоса (пользователь+проект) за каждое значение."""
    v = c.drop_duplicates(keys + ["value", "user", "project"])
    g = v.groupby(keys + ["value"]).agg(голосов=("user", "size"),
                                       авторы=("user", lambda s: ", ".join(sorted(set(s)))),
                                       проекты=("project", lambda s: ", ".join(sorted(set(s))))).reset_index()
    edited = c[c.edited == "да"].drop_duplicates(keys + ["value", "user", "project"])
    g = g.merge(edited.groupby(keys + ["value"]).size().rename("из них_исправлений").reset_index(),
                on=keys + ["value"], how="left").fillna({"из них_исправлений": 0})
    return g.sort_values(keys + ["голосов"], ascending=[True] * len(keys) + [False])


def merge_into_labels(c: pd.DataFrame, labels_path: Path) -> int:
    from openpyxl import load_workbook

    el = c[c.param == EL_CODE]
    if el.empty:
        return 0
    g = votes(el, KEY)
    top = g.drop_duplicates(KEY)                     # самое популярное значение для каждого типа
    lab = pd.read_excel(labels_path, sheet_name="Разметка", dtype=str).fillna("")

    wb = load_workbook(labels_path)
    ws = wb["Разметка"]
    head = [x.value for x in ws[1]]
    col = {h: i + 1 for i, h in enumerate(head)}
    index = {tuple(r[k] for k in KEY): i + 2 for i, r in lab.iterrows()}   # строка в Excel
    changed = 0
    for _, t in top.iterrows():
        key = tuple(t[k] for k in KEY)
        others = g[(g[KEY] == pd.Series(key, index=KEY)).all(axis=1)]
        note = "коллеги: " + "; ".join(f"{r.value} ×{r.голосов} ({r.авторы})" for r in others.itertuples())
        if key in index:
            row = index[key]
            cur = ws.cell(row, col["code_final"]).value or ""
            status = ws.cell(row, col["status"]).value or ""
            comment = ws.cell(row, col["comment"]).value or ""
            if cur == t.value or (status == "проверено" and comment.strip()):
                continue
            ws.cell(row, col["status"]).value = "проверить"
            ws.cell(row, col["auto_note"]).value = note
        else:
            new = ws.max_row + 1
            values = {"status": "проверить", "code_final": t.value, "revit_category": t.revit_category,
                      "ifc_class": t.ifc_class, "parent_class": t.parent_class, "type_full": t.type_full,
                      "auto_note": note + " — новый тип из проектов"}
            src = el[(el[KEY] == pd.Series(key, index=KEY)).all(axis=1)].iloc[0]
            for k in ("materials", "layers_mm", "IsExternal", "has_door_leaf"):
                values[k] = src.get(k, "")
            for k, v in values.items():
                if k in col:
                    ws.cell(new, col[k]).value = v
            if "name_final" in col:   # формула наименования — как в строке выше, но для новой строки
                prev = ws.cell(new - 1, col["name_final"]).value
                if isinstance(prev, str) and prev.startswith("="):
                    ws.cell(new, col["name_final"]).value = re.sub(
                        rf"(?<![$\w])([A-Z]{{1,2}}){new - 1}(?!\d)", rf"\g<1>{new}", prev)
        changed += 1
    wb.save(labels_path)
    return changed


SPACE_COL = {"RUS_MSSK_SpaceAndZone_Code": "code_final", "RUS_Zone": "zone_final",
             "RUS_ResidentialRoom": "residential_final", "RUS_GroundFloor": "floating_final"}
SPACE_KEY = ["space_kind", "revit_category", "space_name", "space_purpose", "zone_type"]


def merge_into_spaces(c: pd.DataFrame, path: Path) -> int:
    """Правки по помещениям → labels_spaces.xlsx (статус «проверить» и подсказка)."""
    from openpyxl import load_workbook
    sp = c[c.param.isin(SPACE_COL) & c.ifc_class.str.startswith("IfcSpace")].copy()
    if sp.empty or not path.exists():
        return 0
    if "zone_type" not in sp:
        sp["zone_type"] = ""
    sp["space_kind"] = sp.revit_category.str.lower().str.contains("зон").map({True: "зона", False: "помещение"})
    wb = load_workbook(path)
    ws = wb["Помещения"]
    head = [x.value for x in ws[1]]
    col = {h: i + 1 for i, h in enumerate(head)}
    rows = {tuple(str(ws.cell(r, col[k]).value or "") for k in SPACE_KEY): r for r in range(2, ws.max_row + 1)}
    changed = 0
    for param, target in SPACE_COL.items():
        g = votes(sp[sp.param == param], SPACE_KEY)
        for _, t in g.drop_duplicates(SPACE_KEY).iterrows():
            key = tuple(t[k] for k in SPACE_KEY)
            note = f"коллеги ({param}): {t.value} ×{t.голосов} ({t.авторы})"
            r = rows.get(key)
            if r is None:
                r = ws.max_row + 1
                for k, v in zip(SPACE_KEY, key):
                    ws.cell(r, col[k]).value = v
                ws.cell(r, col[target]).value = t.value
                ws.cell(r, col["status"]).value = "проверить"
                ws.cell(r, col["auto_note"]).value = note + " — новое из проектов"
                rows[key] = r
                changed += 1
                continue
            cur = str(ws.cell(r, col[target]).value or "")
            status = str(ws.cell(r, col["status"]).value or "")
            comment = str(ws.cell(r, col["comment"]).value or "")
            if cur == t.value or (status == "проверено" and comment.strip()):
                continue
            ws.cell(r, col["status"]).value = "проверить"
            ws.cell(r, col["auto_note"]).value = note
            changed += 1
    wb.save(path)
    return changed


def main(corr_path, labels_path):
    c = load(corr_path)
    print(f"правок: {len(c)}, людей: {c.user.nunique()}, проектов: {c.project.nunique()}")
    n = merge_into_labels(c, Path(labels_path))
    print(f"в labels.xlsx отмечено или добавлено типов: {n}")
    sp = Path(labels_path).with_name("labels_spaces.xlsx")
    n = merge_into_spaces(c, sp)
    if sp.exists():
        print(f"в labels_spaces.xlsx отмечено или добавлено строк: {n}")

    keys = ["param", "ifc_class", "revit_category", "type_full"]
    report = votes(c, keys)
    conflicts = report[report.duplicated(keys, keep=False)]
    out = Path(labels_path).with_name("corrections_report.xlsx")
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        report.to_excel(xw, sheet_name="Все правки", index=False)
        conflicts.to_excel(xw, sheet_name="Коллеги не согласны", index=False)
        (c[c.edited == "да"].groupby(["param", "source"]).size().rename("исправлений").reset_index()
         .sort_values("исправлений", ascending=False)
         .to_excel(xw, sheet_name="Где чаще исправляют", index=False))
    print(f"отчёт: {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
