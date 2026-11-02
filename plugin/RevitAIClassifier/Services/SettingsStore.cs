using System;
using System.IO;
using System.Linq;
using System.Text;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>Сохранение настроек в JSON: автоматически в %AppData% и вручную через импорт/экспорт.</summary>
    public static class SettingsStore
    {
        public static string DefaultDir =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RevitAIClassifier");

        public static string DefaultPath => Path.Combine(DefaultDir, "settings.json");

        /// <summary>Папка, где лежит dll плагина (туда установщик кладёт service_url.txt и company_settings.json).</summary>
        static string PluginDir => Path.GetDirectoryName(typeof(SettingsStore).Assembly.Location);

        /// <summary>
        /// Настройки пользователя. Если их ещё нет — берутся настройки компании из установщика
        /// (company_settings.json рядом с dll). Адрес сервера — из service_url.txt, если пользователь
        /// сам его не менял.
        /// </summary>
        public static PluginSettings LoadDefault()
        {
            PluginSettings s;
            var company = Path.Combine(PluginDir, "company_settings.json");
            if (File.Exists(DefaultPath)) s = Load(DefaultPath);
            else if (File.Exists(company)) s = Load(company);
            else s = EnsureDefinitions(new PluginSettings());

            var urlFile = Path.Combine(PluginDir, "service_url.txt");
            if (File.Exists(urlFile))
            {
                var url = File.ReadAllText(urlFile).Trim();
                bool local = string.IsNullOrEmpty(s.ServiceUrl) || s.ServiceUrl.Contains("127.0.0.1") ||
                             s.ServiceUrl.Contains("localhost");
                if (url != "" && local) s.ServiceUrl = url;
            }
            return s;
        }

        public static void SaveDefault(PluginSettings s) => Save(s, DefaultPath);

        public static PluginSettings Load(string path)
        {
            var json = File.ReadAllText(path, Encoding.UTF8);
            var s = Json.Deserialize<PluginSettings>(json) ?? new PluginSettings();
            return EnsureDefinitions(s);
        }

        public static void Save(PluginSettings s, string path)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, Pretty(Json.Serialize(s)), new UTF8Encoding(true));
        }

        static readonly System.Collections.Generic.Dictionary<string, string> Renamed =
            new System.Collections.Generic.Dictionary<string, string>
            {
                ["RUS_ResidentalRoom"] = "RUS_ResidentialRoom",
            };

        /// <summary>Добавляет категории и параметры, которых нет в файле (например, после обновления плагина).</summary>
        public static PluginSettings EnsureDefinitions(PluginSettings s)
        {
            foreach (var def in CategoryDefinitions.All)
            {
                var cs = s.For(def.Key);
                // переименованные параметры АГР — переносим выбор пользователя на новое имя
                foreach (var p in cs.Params)
                    if (Renamed.TryGetValue(p.IfcName ?? "", out var newName) && cs.Get(newName) == null)
                        p.IfcName = newName;
                // параметры, убранные из плагина (например, RUS_Object), удаляем из настроек
                cs.Params = cs.Params.Where(p => System.Array.IndexOf(def.IfcParams, p.IfcName) >= 0).ToList();
                foreach (var ifc in def.IfcParams)
                    if (cs.Get(ifc) == null)
                        cs.Params.Add(new ParamBinding { IfcName = ifc, RevitParam = "", IsType = false });
                // порядок — как в определении
                cs.Params = cs.Params.OrderBy(p =>
                {
                    int i = Array.IndexOf(def.IfcParams, p.IfcName);
                    return i < 0 ? int.MaxValue : i;
                }).ToList();
            }
            return s;
        }

        /// <summary>Отступы в JSON, чтобы файл можно было читать и править руками.</summary>
        static string Pretty(string json)
        {
            var sb = new StringBuilder();
            int indent = 0;
            bool inString = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (c == '"' && (i == 0 || json[i - 1] != '\\')) inString = !inString;
                if (inString) { sb.Append(c); continue; }
                switch (c)
                {
                    case '{':
                    case '[':
                        sb.Append(c).AppendLine().Append(new string(' ', ++indent * 2));
                        break;
                    case '}':
                    case ']':
                        sb.AppendLine().Append(new string(' ', --indent * 2)).Append(c);
                        break;
                    case ',':
                        sb.Append(c).AppendLine().Append(new string(' ', indent * 2));
                        break;
                    case ':':
                        sb.Append(": ");
                        break;
                    default:
                        sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }
    }
}
