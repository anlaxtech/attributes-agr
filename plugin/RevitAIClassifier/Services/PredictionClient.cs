using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Text;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>Обращение к Python-сервису (service.py v2: таблица правил + обучение).</summary>
    public class PredictionClient
    {
        readonly string _url;

        readonly string _token;

        public PredictionClient(string url, string token = null)
        {
            _url = url.TrimEnd('/');
            _token = token ?? "";
        }

        WebClient NewClient()
        {
            var c = new Client { Encoding = Encoding.UTF8 };
            if (_token != "") c.Headers["X-AGR-Token"] = _token;
            return c;
        }

        class Client : WebClient
        {
            protected override WebRequest GetWebRequest(Uri address)
            {
                var r = base.GetWebRequest(address);
                r.Timeout = 180_000;
                return r;
            }
        }

        string Get(string path)
        {
            using (var c = NewClient())
                return c.DownloadString(_url + path);
        }

        string Post(string path, object body)
        {
            using (var c = NewClient())
            {
                c.Headers[HttpRequestHeader.ContentType] = "application/json; charset=utf-8";
                return c.UploadString(_url + path, Json.Serialize(body));
            }
        }

        /// <summary>Проверка связи. Возвращает текст ошибки или null.</summary>
        public string Check()
        {
            try { Get("/health"); return null; }
            catch (Exception ex)
            {
                return $"Сервис предсказаний не отвечает ({_url}).\n\n" +
                       "Запустите его в папке со скриптами:\n    py service.py Правила_АГР.xlsx labels.xlsx\n\n" +
                       ex.Message;
            }
        }

        static string S(object o) => o?.ToString() ?? "";

        public void LoadClassifiers()
        {
            var d = Json.ParseObject(Get("/classifiers"));
            Classifier.Clear();
            foreach (var kv in (Dictionary<string, object>)d["classifiers"])
                foreach (Dictionary<string, object> r in (IEnumerable)kv.Value)
                    Classifier.Add(kv.Key, S(r["code"]), S(r["name"]),
                        r.TryGetValue("used", out var u) && u != null ? Convert.ToInt32(u) : 0);
            foreach (var kv in (Dictionary<string, object>)d["param_classifier"])
                Classifier.ParamSheet[kv.Key] = S(kv.Value);
            foreach (var kv in (Dictionary<string, object>)d["name_param"])
                Classifier.NameParam[kv.Key] = S(kv.Value);
            foreach (var p in (IEnumerable)d["order"])
                Classifier.Order.Add(S(p));
            if (d.TryGetValue("descriptions", out var ds) && ds is Dictionary<string, object> dd)
                foreach (var kv in dd) Classifier.Descriptions[kv.Key] = S(kv.Value);
        }

        /// <summary>Правки пользователя → сервер (data/corrections.csv).</summary>
        public void SendCorrections(List<Dictionary<string, string>> rows)
        {
            const int batch = 1000;
            for (int i = 0; i < rows.Count; i += batch)
                Post("/corrections", new { rows = rows.Skip(i).Take(batch).ToList() });
        }

        /// <summary>
        /// Отправляет все элементы и получает значения всех параметров.
        /// Значения со статусом «проверено» уходят как исправленные: сервис их не меняет,
        /// а следующие шаги пересчитывает с их учётом.
        /// </summary>
        public void PredictAll(IList<Item> items)
        {
            const int batch = 300;
            for (int i = 0; i < items.Count; i += batch)
            {
                var part = items.Skip(i).Take(batch).ToList();
                var body = new
                {
                    items = part.Select(t => new Dictionary<string, object>
                    {
                        ["id"] = t.Id,
                        ["features"] = t.Features,
                        ["fixed"] = t.Fixed(),
                    }).ToList()
                };
                var result = Json.ParseList(Post("/predict_all", body));
                var byId = part.ToDictionary(t => t.Id);
                foreach (var r in result)
                {
                    if (!byId.TryGetValue(S(r["id"]), out var item)) continue;
                    item.Excluded = r.TryGetValue("excluded", out var ex) && ex != null ? S(ex) : null;
                    var values = (Dictionary<string, object>)r["values"];
                    // параметры, которые больше не относятся к элементу (например, сменился IfcExportAs)
                    foreach (var gone in item.Cells.Keys.Where(k => !values.ContainsKey(k)).ToList())
                        item.Cells.Remove(gone);
                    foreach (var kv in values)
                    {
                        var v = (Dictionary<string, object>)kv.Value;
                        if (!item.Cells.TryGetValue(kv.Key, out var cell))
                            item.Cells[kv.Key] = cell = new ValueCell(item, kv.Key);
                        if (cell.Status == "проверено") continue;   // исправленное пользователем не трогаем
                        var options = v.TryGetValue("options", out var o) && o is IEnumerable e
                            ? e.Cast<object>().Select(S).ToList() : new List<string>();
                        cell.SetPrediction(S(v["value"]), v.TryGetValue("name", out var n) ? S(n) : "",
                            S(v["source"]), Convert.ToDouble(v["conf"]), S(v["status"]), options);
                    }
                }
            }
        }
    }
}
