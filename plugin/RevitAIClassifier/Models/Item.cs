using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using Autodesk.Revit.DB;

namespace RevitAIClassifier.Models
{
    /// <summary>
    /// Что заполняем: тип Revit в одной роли (большинство категорий)
    /// или отдельный экземпляр (помещения и зоны). Двери дополнительно делятся
    /// по помещениям с двух сторон — у одного типа двери могут быть разные коды.
    /// </summary>
    public class Item
    {
        public string Id { get; set; }
        public string CategoryKey { get; set; }        // категория плагина (левый список окна маппинга)
        public bool ByInstance { get; set; }
        /// <summary>Исключён правилом «Исключить элемент» (проёмы, лифты…) — не проверяется и не пишется.</summary>
        public string Excluded { get; set; }
        public ElementId TypeId { get; set; }          // null у помещений и зон
        public List<ElementId> InstanceIds { get; } = new List<ElementId>();

        /// <summary>Признаки для правил и модели — ключи как в таблице правил (revit_category, type_full…).</summary>
        public Dictionary<string, string> Features { get; } = new Dictionary<string, string>();
        /// <summary>Что сейчас стоит в параметрах Revit (по маппингу).</summary>
        public Dictionary<string, string> Current { get; } = new Dictionary<string, string>();
        /// <summary>Параметр АГР → значение-ячейка окна проверки.</summary>
        public Dictionary<string, ValueCell> Cells { get; } = new Dictionary<string, ValueCell>();

        public string F(string key) => Features.TryGetValue(key, out var v) ? v ?? "" : "";
        public string Category => F("revit_category");
        public string Family => ByInstance ? Category : F("type_full").Split(new[] { ':' }, 2)[0];
        public string TypeName
        {
            get
            {
                var t = F("type_full");
                var name = t.Contains(":") ? t.Split(new[] { ':' }, 2)[1] : t;
                var rooms = F("room_from") + F("room_to") == "" ? "" : $"  [{F("room_from")} → {F("room_to")}]";
                var purpose = ByInstance && F("space_purpose") != "" ? $"  [{F("space_purpose")}]" : "";
                return name + rooms + purpose;
            }
        }
        public int Count => InstanceIds.Count;

        /// <summary>Значения, которые пользователь подтвердил или исправил: сервис их не пересчитывает.</summary>
        public Dictionary<string, string> Fixed() =>
            Cells.Values.Where(c => c.Status == "проверено" && !string.IsNullOrEmpty(c.Value))
                 .ToDictionary(c => c.Param, c => c.Value);
    }

    /// <summary>Одно значение одного параметра — строка таблицы во вкладке.</summary>
    public class ValueCell : INotifyPropertyChanged
    {
        public ValueCell(Item item, string param)
        {
            Item = item;
            Param = param;
        }

        public Item Item { get; }
        public string Param { get; }

        // для колонок таблицы
        public string ParamTitle => Classifier.Title(Param);
        public string Category => Item.Category;
        public string Family => Item.Family;
        public string TypeName => Item.TypeName;
        public int Count => Item.Count;
        public string Current => Item.Current.TryGetValue(Param, out var c) ? c : "";
        public bool HasClassifier => Classifier.HasClassifier(Param);

        public string Predicted { get; private set; } = "";
        public string Source { get; private set; } = "";
        public double Conf { get; private set; }
        public List<string> Options { get; private set; } = new List<string>();
        public bool Edited => Value != Predicted;

        bool _loading;
        string _value = "", _name = "", _status = "";

        public string Value
        {
            get => _value;
            set
            {
                value = value ?? "";
                if (_value == value) return;
                _value = value;
                if (HasClassifier) Name = Classifier.NameOf(Param, value);
                if (!_loading) Status = "проверено";
                Changed(nameof(Value));
            }
        }
        public string Name { get => _name; set { _name = value ?? ""; Changed(nameof(Name)); } }
        public string Status { get => _status; set { _status = value ?? ""; Changed(nameof(Status)); } }

        public void SetPrediction(string value, string name, string source, double conf, string status, List<string> options)
        {
            _loading = true;
            Predicted = value ?? "";
            Value = Predicted;
            Name = string.IsNullOrEmpty(name) && HasClassifier ? Classifier.NameOf(Param, Predicted) : name;
            Source = source;
            Conf = conf;
            Status = status;
            Options = options ?? new List<string>();
            _loading = false;
            Changed(nameof(Source));
            Changed(nameof(Conf));
            Changed(nameof(Options));
        }

        public void RefreshCurrent() => Changed(nameof(Current));

        public event PropertyChangedEventHandler PropertyChanged;
        void Changed(string n) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
    }

    /// <summary>Вкладки окна проверки — шаги схемы. Порядок важен: следующие шаги зависят от предыдущих.</summary>
    public static class Steps
    {
        public class Step
        {
            public string Title { get; set; }
            public string[] Params { get; set; }   // null — «всё остальное»
        }

        public static readonly List<Step> All = new List<Step>
        {
            new Step { Title = "1. IfcExportAs", Params = new[] { "IfcExportAs" } },
            new Step { Title = "2. Классификатор", Params = new[] { "RUS_MSSK_Element_Code", "RUS_MSSK_SpaceAndZone_Code" } },
            new Step { Title = "3. Группа модели", Params = new[] { "RUS_Name" } },
            new Step { Title = "4. Материалы", Params = new[] { "RUS_MSSK_Material_Code" } },
            new Step { Title = "5. Прочее", Params = null },
        };

        public static bool InStep(Step step, string param) =>
            step.Params != null
                ? step.Params.Contains(param)
                : !All.Where(s => s.Params != null).SelectMany(s => s.Params).Contains(param);
    }
}
