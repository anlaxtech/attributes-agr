using System.Collections.Generic;
using System.Linq;

namespace RevitAIClassifier.Models
{
    /// <summary>Какой параметр Revit соответствует параметру АГР. Пустое имя — не задан.</summary>
    public class ParamBinding
    {
        public string IfcName { get; set; }
        public string RevitParam { get; set; }
        public bool IsType { get; set; }
        /// <summary>Заполнять ли этот параметр при запуске.</summary>
        public bool Enabled { get; set; } = true;
        /// <summary>Перезаписывать ли значение, если в модели параметр уже заполнен.</summary>
        public bool Overwrite { get; set; } = true;
    }

    public class CategorySettings
    {
        public string Key { get; set; }
        /// <summary>Заполнять ли эту категорию при запуске.</summary>
        public bool Enabled { get; set; } = true;
        public List<ParamBinding> Params { get; set; } = new List<ParamBinding>();

        /// <summary>Параметр включён (нет в списке категории — считаем выключенным).</summary>
        public bool IsOn(string ifcName) => Enabled && (Get(ifcName)?.Enabled ?? false);

        /// <summary>Можно ли перезаписывать уже заполненный параметр.</summary>
        public bool CanOverwrite(string ifcName) => Get(ifcName)?.Overwrite ?? true;

        public ParamBinding Get(string ifcName) => Params.FirstOrDefault(p => p.IfcName == ifcName);
    }

    /// <summary>Все настройки плагина — сохраняются в JSON.</summary>
    public class PluginSettings
    {
        public int Version { get; set; } = 1;
        /// <summary>Адрес Python-сервиса предсказаний (service.py).</summary>
        public string ServiceUrl { get; set; } = "http://127.0.0.1:8765";
        /// <summary>Токен сервиса (если на сервере задан AGR_TOKEN). Передаётся в заголовке X-AGR-Token.</summary>
        public string ServiceToken { get; set; } = "";
        public List<CategorySettings> Categories { get; set; } = new List<CategorySettings>();
        /// <summary>Тип фасада по файлу Revit (имя документа → витражный / навесной / обычный).</summary>
        public Dictionary<string, string> FacadeTypes { get; set; } = new Dictionary<string, string>();
        /// <summary>Что заполнять: «документ» — все элементы, «вид» — только видимые на активном виде.</summary>
        public string Scope { get; set; } = "документ";

        public string FacadeFor(string docTitle) =>
            docTitle != null && FacadeTypes != null && FacadeTypes.TryGetValue(docTitle, out var f) ? f : "";

        public CategorySettings For(string key)
        {
            var c = Categories.FirstOrDefault(x => x.Key == key);
            if (c == null)
            {
                c = new CategorySettings { Key = key };
                Categories.Add(c);
            }
            return c;
        }
    }
}
