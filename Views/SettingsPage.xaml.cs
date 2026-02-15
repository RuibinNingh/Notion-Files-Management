using System;
using System.Diagnostics;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;
using Wpf.Ui.Controls;

namespace Notion_Files_Management.Views
{
    public partial class SettingsPage : Page
    {
        // 版本检查相关常量
        private const string VersionEndpointHttps = "https://nfm.ruibin-ningh.top/version.json";
        private const string VersionEndpointHttp = "http://nfm.ruibin-ningh.top/version.json";

        // 使用静态 HttpClient 避免 socket 资源泄漏
        private static readonly HttpClient _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(15)
        };

        // 版本信息数据模型（与服务端 JSON 字段对应）
        private sealed class VersionInfo
        {
            public string version { get; set; } = "";
            public string build_date { get; set; } = "";
            public string download_url { get; set; } = "";
            public string github { get; set; } = "";
            public string[] changelog { get; set; } = Array.Empty<string>();
        }

        public SettingsPage()
        {
            InitializeComponent();

            // 加载配置
            ConfigManager.Load();

            if (ConfigManager.Current != null)
            {
                TokenInput.Password = ConfigManager.Current.NotionToken;
                NotionUrlInput.Text = ConfigManager.Current.NotionBaseUrl ?? "https://api.notion.com/v1";
                SelectComboByInt(DownloadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxDownloadWorkers));
                SelectComboByInt(UploadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxUploadWorkers));
                
                // 加载主题色配置
                LoadThemeColor();
                
                // 加载背景材质配置
                LoadBackgroundMaterial();
            }
            
            // 监听背景材质选择变化（仅更新UI，不保存）
            if (BackgroundMaterialCombo != null)
            {
                BackgroundMaterialCombo.SelectionChanged += OnBackgroundMaterialChanged;
            }

            // 显示当前版本号
            TxtCurrentVersion.Text = $"当前版本：{AppVersion.FullVersionString}";
            
            // 初始化颜色选择器事件监听
            Loaded += (s, e) =>
            {
                if (ColorPicker != null)
                {
                    var dpd = System.ComponentModel.DependencyPropertyDescriptor.FromProperty(
                        Views.Controls.InlineColorPicker.SelectedColorProperty,
                        typeof(Views.Controls.InlineColorPicker));
                    dpd?.AddValueChanged(ColorPicker, OnColorPickerColorChanged);
                }
            };
        }

        private void OnSaveClick(object sender, RoutedEventArgs e)
        {
            try
            {
                ConfigManager.Load();

                string inputToken = TokenInput.Password?.Trim() ?? "";
                string inputUrl   = NotionUrlInput.Text?.Trim() ?? "";
                int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
                int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo,   fallback: 3));

                string cleanedUrl = CleanAndValidateUrl(inputUrl);

                ConfigManager.Current.NotionToken        = inputToken;
                ConfigManager.Current.NotionBaseUrl      = cleanedUrl;
                ConfigManager.Current.MaxDownloadWorkers = dl;
                ConfigManager.Current.MaxUploadWorkers   = ul;
                
                // 注意：外观设置（主题色、背景材质）需要通过外观块的保存按钮单独保存
                // 这里不保存外观设置，避免覆盖用户未保存的外观设置
                
                ConfigManager.Save();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Save config failed", ex);
            }
        }

        private async void OnApplyWorkersResetClick(object sender, RoutedEventArgs e)
        {
            try
            {
                ConfigManager.Load();

                string inputToken = TokenInput.Password?.Trim() ?? "";
                string inputUrl   = NotionUrlInput.Text?.Trim() ?? "";
                int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
                int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo,   fallback: 3));

                string cleanedUrl = CleanAndValidateUrl(inputUrl);

                ConfigManager.Current.NotionToken        = inputToken;
                ConfigManager.Current.NotionBaseUrl      = cleanedUrl;
                ConfigManager.Current.MaxDownloadWorkers = dl;
                ConfigManager.Current.MaxUploadWorkers   = ul;
                ConfigManager.Save();

                BtnApplyWorkersReset.IsEnabled = false;

                await PythonBackendHost.Instance.ResetTasksAndReinitialize(inputToken, dl, ul, cleanedUrl);

                var ds = DownloadSession.Instance;
                ds.FileSelectionList.Clear();
                ds.DisplayTasks.Clear();
                ds.HasActiveDownloads = false;

                TaskResetNotifier.NotifyTasksReset();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Apply+Reset failed", ex);
            }
            finally
            {
                BtnApplyWorkersReset.IsEnabled = true;
            }
        }

        // ── 版本检查相关方法 ─────────────────────────────────────────────────

        /// <summary>
        /// 点击"检查版本更新"按钮
        /// </summary>
        private async void OnCheckUpdateClick(object sender, RoutedEventArgs e)
        {
            BtnCheckUpdate.IsEnabled = false;
            BtnCheckUpdate.Content = "检查中...";
            
            // 展开版本信息面板
            VersionInfoPanel.Visibility = Visibility.Visible;

            try
            {
                // 获取版本信息
                var versionInfo = await FetchVersionInfoAsync();

                if (versionInfo != null)
                {
                    // 渲染版本信息
                    RenderVersionInfo(versionInfo);
                }
                else
                {
                    // 获取失败
                    ShowInfoBar(InfoBarSeverity.Error, "无法获取版本信息，请检查网络连接");
                    VersionDetailGrid.Visibility = Visibility.Collapsed;
                    DownloadButtonPanel.Visibility = Visibility.Collapsed;
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Check update failed", ex);
                ShowInfoBar(InfoBarSeverity.Error, $"检查更新失败：{ex.Message}");
                VersionDetailGrid.Visibility = Visibility.Collapsed;
                DownloadButtonPanel.Visibility = Visibility.Collapsed;
            }
            finally
            {
                BtnCheckUpdate.Content = "检查版本更新";
                BtnCheckUpdate.IsEnabled = true;
            }
        }

        /// <summary>
        /// 获取远程版本信息
        /// 优先使用 HTTPS，失败时降级到 HTTP
        /// </summary>
        private async Task<VersionInfo?> FetchVersionInfoAsync()
        {
            // 先尝试 HTTPS
            try
            {
                var response = await _httpClient.GetAsync(VersionEndpointHttps);
                response.EnsureSuccessStatusCode();
                var json = await response.Content.ReadAsStringAsync();
                return JsonSerializer.Deserialize<VersionInfo>(json);
            }
            catch (Exception ex)
            {
                Logger.Warn($"[SettingsPage] HTTPS request failed, trying HTTP: {ex.Message}");
            }

            // HTTPS 失败，降级到 HTTP
            try
            {
                var response = await _httpClient.GetAsync(VersionEndpointHttp);
                response.EnsureSuccessStatusCode();
                var json = await response.Content.ReadAsStringAsync();
                return JsonSerializer.Deserialize<VersionInfo>(json);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Both HTTPS and HTTP requests failed", ex);
                return null;
            }
        }

        /// <summary>
        /// 渲染版本信息到 UI
        /// </summary>
        private void RenderVersionInfo(VersionInfo info)
        {
            // 填充版本信息
            TxtLatestVersion.Text = info.version;
            TxtBuildDate.Text = info.build_date;

            // 清空并重新填充更新日志
            ChangelogPanel.Children.Clear();
            if (info.changelog != null && info.changelog.Length > 0)
            {
                foreach (var item in info.changelog)
                {
                    // 支持换行符：将每一项按换行符分割
                    var lines = item.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    
                    foreach (var line in lines)
                    {
                        // 注意：Horizontal StackPanel 会在水平方向给子元素无限宽度，TextWrapping 将不会生效。
                        // 这里改用 Grid（Auto + * 两列）让文本拿到受限宽度，从而按容器宽度自动换行。
                        var row = new Grid
                        {
                            Margin = new Thickness(0, 0, 0, 4),
                            HorizontalAlignment = System.Windows.HorizontalAlignment.Stretch
                        };
                        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                        // 添加图标
                        var icon = new SymbolIcon
                        {
                            Symbol = SymbolRegular.Checkmark24,
                            FontSize = 14,
                            Margin = new Thickness(0, 2, 8, 0),
                            VerticalAlignment = VerticalAlignment.Top
                        };
                        Grid.SetColumn(icon, 0);
                        row.Children.Add(icon);

                        // 添加文本（根据块宽度自动换行）
                        var textBlock = new Wpf.Ui.Controls.TextBlock
                        {
                            Text = line.Trim(),
                            TextWrapping = TextWrapping.Wrap,
                            VerticalAlignment = VerticalAlignment.Top
                        };
                        Grid.SetColumn(textBlock, 1);
                        row.Children.Add(textBlock);

                        ChangelogPanel.Children.Add(row);
                    }
                }
            }

            // 比较版本号：清理两边的版本号（去掉 v 前缀和 Git hash）
            string currentVersion = CleanVersionString(AppVersion.Current);
            string latestVersion = CleanVersionString(info.version);
            
            bool isNewVersion = !latestVersion.Equals(currentVersion, StringComparison.OrdinalIgnoreCase);
            
            if (isNewVersion)
            {
                ShowInfoBar(InfoBarSeverity.Warning, $"发现新版本 {info.version}，建议更新");
                DownloadButtonPanel.Visibility = Visibility.Visible;
            }
            else
            {
                ShowInfoBar(InfoBarSeverity.Success, "已是最新版本");
                DownloadButtonPanel.Visibility = Visibility.Collapsed;
            }

            // 显示详细信息
            VersionDetailGrid.Visibility = Visibility.Visible;

            // 保存下载信息到按钮 Tag，用于后续点击
            BtnOpenGithub.Tag = info.github;
            BtnGetDownloadUrl.Tag = info.download_url;
        }

        /// <summary>
        /// 清理版本号字符串，用于版本比较
        /// 去掉 v 前缀和 Git commit hash
        /// </summary>
        private static string CleanVersionString(string version)
        {
            if (string.IsNullOrEmpty(version))
                return "";
            
            // 去掉 v 前缀
            if (version.StartsWith("v", StringComparison.OrdinalIgnoreCase))
                version = version.Substring(1);
            
            // 去掉 Git commit hash (+ 号后面的部分)
            var plusIndex = version.IndexOf('+');
            if (plusIndex > 0)
                version = version.Substring(0, plusIndex);
            
            return version.Trim();
        }

        /// <summary>
        /// 显示信息栏
        /// </summary>
        private void ShowInfoBar(InfoBarSeverity severity, string message)
        {
            UpdateInfoBar.Severity = severity;
            UpdateInfoBar.Message = message;
        }

        /// <summary>
        /// 点击"从 GitHub 下载"按钮
        /// </summary>
        private void OnOpenGithubClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var github = BtnOpenGithub.Tag as string;
                if (!string.IsNullOrEmpty(github))
                {
                    var url = $"https://github.com/{github}";
                    Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
                    Logger.Info($"[SettingsPage] Opening GitHub: {url}");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to open GitHub", ex);
            }
        }

        /// <summary>
        /// 点击"获取下载链接"按钮
        /// </summary>
        private void OnGetDownloadUrlClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var downloadUrl = BtnGetDownloadUrl.Tag as string;
                if (!string.IsNullOrEmpty(downloadUrl))
                {
                    Process.Start(new ProcessStartInfo(downloadUrl) { UseShellExecute = true });
                    Logger.Info($"[SettingsPage] Opening download URL: {downloadUrl}");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to open download URL", ex);
            }
        }

        // ── 辅助方法 ─────────────────────────────────────────────────────

        private static int ClampWorkers(int v)
        {
            if (v < 1)  return 1;
            if (v > 16) return 16;
            return v;
        }

        private static int ReadComboInt(System.Windows.Controls.ComboBox combo, int fallback)
        {
            try
            {
                if (combo.SelectedItem is ComboBoxItem item &&
                    int.TryParse(item.Content?.ToString(), out int v))
                    return v;
            }
            catch { }
            return fallback;
        }

        private static void SelectComboByInt(System.Windows.Controls.ComboBox combo, int value)
        {
            foreach (var obj in combo.Items.OfType<ComboBoxItem>())
            {
                if (int.TryParse(obj.Content?.ToString(), out int v) && v == value)
                {
                    combo.SelectedItem = obj;
                    return;
                }
            }
            if (combo.Items.Count > 0) combo.SelectedIndex = 0;
        }

        private string CleanAndValidateUrl(string inputUrl)
        {
            string url = inputUrl?.Trim() ?? "";
            if (string.IsNullOrWhiteSpace(url))
                return "https://api.notion.com/v1";
            if (!url.StartsWith("http://",  StringComparison.OrdinalIgnoreCase) &&
                !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                return "https://api.notion.com/v1";
            return url.TrimEnd('/');
        }

        // ── 主题色相关方法 ─────────────────────────────────────────────────

        /// <summary>
        /// 加载主题色配置到UI
        /// </summary>
        private void LoadThemeColor()
        {
            try
            {
                string colorHex = ConfigManager.Current?.ThemeAccentColor ?? ConfigData.DefaultThemeAccentColor;
                if (string.IsNullOrWhiteSpace(colorHex))
                    colorHex = ConfigData.DefaultThemeAccentColor;

                // 确保颜色值格式正确
                if (!colorHex.StartsWith("#"))
                    colorHex = "#" + colorHex;

                // 设置嵌入式颜色选择器的初始颜色
                if (ColorPicker != null)
                {
                    ColorPicker.SelectedColor = colorHex;
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Load theme color failed", ex);
            }
        }

        /// <summary>
        /// 颜色选择器颜色变化事件处理（仅更新UI，不保存）
        /// </summary>
        private void OnColorPickerColorChanged(object? sender, EventArgs e)
        {
            try
            {
                if (ColorPicker == null) return;
                
                string selectedColor = ColorPicker.SelectedColor;
                if (string.IsNullOrWhiteSpace(selectedColor))
                    return;

                Logger.Info($"[SettingsPage] Theme color UI changed to: {selectedColor} (not saved yet)");
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Theme color change failed", ex);
            }
        }

        // ── 背景材质相关方法 ─────────────────────────────────────────────────

        /// <summary>
        /// 加载背景材质配置到UI
        /// </summary>
        private void LoadBackgroundMaterial()
        {
            try
            {
                string material = ConfigManager.Current?.BackgroundMaterial ?? "Mica";
                if (string.IsNullOrWhiteSpace(material) || (material != "Mica" && material != "Acrylic"))
                    material = "Mica";

                // 设置下拉框选择
                if (BackgroundMaterialCombo != null)
                {
                    foreach (ComboBoxItem item in BackgroundMaterialCombo.Items)
                    {
                        if (item.Tag?.ToString() == material)
                        {
                            BackgroundMaterialCombo.SelectedItem = item;
                            break;
                        }
                    }
                }

                // 加载不透明度
                double opacity = ConfigManager.Current?.AcrylicOpacity ?? 0.8;
                if (opacity < 0.0 || opacity > 1.0)
                    opacity = 0.8;

                if (AcrylicOpacitySlider != null)
                {
                    AcrylicOpacitySlider.Value = opacity;
                    UpdateAcrylicOpacityDisplay(opacity);
                }

                // 根据选择的材质显示/隐藏不透明度面板
                UpdateAcrylicOpacityPanelVisibility(material == "Acrylic");
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Load background material failed", ex);
            }
        }

        /// <summary>
        /// 保存背景材质配置
        /// </summary>
        private void SaveBackgroundMaterial()
        {
            try
            {
                // 保存材质类型
                if (BackgroundMaterialCombo?.SelectedItem is ComboBoxItem selectedItem)
                {
                    string material = selectedItem.Tag?.ToString() ?? "Mica";
                    if (material != "Mica" && material != "Acrylic")
                        material = "Mica";
                    ConfigManager.Current.BackgroundMaterial = material;
                }

                // 保存不透明度
                if (AcrylicOpacitySlider != null)
                {
                    double opacity = AcrylicOpacitySlider.Value;
                    if (opacity < 0.0) opacity = 0.0;
                    if (opacity > 1.0) opacity = 1.0;
                    ConfigManager.Current.AcrylicOpacity = opacity;
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Save background material failed", ex);
            }
        }

        /// <summary>
        /// 背景材质选择变化事件处理（仅更新UI，不保存）
        /// </summary>
        private void OnBackgroundMaterialChanged(object sender, SelectionChangedEventArgs e)
        {
            try
            {
                if (BackgroundMaterialCombo?.SelectedItem is ComboBoxItem selectedItem)
                {
                    string material = selectedItem.Tag?.ToString() ?? "Mica";
                    UpdateAcrylicOpacityPanelVisibility(material == "Acrylic");
                    
                    Logger.Info($"[SettingsPage] Background material UI changed to: {material} (not saved yet)");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Background material change failed", ex);
            }
        }

        /// <summary>
        /// 更新亚克力不透明度面板的可见性
        /// </summary>
        private void UpdateAcrylicOpacityPanelVisibility(bool isVisible)
        {
            if (AcrylicOpacityPanel != null)
            {
                AcrylicOpacityPanel.Visibility = isVisible ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        /// <summary>
        /// 亚克力不透明度滑动条值变化事件处理（仅更新UI显示，不保存）
        /// </summary>
        private void OnAcrylicOpacityChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            try
            {
                UpdateAcrylicOpacityDisplay(e.NewValue);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Acrylic opacity change failed", ex);
            }
        }

        /// <summary>
        /// 更新不透明度显示文本
        /// </summary>
        private void UpdateAcrylicOpacityDisplay(double opacity)
        {
            if (AcrylicOpacityValue != null)
            {
                int percentage = (int)(opacity * 100);
                AcrylicOpacityValue.Text = $"{percentage}%";
            }
        }

        /// <summary>
        /// 点击"保存"按钮（仅保存外观设置，不重启）
        /// </summary>
        private void OnSaveAppearanceClick(object sender, RoutedEventArgs e)
        {
            try
            {
                ConfigManager.Load();

                // 保存主题色（从嵌入式颜色选择器读取）
                if (ColorPicker != null && !string.IsNullOrEmpty(ColorPicker.SelectedColor))
                {
                    ConfigManager.Current.ThemeAccentColor = ColorPicker.SelectedColor;
                }

                // 保存背景材质配置
                SaveBackgroundMaterial();

                ConfigManager.Save();

                Logger.Info("[SettingsPage] Appearance settings saved");
                System.Windows.MessageBox.Show("外观设置已保存。部分设置需要重启应用才能完全生效。", "保存成功", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Save appearance settings failed", ex);
                System.Windows.MessageBox.Show($"保存外观设置失败：{ex.Message}", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// 点击"保存并重启应用"按钮
        /// </summary>
        private void OnSaveAndRestartClick(object sender, RoutedEventArgs e)
        {
            try
            {
                // 先保存设置
                ConfigManager.Load();

                // 保存主题色（从嵌入式颜色选择器读取）
                if (ColorPicker != null && !string.IsNullOrEmpty(ColorPicker.SelectedColor))
                {
                    ConfigManager.Current.ThemeAccentColor = ColorPicker.SelectedColor;
                }

                // 保存背景材质配置
                SaveBackgroundMaterial();

                ConfigManager.Save();

                Logger.Info("[SettingsPage] Appearance settings saved, restarting application");

                // 然后重启应用
                RestartApplication();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Save and restart failed", ex);
                System.Windows.MessageBox.Show($"保存并重启失败：{ex.Message}", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// 重启应用程序
        /// </summary>
        private void RestartApplication()
        {
            try
            {
                // 获取当前应用程序的路径
                string appPath = System.Reflection.Assembly.GetExecutingAssembly().Location;
                
                ProcessStartInfo startInfo;
                
                // 如果是 .dll 文件（Debug 模式），需要特殊处理
                if (appPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
                {
                    // 尝试查找同名的 .exe 文件
                    string exePath = appPath.Substring(0, appPath.Length - 4) + ".exe";
                    if (System.IO.File.Exists(exePath))
                    {
                        // 如果找到 .exe 文件，使用它
                        startInfo = new ProcessStartInfo(exePath) { UseShellExecute = true };
                    }
                    else
                    {
                        // 如果找不到 .exe，使用 dotnet 命令运行 .dll
                        startInfo = new ProcessStartInfo
                        {
                            FileName = "dotnet",
                            Arguments = $"\"{appPath}\"",
                            UseShellExecute = true
                        };
                    }
                }
                else
                {
                    // 如果是 .exe 文件（Release 模式或已发布版本），直接启动
                    startInfo = new ProcessStartInfo(appPath) { UseShellExecute = true };
                }
                
                // 启动新进程
                Process.Start(startInfo);
                
                // 关闭当前应用
                Application.Current.Shutdown();
                
                Logger.Info("[SettingsPage] Application restarted");
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to restart application", ex);
                System.Windows.MessageBox.Show($"重启应用失败：{ex.Message}", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }
    }
}
