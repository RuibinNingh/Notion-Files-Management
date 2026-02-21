using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
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

        // 自动推送背景配置端点
        private const string BgConfigEndpointHttps = "https://nfm.ruibin-ningh.top/background/config.json";
        private const string BgConfigEndpointHttp  = "http://nfm.ruibin-ningh.top/background/config.json";
        private const string BgBaseUrlHttps = "https://nfm.ruibin-ningh.top";
        private const string BgBaseUrlHttp  = "http://nfm.ruibin-ningh.top";

        // 使用静态 HttpClient 避免 socket 资源泄漏
        private static readonly HttpClient _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(15)
        };

        // 下载更新用的 HttpClient（超时更长）
        private static readonly HttpClient _downloadHttpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(10)
        };

        // 版本信息数据模型（与服务端 JSON 字段对应）
        internal sealed class VersionInfo
        {
            public string version { get; set; } = "";
            public string build_date { get; set; } = "";
            public string github { get; set; } = "";
            public DownloadInfo? download { get; set; }
            public string[] changelog { get; set; } = Array.Empty<string>();
        }

        internal sealed class DownloadInfo
        {
            public ManualDownloadInfo? manual { get; set; }
            public AutoDownloadEntry[] auto { get; set; } = Array.Empty<AutoDownloadEntry>();
        }

        internal sealed class ManualDownloadInfo
        {
            public string url { get; set; } = "";
            public string label { get; set; } = "";
        }

        internal sealed class AutoDownloadEntry
        {
            public string id { get; set; } = "";
            public string label { get; set; } = "";
            public string url { get; set; } = "";
            public int priority { get; set; } = 99;
            /// <summary>
            /// 下载类型："installer"（安装包，默认）或 "exe"（裸 exe，需替换自身）
            /// </summary>
            public string type { get; set; } = "installer";
        }

        // ── 自动推送背景配置数据模型 ─────────────────────────────────────
        internal sealed class BgConfigResponse
        {
            public BgPresetItem? @default { get; set; }
            public BgPresetItem[] list { get; set; } = Array.Empty<BgPresetItem>();
        }

        internal sealed class BgPresetItem
        {
            public string name { get; set; } = "";
            public string src { get; set; } = "";
        }

        /// <summary>
        /// 当前加载的背景配置（供预设选择使用）
        /// </summary>
        private BgConfigResponse? _bgConfig;

        /// <summary>
        /// 背景配置 JSON 本地缓存文件路径
        /// </summary>
        private static readonly string _bgConfigCachePath = System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "NotionFilesManagement", "background_cache", "config_cache.json");

        /// <summary>
        /// 缩略图本地缓存目录
        /// </summary>
        private static readonly string _thumbCacheDir = System.IO.Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "NotionFilesManagement", "background_cache", "thumbs");

        /// <summary>
        /// 静态缓存：启动时静默检查的版本信息（供 SettingsPage 使用）
        /// </summary>
        internal static VersionInfo? CachedVersionInfo { get; set; }

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

        /// <summary>
        /// 自动更新会话单例引用（跨页面持久化下载进度）
        /// </summary>
        private readonly AutoUpdateSession _autoUpdateSession = AutoUpdateSession.Instance;

        /// <summary>
        /// 自动更新进度轮询定时器（页面可见时从 Session 同步进度到 UI）
        /// </summary>
        private DispatcherTimer? _autoUpdatePollTimer;

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
                
                // 如果启动时静默检查已有缓存结果，自动展示
                if (CachedVersionInfo != null)
                {
                    try
                    {
                        VersionInfoPanel.Visibility = Visibility.Visible;
                        RenderVersionInfo(CachedVersionInfo);
                    }
                    catch (Exception ex)
                    {
                        Logger.Error("[SettingsPage] Failed to render cached version info", ex);
                    }
                }

                // ── 恢复自动更新下载状态 ──
                RestoreAutoUpdateState();
            };

            // 页面卸载时停止轮询定时器（页面不可见时不需要更新 UI）
            Unloaded += (s, e) =>
            {
                StopAutoUpdatePolling();
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
                    SectionAppConfig,
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

        /// <summary>
        /// 点击"保存配置"按钮 — 统一保存所有配置（基础 + 外观）
        /// </summary>
        private void OnSaveAllConfigClick(object sender, RoutedEventArgs e)
        {
            try
            {
                SaveBasicConfig();
                SaveAppearanceSettings();

                Logger.Info("[SettingsPage] All config saved (basic + appearance)");
                ShowSaveResultInfoBar(InfoBarSeverity.Success, "保存成功", "所有配置已保存。部分设置需要重启应用才能生效。");
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Save all config failed", ex);
                ShowSaveResultInfoBar(InfoBarSeverity.Error, "保存失败", $"保存配置失败：{ex.Message}");
            }
        }

        /// <summary>
        /// 显示保存结果的内嵌式 InfoBar 提示（替代系统弹窗）
        /// </summary>
        private void ShowSaveResultInfoBar(InfoBarSeverity severity, string title, string message)
        {
            if (SaveResultInfoBar != null)
            {
                SaveResultInfoBar.Severity = severity;
                SaveResultInfoBar.Title = title;
                SaveResultInfoBar.Message = message;
                SaveResultInfoBar.IsOpen = true;
            }
        }

        // OnApplyWorkersResetClick removed — "应用并重置任务" button merged into unified "应用配置" section

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
            
            int cmpResult = CompareVersionStrings(latestVersion, currentVersion);
            
            if (cmpResult > 0)
            {
                // 远程版本 > 本地版本：建议升级
                ShowInfoBar(InfoBarSeverity.Warning, $"发现新版本 {info.version}，建议更新");
                DownloadButtonPanel.Visibility = Visibility.Visible;
            }
            else if (cmpResult < 0)
            {
                // 远程版本 < 本地版本：穿越彩蛋
                ShowInfoBar(InfoBarSeverity.Informational, "你是穿越来的吗？");
                DownloadButtonPanel.Visibility = Visibility.Collapsed;
            }
            else
            {
                // 版本相同：已是最新
                ShowInfoBar(InfoBarSeverity.Success, "已是最新版本");
                DownloadButtonPanel.Visibility = Visibility.Collapsed;
            }

            // 显示详细信息
            VersionDetailGrid.Visibility = Visibility.Visible;

            // 保存下载信息到按钮 Tag，用于后续点击
            BtnOpenGithub.Tag = info.github;
            BtnManualDownload.Tag = info.download?.manual?.url ?? "";
            BtnManualDownload.Content = info.download?.manual?.label ?? "手动下载";

            // 自动更新按钮：仅在有 auto 线路时显示
            bool hasAutoRoutes = info.download?.auto != null && info.download.auto.Length > 0;
            BtnAutoUpdate.Visibility = hasAutoRoutes ? Visibility.Visible : Visibility.Collapsed;
            BtnAutoUpdate.Tag = info; // 保存完整版本信息供自动更新使用
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
        /// 比较两个版本号字符串（格式：X.Y.Z-Status）
        /// 先比较数字部分（X.Y.Z），再比较状态后缀（Status > Beta）
        /// 返回值：正数 = a 更新，0 = 相同，负数 = b 更新
        /// </summary>
        private static int CompareVersionStrings(string a, string b)
        {
            if (string.IsNullOrEmpty(a) && string.IsNullOrEmpty(b)) return 0;
            if (string.IsNullOrEmpty(a)) return -1;
            if (string.IsNullOrEmpty(b)) return 1;

            // 分离数字部分和状态后缀
            SplitVersion(a, out string aNumeric, out string aStatus);
            SplitVersion(b, out string bNumeric, out string bStatus);

            // 比较数字部分（逐段比较）
            var aParts = aNumeric.Split('.');
            var bParts = bNumeric.Split('.');
            int maxLen = Math.Max(aParts.Length, bParts.Length);

            for (int i = 0; i < maxLen; i++)
            {
                int aVal = i < aParts.Length && int.TryParse(aParts[i], out int av) ? av : 0;
                int bVal = i < bParts.Length && int.TryParse(bParts[i], out int bv) ? bv : 0;
                if (aVal != bVal) return aVal.CompareTo(bVal);
            }

            // 数字部分相同，比较状态后缀：Status（正式版） > Beta（测试版）
            int aRank = GetStatusRank(aStatus);
            int bRank = GetStatusRank(bStatus);
            return aRank.CompareTo(bRank);
        }

        /// <summary>
        /// 将版本号分离为数字部分和状态后缀
        /// 例如 "1.3.0-Status" → numeric="1.3.0", status="Status"
        /// </summary>
        private static void SplitVersion(string version, out string numeric, out string status)
        {
            var dashIndex = version.IndexOf('-');
            if (dashIndex > 0)
            {
                numeric = version.Substring(0, dashIndex);
                status = version.Substring(dashIndex + 1);
            }
            else
            {
                numeric = version;
                status = "";
            }
        }

        /// <summary>
        /// 获取版本状态的优先级排名（数值越大越新）
        /// Status（正式版）> Beta（测试版）> 未知
        /// </summary>
        private static int GetStatusRank(string status)
        {
            if (string.IsNullOrEmpty(status)) return 0;
            if (status.Equals("Beta", StringComparison.OrdinalIgnoreCase)) return 1;
            if (status.Equals("Status", StringComparison.OrdinalIgnoreCase)) return 2;
            // 未来可扩展更多状态
            return 0;
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
        /// 点击"手动下载"按钮 — 打开官网下载页
        /// </summary>
        private void OnManualDownloadClick(object sender, RoutedEventArgs e)
        {
            try
            {
                var downloadUrl = BtnManualDownload.Tag as string;
                if (!string.IsNullOrEmpty(downloadUrl))
                {
                    Process.Start(new ProcessStartInfo(downloadUrl) { UseShellExecute = true });
                    Logger.Info($"[SettingsPage] Opening manual download URL: {downloadUrl}");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to open manual download URL", ex);
            }
        }

        /// <summary>
        /// 恢复自动更新下载状态（页面 Loaded 时调用）
        /// 如果 Session 中有正在进行的下载，恢复进度条和按钮状态并启动轮询
        /// </summary>
        private void RestoreAutoUpdateState()
        {
            try
            {
                if (_autoUpdateSession.IsDownloading)
                {
                    Logger.Info("[SettingsPage] Restoring auto-update download state from session");

                    // 确保版本信息面板和下载按钮面板可见
                    VersionInfoPanel.Visibility = Visibility.Visible;
                    DownloadButtonPanel.Visibility = Visibility.Visible;

                    // 恢复按钮状态
                    BtnAutoUpdate.IsEnabled = false;
                    BtnAutoUpdate.Content = _autoUpdateSession.StatusText;
                    BtnAutoUpdate.Visibility = Visibility.Visible;

                    // 恢复进度条状态
                    AutoUpdateProgressBar.Visibility = Visibility.Visible;
                    if (_autoUpdateSession.ProgressPercent < 0)
                    {
                        AutoUpdateProgressBar.IsIndeterminate = true;
                    }
                    else
                    {
                        AutoUpdateProgressBar.IsIndeterminate = false;
                        AutoUpdateProgressBar.Value = _autoUpdateSession.ProgressPercent;
                    }

                    // 启动轮询定时器同步进度
                    StartAutoUpdatePolling();
                }
                else if (_autoUpdateSession.HasFailed)
                {
                    // 下载已失败：显示错误信息
                    VersionInfoPanel.Visibility = Visibility.Visible;
                    DownloadButtonPanel.Visibility = Visibility.Visible;
                    BtnAutoUpdate.Visibility = Visibility.Visible;
                    BtnAutoUpdate.IsEnabled = true;
                    BtnAutoUpdate.Content = "自动更新";
                    AutoUpdateProgressBar.Visibility = Visibility.Collapsed;
                    ShowInfoBar(InfoBarSeverity.Error, _autoUpdateSession.ErrorMessage ?? "所有下载线路均失败，请尝试手动下载");
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Failed to restore auto-update state", ex);
            }
        }

        /// <summary>
        /// 启动自动更新进度轮询定时器（200ms 间隔从 Session 同步进度到 UI）
        /// </summary>
        private void StartAutoUpdatePolling()
        {
            StopAutoUpdatePolling(); // 确保不重复

            _autoUpdatePollTimer = new DispatcherTimer
            {
                Interval = TimeSpan.FromMilliseconds(200)
            };
            _autoUpdatePollTimer.Tick += OnAutoUpdatePollTick;
            _autoUpdatePollTimer.Start();

            Logger.Info("[SettingsPage] Auto-update poll timer started");
        }

        /// <summary>
        /// 停止自动更新进度轮询定时器
        /// </summary>
        private void StopAutoUpdatePolling()
        {
            if (_autoUpdatePollTimer != null)
            {
                _autoUpdatePollTimer.Stop();
                _autoUpdatePollTimer.Tick -= OnAutoUpdatePollTick;
                _autoUpdatePollTimer = null;
                Logger.Info("[SettingsPage] Auto-update poll timer stopped");
            }
        }

        /// <summary>
        /// 自动更新进度轮询回调：从 Session 读取状态并更新当前页面 UI
        /// </summary>
        private void OnAutoUpdatePollTick(object? sender, EventArgs e)
        {
            try
            {
                if (_autoUpdateSession.IsDownloading)
                {
                    // 同步进度
                    BtnAutoUpdate.Content = _autoUpdateSession.StatusText;
                    if (_autoUpdateSession.ProgressPercent < 0)
                    {
                        AutoUpdateProgressBar.IsIndeterminate = true;
                    }
                    else
                    {
                        AutoUpdateProgressBar.IsIndeterminate = false;
                        AutoUpdateProgressBar.Value = _autoUpdateSession.ProgressPercent;
                    }
                }
                else
                {
                    // 下载已结束（成功或失败）
                    StopAutoUpdatePolling();

                    AutoUpdateProgressBar.Visibility = Visibility.Collapsed;
                    BtnAutoUpdate.Content = "自动更新";
                    BtnAutoUpdate.IsEnabled = true;

                    if (_autoUpdateSession.IsCompleted)
                    {
                        // 下载成功后的安装/替换逻辑由 OnAutoUpdateClick 处理
                        // 这里只需确保 UI 状态正确
                    }
                    else if (_autoUpdateSession.HasFailed)
                    {
                        ShowInfoBar(InfoBarSeverity.Error, _autoUpdateSession.ErrorMessage ?? "所有下载线路均失败，请尝试手动下载");
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Auto-update poll tick error", ex);
                StopAutoUpdatePolling();
            }
        }

        /// <summary>
        /// 点击"自动更新"按钮 — 按优先级顺序从 auto 线路下载更新
        /// </summary>
        private async void OnAutoUpdateClick(object sender, RoutedEventArgs e)
        {
            var info = BtnAutoUpdate.Tag as VersionInfo;
            if (info?.download?.auto == null || info.download.auto.Length == 0)
            {
                ShowInfoBar(InfoBarSeverity.Error, "没有可用的自动更新线路");
                return;
            }

            // ── 初始化 Session 状态 ──
            _autoUpdateSession.Reset();
            _autoUpdateSession.IsDownloading = true;
            _autoUpdateSession.StatusText = "下载中...";
            _autoUpdateSession.ProgressPercent = 0;

            BtnAutoUpdate.IsEnabled = false;
            BtnAutoUpdate.Content = "下载中...";
            AutoUpdateProgressBar.Visibility = Visibility.Visible;
            AutoUpdateProgressBar.IsIndeterminate = false;
            AutoUpdateProgressBar.Value = 0;

            // 启动轮询定时器（支持跨页面恢复进度）
            StartAutoUpdatePolling();

            // 按 priority 排序
            var routes = info.download.auto.OrderBy(r => r.priority).ToArray();

            string? downloadedPath = null;
            AutoDownloadEntry? successRoute = null;

            for (int i = 0; i < routes.Length; i++)
            {
                var route = routes[i];
                Logger.Info($"[SettingsPage] Auto-update: trying route '{route.label}' (priority={route.priority}, type={route.type}): {route.url}");
                
                string statusText = $"下载中（{route.label}）...";
                BtnAutoUpdate.Content = statusText;
                _autoUpdateSession.StatusText = statusText;

                try
                {
                    // 确定保存路径
                    string tempDir = Path.Combine(Path.GetTempPath(), "NFM_Update");
                    if (!Directory.Exists(tempDir))
                        Directory.CreateDirectory(tempDir);
                    
                    string fileName = Path.GetFileName(new Uri(route.url).AbsolutePath);
                    if (string.IsNullOrEmpty(fileName))
                        fileName = $"NFM-{info.version}.exe";
                    string savePath = Path.Combine(tempDir, fileName);

                    // 下载文件（带进度）
                    using var response = await _downloadHttpClient.GetAsync(route.url, HttpCompletionOption.ResponseHeadersRead);
                    response.EnsureSuccessStatusCode();

                    long? totalBytes = response.Content.Headers.ContentLength;
                    long receivedBytes = 0;

                    using var contentStream = await response.Content.ReadAsStreamAsync();
                    using var fileStream = new FileStream(savePath, FileMode.Create, FileAccess.Write, FileShare.None, 8192, true);
                    
                    var buffer = new byte[8192];
                    int bytesRead;
                    while ((bytesRead = await contentStream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                    {
                        await fileStream.WriteAsync(buffer, 0, bytesRead);
                        receivedBytes += bytesRead;

                        if (totalBytes.HasValue && totalBytes.Value > 0)
                        {
                            double percent = (double)receivedBytes / totalBytes.Value * 100;
                            AutoUpdateProgressBar.IsIndeterminate = false;
                            AutoUpdateProgressBar.Value = percent;
                            _autoUpdateSession.ProgressPercent = percent;
                        }
                        else
                        {
                            AutoUpdateProgressBar.IsIndeterminate = true;
                            _autoUpdateSession.ProgressPercent = -1; // 不确定进度
                        }
                    }

                    Logger.Info($"[SettingsPage] Auto-update: downloaded {receivedBytes} bytes from '{route.label}' to {savePath}");
                    downloadedPath = savePath;
                    successRoute = route;
                    break; // 下载成功，跳出循环
                }
                catch (Exception ex)
                {
                    Logger.Warn($"[SettingsPage] Auto-update route '{route.label}' failed: {ex.Message}");
                    // 继续尝试下一个线路
                }
            }

            // ── 下载结束，停止轮询 ──
            _autoUpdateSession.IsDownloading = false;
            StopAutoUpdatePolling();

            AutoUpdateProgressBar.Visibility = Visibility.Collapsed;

            if (!string.IsNullOrEmpty(downloadedPath) && File.Exists(downloadedPath))
            {
                _autoUpdateSession.IsCompleted = true;
                _autoUpdateSession.DownloadedFilePath = downloadedPath;
                _autoUpdateSession.SuccessRouteType = successRoute?.type;

                bool isExeReplace = string.Equals(successRoute?.type, "exe", StringComparison.OrdinalIgnoreCase);

                if (isExeReplace)
                {
                    // ── 裸 exe 模式：生成 bat 脚本延迟替换自身 ──
                    ShowInfoBar(InfoBarSeverity.Success, "下载完成，即将替换并重启...");
                    Logger.Info($"[SettingsPage] Auto-update: exe-replace mode, generating update script");

                    try
                    {
                        string currentExe = Environment.ProcessPath!;
                        string batPath = Path.Combine(Path.GetTempPath(), "nfm_update.bat");
                        string batContent = $@"
@echo off
timeout /t 2 /nobreak >nul
copy /y ""{downloadedPath}"" ""{currentExe}""
start """" ""{currentExe}""
del ""%~f0""
";
                        File.WriteAllText(batPath, batContent, System.Text.Encoding.Default);
                        Logger.Info($"[SettingsPage] Auto-update: wrote update script to {batPath}");

                        Process.Start(new ProcessStartInfo(batPath)
                        {
                            UseShellExecute = true,
                            WindowStyle = ProcessWindowStyle.Hidden
                        });
                        System.Windows.Application.Current.Shutdown();
                    }
                    catch (Exception ex)
                    {
                        Logger.Error("[SettingsPage] Failed to execute exe-replace update", ex);
                        ShowInfoBar(InfoBarSeverity.Error, $"替换更新失败：{ex.Message}");
                    }
                }
                else
                {
                    // ── 安装包模式（默认）：直接启动安装程序 ──
                    ShowInfoBar(InfoBarSeverity.Success, "下载完成，即将启动安装程序...");
                    Logger.Info($"[SettingsPage] Auto-update: launching installer: {downloadedPath}");

                    try
                    {
                        Process.Start(new ProcessStartInfo(downloadedPath) { UseShellExecute = true });
                        System.Windows.Application.Current.Shutdown();
                    }
                    catch (Exception ex)
                    {
                        Logger.Error("[SettingsPage] Failed to launch installer", ex);
                        ShowInfoBar(InfoBarSeverity.Error, $"启动安装程序失败：{ex.Message}");
                    }
                }
            }
            else
            {
                _autoUpdateSession.HasFailed = true;
                _autoUpdateSession.ErrorMessage = "所有下载线路均失败，请尝试手动下载";
                ShowInfoBar(InfoBarSeverity.Error, "所有下载线路均失败，请尝试手动下载");
            }

            BtnAutoUpdate.Content = "自动更新";
            BtnAutoUpdate.IsEnabled = true;
        }

        /// <summary>
        /// 启动时静默检查版本更新（由 App.xaml.cs 调用）
        /// 成功时缓存结果，失败时仅记录日志
        /// </summary>
        internal static async Task SilentCheckUpdateAsync()
        {
            try
            {
                var httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };

                string? json = null;
                // 先尝试 HTTPS
                try
                {
                    var response = await httpClient.GetAsync(VersionEndpointHttps);
                    response.EnsureSuccessStatusCode();
                    json = await response.Content.ReadAsStringAsync();
                }
                catch
                {
                    // 降级到 HTTP
                    try
                    {
                        var response = await httpClient.GetAsync(VersionEndpointHttp);
                        response.EnsureSuccessStatusCode();
                        json = await response.Content.ReadAsStringAsync();
                    }
                    catch { }
                }

                if (!string.IsNullOrEmpty(json))
                {
                    var info = JsonSerializer.Deserialize<VersionInfo>(json);
                    if (info != null)
                    {
                        CachedVersionInfo = info;
                        Logger.Info($"[AutoUpdate] Silent check OK: remote={info.version}, local={AppVersion.Current}");
                    }
                }
                else
                {
                    Logger.Warn("[AutoUpdate] Silent version check failed: no response from server");
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"[AutoUpdate] Silent version check failed: {ex.Message}");
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
                string material = ConfigManager.Current?.BackgroundMaterial ?? "AutoPush";
                if (string.IsNullOrWhiteSpace(material) || 
                    (material != "Mica" && material != "Acrylic" && material != "Image" && material != "AutoPush"))
                    material = "AutoPush";

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
                    // UI 显示"不透明度"= 遮挡程度 = 1 - 壁纸可见度
                    ImageOpacitySlider.Value = 1.0 - imgOpacity;
                    UpdateImageOpacityDisplay(1.0 - imgOpacity);
                }

                // 加载自动推送设置
                double apTransparency = ConfigManager.Current?.AutoPushTransparency ?? 0.3;
                if (apTransparency < 0.0) apTransparency = 0.0;
                if (apTransparency > 1.0) apTransparency = 1.0;
                if (AutoPushTransparencySlider != null)
                {
                    AutoPushTransparencySlider.Value = apTransparency;
                    UpdateAutoPushTransparencyDisplay(apTransparency);
                }

                string apName = ConfigManager.Current?.AutoPushBackgroundName ?? "";
                if (AutoPushCurrentName != null)
                {
                    AutoPushCurrentName.Text = string.IsNullOrEmpty(apName) ? "（服务端默认）" : apName;
                }

                // 根据选择的材质显示/隐藏对应面板
                UpdateBackgroundPanelVisibility(material);

                // 如果选中 AutoPush，自动拉取远端配置
                if (material == "AutoPush")
                {
                    _ = FetchBgConfigAsync();
                }
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
                    string material = selectedItem.Tag?.ToString() ?? "AutoPush";
                    if (material != "Mica" && material != "Acrylic" && material != "Image" && material != "AutoPush")
                        material = "AutoPush";
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
                    // 滑条显示"不透明度"（遮挡程度），存储转回壁纸可见度 = 1 - slider
                    double sliderVal = ImageOpacitySlider.Value;
                    if (sliderVal < 0.0) sliderVal = 0.0;
                    if (sliderVal > 1.0) sliderVal = 1.0;
                    ConfigManager.Current.BackgroundImageOpacity = 1.0 - sliderVal;
                }

                // 保存自动推送背景设置
                if (AutoPushTransparencySlider != null)
                {
                    double t = AutoPushTransparencySlider.Value;
                    if (t < 0.0) t = 0.0;
                    if (t > 1.0) t = 1.0;
                    ConfigManager.Current.AutoPushTransparency = t;
                }
                // AutoPushBackgroundName / Src 在选择预设时已写入 ConfigManager.Current
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
                    string material = selectedItem.Tag?.ToString() ?? "AutoPush";
                    UpdateBackgroundPanelVisibility(material);
                    
                    // 选中 AutoPush 时自动拉取远端配置
                    if (material == "AutoPush" && _bgConfig == null)
                    {
                        _ = FetchBgConfigAsync();
                    }

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
            // 自动推送面板
            if (AutoPushPanel != null)
            {
                AutoPushPanel.Visibility = (material == "AutoPush") ? Visibility.Visible : Visibility.Collapsed;
            }

            UpdateAcrylicOpacityPanelVisibility(material == "Acrylic");
            UpdateImageBackgroundPanelVisibility(material == "Image");
            
            // 显示/隐藏视频或图片背景功耗警告
            if (ImagePowerWarningBar != null)
            {
                ImagePowerWarningBar.IsOpen = (material == "Image");
            }
            
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

        // ── 自动推送背景相关方法 ─────────────────────────────────────────

        /// <summary>
        /// 获取背景缓存目录
        /// </summary>
        private static string GetBgCacheDir()
        {
            string dir = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "NotionFilesManagement", "background_cache");
            if (!System.IO.Directory.Exists(dir))
                System.IO.Directory.CreateDirectory(dir);
            return dir;
        }

        /// <summary>
        /// 从服务器获取背景配置（优先读取本地缓存，后台静默刷新）
        /// </summary>
        private async Task FetchBgConfigAsync()
        {
            try
            {
                // ── 第 1 步：尝试从本地磁盘缓存加载 ──
                bool loadedFromCache = false;
                if (_bgConfig == null && System.IO.File.Exists(_bgConfigCachePath))
                {
                    try
                    {
                        string cachedJson = await Task.Run(() => System.IO.File.ReadAllText(_bgConfigCachePath));
                        var cachedConfig = JsonSerializer.Deserialize<BgConfigResponse>(cachedJson);
                        if (cachedConfig != null)
                        {
                            _bgConfig = cachedConfig;
                            loadedFromCache = true;
                            Logger.Info($"[SettingsPage] Bg config loaded from cache: default={cachedConfig.@default?.name}, list count={cachedConfig.list?.Length ?? 0}");

                            Dispatcher.Invoke(() =>
                            {
                                if (BtnSwitchPreset != null) BtnSwitchPreset.IsEnabled = true;

                                string currentName = ConfigManager.Current?.AutoPushBackgroundName ?? "";
                                if (string.IsNullOrEmpty(currentName) && cachedConfig.@default != null)
                                {
                                    currentName = cachedConfig.@default.name;
                                    ConfigManager.Current.AutoPushBackgroundName = cachedConfig.@default.name;
                                    ConfigManager.Current.AutoPushBackgroundSrc = cachedConfig.@default.src;
                                }
                                if (AutoPushCurrentName != null)
                                {
                                    AutoPushCurrentName.Text = string.IsNullOrEmpty(currentName) ? "（服务端默认）" : currentName;
                                }
                            });
                        }
                    }
                    catch (Exception cacheEx)
                    {
                        Logger.Warn($"[SettingsPage] Bg config cache read failed: {cacheEx.Message}");
                    }
                }

                // 如果已经有内存中的配置（含缓存加载的），跳过网络请求的 Loading UI
                if (_bgConfig != null && loadedFromCache)
                {
                    // 后台静默刷新（不显示 Loading）
                    _ = RefreshBgConfigFromNetworkAsync();
                    return;
                }

                // ── 第 2 步：无缓存时，从网络获取（显示 Loading） ──
                Dispatcher.Invoke(() =>
                {
                    if (AutoPushLoadingBar != null) AutoPushLoadingBar.IsOpen = true;
                    if (AutoPushErrorBar != null) AutoPushErrorBar.IsOpen = false;
                    if (BtnSwitchPreset != null) BtnSwitchPreset.IsEnabled = false;
                });

                await FetchAndApplyBgConfigFromNetworkAsync();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] FetchBgConfigAsync failed", ex);
                Dispatcher.Invoke(() =>
                {
                    if (AutoPushLoadingBar != null) AutoPushLoadingBar.IsOpen = false;
                    if (AutoPushErrorBar != null && _bgConfig == null) AutoPushErrorBar.IsOpen = true;
                });
            }
        }

        /// <summary>
        /// 后台静默从网络刷新配置（不影响 UI Loading 状态）
        /// </summary>
        private async Task RefreshBgConfigFromNetworkAsync()
        {
            try
            {
                string json = "";
                try
                {
                    json = await _httpClient.GetStringAsync(BgConfigEndpointHttps);
                }
                catch
                {
                    Logger.Info("[SettingsPage] HTTPS bg config refresh failed, falling back to HTTP");
                    json = await _httpClient.GetStringAsync(BgConfigEndpointHttp);
                }

                var config = JsonSerializer.Deserialize<BgConfigResponse>(json);
                if (config == null) return;

                _bgConfig = config;

                // 写入本地缓存
                SaveBgConfigCache(json);

                Logger.Info($"[SettingsPage] Bg config silently refreshed: default={config.@default?.name}, list count={config.list?.Length ?? 0}");
            }
            catch (Exception ex)
            {
                Logger.Warn($"[SettingsPage] Bg config silent refresh failed (using cache): {ex.Message}");
            }
        }

        /// <summary>
        /// 从网络获取配置并应用到 UI（首次加载时使用，带 Loading 状态）
        /// </summary>
        private async Task FetchAndApplyBgConfigFromNetworkAsync()
        {
            try
            {
                string json = "";
                try
                {
                    json = await _httpClient.GetStringAsync(BgConfigEndpointHttps);
                }
                catch
                {
                    Logger.Info("[SettingsPage] HTTPS bg config failed, falling back to HTTP");
                    json = await _httpClient.GetStringAsync(BgConfigEndpointHttp);
                }

                var config = JsonSerializer.Deserialize<BgConfigResponse>(json);
                if (config == null)
                    throw new Exception("Deserialized config is null");

                _bgConfig = config;

                // 写入本地缓存
                SaveBgConfigCache(json);

                Dispatcher.Invoke(() =>
                {
                    if (AutoPushLoadingBar != null) AutoPushLoadingBar.IsOpen = false;
                    if (BtnSwitchPreset != null) BtnSwitchPreset.IsEnabled = true;

                    // 如果当前没有选中名称，使用默认
                    string currentName = ConfigManager.Current?.AutoPushBackgroundName ?? "";
                    if (string.IsNullOrEmpty(currentName) && config.@default != null)
                    {
                        currentName = config.@default.name;
                        ConfigManager.Current.AutoPushBackgroundName = config.@default.name;
                        ConfigManager.Current.AutoPushBackgroundSrc = config.@default.src;
                    }
                    if (AutoPushCurrentName != null)
                    {
                        AutoPushCurrentName.Text = string.IsNullOrEmpty(currentName) ? "（服务端默认）" : currentName;
                    }

                    Logger.Info($"[SettingsPage] Bg config loaded from network: default={config.@default?.name}, list count={config.list?.Length ?? 0}");
                });
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Fetch bg config from network failed", ex);
                Dispatcher.Invoke(() =>
                {
                    if (AutoPushLoadingBar != null) AutoPushLoadingBar.IsOpen = false;
                    if (AutoPushErrorBar != null) AutoPushErrorBar.IsOpen = true;
                });
            }
        }

        /// <summary>
        /// 将背景配置 JSON 保存到本地缓存
        /// </summary>
        private static void SaveBgConfigCache(string json)
        {
            try
            {
                string dir = System.IO.Path.GetDirectoryName(_bgConfigCachePath)!;
                if (!System.IO.Directory.Exists(dir))
                    System.IO.Directory.CreateDirectory(dir);
                System.IO.File.WriteAllText(_bgConfigCachePath, json);
                Logger.Info("[SettingsPage] Bg config cache saved to disk");
            }
            catch (Exception ex)
            {
                Logger.Warn($"[SettingsPage] Failed to save bg config cache: {ex.Message}");
            }
        }

        /// <summary>
        /// 点击"切换预设"按钮 — 展开/收起预设选择面板
        /// </summary>
        private void OnSwitchPresetClick(object sender, RoutedEventArgs e)
        {
            try
            {
                if (PresetSelectionPanel == null) return;

                if (PresetSelectionPanel.Visibility == Visibility.Visible)
                {
                    PresetSelectionPanel.Visibility = Visibility.Collapsed;
                    return;
                }

                if (_bgConfig == null)
                {
                    Logger.Warn("[SettingsPage] Bg config not loaded yet, cannot show presets");
                    return;
                }

                BuildPresetCards();
                PresetSelectionPanel.Visibility = Visibility.Visible;

                // 重新平衡布局
                Dispatcher.BeginInvoke(new Action(() =>
                {
                    var window = Window.GetWindow(this);
                    double windowWidth = window?.ActualWidth ?? ActualWidth;
                    DistributeSections(windowWidth);
                }), System.Windows.Threading.DispatcherPriority.Loaded);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Switch preset click failed", ex);
            }
        }

        /// <summary>
        /// 构建预设卡片列表（带预览图）
        /// </summary>
        private void BuildPresetCards()
        {
            if (PresetItemsPanel == null || _bgConfig == null) return;
            PresetItemsPanel.Children.Clear();

            // 收集所有预设项：默认 + 列表
            var allPresets = new System.Collections.Generic.List<BgPresetItem>();
            if (_bgConfig.@default != null)
                allPresets.Add(_bgConfig.@default);
            if (_bgConfig.list != null)
                allPresets.AddRange(_bgConfig.list);

            string currentName = ConfigManager.Current?.AutoPushBackgroundName ?? "";

            foreach (var preset in allPresets)
            {
                bool isSelected = preset.name == currentName;
                string fullUrl;
                try { fullUrl = BgBaseUrlHttps + preset.src; }
                catch { fullUrl = BgBaseUrlHttp + preset.src; }

                // 根据后缀判断类型
                string ext = System.IO.Path.GetExtension(preset.src).ToLowerInvariant();
                bool isVideo = ext == ".mp4";
                string typeLabel = isVideo ? "🎬 视频" : "🖼️ 图片";

                // 卡片容器
                var card = new Border
                {
                    Width = 140,
                    Margin = new Thickness(4),
                    CornerRadius = new CornerRadius(8),
                    BorderThickness = new Thickness(isSelected ? 2 : 1),
                    BorderBrush = isSelected 
                        ? (Brush)FindResource("SystemAccentColorPrimaryBrush") 
                        : new SolidColorBrush(System.Windows.Media.Color.FromArgb(0x44, 0xFF, 0xFF, 0xFF)),
                    Background = new SolidColorBrush(System.Windows.Media.Color.FromArgb(0x22, 0xFF, 0xFF, 0xFF)),
                    Padding = new Thickness(4),
                    Cursor = System.Windows.Input.Cursors.Hand,
                    Tag = preset // 将预设信息存入 Tag
                };

                var stack = new StackPanel();

                // 预览图（图片模式下加载缩略图，视频则显示占位符）
                if (!isVideo)
                {
                    var img = new System.Windows.Controls.Image
                    {
                        Height = 80,
                        Stretch = Stretch.UniformToFill,
                        HorizontalAlignment = HorizontalAlignment.Center,
                        Margin = new Thickness(0, 0, 0, 4)
                    };
                    // 异步加载缩略图
                    _ = LoadThumbnailAsync(img, fullUrl);
                    stack.Children.Add(img);
                }
                else
                {
                    var placeholder = new Border
                    {
                        Height = 80,
                        Background = new SolidColorBrush(System.Windows.Media.Color.FromArgb(0x33, 0x88, 0x88, 0xFF)),
                        CornerRadius = new CornerRadius(4),
                        Margin = new Thickness(0, 0, 0, 4),
                        Child = new System.Windows.Controls.TextBlock
                        {
                            Text = "🎬",
                            FontSize = 28,
                            HorizontalAlignment = HorizontalAlignment.Center,
                            VerticalAlignment = VerticalAlignment.Center
                        }
                    };
                    stack.Children.Add(placeholder);
                }

                // 名称 + 类型标签
                var nameBlock = new System.Windows.Controls.TextBlock
                {
                    Text = preset.name,
                    FontWeight = isSelected ? FontWeights.Bold : FontWeights.Normal,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    Foreground = (Brush)FindResource("TextFillColorPrimaryBrush")
                };
                stack.Children.Add(nameBlock);

                var typeBlock = new System.Windows.Controls.TextBlock
                {
                    Text = typeLabel,
                    FontSize = 11,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    Foreground = (Brush)FindResource("TextFillColorTertiaryBrush")
                };
                stack.Children.Add(typeBlock);

                if (isSelected)
                {
                    var checkMark = new System.Windows.Controls.TextBlock
                    {
                        Text = "✓ 已选中",
                        FontSize = 11,
                        Foreground = (Brush)FindResource("SystemAccentColorPrimaryBrush"),
                        HorizontalAlignment = HorizontalAlignment.Center,
                        Margin = new Thickness(0, 2, 0, 0)
                    };
                    stack.Children.Add(checkMark);
                }

                card.Child = stack;
                card.MouseLeftButtonDown += OnPresetCardClicked;
                PresetItemsPanel.Children.Add(card);
            }
        }

        /// <summary>
        /// 异步加载缩略图到 Image 控件（优先从本地磁盘缓存加载）
        /// </summary>
        private async Task LoadThumbnailAsync(System.Windows.Controls.Image imgCtrl, string url)
        {
            try
            {
                // 确定缩略图缓存文件路径
                string thumbFileName = GenerateThumbCacheFileName(url);
                string thumbPath = System.IO.Path.Combine(_thumbCacheDir, thumbFileName);

                byte[]? bytes = null;

                // 优先从磁盘缓存加载
                if (System.IO.File.Exists(thumbPath))
                {
                    try
                    {
                        bytes = await Task.Run(() => System.IO.File.ReadAllBytes(thumbPath));
                    }
                    catch (Exception cacheReadEx)
                    {
                        Logger.Warn($"[SettingsPage] Thumb cache read failed: {cacheReadEx.Message}");
                        bytes = null;
                    }
                }

                // 缓存未命中，从网络下载
                if (bytes == null || bytes.Length == 0)
                {
                    bytes = await _httpClient.GetByteArrayAsync(url);

                    // 写入磁盘缓存
                    try
                    {
                        if (!System.IO.Directory.Exists(_thumbCacheDir))
                            System.IO.Directory.CreateDirectory(_thumbCacheDir);
                        await Task.Run(() => System.IO.File.WriteAllBytes(thumbPath, bytes));
                    }
                    catch (Exception cacheWriteEx)
                    {
                        Logger.Warn($"[SettingsPage] Thumb cache write failed: {cacheWriteEx.Message}");
                    }
                }

                Dispatcher.Invoke(() =>
                {
                    try
                    {
                        var bitmap = new System.Windows.Media.Imaging.BitmapImage();
                        bitmap.BeginInit();
                        bitmap.StreamSource = new System.IO.MemoryStream(bytes);
                        bitmap.DecodePixelHeight = 160; // 缩略图
                        bitmap.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                        bitmap.EndInit();
                        bitmap.Freeze();
                        imgCtrl.Source = bitmap;
                    }
                    catch (Exception ex)
                    {
                        Logger.Warn($"[SettingsPage] Thumbnail decode failed: {ex.Message}");
                    }
                });
            }
            catch (Exception ex)
            {
                Logger.Warn($"[SettingsPage] Thumbnail load failed: {url} → {ex.Message}");
            }
        }

        /// <summary>
        /// 根据 URL 生成缩略图缓存文件名（使用 URL 的文件名部分，确保唯一性）
        /// </summary>
        private static string GenerateThumbCacheFileName(string url)
        {
            try
            {
                // 提取 URL 中的文件名部分，加上路径哈希前缀确保唯一
                var uri = new Uri(url);
                string pathPart = uri.AbsolutePath.TrimStart('/').Replace("/", "_");
                // 过滤非法文件名字符
                foreach (char c in System.IO.Path.GetInvalidFileNameChars())
                    pathPart = pathPart.Replace(c, '_');
                return "thumb_" + pathPart;
            }
            catch
            {
                // 降级：使用哈希
                int hash = url.GetHashCode();
                return $"thumb_{hash:X8}.dat";
            }
        }

        /// <summary>
        /// 预设卡片点击事件 — 选中预设（就地更新样式，不重建卡片）
        /// </summary>
        private void OnPresetCardClicked(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            try
            {
                if (sender is Border card && card.Tag is BgPresetItem preset)
                {
                    // 更新配置
                    ConfigManager.Current.AutoPushBackgroundName = preset.name;
                    ConfigManager.Current.AutoPushBackgroundSrc = preset.src;

                    if (AutoPushCurrentName != null)
                        AutoPushCurrentName.Text = preset.name;

                    Logger.Info($"[SettingsPage] AutoPush preset selected: {preset.name} ({preset.src})");

                    // 就地更新所有卡片的选中/未选中样式（不重建，避免重新加载缩略图）
                    UpdatePresetCardSelectionStyles(preset.name);
                }
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Preset card click failed", ex);
            }
        }

        /// <summary>
        /// 就地更新预设卡片的选中/未选中样式
        /// </summary>
        private void UpdatePresetCardSelectionStyles(string selectedName)
        {
            if (PresetItemsPanel == null) return;

            var accentBrush = (Brush)FindResource("SystemAccentColorPrimaryBrush");
            var normalBorderBrush = new SolidColorBrush(System.Windows.Media.Color.FromArgb(0x44, 0xFF, 0xFF, 0xFF));
            var accentForeground = (Brush)FindResource("SystemAccentColorPrimaryBrush");
            var primaryText = (Brush)FindResource("TextFillColorPrimaryBrush");

            foreach (var child in PresetItemsPanel.Children)
            {
                if (child is not Border cardBorder || cardBorder.Tag is not BgPresetItem presetItem)
                    continue;

                bool isSelected = presetItem.name == selectedName;

                // 更新边框
                cardBorder.BorderThickness = new Thickness(isSelected ? 2 : 1);
                cardBorder.BorderBrush = isSelected ? accentBrush : normalBorderBrush;

                // 更新内部文本样式
                if (cardBorder.Child is StackPanel stack)
                {
                    // 移除旧的 "✓ 已选中" 标签（如果有）
                    var existingCheck = stack.Children.OfType<System.Windows.Controls.TextBlock>()
                        .FirstOrDefault(t => t.Text == "✓ 已选中");
                    if (existingCheck != null)
                        stack.Children.Remove(existingCheck);

                    // 更新名称文本的粗体
                    foreach (var stackChild in stack.Children)
                    {
                        if (stackChild is System.Windows.Controls.TextBlock tb)
                        {
                            // 名称行（非类型标签，非"✓ 已选中"）
                            if (tb.Text == presetItem.name)
                            {
                                tb.FontWeight = isSelected ? FontWeights.Bold : FontWeights.Normal;
                            }
                        }
                    }

                    // 添加 "✓ 已选中" 标签
                    if (isSelected)
                    {
                        var checkMark = new System.Windows.Controls.TextBlock
                        {
                            Text = "✓ 已选中",
                            FontSize = 11,
                            Foreground = accentForeground,
                            HorizontalAlignment = HorizontalAlignment.Center,
                            Margin = new Thickness(0, 2, 0, 0)
                        };
                        stack.Children.Add(checkMark);
                    }
                }
            }
        }

        /// <summary>
        /// 自动推送背景透明度滑动条值变化事件处理
        /// </summary>
        private void OnAutoPushTransparencyChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            try
            {
                UpdateAutoPushTransparencyDisplay(e.NewValue);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] AutoPush transparency change failed", ex);
            }
        }

        /// <summary>
        /// 更新自动推送不透明度显示文本
        /// </summary>
        private void UpdateAutoPushTransparencyDisplay(double value)
        {
            if (AutoPushTransparencyValue != null)
            {
                int percentage = (int)(value * 100);
                AutoPushTransparencyValue.Text = $"{percentage}%";
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
        /// 点击"重启应用"按钮 — 显示内嵌确认提示（不保存配置）
        /// </summary>
        private void OnRestartAppClick(object sender, RoutedEventArgs e)
        {
            try
            {
                // 显示内嵌确认提示（非弹窗）
                if (RestartConfirmBar != null)
                    RestartConfirmBar.IsOpen = true;
                if (RestartConfirmButtons != null)
                    RestartConfirmButtons.Visibility = Visibility.Visible;
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Show restart confirmation failed", ex);
            }
        }

        /// <summary>
        /// 确认重启按钮点击事件
        /// </summary>
        private void OnConfirmRestartClick(object sender, RoutedEventArgs e)
        {
            try
            {
                if (RestartConfirmBar != null)
                    RestartConfirmBar.IsOpen = false;
                if (RestartConfirmButtons != null)
                    RestartConfirmButtons.Visibility = Visibility.Collapsed;

                Logger.Info("[SettingsPage] User confirmed restart, restarting application");
                RestartApplication();
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] Confirmed restart failed", ex);
                System.Windows.MessageBox.Show($"重启应用失败：{ex.Message}", "错误", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// 取消重启按钮点击事件
        /// </summary>
        private void OnCancelRestartClick(object sender, RoutedEventArgs e)
        {
            if (RestartConfirmBar != null)
                RestartConfirmBar.IsOpen = false;
            if (RestartConfirmButtons != null)
                RestartConfirmButtons.Visibility = Visibility.Collapsed;
            
            Logger.Info("[SettingsPage] User cancelled restart");
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
