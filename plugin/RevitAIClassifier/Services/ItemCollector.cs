using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>
    /// Собирает из проекта всё, что нужно заполнить, с признаками для таблицы правил:
    /// тип файла (по имени документа), тип фасада, категория, «внутри витража», слои, материалы,
    /// створки окон, помещения по обе стороны двери, модель в контексте, помещения и зоны.
    /// </summary>
    public static class ItemCollector
    {
        const double FtToMm = 304.8;

        public static List<Item> Collect(Document doc, PluginSettings settings)
        {
            var items = new Dictionary<string, Item>();
            var inCurtain = CurtainMembers(doc);
            Phase phase = doc.Phases.Size > 0 ? doc.Phases.get_Item(doc.Phases.Size - 1) : null;
            string file = doc.Title;
            string facade = settings.FacadeFor(doc.Title);
            // «вид» — только элементы, видимые на активном виде
            var view = settings.Scope == "вид" ? doc.ActiveView : null;
            // квартиры: контуры помещений с назначением «Квартира» по уровням — для зон
            var apartments = ApartmentIndex(doc);

            foreach (var def in CategoryDefinitions.All)
            {
                var cs = settings.For(def.Key);
                if (!cs.Enabled) continue;
                foreach (var (bic, ifcClass) in def.Revit)
                {
                    bool spatial = CategoryDefinitions.IsSpatial(bic);
                    var collector = view != null ? new FilteredElementCollector(doc, view.Id) : new FilteredElementCollector(doc);
                    foreach (var e in collector.OfCategory(bic).WhereElementIsNotElementType())
                    {
                        if (e.Category == null) continue;
                        // «Витражи» и «Стены» — одна категория Revit, делим по тому, витраж ли это
                        if (def.Curtain.HasValue && e is Wall cw)
                        {
                            bool isCurtain = cw.CurtainGrid != null || inCurtain.Contains(e.Id);
                            if (isCurtain != def.Curtain.Value) continue;
                        }
                        if (spatial)
                        {
                            if (e is SpatialElement se && se.Area <= 0) continue;   // неразмещённые помещения
                            var it = SpaceItem(e, def, file);
                            if (bic == BuiltInCategory.OST_Areas && e is SpatialElement zone)
                                ZoneFeatures(zone, it.Features, apartments);
                            ReadCurrent(doc, it, e, null, cs, def);
                            items[it.Id] = it;
                            continue;
                        }

                        var type = doc.GetElement(e.GetTypeId()) as ElementType;
                        if (type == null) continue;
                        string category = CategoryName(e.Category);
                        string ifc = e is Wall w && w.CurtainGrid != null ? "IfcCurtainWall" : ifcClass;
                        // в витраже: элемент сетки витража (в т.ч. базовая стена вместо панели)
                        // или семейство, у которого хозяин — витраж
                        bool inGrid = inCurtain.Contains(e.Id) ||
                                      (e is FamilyInstance hosted && hosted.Host is Wall hw && hw.CurtainGrid != null);
                        string roomFrom = "", roomTo = "";
                        if (bic == BuiltInCategory.OST_Doors && e is FamilyInstance door && phase != null)
                        {
                            roomFrom = Purpose(door.get_FromRoom(phase));
                            roomTo = Purpose(door.get_ToRoom(phase));
                        }
                        string key = $"{type.Id.Num()}|{category}|{ifc}|{inGrid}|{roomFrom}|{roomTo}";

                        if (!items.TryGetValue(key, out var item))
                        {
                            item = new Item { Id = key, CategoryKey = def.Key, TypeId = type.Id };
                            var f = item.Features;
                            f["file"] = file;
                            f["facade_type"] = facade;
                            f["revit_category"] = category;
                            f["ifc_class"] = ifc;
                            f["parent_class"] = inGrid ? "IfcCurtainWall" : "";
                            f["in_curtain_wall"] = inGrid ? "да" : "нет";
                            f["is_curtain_wall"] = ifc == "IfcCurtainWall" && e is Wall ? "да" : "нет";
                            f["type_full"] = type.FamilyName + ":" + type.Name;
                            f["in_place"] = e is FamilyInstance fi && fi.Symbol?.Family != null && fi.Symbol.Family.IsInPlace
                                ? "да" : "нет";
                            f["room_from"] = roomFrom;
                            f["room_to"] = roomTo;
                            FillLayers(type, doc, f);
                            if (string.IsNullOrEmpty(f.TryGetValue("materials", out var m) ? m : ""))
                                f["materials"] = Materials(doc, e);
                            if (type is WallType wt)
                                f["IsExternal"] = wt.Function == WallFunction.Exterior ? "True" : "False";
                            if (bic == BuiltInCategory.OST_Windows)
                                f["has_door_leaf"] = DoorLeaf(e, type);
                            ReadCurrent(doc, item, e, type, cs, def);
                            items[key] = item;
                        }
                        item.InstanceIds.Add(e.Id);
                    }
                }
            }
            return items.Values.ToList();
        }

        static string CategoryName(Category c) => c.Parent != null ? c.Parent.Name + ": " + c.Name : c.Name;

        /// <summary>Помещение или зона — отдельной строкой (параметры у них свои у каждого экземпляра).</summary>
        static Item SpaceItem(Element e, CategoryDefinition def, string file)
        {
            string name = e.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? e.Name ?? "";
            string category = CategoryName(e.Category);
            var it = new Item { Id = "space|" + e.Id.Num(), CategoryKey = def.Key, ByInstance = true };
            it.InstanceIds.Add(e.Id);
            var f = it.Features;
            f["file"] = file;
            f["revit_category"] = category;
            f["ifc_class"] = "IfcSpace";
            f["type_full"] = category + ":" + name;
            f["space_name"] = name;
            f["space_number"] = e.get_Parameter(BuiltInParameter.ROOM_NUMBER)?.AsString() ?? "";
            f["level"] = (e.Document.GetElement(e.LevelId) as Level)?.Name ?? "";
            f["space_purpose"] = ParamContains(e, "Назначение помещения");
            f["apartment_number"] = Param(e, "Номер квартиры (сквозной)") ?? Param(e, "Номер квартиры") ?? "";
            return it;
        }

        // ---------- зоны и квартиры ----------

        class Apartment
        {
            public ElementId Level;
            public XYZ Point;
            public List<List<XYZ>> Loops;
        }

        /// <summary>Помещения квартир (назначение содержит «квартир») с контурами.</summary>
        static List<Apartment> ApartmentIndex(Document doc)
        {
            var list = new List<Apartment>();
            foreach (Room r in new FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                         .WhereElementIsNotElementType().OfType<Room>())
            {
                if (r.Area <= 0) continue;
                if (!ParamContains(r, "Назначение помещения").ToLowerInvariant().Contains("квартир")) continue;
                list.Add(new Apartment
                {
                    Level = r.LevelId,
                    Point = (r.Location as LocationPoint)?.Point,
                    Loops = Loops(r)
                });
            }
            return list;
        }

        /// <summary>Контуры помещения или зоны как точки (дуги разбиваются на отрезки).</summary>
        static List<List<XYZ>> Loops(SpatialElement se)
        {
            var result = new List<List<XYZ>>();
            IList<IList<BoundarySegment>> segs;
            try { segs = se.GetBoundarySegments(new SpatialElementBoundaryOptions()); }
            catch { return result; }
            if (segs == null) return result;
            foreach (var loop in segs)
            {
                var pts = new List<XYZ>();
                foreach (var seg in loop)
                {
                    var t = seg.GetCurve()?.Tessellate();
                    if (t == null) continue;
                    for (int i = 0; i < t.Count - 1; i++) pts.Add(t[i]);   // последняя точка = первая следующего
                }
                if (pts.Count >= 3) result.Add(pts);
            }
            return result;
        }

        /// <summary>Точка внутри многоугольника с отверстиями (в плане, правило чёт-нечет по всем контурам).</summary>
        static bool Inside(List<List<XYZ>> loops, XYZ p)
        {
            if (p == null || loops.Count == 0) return false;
            bool inside = false;
            foreach (var poly in loops)
                for (int i = 0, j = poly.Count - 1; i < poly.Count; j = i++)
                {
                    var a = poly[i];
                    var b = poly[j];
                    if ((a.Y > p.Y) != (b.Y > p.Y) &&
                        p.X < (b.X - a.X) * (p.Y - a.Y) / (b.Y - a.Y) + a.X)
                        inside = !inside;
                }
            return inside;
        }

        /// <summary>Контуры пересекаются: точка/вершина одного внутри другого.</summary>
        static bool Overlap(List<List<XYZ>> zone, Apartment apt)
        {
            if (Inside(zone, apt.Point)) return true;
            if (apt.Loops.Any(l => l.Any(v => Inside(zone, v)))) return true;
            return zone.Any(l => l.Any(v => Inside(apt.Loops, v)));
        }

        /// <summary>Признаки зоны: схема зонирования, тип зон, есть ли квартиры в зоне и на её уровне.</summary>
        static void ZoneFeatures(SpatialElement zone, Dictionary<string, string> f, List<Apartment> apartments)
        {
            if (zone is Area area) f["area_scheme"] = area.AreaScheme?.Name ?? "";
            f["zone_type"] = Param(zone, "Тип зон") ?? "";
            var onLevel = apartments.Where(a => a.Level == zone.LevelId).ToList();
            f["level_has_apartments"] = onLevel.Count > 0 ? "да" : "нет";
            var loops = Loops(zone);
            f["zone_has_apartments"] = loops.Count > 0 && onLevel.Any(a => Overlap(loops, a)) ? "да" : "нет";
        }

        /// <summary>«…Назначение помещения» у помещения с одной из сторон двери.</summary>
        static string Purpose(Room room) => room == null ? "" : ParamContains(room, "Назначение помещения");

        static string Param(Element e, string name)
        {
            var p = e.LookupParameter(name);
            var v = p == null ? null : (p.AsString() ?? p.AsValueString());
            return string.IsNullOrWhiteSpace(v) ? null : v;
        }

        static string ParamContains(Element e, string part)
        {
            foreach (Parameter p in e.Parameters)
                if (p?.Definition != null && p.Definition.Name.Contains(part))
                {
                    var v = p.AsString() ?? p.AsValueString();
                    if (!string.IsNullOrWhiteSpace(v)) return v;
                }
            return "";
        }

        /// <summary>Все панели и импосты всех витражей проекта, включая стены-панели.</summary>
        static HashSet<ElementId> CurtainMembers(Document doc)
        {
            var ids = new HashSet<ElementId>();
            foreach (Wall w in new FilteredElementCollector(doc).OfClass(typeof(Wall)))
            {
                var grid = w.CurtainGrid;
                if (grid == null) continue;
                foreach (var id in grid.GetPanelIds()) ids.Add(id);
                foreach (var id in grid.GetMullionIds()) ids.Add(id);
            }
            return ids;
        }

        /// <summary>Слои стен и перекрытий: «20.0+150.0» и имена материалов, как в выгрузке IFC.</summary>
        static void FillLayers(ElementType type, Document doc, Dictionary<string, string> f)
        {
            if (!(type is HostObjAttributes hoa)) return;
            var cs = hoa.GetCompoundStructure();
            if (cs == null) return;
            var layers = cs.GetLayers();
            f["layers_mm"] = string.Join("+", layers.Select(l =>
                (l.Width * FtToMm).ToString("0.0", CultureInfo.InvariantCulture)));
            f["materials"] = string.Join(" | ", layers.Select(l => doc.GetElement(l.MaterialId)?.Name ?? ""));
        }

        /// <summary>Материалы геометрии семейства (двери, окна, импосты, панели).</summary>
        static string Materials(Document doc, Element e)
        {
            try
            {
                return string.Join(" | ", e.GetMaterialIds(false)
                    .Select(id => doc.GetElement(id)?.Name).Where(n => !string.IsNullOrEmpty(n)).Distinct());
            }
            catch
            {
                return "";
            }
        }

        /// <summary>Окна с вложенными створками: есть ли дверь среди «Открывание створки N».</summary>
        static string DoorLeaf(Element e, ElementType type)
        {
            var values = new List<string>();
            foreach (var el in new[] { e, (Element)type })
                foreach (Parameter p in el.Parameters)
                    if (p?.Definition != null && p.Definition.Name.StartsWith("Открывание створки"))
                    {
                        var v = p.AsValueString() ?? p.AsString();
                        if (!string.IsNullOrWhiteSpace(v)) values.Add(v);
                    }
            if (values.Count == 0) return "";
            return values.Any(v => v.ToLower().Contains("дверь")) ? "True" : "False";
        }

        /// <summary>Текущие значения параметров АГР в модели — для колонки «Сейчас в модели».</summary>
        static void ReadCurrent(Document doc, Item item, Element e, ElementType type, CategorySettings cs,
                                CategoryDefinition def)
        {
            foreach (var ifc in def.IfcParams)
            {
                var b = cs.Get(ifc);
                if (b == null || string.IsNullOrEmpty(b.RevitParam)) continue;
                var target = b.IsType ? (Element)type : e;
                var p = target?.LookupParameter(b.RevitParam);
                if (p == null) continue;
                item.Current[ifc] = p.StorageType == StorageType.String ? p.AsString() ?? "" : p.AsValueString() ?? "";
            }
        }
    }
}
