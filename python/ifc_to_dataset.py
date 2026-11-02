"""
Извлечение обучающего датасета из выданных IFC для АГР.

Запуск:
    pip install ifcopenshell pandas pyarrow
    python ifc_to_dataset.py путь/к/папке_с_ifc  out/

На выходе:
    out/elements.parquet  — одна строка на элемент (признаки + целевые параметры)
    out/types.parquet/.csv — одна строка на (тип, категория Revit, IFC-класс, роль в витраже);
                             файлы, где встречается тип, — через запятую
    out/elements.csv      — то же, что elements, для просмотра в Excel
"""
import os
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
import pandas as pd

# Элементы, которые не классифицируются
SKIP_CLASSES = ("IfcOpeningElement", "IfcFlowTerminal", "IfcBuildingElementProxy")

# Целевые параметры АГР: (Pset, свойство) -> колонка
TARGETS = {
    ("RusSet_Common", "RUS_MSSK_Element_Code"): "y_el_code",
    ("RusSet_Common", "RUS_MSSK_Element_Name"): "y_el_name",
    ("RusSet_Common", "RUS_MSSK_Material_Code"): "y_mat_code",
    ("RusSet_Common", "RUS_MSSK_Material_Name"): "y_mat_name",
    ("RusSet_Common", "RUS_Name"): "y_rus_name",
    ("RusSet_Quantities", "RUS_Thickness"): "y_thickness",
    ("RusSet_Quantities", "RUS_Height"): "y_height",
    ("RusSet_Quantities", "RUS_Width"): "y_width",
    ("RusSet_Location", "RUS_Object"): "obj",
    ("RusSet_Location", "RUS_Object_Sub"): "obj_sub",
    # помещения и зоны (IfcSpace)
    ("RusSet_Common", "RUS_MSSK_SpaceAndZone_Code"): "y_space_code",
    ("RusSet_Common", "RUS_MSSK_SpaceAndZone_Name"): "y_space_name",
    ("RusSet_Identification", "RUS_Zone"): "y_zone",
    ("RusSet_Identification", "RUS_Group_Type"): "y_group_type",
    ("RusSet_Identification", "RUS_Number"): "y_number",
    ("RusSet_Identification", "RUS_Group_Number"): "y_group_number",
    ("RusSet_AGR", "RUS_StudioApart"): "y_studio",
    ("RusSet_AGR", "RUS_BasementFloor"): "y_basement",
    ("RusSet_AGR", "RUS_GroundFloor"): "y_floating_floor",
    ("RusSet_AGR", "RUS_ResidentialRoom"): "y_residential",
    ("RusSet_AGR", "RUS_ResidentalRoom"): "y_residential",   # старое написание в части выданных IFC
    ("RusSet_Quantities", "RUS_Area"): "y_area",
}

# Признаки, которые можно получить и из Revit API
FEATURES = {
    ("Идентификация", "Код по классификатору"): "revit_code",
    ("Идентификация", "Описание"): "revit_description",
    ("Идентификация", "Маркировка типоразмера"): "revit_type_mark",
    ("Идентификация", "UniqueId"): "revit_unique_id",
    ("Прочее", "Категория"): "revit_category",
    # помещения и зоны
    ("Идентификация", "Имя"): "space_name",
    ("Идентификация", "Назначение"): "space_purpose",
    ("Прочее", "Тип зон"): "zone_type",
}
COMMON_FLAGS = ("IsExternal", "LoadBearing")


def material_info(el):
    """Имена материалов и толщины слоёв (если есть набор слоёв)."""
    mat = ue.get_material(el, should_skip_usage=True)
    if mat is None:
        return None, None, None
    kind = mat.is_a()
    names, layers = [], []
    if kind == "IfcMaterial":
        names = [mat.Name]
    elif kind == "IfcMaterialLayerSet":
        for l in mat.MaterialLayers:
            names.append(l.Material.Name if l.Material else "")
            layers.append(round(float(l.LayerThickness), 1))
    elif kind == "IfcMaterialProfileSet":
        names = [p.Material.Name for p in mat.MaterialProfiles if p.Material]
        names = names or [mat.Name or ""]
    elif kind == "IfcMaterialConstituentSet":
        names = [c.Material.Name for c in (mat.MaterialConstituents or []) if c.Material]
    elif kind == "IfcMaterialList":
        names = [m.Name for m in mat.Materials]
    layers_str = "+".join(str(x) for x in layers) if layers else None
    return kind, " | ".join(n or "" for n in names), layers_str


def door_leaf(psets: dict):
    """Окна с вложенными створками: есть ли среди створок дверь.
    Параметры «Открывание створки N» семейства (тип или экземпляр) выгружаются в IFC,
    значение вида «Створка рама и стекло : Дверь - Правое (внутрь)».
    None — у окна таких параметров нет."""
    vals = [str(v) for ps in psets.values() for k, v in ps.items()
            if k.startswith("Открывание створки") and v]
    if not vals:
        return None
    return any("дверь" in v.lower() for v in vals)


def _row(path: Path, el, psets: dict) -> dict:
    row = {}
    for flag in COMMON_FLAGS:
        row[flag] = next((v[flag] for k, v in psets.items()
                          if k.startswith("Pset_") and k.endswith("Common") and flag in v), None)
    for (ps, prop), col in {**FEATURES, **TARGETS}.items():
        v = psets.get(ps, {}).get(prop)
        if v is not None or col not in row:   # несколько написаний одного параметра — берём найденное
            row[col] = v
    return row


def extract(path: Path) -> list[dict]:
    f = ifcopenshell.open(str(path))
    rows = []
    for el in f.by_type("IfcElement"):
        if el.is_a() in SKIP_CLASSES:
            continue
        psets = ue.get_psets(el)
        t = ue.get_type(el)
        type_full = t.Name if t else el.Name
        family, _, type_name = (type_full or "").partition(":")
        container = ue.get_aggregate(el)
        mkind, mnames, layers = material_info(el)

        row = {
            "file": path.name,
            "guid": el.GlobalId,
            "ifc_class": el.is_a(),
            "predefined_type": getattr(el, "PredefinedType", None),
            "family": family.strip("… ").strip(),
            "type_name": type_name.strip(),
            "type_full": type_full,
            "parent_class": container.is_a() if container else None,  # напр. панель внутри IfcCurtainWall
            "has_parts": bool(getattr(el, "IsDecomposedBy", None)),
            "material_kind": mkind,
            "materials": mnames,
            "layers_mm": layers,
            "storey": getattr(ue.get_container(el), "Name", None),
            "has_door_leaf": door_leaf(psets) if el.is_a("IfcWindow") else None,
        }
        row.update(_row(path, el, psets))
        rows.append(row)

    # Помещения и зоны: Revit выгружает и то и другое как IfcSpace.
    # «Тип» для них — имя (Жилая комната, Общая площадь…), чтобы группировать одинаковые.
    for sp in f.by_type("IfcSpace"):
        psets = ue.get_psets(sp)
        r = _row(path, sp, psets)
        is_zone = bool(r.get("zone_type"))
        name = r.get("space_name") or sp.LongName or sp.Name or ""
        cat = r.get("revit_category") or ("Зоны" if is_zone else "Помещения")
        r.update({
            "file": path.name,
            "guid": sp.GlobalId,
            "ifc_class": "IfcSpace",
            "space_kind": "зона" if is_zone else "помещение",
            "family": cat,
            "type_name": name,
            "type_full": f"{cat}:{name}",
            "parent_class": None,
            "storey": getattr(ue.get_container(sp), "Name", None)
                      or getattr(ue.get_aggregate(sp), "Name", None),
        })
        rows.append(r)
    return rows


def _cache_path(cache_dir: Path, p: Path) -> Path:
    st = p.stat()
    return cache_dir / f"{p.stem}_{st.st_size}_{int(st.st_mtime)}.parquet"


def _extract_one(path_str: str) -> list[dict]:
    return extract(Path(path_str))


def extract_files(files, cache_dir: Path, log=print, workers: int = 1) -> pd.DataFrame:
    """Читает IFC (параллельно, если workers > 1). Уже прочитанные файлы берутся из кэша:
    при повторном запуске обрабатываются только новые или изменённые IFC."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames, todo = [], []
    for p in files:
        c = _cache_path(cache_dir, p)
        if c.exists():
            frames.append(pd.read_parquet(c))
            log(f"✓ {p.name} (из кэша)")
        else:
            todo.append(p)

    def done(p, rows):
        df = pd.DataFrame(rows)
        for col in df.columns:  # смешанные типы → строки, чтобы parquet не ругался
            if df[col].dtype == object:
                df[col] = df[col].map(lambda v: v if v is None or isinstance(v, str) else str(v))
        df.to_parquet(_cache_path(cache_dir, p), index=False)
        frames.append(df)
        log(f"✓ {p.name}: {len(df)} элементов")

    if workers > 1 and len(todo) > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_extract_one, str(p)): p for p in todo}
            for f in as_completed(futs):
                p = futs[f]
                try:
                    done(p, f.result())
                except Exception as e:  # битый файл не должен ронять всё
                    log(f"✗ {p.name}: {e}")
    else:
        for p in todo:
            log(f"→ {p.name}…")
            try:
                done(p, extract(p))
            except Exception as e:
                log(f"✗ {p.name}: {e}")
    if not frames:
        raise RuntimeError("не удалось прочитать ни одного IFC")
    return pd.concat(frames, ignore_index=True)


def save_tables(df: pd.DataFrame, out: Path, log=print) -> Path:
    """Сохраняет elements.* и types.* в папку out. Возвращает путь к types.csv."""
    out.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    # Файлы из кэша могут отличаться типами колонок (bool / str) — приводим всё нечисловое к строкам
    for c in df.columns:
        if df[c].dtype == object or df[c].dtype == bool or str(df[c].dtype).startswith("str"):
            df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    df.to_parquet(out / "elements.parquet", index=False)
    df.to_csv(out / "elements.csv", index=False, encoding="utf-8-sig")

    # Уровень типа: одна строка на (тип, класс, роль в витраже) по всем файлам.
    # Если тип встречается в нескольких файлах, их имена собираются через запятую.
    def join_unique(s):
        vals = sorted({str(v) for v in s.dropna()})
        return ", ".join(vals) if vals else None

    # Помещения и зоны — в отдельную таблицу, чтобы не смешивать с классификатором элементов
    if "ifc_class" in df and (df.ifc_class == "IfcSpace").any():
        sp = df[df.ifc_class == "IfcSpace"]
        cols = [c for c in ["file", "space_kind", "revit_category", "space_name", "space_purpose", "zone_type",
                            "y_rus_name", "y_space_code", "y_space_name", "y_zone", "y_group_type",
                            "y_studio", "y_basement", "y_floating_floor", "y_residential"] if c in sp]
        sp[cols].fillna("").astype(str).value_counts(dropna=False).reset_index(name="n").to_csv(
            out / "spaces.csv", index=False, encoding="utf-8-sig")
        log(f"помещений и зон: {len(sp)} → spaces.csv")
        df = df[df.ifc_class != "IfcSpace"]

    keys = ["type_full", "ifc_class", "parent_class", "revit_category"]
    agg = {c: "first" for c in ["family", "type_name", "predefined_type", "materials",
                                "layers_mm", "IsExternal", "LoadBearing", "has_door_leaf"]}
    # Целевые и сравниваемые коды: все встретившиеся варианты, чтобы видеть расхождения
    agg.update({c: join_unique for c in ["revit_code", "y_el_code", "y_el_name", "y_mat_code",
                                         "y_mat_name", "y_rus_name", "y_thickness"]})
    types = df.groupby(keys, dropna=False).agg(files=("file", join_unique),
                                               n_files=("file", "nunique"),
                                               n_elements=("guid", "size"),
                                               n_el_codes=("y_el_code", "nunique"),
                                               **{k: (k, v) for k, v in agg.items()}).reset_index()
    first = ["files", "n_files", "revit_category", "ifc_class", "parent_class", "family", "type_name",
             "y_el_code", "n_el_codes", "y_el_name", "revit_code", "n_elements"]
    types = types[first + [c for c in types.columns if c not in first]]
    types.to_parquet(out / "types.parquet", index=False)
    types.to_csv(out / "types.csv", index=False, encoding="utf-8-sig")

    conflicts = types[types.n_el_codes > 1]
    log(f"элементов: {len(df)}, строк уровня типа: {len(types)}")
    log(f"доля с кодом элемента: {df.y_el_code.notna().mean():.0%}, "
        f"с кодом материала: {df.y_mat_code.notna().mean():.0%}")
    if len(conflicts):
        log(f"типов с разными кодами (внутри файла или между файлами): {len(conflicts)}")
    return out / "types.csv"


def main(src: str, out: str):
    src, out = Path(src), Path(out)
    files = [src] if src.is_file() else sorted(src.glob("*.ifc"))
    df = extract_files(files, out / "cache", workers=min(4, os.cpu_count() or 1))
    save_tables(df, out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
