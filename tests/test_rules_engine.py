"""Таблица правил: несколько ключевых правил из схемы должны срабатывать."""
from rules_engine import RuleSet


def apply(rs, **f):
    return {p: v for p, (v, q) in rs.apply_all(f).items()}


def test_table_loads(rules_path):
    rs = RuleSet(rules_path)
    assert rs.rules, "в таблице нет правил"
    assert rs.order[0] == "Исключить элемент"
    assert "IfcExportAs" in rs.order


def test_file_types(rules_path):
    rs = RuleSet(rules_path)
    assert rs.file_type("Проект_ФСД-АР_R22") == "фасад"
    assert rs.file_type("Проект_П-АР") == "паркинг"
    assert rs.file_type("Проект_АР-Р") == "план"
    assert rs.file_type("что-то другое") == "план"      # «*» — по умолчанию


def test_window_with_door_leaf_is_balcony_block(rules_path):
    rs = RuleSet(rules_path)
    r = apply(rs, file="АР-Р", file_type="план", revit_category="Окна", ifc_class="IfcWindow",
              type_full="Окно:ОК-1", has_door_leaf="да")
    assert r["IfcExportAs"] == "IfcWindow"
    assert r["RUS_MSSK_Element_Code"] == "ЭЛ 30 18 09"
    assert r["RUS_MSSK_Material_Code"] == "СТ 00 70"          # окно — всегда стекло


def test_thin_wall_in_plan_is_partition(rules_path):
    rs = RuleSet(rules_path)
    r = apply(rs, file="АР-Р", file_type="план", revit_category="Стены", ifc_class="IfcWall",
              type_full="Базовая стена:Газобетон 100", thick=100, in_curtain_wall="нет", is_curtain_wall="нет")
    assert r["IfcExportAs"] == "IfcWall"
    assert r["RUS_MSSK_Element_Code"] == "ЭЛ 30 10 20"


def test_openings_are_excluded(rules_path):
    rs = RuleSet(rules_path)
    r = apply(rs, revit_category="Двери", ifc_class="IfcDoor", type_full="…Проём:П-1")
    assert str(r["Исключить элемент"]).lower() == "да"


def test_stair_cell_room(rules_path):
    rs = RuleSet(rules_path)
    r = apply(rs, revit_category="Помещения", ifc_class="IfcSpace", type_full="Помещения:ЛК", space_name="ЛК")
    assert r["RUS_MSSK_SpaceAndZone_Code"] == "ПЗ 31 07 08"
