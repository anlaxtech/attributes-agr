"""
Модели для помещений и зон: код «Помещения и зоны», RUS_Zone, жилая зона, плавающий пол.

Запуск:
    python train_spaces.py labels_spaces.xlsx

Проверка как у элементов: строки делятся на части по имени (одинаковые имена — вместе),
каждая часть прячется и угадывается по остальным. Так видно, справится ли модель
с именем, которого ещё не было («Лест. клетка», «Коридор МОП»).
Ошибки — в errors_spaces.csv. Сервис использует ту же make_space_model().
"""
from __future__ import annotations

import re
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

TARGETS = {
    "code_final": "RUS_MSSK_SpaceAndZone_Code",
    "zone_final": "RUS_Zone",
    "residential_final": "RUS_ResidentialRoom",
    "floating_final": "RUS_GroundFloor",
}
KEY = ["space_kind", "revit_category", "space_name", "space_purpose", "zone_type"]


def norm(s) -> str:
    s = str(s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[_\-–.,]+", " ", s)).strip()


def prepare(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    for c in KEY:
        if c not in d:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str)
    d["name"] = d.space_name.map(norm)
    # группа = имя как есть: «Коридор 2» может опереться на «Коридор», а то же самое имя — нет
    d["group"] = d.name
    return d


def make_space_model() -> Pipeline:
    features = ColumnTransformer([
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True), "name"),
        ("words", TfidfVectorizer(analyzer="word", token_pattern=r"[а-яa-z0-9]{2,}"), "name"),
        ("cat", OneHotEncoder(handle_unknown="ignore"), ["space_kind", "space_purpose", "zone_type",
                                                         "revit_category"]),
    ])
    return Pipeline([("features", features),
                     ("clf", LogisticRegression(C=10, max_iter=3000, class_weight="balanced"))])


def train_rows(d: pd.DataFrame, target: str) -> pd.DataFrame:
    """Строки, пригодные для обучения столбца: значение заполнено и не исключено."""
    return d[(d[target] != "") & (d.status != "исключить")]


def fit_all(path) -> dict:
    """Для сервиса: {параметр АГР: (модель, справочник «ключ → значение»)}."""
    warnings.filterwarnings("ignore", module="sklearn")
    d = prepare(pd.read_excel(path, sheet_name="Помещения", dtype=str).fillna(""))
    out = {}
    for col, param in TARGETS.items():
        t = train_rows(d, col)
        known = {tuple(norm(r[k]) for k in KEY): r[col] for _, r in t.iterrows()}
        model = make_space_model().fit(t, t[col]) if t[col].nunique() >= 2 else None
        single = t[col].iloc[0] if t[col].nunique() == 1 else None   # всего одно значение — модель не нужна
        out[param] = {"model": model, "known": known, "single": single, "rows": len(t)}
    return out


def main(path):
    warnings.filterwarnings("ignore")
    d = prepare(pd.read_excel(path, sheet_name="Помещения", dtype=str).fillna(""))
    print(f"строк разметки: {len(d)}, уникальных имён: {d.group.nunique()}")
    errors = []
    for col, param in TARGETS.items():
        t = train_rows(d, col).reset_index(drop=True)
        classes = t[col].nunique()
        if classes < 2 or t.group.nunique() < 3:
            print(f"\n{param}: строк {len(t)}, значений {classes} — учить пока не на чем")
            continue
        folds = min(5, t.group.nunique())
        pred = np.empty(len(t), dtype=object)
        conf = np.zeros(len(t))
        for tr, te in GroupKFold(n_splits=folds).split(t, groups=t.group):
            train = t.iloc[tr]
            if train[col].nunique() < 2:
                pred[te] = train[col].iloc[0]
                conf[te] = 1.0
                continue
            m = make_space_model().fit(train, train[col])
            p = m.predict_proba(t.iloc[te])
            pred[te] = m.classes_[p.argmax(1)]
            conf[te] = p.max(1)
        ok = pred == t[col].values
        w = pd.to_numeric(t.n, errors="coerce").fillna(1).values
        print(f"\n{param}: строк {len(t)}, значений {classes}")
        print(f"  незнакомое написание угадано: {ok.mean():.0%} строк, {(ok * w).sum() / w.sum():.0%} помещений")
        if col == "code_final":
            unseen = ~t[col].isin(t[col].value_counts()[lambda v: v > 1].index)
            print(f"  из них у {unseen.sum()} строк код встречается в разметке один раз — "
                  f"угадать его по другим строкам нельзя, нужны данные из других проектов")
        hi = conf >= 0.8
        if hi.any():
            print(f"  уверенность ≥ 0.8: {hi.sum()} строк, верно {ok[hi].mean():.0%}")
        for i in np.where(~ok)[0]:
            r = t.iloc[i]
            errors.append({"параметр": param, "вид": r.space_kind, "имя": r.space_name,
                           "назначение": r.space_purpose, "правильно": r[col], "модель": pred[i],
                           "уверенность": round(conf[i], 2), "помещений": r.n})
    pd.DataFrame(errors).to_csv("errors_spaces.csv", index=False, encoding="utf-8-sig")
    print(f"\nошибки — errors_spaces.csv ({len(errors)})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
