using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Navigation;
using Notion_Files_Management.Models;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Views
{
    /// <summary>
    /// 公告中心页面 — 卡片流式布局，内联渲染 Markdown 正文
    /// </summary>
    public partial class NoticePage : Page
    {
        /// <summary>
        /// 当前排序后的公告列表（用于标记已读）
        /// </summary>
        private List<NoticeItem>? _currentNotices;

        public NoticePage()
        {
            InitializeComponent();
            Loaded += OnPageLoaded;

            AddHandler(Hyperlink.RequestNavigateEvent,
                new RequestNavigateEventHandler(OnHyperlinkRequestNavigate));
        }

        // ═══════════════════ Markdown 链接点击处理（RequestNavigate） ═══════════════════

        private void OnHyperlinkRequestNavigate(object sender, RequestNavigateEventArgs e)
        {
            try
            {
                if (e.Uri != null && !string.IsNullOrEmpty(e.Uri.AbsoluteUri))
                {
                    TryOpenUrl(e.Uri.AbsoluteUri);
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticePage] Failed to open link: {ex.Message}");
            }

            e.Handled = true;
        }

        // ═══════════════════ 页面生命周期 ═══════════════════

        private async void OnPageLoaded(object sender, RoutedEventArgs e)
        {
            await LoadNoticesAsync();
        }

        // ═══════════════════ 核心加载逻辑 ═══════════════════

        private async System.Threading.Tasks.Task LoadNoticesAsync()
        {
            LoadingPanel.Visibility = Visibility.Visible;
            EmptyPanel.Visibility = Visibility.Collapsed;
            NoticeList.Visibility = Visibility.Collapsed;
            BtnRefresh.IsEnabled = false;

            try
            {
                var index = await NoticeService.FetchIndexAsync();

                if (index == null || index.Notices.Count == 0)
                {
                    ShowEmptyState(index == null
                        ? "无法加载公告，请检查网络连接"
                        : "暂无公告");
                    return;
                }

                var sorted = index.Notices
                    .OrderByDescending(n => n.Pinned)
                    .ThenByDescending(n => n.Date)
                    .ThenByDescending(n => n.Id)
                    .ToList();

                _currentNotices = sorted;

                NoticeList.ItemsSource = sorted;
                LoadingPanel.Visibility = Visibility.Collapsed;
                NoticeList.Visibility = Visibility.Visible;

                await NoticeService.PreloadAllContentAsync(sorted);
                NoticeService.MarkAllAsRead(sorted);

                Logger.Info($"[NoticePage] Loaded {sorted.Count} notices");
            }
            catch (Exception ex)
            {
                Logger.Error("[NoticePage] LoadNoticesAsync failed", ex);
                ShowEmptyState("加载公告时出错，请稍后重试");
            }
            finally
            {
                BtnRefresh.IsEnabled = true;
            }
        }

        // ═══════════════════ 工具方法 ═══════════════════

        private void TryOpenUrl(string url)
        {
            try
            {
                Logger.Info($"[NoticePage] Opening URL: {url}");
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticePage] Failed to open URL: {ex.Message}");
            }
        }

        // ═══════════════════ 空/错误状态 ═══════════════════

        private void ShowEmptyState(string message)
        {
            LoadingPanel.Visibility = Visibility.Collapsed;
            NoticeList.Visibility = Visibility.Collapsed;
            EmptyPanel.Visibility = Visibility.Visible;
            TxtEmptyMessage.Text = message;
        }

        // ═══════════════════ 按钮事件 ═══════════════════

        private async void OnRefreshClick(object sender, RoutedEventArgs e)
        {
            await LoadNoticesAsync();
        }
    }
}
