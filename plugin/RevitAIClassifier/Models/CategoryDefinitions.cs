using System.Collections.Generic;
using Autodesk.Revit.DB;

namespace RevitAIClassifier.Models
{
    /// <summary>Категория плагина: какие категории Revit в неё входят и какие параметры АГР у неё есть.</summary>
    public class CategoryDefinition
    {
        public string Key { get; set; }   // как в левом списке окна
        public List<(BuiltInCategory Bic, string IfcClass)> Revit { get; } =
            new List<(BuiltInCategory, string)>();
        public string[] IfcParams { get; set; }
        /// <summary>Подбирать ли код классификатора моделью (для помещений и зон — нет).</summary>
        public bool Classify { get; set; } = true;
        /// <summary>Только для стен: true — витражи и стены-панели витражей, false — остальные стены, null — все.</summary>
        public bool? Curtain { get; set; }

        public override string ToString() => Key;
    }

    public static class CategoryDefinitions
    {
        // Параметры АГР, которые чаще всего упоминаются в коде
        public const string ElementCode = "RUS_MSSK_Element_Code";
        public const string ElementName = "RUS_MSSK_Element_Name";

        /// <summary>Пространства: помещения и зоны заполняются по экземплярам, а не по типам.</summary>
        public static bool IsSpatial(BuiltInCategory bic) =>
            bic == BuiltInCategory.OST_Rooms || bic == BuiltInCategory.OST_Areas;

        static readonly string[] Common = { "RUS_Name", ElementCode, ElementName };
        static readonly string[] WithMaterial =
        {
            "RUS_Name", ElementCode, ElementName, "RUS_MSSK_Material_Name", "RUS_MSSK_Material_Code"
        };

        /// <summary>Категории и параметры по макету. Чтобы добавить параметр — допишите его сюда.</summary>
        public static readonly List<CategoryDefinition> All = new List<CategoryDefinition>
        {
            new CategoryDefinition
            {
                Key = "Импосты витража",
                Revit = { (BuiltInCategory.OST_CurtainWallMullions, "IfcMember") },
                IfcParams = new[] { "RUS_Name", "RUS_MSSK_Material_Name", "RUS_MSSK_Material_Code",
                                    ElementCode, ElementName }
            },
            new CategoryDefinition
            {
                Key = "Панели витража",
                Revit = { (BuiltInCategory.OST_CurtainWallPanels, "IfcPlate") },
                IfcParams = WithMaterial
            },
            new CategoryDefinition
            {
                Key = "Окна",
                Revit = { (BuiltInCategory.OST_Windows, "IfcWindow") },
                IfcParams = Concat(WithMaterial, "RUS_Width", "RUS_Height")
            },
            new CategoryDefinition
            {
                Key = "Двери",
                Revit = { (BuiltInCategory.OST_Doors, "IfcDoor") },
                IfcParams = Concat(WithMaterial, "RUS_Width", "RUS_Height")
            },
            new CategoryDefinition
            {
                Key = "Витражи",
                Curtain = true,
                // стена с сеткой витража и базовые стены, вставленные в витраж вместо панелей → IfcCurtainWall
                Revit = { (BuiltInCategory.OST_Walls, "IfcCurtainWall") },
                IfcParams = new[] { "RUS_Name", ElementCode, ElementName, "RUS_MSSK_Material_Name",
                                    "RUS_MSSK_Material_Code" }
            },
            new CategoryDefinition
            {
                Key = "Стены",
                Curtain = false,
                // стена с сеткой витража уходит в IFC как IfcCurtainWall (см. ItemCollector)
                Revit = { (BuiltInCategory.OST_Walls, "IfcWall") },
                IfcParams = Concat(Common, "RUS_Thickness")
            },
            new CategoryDefinition
            {
                Key = "Перекрытия",
                Revit = { (BuiltInCategory.OST_Floors, "IfcSlab") },
                IfcParams = Concat(Common, "RUS_Thickness")
            },
            new CategoryDefinition
            {
                Key = "Лестницы",
                Revit =
                {
                    (BuiltInCategory.OST_Stairs, "IfcStair"),
                    (BuiltInCategory.OST_StairsRuns, "IfcStairFlight"),
                    (BuiltInCategory.OST_StairsLandings, "IfcSlab")
                },
                IfcParams = Common
            },
            new CategoryDefinition
            {
                Key = "Колонны",
                Revit =
                {
                    (BuiltInCategory.OST_Columns, "IfcColumn"),
                    (BuiltInCategory.OST_StructuralColumns, "IfcColumn")
                },
                IfcParams = new[] { "RUS_Name", ElementCode, ElementName, "RUS_Diametr", "RUS_Height" }
            },
            new CategoryDefinition
            {
                Key = "Помещения",
                Classify = false,
                Revit = { (BuiltInCategory.OST_Rooms, "IfcSpace") },
                IfcParams = new[] { "RUS_StudioApart", "RUS_BasementFloor", "RUS_GroundFloor",
                                    "RUS_MSSK_SpaceAndZone_Code", "RUS_MSSK_SpaceAndZone_Name", "RUS_Name",
                                    "RUS_Group_Type", "RUS_Number", "RUS_Group_Number", "RUS_Zone",
                                    "RUS_Area" }
            },
            new CategoryDefinition
            {
                Key = "Зоны",
                Classify = false,
                Revit = { (BuiltInCategory.OST_Areas, "IfcZone") },
                IfcParams = new[] { "RUS_MSSK_SpaceAndZone_Code", "RUS_MSSK_SpaceAndZone_Name",
                                    "RUS_BasementFloor", "RUS_GroundFloor", "RUS_ResidentialRoom", "RUS_Name",
                                    "RUS_Zone", "RUS_Area" }
            },
        };

        static string[] Concat(string[] a, params string[] b)
        {
            var list = new List<string>(a);
            list.AddRange(b);
            return list.ToArray();
        }

        public const string ExportAs = "IfcExportAs";

        static CategoryDefinitions()
        {
            // IfcExportAs — первым параметром в каждой категории (с него начинается схема)
            foreach (var d in All)
                if (System.Array.IndexOf(d.IfcParams, ExportAs) < 0)
                {
                    var list = new List<string> { ExportAs };
                    list.AddRange(d.IfcParams);
                    d.IfcParams = list.ToArray();
                }
        }
    }
}
