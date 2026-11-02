"""
Проверка: насколько хорошо угадывается код для типа, которого модель ещё не видела.

Запуск:
    pip install scikit-learn
    python eval_baseline.py labels.xlsx

Имена файлов не используются. Таблица делится на 5 частей по группам похожих имён
(чтобы «Карниз33» не подсказывал «Карниз34»). Каждая часть по очереди прячется,
и её коды предсказываются по остальным:
    1. самый похожий размеченный тип того же IFC-класса (и той же категории Revit, если есть) (сходство имени и материалов)
    2. если такого класса в обучении нет — самый частый код вообще (почти всегда ошибка)
Для уже знакомых типов отдельной проверки не нужно: там код просто берётся из справочника.
Ошибки сохраняются в errors.csv.
"""
import sys

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import GroupKFold

from build_labels import norm_name


def load(path):
    d = pd.read_excel(path, sheet_name="Разметка", dtype=str).fillna("")
    d = d[(d.code_final != "") & (d.status != "исключить")].copy()
    if "revit_category" not in d:
        d["revit_category"] = ""
    d["group"] = (d.revit_category + " | " + d.ifc_class + " | " + d.parent_class + " | "
                  + d.type_full.map(norm_name))
    d["text"] = d.type_full.map(norm_name) + " " + d.materials.str.lower()
    return d.reset_index(drop=True)


def predict(train, test, vec):
    out = []
    for r in test.itertuples():
        same = train[(train.ifc_class == r.ifc_class) & (train.parent_class == r.parent_class)]
        # сначала ищем среди типов той же категории Revit, если такие есть
        same_cat = same[same.revit_category == r.revit_category]
        if len(same_cat):
            same = same_cat
        if len(same):
            sim = cosine_similarity(vec.transform([r.text]), vec.transform(same.text))[0]
            b = sim.argmax()
            out.append((same.code_final.iloc[b], "похожий тип", round(sim[b], 2), same.type_full.iloc[b]))
        else:
            out.append((train.code_final.mode()[0], "класса нет в обучении", 0, ""))
    return out


def main(path):
    d = load(path)
    print(f"размеченных типов: {len(d)}, групп похожих имён: {d.group.nunique()}")
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(d.text)

    d["pred"] = d["method"] = d["matched"] = None
    d["sim"] = 0.0
    for tr, te in GroupKFold(n_splits=5).split(d, groups=d.group):
        res = predict(d.iloc[tr], d.iloc[te], vec)
        d.loc[d.index[te], ["pred", "method", "sim", "matched"]] = res
    d["ok"] = d.pred == d.code_final

    print(f"\nНовый, ни разу не виденный тип получает правильный код: {d.ok.mean():.0%}\n")
    d["категория"] = d.revit_category.where(d.revit_category != "", d.ifc_class)
    by_class = d.groupby("категория").agg(типов=("ok", "size"), верно=("ok", "sum"))
    by_class["точность"] = (by_class.верно / by_class.типов).map("{:.0%}".format)
    print(by_class.sort_values("типов", ascending=False).to_string())

    # Насколько можно доверять сходству: точность при высоком и низком сходстве
    hi = d[d.sim >= 0.5]
    lo = d[d.sim < 0.5]
    print(f"\nсходство ≥ 0.5: {len(hi)} типов, верно {hi.ok.mean():.0%}")
    print(f"сходство < 0.5: {len(lo)} типов, верно {lo.ok.mean():.0%}  ← такие стоит показывать на проверку")

    err = d[~d.ok][["revit_category", "ifc_class", "type_full", "code_final", "pred", "sim", "matched"]]
    err.sort_values("sim").to_csv("errors.csv", index=False, encoding="utf-8-sig")
    print(f"\nошибок: {len(err)}, сохранены в errors.csv (столбец matched — на какой тип опиралось предсказание)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
