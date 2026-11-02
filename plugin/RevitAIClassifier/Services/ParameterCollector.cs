using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Services
{
    /// <summary>
    /// Список параметров для выпадающего списка: параметры типа и экземпляра,
    /// которые есть у элементов категории в проекте, плюс общие/проектные параметры,
    /// привязанные к категории (чтобы список был и в пустой категории).
    /// </summary>
    public static class ParameterCollector
    {
        const int Sample = 40;   // сколько элементов просматривать на категорию

        public static List<ParamOption> Collect(Document doc, CategoryDefinition def)
        {
            var found = new HashSet<ParamOption>();

            foreach (var (bic, _) in def.Revit)
            {
                var instances = new FilteredElementCollector(doc).OfCategory(bic)
                    .WhereElementIsNotElementType().Take(Sample).ToList();
                foreach (var e in instances)
                {
                    Add(found, e, isType: false);
                    var t = doc.GetElement(e.GetTypeId());
                    if (t != null) Add(found, t, isType: true);
                }
                foreach (var t in new FilteredElementCollector(doc).OfCategory(bic)
                             .WhereElementIsElementType().Take(Sample))
                    Add(found, t, isType: true);

                var cat = Category.GetCategory(doc, bic);
                if (cat == null) continue;
                var it = doc.ParameterBindings.ForwardIterator();
                while (it.MoveNext())
                {
                    if (it.Current is ElementBinding b && b.Categories.Contains(cat) && it.Key != null)
                        found.Add(new ParamOption { Name = it.Key.Name, IsType = b is TypeBinding });
                }
            }

            var list = new List<ParamOption> { ParamOption.None };
            list.AddRange(found.Where(o => !o.IsNone)
                .OrderByDescending(o => o.IsType)
                .ThenBy(o => o.Name.TrimStart('.', '…', '_'), System.StringComparer.CurrentCultureIgnoreCase));
            return list;
        }

        static void Add(HashSet<ParamOption> set, Element e, bool isType)
        {
            foreach (Parameter p in e.Parameters)
            {
                if (p?.Definition == null || string.IsNullOrWhiteSpace(p.Definition.Name)) continue;
                if (p.StorageType == StorageType.None) continue;
                set.Add(new ParamOption { Name = p.Definition.Name, IsType = isType });
            }
        }
    }
}
