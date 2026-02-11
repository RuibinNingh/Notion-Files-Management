using Python.Runtime;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;
using Notion_Files_Management.Views.Tools;

namespace Notion_Files_Management.Views
{
    public partial class ToolsPage : Page
    {
        private sealed record ProbeProgress(string Status, double Percent, int Done, int Total, string Error);

        public ObservableCollection<PageInfoItem> PageInfoItems { get; } = new();

        private readonly PythonBackendHost _backend = PythonBackendHost.Instance;

        private CancellationTokenSource? _cts;
        private int _reqId;

        public ToolsPage()
        {
            InitializeComponent();
            DataContext = this;

            try { PageInfoListView.ItemsSource = PageInfoItems; } catch { }

            // Warm up backend (no UI blocking)
            _ = Task.Run(async () =>
            {
                try { await EnsureBackendAsync(); } catch { }
            });
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
            if (!await EnsureBackendAsync())
            {
                MessageBox.Show("未检测到 Notion Token，请先到【设置】页保存。");
                return;
            }

            string pageId = (PageIdInput.Text ?? "").Trim().Replace(" ", "");
            if (string.IsNullOrWhiteSpace(pageId))
            {
                MessageBox.Show("请输入目标页面 ID。");
                return;
            }

            _cts?.Cancel();
            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            int reqId = ++_reqId;

            BtnStartQuery.IsEnabled = false;
            OpenStep2();

            try
            {
                // 1) Trigger probe via get_download_list
                var (probeId, total, msg, status) = await _backend.RunPython(py =>
                {
                    dynamic pyMain = py;
                    dynamic ret = pyMain.get_download_list(pageId);
                    return (
                        PyConvert.ToInt(ret["probe_id"], 0),
                        PyConvert.ToInt(ret["total"], 0),
                        ret["msg"]?.ToString() ?? "",
                        ret["status"]?.ToString() ?? ""
                    );
                }, token);

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                if (probeId <= 0)
                {
                    MessageBox.Show(string.IsNullOrWhiteSpace(msg) ? "获取列表失败或页面无文件。" : msg);
                    BackToStep1_Click(null!, null!);
                    return;
                }

                // 2) Poll probe progress
                int notFoundCount = 0;
                while (true)
                {
                    token.ThrowIfCancellationRequested();
                    if (reqId != _reqId) return;

                    var p = await GetProbeProgressAsync(probeId, token);

                    await Application.Current.Dispatcher.InvokeAsync(() =>
                    {
                        ProbeProgressBar.Value = p.Percent;
                        ProbeStatusText.Text = string.Equals(p.Status, "not_found", StringComparison.OrdinalIgnoreCase)
                            ? $"准备探测任务…（{++notFoundCount}）"
                            : $"探测中 {p.Percent:0}%（{p.Done}/{Math.Max(1, p.Total)}）";
                    });

                    if (string.Equals(p.Status, "done", StringComparison.OrdinalIgnoreCase))
                        break;

                    if (string.Equals(p.Status, "error", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(p.Status, "failed", StringComparison.OrdinalIgnoreCase))
                        throw new Exception(string.IsNullOrWhiteSpace(p.Error) ? "探测失败" : p.Error);

                    await Task.Delay(350, token);
                }

                // 3) Read final list from main.download_list
                var items = await _backend.RunPython(py =>
                {
                    dynamic pyMain = py;
                    var list = new List<PageInfoItem>();
                    foreach (var it in pyMain.download_list)
                    {
                        string realName = it["real_name"]?.ToString() ?? "(未命名文件)";
                        string url = it["url"]?.ToString() ?? "";
                        double sizeMb = PyConvert.ToDouble(it["size_mb"], 0.0);
                        if (string.IsNullOrWhiteSpace(realName)) realName = "(未命名文件)";
                        list.Add(new PageInfoItem { RealName = realName, Url = url, SizeGb = sizeMb / 1024.0 });
                    }
                    return list;
                }, token);

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                // 4) Render
                await Application.Current.Dispatcher.InvokeAsync(() =>
                {
                    PageInfoItems.Clear();
                    foreach (var x in items.OrderByDescending(x => x.SizeGb))
                        PageInfoItems.Add(x);

                    StatFileCount.Text = PageInfoItems.Count.ToString();
                    StatTotalGb.Text = Math.Round(PageInfoItems.Sum(x => x.SizeGb), 3).ToString("0.###");
                    ProbeProgressBar.Value = 100;
                    ProbeStatusText.Text = "探测完成。";
                });
            }
            catch (OperationCanceledException)
            {
                await Application.Current.Dispatcher.InvokeAsync(() => ProbeStatusText.Text = "已取消。");
            }
            catch (Exception ex)
            {
                MessageBox.Show("获取页面信息失败：" + ex.Message);
                Logger.Error("ToolsPage StartQuery failed", ex);
                BackToStep1_Click(null!, null!);
            }
            finally
            {
                await Application.Current.Dispatcher.InvokeAsync(() => BtnStartQuery.IsEnabled = true);
            }
        }

        private async Task<bool> EnsureBackendAsync()
        {
            try
            {
                ConfigManager.Load();
                string tk = ConfigManager.Current?.NotionToken?.Trim() ?? "";
                if (string.IsNullOrEmpty(tk)) return false;

                string url = ConfigManager.Current?.NotionBaseUrl ?? "https://api.notion.com/v1";
                int dl = ConfigManager.Current?.MaxDownloadWorkers ?? 3;
                int ul = ConfigManager.Current?.MaxUploadWorkers ?? 3;

                await _backend.EnsureBackendReady(tk, dl, ul, url);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private Task<ProbeProgress> GetProbeProgressAsync(int probeId, CancellationToken token)
        {
            return _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                dynamic prog = pyMain.download_list_processing(probeId);
                string st = prog["status"]?.ToString() ?? "";
                double pct = PyConvert.ToDouble(prog["percent"], 0.0);
                int dn = PyConvert.ToInt(prog["done"], 0);
                int tt = PyConvert.ToInt(prog["total"], 0);

                string err = "";
                try
                {
                    var eobj = prog["error"];
                    if (eobj != null)
                    {
                        var s = eobj.ToString();
                        if (!string.IsNullOrWhiteSpace(s) && !string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                            err = s;
                    }
                }
                catch { }

                return new ProbeProgress(st, pct, dn, tt, err);
            }, token);
        }

        private void OpenIconThemeLab_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                // 优先通过名为 RootFrame 的 Frame 导航（与主框架约定）
                var rootFrame = Window.GetWindow(this)?.FindName("RootFrame") as Frame;
                if (rootFrame != null)
                {
                    rootFrame.Navigate(new IconThemeLabPage());
                    return;
                }

                // 如果没有 Frame，就尝试直接在当前窗口内容中展示
                if (Window.GetWindow(this) is Window win && win.Content is Frame currentFrame)
                {
                    currentFrame.Navigate(new IconThemeLabPage());
                }
            }
            catch
            {
                // 忽略实验页导航失败，避免影响其他工具
            }
        }
    }

    public sealed class PageInfoItem
    {
        public string RealName { get; set; } = "";
        public string Url { get; set; } = "";
        public double SizeGb { get; set; }
        public string SizeGbText => Math.Round(SizeGb, 3).ToString("0.###");
    }
}
