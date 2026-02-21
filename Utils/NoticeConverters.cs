using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// bool → Visibility（true = Visible, false = Collapsed）
    /// </summary>
    public sealed class BoolToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
            => value is true ? Visibility.Visible : Visibility.Collapsed;

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => value is Visibility.Visible;
    }

    /// <summary>
    /// bool → Visibility（true = Collapsed, false = Visible）— 反转
    /// </summary>
    public sealed class InverseBoolToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
            => value is true ? Visibility.Collapsed : Visibility.Visible;

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => value is Visibility.Collapsed;
    }

    /// <summary>
    /// 公告标签 → 背景色（深色主题适配）
    /// </summary>
    public sealed class TagToBackgroundConverter : IValueConverter
    {
        // 深色主题下的标签背景色
        private static readonly Dictionary<string, string> TagColors = new()
        {
            { "更新", "#1A3A5C" },  // 深蓝
            { "维护", "#3D2B10" },  // 深橙
            { "通知", "#1A3A1A" },  // 深绿
            { "紧急", "#3D1515" },  // 深红
        };

        private const string DefaultColor = "#2A2A2A"; // 深灰兜底

        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is string tag && TagColors.TryGetValue(tag, out var hex))
                return new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            return new SolidColorBrush((Color)ColorConverter.ConvertFromString(DefaultColor));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotSupportedException();
    }

    /// <summary>
    /// 公告标签 → 前景色（深色主题适配）
    /// </summary>
    public sealed class TagToForegroundConverter : IValueConverter
    {
        private static readonly Dictionary<string, string> TagColors = new()
        {
            { "更新", "#64B5F6" },  // 亮蓝
            { "维护", "#FFB74D" },  // 亮橙
            { "通知", "#81C784" },  // 亮绿
            { "紧急", "#EF5350" },  // 亮红
        };

        private const string DefaultColor = "#B0B0B0"; // 灰色兜底

        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is string tag && TagColors.TryGetValue(tag, out var hex))
                return new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            return new SolidColorBrush((Color)ColorConverter.ConvertFromString(DefaultColor));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotSupportedException();
    }
}
