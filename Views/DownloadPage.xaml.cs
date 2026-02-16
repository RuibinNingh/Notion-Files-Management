using Microsoft.Win32;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Notion_Files_Management.Models;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Views
{
    public partial class DownloadPage : Page
    {
        // ===== UI data is kept in session to survive navigation =====
        private readonly DownloadSession _session = DownloadSession.Instance;
        private readonly NotionBackendService _svc = NotionBackendService.Instance;

        public ObservableCollection<FileSelectItem> FileSelectionList => _session.FileSelectionList;
        public ObservableCollection<DownloadTaskStatus> DisplayTasks => _session.DisplayTasks;

        private string _saveDirectory
        {
            get => _session.SaveDirectory;
            set => _session.SaveDirectory = value;
        }

        // ===== Get list cancellation =====
        private CancellationTokenSource? _getListCts;
        private int _getListReqId;

        // ===== Download polling =====
        private readonly DispatcherTimer _downloadStatusTimer = new DispatcherTimer();

        // Avoid recursive TextChanged when we programmatically set Text.
        private bool _isFormattingPageId;

        public DownloadPage()
        {
            InitializeComponent();
            DataContext = this;

            Logger.Info("DownloadPage initialized");

            TaskResetNotifier.TasksReset += OnTasksReset;

            // Ensure ItemsSource even if XAML binding is missing.
            try { FileListSelector.ItemsSource = FileSelectionList; } catch { }
            try { DownloadTaskListView.ItemsSource = DisplayTasks; } catch { }

            // Restore persisted save directory (if any)
            try { SavePathDisplay.Text = _saveDirectory; } catch { }

            _downloadStatusTimer.Interval = TimeSpan.FromSeconds(1);
            _downloadStatusTimer.Tick += UpdateDownloadStatusesTick;

            Loaded += async (_, __) =>
            {
                try
                {
                    if (_session.HasActiveDownloads)
                    {
                        await RefreshStatusesAsync(CancellationToken.None);
                        if (!_downloadStatusTimer.IsEnabled)
                            _downloadStatusTimer.Start();
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn($"Restore polling failed: {ex.Message}");
                }
            };

            Unloaded += (_, __) =>
            {
                TaskResetNotifier.TasksReset -= OnTasksReset;
                if (_downloadStatusTimer.IsEnabled)
                    _downloadStatusTimer.Stop();
            };

            // Warm up python (do not block UI)
            UiHelpers.WarmUpBackend();
        }

        // =========================
        // UI: open / close modal
        // =========================
        private void BtnOpenDownloadDialog_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("Open download dialog");
            ModalOverlay.Visibility = Visibility.Visible;
            ModalStep1.Visibility = Visibility.Visible;
            ModalStep2.Visibility = Visibility.Collapsed;
            BtnConfirmId.IsEnabled = true;

            try { PageIdInput.Text = _session.PageId; } catch { }
            try { SavePathDisplay.Text = _saveDirectory; } catch { }

            // Clear inline error when opening.
            try { PageIdErrorText.Text = ""; } catch { }
        }

        private void PageIdInput_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox textBox)
            {
                PageIdInputHelper.HandleTextChanged(textBox, PageIdErrorText, ref _isFormattingPageId);
            }
        }

        private void CloseModal_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("Close download dialog (cancel probe if running)");
            _getListCts?.Cancel();

            ModalOverlay.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;

            BtnConfirmId.IsEnabled = true;
            BtnConfirmId.Content = "获取列表";
        }

        private void BackToStep1_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("Back to Step1");
            ModalStep2.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Visible;
        }

        // =========================
        // Core: get download list + probe sizes
        // =========================
        private async void ConfirmId_Click(object sender, RoutedEventArgs e)
        {
            var confirmBtn = sender as Button;
            var oldContent = confirmBtn?.Content;
            if (confirmBtn != null)
                confirmBtn.Content = "稍等";

            string rawInput = PageIdInput.Text ?? "";
            if (!NotionPageId.TryNormalize(rawInput, out string pageId, out string pageIdErr))
            {
                // Inline hint + modal alert.
                try { PageIdErrorText.Text = pageIdErr; } catch { }
                MessageBox.Show(pageIdErr);
                if (confirmBtn != null)
                    confirmBtn.Content = oldContent;
                return;
            }

            // Keep UI canonical (e.g., user pasted without hyphens).
            if (!string.Equals(PageIdInput.Text, pageId, StringComparison.Ordinal))
                PageIdInput.Text = pageId;

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                if (confirmBtn != null)
                    confirmBtn.Content = oldContent;
                return;
            }

            // New request: cancel previous.
            _getListCts?.Cancel();
            _getListCts = new CancellationTokenSource();
            var token = _getListCts.Token;
            int reqId = ++_getListReqId;

            BtnConfirmId.IsEnabled = false;
            _session.PageId = pageId;

            int notFoundCount = 0;
            double lastPct = -1;

            var progress = new Progress<NotionBackendService.ProbeProgress>(p =>
            {
                if (token.IsCancellationRequested || reqId != _getListReqId)
                    return;

                if (string.Equals(p.Status, "not_found", StringComparison.OrdinalIgnoreCase))
                {
                    BtnConfirmId.Content = $"准备探测任务…（{++notFoundCount}）";
                    return;
                }

                if (Math.Abs(p.Percent - lastPct) > 0.01)
                    lastPct = p.Percent;

                BtnConfirmId.Content = string.Equals(p.Status, "done", StringComparison.OrdinalIgnoreCase)
                    ? "探测完成"
                    : $"探测中 {p.Percent:0}% ({p.Done}/{Math.Max(1, p.Total)})";
            });

            try
            {
                Logger.Info($"Get list clicked. pageId={pageId}");

                var ret = await _svc.FetchDownloadListWithProbeAsync(pageId, progress, token);
                token.ThrowIfCancellationRequested();
                if (reqId != _getListReqId)
                    return;

                if (ret.ProbeId <= 0 || ret.Items.Count == 0)
                {
                    MessageBox.Show(string.IsNullOrWhiteSpace(ret.Msg) ? "该页面没有可下载的文件。" : ret.Msg);
                    Logger.Warn($"get_download_list returned probe_id={ret.ProbeId}, total={ret.Total}, status={ret.Status}, msg={ret.Msg}");
                    return;
                }

                // Preserve selection across refresh (url as key)
                var selectedMap = FileSelectionList.ToDictionary(
                    x => x.url ?? "",
                    x => x.IsSelected,
                    StringComparer.OrdinalIgnoreCase);

                FileSelectionList.Clear();
                foreach (var x in ret.Items)
                {
                    if (!string.IsNullOrWhiteSpace(x.url) && selectedMap.TryGetValue(x.url, out bool sel))
                        x.IsSelected = sel;
                    FileSelectionList.Add(x);
                }

                // Switch to Step2
                ModalStep1.Visibility = Visibility.Collapsed;
                ModalStep2.Visibility = Visibility.Visible;

                Logger.Info($"Download list ready. count={FileSelectionList.Count}");
            }
            catch (OperationCanceledException)
            {
                Logger.Warn("Get list canceled");
            }
            catch (Exception ex)
            {
                MessageBox.Show("获取列表失败: " + ex.Message);
                Logger.Error("Get list failed", ex);
            }
            finally
            {
                if (reqId == _getListReqId)
                {
                    BtnConfirmId.IsEnabled = true;
                    BtnConfirmId.Content = oldContent ?? "获取列表";
                }
            }
        }

        // =========================
        // UI: choose folder
        // =========================
        private void SelectFolder_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("SelectFolder clicked");

            // WPF has no built-in folder picker (without WinForms). Use OpenFileDialog to pick a directory.
            var dlg = new OpenFileDialog
            {
                Title = "请选择保存目录（进入目标文件夹后点“打开”即可）",
                CheckFileExists = false,
                CheckPathExists = true,
                FileName = "选择此文件夹",
                Filter = "文件夹|*.folder"
            };

            if (dlg.ShowDialog() == true)
            {
                string? dir = Path.GetDirectoryName(dlg.FileName);
                if (!string.IsNullOrWhiteSpace(dir) && Directory.Exists(dir))
                {
                    _saveDirectory = dir;
                    SavePathDisplay.Text = _saveDirectory;
                    Logger.Info($"SaveDirectory set: {_saveDirectory}");
                }
            }
        }

        private void SelectAll_Click(object sender, RoutedEventArgs e)
        {
            foreach (var x in FileSelectionList)
                x.IsSelected = true;
        }

        private void InvertSelect_Click(object sender, RoutedEventArgs e)
        {
            foreach (var x in FileSelectionList)
                x.IsSelected = !x.IsSelected;
        }

        // =========================
        // Core: start download tasks
        // =========================
        private async void SubmitDownload_Click(object sender, RoutedEventArgs e)
        {
            var btn = sender as Button;
            var oldContent = btn?.Content;
            if (btn != null)
                btn.Content = "稍等";

            Logger.Info("SubmitDownload clicked");

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                if (btn != null)
                    btn.Content = oldContent;
                return;
            }

            var selected = FileSelectionList.Where(x => x.IsSelected).ToList();
            if (selected.Count == 0)
            {
                MessageBox.Show("请至少选择一个下载项。");
                if (btn != null)
                    btn.Content = oldContent;
                return;
            }

            if (string.IsNullOrWhiteSpace(_saveDirectory) || !Directory.Exists(_saveDirectory))
            {
                MessageBox.Show("请选择有效的保存目录。");
                if (btn != null)
                    btn.Content = oldContent;
                return;
            }

            // Best-effort URL expiry pre-check (Notion file urls expire).
            var expired = selected
                .Where(x => x.expiry_utc is DateTimeOffset dto && dto <= DateTimeOffset.UtcNow)
                .ToList();

            if (expired.Count > 0)
            {
                MessageBox.Show($"检测到 {expired.Count} 个文件的下载链接已过期（expiry_time 早于当前时间）。\n请重新获取列表后再开始下载。");
                if (btn != null)
                    btn.Content = oldContent;
                return;
            }

            try
            {
                Logger.Info($"Starting download. selected={selected.Count}, saveDir={_saveDirectory}");
                string ret = await _svc.StartDownloadAsync(selected, _saveDirectory, CancellationToken.None);

                // Close modal
                ModalOverlay.Visibility = Visibility.Collapsed;
                ModalStep1.Visibility = Visibility.Collapsed;
                ModalStep2.Visibility = Visibility.Collapsed;

                Logger.Info($"download_notion_files returned: {ret}");
                // Only show message box when response indicates an unexpected error.
                if (!Notion_Files_Management.Utils.UiHelpers.IsSuccessResponse(ret))
                    MessageBox.Show(ret);

                // Start polling
                if (!_downloadStatusTimer.IsEnabled)
                    _downloadStatusTimer.Start();

                _session.HasActiveDownloads = true;
            }
            catch (Exception ex)
            {
                MessageBox.Show("启动下载失败: " + ex.Message);
                Logger.Error("Start download failed", ex);
            }
            finally
            {
                if (btn != null)
                {
                    btn.Content = oldContent;
                    btn.IsEnabled = true;
                }
            }
        }

        // =========================
        // Poll: download statuses
        // =========================
        private async void UpdateDownloadStatusesTick(object? sender, EventArgs e)
        {
            if (!_svc.IsReady)
                return;

            try
            {
                await RefreshStatusesAsync(CancellationToken.None);
                if (DisplayTasks.Count == 0 && _downloadStatusTimer.IsEnabled)
                {
                    _downloadStatusTimer.Stop();
                    _session.HasActiveDownloads = false;
                }
            }
            catch (Exception ex)
            {
                Logger.Error("Polling download statuses failed", ex);
            }
        }

        private async Task RefreshStatusesAsync(CancellationToken token)
        {
            if (!_svc.IsReady)
                return;

            var all = await _svc.GetDownloadStatusesAsync(token);
            var statuses = all
                .Where(x => !string.Equals(x.status, "completed", StringComparison.OrdinalIgnoreCase))
                .ToList();

            // Update session.DisplayTasks (reuse existing items when possible)
            var map = _session.DisplayTasks.ToDictionary(x => x.url ?? "", x => x, StringComparer.OrdinalIgnoreCase);

            foreach (var s in statuses)
            {
                string key = s.url ?? "";
                if (string.IsNullOrWhiteSpace(key))
                    continue;

                if (!map.TryGetValue(key, out var item))
                {
                    _session.DisplayTasks.Add(s);
                    map[key] = s;
                }
                else
                {
                    item.name = s.name;
                    item.real_name = s.real_name;
                    item.status = s.status;
                    item.progress = s.progress;
                    item.downloaded_mb = s.downloaded_mb;
                    item.total_mb = s.total_mb;
                    item.speed_mb_s = s.speed_mb_s;
                    item.ETA = s.ETA;
                    item.error = s.error;
                }
            }

            var alive = new HashSet<string>(statuses.Select(x => x.url ?? ""), StringComparer.OrdinalIgnoreCase);
            for (int i = _session.DisplayTasks.Count - 1; i >= 0; i--)
            {
                var u = _session.DisplayTasks[i].url ?? "";
                if (!alive.Contains(u))
                    _session.DisplayTasks.RemoveAt(i);
            }

            _session.HasActiveDownloads = _session.DisplayTasks.Count > 0;
        }

        private void OnTasksReset()
        {
            try
            {
                if (_downloadStatusTimer.IsEnabled)
                    _downloadStatusTimer.Stop();

                _session.HasActiveDownloads = false;

                Application.Current.Dispatcher.Invoke(() =>
                {
                    try
                    {
                        DisplayTasks.Clear();
                        FileSelectionList.Clear();
                    }
                    catch { }
                });
            }
            catch { }
        }
    }
}
