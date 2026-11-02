namespace RevitAIClassifier.Models
{
    /// <summary>Вариант в выпадающем списке параметров Revit.</summary>
    public class ParamOption
    {
        public const string TypeGroup = "Параметры типа";
        public const string InstanceGroup = "Параметры экземпляра";
        public const string NoneGroup = " ";

        public string Name { get; set; }
        public bool IsType { get; set; }
        /// <summary>Параметр есть в настройках, но в этом проекте не найден.</summary>
        public bool Missing { get; set; }

        public bool IsNone => string.IsNullOrEmpty(Name);
        public string Group => IsNone ? NoneGroup : IsType ? TypeGroup : InstanceGroup;
        public string Display => IsNone ? "— не задан —" : Missing ? Name + "  (нет в проекте)" : Name;

        public static ParamOption None => new ParamOption { Name = "" };

        public override bool Equals(object obj) =>
            obj is ParamOption o && o.Name == Name && (IsNone || o.IsType == IsType);

        public override int GetHashCode() => (Name ?? "").GetHashCode() ^ (IsType && !IsNone ? 1 : 0);
        public override string ToString() => Display;
    }
}
