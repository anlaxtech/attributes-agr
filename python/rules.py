"""
Правила классификации «Элементы», которые известны заранее.
Правило срабатывает раньше модели: если оно подходит, код берётся из правила.

Чтобы добавить правило, допишите функцию в RULES: она получает строку типа
(revit_category, ifc_class, parent_class, type_full, thick, IsExternal, has_door_leaf)
и возвращает код или None.
"""
from __future__ import annotations

import re


def thickness(row) -> float:
    """Толщина: сумма слоёв, а если слоёв нет — отдельное число из имени типа
    («Газобетон 100», «Кирпич_250», «Железобетон 450 мм»). Размеры вида 860х2080 не берём."""
    layers = str(getattr(row, "layers_mm", "") or "")
    if layers and layers != "nan":
        try:
            return sum(float(x) for x in layers.split("+"))
        except ValueError:
            pass
    name = str(row.type_full).split(":", 1)[-1]
    nums = re.findall(r"(?<![\dхx×.,])(\d{2,3})(?![\dхx×.,])", name, flags=re.I)
    return float(nums[0]) if nums else 0.0


def _name(r) -> str:
    return str(r.type_full).lower()


def _true(v) -> bool:
    return str(v).strip().lower() == "true"


# ---------- правила (порядок важен: срабатывает первое подходящее) ----------

def window_door_leaf(r):
    """Окно с вложенной дверной створкой — балконный блок, без неё — окно."""
    if r.ifc_class == "IfcWindow" and str(r.has_door_leaf).lower() in ("true", "false"):
        return "ЭЛ 30 18 09" if _true(r.has_door_leaf) else "ЭЛ 30 18 40"


def gates(r):
    """Ворота — всегда ворота с автоматическим механизмом открывания."""
    if r.revit_category == "Двери" and "ворот" in _name(r):
        return "ЭЛ 30 18 20 02"


def steel_door(r):
    """Стальная дверь — всегда входная."""
    if r.revit_category == "Двери" and "стал" in _name(r) and "ворот" not in _name(r):
        return "ЭЛ 30 18 30 30"


def curtain_panel(r):
    """Любая панель (IfcPlate: стеклопакеты, сэндвичи, решётки, стены-панели) —
    панель навесного фасада. Принято для единообразия разметки разных авторов."""
    if r.ifc_class == "IfcPlate":
        return "ЭЛ 30 10 61 01"


def stair_parts(r):
    """Категория определяет код: марш — лестничный марш, площадка — лестничная площадка."""
    return {"Лестницы: Марши": "ЭЛ 30 24 10",
            "Лестницы: Площадки": "ЭЛ 30 24 20"}.get(r.revit_category)


FACADE_WORDS = ("фасад", "утепл", "облиц", "панел", "карниз", "сфб", "клинкер", "керам", "наружн")


def facade_panel_wall(r):
    """Стена с «панел» в имени (не в витраже) — фасадная панель."""
    if (r.revit_category == "Стены" and r.ifc_class == "IfcWall" and not r.parent_class
            and "панел" in _name(r)):
        return "ЭЛ 30 10 75"


def _plain_wall(r) -> bool:
    """Обычная стена: категория «Стены», IfcWall, не в витраже, не фасадный слой и не карниз."""
    return (r.revit_category == "Стены" and r.ifc_class == "IfcWall" and not r.parent_class
            and not any(w in _name(r) for w in FACADE_WORDS))


def thin_wall_partition(r):
    """Стена тоньше 180 мм — перегородка (кроме фасадных слоёв и наружных стен по имени)."""
    if _plain_wall(r) and 0 < float(r.thick) < 180:
        return "ЭЛ 30 10 20"


def thick_wall(r):
    """Стена от 180 мм — стена."""
    if _plain_wall(r) and 180 <= float(r.thick) < 1000:
        return "ЭЛ 30 10 15"


RULES = [window_door_leaf, gates, steel_door, curtain_panel, stair_parts,
         facade_panel_wall, thin_wall_partition, thick_wall]

RULE_NAMES = {
    "window_door_leaf": "окно: дверная створка → балконный блок",
    "gates": "ворота → с автоматическим механизмом",
    "steel_door": "стальная дверь → входная",
    "curtain_panel": "панель витража → панель навесного фасада",
    "stair_parts": "категория марша/площадки",
    "facade_panel_wall": "«панель» в имени стены → фасадная панель",
    "thin_wall_partition": "стена < 180 мм → перегородка",
    "thick_wall": "стена ≥ 180 мм → стена",
}


def apply_rules(r):
    """(код, название правила) или (None, None)."""
    for rule in RULES:
        code = rule(r)
        if code:
            return code, RULE_NAMES[rule.__name__]
    return None, None
