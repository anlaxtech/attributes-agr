using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using Autodesk.Revit.DB;
using Microsoft.Win32;
using RevitAIClassifier.Models;
using RevitAIClassifier.Services;

namespace RevitAIClassifier.Views
{
    /// <summary>
    /// Проверка по шагам схемы: вкладки IfcExportAs → Классификатор → Группа модели → Материалы → Прочее.
    /// Исправления на шаге фиксируются и при «Пересчитать» учитываются в следующих шагах.
    /// </summary>
    public partial class ReviewWindow : Window
    {
        readonly Document _doc;
        readonly List<Item> _items;
        readonly PluginSettings _settings;
        readonly PredictionClient _client;
        List<ValueCell> _cells = new List<ValueCell>();   // все значения (для записи, журнала, экспорта)
        List<RowCell> _rows = new List<RowCell>();        // строки таблицы (помещения могут быть сгруппированы)
        readonly HashSet<string> _expanded = new HashSet<string>();   // раскрытые группы
        bool _written;                                                 // в этом окне уже нажимали «Записать»
        ListCollectionView _view;

        public ReviewWindow(Document doc, List<Item> items, PluginSettings settings, PredictionClient client)
        {
            InitializeComponent();
            _doc = doc;
            _items = items;
            _settings = settings;
            _client = client;
            foreach (var s in Steps.All)
                StepTabs.Items.Add(new TabItem { Header = s.Title, Tag = s });
            Rebuild();
            StepTabs.SelectedIndex = 0;
        }

        Steps.Step CurrentStep => (StepTabs.SelectedItem as TabItem)?.Tag as Steps.Step ?? Steps.All[0];

        /// <summary>Пересобрать строки после ответа сервиса (набор параметров мог измениться).</summary>
        void Rebuild()
        {
            foreach (var r in _rows) r.PropertyChanged -= Row_Changed;
            // только включённые галочками параметры и не исключённые правилами элементы
            _cells = _items.Where(i => i.Excluded == null).SelectMany(i => i.Cells.Values)
                .Where(c => _settings.For(c.Item.CategoryKey).IsOn(c.Param)).ToList();
            _rows = RowCell.Build(_cells, GroupSpaces.IsChecked == true, _expanded);
            foreach (var r in _rows) r.PropertyChanged += Row_Changed;
            _view = new ListCollectionView(_rows) { Filter = Matches };
            CellsGrid.ItemsSource = _view;
            UpdateHeaders();
        }

        /// <summary>«▸ N» — показать элементы группы поштучно, «▾» — свернуть обратно.</summary>
        void Toggle_Click(object sender, RoutedEventArgs e)
        {
            if (!(((FrameworkElement)sender).DataContext is RowCell row) || row.GroupKey == null) return;
            CellsGrid.CommitEdit(DataGridEditingUnit.Row, true);
            if (!_expanded.Remove(row.GroupKey)) _expanded.Add(row.GroupKey);
            var keep = row.GroupKey;
            Rebuild();
            var first = _rows.FirstOrDefault(r => r.GroupKey == keep);
            if (first != null) CellsGrid.ScrollIntoView(first);
        }

        void Group_Changed(object sender, RoutedEventArgs e)
        {
            if (_view != null) Rebuild();
        }

        bool Matches(object o)
        {
            var c = (RowCell)o;
            return Steps.InStep(CurrentStep, c.Param) && (OnlyReview.IsChecked != true || c.Status == "проверить");
        }

        void StepTabs_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (e.Source != StepTabs || _view == null) return;
            // колонка «Параметр» нужна там, где на вкладке несколько параметров
            var step = CurrentStep;
            ParamColumn.Visibility = step.Params == null || step.Params.Length > 1
                ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed;
            _view.Refresh();
            UpdateHeaders();
        }

        void Filter_Changed(object sender, RoutedEventArgs e) => _view?.Refresh();

        void Row_Changed(object sender, System.ComponentModel.PropertyChangedEventArgs e)
        {
            if (e.PropertyName == nameof(RowCell.Status) || e.PropertyName == nameof(RowCell.Value))
                UpdateHeaders();
        }

        void UpdateHeaders()
        {
            foreach (TabItem t in StepTabs.Items)
            {
                var s = (Steps.Step)t.Tag;
                int review = _rows.Count(r => Steps.InStep(s, r.Param) && r.Status == "проверить");
                t.Header = review > 0 ? $"{s.Title}  ({review})" : s.Title;
            }
            var mine = _rows.Where(r => Steps.InStep(CurrentStep, r.Param)).ToList();
            int excluded = _items.Count(i => i.Excluded != null);
            var changes = _cells.Where(c => c.Status != "исключить" && c.Value != "" && c.Value != c.Current).ToList();
            int kept = changes.Count(Kept);
            SummaryText.Text = $"Строк на вкладке: {mine.Count}   •   на проверку: " +
                               $"{mine.Count(c => c.Status == "проверить")}   •   будет изменено в модели: " +
                               $"{changes.Count - kept}" +
                               (kept > 0 ? $"   •   не перезапишутся (уже заполнены): {kept}" : "") +
                               (excluded > 0 ? $"   •   исключено правилами: {excluded}" : "");
        }

        /// <summary>Значение уже есть в модели, а перезапись для параметра выключена.</summary>
        bool Kept(ValueCell c) =>
            !string.IsNullOrWhiteSpace(c.Current) && !_settings.For(c.Item.CategoryKey).CanOverwrite(c.Param);

        /// <summary>Выбор кода. Если выделено несколько строк и щелчок по одной из них — код ставится всем.</summary>
        void Code_Click(object sender, RoutedEventArgs e)
        {
            if (!(((FrameworkElement)sender).DataContext is RowCell row)) return;
            var selected = CellsGrid.SelectedItems.OfType<RowCell>().Where(r => r.Param == row.Param).ToList();
            var targets = selected.Count > 1 && selected.Contains(row) ? selected : new List<RowCell> { row };
            int n = targets.Sum(t => t.Count);
            string what = targets.Count > 1 || row.IsGroup
                ? $"{row.Param}: код для {targets.Count} строк ({n} шт.)"
                : $"{row.Param} — {row.Category}: {row.Item.F("type_full")}";
            var code = CodePickerWindow.Pick(this, row.Value, what, Classifier.EntriesFor(row.Param));
            if (code == null) return;
            foreach (var t in targets)
            {
                t.Value = code;
                t.Status = "проверено";   // выбор того же кода — тоже подтверждение
            }
        }

        /// <summary>Сервис пересчитывает всё, кроме подтверждённого («проверено»).</summary>
        void Recalc_Click(object sender, RoutedEventArgs e)
        {
            CellsGrid.CommitEdit(DataGridEditingUnit.Row, true);
            try
            {
                using (new WaitCursor())
                    _client.PredictAll(_items);
            }
            catch (System.Exception ex)
            {
                MessageBox.Show(this, "Не удалось пересчитать:\n" + ex.Message, "АтрибутыАГР");
                return;
            }
            Rebuild();
        }

        /// <summary>Отчёт в Excel: после записи — результат, до записи — что будет записано.</summary>
        void Report_Click(object sender, RoutedEventArgs e)
        {
            CellsGrid.CommitEdit(DataGridEditingUnit.Row, true);
            var dlg = new SaveFileDialog
            {
                Filter = "Excel (*.xlsx)|*.xlsx",
                FileName = $"АтрибутыАГР_отчёт_{_doc.Title}_{System.DateTime.Now:yyyy-MM-dd_HHmm}.xlsx"
            };
            if (dlg.ShowDialog(this) != true) return;
            try
            {
                using (new WaitCursor())
                {
                    if (!_written) ParameterWriter.Write(_doc, _items, _settings, dryRun: true);
                    ReportExporter.Export(dlg.FileName, _doc, ParameterWriter.LastRecords, ParameterWriter.LastWasDryRun);
                }
                Compat.OpenFile(dlg.FileName);
            }
            catch (System.Exception ex)
            {
                MessageBox.Show(this, "Не удалось сохранить отчёт:\n" + ex.Message, "АтрибутыАГР");
            }
        }

        void Export_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new SaveFileDialog { Filter = "CSV для Excel (*.csv)|*.csv", FileName = $"АтрибутыАГР_{_doc.Title}.csv" };
            if (dlg.ShowDialog(this) == true) CsvLog.Export(dlg.FileName, _cells, _doc);
        }

        void Write_Click(object sender, RoutedEventArgs e)
        {
            CellsGrid.CommitEdit(DataGridEditingUnit.Row, true);
            int review = _cells.Count(c => c.Status == "проверить");
            if (review > 0 && MessageBox.Show(this,
                    $"{review} значений ещё на проверке. Записать их как есть?",
                    "АтрибутыАГР", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
                return;

            string report;
            using (new WaitCursor())
                report = ParameterWriter.Write(_doc, _items, _settings);
            _written = true;
            CsvLog.AppendCorrections(_cells, _doc);               // локальная копия на всякий случай
            var sent = CsvLog.Send(_client, CsvLog.CorrectionRows(_cells, _doc));
            if (sent != null) report += "\n" + sent;
            foreach (var r in _rows) r.RefreshCurrent();
            UpdateHeaders();
            if (MessageBox.Show(this, report + "\n\nСохранить отчёт в Excel (что заполнено и что нет, с ID элементов)?",
                    "АтрибутыАГР: запись", MessageBoxButton.YesNo, MessageBoxImage.Information) == MessageBoxResult.Yes)
                Report_Click(sender, e);
        }
    }
}
