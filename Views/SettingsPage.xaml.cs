using System;
using System.Diagnostics;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
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
            }

            // 显示当前版本号
            TxtCurrentVersion.Text = $"当前版本：{AppVersion.FullVersionString}";
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
                Logger.Warning($"[SettingsPage] HTTPS request failed, trying HTTP: {ex.Message}");
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
                            HorizontalAlignment = HorizontalAlignment.Stretch
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
