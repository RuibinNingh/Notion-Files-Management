using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Wpf.Ui.Controls;
using Notion_Files_Management;

namespace Notion_Files_Management.Views.Dialogs
{
    public partial class ColorPickerWindow : Window
    {
        public string SelectedColor { get; private set; } = ConfigData.DefaultThemeAccentColor;
        
        // HSV 颜色值 (0-360, 0-100, 0-100)
        private double _hue = 210;
        private double _saturation = 100;
        private double _brightness = 100;
        
        // 防止循环更新的标志
        private bool _isUpdatingFromCode = false;
        private bool _isDraggingHue = false;
        private bool _isDraggingSaturationBrightness = false;
        
        // 渐变更新方法
        private Action? _updateSaturationBrightnessGradient;

        public ColorPickerWindow(string initialColor = ConfigData.DefaultThemeAccentColor)
        {
            InitializeComponent();
            SelectedColor = initialColor;
            Loaded += OnWindowLoaded;
        }

        private void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            LoadColor(SelectedColor);
            InitializeGradients();
        }

        private void InitializeGradients()
        {
            // 初始化色相渐变
            CreateHueGradient();
            
            // 初始化饱和度和亮度渐变
            CreateSaturationBrightnessGradient();
        }

        private void CreateHueGradient()
        {
            if (HueCanvas == null || HueGradient == null) return;
            
            void UpdateGradient()
            {
                if (HueCanvas.ActualWidth <= 0 || HueCanvas.ActualHeight <= 0) return;
                
                var width = (int)HueCanvas.ActualWidth;
                var height = (int)HueCanvas.ActualHeight;
                
                var bitmap = new WriteableBitmap(width, height, 96, 96, PixelFormats.Bgra32, null);
                var pixels = new byte[width * height * 4];
                
                for (int y = 0; y < height; y++)
                {
                    double hue = 360.0 * y / height;
                    var color = HsvToRgb(hue, 100, 100);
                    
                    for (int x = 0; x < width; x++)
                    {
                        int index = (y * width + x) * 4;
                        pixels[index] = color.B;     // Blue
                        pixels[index + 1] = color.G; // Green
                        pixels[index + 2] = color.R; // Red
                        pixels[index + 3] = color.A; // Alpha
                    }
                }
                
                bitmap.WritePixels(new Int32Rect(0, 0, width, height), pixels, width * 4, 0);
                
                HueGradient.Fill = new ImageBrush(bitmap);
                UpdateHueSelector();
            }
            
            HueCanvas.LayoutUpdated += (s, e) => UpdateGradient();
            HueCanvas.SizeChanged += (s, e) => UpdateGradient();
            
            // 立即更新一次
            if (HueCanvas.IsLoaded)
                UpdateGradient();
            else
                HueCanvas.Loaded += (s, e) => UpdateGradient();
        }

        private void CreateSaturationBrightnessGradient()
        {
            if (SaturationBrightnessCanvas == null || SaturationBrightnessGradient == null) return;
            
            void UpdateGradient()
            {
                if (SaturationBrightnessCanvas.ActualWidth <= 0 || SaturationBrightnessCanvas.ActualHeight <= 0) return;
                
                var width = (int)SaturationBrightnessCanvas.ActualWidth;
                var height = (int)SaturationBrightnessCanvas.ActualHeight;
                
                var bitmap = new WriteableBitmap(width, height, 96, 96, PixelFormats.Bgra32, null);
                var pixels = new byte[width * height * 4];
                
                for (int y = 0; y < height; y++)
                {
                    double brightness = 100.0 * y / height; // 从上到下
                    
                    for (int x = 0; x < width; x++)
                    {
                        double saturation = 100.0 * x / width; // 从左到右
                        var color = HsvToRgb(_hue, saturation, brightness);
                        
                        int index = (y * width + x) * 4;
                        pixels[index] = color.B;     // Blue
                        pixels[index + 1] = color.G; // Green
                        pixels[index + 2] = color.R; // Red
                        pixels[index + 3] = color.A; // Alpha
                    }
                }
                
                bitmap.WritePixels(new Int32Rect(0, 0, width, height), pixels, width * 4, 0);
                
                SaturationBrightnessGradient.Fill = new ImageBrush(bitmap);
                UpdateSaturationBrightnessSelector();
            }
            
            _updateSaturationBrightnessGradient = UpdateGradient;
            
            SaturationBrightnessCanvas.LayoutUpdated += (s, e) => UpdateGradient();
            SaturationBrightnessCanvas.SizeChanged += (s, e) => UpdateGradient();
            
            // 立即更新一次
            if (SaturationBrightnessCanvas.IsLoaded)
                UpdateGradient();
            else
                SaturationBrightnessCanvas.Loaded += (s, e) => UpdateGradient();
        }

        private void UpdateHueSelector()
        {
            if (HueCanvas == null || HueSelector == null) return;
            
            double position = _hue / 360.0 * HueCanvas.ActualHeight;
            Canvas.SetTop(HueSelector, Math.Max(0, Math.Min(HueCanvas.ActualHeight - 8, position - 4)));
            HueSelector.Visibility = Visibility.Visible;
        }

        private void UpdateSaturationBrightnessSelector()
        {
            if (SaturationBrightnessCanvas == null || ColorSelector == null) return;
            
            double x = _saturation / 100.0 * SaturationBrightnessCanvas.ActualWidth;
            double y = _brightness / 100.0 * SaturationBrightnessCanvas.ActualHeight; // 从上到下
            
            Canvas.SetLeft(ColorSelector, Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualWidth - 16, x - 8)));
            Canvas.SetTop(ColorSelector, Math.Max(0, Math.Min(SaturationBrightnessCanvas.ActualHeight - 16, y - 8)));
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
                // 使用默认颜色
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
                SelectedColor = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
                
                // 更新预览
                if (ColorPreviewBrush != null)
                    ColorPreviewBrush.Color = color;
                
                if (ColorHexText != null)
                    ColorHexText.Text = SelectedColor.ToUpper();
                
                // 更新 RGB 显示
                if (RgbText != null)
                    RgbText.Text = $"{color.R}, {color.G}, {color.B}";
                
                // 更新 HSV 显示
                if (HsvText != null)
                    HsvText.Text = $"{(int)_hue}°, {(int)_saturation}%, {(int)_brightness}%";
                
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
                
                // 更新 HSV 滑块和输入框
                if (HueSlider != null && HueBox != null)
                {
                    HueSlider.Value = _hue;
                    HueBox.Text = ((int)_hue).ToString();
                }
                
                if (SaturationSlider != null && SaturationBox != null)
                {
                    SaturationSlider.Value = _saturation;
                    SaturationBox.Text = ((int)_saturation).ToString();
                }
                
                if (BrightnessSlider != null && BrightnessBox != null)
                {
                    BrightnessSlider.Value = _brightness;
                    BrightnessBox.Text = ((int)_brightness).ToString();
                }
                
                // 更新选择器位置
                UpdateHueSelector();
                UpdateSaturationBrightnessSelector();
                
                // 更新饱和度/亮度渐变（因为色相改变了）
                _updateSaturationBrightnessGradient?.Invoke();
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
            _brightness = 100.0 * y / SaturationBrightnessCanvas.ActualHeight; // 从上到下
            
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
        private void OnRgbValueChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
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

        // HSV 滑块变化
        private void OnHsvSliderChanged(object sender, RoutedEventArgs e)
        {
            if (_isUpdatingFromCode) return;
            
            try
            {
                if (HueSlider != null)
                    _hue = HueSlider.Value;
                if (SaturationSlider != null)
                    _saturation = SaturationSlider.Value;
                if (BrightnessSlider != null)
                    _brightness = BrightnessSlider.Value;
                
                UpdateColorDisplay();
            }
            catch { }
        }

        // HSV 输入框变化
        private void OnHsvValueChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
        {
            if (_isUpdatingFromCode) return;
            
            try
            {
                if (HueBox == null || SaturationBox == null || BrightnessBox == null) return;
                
                if (!double.TryParse(HueBox.Text, out double h) ||
                    !double.TryParse(SaturationBox.Text, out double s) ||
                    !double.TryParse(BrightnessBox.Text, out double v))
                    return;
                
                _hue = Math.Clamp(h, 0, 360);
                _saturation = Math.Clamp(s, 0, 100);
                _brightness = Math.Clamp(v, 0, 100);
                
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

        private void OnOkClick(object sender, RoutedEventArgs e)
        {
            DialogResult = true;
            Close();
        }

        private void OnCancelClick(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
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