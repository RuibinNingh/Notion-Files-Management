using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// Converts ActualWidth/ActualHeight to a responsive clamped length.
    /// ConverterParameter format: "min=360;max=720;margin=80;ratio=1".
    /// </summary>
    public sealed class ResponsiveClampConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not double available || double.IsNaN(available) || double.IsInfinity(available))
                return DependencyProperty.UnsetValue;

            var opts = Parse(parameter as string);

            double ratio = TryGetDouble(opts, "ratio", 1.0, culture);
            double min = TryGetDouble(opts, "min", 0.0, culture);
            double max = TryGetDouble(opts, "max", double.PositiveInfinity, culture);
            double margin = TryGetDouble(opts, "margin", 0.0, culture);

            double computed = Math.Max(0.0, (available - margin) * ratio);

            if (computed < min) computed = min;
            if (computed > max) computed = max;

            if (double.IsNaN(computed) || double.IsInfinity(computed))
                return DependencyProperty.UnsetValue;

            return computed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotSupportedException();

        private static double TryGetDouble(Dictionary<string, string> opts, string key, double fallback, CultureInfo culture)
        {
            if (opts.TryGetValue(key, out var s) && double.TryParse(s, NumberStyles.Any, culture, out var v))
                return v;
            return fallback;
        }

        private static Dictionary<string, string> Parse(string? s)
        {
            var dict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (string.IsNullOrWhiteSpace(s))
                return dict;

            foreach (var part in s.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var kv = part.Split(new[] { '=' }, 2, StringSplitOptions.RemoveEmptyEntries);
                if (kv.Length == 2)
                    dict[kv[0].Trim()] = kv[1].Trim();
            }

            return dict;
        }
    }
}
