using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
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

            // ── 链接点击处理（三层保障） ──

            // 主修复：PreviewMouseLeftButtonDown 隧道事件 —— 在 MdXaml 内部吞掉点击之前拦截，
            // 检测点击目标是否为 Hyperlink，是则直接打开 URL。
            // handledEventsToo: true 确保即使事件被标记为已处理也能触发。
            AddHandler(UIElement.PreviewMouseLeftButtonDownEvent,
                new MouseButtonEventHandler(OnPreviewMouseLeftButtonDown), true);

            // 兜底：捕获 RequestNavigateEvent（部分场景下 MdXaml 可能触发此事件）
            AddHandler(Hyperlink.RequestNavigateEvent,
                new RequestNavigateEventHandler(OnHyperlinkRequestNavigate));
        }

        // ═══════════════════ 链接点击处理 ═══════════════════

        /// <summary>
        /// 主修复：PreviewMouseLeftButtonDown — 沿逻辑树向上查找 Hyperlink，
        /// 在 MdXaml 内部处理之前拦截链接点击。
        /// 兼容两种模式：NavigateUri（标准）和 CommandParameter（MdXaml HyperlinkCommand 模式）。
        /// </summary>
        private void OnPreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.OriginalSource is not DependencyObject source) return;

            var hyperlink = FindAncestorHyperlink(source);
            if (hyperlink == null) return;

            // 优先使用 NavigateUri（标准模式）
            string? url = hyperlink.NavigateUri?.AbsoluteUri;

            // 如果 NavigateUri 为空，尝试 CommandParameter（MdXaml HyperlinkCommand 模式）
            if (string.IsNullOrEmpty(url) && hyperlink.CommandParameter is string cmdParam)
            {
                url = cmdParam;
            }
            // 再尝试 CommandParameter 的 Uri 类型
            if (string.IsNullOrEmpty(url) && hyperlink.CommandParameter is Uri cmdUri)
            {
                url = cmdUri.AbsoluteUri;
            }

            if (string.IsNullOrEmpty(url)) return;

            TryOpenUrl(url);
            e.Handled = true;
        }

        /// <summary>
        /// 兜底：RequestNavigateEvent handler
        /// </summary>
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
                Logger.Warn($"[NoticePage] RequestNavigate failed: {ex.Message}");
            }

            e.Handled = true;
        }

        /// <summary>
        /// 从点击目标沿 FrameworkContentElement.Parent 链向上查找 Hyperlink。
        /// Hyperlink 是 Inline（文本模型），不在 VisualTree 中，需走逻辑树。
        /// </summary>
        private static Hyperlink? FindAncestorHyperlink(DependencyObject obj)
        {
            var current = obj;
            while (current != null)
            {
                if (current is Hyperlink hl)
                    return hl;

                current = current switch
                {
                    FrameworkContentElement fce => fce.Parent,
                    FrameworkElement fe => fe.Parent ?? VisualTreeHelper.GetParent(fe),
                    _ => null
                };
            }
            return null;
        }

        // ═══════════════════ MdXaml HyperlinkCommand 反射注入 ═══════════════════

        /// <summary>
        /// 遍历视觉树，找到所有 MdXaml MarkdownScrollViewer 实例，
        /// 通过反射设置其 HyperlinkCommand 属性（如果存在）。
        /// 此为辅助手段，主修复为 PreviewMouseLeftButtonDown。
        /// </summary>
        private void TrySetHyperlinkCommandOnRenderedViewers()
        {
            try
            {
                var viewers = FindVisualChildren<FrameworkElement>(NoticeList)
                    .Where(fe => fe.GetType().Name == "MarkdownScrollViewer");

                foreach (var viewer in viewers)
                {
                    var prop = viewer.GetType().GetProperty("HyperlinkCommand",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (prop != null && prop.CanWrite)
                    {
                        prop.SetValue(viewer, OpenBrowserCommand.Instance);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticePage] TrySetHyperlinkCommand reflection failed (non-critical): {ex.Message}");
            }
        }

        /// <summary>
        /// 递归查找视觉树中所有指定类型的子元素
        /// </summary>
        private static IEnumerable<T> FindVisualChildren<T>(DependencyObject parent) where T : DependencyObject
        {
            if (parent == null) yield break;

            int count = VisualTreeHelper.GetChildrenCount(parent);
            for (int i = 0; i < count; i++)
            {
                var child = VisualTreeHelper.GetChild(parent, i);
                if (child is T t) yield return t;
                foreach (var grandChild in FindVisualChildren<T>(child))
                    yield return grandChild;
            }
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

                // 内容加载完成后，尝试通过反射为 MarkdownScrollViewer 设置 HyperlinkCommand
                // 延迟一帧确保 DataTemplate 已渲染
                Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Loaded,
                    new Action(TrySetHyperlinkCommandOnRenderedViewers));

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
                // 安全校验：仅允许 http/https 协议
                if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
                    || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
                {
                    Logger.Warn($"[NoticePage] Blocked non-HTTP URL: {url}");
                    return;
                }

                Logger.Info($"[NoticePage] Opening URL: {url}");
                Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
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
