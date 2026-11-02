using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using System.Windows.Data;
using Autodesk.Revit.DB;
using Microsoft.Win32;
using RevitAIClassifier.Models;
using RevitAIClassifier.Services;

namespace RevitAIClassifier.Views
{
    /// <summary>Строка списка категорий с галочкой.</summary>
    public class CategoryRow
    {
        readonly CategorySettings _cs;
        public CategoryRow(CategoryDefinition def, CategorySettings cs)
        {
            Def = def;
            _cs = cs;
        }
        public CategoryDefinition Def { get; }
        public string Key => Def.Key;
        public bool Enabled { get => _cs.Enabled; set => _cs.Enabled = value; }
    }

    /// <summary>Строка таблицы маппинга: параметр АГР ↔ параметр Revit.</summary>
    public class MappingRow : INotifyPropertyChanged
    {
        readonly ParamBinding _binding;
        ParamOption _selected;

        public MappingRow(ParamBinding binding, List<ParamOption> baseOptions)
        {
            _binding = binding;
            Options = new List<ParamOption>(baseOptions);
            var current = string.IsNullOrEmpty(binding.RevitParam)
                ? ParamOption.None
                : new ParamOption { Name = binding.RevitParam, IsType = binding.IsType };
            var match = Options.FirstOrDefault(o => o.Equals(current));
            if (match == null)
            {
                // параметр сохранён в настройках, но в проекте его нет — не теряем выбор
                match = new ParamOption { Name = current.Name, IsType = current.IsType, Missing = true };
                Options.Add(match);
            }
            _selected = match;
        }

        public string IfcName => _binding.IfcName;
        public string Marker => IfcName.EndsWith("_Name") && IfcName.StartsWith("RUS_MSSK") ? "★" : "";
        public List<ParamOption> Options { get; }
        public string KindText => _selected == null || _selected.IsNone ? "" : _selected.IsType ? "тип" : "экз.";

        public bool Enabled
        {
            get => _binding.Enabled;
            set { _binding.Enabled = value; Changed(nameof(Enabled)); }
        }

        public bool Overwrite
        {
            get => _binding.Overwrite;
            set { _binding.Overwrite = value; Changed(nameof(Overwrite)); }
        }

        public ParamOption Selected
        {
            get => _selected;
            set
            {
                if (value == null) return;
                _selected = value;
                _binding.RevitParam = _selected.Name;
                _binding.IsType = _selected.IsType;
                Changed(nameof(Selected));
                Changed(nameof(KindText));
            }
        }

        public event PropertyChangedEventHandler PropertyChanged;
        void Changed(string n) => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
    }

    public partial class MappingWindow : Window
    {
        readonly Document _doc;
        PluginSettings _settings;
        readonly Dictionary<string, List<ParamOption>> _optionsCache = new Dictionary<string, List<ParamOption>>();

        public MappingWindow(Document doc, PluginSettings settings)
        {
            InitializeComponent();
            _doc = doc;
            _settings = settings;
            Title = $"АтрибутыАГР — {doc.Title}";
            FillCategories();
            if (_settings.Scope == "вид") ScopeView.IsChecked = true; else ScopeDoc.IsChecked = true;
            ServiceUrlBox.Text = _settings.ServiceUrl;
            FacadeBox.ItemsSource = new[] { "не задан", "витражный", "навесной", "обычный" };
            var f = _settings.FacadeFor(doc.Title);
            FacadeBox.SelectedItem = string.IsNullOrEmpty(f) ? "не задан" : f;
            Closing += (s, e) => SettingsStore.SaveDefault(_settings);
        }

        void FillCategories()
        {
            int i = System.Math.Max(0, CategoryList.SelectedIndex);
            CategoryList.ItemsSource = CategoryDefinitions.All
                .Select(d => new CategoryRow(d, _settings.For(d.Key))).ToList();
            CategoryList.SelectedIndex = i;
        }

        void CategoryList_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e) =>
            ShowCategory();

        void ServiceUrl_LostFocus(object sender, RoutedEventArgs e)
        {
            var url = ServiceUrlBox.Text.Trim();
            if (url != "" && !url.StartsWith("http")) url = "http://" + url;
            _settings.ServiceUrl = url;
            ServiceUrlBox.Text = url;
        }

        void Scope_Changed(object sender, RoutedEventArgs e) =>
            _settings.Scope = ScopeView.IsChecked == true ? "вид" : "документ";

        /// <summary>Выбор параметра Revit — окно с поиском.</summary>
        void Param_Click(object sender, RoutedEventArgs e)
        {
            if (!(((FrameworkElement)sender).DataContext is MappingRow row)) return;
            var cat = (CategoryList.SelectedItem as CategoryRow)?.Key ?? "";
            var opt = ParamPickerWindow.Pick(this, row.Options, row.Selected, $"{cat}: {row.IfcName}");
            if (opt != null) row.Selected = opt;
        }

        void ShowCategory()
        {
            if (!(CategoryList.SelectedItem is CategoryRow cr)) return;
            var def = cr.Def;
            if (!_optionsCache.TryGetValue(def.Key, out var options))
                _optionsCache[def.Key] = options = ParameterCollector.Collect(_doc, def);
            var cs = _settings.For(def.Key);
            MappingGrid.ItemsSource = def.IfcParams
                .Select(ifc => new MappingRow(cs.Get(ifc), options))
                .ToList();
        }

        void Import_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new OpenFileDialog { Filter = "Настройки АтрибутыАГР (*.json)|*.json", Title = "Импорт настроек" };
            if (dlg.ShowDialog(this) != true) return;
            try
            {
                _settings = SettingsStore.Load(dlg.FileName);
                SettingsStore.SaveDefault(_settings);
                FillCategories();
                ShowCategory();
                ServiceUrlBox.Text = _settings.ServiceUrl;
            }
            catch (System.Exception ex)
            {
                MessageBox.Show(this, "Не удалось прочитать файл настроек:\n" + ex.Message, "АтрибутыАГР");
            }
        }

        void Export_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new SaveFileDialog
            {
                Filter = "Настройки АтрибутыАГР (*.json)|*.json",
                FileName = "АтрибутыАГР_маппинг.json",
                Title = "Экспорт настроек"
            };
            if (dlg.ShowDialog(this) != true) return;
            SettingsStore.Save(_settings, dlg.FileName);
        }

        void FacadeBox_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
        {
            var v = FacadeBox.SelectedItem as string;
            if (_settings.FacadeTypes == null) _settings.FacadeTypes = new Dictionary<string, string>();
            _settings.FacadeTypes[_doc.Title] = v == "не задан" ? "" : v;
        }

        void Fill_Click(object sender, RoutedEventArgs e)
        {
            ServiceUrl_LostFocus(sender, e);
            SettingsStore.SaveDefault(_settings);
            bool anyOn = _settings.Categories.Any(c => c.Enabled &&
                c.Params.Any(p => p.Enabled && !string.IsNullOrEmpty(p.RevitParam)));
            if (!anyOn)
            {
                MessageBox.Show(this, "Нет ни одного включённого параметра с выбранным параметром Revit.", "АтрибутыАГР");
                return;
            }
            if (_settings.Scope == "вид" && (_doc.ActiveView == null || _doc.ActiveView.IsTemplate))
            {
                MessageBox.Show(this, "Активный вид не подходит для выбора элементов — откройте план или 3D-вид.", "АтрибутыАГР");
                return;
            }

            var client = new PredictionClient(_settings.ServiceUrl, _settings.ServiceToken);
            var error = client.Check();
            if (error != null)
            {
                MessageBox.Show(this, error, "АтрибутыАГР");
                return;
            }

            List<Item> items;
            try
            {
                using (new WaitCursor())
                {
                    client.LoadClassifiers();
                    items = ItemCollector.Collect(_doc, _settings);
                    if (items.Count > 0) client.PredictAll(items);
                }
            }
            catch (System.Exception ex)
            {
                MessageBox.Show(this, "Ошибка при обращении к сервису:\n" + ex.Message, "АтрибутыАГР");
                return;
            }
            if (items.Count == 0)
            {
                MessageBox.Show(this, "В проекте нет элементов в категориях плагина.", "АтрибутыАГР");
                return;
            }
            new ReviewWindow(_doc, items, _settings, client) { Owner = this }.ShowDialog();
        }
    }

    /// <summary>Курсор ожидания на время долгой операции.</summary>
    sealed class WaitCursor : System.IDisposable
    {
        readonly System.Windows.Input.Cursor _prev = System.Windows.Input.Mouse.OverrideCursor;
        public WaitCursor() => System.Windows.Input.Mouse.OverrideCursor = System.Windows.Input.Cursors.Wait;
        public void Dispose() => System.Windows.Input.Mouse.OverrideCursor = _prev;
    }
}
