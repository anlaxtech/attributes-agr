"""Сервис: запускается, отдаёт классификаторы, предсказывает, проверяет токен."""
import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def make_client(monkeypatch, rules_path, labels_path, tmp_path):
    def make(token=""):
        monkeypatch.setattr(sys, "argv", ["service.py"])
        monkeypatch.setenv("AGR_RULES", str(rules_path))
        monkeypatch.setenv("AGR_LABELS", str(labels_path))
        monkeypatch.setenv("AGR_SPACE_LABELS", str(tmp_path / "нет.xlsx"))
        monkeypatch.setenv("AGR_RELOAD_SEC", "0")
        monkeypatch.setenv("AGR_TOKEN", token)
        import service
        importlib.reload(service)
        return TestClient(service.app)
    return make


ITEMS = [
    {"id": "door", "features": {"file": "АР-Р", "revit_category": "Двери", "ifc_class": "IfcDoor",
                                "type_full": "…Дверь:Сталь 900х2080h", "materials": "Сталь"}},
    {"id": "window", "features": {"file": "АР-Р", "revit_category": "Окна", "ifc_class": "IfcWindow",
                                  "type_full": "…Окно:ОК-9", "has_door_leaf": "True"}},
    {"id": "opening", "features": {"file": "АР-Р", "revit_category": "Двери", "ifc_class": "IfcDoor",
                                   "type_full": "…Проём:П-1"}},
]


def test_health_and_predict(make_client):
    with make_client() as c:
        h = c.get("/health").json()
        assert h["ok"] and h["mode"] == "hybrid"
        cl = c.get("/classifiers").json()
        assert "Кл. Элементы" in cl["classifiers"]
        res = {r["id"]: r for r in c.post("/predict_all", json={"items": ITEMS}).json()}
        assert res["window"]["values"]["RUS_MSSK_Element_Code"]["value"] == "ЭЛ 30 18 09"
        # правило «сверить с моделью»: значение из правила, источник — правило
        assert "правило" in res["window"]["values"]["RUS_MSSK_Element_Code"]["source"]
        assert res["door"]["values"]["RUS_MSSK_Element_Code"]["value"].startswith("ЭЛ 30 18 30")
        assert res["opening"]["excluded"]


def test_fixed_value_is_kept(make_client):
    item = dict(ITEMS[1], fixed={"RUS_MSSK_Element_Code": "ЭЛ 30 18 40"})
    with make_client() as c:
        v = c.post("/predict_all", json={"items": [item]}).json()[0]["values"]["RUS_MSSK_Element_Code"]
        assert v["value"] == "ЭЛ 30 18 40" and v["status"] == "проверено"


def test_token(make_client):
    with make_client(token="secret") as c:
        assert c.get("/health").status_code == 200                       # health — без токена
        assert c.get("/classifiers").status_code == 401
        assert c.get("/classifiers", headers={"X-AGR-Token": "secret"}).status_code == 200


def test_corrections(make_client, labels_path):
    row = {"user": "test", "project": "p", "param": "RUS_MSSK_Element_Code", "value": "ЭЛ 30 18 40",
           "edited": "да", "type_full": "…Окно:ОК-9"}
    with make_client() as c:
        assert c.post("/corrections", json={"rows": [row]}).json()["saved"] == 1
    assert (labels_path.parent / "corrections.csv").exists()
