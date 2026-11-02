"""
Первая модель: логистическая регрессия, которая учится, какие слова,
категория и толщина определяют код классификатора.

Запуск:
    python train_model.py labels.xlsx

Что делает:
    1. Проверка на «новых» типах (как в eval_baseline.py, те же 5 частей по группам):
       сравнивает поиск похожего типа и модель.
    2. Обучает модель на всей разметке и сохраняет её в model.joblib (для predict.py).
Ошибки модели — в errors_model.csv.
"""
from __future__ import annotations

import re
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, FunctionTransformer

from build_labels import norm_name
from eval_baseline import load, predict as predict_similar
from rules import apply_rules, thickness


# ---------- признаки ----------

def prepare(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["name"] = d.type_full.map(norm_name)
    d["mats"] = d.materials.str.lower()
    d["thick"] = d.apply(thickness, axis=1)
    d["role"] = d.revit_category + "|" + d.ifc_class + "|" + d.parent_class
    if "has_door_leaf" not in d:
        d["has_door_leaf"] = ""
    for c in ("IsExternal", "LoadBearing", "has_door_leaf"):
        d[c] = d[c].replace("", "нет данных")
    return d


def thick_bins(x):
    """Толщина как набор порогов: ≤60, ≤100, ≤130, ≤160, ≤220, ≤320, ≤500 мм."""
    t = np.asarray(x, dtype=float).reshape(-1, 1)
    edges = np.array([0, 60, 100, 130, 160, 220, 320, 500])
    return np.hstack([(t > 0).astype(float), (t <= edges[1:]).astype(float) * (t > 0)])


def make_model() -> Pipeline:
    features = ColumnTransformer([
        ("words", TfidfVectorizer(analyzer="word", token_pattern=r"[а-яa-z]{3,}", sublinear_tf=True), "name"),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), sublinear_tf=True, max_features=5000), "name"),
        ("mats", TfidfVectorizer(analyzer="word", token_pattern=r"[а-яa-z]{3,}"), "mats"),
        ("role", OneHotEncoder(handle_unknown="ignore"), ["role", "revit_category", "ifc_class",
                                                          "IsExternal", "LoadBearing", "has_door_leaf"]),
        ("thick", FunctionTransformer(thick_bins), "thick"),
    ])
    return Pipeline([("features", features),
                     ("clf", LogisticRegression(C=10, max_iter=3000, class_weight="balanced"))])


def predict_masked(model: Pipeline, train: pd.DataFrame, test: pd.DataFrame):
    """Предсказание с ограничением: только коды, которые в обучении встречались
    у того же IFC-класса (дверь не может получить код стены)."""
    proba = model.predict_proba(test)
    classes = model.classes_
    allowed = train.groupby("ifc_class").code_final.agg(set)
    preds, conf = [], []
    for i, cls in enumerate(test.ifc_class):
        p = proba[i].copy()
        if cls in allowed.index:
            p[~np.isin(classes, list(allowed[cls]))] = 0
        if p.sum() == 0:
            p = proba[i].copy()
        p = p / p.sum()
        preds.append(classes[p.argmax()])
        conf.append(p.max())
    return preds, conf


# ---------- проверка ----------

def main(path):
    d = prepare(load(path))
    print(f"размеченных типов: {len(d)}, кодов: {d.code_final.nunique()}")
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(d.text)

    d["pred_sim"] = d["pred_model"] = None
    d["conf"] = 0.0
    for tr, te in GroupKFold(n_splits=5).split(d, groups=d.group):
        train, test = d.iloc[tr], d.iloc[te]
        d.loc[d.index[te], "pred_sim"] = [r[0] for r in predict_similar(train, test, vec)]
        model = make_model().fit(train, train.code_final)
        preds, conf = predict_masked(model, train, test)
        d.loc[d.index[te], "pred_model"] = preds
        d.loc[d.index[te], "conf"] = conf

    # Итоговая схема: правило, если подходит, иначе модель
    hits = d.apply(apply_rules, axis=1)
    d["rule_code"] = hits.map(lambda h: h[0])
    d["rule"] = hits.map(lambda h: h[1])
    d["pred_final"] = d.rule_code.fillna(d.pred_model)
    d["ok_final"] = d.pred_final == d.code_final
    d.loc[d.rule_code.notna(), "conf"] = 1.0  # правило — полная уверенность
    d["ok_sim"] = d.pred_sim == d.code_final
    d["ok_model"] = d.pred_model == d.code_final
    karniz = d.type_full.str.contains("карниз", case=False)

    print("\nНовый тип получает правильный код:")
    print(f"  поиск похожего типа: {d.ok_sim.mean():.0%}   (без карнизов {d[~karniz].ok_sim.mean():.0%})")
    print(f"  модель:              {d.ok_model.mean():.0%}   (без карнизов {d[~karniz].ok_model.mean():.0%})")
    print(f"  правила + модель:    {d.ok_final.mean():.0%}   (без карнизов {d[~karniz].ok_final.mean():.0%})")
    r = d[d.rule_code.notna()]
    print(f"\nправила сработали на {len(r)} типах, совпали с разметкой в {r.ok_final.mean():.0%}")
    print(r.groupby("rule").agg(типов=("ok_final", "size"), совпало=("ok_final", "sum")).to_string())

    t = d.groupby("revit_category").agg(типов=("ok_sim", "size"),
                                        похожий_тип=("ok_sim", "mean"), модель=("ok_model", "mean"),
                                        правила_и_модель=("ok_final", "mean"))
    print("\n" + t.sort_values("типов", ascending=False).to_string(formatters={
        "похожий_тип": "{:.0%}".format, "модель": "{:.0%}".format,
        "правила_и_модель": "{:.0%}".format}))

    print("\nУверенность (правило = 1.0):")
    for lo, hi in [(0.8, 1.01), (0.5, 0.8), (0, 0.5)]:
        part = d[(d.conf >= lo) & (d.conf < hi)]
        if len(part):
            print(f"  {lo:.1f}–{min(hi, 1):.1f}: {len(part):3d} типов, верно {part.ok_final.mean():.0%}")

    fixed = d[d.ok_model & ~d.ok_sim]
    broken = d[~d.ok_model & d.ok_sim]
    print(f"\nмодель исправила {len(fixed)} ошибок поиска, но сделала {len(broken)} новых")

    # Наименования кодов из листа «Классификатор» той же книги
    clf = pd.read_excel(path, sheet_name="Классификатор", dtype=str)
    names = dict(zip(clf.code.str.strip(), clf.name.str.strip()))
    err = d[~d.ok_final].copy()
    for c in ("code_final", "pred_final", "pred_sim"):
        col = {"code_final": "final_name", "pred_final": "final_name_pred", "pred_sim": "sim_name"}[c]
        err[col] = err[c].map(names)
    err = err[["revit_category", "type_full", "thick",
               "code_final", "final_name",
               "pred_final", "final_name_pred", "rule", "conf",
               "pred_sim", "sim_name"]].sort_values("conf")
    err = err.rename(columns={"final_name": "правильный_код_что_это", "pred_final": "предсказано",
                              "final_name_pred": "предсказано_что_это", "rule": "правило",
                              "sim_name": "похожий_тип_что_это"})
    err["conf"] = err.conf.round(2)
    err.to_csv("errors_model.csv", index=False, encoding="utf-8-sig")
    print(f"ошибки правил и модели ({len(err)}) — в errors_model.csv")

    final = make_model().fit(d, d.code_final)
    joblib.dump({"model": final, "allowed": d.groupby("ifc_class").code_final.agg(set)}, "model.joblib")
    print("модель на всей разметке сохранена в model.joblib")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
