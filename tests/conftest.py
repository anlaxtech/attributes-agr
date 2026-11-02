import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

RULES = ROOT / "rules" / "Правила_АГР.xlsx"


@pytest.fixture
def rules_path():
    return RULES


@pytest.fixture
def labels_path(tmp_path):
    """Маленькая искусственная разметка элементов — чтобы сервис мог обучить модель."""
    rows = []
    for i in range(6):
        rows.append(("Двери", "IfcDoor", f"…Дверь:Сталь {860 + i}х2080h", "ЭЛ 30 18 30 30", "Сталь"))
        rows.append(("Двери", "IfcDoor", f"…Дверь:Дерево {760 + i}х2080h", "ЭЛ 30 18 30 20", "Древесина"))
        rows.append(("Окна", "IfcWindow", f"…Окно:ОК-{i} 1200х1500", "ЭЛ 30 18 40", "Стекло"))
    d = pd.DataFrame(rows, columns=["revit_category", "ifc_class", "type_full", "code_final", "materials"])
    d["status"] = "проверено"
    d["parent_class"] = ""
    d["layers_mm"] = ""
    d["IsExternal"] = ""
    d["LoadBearing"] = ""
    d["has_door_leaf"] = ""
    d["files"] = "test.ifc"
    path = tmp_path / "labels.xlsx"
    with pd.ExcelWriter(path) as xw:
        d.to_excel(xw, sheet_name="Разметка", index=False)
    return path
