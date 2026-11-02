using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using Autodesk.Revit.DB;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>Что получилось с одним параметром одного элемента — строка отчёта.</summary>
    public class WriteRecord
    {
        public ElementId ElementId;
        public Item Item;
        public string Param;          // параметр АГР
        public string RevitParam;     // параметр Revit из маппинга
        public bool TypeLevel;        // записывался в тип
        public string Value;
        public string Status;         // статус проверки в окне
        public string Source;
        public string Result;         // записано / уже стояло / не перезаписано / не заполнено: …
        public bool Ok;               // значение в модели соответствует итогу
    }

    /// <summary>Записывает значения всех параметров в параметры Revit из маппинга.</summary>
    public static class ParameterWriter
    {
        /// <summary>Результаты последней записи (или проверки без записи) — для отчёта в Excel.</summary>
        public static List<WriteRecord> LastRecords { get; private set; } = new List<WriteRecord>();
        public static bool LastWasDryRun { get; private set; } = true;

        /// <summary>
        /// dryRun = true — ничего не меняет в модели, только считает, что будет записано
        /// (для отчёта до записи).
        /// </summary>
        public static string Write(Document doc, IEnumerable<Item> items, PluginSettings settings, bool dryRun = false)
        {
            int written = 0, same = 0, kept = 0;
            var records = new List<WriteRecord>();
            var problems = new SortedDictionary<string, SortedSet<string>>();
            void Problem(string what, string where)
            {
                if (!problems.TryGetValue(what, out var set)) problems[what] = set = new SortedSet<string>();
                set.Add(where);
            }
            void Rec(Item it, ElementId id, string param, string revitParam, bool typeLevel, string value,
                     ValueCell cell, string result, bool ok)
            {
                records.Add(new WriteRecord
                {
                    ElementId = id, Item = it, Param = param, RevitParam = revitParam, TypeLevel = typeLevel,
                    Value = value, Status = cell?.Status ?? "", Source = cell?.Source ?? "", Result = result, Ok = ok
                });
            }
            void RecAll(Item it, string param, string revitParam, bool typeLevel, string value, ValueCell cell,
                        string result, bool ok)
            {
                foreach (var id in it.InstanceIds) Rec(it, id, param, revitParam, typeLevel, value, cell, result, ok);
            }

            var all = items.ToList();
            // исключённые правилом элементы — тоже в отчёт, чтобы было видно, что их пропустили намеренно
            foreach (var it in all.Where(i => i.Excluded != null))
                RecAll(it, "—", "", false, "", null, $"исключён правилом ({it.Excluded})", true);

            // что пишем: (элемент, параметр АГР, значение, ячейка)
            var todo = new List<(Item item, string param, string value, ValueCell cell)>();
            foreach (var it in all.Where(i => i.Excluded == null))
                foreach (var c in it.Cells.Values)
                {
                    var cs = settings.For(it.CategoryKey);
                    if (!cs.IsOn(c.Param)) continue;       // параметр выключен галочкой в окне маппинга
                    var bnd = cs.Get(c.Param);
                    if (c.Status == "исключить")
                    {
                        RecAll(it, c.Param, bnd?.RevitParam, bnd?.IsType == true, c.Value, c, "исключено при проверке", true);
                        continue;
                    }
                    if (string.IsNullOrWhiteSpace(c.Value))
                    {
                        RecAll(it, c.Param, bnd?.RevitParam, bnd?.IsType == true, "", c, "не заполнено: нет значения", false);
                        continue;
                    }
                    var value = c.Param == CategoryDefinitions.ExportAs
                        ? c.Value.Split(new[] { " (" }, 2, System.StringSplitOptions.None)[0] : c.Value;
                    todo.Add((it, c.Param, value, c));
                    if (Classifier.NameParam.TryGetValue(c.Param, out var nameParam) && !string.IsNullOrEmpty(c.Name)
                        && cs.IsOn(nameParam))
                        todo.Add((it, nameParam, c.Name, c));
                }

            // в параметр ТИПА нельзя записать разные значения для разных ролей одного типа
            var conflicts = new HashSet<(ElementId, string)>(todo
                .Where(t => !(t.item.TypeId is null) && settings.For(t.item.CategoryKey).Get(t.param)?.IsType == true)
                .GroupBy(t => (t.item.TypeId, t.param))
                .Where(g => g.Select(t => t.value).Distinct().Count() > 1)
                .Select(g => g.Key));

            Transaction tr = null;
            if (!dryRun)
            {
                tr = new Transaction(doc, "АтрибутыАГР: заполнение параметров АГР");
                tr.Start();
            }
            try
            {
                foreach (var (item, param, value, cell) in todo)
                {
                    var b = settings.For(item.CategoryKey).Get(param);
                    if (b == null || string.IsNullOrEmpty(b.RevitParam))
                    {
                        Problem($"не задан параметр Revit для {param}", item.CategoryKey);
                        RecAll(item, param, "", false, value, cell, "не заполнено: не выбран параметр Revit", false);
                        continue;
                    }
                    bool typeLevel = b.IsType && !(item.TypeId is null);
                    if (typeLevel && conflicts.Contains((item.TypeId, param)))
                    {
                        Problem($"{param}: у одного типа разные значения (пропущено — задайте параметр экземпляра)",
                            item.F("type_full"));
                        RecAll(item, param, b.RevitParam, true, value, cell,
                            "не заполнено: у типа разные значения в разных ролях", false);
                        continue;
                    }
                    var targets = typeLevel
                        ? new List<Element> { doc.GetElement(item.TypeId) }
                        : item.InstanceIds.Select(id => doc.GetElement(id)).ToList();
                    foreach (var el in targets.Where(x => x != null))
                    {
                        string where = item.F("type_full");
                        string result;
                        bool ok;
                        var p = el.LookupParameter(b.RevitParam);
                        if (p == null) { Problem($"нет параметра «{b.RevitParam}»", where); result = "не заполнено: нет такого параметра у элемента"; ok = false; }
                        else if (p.IsReadOnly) { Problem($"«{b.RevitParam}» только для чтения", where); result = "не заполнено: параметр только для чтения"; ok = false; }
                        else if (SameValue(p, value)) { same++; result = "уже стояло это значение"; ok = true; }
                        else if (!b.Overwrite && HasValue(p)) { kept++; result = "не перезаписано: уже было заполнено"; ok = false; }
                        else if (dryRun) { written++; result = "будет записано"; ok = true; }
                        else if (SetValue(p, value)) { written++; result = "записано"; ok = true; }
                        else { Problem($"не удалось записать «{b.RevitParam}» = {value}", where); result = "не заполнено: ошибка записи"; ok = false; }

                        // запись в тип отражаем у каждого экземпляра этого типа
                        if (typeLevel) RecAll(item, param, b.RevitParam, true, value, cell, result, ok);
                        else Rec(item, el.Id, param, b.RevitParam, false, value, cell, result, ok);
                    }
                    if (!dryRun) item.Current[param] = value;
                }
                tr?.Commit();
            }
            catch
            {
                if (tr != null && tr.HasStarted() && !tr.HasEnded()) tr.RollBack();
                throw;
            }
            finally
            {
                tr?.Dispose();
            }

            LastRecords = records;
            LastWasDryRun = dryRun;

            var sb = new StringBuilder();
            sb.AppendLine(dryRun ? $"Будет записано значений: {written}" : $"Записано значений: {written}");
            sb.AppendLine($"Уже стояло то же значение: {same}");
            if (kept > 0) sb.AppendLine($"Оставлено как было (уже заполнено, перезапись выключена): {kept}");
            foreach (var kv in problems)
            {
                sb.AppendLine().AppendLine($"{kv.Key}: {kv.Value.Count}");
                foreach (var w in kv.Value.Take(8)) sb.AppendLine("   " + w);
                if (kv.Value.Count > 8) sb.AppendLine("   …");
            }
            return sb.ToString();
        }

        static bool? YesNo(string v)
        {
            switch ((v ?? "").Trim().ToLowerInvariant())
            {
                case "да": case "true": case "1": case "yes": return true;
                case "нет": case "false": case "0": case "no": return false;
                default: return null;
            }
        }

        /// <summary>Параметр уже заполнен: непустой текст, ненулевое число / да-нет считается заполненным, если HasValue.</summary>
        static bool HasValue(Parameter p)
        {
            if (!p.HasValue) return false;
            switch (p.StorageType)
            {
                case StorageType.String: return !string.IsNullOrWhiteSpace(p.AsString());
                case StorageType.ElementId: return p.AsElementId() != ElementId.InvalidElementId;
                default: return true;
            }
        }

        static bool SameValue(Parameter p, string value)
        {
            switch (p.StorageType)
            {
                case StorageType.String: return (p.AsString() ?? "") == value;
                case StorageType.Integer:
                    var yn = YesNo(value);
                    return yn.HasValue ? p.AsInteger() == (yn.Value ? 1 : 0)
                                       : int.TryParse(value, out var i) && p.AsInteger() == i;
                default: return (p.AsValueString() ?? "") == value;
            }
        }

        /// <summary>Текст — как есть; да/нет — в 1/0; числа — в единицах проекта (толщина в мм).</summary>
        static bool SetValue(Parameter p, string value)
        {
            switch (p.StorageType)
            {
                case StorageType.String:
                    return p.Set(value);
                case StorageType.Integer:
                    var yn = YesNo(value);
                    if (yn.HasValue) return p.Set(yn.Value ? 1 : 0);
                    return int.TryParse(value, out var i) && p.Set(i);
                case StorageType.Double:
                    return p.SetValueString(value.Replace(",", ".")) ||
                           (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var d)
                            && p.SetValueString(d.ToString(CultureInfo.CurrentCulture)));
                default:
                    return false;
            }
        }
    }
}
