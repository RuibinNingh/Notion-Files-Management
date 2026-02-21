using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Notion_Files_Management.Services;

namespace Notion_Files_Management.Views
{
    public partial class DashboardPage : Page
    {
        private const string WebsiteUrl = "https://nfm.ruibin-ningh.top";
        private const string GitHubUrl  = "https://github.com/RuibinNingh/Notion-Files-Management";
        private const string SponsorUrl = "https://nfm.ruibin-ningh.top/sponsor";

        /// <summary>
        /// 轮询定时器：等待静默版本检查结果（最多 ~15 秒）
        /// </summary>
        private DispatcherTimer? _versionPollTimer;
        private int _pollCount;
        private const int MaxPollAttempts = 15;

        /// <summary>
        /// 避免在同一次应用生命周期中重复弹出（用户关闭后不再显示）
        /// </summary>
        private static bool _bannerDismissed;

        /// <summary>
        /// 公告未读横幅是否已关闭
        /// </summary>
        private static bool _noticeBannerDismissed;

        public DashboardPage()
        {
            InitializeComponent();

            // 从 AppVersion 类读取版本号并展示（统一版本号来源）
            TxtVersion.Text = AppVersion.FullVersionString;

            Loaded += OnPageLoaded;
            Unloaded += OnPageUnloaded;
        }

        // ═══════════════════ 页面生命周期 ═══════════════════

        private void OnPageLoaded(object sender, RoutedEventArgs e)
        {
            // 尝试立即检查缓存
            if (TryShowUpdateBanner())
                return;

            // 缓存尚未就绪 — 启动轮询定时器（每秒检查一次）
            if (_bannerDismissed) return;

            _pollCount = 0;
            _versionPollTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            _versionPollTimer.Tick += OnVersionPollTick;
            _versionPollTimer.Start();

            // 异步检查公告未读数
            CheckNoticeUnread();
        }

        private void OnPageUnloaded(object sender, RoutedEventArgs e)
        {
            StopPollTimer();
        }

        private void OnVersionPollTick(object? sender, EventArgs e)
        {
            _pollCount++;
            if (TryShowUpdateBanner() || _pollCount >= MaxPollAttempts)
            {
                StopPollTimer();
            }
        }

        private void StopPollTimer()
        {
            if (_versionPollTimer != null)
            {
                _versionPollTimer.Stop();
                _versionPollTimer.Tick -= OnVersionPollTick;
                _versionPollTimer = null;
            }
        }

        // ═══════════════════ 版本检测与横幅 ═══════════════════

        /// <summary>
        /// 尝试检查缓存版本信息并显示横幅。
        /// 返回 true 表示已处理（无论是否显示横幅）。
        /// </summary>
        private bool TryShowUpdateBanner()
        {
            if (_bannerDismissed) return true;

            var cached = SettingsPage.CachedVersionInfo;
            if (cached == null) return false; // 还没拿到

            string remoteVersion = cached.version ?? "";
            string localVersion = AppVersion.Current;

            if (string.IsNullOrEmpty(remoteVersion))
                return true; // 拿到了但内容为空，不处理

            int cmp = CompareVersionStrings(remoteVersion, localVersion);
            if (cmp > 0)
            {
                // 有新版本 → 显示横幅
                BannerTitle.Text = $"发现新版本 {remoteVersion}";
                BannerSubtitle.Text = $"当前版本 {localVersion}，建议更新以获取最新功能与修复";
                ShowBannerWithAnimation();
            }

            return true;
        }

        /// <summary>
        /// 渐入 + 下滑动画显示横幅
        /// </summary>
        private void ShowBannerWithAnimation()
        {
            UpdateBanner.Visibility = Visibility.Visible;
            UpdateBanner.IsHitTestVisible = true;

            // 时长 & 缓动
            var duration = new Duration(TimeSpan.FromMilliseconds(520));
            var easing = new CubicEase { EasingMode = EasingMode.EaseOut };

            // 透明度：0 → 1
            var fadeIn = new DoubleAnimation(0, 1, duration) { EasingFunction = easing };

            // 平移：-18 → 0（从上方滑入）
            var slideDown = new DoubleAnimation(-18, 0, duration) { EasingFunction = easing };

            UpdateBanner.BeginAnimation(OpacityProperty, fadeIn);
            BannerTranslate.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty, slideDown);
        }

        // ═══════════════════ 公告未读提醒 ═══════════════════

        /// <summary>
        /// 异步检查公告未读数，有未读则显示提醒横幅
        /// </summary>
        private async void CheckNoticeUnread()
        {
            if (_noticeBannerDismissed) return;

            try
            {
                // 尝试获取公告索引（可能已被 App 启动时预加载到缓存）
                var index = NoticeService.CachedIndex ?? await NoticeService.FetchIndexAsync();
                if (index == null) return;

                int unread = NoticeService.GetUnreadCount(index);
                if (unread > 0)
                {
                    Dispatcher.Invoke(() =>
                    {
                        NoticeBannerText.Text = $"您有 {unread} 条未读公告";
                        ShowNoticeBannerWithAnimation();
                    });
                }
            }
            catch (Exception ex)
            {
                Utils.Logger.Warn($"[DashboardPage] CheckNoticeUnread failed: {ex.Message}");
            }
        }

        /// <summary>
        /// 渐入 + 下滑动画显示公告横幅
        /// </summary>
        private void ShowNoticeBannerWithAnimation()
        {
            NoticeBanner.Visibility = Visibility.Visible;
            NoticeBanner.IsHitTestVisible = true;

            var duration = new Duration(TimeSpan.FromMilliseconds(520));
            var easing = new CubicEase { EasingMode = EasingMode.EaseOut };

            var fadeIn = new DoubleAnimation(0, 1, duration) { EasingFunction = easing };
            var slideDown = new DoubleAnimation(-18, 0, duration) { EasingFunction = easing };

            NoticeBanner.BeginAnimation(OpacityProperty, fadeIn);
            NoticeBannerTranslate.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty, slideDown);
        }

        /// <summary>
        /// 点击"查看公告"按钮 — 导航到公告页面
        /// </summary>
        private void OnGoNoticeClick(object sender, RoutedEventArgs e)
        {
            try
            {
                _noticeBannerDismissed = true;

                if (System.Windows.Application.Current.MainWindow is MainWindow mw)
                {
                    mw.RootNavigation.Navigate(typeof(NoticePage));
                }
            }
            catch (Exception ex)
            {
                Utils.Logger.Error("[DashboardPage] Failed to navigate to NoticePage", ex);
            }
        }

        // ═══════════════════ 版本比较（复用 SettingsPage 的逻辑） ═══════════════════

        private static int CompareVersionStrings(string a, string b)
        {
            if (string.IsNullOrEmpty(a) && string.IsNullOrEmpty(b)) return 0;
            if (string.IsNullOrEmpty(a)) return -1;
            if (string.IsNullOrEmpty(b)) return 1;

            SplitVersion(a, out string aNumeric, out string aStatus);
            SplitVersion(b, out string bNumeric, out string bStatus);

            var aParts = aNumeric.Split('.');
            var bParts = bNumeric.Split('.');
            int maxLen = Math.Max(aParts.Length, bParts.Length);

            for (int i = 0; i < maxLen; i++)
            {
                int aVal = i < aParts.Length && int.TryParse(aParts[i], out int av) ? av : 0;
                int bVal = i < bParts.Length && int.TryParse(bParts[i], out int bv) ? bv : 0;
                if (aVal != bVal) return aVal.CompareTo(bVal);
            }

            int aRank = GetStatusRank(aStatus);
            int bRank = GetStatusRank(bStatus);
            return aRank.CompareTo(bRank);
        }

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

        private static int GetStatusRank(string status)
        {
            if (string.IsNullOrEmpty(status)) return 0;
            if (status.Equals("Beta", StringComparison.OrdinalIgnoreCase)) return 1;
            if (status.Equals("Status", StringComparison.OrdinalIgnoreCase)) return 2;
            return 0;
        }

        // ═══════════════════ 按钮事件 ═══════════════════

        /// <summary>
        /// 点击"转到设置更新"按钮 — 导航到设置页面
        /// </summary>
        private void OnGoSettingsClick(object sender, RoutedEventArgs e)
        {
            try
            {
                _bannerDismissed = true; // 用户已操作，不再重复弹出

                if (System.Windows.Application.Current.MainWindow is MainWindow mw)
                {
                    mw.RootNavigation.Navigate(typeof(SettingsPage));
                }
            }
            catch (Exception ex)
            {
                Utils.Logger.Error("[DashboardPage] Failed to navigate to SettingsPage", ex);
            }
        }

        private void OnWebsiteClick(object sender, RoutedEventArgs e)
            => OpenUrl(WebsiteUrl);

        private void OnGitHubClick(object sender, RoutedEventArgs e)
            => OpenUrl(GitHubUrl);

        private void OnSponsorClick(object sender, RoutedEventArgs e)
            => OpenUrl(SponsorUrl);

        private static void OpenUrl(string url)
        {
            try
            {
                System.Diagnostics.Process.Start(
                    new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch { /* 静默失败，不弹窗 */ }
        }
    }
}
