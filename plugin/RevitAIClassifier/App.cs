using System.Reflection;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;

namespace RevitAIClassifier
{
    /// <summary>Вкладка «АГР» с кнопкой запуска плагина.</summary>
    public class App : IExternalApplication
    {
        public Result OnStartup(UIControlledApplication app)
        {
            const string tab = "АтрибутыАГР";
            try { app.CreateRibbonTab(tab); } catch { /* вкладка уже есть */ }
            var panel = app.CreateRibbonPanel(tab, "Классификация");
            var button = new PushButtonData("AgrMapping", "Атрибуты\nАГР",
                Assembly.GetExecutingAssembly().Location, typeof(MainCommand).FullName)
            {
                ToolTip = "АтрибутыАГР: заполнение параметров АГР — IfcExportAs, классификаторы, группы модели, материалы, помещения и зоны",
                LargeImage = Icon("RevitAIClassifier.icon32.png"),
                Image = Icon("RevitAIClassifier.icon16.png")
            };
            panel.AddItem(button);
            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication app) => Result.Succeeded;

        /// <summary>Иконка из ресурсов dll. Если не нашлась — кнопка просто будет без иконки.</summary>
        static ImageSource Icon(string name)
        {
            try
            {
                var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name);
                if (stream == null) return null;
                var img = new BitmapImage();
                img.BeginInit();
                img.StreamSource = stream;
                img.CacheOption = BitmapCacheOption.OnLoad;
                img.EndInit();
                img.Freeze();
                return img;
            }
            catch
            {
                return null;
            }
        }
    }
}
