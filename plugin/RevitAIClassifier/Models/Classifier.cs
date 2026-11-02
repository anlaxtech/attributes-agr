using System;
using System.Collections.Generic;

namespace RevitAIClassifier.Models
{
    /// <summary>Строка классификатора для окна выбора кода.</summary>
    public class ClassifierEntry
    {
        public string Code { get; set; }
        public string Name { get; set; }
        /// <summary>Сколько типов в разметке с этим кодом (0 — код ещё не использовался).</summary>
        public int Used { get; set; }
        /// <summary>Уровень вложенности: «ЭЛ 30 18» — 2, «ЭЛ 30 18 30 31» — 4.</summary>
        public int Level => Math.Max(0, (Code ?? "").Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries).Length - 2);
        public System.Windows.Thickness Indent => new System.Windows.Thickness(Level * 12, 0, 0, 0);
        public string UsedText => Used > 0 ? $"★ {Used}" : "";
        /// <summary>Текст для поиска: код (с пробелами и без), наименование, в нижнем регистре.</summary>
        public string SearchText { get; set; }
    }

    /// <summary>
    /// Классификаторы от сервиса: «Кл. Элементы», «Кл. Материалы», «Кл. Помещения»,
    /// какой параметр-код к какому классификатору относится и какой параметр — его наименование.
    /// </summary>
    public static class Classifier
    {
        public static Dictionary<string, List<ClassifierEntry>> Sheets { get; } = new Dictionary<string, List<ClassifierEntry>>();
        static readonly Dictionary<string, Dictionary<string, string>> _names = new Dictionary<string, Dictionary<string, string>>();
        /// <summary>Параметр-код → лист классификатора.</summary>
        public static Dictionary<string, string> ParamSheet { get; } = new Dictionary<string, string>();
        /// <summary>Параметр-код → параметр-наименование (RUS_MSSK_Element_Code → RUS_MSSK_Element_Name).</summary>
        public static Dictionary<string, string> NameParam { get; } = new Dictionary<string, string>();
        /// <summary>Порядок параметров (лист «Параметры» таблицы правил).</summary>
        public static List<string> Order { get; } = new List<string>();
        /// <summary>Описание параметра из листа «Параметры» («Плавающая отметка пола»).</summary>
        public static Dictionary<string, string> Descriptions { get; } = new Dictionary<string, string>();

        /// <summary>«RUS_GroundFloor · Плавающая отметка пола» — для колонки «Параметр».</summary>
        public static string Title(string param)
        {
            if (param == null || !Descriptions.TryGetValue(param, out var d) || string.IsNullOrWhiteSpace(d)) return param;
            var cut = d.IndexOfAny(new[] { '.', '(', ';' });
            if (cut > 0) d = d.Substring(0, cut);
            d = d.Trim();
            if (d.Length > 45) d = d.Substring(0, 45) + "…";
            return $"{param} · {d}";
        }

        public static void Clear()
        {
            Sheets.Clear();
            _names.Clear();
            ParamSheet.Clear();
            NameParam.Clear();
            Order.Clear();
            Descriptions.Clear();
        }

        public static void Add(string sheet, string code, string name, int used)
        {
            if (string.IsNullOrEmpty(code)) return;
            if (!Sheets.TryGetValue(sheet, out var list))
            {
                Sheets[sheet] = list = new List<ClassifierEntry>();
                _names[sheet] = new Dictionary<string, string>();
            }
            if (_names[sheet].ContainsKey(code)) return;
            _names[sheet][code] = name;
            list.Add(new ClassifierEntry
            {
                Code = code,
                Name = name,
                Used = used,
                SearchText = Normalize(code + " " + code.Replace(" ", "") + " " + name)
            });
        }

        public static bool HasClassifier(string param) => param != null && ParamSheet.ContainsKey(param);

        public static List<ClassifierEntry> EntriesFor(string param) =>
            HasClassifier(param) && Sheets.TryGetValue(ParamSheet[param], out var l) ? l : new List<ClassifierEntry>();

        public static string NameOf(string param, string code)
        {
            if (code == null || !HasClassifier(param)) return "";
            return _names.TryGetValue(ParamSheet[param], out var d) && d.TryGetValue(code, out var n) ? n : "";
        }

        public static string Normalize(string s) => (s ?? "").ToLowerInvariant().Replace('ё', 'е');
    }
}
