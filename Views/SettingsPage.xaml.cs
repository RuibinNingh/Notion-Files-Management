using System;
using System.Diagnostics;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Win32;
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

        // ── 自动排版相关 ─────────────────────────────────────────────────
        
        /// <summary>
        /// 所有独立的节区块（按显示顺序），将在 Loaded 时从 SectionPool 中提取
        /// </summary>
        private StackPanel[] _sections = Array.Empty<StackPanel>();
        
        /// <summary>
        /// 节区块间距（非首块顶部 Margin）
        /// </summary>
        private const double SectionSpacing = 20.0;
        
        /// <summary>
        /// 双列模式断点宽度
        /// </summary>
        private const double LayoutBreakpoint = 1200.0;
        
        /// <summary>
        /// 当前是否处于单列布局
        /// </summary>
        private bool _isSingleColumn = false;

        /// <summary>
        /// 运行时发现的最近祖先 ScrollViewer（来自 NavigationView 内部模板）
        /// </summary>
        private ScrollViewer? _ancestorScrollViewer = null;

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
                
                // 初始化自动排版
                InitializeSectionLayout();
                
                // 诊断 + 发现祖先 ScrollViewer
                DumpVisualTreeAncestors();
                
                // 注册鼠标滚轮拦截（handledEventsToo=true 确保即使被子控件吃掉也能触发）
                this.AddHandler(
                    UIElement.PreviewMouseWheelEvent,
                    new System.Windows.Input.MouseWheelEventHandler(OnPagePreviewMouseWheel),
                    handledEventsToo: true);
            };
            
            // 监听窗口大小变化
            SizeChanged += OnPageSizeChanged;
        }

        // ── 滚动处理 + 视觉树诊断 ─────────────────────────────────────────

        /// <summary>
        /// 遍历视觉树祖先，找到最近的 ScrollViewer 并记录完整链路。
        /// 这是定位滚动问题的关键诊断方法。
        /// </summary>
        private void DumpVisualTreeAncestors()
        {
            try
            {
                Logger.Info("[SettingsPage:VisualTree] ═══ 开始遍历祖先链 ═══");
                
                DependencyObject current = this;
                int depth = 0;
                _ancestorScrollViewer = null;
                
                while (current != null)
                {
                    string typeName = current.GetType().FullName ?? current.GetType().Name;
                    string name = (current is FrameworkElement fe) ? (fe.Name ?? "(unnamed)") : "(no-name)";
                    string size = (current is FrameworkElement fe2) 
                        ? $"Actual={fe2.ActualWidth:F0}x{fe2.ActualHeight:F0}" 
                        : "";
                    
                    string extra = "";
                    if (current is ScrollViewer sv)
                    {
                        extra = $" ★ScrollViewer★ Viewport={sv.ViewportHeight:F0}, Extent={sv.ExtentHeight:F0}, " +
                                $"Scrollable={sv.ScrollableHeight:F0}, VBar={sv.VerticalScrollBarVisibility}, " +
                                $"Computed={sv.ComputedVerticalScrollBarVisibility}";
                        
                        // 记录第一个找到的祖先 ScrollViewer
                        if (_ancestorScrollViewer == null)
                        {
                            _ancestorScrollViewer = sv;
                            extra += " ← 已捕获为目标 ScrollViewer";
                        }
                    }
                    
                    Logger.Info($"[SettingsPage:VisualTree] [{depth}] {typeName} Name=\"{name}\" {size}{extra}");
                    
                    current = VisualTreeHelper.GetParent(current);
                    depth++;
                    
                    if (depth > 50) break; // 安全阀
                }
                
                Logger.Info($"[SettingsPage:VisualTree] ═══ 遍历完毕，共 {depth} 层 ═══");
                
                if (_ancestorScrollViewer != null)
                {
                    Logger.Info($"[SettingsPage:VisualTree] ✓ 已找到祖先 ScrollViewer: " +
                                $"Name=\"{_ancestorScrollViewer.Name}\", Type={_ancestorScrollViewer.GetType().Name}");
                }
                else
                {
                    Logger.Warn("[SettingsPage:VisualTree] ✗ 未找到任何祖先 ScrollViewer！滚动可能不工作。");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage:VisualTree] Dump failed", ex);
            }
        }

        /// <summary>
        /// Page 级别鼠标滚轮处理。
        /// 找到祖先 ScrollViewer 并手动驱动滚动，防止 Slider/ComboBox 吞事件。
        /// </summary>
        private void OnPagePreviewMouseWheel(object sender, System.Windows.Input.MouseWheelEventArgs e)
        {
            // 优先使用已发现的祖先 ScrollViewer
            ScrollViewer? target = _ancestorScrollViewer;
            
            if (target == null)
            {
                Logger.Warn("[SettingsPage:Scroll] No ancestor ScrollViewer found, cannot scroll");
                return;
            }

            double scrollAmount = e.Delta > 0 ? -48.0 : 48.0;
            double newOffset = target.VerticalOffset + scrollAmount;
            
            if (newOffset < 0) newOffset = 0;
            if (newOffset > target.ScrollableHeight) newOffset = target.ScrollableHeight;
            
            target.ScrollToVerticalOffset(newOffset);
            e.Handled = true;
            
            // 诊断日志（确认滚动正在工作，调试后可移除）
            Logger.Info($"[SettingsPage:Scroll] delta={e.Delta}, offset={newOffset:F0}/{target.ScrollableHeight:F0}, " +
                        $"viewport={target.ViewportHeight:F0}, extent={target.ExtentHeight:F0}");
        }

        /// <summary>
        /// 初始化自动排版：从 SectionPool 提取所有节区块，执行首次分配
        /// </summary>
        private void InitializeSectionLayout()
        {
            try
            {
                // 提取节区块引用（按显示顺序）
                _sections = new StackPanel[]
                {
                    SectionNotionConfig,
                    SectionTaskWorkers,
                    SectionThemeColor,
                    SectionBackground,
                    SectionAbout
                };

                // 从 SectionPool 移除所有节区块
                SectionPool.Children.Clear();
                SectionPool.Visibility = Visibility.Collapsed;

                // 执行首次分配
                var window = Window.GetWindow(this);
                double windowWidth = window?.ActualWidth ?? ActualWidth;
                DistributeSections(windowWidth);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Initialize section layout failed", ex);
            }
        }

        /// <summary>
        /// 页面大小变化事件处理
        /// </summary>
        private void OnPageSizeChanged(object sender, SizeChangedEventArgs e)
        {
            var window = Window.GetWindow(this);
            double windowWidth = window?.ActualWidth ?? ActualWidth;
            DistributeSections(windowWidth);
        }

        /// <summary>
        /// 根据窗口宽度分配节区块到列中
        /// 窄窗口（&lt; 1200px）：单列布局
        /// 宽窗口（≥ 1200px）：双列布局，使用贪心高度平衡算法
        /// </summary>
        private void DistributeSections(double windowWidth)
        {
            if (_sections == null || _sections.Length == 0 || MainGrid == null)
                return;

            try
            {
                bool shouldBeSingleColumn = windowWidth < LayoutBreakpoint;

                // 1. 从当前父容器中移除所有节区块
                foreach (var section in _sections)
                {
                    if (section.Parent is Panel parent)
                        parent.Children.Remove(section);
                }

                if (shouldBeSingleColumn)
                {
                    // ── 单列布局 ──
                    _isSingleColumn = true;
                    RightColumnDef.Width = new GridLength(0);
                    ColumnLeft.Margin = new Thickness(0);
                    ColumnRight.Margin = new Thickness(0);

                    for (int i = 0; i < _sections.Length; i++)
                    {
                        _sections[i].Margin = new Thickness(0, i > 0 ? SectionSpacing : 0, 0, 0);
                        ColumnLeft.Children.Add(_sections[i]);
                    }
                }
                else
                {
                    // ── 双列布局：贪心高度平衡 ──
                    _isSingleColumn = false;
                    RightColumnDef.Width = new GridLength(1, GridUnitType.Star);
                    ColumnLeft.Margin = new Thickness(0, 0, 15, 0);
                    ColumnRight.Margin = new Thickness(15, 0, 0, 0);

                    // 测量每个节区块的期望高度
                    double availableWidth = Math.Max(200, (windowWidth - 90) / 2); // 减去 Margin 和间距
                    var heights = new double[_sections.Length];
                    for (int i = 0; i < _sections.Length; i++)
                    {
                        _sections[i].Measure(new Size(availableWidth, double.PositiveInfinity));
                        heights[i] = _sections[i].DesiredSize.Height + SectionSpacing;
                    }

                    // 贪心分配：依次将区块放入当前较矮的列
                    double leftHeight = 0, rightHeight = 0;
                    var leftIndices = new System.Collections.Generic.List<int>();
                    var rightIndices = new System.Collections.Generic.List<int>();

                    for (int i = 0; i < _sections.Length; i++)
                    {
                        if (leftHeight <= rightHeight)
                        {
                            leftIndices.Add(i);
                            leftHeight += heights[i];
                        }
                        else
                        {
                            rightIndices.Add(i);
                            rightHeight += heights[i];
                        }
                    }

                    // 将区块添加到对应列
                    for (int j = 0; j < leftIndices.Count; j++)
                    {
                        int idx = leftIndices[j];
                        _sections[idx].Margin = new Thickness(0, j > 0 ? SectionSpacing : 0, 0, 0);
                        ColumnLeft.Children.Add(_sections[idx]);
                    }
                    for (int j = 0; j < rightIndices.Count; j++)
                    {
                        int idx = rightIndices[j];
                        _sections[idx].Margin = new Thickness(0, j > 0 ? SectionSpacing : 0, 0, 0);
                        ColumnRight.Children.Add(_sections[idx]);
                    }

                    Logger.Info($"[SettingsPage] Layout balanced: Left=[{string.Join(",", leftIndices)}] ({leftHeight:F0}px), Right=[{string.Join(",", rightIndices)}] ({rightHeight:F0}px)");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Distribute sections failed", ex);
            }
        }

        /// <summary>
        /// 保存基础配置（Token、URL、并发数）
        /// </summary>
        private void SaveBasicConfig()
        {
            ConfigManager.Load();

            string inputToken = TokenInput.Password?.Trim() ?? "";
            string inputUrl = NotionUrlInput.Text?.Trim() ?? "";
            int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
            int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo, fallback: 3));

            string cleanedUrl = CleanAndValidateUrl(inputUrl);

            ConfigManager.Current.NotionToken = inputToken;
            ConfigManager.Current.NotionBaseUrl = cleanedUrl;
            ConfigManager.Current.MaxDownloadWorkers = dl;
            ConfigManager.Current.MaxUploadWorkers = ul;
            
            ConfigManager.Save();
        }

        private void OnSaveClick(object sender, RoutedEventArgs e)
        {
            try
            {
                SaveBasicConfig();
                // 注意：外观设置（主题色、背景材质）需要通过外观块的保存按钮单独保存
                // 这里不保存外观设置，避免覆盖用户未保存的外观设置
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
                SaveBasicConfig();

                BtnApplyWorkersReset.IsEnabled = false;

                string inputToken = TokenInput.Password?.Trim() ?? "";
                string inputUrl = NotionUrlInput.Text?.Trim() ?? "";
                int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
                int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo, fallback: 3));
                string cleanedUrl = CleanAndValidateUrl(inputUrl);

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
                if (string.IsNullOrWhiteSpace(material) || 
                    (material != "Mica" && material != "Acrylic" && material != "Image"))
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

                // 加载亚克力不透明度
                double opacity = ConfigManager.Current?.AcrylicOpacity ?? 0.8;
                if (opacity < 0.0 || opacity > 1.0)
                    opacity = 0.8;

                if (AcrylicOpacitySlider != null)
                {
                    AcrylicOpacitySlider.Value = opacity;
                    UpdateAcrylicOpacityDisplay(opacity);
                }

                // 加载图片背景设置
                if (ImagePathInput != null)
                {
                    ImagePathInput.Text = ConfigManager.Current?.BackgroundImagePath ?? "";
                }

                double imgBlur = ConfigManager.Current?.BackgroundImageBlur ?? 0;
                if (imgBlur < 0) imgBlur = 0;
                if (imgBlur > 50) imgBlur = 50;
                if (ImageBlurSlider != null)
                {
                    ImageBlurSlider.Value = imgBlur;
                    UpdateImageBlurDisplay(imgBlur);
                }

                double imgOpacity = ConfigManager.Current?.BackgroundImageOpacity ?? 0.3;
                if (imgOpacity < 0.0) imgOpacity = 0.0;
                if (imgOpacity > 1.0) imgOpacity = 1.0;
                if (ImageOpacitySlider != null)
                {
                    ImageOpacitySlider.Value = imgOpacity;
                    UpdateImageOpacityDisplay(imgOpacity);
                }

                // 根据选择的材质显示/隐藏对应面板
                UpdateBackgroundPanelVisibility(material);
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
                    if (material != "Mica" && material != "Acrylic" && material != "Image")
                        material = "Mica";
                    ConfigManager.Current.BackgroundMaterial = material;
                }

                // 保存亚克力不透明度
                if (AcrylicOpacitySlider != null)
                {
                    double opacity = AcrylicOpacitySlider.Value;
                    if (opacity < 0.0) opacity = 0.0;
                    if (opacity > 1.0) opacity = 1.0;
                    ConfigManager.Current.AcrylicOpacity = opacity;
                }

                // 保存图片背景设置
                if (ImagePathInput != null)
                {
                    ConfigManager.Current.BackgroundImagePath = ImagePathInput.Text?.Trim() ?? "";
                }
                if (ImageBlurSlider != null)
                {
                    double blur = ImageBlurSlider.Value;
                    if (blur < 0) blur = 0;
                    if (blur > 50) blur = 50;
                    ConfigManager.Current.BackgroundImageBlur = blur;
                }
                if (ImageOpacitySlider != null)
                {
                    double imgOpacity = ImageOpacitySlider.Value;
                    if (imgOpacity < 0.0) imgOpacity = 0.0;
                    if (imgOpacity > 1.0) imgOpacity = 1.0;
                    ConfigManager.Current.BackgroundImageOpacity = imgOpacity;
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
                    UpdateBackgroundPanelVisibility(material);
                    
                    Logger.Info($"[SettingsPage] Background material UI changed to: {material} (not saved yet)");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Background material change failed", ex);
            }
        }

        /// <summary>
        /// 根据材质类型更新面板可见性
        /// </summary>
        private void UpdateBackgroundPanelVisibility(string material)
        {
            UpdateAcrylicOpacityPanelVisibility(material == "Acrylic");
            UpdateImageBackgroundPanelVisibility(material == "Image");
            
            // 子面板可见性变化后，重新平衡布局（延迟执行，等待布局更新）
            Dispatcher.BeginInvoke(new Action(() =>
            {
                var window = Window.GetWindow(this);
                double windowWidth = window?.ActualWidth ?? ActualWidth;
                DistributeSections(windowWidth);
            }), System.Windows.Threading.DispatcherPriority.Loaded);
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
        /// 更新图片背景面板的可见性
        /// </summary>
        private void UpdateImageBackgroundPanelVisibility(bool isVisible)
        {
            if (ImageBackgroundPanel != null)
            {
                ImageBackgroundPanel.Visibility = isVisible ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        /// <summary>
        /// 浏览图片/视频文件按钮点击事件
        /// </summary>
        private void OnBrowseImageClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var dialog = new OpenFileDialog
                {
                    Title = "选择背景图片或视频",
                    Filter = "图片和视频文件|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.mp4|图片文件|*.png;*.jpg;*.jpeg;*.bmp;*.gif|视频文件|*.mp4|所有文件|*.*",
                    CheckFileExists = true
                };

                if (dialog.ShowDialog() == true)
                {
                    if (ImagePathInput != null)
                    {
                        ImagePathInput.Text = dialog.FileName;
                        Logger.Info($"[SettingsPage] Background image path selected: {dialog.FileName}");
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Browse image file failed", ex);
            }
        }

        /// <summary>
        /// 图片模糊度滑动条值变化事件处理（仅更新UI显示，不保存）
        /// </summary>
        private void OnImageBlurChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            try
            {
                UpdateImageBlurDisplay(e.NewValue);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Image blur change failed", ex);
            }
        }

        /// <summary>
        /// 更新模糊度显示文本
        /// </summary>
        private void UpdateImageBlurDisplay(double blur)
        {
            if (ImageBlurValue != null)
            {
                ImageBlurValue.Text = $"{(int)blur}px";
            }
        }

        /// <summary>
        /// 图片不透明度滑动条值变化事件处理（仅更新UI显示，不保存）
        /// </summary>
        private void OnImageOpacityChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            try
            {
                UpdateImageOpacityDisplay(e.NewValue);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Image opacity change failed", ex);
            }
        }

        /// <summary>
        /// 更新图片不透明度显示文本
        /// </summary>
        private void UpdateImageOpacityDisplay(double opacity)
        {
            if (ImageOpacityValue != null)
            {
                int percentage = (int)(opacity * 100);
                ImageOpacityValue.Text = $"{percentage}%";
            }
        }

        /// <summary>
        /// 保存外观设置（主题色和背景材质）
        /// </summary>
        private void SaveAppearanceSettings()
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
        }

        /// <summary>
        /// 点击"保存"按钮（仅保存外观设置，不重启）
        /// </summary>
        private void OnSaveAppearanceClick(object sender, RoutedEventArgs e)
        {
            try
            {
                SaveAppearanceSettings();

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
                SaveAppearanceSettings();

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
                // 优先使用 Environment.ProcessPath（.NET 6+），兼容单文件发布模式
                // Assembly.GetExecutingAssembly().Location 在单文件发布时返回空字符串
                string? appPath = Environment.ProcessPath;

                // 回退方案：通过当前进程获取路径
                if (string.IsNullOrEmpty(appPath))
                {
                    appPath = Process.GetCurrentProcess().MainModule?.FileName;
                }

                if (string.IsNullOrEmpty(appPath))
                {
                    Logger.Error("[SettingsPage] Failed to determine application path for restart");
                    System.Windows.MessageBox.Show("无法确定应用程序路径，重启失败。请手动重启应用。", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
                    return;
                }

                Logger.Info($"[SettingsPage] Restarting application from path: {appPath}");

                ProcessStartInfo startInfo;

                // 如果是 .dll 文件（Debug 模式下 dotnet run），需要通过 dotnet 命令启动
                if (appPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
                {
                    // 尝试查找同名的 .exe 文件
                    string exePath = appPath.Substring(0, appPath.Length - 4) + ".exe";
                    if (System.IO.File.Exists(exePath))
                    {
                        startInfo = new ProcessStartInfo(exePath) { UseShellExecute = true };
                    }
                    else
                    {
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
                    // .exe 文件（Release 模式或已发布版本），直接启动
                    startInfo = new ProcessStartInfo(appPath) { UseShellExecute = true };
                }

                // 启动新进程
                Process.Start(startInfo);

                Logger.Info("[SettingsPage] New process started, shutting down current instance");

                // 关闭当前应用
                Application.Current.Shutdown();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to restart application", ex);
                System.Windows.MessageBox.Show($"重启应用失败：{ex.Message}", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }
    }
}
