using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Data;
using System.Windows.Input;
using RevitAIClassifier.Models;

namespace RevitAIClassifier.Views
{
    /// <summary>Выбор параметра Revit с поиском и фильтром «типа / экземпляра».</summary>
    public partial class ParamPickerWindow : Window
    {
        readonly ListCollectionView _view;
        string[] _words = new string[0];

        public ParamOption Selected { get; private set; }

        public ParamPickerWindow(List<ParamOption> options, ParamOption current, string target)
        {
            InitializeComponent();
            TargetText.Text = target;
            _view = new ListCollectionView(options) { Filter = Matches };
            _view.GroupDescriptions.Add(new PropertyGroupDescription(nameof(ParamOption.Group)));
            Results.ItemsSource = _view;
            var cur = options.FirstOrDefault(o => o.Equals(current));
            if (cur != null)
            {
                Results.SelectedItem = cur;
                Loaded += (s, e) => Results.ScrollIntoView(cur);
            }
            Loaded += (s, e) => SearchBox.Focus();
        }

        public static ParamOption Pick(Window owner, List<ParamOption> options, ParamOption current, string target)
        {
            var w = new ParamPickerWindow(options, current, target) { Owner = owner };
            var p = owner.PointToScreen(Mouse.GetPosition(owner));
            var source = PresentationSource.FromVisual(owner);
            if (source?.CompositionTarget != null)
                p = source.CompositionTarget.TransformFromDevice.Transform(p);
            w.Left = Math.Max(0, Math.Min(p.X - 60, SystemParameters.WorkArea.Right - w.Width));
            w.Top = Math.Max(0, Math.Min(p.Y + 12, SystemParameters.WorkArea.Bottom - w.Height));
            return w.ShowDialog() == true ? w.Selected : null;
        }

        bool Matches(object o)
        {
            var opt = (ParamOption)o;
            if (opt.IsNone) return _words.Length == 0;   // «— не задан —» только без поиска
            if (TypeOnly.IsChecked == true && !opt.IsType) return false;
            if (InstOnly.IsChecked == true && opt.IsType) return false;
            var text = Classifier.Normalize(opt.Name);
            return _words.All(w => text.Contains(w));
        }

        void SearchBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
        {
            Placeholder.Visibility = SearchBox.Text.Length == 0 ? System.Windows.Visibility.Visible
                                                                : System.Windows.Visibility.Collapsed;
            _words = Classifier.Normalize(SearchBox.Text).Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            Refresh();
        }

        void Kind_Changed(object sender, RoutedEventArgs e) => Refresh();

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
            if (e.Key != Key.Down && e.Key != Key.Up) return;
            int i = Results.SelectedIndex + (e.Key == Key.Down ? 1 : -1);
            if (i >= 0 && i < _view.Count)
            {
                Results.SelectedIndex = i;
                Results.ScrollIntoView(Results.SelectedItem);
            }
            e.Handled = true;
        }

        void Results_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter) { Ok_Click(sender, e); e.Handled = true; }
        }

        void Results_MouseDoubleClick(object sender, MouseButtonEventArgs e) => Ok_Click(sender, e);

        void Ok_Click(object sender, RoutedEventArgs e)
        {
            if (!(Results.SelectedItem is ParamOption opt)) return;
            Selected = opt;
            DialogResult = true;
        }
    }
}
