using System;
using System.Linq;
using System.Windows;
using System.Windows.Data;
using System.Windows.Input;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Views
{
    /// <summary>
    /// Окно выбора кода: поиск по части кода или наименования (несколько слов — все должны совпасть),
    /// стрелки и Enter, двойной щелчок. ★ — коды, которые уже есть в разметке.
    /// </summary>
    public partial class CodePickerWindow : Window
    {
        readonly ListCollectionView _view;
        string[] _words = new string[0];

        public string SelectedCode { get; private set; }

        public CodePickerWindow(string currentCode, string target, System.Collections.Generic.List<ClassifierEntry> entries)
        {
            InitializeComponent();
            TargetText.Text = target;
            _view = new ListCollectionView(entries) { Filter = Matches };
            Results.ItemsSource = _view;

            var current = entries.FirstOrDefault(e => e.Code == currentCode);
            if (current != null)
            {
                Results.SelectedItem = current;
                Loaded += (s, e) => Results.ScrollIntoView(current);
            }
            Loaded += (s, e) => SearchBox.Focus();
        }

        /// <summary>Открыть окно рядом с курсором.</summary>
        public static string Pick(Window owner, string currentCode, string target,
                                  System.Collections.Generic.List<ClassifierEntry> entries)
        {
            var w = new CodePickerWindow(currentCode, target, entries) { Owner = owner };
            var p = owner.PointToScreen(Mouse.GetPosition(owner));
            var source = PresentationSource.FromVisual(owner);
            if (source?.CompositionTarget != null)
                p = source.CompositionTarget.TransformFromDevice.Transform(p);
            w.Left = Math.Max(0, Math.Min(p.X - 60, SystemParameters.WorkArea.Right - w.Width));
            w.Top = Math.Max(0, Math.Min(p.Y + 12, SystemParameters.WorkArea.Bottom - w.Height));
            return w.ShowDialog() == true ? w.SelectedCode : null;
        }

        bool Matches(object o)
        {
            var e = (ClassifierEntry)o;
            if (OnlyUsed.IsChecked == true && e.Used == 0) return false;
            return _words.All(w => e.SearchText.Contains(w));
        }

        void SearchBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
        {
            Placeholder.Visibility = SearchBox.Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
            _words = Classifier.Normalize(SearchBox.Text)
                .Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            Refresh();
        }

        void Filter_Changed(object sender, RoutedEventArgs e) => Refresh();

        void Refresh()
        {
            if (_view == null) return;
            _view.Refresh();
            if (Results.SelectedItem == null || !_view.Contains(Results.SelectedItem))
                Results.SelectedIndex = _view.Count > 0 ? 0 : -1;
            if (Results.SelectedItem != null) Results.ScrollIntoView(Results.SelectedItem);
        }

        void SearchBox_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Down || e.Key == Key.Up)
            {
                int i = Results.SelectedIndex + (e.Key == Key.Down ? 1 : -1);
                if (i >= 0 && i < _view.Count)
                {
                    Results.SelectedIndex = i;
                    Results.ScrollIntoView(Results.SelectedItem);
                }
                e.Handled = true;
            }
        }

        void Results_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter) { Ok_Click(sender, e); e.Handled = true; }
        }

        void Results_MouseDoubleClick(object sender, MouseButtonEventArgs e) => Ok_Click(sender, e);

        void Ok_Click(object sender, RoutedEventArgs e)
        {
            if (!(Results.SelectedItem is ClassifierEntry entry)) return;
            SelectedCode = entry.Code;
            DialogResult = true;
        }
    }
}
