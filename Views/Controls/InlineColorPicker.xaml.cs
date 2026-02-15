using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using Wpf.Ui.Controls;
using Notion_Files_Management;

namespace Notion_Files_Management.Views.Controls
{
    public partial class InlineColorPicker : UserControl
    {
        public static readonly DependencyProperty SelectedColorProperty =
            DependencyProperty.Register(
                nameof(SelectedColor),
                typeof(string),
                typeof(InlineColorPicker),
                new PropertyMetadata(ConfigData.DefaultThemeAccentColor, OnSelectedColorChanged));

        public string SelectedColor
        {
            get => (string)GetValue(SelectedColorProperty);
            set => SetValue(SelectedColorProperty, value);
        }

        // HSV 颜色值 (0-360, 0-100, 0-100)
        private double _hue = 210;
        private double _saturation = 100;
        private double _brightness = 100;
        
        // 防止循环更新的标志
        private bool _isUpdatingFromCode = false;
        private bool _isDraggingHue = false;
        private bool _isDraggingSaturationBrightness = false;

        public InlineColorPicker()
        {
            InitializeComponent();
            Loaded += OnLoaded;
        }

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            LoadColor(SelectedColor);
            UpdateSaturationBrightnessGradient();
        }

        private static void OnSelectedColorChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        {
            if (d is InlineColorPicker picker && !picker._isUpdatingFromCode)
            {
                picker.LoadColor((string)e.NewValue);
            }
        }

        private void UpdateSaturationBrightnessGradient()
        {
            if (GradientStopRight == null || SaturationBrightnessCanvas == null) return;
            
            // 使用当前色相更新右侧渐变色
            var hueColor = HsvToRgb(_hue, 100, 100);
            GradientStopRight.Color = hueColor;
        }

        private void UpdateHueSelector()
        {
            if (HueCanvas == null || HueSelector == null) return;
            
            double position = _hue / 360.0 * HueCanvas.ActualHeight;
            Canvas.SetTop(HueSelector, Math.Max(0, Math.Min(HueCanvas.ActualHeight - 6, position - 3)));
            HueSelector.Visibility = Visibility.Visible;
        }

        private void UpdateSaturationBrightnessSelector()
        {
            if (SaturationBrightnessCanvas == null || ColorSelector == null) return;
            
            double x = _saturation / 100.0 * SaturationBrightnessCanvas.ActualWidth;
            // 反转Y坐标：由于叠加了从透明到黑色的渐变，视觉上顶部是低亮度，底部是高亮度
            // 但代码生成的渐变是顶部低亮度、底部高亮度，所以需要反转
            double y = (100.0 - _brightness) / 100.0 * SaturationBrightnessCanvas.ActualHeight;
            
            Canvas.SetLeft(ColorSelector, Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualWidth - 14, x - 7)));
            Canvas.SetTop(ColorSelector, Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualHeight - 14, y - 7)));
            ColorSelector.Visibility = Visibility.Visible;
        }

        private void LoadColor(string colorHex)
        {
            try
            {
                if (!colorHex.StartsWith("#"))
                    colorHex = "#" + colorHex;

                var color = (Color)ColorConverter.ConvertFromString(colorHex);
                var hsv = RgbToHsv(color);
                
                _hue = hsv.H;
                _saturation = hsv.S;
                _brightness = hsv.V;
                
                UpdateColorDisplay();
            }
            catch
            {
                _hue = 210;
                _saturation = 100;
                _brightness = 100;
                UpdateColorDisplay();
            }
        }

        private void UpdateColorDisplay()
        {
            if (_isUpdatingFromCode) return;
            
            _isUpdatingFromCode = true;
            
            try
            {
                var color = HsvToRgb(_hue, _saturation, _brightness);
                var colorHex = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
                
                // 更新依赖属性（触发外部绑定）
                SetValue(SelectedColorProperty, colorHex);
                
                // 更新预览
                if (ColorPreviewBrush != null)
                    ColorPreviewBrush.Color = color;
                
                if (ColorHexText != null)
                    ColorHexText.Text = colorHex.ToUpper();
                
                // 更新 RGB 显示
                if (RgbText != null)
                    RgbText.Text = $"{color.R}, {color.G}, {color.B}";
                
                // 更新 RGB 滑块和输入框
                if (RedSlider != null && RedBox != null)
                {
                    RedSlider.Value = color.R;
                    RedBox.Text = color.R.ToString();
                }
                
                if (GreenSlider != null && GreenBox != null)
                {
                    GreenSlider.Value = color.G;
                    GreenBox.Text = color.G.ToString();
                }
                
                if (BlueSlider != null && BlueBox != null)
                {
                    BlueSlider.Value = color.B;
                    BlueBox.Text = color.B.ToString();
                }
                
                // 更新选择器位置
                UpdateHueSelector();
                UpdateSaturationBrightnessSelector();
                
                // 更新饱和度/亮度渐变（只在色相改变时更新）
                UpdateSaturationBrightnessGradient();
            }
            finally
            {
                _isUpdatingFromCode = false;
            }
        }

        // 色相选择
        private void OnHueMouseDown(object sender, MouseButtonEventArgs e)
        {
            if (HueCanvas == null) return;
            _isDraggingHue = true;
            UpdateHueFromMousePosition(e.GetPosition(HueCanvas));
            HueCanvas.CaptureMouse();
        }

        private void OnHueMouseMove(object sender, MouseEventArgs e)
        {
            if (_isDraggingHue && HueCanvas != null)
            {
                UpdateHueFromMousePosition(e.GetPosition(HueCanvas));
            }
        }

        private void OnHueMouseUp(object sender, MouseButtonEventArgs e)
        {
            if (_isDraggingHue)
            {
                _isDraggingHue = false;
                if (HueCanvas != null)
                    HueCanvas.ReleaseMouseCapture();
            }
        }

        private void UpdateHueFromMousePosition(Point position)
        {
            if (HueCanvas == null) return;
            
            double y = Math.Max(0, Math.Min(HueCanvas.ActualHeight, position.Y));
            _hue = 360.0 * y / HueCanvas.ActualHeight;
            UpdateColorDisplay();
        }

        // 饱和度和亮度选择
        private void OnSaturationBrightnessMouseDown(object sender, MouseButtonEventArgs e)
        {
            if (SaturationBrightnessCanvas == null) return;
            _isDraggingSaturationBrightness = true;
            UpdateSaturationBrightnessFromMousePosition(e.GetPosition(SaturationBrightnessCanvas));
            SaturationBrightnessCanvas.CaptureMouse();
        }

        private void OnSaturationBrightnessMouseMove(object sender, MouseEventArgs e)
        {
            if (_isDraggingSaturationBrightness && SaturationBrightnessCanvas != null)
            {
                UpdateSaturationBrightnessFromMousePosition(e.GetPosition(SaturationBrightnessCanvas));
            }
        }

        private void OnSaturationBrightnessMouseUp(object sender, MouseButtonEventArgs e)
        {
            if (_isDraggingSaturationBrightness)
            {
                _isDraggingSaturationBrightness = false;
                if (SaturationBrightnessCanvas != null)
                    SaturationBrightnessCanvas.ReleaseMouseCapture();
            }
        }

        private void UpdateSaturationBrightnessFromMousePosition(Point position)
        {
            if (SaturationBrightnessCanvas == null) return;
            
            double x = Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualWidth, position.X));
            double y = Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualHeight, position.Y));
            
            _saturation = 100.0 * x / SaturationBrightnessCanvas.ActualWidth;
            // 反转亮度计算：由于叠加了从透明到黑色的渐变，视觉上顶部是低亮度，底部是高亮度
            // 但代码生成的渐变是顶部低亮度、底部高亮度，所以需要反转
            _brightness = 100.0 * (SaturationBrightnessCanvas.ActualHeight - y) / SaturationBrightnessCanvas.ActualHeight;
            
            UpdateColorDisplay();
        }

        // RGB 滑块变化
        private void OnRgbSliderChanged(object sender, RoutedEventArgs e)
        {
            if (_isUpdatingFromCode) return;
            
            try
            {
                if (RedSlider == null || GreenSlider == null || BlueSlider == null) return;
                
                var color = Color.FromRgb(
                    (byte)RedSlider.Value,
                    (byte)GreenSlider.Value,
                    (byte)BlueSlider.Value);
                
                var hsv = RgbToHsv(color);
                _hue = hsv.H;
                _saturation = hsv.S;
                _brightness = hsv.V;
                
                UpdateColorDisplay();
            }
            catch { }
        }

        // RGB 输入框变化
        private void OnRgbValueChanged(object sender, TextChangedEventArgs e)
        {
            if (_isUpdatingFromCode) return;
            
            try
            {
                if (RedBox == null || GreenBox == null || BlueBox == null) return;
                
                if (!int.TryParse(RedBox.Text, out int r) ||
                    !int.TryParse(GreenBox.Text, out int g) ||
                    !int.TryParse(BlueBox.Text, out int b))
                    return;
                
                r = Math.Clamp(r, 0, 255);
                g = Math.Clamp(g, 0, 255);
                b = Math.Clamp(b, 0, 255);
                
                var color = Color.FromRgb((byte)r, (byte)g, (byte)b);
                var hsv = RgbToHsv(color);
                _hue = hsv.H;
                _saturation = hsv.S;
                _brightness = hsv.V;
                
                UpdateColorDisplay();
            }
            catch { }
        }

        // 预设颜色点击
        private void OnPresetColorClick(object sender, MouseButtonEventArgs e)
        {
            if (sender is FrameworkElement element && element.Tag is string colorHex)
            {
                LoadColor(colorHex);
            }
        }

        // HSV 转 RGB
        private Color HsvToRgb(double h, double s, double v)
        {
            h = h % 360;
            if (h < 0) h += 360;
            
            s = Math.Clamp(s, 0, 100) / 100.0;
            v = Math.Clamp(v, 0, 100) / 100.0;
            
            double c = v * s;
            double x = c * (1 - Math.Abs((h / 60.0) % 2 - 1));
            double m = v - c;
            
            double r = 0, g = 0, b = 0;
            
            if (h < 60)
            {
                r = c; g = x; b = 0;
            }
            else if (h < 120)
            {
                r = x; g = c; b = 0;
            }
            else if (h < 180)
            {
                r = 0; g = c; b = x;
            }
            else if (h < 240)
            {
                r = 0; g = x; b = c;
            }
            else if (h < 300)
            {
                r = x; g = 0; b = c;
            }
            else
            {
                r = c; g = 0; b = x;
            }
            
            return Color.FromRgb(
                (byte)((r + m) * 255),
                (byte)((g + m) * 255),
                (byte)((b + m) * 255));
        }

        // RGB 转 HSV
        private (double H, double S, double V) RgbToHsv(Color color)
        {
            double r = color.R / 255.0;
            double g = color.G / 255.0;
            double b = color.B / 255.0;
            
            double max = Math.Max(r, Math.Max(g, b));
            double min = Math.Min(r, Math.Min(g, b));
            double delta = max - min;
            
            double h = 0;
            if (delta != 0)
            {
                if (max == r)
                    h = 60 * (((g - b) / delta) % 6);
                else if (max == g)
                    h = 60 * ((b - r) / delta + 2);
                else
                    h = 60 * ((r - g) / delta + 4);
            }
            
            if (h < 0) h += 360;
            
            double s = max == 0 ? 0 : delta / max;
            double v = max;
            
            return (h, s * 100, v * 100);
        }
    }
}
