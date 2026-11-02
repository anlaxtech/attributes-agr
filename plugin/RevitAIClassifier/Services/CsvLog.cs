using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>CSV: экспорт таблицы для Excel и журнал ручных правок (данные для дообучения).</summary>
    public static class CsvLog
    {
        static readonly string[] FeatureKeys =
        {
            "revit_category", "ifc_class", "parent_class", "type_full", "materials", "layers_mm",
            "IsExternal", "has_door_leaf", "room_from", "room_to", "space_name", "space_purpose", "zone_type", "file", "facade_type"
        };

        static readonly string[] Header = new[] { "date", "project", "param", "predicted", "value", "name",
            "source", "conf", "status", "current", "n_elements" }.Concat(FeatureKeys).ToArray();

        static IEnumerable<string> Row(ValueCell c, string project) => new[]
        {
            DateTime.Now.ToString("yyyy-MM-dd HH:mm"), project, c.Param, c.Predicted, c.Value, c.Name, c.Source,
            c.Conf.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture), c.Status, c.Current,
            c.Count.ToString()
        }.Concat(FeatureKeys.Select(k => c.Item.F(k)));

        static string Line(IEnumerable<string> cells, char sep) =>
            string.Join(sep.ToString(), cells.Select(x =>
            {
                x = x ?? "";
                return x.IndexOfAny(new[] { sep, '"', '\n' }) >= 0 ? "\"" + x.Replace("\"", "\"\"") + "\"" : x;
            }));

        /// <summary>Вся таблица — разделитель «;», чтобы русский Excel открыл по двойному щелчку.</summary>
        public static void Export(string path, IEnumerable<ValueCell> cells, Document doc)
        {
            var sb = new StringBuilder().AppendLine(Line(Header, ';'));
            foreach (var c in cells) sb.AppendLine(Line(Row(c, doc.Title), ';'));
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(true));
        }

        /// <summary>
        /// Правки для отправки на сервер: всё, что человек исправил или подтвердил вручную («проверено»).
        /// Подтверждения тоже ценны — это проверенные человеком примеры.
        /// </summary>
        public static List<Dictionary<string, string>> CorrectionRows(IEnumerable<ValueCell> cells, Document doc)
        {
            var user = Environment.UserName;
            var rows = new List<Dictionary<string, string>>();
            foreach (var c in cells.Where(c => c.Status != "исключить" && !string.IsNullOrEmpty(c.Value) &&
                                               (c.Edited || c.Status == "проверено")))
            {
                var r = new Dictionary<string, string>
                {
                    ["date"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                    ["user"] = user,
                    ["project"] = doc.Title,
                    ["edited"] = c.Edited ? "да" : "нет",
                    ["param"] = c.Param,
                    ["predicted"] = c.Predicted,
                    ["value"] = c.Value,
                    ["name"] = c.Name,
                    ["source"] = c.Source,
                    ["conf"] = c.Conf.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture),
                    ["status"] = c.Status,
                    ["n_elements"] = c.Count.ToString(),
                    ["ifc_export"] = c.Item.Cells.TryGetValue("IfcExportAs", out var ex) ? ex.Value : "",
                };
                foreach (var k in FeatureKeys) r[k] = c.Item.F(k);
                rows.Add(r);
            }
            return rows;
        }

        static string PendingPath => Path.Combine(SettingsStore.DefaultDir, "pending_corrections.json");

        /// <summary>Отправить правки на сервер. Не получилось — сохранить и отправить в следующий раз.</summary>
        public static string Send(PredictionClient client, List<Dictionary<string, string>> rows)
        {
            var all = new List<Dictionary<string, string>>();
            if (File.Exists(PendingPath))
            {
                try { all.AddRange(Json.Deserialize<List<Dictionary<string, string>>>(File.ReadAllText(PendingPath, Encoding.UTF8))); }
                catch { /* испорченный файл — начинаем заново */ }
            }
            all.AddRange(rows);
            if (all.Count == 0) return null;
            try
            {
                client.SendCorrections(all);
                if (File.Exists(PendingPath)) File.Delete(PendingPath);
                return $"Правки отправлены на сервер: {all.Count}";
            }
            catch (Exception ex)
            {
                Directory.CreateDirectory(SettingsStore.DefaultDir);
                File.WriteAllText(PendingPath, Json.Serialize(all), new UTF8Encoding(false));
                return $"Сервер не принял правки ({ex.Message}). Сохранены и уйдут при следующей записи: {all.Count}";
            }
        }

        /// <summary>Журнал правок: значения, изменённые вручную. Дописывается.</summary>
        public static string AppendCorrections(IEnumerable<ValueCell> cells, Document doc)
        {
            var edited = cells.Where(c => c.Edited && c.Status != "исключить").ToList();
            if (edited.Count == 0) return null;
            Directory.CreateDirectory(SettingsStore.DefaultDir);
            var path = Path.Combine(SettingsStore.DefaultDir, "corrections_v2.csv");
            bool isNew = !File.Exists(path);
            var sb = new StringBuilder();
            if (isNew) sb.AppendLine(Line(Header, ','));
            foreach (var c in edited) sb.AppendLine(Line(Row(c, doc.Title), ','));
            File.AppendAllText(path, sb.ToString(), new UTF8Encoding(isNew));
            return path;
        }
    }
}
