using System;
using System.Windows.Interop;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevitAIClassifier.Services;
using RevitAIClassifier.Views;

namespace RevitAIClassifier
{
    /// <summary>
    /// Открывает окно маппинга. Окно модальное, поэтому из него можно сразу
    /// менять документ (транзакции открываются в ParameterWriter).
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class MainCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            Document doc = data.Application.ActiveUIDocument?.Document;
            if (doc == null || doc.IsFamilyDocument)
            {
                TaskDialog.Show("АтрибутыАГР", "Откройте модель проекта (не семейство).");
                return Result.Cancelled;
            }
            try
            {
                var settings = SettingsStore.LoadDefault();
                var window = new MappingWindow(doc, settings);
                new WindowInteropHelper(window).Owner = data.Application.MainWindowHandle;
                window.ShowDialog();
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = ex.Message;
                TaskDialog.Show("АтрибутыАГР: ошибка", ex.ToString());
                return Result.Failed;
            }
        }
    }
}
