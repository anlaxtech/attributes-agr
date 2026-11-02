using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevitAIClassifier.Models
{
    /// <summary>
    /// Строка окна проверки. Обычно это одно значение (ValueCell), но объединяются в одну строку:
    ///   • помещения и зоны с одинаковым именем и назначением;
    ///   • модели в контексте с одинаковым именем семейства без номера («Лоджия 39», «Лоджия 40» → «Лоджия»).
    /// В группу попадают только значения с одинаковым предложенным значением. Правка строки — для всей группы.
    /// </summary>
    public class RowCell : INotifyPropertyChanged
    {
        public RowCell(List<ValueCell> cells)
        {
            Cells = cells;
            foreach (var c in cells) c.PropertyChanged += (s, e) => Changed(e.PropertyName);
        }

        public List<ValueCell> Cells { get; }
        public ValueCell First => Cells[0];
        public Item Item => First.Item;

        public string Param => First.Param;
        public string ParamTitle => First.ParamTitle;

        /// <summary>Ключ группы; у раскрытой группы он есть и у каждой её строки.</summary>
        public string GroupKey { get; private set; }
        /// <summary>Строка — отдельный элемент раскрытой группы.</summary>
        public bool IsChild { get; private set; }
        /// <summary>Ключ сортировки: строки раскрытой группы идут подряд, на месте группы.</summary>
        public string SortKey { get; private set; } = "";
        /// <summary>Кнопка в первой колонке: «▸ 12» — раскрыть группу, «▾» — свернуть.</summary>
        public string ToggleText => IsChild ? "▾" : IsGroup ? $"▸ {Cells.Count}" : "";
        public string Category => First.Category;
        public bool InPlaceGroup => IsGroup && !Item.ByInstance;
        public string Family => InPlaceGroup ? BaseName(First.Family) + " …" : First.Family;
        public string TypeName
        {
            get
            {
                if (InPlaceGroup) return $"модели в контексте: {Cells.Count} шт.";
                if (!IsChild) return First.TypeName;
                // отдельный элемент раскрытой группы — чем он отличается от соседей
                if (Item.ByInstance)
                    return $"   └ {First.TypeName}  № {Item.F("space_number")}  {Item.F("level")}".TrimEnd();
                return $"   └ {Item.F("type_full")}";
            }
        }
        public int Count => Cells.Sum(c => c.Count);
        public bool HasClassifier => First.HasClassifier;
        public List<string> Options => First.Options;
        public string Source => First.Source;
        public double Conf => Cells.Min(c => c.Conf);
        public string Name => First.Name;
        public bool IsGroup => Cells.Count > 1;

        /// <summary>Имя без номера в конце: «Лоджия 39» → «Лоджия», «Карниз33» → «Карниз».</summary>
        public static string BaseName(string name) =>
            Regex.Replace((name ?? "").Trim(), @"[\s_\-\.]*\(?\d+\)?$", "").Trim();

        public string Current
        {
            get
            {
                var cur = Cells.Select(c => c.Current).Distinct().ToList();
                return cur.Count == 1 ? cur[0] : "разные";
            }
        }

        public string Value
        {
            get => First.Value;
            set { foreach (var c in Cells) c.Value = value; }
        }

        public string Status
        {
            get
            {
                var st = Cells.Select(c => c.Status).Distinct().ToList();
                if (st.Count == 1) return st[0];
                return st.Contains("проверить") ? "проверить" : st[0];
            }
            set { foreach (var c in Cells) c.Status = value; }
        }

        public void RefreshCurrent()
        {
            foreach (var c in Cells) c.RefreshCurrent();
        }

        /// <summary>
        /// Строки для таблицы. Помещения/зоны и модели в контексте группируются (если включено);
        /// группы из expanded показываются поштучно, но подряд, на месте группы.
        /// </summary>
        public static List<RowCell> Build(IEnumerable<ValueCell> cells, bool group, ISet<string> expanded)
        {
            var rows = new List<RowCell>();
            var groups = new Dictionary<string, List<ValueCell>>();
            foreach (var c in cells)
            {
                string key = null;
                if (group && c.Item.ByInstance)
                    // имя + назначение + что предложено: разные номера квартир останутся разными строками
                    key = string.Join("|", "space", c.Param, c.Item.CategoryKey, c.Item.F("space_name"),
                                      c.Item.F("space_purpose"), c.Predicted, c.Edited ? c.Value : "");
                else if (group && c.Item.F("in_place") == "да")
                    key = string.Join("|", "inplace", c.Param, c.Item.CategoryKey, c.Category,
                                      BaseName(c.Family).ToLowerInvariant(), c.Predicted, c.Edited ? c.Value : "");
                if (key == null)
                {
                    var r = new RowCell(new List<ValueCell> { c });
                    r.SortKey = r.MakeSortKey(r.Status);
                    rows.Add(r);
                    continue;
                }
                if (!groups.TryGetValue(key, out var list)) groups[key] = list = new List<ValueCell>();
                list.Add(c);
            }
            foreach (var kv in groups)
            {
                var whole = new RowCell(kv.Value) { GroupKey = kv.Value.Count > 1 ? kv.Key : null };
                var sort = whole.MakeSortKey(whole.Status);
                if (kv.Value.Count > 1 && expanded != null && expanded.Contains(kv.Key))
                {
                    int i = 0;
                    foreach (var c in kv.Value.OrderBy(x => x.Item.F("space_number")).ThenBy(x => x.Item.F("type_full")))
                        rows.Add(new RowCell(new List<ValueCell> { c })
                        { GroupKey = kv.Key, IsChild = true, SortKey = sort + "|" + (i++).ToString("D5") });
                }
                else
                {
                    whole.SortKey = sort;
                    rows.Add(whole);
                }
            }
            return rows.OrderBy(r => r.SortKey, System.StringComparer.CurrentCulture).ToList();
        }

        string MakeSortKey(string status) =>
            string.Join("|", status == "проверить" ? "0" : "1", Category, Family, First.TypeName, Param);

        public event PropertyChangedEventHandler PropertyChanged;
        void Changed(string n)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
            if (n == nameof(ValueCell.Status) || n == nameof(ValueCell.Value))
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Current)));
        }
    }
}
