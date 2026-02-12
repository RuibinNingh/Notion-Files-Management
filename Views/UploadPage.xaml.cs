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
    public partial class UploadPage : Page
    {
        // ===== UI data is kept in session to survive navigation =====
        private readonly UploadSession _session = UploadSession.Instance;
        private readonly NotionBackendService _svc = NotionBackendService.Instance;

        public ObservableCollection<string> SelectedUploadFiles => _session.SelectedUploadFiles;
        public ObservableCollection<UploadTaskStatus> DisplayUploads => _session.DisplayUploads;

        // ===== Polling & EMA =====
        private readonly DispatcherTimer _statusTimer = new DispatcherTimer();
        private const double SpeedEmaAlpha = 0.2; // 0.1~0.3 (smaller => smoother)

        public UploadPage()
        {
            InitializeComponent();
            DataContext = this;

            Logger.Info("UploadPage initialized");

            _statusTimer.Interval = TimeSpan.FromSeconds(1);
            _statusTimer.Tick += UploadStatusTick;

            TaskResetNotifier.TasksReset += OnTasksReset;

            // Ensure ItemsSource binding
            try { UploadTaskListView.ItemsSource = DisplayUploads; } catch { }
            try { UploadFileListView.ItemsSource = SelectedUploadFiles; } catch { }

            // Restore persisted page id (if any)
            try { PageIdInput.Text = _session.PageId; } catch { }

            Loaded += async (_, __) =>
            {
                try
                {
                    // 恢复轮询状态：如果有活跃的上传任务，重新启动轮询
                    if (_session.HasActiveUploads)
                    {
                        await RefreshUploadStatusesAsync(CancellationToken.None);
                        if (!_statusTimer.IsEnabled)
                            _statusTimer.Start();
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn($"Restore upload polling failed: {ex.Message}");
                }
            };

            Unloaded += (_, __) =>
            {
                TaskResetNotifier.TasksReset -= OnTasksReset;
                // 停止计时器但不清除数据，以便下次加载时恢复
                if (_statusTimer.IsEnabled)
                    _statusTimer.Stop();
            };

            // Warm up python backend (do not block UI)
            _ = Task.Run(async () =>
            {
                try { await _svc.EnsureBackendReadyFromConfigAsync(); } catch { }
            });
        }

        // ========== UI: modal open/close ==========
        private void BtnOpenUploadDialog_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("Open upload dialog");
            ModalHint.Text = "";
            BtnConfirmStart.IsEnabled = true;

            ModalOverlay.Visibility = Visibility.Visible;
            ModalStep1.Visibility = Visibility.Visible;
        }

        private void CloseModal_Click(object sender, RoutedEventArgs e)
        {
            Logger.Info("Close upload dialog");
            ModalOverlay.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Collapsed;
        }

        // ========== UI: select files ==========
        private void SelectUploadFiles_Click(object sender, RoutedEventArgs e)
        {
            bool multiselect = ToggleMultiSelect.IsChecked == true;

            var dlg = new OpenFileDialog
            {
                Multiselect = multiselect,
                Title = multiselect ? "选择要上传的文件（可多选）" : "选择要上传的文件（单选）"
            };

            if (dlg.ShowDialog() == true)
            {
                SelectedUploadFiles.Clear();
                foreach (var f in dlg.FileNames)
                    SelectedUploadFiles.Add(f);

                ModalHint.Text = $"已选择 {SelectedUploadFiles.Count} 个文件";
            }
        }

        private void ClearUploadFiles_Click(object sender, RoutedEventArgs e)
        {
            SelectedUploadFiles.Clear();
            ModalHint.Text = "已清空";
        }

        // ========== Core: confirm start upload ==========
        private async void ConfirmStart_Click(object sender, RoutedEventArgs e)
        {
            if (SelectedUploadFiles.Count == 0)
            {
                MessageBox.Show("请先选择至少一个文件。");
                return;
            }

            string pageId = (PageIdInput.Text ?? "").Trim();
            if (string.IsNullOrEmpty(pageId))
            {
                MessageBox.Show("请输入 Notion Page ID。");
                return;
            }

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnConfirmStart.IsEnabled = false;
            ModalHint.Text = "正在创建上传任务…";

            try
            {
                // Snapshot list (avoid enumerating ObservableCollection from other threads)
                var filePaths = SelectedUploadFiles.ToList();

                Logger.Info($"Start upload. pageId={pageId}, files={filePaths.Count}");

                // 保存PageId到session
                _session.PageId = pageId;

                string ret = await _svc.StartUploadAsync(pageId, filePaths, CancellationToken.None);

                // Close modal
                ModalOverlay.Visibility = Visibility.Collapsed;
                ModalStep1.Visibility = Visibility.Collapsed;

                // Add tasks to UI immediately (EMA init)
                foreach (var path in filePaths)
                {
                    if (DisplayUploads.Any(x => string.Equals(x.FilePath, path, StringComparison.OrdinalIgnoreCase)))
                        continue;

                    DisplayUploads.Add(new UploadTaskStatus
                    {
                        FilePath = path,
                        FileName = Path.GetFileName(path),
                        Status = "waiting",
                        Stage = "waiting",
                        Progress = 0,
                        UploadedMB = 0,
                        TotalMB = GuessSizeMB(path),
                        SmoothedSpeedMBps = 0,
                        ETASeconds = 0,
                        Error = null
                    });

                    _session.SpeedEma[path] = 0.0;
                }

                if (!_statusTimer.IsEnabled)
                    _statusTimer.Start();

                _session.HasActiveUploads = true;

                if (!string.IsNullOrWhiteSpace(ret))
                    // Only show message box when response indicates an unexpected error.
                    if (!Notion_Files_Management.Utils.UiHelpers.IsSuccessResponse(ret))
                        MessageBox.Show(ret);
            }
            catch (Exception ex)
            {
                MessageBox.Show("启动上传失败: " + ex.Message);
                Logger.Error("Start upload failed", ex);
            }

            // response classification moved to Utils.UiHelpers
            finally
            {
                BtnConfirmStart.IsEnabled = true;
                ModalHint.Text = "";
            }
        }

        // ========== Polling: get_upload_statuses + EMA smoothing ==========
        private async void UploadStatusTick(object? sender, EventArgs e)
        {
            if (!_svc.IsReady)
                return;

            try
            {
                await RefreshUploadStatusesAsync(CancellationToken.None);

                // 如果没有上传任务了，停止轮询
                if (DisplayUploads.Count == 0 && _statusTimer.IsEnabled)
                {
                    _statusTimer.Stop();
                    _session.HasActiveUploads = false;
                }
            }
            catch (Exception ex)
            {
                // Avoid popping dialogs every second; keep logs.
                Logger.Error("Polling upload statuses failed", ex);
            }
        }

        private async Task RefreshUploadStatusesAsync(CancellationToken token)
        {
            if (!_svc.IsReady)
                return;

            var statuses = await _svc.GetUploadStatusesAsync(token);

            // Incremental update using file_path as key
            var map = DisplayUploads.ToDictionary(x => x.FilePath ?? "", x => x, StringComparer.OrdinalIgnoreCase);

            foreach (var s in statuses)
            {
                if (string.IsNullOrWhiteSpace(s.FilePath))
                    continue;

                // completed: remove immediately
                if (string.Equals(s.Status, "completed", StringComparison.OrdinalIgnoreCase))
                {
                    var toRemove = DisplayUploads.FirstOrDefault(x =>
                        string.Equals(x.FilePath, s.FilePath, StringComparison.OrdinalIgnoreCase));

                    if (toRemove != null)
                        DisplayUploads.Remove(toRemove);

                    _session.SpeedEma.Remove(s.FilePath);
                    continue;
                }

                if (!map.TryGetValue(s.FilePath, out var item))
                {
                    item = new UploadTaskStatus
                    {
                        FilePath = s.FilePath,
                        FileName = Path.GetFileName(s.FilePath),
                    };
                    DisplayUploads.Add(item);
                    map[s.FilePath] = item;
                    _session.SpeedEma[s.FilePath] = 0.0;
                }

                item.Status = s.Status;
                item.Stage = s.Stage;
                item.Progress = s.Progress;
                item.UploadedMB = s.UploadedMB;
                item.TotalMB = s.TotalMB;
                item.ETASeconds = s.ETA;
                item.Error = string.IsNullOrWhiteSpace(s.Error) ? null : s.Error;

                // EMA smoothed speed
                double raw = Math.Max(0.0, s.Speed);
                double prev = _session.SpeedEma.TryGetValue(s.FilePath, out var old) ? old : 0.0;
                double ema = (SpeedEmaAlpha * raw) + ((1.0 - SpeedEmaAlpha) * prev);
                _session.SpeedEma[s.FilePath] = ema;
                item.SmoothedSpeedMBps = ema;
            }

            _session.HasActiveUploads = DisplayUploads.Count > 0;
        }

        // ===== Helpers =====
        private static double GuessSizeMB(string filePath)
        {
            try
            {
                var fi = new FileInfo(filePath);
                return Math.Max(0.1, fi.Length / 1024.0 / 1024.0);
            }
            catch
            {
                return 0.0;
            }
        }

        private void OnTasksReset()
        {
            try
            {
                if (_statusTimer.IsEnabled)
                    _statusTimer.Stop();

                _session.HasActiveUploads = false;

                Application.Current?.Dispatcher?.Invoke(() =>
                {
                    try
                    {
                        DisplayUploads.Clear();
                        SelectedUploadFiles.Clear();
                        _session.SpeedEma.Clear();
                        ModalHint.Text = "";
                    }
                    catch { }
                });
            }
            catch { }
        }
    }
}