using System;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Notion_Files_Management.Models;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Views
{
    public partial class ToolsPage : Page
    {
        public ObservableCollection<PageInfoItem> PageInfoItems { get; } = new();

        private readonly NotionBackendService _svc = NotionBackendService.Instance;

        private CancellationTokenSource? _cts;
        private int _reqId;

        // Avoid recursive TextChanged when we programmatically set Text.
        private bool _isFormattingPageId;

        public ToolsPage()
        {
            InitializeComponent();
            DataContext = this;

            try { PageInfoListView.ItemsSource = PageInfoItems; } catch { }

            // Warm up backend (no UI blocking)
            UiHelpers.WarmUpBackend();
        }

        // ===== Modal controls =====
        private void OpenPageInfoModal_Click(object sender, RoutedEventArgs e) => OpenStep1();

        private void OpenStep1()
        {
            ModalOverlay.Visibility = Visibility.Visible;
            ModalStep1.Visibility = Visibility.Visible;
            ModalStep2.Visibility = Visibility.Collapsed;
            PageIdInput.Text = "";
            BtnStartQuery.IsEnabled = true;

            try { PageIdErrorText.Text = ""; } catch { }
        }

        private void PageIdInput_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox textBox)
            {
                PageIdInputHelper.HandleTextChanged(textBox, PageIdErrorText, ref _isFormattingPageId);
            }
        }

        private void OpenStep2()
        {
            ModalOverlay.Visibility = Visibility.Visible;
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Visible;

            ProbeProgressBar.Value = 0;
            ProbeStatusText.Text = "准备开始…";
            PageInfoItems.Clear();
            StatFileCount.Text = "0";
            StatTotalGb.Text = "0";
        }

        private void CloseModal_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            ModalOverlay.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;
        }

        private void BackToStep1_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            ModalStep2.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Visible;
        }

        // ===== Core =====
        private async void StartQuery_Click(object sender, RoutedEventArgs e)
        {
            string rawInput = PageIdInput.Text ?? "";
            if (!NotionPageId.TryNormalize(rawInput, out string pageId, out string pageIdErr))
            {
                try { PageIdErrorText.Text = pageIdErr; } catch { }
                MessageBox.Show(pageIdErr);
                return;
            }

            // Keep UI canonical.
            if (!string.Equals(PageIdInput.Text, pageId, StringComparison.Ordinal))
                PageIdInput.Text = pageId;

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            _cts?.Cancel();
            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            int reqId = ++_reqId;

            BtnStartQuery.IsEnabled = false;
            OpenStep2();

            int notFoundCount = 0;
            var progress = new Progress<NotionBackendService.ProbeProgress>(p =>
            {
                if (token.IsCancellationRequested || reqId != _reqId)
                    return;

                ProbeProgressBar.Value = p.Percent;

                ProbeStatusText.Text = string.Equals(p.Status, "not_found", StringComparison.OrdinalIgnoreCase)
                    ? $"准备探测任务…（{++notFoundCount}）"
                    : $"探测中 {p.Percent:0}%（{p.Done}/{Math.Max(1, p.Total)}）";
            });

            try
            {
                Logger.Info($"ToolsPage start page info. pageId={pageId}");
                var ret = await _svc.FetchDownloadListWithProbeAsync(pageId, progress, token);

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId)
                    return;

                if (ret.ProbeId <= 0 || ret.Items.Count == 0)
                {
                    MessageBox.Show(string.IsNullOrWhiteSpace(ret.Msg) ? "获取列表失败或页面无文件。" : ret.Msg);
                    BackToStep1_Click(null!, null!);
                    return;
                }

                // Render list
                PageInfoItems.Clear();
                foreach (var it in ret.Items.OrderByDescending(x => x.size_mb))
                {
                    string realName = string.IsNullOrWhiteSpace(it.real_name) ? "(未命名文件)" : it.real_name!;
                    PageInfoItems.Add(new PageInfoItem
                    {
                        RealName = realName,
                        Url = it.url ?? "",
                        SizeGb = (it.size_mb <= 0 ? 0.0 : it.size_mb / 1024.0)
                    });
                }

                StatFileCount.Text = PageInfoItems.Count.ToString();
                StatTotalGb.Text = Math.Round(PageInfoItems.Sum(x => x.SizeGb), 3).ToString("0.###");
                ProbeProgressBar.Value = 100;
                ProbeStatusText.Text = "探测完成。";
            }
            catch (OperationCanceledException)
            {
                ProbeStatusText.Text = "已取消。";
            }
            catch (Exception ex)
            {
                MessageBox.Show("获取页面信息失败：" + ex.Message);
                Logger.Error("ToolsPage StartQuery failed", ex);
                BackToStep1_Click(null!, null!);
            }
            finally
            {
                BtnStartQuery.IsEnabled = true;
            }
        }

        private void OpenLogFolder_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                string? logDir = Logger.LogDirectory;
                
                if (string.IsNullOrEmpty(logDir))
                {
                    // 如果日志目录未初始化，尝试获取默认位置
                    logDir = System.IO.Path.Combine(AppContext.BaseDirectory, "logs");
                }

                if (!System.IO.Directory.Exists(logDir))
                {
                    System.IO.Directory.CreateDirectory(logDir);
                }

                // 使用 explorer 打开文件夹
                Process.Start(new ProcessStartInfo
                {
                    FileName = logDir,
                    UseShellExecute = true,
                    Verb = "open"
                });

                Logger.Info($"User opened log folder: {logDir}");
            }
            catch (Exception ex)
            {
                MessageBox.Show($"无法打开日志文件夹：{ex.Message}", "错误", MessageBoxButton.OK, MessageBoxImage.Error);
                Logger.Error("OpenLogFolder failed", ex);
            }
        }

        private void ReportError_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                const string issuesUrl = "https://github.com/RuibinNingh/Notion-Files-Management/issues";
                Process.Start(new ProcessStartInfo(issuesUrl) { UseShellExecute = true });
                Logger.Info($"User opened GitHub Issues page: {issuesUrl}");
            }
            catch (Exception ex)
            {
                MessageBox.Show($"无法打开浏览器：{ex.Message}", "错误", MessageBoxButton.OK, MessageBoxImage.Error);
                Logger.Error("ReportError failed", ex);
            }
        }
    }
}
