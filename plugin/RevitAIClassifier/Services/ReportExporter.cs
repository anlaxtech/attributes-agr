using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>
    /// Отчёт в Excel по результатам записи: что заполнено, что нет и почему — по каждому элементу (с ID).
    /// Листы: «Не заполнено», «Все элементы», «Сводка».
    /// </summary>
    public static class ReportExporter
    {
        static readonly string[] Head =
        {
            "ID элемента", "Категория", "Семейство", "Тип / имя", "Номер", "Уровень",
            "Параметр АГР", "Что это", "Параметр Revit", "Тип / экз.", "Значение", "Результат",
            "Статус проверки", "Источник значения"
        };

        public static void Export(string path, Document doc, List<WriteRecord> records, bool dryRun)
        {
            var levels = new Dictionary<ElementId, string>();
            string LevelOf(ElementId id)
            {
                var el = doc.GetElement(id);
                if (el == null) return "";
                var lid = el.LevelId;
                if (lid == null || lid == ElementId.InvalidElementId)
                {
                    var p = el.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM) ??
                            el.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
                    lid = p?.AsElementId();
                }
                if (lid == null || lid == ElementId.InvalidElementId) return "";
                if (!levels.TryGetValue(lid, out var n)) levels[lid] = n = doc.GetElement(lid)?.Name ?? "";
                return n;
            }

            string[] Row(WriteRecord r) => new[]
            {
                r.ElementId.Num().ToString(),
                r.Item.Category,
                r.Item.Family,
                r.Item.ByInstance ? r.Item.F("space_name") : r.Item.F("type_full").Split(new[] { ':' }, 2).Last(),
                r.Item.F("space_number"),
                LevelOf(r.ElementId),
                r.Param,
                r.Param == "—" ? "" : Classifier.Title(r.Param).Replace(r.Param, "").Trim(' ', '·'),
                r.RevitParam ?? "",
                string.IsNullOrEmpty(r.RevitParam) ? "" : r.TypeLevel ? "тип" : "экземпляр",
                r.Value ?? "",
                r.Result,
                r.Status,
                r.Source,
            };

            var sorted = records.OrderBy(r => r.Item.Category).ThenBy(r => r.Item.Family)
                                .ThenBy(r => r.ElementId.Num()).ThenBy(r => r.Param).ToList();

            var bad = new XlsxWriter.Sheet { Name = "Не заполнено", NumericColumns = { 0 } };
            bad.Rows.Add(Head);
            bad.Rows.AddRange(sorted.Where(r => !r.Ok).Select(Row));

            var all = new XlsxWriter.Sheet { Name = "Все элементы", NumericColumns = { 0 } };
            all.Rows.Add(Head);
            all.Rows.AddRange(sorted.Select(Row));

            // сводка: категория × параметр → сколько элементов с каждым результатом
            var results = records.Select(r => r.Result).Distinct().OrderBy(x => x).ToList();
            var summary = new XlsxWriter.Sheet { Name = "Сводка" };
            summary.Rows.Add(new[] { "Категория", "Параметр АГР", "Всего" }.Concat(results).ToArray());
            for (int i = 2; i < 3 + results.Count; i++) summary.NumericColumns.Add(i);
            foreach (var g in records.GroupBy(r => (r.Item.CategoryKey, r.Param)).OrderBy(g => g.Key.CategoryKey).ThenBy(g => g.Key.Param))
            {
                var row = new List<string> { g.Key.CategoryKey, g.Key.Param, g.Count().ToString() };
                row.AddRange(results.Select(res => g.Count(r => r.Result == res).ToString()));
                summary.Rows.Add(row.ToArray());
            }
            var info = new XlsxWriter.Sheet { Name = "О файле" };
            info.Rows.Add(new[] { "Отчёт АтрибутыАГР", "" });
            info.Rows.Add(new[] { "Проект", doc.Title });
            info.Rows.Add(new[] { "Дата", System.DateTime.Now.ToString("yyyy-MM-dd HH:mm") });
            info.Rows.Add(new[] { "Что это", dryRun ? "План: что БУДЕТ записано (в модель ещё ничего не писалось)"
                                                    : "Результат записи в модель" });
            info.Rows.Add(new[] { "Найти элемент", "Управление → Выбрать по коду (ID) → вставить ID элемента" });

            XlsxWriter.Save(path, new[] { bad, all, summary, info });
        }
    }
}
