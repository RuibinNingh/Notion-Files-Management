using System;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Threading.Tasks;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;
using Wpf.Ui.Controls;

namespace Notion_Files_Management.Views
{
    public partial class SettingsPage : Page
    {
        // ── 版本检查：服务器返回的数据模型 ──────────────────────────────
        private sealed class VersionInfo
        {
            public string version     { get; set; } = "";
            public string build_date  { get; set; } = "";
            public string download_url { get; set; } = "";
            public string github      { get; set; } = "";
            public string[] changelog { get; set; } = Array.Empty<string>();
        }

        /// <summary>
        /// 版本状态枚举（权重越高越稳定）
        /// </summary>
        private enum VersionState { Unknown = 0, Beta = 1, Stable = 2 }

        // 存储本次查询到的版本信息，供下载按钮使用
        private VersionInfo? _latestVersionInfo;

        // 检查地址：优先 HTTPS，降级 HTTP（兼容服务端未来协议升级）
        private const string VersionEndpointHttps = "https://nfm.ruibin-ningh.top/version.json";
        private const string VersionEndpointHttp  = "http://nfm.ruibin-ningh.top/version.json";

        // 共享 HttpClient（避免 socket 耗尽）
        private static readonly HttpClient _httpClient = new(new HttpClientHandler
        {
            AllowAutoRedirect = true,
            MaxAutomaticRedirections = 5
        })
        {
            Timeout = TimeSpan.FromSeconds(15)
        };

        public SettingsPage()
        {
            InitializeComponent();

            // 从 config.json 读取当前版本号并展示
            ConfigManager.Load();
            var currentVer = ConfigManager.Current?.AppVersion ?? "1.0.0-Beta";
            TxtCurrentVersion.Text = $"当前版本：v{currentVer}";

            if (ConfigManager.Current != null)
            {
                TokenInput.Password = ConfigManager.Current.NotionToken;
                NotionUrlInput.Text = ConfigManager.Current.NotionBaseUrl ?? "https://api.notion.com/v1";
                SelectComboByInt(DownloadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxDownloadWorkers));
                SelectComboByInt(UploadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxUploadWorkers));
            }
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

        // ── 版本检查 ──────────────────────────────────────────────────────

        /// <summary>
        /// 「检查版本更新」按钮点击
        /// </summary>
        private async void OnCheckUpdateClick(object sender, RoutedEventArgs e)
        {
            BtnCheckUpdate.IsEnabled = false;
            BtnCheckUpdate.Content   = "检查中…";

            VersionInfoPanel.Visibility    = Visibility.Visible;
            VersionDetailGrid.Visibility   = Visibility.Collapsed;
            DownloadButtonPanel.Visibility = Visibility.Collapsed;
            UpdateInfoBar.IsOpen           = false;

            try
            {
                var info = await FetchVersionInfoAsync();
                _latestVersionInfo = info;
                RenderVersionInfo(info);
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] 版本检查失败", ex);
                ShowInfoBar(InfoBarSeverity.Error, "无法连接到更新服务器，请检查网络连接后重试。");
            }
            finally
            {
                BtnCheckUpdate.IsEnabled = true;
                BtnCheckUpdate.Content   = "检查版本更新";
            }
        }

        /// <summary>
        /// 先尝试 HTTPS，失败则降级 HTTP（兼容服务端未来协议升级）
        /// </summary>
        private static async Task<VersionInfo> FetchVersionInfoAsync()
        {
            try
            {
                var json = await _httpClient.GetStringAsync(VersionEndpointHttps);
                return JsonSerializer.Deserialize<VersionInfo>(json)
                    ?? throw new InvalidOperationException("服务器返回空响应");
            }
            catch (Exception httpsEx)
            {
                Logger.Warn($"[SettingsPage] HTTPS 请求失败，降级到 HTTP: {httpsEx.Message}");
            }

            var httpJson = await _httpClient.GetStringAsync(VersionEndpointHttp);
            return JsonSerializer.Deserialize<VersionInfo>(httpJson)
                ?? throw new InvalidOperationException("服务器返回空响应");
        }

        /// <summary>
        /// 渲染版本信息到 UI，并进行版本比较
        /// </summary>
        private void RenderVersionInfo(VersionInfo info)
        {
            TxtLatestVersion.Text = info.version;
            TxtBuildDate.Text     = string.IsNullOrWhiteSpace(info.build_date) ? "—" : info.build_date;

            // 动态生成 Changelog 列表
            ChangelogPanel.Children.Clear();
            if (info.changelog is { Length: > 0 })
            {
                foreach (var item in info.changelog)
                {
                    var row = new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        Margin      = new Thickness(0, 0, 0, 4)
                    };
                    row.Children.Add(new Wpf.Ui.Controls.SymbolIcon
                    {
                        Symbol   = Wpf.Ui.Controls.SymbolRegular.CheckmarkCircle16,
                        FontSize = 14,
                        Margin   = new Thickness(0, 1, 6, 0),
                        Foreground = (System.Windows.Media.Brush)Application.Current.Resources["SystemAccentColorBrush"]
                    });
                    row.Children.Add(new System.Windows.Controls.TextBlock
                    {
                        Text            = item,
                        FontSize        = 12,
                        TextWrapping    = TextWrapping.Wrap,
                        VerticalAlignment = VerticalAlignment.Center
                    });
                    ChangelogPanel.Children.Add(row);
                }
            }
            else
            {
                ChangelogPanel.Children.Add(new System.Windows.Controls.TextBlock
                {
                    Text = "暂无更新说明", FontSize = 12, Opacity = 0.6
                });
            }

            // ── 智能版本比较（支持 Stable / Beta 状态） ──────────────────
            var currentVerStr = ConfigManager.Current?.AppVersion ?? "1.0.0-Beta";
            var compareResult = CompareVersionStrings(currentVerStr, info.version);

            switch (compareResult)
            {
                case VersionCompareResult.LatestIsNewer:
                    ShowInfoBar(InfoBarSeverity.Warning,
                        $"发现新版本 {info.version}，建议更新！");
                    break;

                case VersionCompareResult.SameVersionStableUpgrade:
                    ShowInfoBar(InfoBarSeverity.Informational,
                        $"相同版本号，但官方已发布正式版 {info.version}，建议升级。");
                    break;

                case VersionCompareResult.UpToDate:
                default:
                    ShowInfoBar(InfoBarSeverity.Success, "当前已是最新版本。");
                    break;
            }

            VersionDetailGrid.Visibility   = Visibility.Visible;
            DownloadButtonPanel.Visibility = Visibility.Visible;
        }

        // ── 版本比较逻辑 ────────────────────────────────────────────────

        private enum VersionCompareResult
        {
            UpToDate,               // 已是最新或本地更新
            LatestIsNewer,          // 服务端版本号更大，有新版本
            SameVersionStableUpgrade // 版本号相同，但服务端已是 Stable（本地是 Beta）
        }

        /// <summary>
        /// 比较两个版本字符串，格式：{major}.{minor}.{patch}-{State}
        /// State 权重：Beta(1) &lt; Stable(2)
        /// </summary>
        private static VersionCompareResult CompareVersionStrings(string current, string latest)
        {
            ParseVersion(current, out var curNums, out var curState);
            ParseVersion(latest,  out var latNums, out var latState);

            // 1) 比较纯版本号元组
            int numCmp = CompareNumericParts(curNums, latNums);
            if (numCmp < 0)
                return VersionCompareResult.LatestIsNewer;          // 服务端版本更新
            if (numCmp > 0)
                return VersionCompareResult.UpToDate;               // 本地更新（预览/内测）

            // 2) 版本号相同：比较状态
            if (curState < latState)
            {
                // 本地是 Beta，服务端是 Stable（同版本升正式）
                if (curState == VersionState.Beta && latState == VersionState.Stable)
                    return VersionCompareResult.SameVersionStableUpgrade;
                return VersionCompareResult.LatestIsNewer;
            }
            return VersionCompareResult.UpToDate;
        }

        /// <summary>
        /// 解析 "1.2.3-Beta" → (int[]{1,2,3}, VersionState.Beta)
        /// </summary>
        private static void ParseVersion(string raw, out int[] nums, out VersionState state)
        {
            nums  = new[] { 0, 0, 0 };
            state = VersionState.Unknown;

            if (string.IsNullOrWhiteSpace(raw)) return;

            var parts   = raw.Trim().Split('-');
            var numStr  = parts[0];
            var statStr = parts.Length > 1 ? parts[1].Trim() : "";

            // 解析版本号数字
            var segments = numStr.Split('.');
            for (int i = 0; i < Math.Min(segments.Length, 3); i++)
                if (int.TryParse(segments[i], out int v))
                    nums[i] = v;

            // 解析状态
            state = statStr.ToLowerInvariant() switch
            {
                "stable" => VersionState.Stable,
                "beta"   => VersionState.Beta,
                _        => VersionState.Unknown
            };
        }

        /// <summary>按优先级比较 int[] 版本号（major > minor > patch）</summary>
        private static int CompareNumericParts(int[] a, int[] b)
        {
            for (int i = 0; i < 3; i++)
            {
                if (a[i] != b[i]) return a[i].CompareTo(b[i]);
            }
            return 0;
        }

        // ── 下载按钮事件 ────────────────────────────────────────────────

        private void ShowInfoBar(InfoBarSeverity severity, string message)
        {
            UpdateInfoBar.Severity = severity;
            UpdateInfoBar.Message  = message;
            UpdateInfoBar.IsOpen   = true;
        }

        private void OnOpenGithubClick(object sender, RoutedEventArgs e)
        {
            if (_latestVersionInfo == null) return;
            var repo = _latestVersionInfo.github?.Trim();
            if (string.IsNullOrEmpty(repo)) return;
            OpenUrl($"https://github.com/{repo}");
        }

        private void OnGetDownloadUrlClick(object sender, RoutedEventArgs e)
        {
            if (_latestVersionInfo == null) return;
            var url = _latestVersionInfo.download_url?.Trim();
            if (string.IsNullOrEmpty(url)) return;
            OpenUrl(url);
        }

        private static void OpenUrl(string url)
        {
            try
            {
                System.Diagnostics.Process.Start(
                    new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Logger.Error("[SettingsPage] 无法打开浏览器", ex);
            }
        }

        // ── 辅助方法 ─────────────────────────────────────────────────────

        private static int ClampWorkers(int v)
        {
            if (v < 1)  return 1;
            if (v > 16) return 16;
            return v;
        }

        private static int ReadComboInt(ComboBox combo, int fallback)
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

        private static void SelectComboByInt(ComboBox combo, int value)
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
    }
}
