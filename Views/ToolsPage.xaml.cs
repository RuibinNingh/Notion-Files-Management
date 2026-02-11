using Python.Runtime;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Views
{
    public partial class ToolsPage : Page
    {
        private sealed record ProbeProgress(string Status, double Percent, int Done, int Total, string Error);

        // ===== UI 数据（绑定给 ListView）=====
        public ObservableCollection<PageInfoItem> PageInfoItems { get; } = new();

        // ===== Python =====
        private dynamic? _pyMain;
        private string _currentNotionToken = "";
        private static readonly SemaphoreSlim _pyLock = new(1, 1);

        // ===== 查询取消支持 =====
        private CancellationTokenSource? _cts;
        private int _reqId = 0;

        public ToolsPage()
        {
            InitializeComponent();
            DataContext = this;

            try { PageInfoListView.ItemsSource = PageInfoItems; } catch { }

            // 预热（不阻塞 UI）
            _ = Task.Run(() => EnsureBackendReady(out _));
        }

        // 打开“提示框”而不是 Window
        private void OpenPageInfoModal_Click(object sender, RoutedEventArgs e)
        {
            OpenStep1();
        }

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

            // 清空旧结果
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

        private async void StartQuery_Click(object sender, RoutedEventArgs e)
        {
            if (!EnsureBackendReady(out string err))
            {
                MessageBox.Show(err);
                return;
            }

            string pageId = (PageIdInput.Text ?? "").Trim().Replace(" ", "");
            if (string.IsNullOrWhiteSpace(pageId))
            {
                MessageBox.Show("请输入目标页面 ID。");
                return;
            }

            // 新请求：取消旧请求
            _cts?.Cancel();
            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            int reqId = ++_reqId;

            BtnStartQuery.IsEnabled = false;

            OpenStep2();

            try
            {
                // 1) 触发 get_download_list（启动探测）
                var (probeId, total, msg, status) = await RunPython(() =>
                {
                    dynamic ret = _pyMain!.get_download_list(pageId);

                    int pid = 0, tot = 0;
                    string m = "", st = "";
                    try { pid = PyConvert.ToInt(ret["probe_id"], 0); } catch { }
                    try { tot = PyConvert.ToInt(ret["total"], 0); } catch { }
                    try { m = ret["msg"]?.ToString() ?? ""; } catch { }
                    try { st = ret["status"]?.ToString() ?? ""; } catch { }
                    return (pid, tot, m, st);
                }, token);

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                if (probeId <= 0)
                {
                    MessageBox.Show(string.IsNullOrWhiteSpace(msg) ? "获取列表失败或页面无文件。" : msg);
                    BackToStep1_Click(null!, null!);
                    return;
                }

                // 2) 轮询 download_list_processing(probeId)
                int notFoundCount = 0;
                while (true)
                {
                    token.ThrowIfCancellationRequested();
                    if (reqId != _reqId) return;

                    var p = await GetProbeProgressAsync(probeId, token);

                    // 更新 UI（确保进度条一定渲染）
                    await Dispatcher.InvokeAsync(() =>
                    {
                        ProbeProgressBar.Value = p.Percent;
                        if (string.Equals(p.Status, "not_found", StringComparison.OrdinalIgnoreCase))
                        {
                            ProbeStatusText.Text = $"准备探测任务…（{++notFoundCount}）";
                        }
                        else
                        {
                            ProbeStatusText.Text = $"探测中 {p.Percent:0}%（{p.Done}/{Math.Max(1, p.Total)}）";
                        }
                    });

                    if (string.Equals(p.Status, "done", StringComparison.OrdinalIgnoreCase))
                        break;

                    if (string.Equals(p.Status, "error", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(p.Status, "failed", StringComparison.OrdinalIgnoreCase))
                        throw new Exception(string.IsNullOrWhiteSpace(p.Error) ? "探测失败" : p.Error);

                    await Task.Delay(350, token);
                }

                // 3) 探测完成，读取 main.download_list（注意文件名用 real_name）
                var items = await RunPython(() =>
                {
                    var list = new List<PageInfoItem>();
                    dynamic pyList = _pyMain!.download_list;

                    foreach (var it in pyList)
                    {
                        string realName = "";
                        string url = "";
                        double sizeMb = 0;

                        try { realName = it["real_name"]?.ToString() ?? ""; } catch { }
                        try { url = it["url"]?.ToString() ?? ""; } catch { }
                        try { sizeMb = PyConvert.ToDouble(it["size_mb"], 0.0); } catch { }

                        if (string.IsNullOrWhiteSpace(realName))
                            realName = "(未命名文件)";

                        // UI 要 GB
                        double sizeGb = sizeMb / 1024.0;

                        list.Add(new PageInfoItem
                        {
                            RealName = realName,
                            Url = url,
                            SizeGb = sizeGb
                        });
                    }

                    return list;
                }, token);

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                // 4) 渲染列表 + 统计
                await Dispatcher.InvokeAsync(() =>
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
                await Dispatcher.InvokeAsync(() =>
                {
                    ProbeStatusText.Text = "已取消。";
                });
            }
            catch (Exception ex)
            {
                MessageBox.Show("获取页面信息失败：" + ex.Message);
                Logger.Error("ToolsPage StartQuery failed", ex);
                BackToStep1_Click(null!, null!);
            }
            finally
            {
                await Dispatcher.InvokeAsync(() => BtnStartQuery.IsEnabled = true);
            }
        }

        // ======== Python 封装（复用 DownloadPage） ========

        private bool EnsureBackendReady(out string error)
        {
            error = "";
            try
            {
                ConfigManager.Load();
                string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";
                if (string.IsNullOrEmpty(token))
                {
                    error = "未检测到 Notion Token，请先到【设置】页保存 Token。";
                    return false;
                }

                if (_pyMain != null && token == _currentNotionToken)
                    return true;

                using (Py.GIL())
                {
                    InjectDotenvStubIfMissing();

                    dynamic sys = Py.Import("sys");
                    string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
                    sys.path.append(scriptsPath);

                    dynamic mainMod = Py.Import("main");
                    _pyMain = mainMod.Main(token, 3);
                    _currentNotionToken = token;
                }

                return true;
            }
            catch (Exception ex)
            {
                error = "初始化失败: " + ex.Message;
                return false;
            }
        }

        private async Task<T> RunPython<T>(Func<T> func, CancellationToken token)
        {
            await _pyLock.WaitAsync(token);
            try
            {
                return await Task.Run(() =>
                {
                    token.ThrowIfCancellationRequested();
                    using (Py.GIL())
                        return func();
                }, token);
            }
            finally
            {
                _pyLock.Release();
            }
        }

        private Task<ProbeProgress> GetProbeProgressAsync(int probeId, CancellationToken token)
        {
            return RunPython(() =>
            {
                dynamic prog = _pyMain!.download_list_processing(probeId);

                string st = prog["status"]?.ToString() ?? "";
                double pct = 0.0;
                int dn = 0, tt = 0;
                string err = "";

                try { pct = PyConvert.ToDouble(prog["percent"], 0.0); } catch { }
                try { dn = PyConvert.ToInt(prog["done"], 0); } catch { }
                try { tt = PyConvert.ToInt(prog["total"], 0); } catch { }

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

        private static void InjectDotenvStubIfMissing()
        {
            try { Py.Import("dotenv"); }
            catch
            {
                dynamic types = Py.Import("types");
                dynamic sys = Py.Import("sys");
                dynamic mod = types.ModuleType("dotenv");
                mod.__dict__["load_dotenv"] = new Action(() => { });
                sys.modules["dotenv"] = mod;
            }
        }
    }

    // ===== ListView 绑定项（GB 文本）=====
    public sealed class PageInfoItem
    {
        public string RealName { get; set; } = "";
        public string Url { get; set; } = "";
        public double SizeGb { get; set; }

        public string SizeGbText => Math.Round(SizeGb, 3).ToString("0.###");
    }
}