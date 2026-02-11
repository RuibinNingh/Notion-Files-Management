using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Wpf.Ui.Appearance;

namespace Notion_Files_Management.Views.Tools
{
    public partial class IconThemeLabPage : Page
    {
        public IconThemeLabPage()
        {
            InitializeComponent();
            RefreshThemeInfo();
        }

        private void RefreshThemeInfo()
        {
            // 当前主题
            var appTheme = ApplicationThemeManager.GetAppTheme();
            TxtCurrentTheme.Text = appTheme.ToString();

            // 关键刷子颜色
            TxtBrushTextPrimary.Text = GetBrushInfo("TextFillColorPrimaryBrush");
            TxtBrushTextOnAccent.Text = GetBrushInfo("TextOnAccentFillColorPrimaryBrush");

            // 附加：输出几个按钮的实际前景/背景，方便肉眼对照不准时诊断
            try
            {
                TxtBrushTextOnAccent.Text += "\n" + DescribeButton("Primary-NoStyle", BtnPrimaryNoStyle);
                TxtBrushTextOnAccent.Text += "\n" + DescribeButton("Primary-WithStyle", BtnPrimaryWithStyle);
                TxtBrushTextOnAccent.Text += "\n" + DescribeButton("Native-Wpf", BtnNativeWpf);
            }
            catch
            {
                // 忽略测试按钮不可用的情况
            }
        }

        private static string ColorToString(Color c)
        {
            return $"#{c.A:X2}{c.R:X2}{c.G:X2}{c.B:X2} (A={c.A}, R={c.R}, G={c.G}, B={c.B})";
        }

        private string GetBrushInfo(string resourceKey)
        {
            try
            {
                if (Application.Current.Resources[resourceKey] is SolidColorBrush brush)
                {
                    return $"{resourceKey}: {ColorToString(brush.Color)}";
                }

                return $"{resourceKey}: 未找到或不是 SolidColorBrush";
            }
            catch (Exception ex)
            {
                return $"{resourceKey}: 读取失败 - {ex.Message}";
            }
        }

        private string DescribeButton(string name, Control btn)
        {
            string bg = btn.Background is SolidColorBrush b1 ? ColorToString(b1.Color) : (btn.Background?.ToString() ?? "null");
            string fg = btn.Foreground is SolidColorBrush b2 ? ColorToString(b2.Color) : (btn.Foreground?.ToString() ?? "null");
            return $"{name}  BG={bg}  FG={fg}";
        }

        private void BtnToggleTheme_Click(object sender, RoutedEventArgs e)
        {
            var current = ApplicationThemeManager.GetAppTheme();
            var next = current == ApplicationTheme.Dark ? ApplicationTheme.Light : ApplicationTheme.Dark;
            ApplicationThemeManager.Apply(next);
            RefreshThemeInfo();
        }
    }
}

