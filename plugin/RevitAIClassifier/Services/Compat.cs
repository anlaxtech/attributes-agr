using System.Collections;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
#if NETFRAMEWORK
using System.Web.Script.Serialization;
#else
using System.Text.Encodings.Web;
using System.Text.Json;
#endif

namespace RevitAIClassifier.Services
{
    /// <summary>
    /// Различия между версиями Revit в одном месте.
    /// Revit 2020–2024 — .NET Framework, Revit 2025+ — .NET 8; в Revit 2024 ElementId стал 64-битным.
    /// </summary>
    public static class Compat
    {
        /// <summary>Числовой ID элемента в любой версии Revit.</summary>
        public static long Num(this ElementId id) =>
#if REVIT2024_OR_GREATER
            id.Value;
#else
            id.IntegerValue;
#endif

        /// <summary>Открыть файл в программе по умолчанию (в .NET 8 нужен UseShellExecute).</summary>
        public static void OpenFile(string path) =>
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path) { UseShellExecute = true });
    }

    /// <summary>JSON для .NET Framework (JavaScriptSerializer) и .NET 8 (System.Text.Json) с одинаковым поведением.</summary>
    public static class Json
    {
#if NETFRAMEWORK
        static JavaScriptSerializer S => new JavaScriptSerializer { MaxJsonLength = int.MaxValue };

        public static string Serialize(object o) => S.Serialize(o);
        public static T Deserialize<T>(string s) => S.Deserialize<T>(s);

        /// <summary>Дерево: Dictionary&lt;string, object&gt;, списки (IEnumerable), строки, числа, bool, null.</summary>
        public static object Parse(string s) => S.DeserializeObject(s);
#else
        static readonly JsonSerializerOptions Options = new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,   // кириллица — как есть, без \u0410
            PropertyNameCaseInsensitive = true,
        };

        public static string Serialize(object o) => JsonSerializer.Serialize(o, o?.GetType() ?? typeof(object), Options);
        public static T Deserialize<T>(string s) => JsonSerializer.Deserialize<T>(s, Options);

        public static object Parse(string s)
        {
            using (var doc = JsonDocument.Parse(s))
                return Convert(doc.RootElement);
        }

        static object Convert(JsonElement e)
        {
            switch (e.ValueKind)
            {
                case JsonValueKind.Object:
                    return e.EnumerateObject().ToDictionary(p => p.Name, p => Convert(p.Value));
                case JsonValueKind.Array:
                    return e.EnumerateArray().Select(Convert).ToList();
                case JsonValueKind.String:
                    return e.GetString();
                case JsonValueKind.Number:
                    return e.TryGetInt64(out var l) ? (object)l : e.GetDouble();
                case JsonValueKind.True:
                    return true;
                case JsonValueKind.False:
                    return false;
                default:
                    return null;
            }
        }
#endif

        public static Dictionary<string, object> ParseObject(string s) => (Dictionary<string, object>)Parse(s);

        public static List<Dictionary<string, object>> ParseList(string s) =>
            ((IEnumerable)Parse(s)).Cast<Dictionary<string, object>>().ToList();
    }
}
