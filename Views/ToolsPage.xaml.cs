using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
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
    public partial class ToolsPage : Page
    {
        public ObservableCollection<PageInfoItem> PageInfoItems { get; } = new();

        private readonly NotionBackendService _svc = NotionBackendService.Instance;

        private CancellationTokenSource? _cts;
        private int _reqId;

        // Avoid recursive TextChanged when we programmatically set Text.
        private bool _isFormattingPageId;
        private bool _isFormattingMigSource;
        private bool _isFormattingMigTarget;

        // Migration state
        private CancellationTokenSource? _migCts;
        private List<NotionBackendService.DataSourcePropertyInfo>? _srcProperties;
        private List<NotionBackendService.DataSourcePropertyInfo>? _tgtProperties;
        private readonly List<ComboBox> _mappingCombos = new();

        // Batch suffix removal state
        private CancellationTokenSource? _suffixCts;
        private bool _isFormattingSuffixDsId;

        // Size update state (v1.4.0-Status)
        private CancellationTokenSource? _suCts;
        private bool _isFormattingSuDsId;
        private List<NotionBackendService.DataSourcePropertyInfo>? _suProperties;
        private List<NotionBackendService.PageSizeInfo> _suPagesWithSize = new();
        private List<NotionBackendService.PageSizeInfo> _suPagesWithoutSize = new();
        private readonly List<CheckBox> _suEmptyCheckboxes = new();
        private readonly List<CheckBox> _suSetCheckboxes = new();

        // Timer state for single page query
        private Stopwatch? _queryStopwatch;
        private DispatcherTimer? _queryElapsedTimer;

        // Timer state for auto-update
        private Stopwatch? _suStopwatch;
        private DispatcherTimer? _suElapsedTimer;

        public ToolsPage()
        {
            InitializeComponent();
            DataContext = this;

            try { PageInfoListView.ItemsSource = PageInfoItems; } catch { }

            // Warm up backend (no UI blocking)
            UiHelpers.WarmUpBackend();
        }

        // ===== Modal controls =====
        private void OpenSizeUpdateChoice_Click(object sender, RoutedEventArgs e)
        {
            ModalOverlay.Visibility = Visibility.Visible;
            HideAllModalSteps();
            SizeUpdateChoice.Visibility = Visibility.Visible;
        }

        private void SizeUpdateAutoMode_Click(object sender, RoutedEventArgs e)
        {
            SizeUpdateChoice.Visibility = Visibility.Collapsed;
            OpenSizeUpdateStep1();
        }

        private void SizeUpdateQueryMode_Click(object sender, RoutedEventArgs e)
        {
            SizeUpdateChoice.Visibility = Visibility.Collapsed;
            OpenStep1();
        }

        private void OpenPageInfoModal_Click(object sender, RoutedEventArgs e) => OpenStep1();

        private void OpenStep1()
        {
            ModalOverlay.Visibility = Visibility.Visible;
            HideAllModalSteps();
            ModalStep1.Visibility = Visibility.Visible;
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
            ProbeProgressBar.IsIndeterminate = true;
            ProbeTitle.Text = "正在扫描页面文件";
            ProbeStatusText.Text = "准备开始…";
            ProbeElapsedText.Text = "";
            PageInfoItems.Clear();
            StatFileCount.Text = "0";
            StatTotalGb.Text = "0";
            StatProbingHint.Visibility = Visibility.Collapsed;
            BtnCancelQuery.IsEnabled = true;

            // Start elapsed timer
            StartQueryElapsedTimer();
        }

        private void CloseModal_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            _migCts?.Cancel();
            _suffixCts?.Cancel();
            _suCts?.Cancel();
            StopQueryElapsedTimer();
            StopSuElapsedTimer();
            ModalOverlay.Visibility = Visibility.Collapsed;
            HideAllModalSteps();
        }

        private void BackToStep1_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            StopQueryElapsedTimer();
            ModalStep2.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Visible;
        }

        private void CancelQuery_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            BtnCancelQuery.IsEnabled = false;
            StopQueryElapsedTimer();
            ProbeStatusText.Text = "已取消。";
            ProbeTitle.Text = "已取消";
            ProbeProgressBar.IsIndeterminate = false;
            // 通知 Python 后台线程停止扫描和探测
            _ = _svc.CancelDownloadListStreamingAsync(CancellationToken.None);
        }

        // ===== Core (Page Info) =====
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

            ProbeStatusText.Text = "正在扫描页面文件（实时发现文件）…";

            try
            {
                Logger.Info($"ToolsPage start page info (streaming). pageId={pageId}");

                // 读取探测线程数
                int probeWorkers = 8;
                try
                {
                    if (int.TryParse(ProbeWorkersInput.Text?.Trim(), out int w) && w >= 1 && w <= 64)
                        probeWorkers = w;
                }
                catch { }

                // ── Phase 1: 启动流式扫描（后台线程递归发现文件） ──
                var (startStatus, startMsg) = await _svc.StartDownloadListStreamingAsync(pageId, probeWorkers, token);
                Logger.Info($"start_download_list_streaming => status={startStatus}, msg={startMsg}");

                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                // ── Phase 2: 轮询扫描进度，实时渲染新发现的文件 ──
                var urlToItem = new Dictionary<string, PageInfoItem>(StringComparer.Ordinal);
                int lastDiscovered = 0;

                while (true)
                {
                    token.ThrowIfCancellationRequested();
                    if (reqId != _reqId) return;

                    var scan = await _svc.GetDownloadListScanStatusAsync(token);

                    // 有新文件被发现或探测有更新 → 增量同步到 UI
                    if (scan.Discovered > lastDiscovered || scan.FilesProbed > 0)
                    {
                        try
                        {
                            bool stillProbing = await SyncDownloadListToUI(urlToItem, token);
                            lastDiscovered = scan.Discovered;
                            UpdateProbeSizeStats(isStillProbing: stillProbing);
                        }
                        catch (OperationCanceledException) { throw; }
                        catch (Exception ex)
                        {
                            Logger.Warn($"Incremental list read failed (non-fatal): {ex.Message}");
                        }
                    }

                    int probedCount = scan.FilesProbed;
                    ProbeStatusText.Text = scan.Done
                        ? $"扫描完成，共发现 {scan.Discovered} 个文件（已探测 {probedCount}）"
                        : $"正在扫描页面…已发现 {scan.Discovered} 个文件（已探测 {probedCount}）";
                    StatFileCount.Text = PageInfoItems.Count.ToString();

                    if (scan.Done)
                    {
                        if (string.Equals(scan.Status, "error", StringComparison.OrdinalIgnoreCase))
                            throw new Exception(scan.Error ?? "扫描失败");
                        break;
                    }

                    await Task.Delay(300, token);
                }

                // ── Phase 3: 扫描完成，读取最终列表确保没有遗漏 ──
                token.ThrowIfCancellationRequested();
                if (reqId != _reqId) return;

                try
                {
                    await SyncDownloadListToUI(urlToItem, token);
                    UpdateProbeSizeStats(isStillProbing: true);
                }
                catch (OperationCanceledException) { throw; }
                catch (Exception ex)
                {
                    Logger.Warn($"Final scan list read failed (non-fatal): {ex.Message}");
                }

                if (PageInfoItems.Count == 0)
                {
                    MessageBox.Show("该页面没有发现任何文件。");
                    BackToStep1_Click(null!, null!);
                    return;
                }

                // ── Phase 4: 轮询流式探测（_probe_consumer）进度，实时更新大小 ──
                // 不再使用传统 start_probe_sizes 重复探测，直接轮询 probing_done 状态。
                // _probe_consumer 在扫描期间就已并行探测，此处只是等它把剩余队列处理完。
                {
                    var scanInit = await _svc.GetDownloadListScanStatusAsync(token);
                    int totalUrls = scanInit.TotalUrls;

                    if (totalUrls == 0)
                    {
                        // 没有可探测的文件，直接结束
                        foreach (var kv in urlToItem) kv.Value.IsProbing = false;
                        UpdateProbeSizeStats(isStillProbing: false);
                        ProbeProgressBar.IsIndeterminate = false;
                        ProbeProgressBar.Value = 100;
                        ProbeStatusText.Text = "查询完成。";
                    }
                    else
                    {
                        ProbeTitle.Text = "正在探测文件大小";
                        ProbeProgressBar.IsIndeterminate = false;
                        ProbeProgressBar.Value = 0;
                        StatProbingHint.Visibility = Visibility.Visible;

                        while (true)
                        {
                            token.ThrowIfCancellationRequested();
                            if (reqId != _reqId) return;

                            var scan = await _svc.GetDownloadListScanStatusAsync(token);
                            int probed = scan.FilesProbed;
                            int total  = Math.Max(1, scan.TotalUrls > 0 ? scan.TotalUrls : totalUrls);
                            double pct = Math.Min(100.0, probed * 100.0 / total);

                            ProbeProgressBar.Value = pct;
                            ProbeStatusText.Text = scan.ProbingDone
                                ? "探测完成。"
                                : $"探测中 {pct:0}%（{probed}/{total}）";

                            try
                            {
                                bool stillProbing = await SyncDownloadListToUI(urlToItem, token);
                                UpdateProbeSizeStats(isStillProbing: !scan.ProbingDone && stillProbing);
                            }
                            catch (OperationCanceledException) { throw; }
                            catch (Exception ex) { Logger.Warn($"Phase4 list read failed (non-fatal): {ex.Message}"); }

                            if (scan.ProbingDone) break;

                            await Task.Delay(350, token);
                        }

                        // ── Phase 5: 最终读取，确保所有大小已更新 ──
                        token.ThrowIfCancellationRequested();
                        if (reqId != _reqId) return;

                        var finalItems = await _svc.ReadDownloadListAsync(token);
                        foreach (var it in finalItems)
                        {
                            if (!string.IsNullOrEmpty(it.url) && urlToItem.TryGetValue(it.url, out var uiItem))
                            {
                                uiItem.SizeGb = it.size_mb > 0 ? it.size_mb / 1024.0 : 0.0;
                                uiItem.IsProbing = false;
                            }
                        }
                    }
                }

                // 按大小降序重排列表
                var sorted = PageInfoItems.OrderByDescending(x => x.SizeGb).ToList();
                PageInfoItems.Clear();
                foreach (var item in sorted)
                    PageInfoItems.Add(item);

                UpdateProbeSizeStats(isStillProbing: false);
                ProbeProgressBar.IsIndeterminate = false;
                ProbeProgressBar.Value = 100;
                ProbeTitle.Text = "查询完成";
                ProbeStatusText.Text = "查询完成。";
                BtnCancelQuery.IsEnabled = false;
                StopQueryElapsedTimer();
            }
            catch (OperationCanceledException)
            {
                ProbeStatusText.Text = "已取消。";
                StopQueryElapsedTimer();
            }
            catch (Exception ex)
            {
                MessageBox.Show("获取页面信息失败：" + ex.Message);
                Logger.Error("ToolsPage StartQuery failed", ex);
                StopQueryElapsedTimer();
                BackToStep1_Click(null!, null!);
            }
            finally
            {
                BtnStartQuery.IsEnabled = true;
            }
        }

        /// <summary>
        /// 更新统计栏的总大小和探测提示
        /// </summary>
        private void UpdateProbeSizeStats(bool isStillProbing)
        {
            StatFileCount.Text = PageInfoItems.Count.ToString();
            double totalGb = PageInfoItems.Sum(x => x.SizeGb);
            StatTotalGb.Text = Math.Round(totalGb, 3).ToString("0.000") + " GB";
            StatProbingHint.Visibility = isStillProbing ? Visibility.Visible : Visibility.Collapsed;
        }

        /// <summary>
        /// 从后端读取 download_list 并增量同步到 PageInfoItems UI 集合。
        /// 新文件添加到集合，已有文件更新大小（如果已探测完成）。
        /// 返回是否仍有文件在探测中。
        /// </summary>
        private async Task<bool> SyncDownloadListToUI(
            Dictionary<string, PageInfoItem> urlToItem,
            CancellationToken token)
        {
            var items = await _svc.ReadDownloadListAsync(token);
            foreach (var it in items)
            {
                string url = it.url ?? "";
                if (string.IsNullOrEmpty(url)) continue;

                if (!urlToItem.ContainsKey(url))
                {
                    bool hasSize = it.size_mb > 0;
                    var item = new PageInfoItem
                    {
                        RealName = string.IsNullOrWhiteSpace(it.real_name) ? "(未命名文件)" : it.real_name!,
                        Url = url,
                        SizeGb = hasSize ? it.size_mb / 1024.0 : 0.0,
                        IsProbing = !hasSize
                    };
                    PageInfoItems.Add(item);
                    urlToItem[url] = item;
                }
                else if (urlToItem.TryGetValue(url, out var existingItem))
                {
                    if (it.size_mb > 0 && existingItem.IsProbing)
                    {
                        existingItem.SizeGb = it.size_mb / 1024.0;
                        existingItem.IsProbing = false;
                    }
                }
            }
            return PageInfoItems.Any(x => x.IsProbing);
        }

        // ── Reusable elapsed timer helpers ────────────────────────────────

        private void StartElapsedTimer(ref Stopwatch? stopwatch, ref DispatcherTimer? timer, TextBlock target)
        {
            StopElapsedTimer(ref stopwatch, ref timer, target);
            stopwatch = Stopwatch.StartNew();
            var sw = stopwatch; // capture for closure
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
            timer.Tick += (_, _) =>
            {
                if (sw != null)
                    target.Text = $"⏱ 用时 {FormatElapsed(sw.Elapsed)}";
            };
            timer.Start();
        }

        private void StopElapsedTimer(ref Stopwatch? stopwatch, ref DispatcherTimer? timer, TextBlock target)
        {
            stopwatch?.Stop();
            if (timer != null)
            {
                timer.Stop();
                timer = null;
            }
            if (stopwatch != null)
            {
                target.Text = $"⏱ 总用时 {FormatElapsed(stopwatch.Elapsed)}";
            }
        }

        private void StartQueryElapsedTimer() => StartElapsedTimer(ref _queryStopwatch, ref _queryElapsedTimer, ProbeElapsedText);
        private void StopQueryElapsedTimer() => StopElapsedTimer(ref _queryStopwatch, ref _queryElapsedTimer, ProbeElapsedText);
        private void StartSuElapsedTimer() => StartElapsedTimer(ref _suStopwatch, ref _suElapsedTimer, SuElapsedText);
        private void StopSuElapsedTimer() => StopElapsedTimer(ref _suStopwatch, ref _suElapsedTimer, SuElapsedText);

        private static string FormatElapsed(TimeSpan ts)
        {
            if (ts.TotalHours >= 1)
                return $"{(int)ts.TotalHours}:{ts.Minutes:D2}:{ts.Seconds:D2}";
            return $"{ts.Minutes:D2}:{ts.Seconds:D2}";
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

        // ── 清除一切缓存 (v1.5.0-Status) ────────────────────────────────

        /// <summary>
        /// 点击"清除"按钮 — 显示危险操作确认
        /// </summary>
        private void ClearAllCache_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (ClearCacheConfirmBar != null)
                    ClearCacheConfirmBar.IsOpen = true;
                if (ClearCacheConfirmButtons != null)
                    ClearCacheConfirmButtons.Visibility = Visibility.Visible;
            }
            catch (Exception ex)
            {
                Logger.Error("[ToolsPage] Show clear cache confirm failed", ex);
            }
        }

        /// <summary>
        /// 确认清除一切缓存
        /// </summary>
        private void ConfirmClearAllCache_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (ClearCacheConfirmBar != null)
                    ClearCacheConfirmBar.IsOpen = false;
                if (ClearCacheConfirmButtons != null)
                    ClearCacheConfirmButtons.Visibility = Visibility.Collapsed;

                string appDataDir = System.IO.Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "NotionFilesManagement");

                int deletedCount = 0;
                var errors = new System.Collections.Generic.List<string>();

                if (System.IO.Directory.Exists(appDataDir))
                {
                    // 清除子目录：background_cache、notices_cache、logs 等
                    foreach (var dir in System.IO.Directory.GetDirectories(appDataDir))
                    {
                        try
                        {
                            System.IO.Directory.Delete(dir, recursive: true);
                            deletedCount++;
                            Logger.Info($"[ToolsPage] Deleted cache dir: {dir}");
                        }
                        catch (Exception dirEx)
                        {
                            errors.Add($"{System.IO.Path.GetFileName(dir)}: {dirEx.Message}");
                            Logger.Warn($"[ToolsPage] Failed to delete dir {dir}: {dirEx.Message}");
                        }
                    }

                    // 清除文件：config.json、read_ids.json 等
                    foreach (var file in System.IO.Directory.GetFiles(appDataDir))
                    {
                        try
                        {
                            System.IO.File.Delete(file);
                            deletedCount++;
                            Logger.Info($"[ToolsPage] Deleted cache file: {file}");
                        }
                        catch (Exception fileEx)
                        {
                            errors.Add($"{System.IO.Path.GetFileName(file)}: {fileEx.Message}");
                            Logger.Warn($"[ToolsPage] Failed to delete file {file}: {fileEx.Message}");
                        }
                    }
                }

                if (errors.Count == 0)
                {
                    MessageBox.Show($"已成功清除所有缓存（{deletedCount} 项）。\n\n建议重启应用以使更改完全生效。",
                        "清除完成", MessageBoxButton.OK, MessageBoxImage.Information);
                }
                else
                {
                    MessageBox.Show($"已清除 {deletedCount} 项缓存，但有 {errors.Count} 项失败：\n\n{string.Join("\n", errors)}\n\n部分文件可能正在使用中，建议重启后再试。",
                        "部分清除", MessageBoxButton.OK, MessageBoxImage.Warning);
                }

                Logger.Info($"[ToolsPage] Clear all cache complete: {deletedCount} deleted, {errors.Count} errors");
            }
            catch (Exception ex)
            {
                Logger.Error("[ToolsPage] Clear all cache failed", ex);
                MessageBox.Show($"清除缓存失败：{ex.Message}", "错误", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// 取消清除缓存
        /// </summary>
        private void CancelClearAllCache_Click(object sender, RoutedEventArgs e)
        {
            if (ClearCacheConfirmBar != null)
                ClearCacheConfirmBar.IsOpen = false;
            if (ClearCacheConfirmButtons != null)
                ClearCacheConfirmButtons.Visibility = Visibility.Collapsed;
            Logger.Info("[ToolsPage] User cancelled clear all cache");
        }

        // =================================================================
        // Migration (v1.3.0-Status)
        // =================================================================

        private void HideAllMigrateSteps()
        {
            MigrateStep1.Visibility = Visibility.Collapsed;
            MigrateStep2.Visibility = Visibility.Collapsed;
            MigrateStep3.Visibility = Visibility.Collapsed;
            SuffixStep1.Visibility = Visibility.Collapsed;
            SuffixStep2.Visibility = Visibility.Collapsed;
        }

        private void HideAllSizeUpdateSteps()
        {
            SizeUpdateChoice.Visibility = Visibility.Collapsed;
            SizeUpdateStep1.Visibility = Visibility.Collapsed;
            SizeUpdateStep2.Visibility = Visibility.Collapsed;
            SizeUpdateStep3.Visibility = Visibility.Collapsed;
        }

        /// <summary>
        /// 隐藏所有模态步骤面板（包括 PageInfo / Migrate / Suffix / SizeUpdate）。
        /// 用于打开新模态前统一清理。
        /// </summary>
        private void HideAllModalSteps()
        {
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;
            HideAllMigrateSteps();
            HideAllSizeUpdateSteps();
        }

        private void OpenMigrateModal_Click(object sender, RoutedEventArgs e)
        {
            ModalOverlay.Visibility = Visibility.Visible;
            HideAllModalSteps();
            MigrateStep1.Visibility = Visibility.Visible;

            MigSourceIdInput.Text = "";
            MigTargetIdInput.Text = "";
            try { MigSourceIdError.Text = ""; } catch { }
            try { MigTargetIdError.Text = ""; } catch { }
        }

        private void MigSourceId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox tb)
                PageIdInputHelper.HandleTextChanged(tb, MigSourceIdError, ref _isFormattingMigSource);
        }

        private void MigTargetId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox tb)
                PageIdInputHelper.HandleTextChanged(tb, MigTargetIdError, ref _isFormattingMigTarget);
        }

        private async void MigFetchProperties_Click(object sender, RoutedEventArgs e)
        {
            // Validate both IDs
            if (!NotionPageId.TryNormalize(MigSourceIdInput.Text, out string srcId, out string srcErr))
            {
                try { MigSourceIdError.Text = srcErr; } catch { }
                MessageBox.Show("源数据源 ID：" + srcErr);
                return;
            }
            if (!NotionPageId.TryNormalize(MigTargetIdInput.Text, out string tgtId, out string tgtErr))
            {
                try { MigTargetIdError.Text = tgtErr; } catch { }
                MessageBox.Show("目标数据源 ID：" + tgtErr);
                return;
            }

            if (string.Equals(srcId, tgtId, StringComparison.OrdinalIgnoreCase))
            {
                MessageBox.Show("源和目标数据源 ID 不能相同。");
                return;
            }

            MigSourceIdInput.Text = srcId;
            MigTargetIdInput.Text = tgtId;

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnMigFetchProps.IsEnabled = false;
            try
            {
                _migCts?.Cancel();
                _migCts = new CancellationTokenSource();
                var token = _migCts.Token;

                // Fetch both schemas
                var srcResult = await _svc.GetDatabasePropertiesAsync(srcId, token);
                if (!string.Equals(srcResult.Status, "success", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("获取源数据源属性失败：" + srcResult.Error);
                    return;
                }

                var tgtResult = await _svc.GetDatabasePropertiesAsync(tgtId, token);
                if (!string.Equals(tgtResult.Status, "success", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("获取目标数据源属性失败：" + tgtResult.Error);
                    return;
                }

                _srcProperties = srcResult.Properties.ToList();
                _tgtProperties = tgtResult.Properties.ToList();

                Logger.Info($"Migration: src properties={_srcProperties.Count}, tgt properties={_tgtProperties.Count}");

                // Build mapping UI
                BuildMappingUI();

                // Show step 2
                MigrateStep1.Visibility = Visibility.Collapsed;
                MigrateStep2.Visibility = Visibility.Visible;
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("获取属性失败：" + ex.Message);
                Logger.Error("MigFetchProperties failed", ex);
            }
            finally
            {
                BtnMigFetchProps.IsEnabled = true;
            }
        }

        /// <summary>
        /// Readonly property types that cannot be written via Notion API.
        /// </summary>
        private static readonly HashSet<string> ReadonlyTypes = new(StringComparer.OrdinalIgnoreCase)
        {
            "rollup", "created_by", "created_time", "last_edited_by", "last_edited_time", "formula", "unique_id", "button"
        };

        private void BuildMappingUI()
        {
            MappingPanel.Children.Clear();
            _mappingCombos.Clear();

            if (_srcProperties == null || _tgtProperties == null) return;

            // Header row
            var header = new Grid { Margin = new Thickness(0, 0, 0, 8) };
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40, GridUnitType.Pixel) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var h1 = new TextBlock { Text = "源属性", FontWeight = FontWeights.SemiBold, Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush };
            Grid.SetColumn(h1, 0);
            header.Children.Add(h1);

            var arrow = new TextBlock { Text = "→", HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush };
            Grid.SetColumn(arrow, 1);
            header.Children.Add(arrow);

            var h2 = new TextBlock { Text = "目标属性", FontWeight = FontWeights.SemiBold, Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush };
            Grid.SetColumn(h2, 2);
            header.Children.Add(h2);

            MappingPanel.Children.Add(header);

            // Target property options for ComboBox
            var tgtOptions = new List<string> { "(不映射)" };
            foreach (var p in _tgtProperties)
            {
                tgtOptions.Add($"{p.Name} [{p.Type}]");
            }

            // Each source property row
            foreach (var srcProp in _srcProperties)
            {
                bool isReadonly = ReadonlyTypes.Contains(srcProp.Type);

                var row = new Grid { Margin = new Thickness(0, 2, 0, 2) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(40, GridUnitType.Pixel) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var label = new TextBlock
                {
                    Text = $"{srcProp.Name} [{srcProp.Type}]" + (isReadonly ? " (只读)" : ""),
                    VerticalAlignment = VerticalAlignment.Center,
                    Foreground = isReadonly
                        ? new System.Windows.Media.SolidColorBrush(System.Windows.Media.Color.FromArgb(128, 255, 255, 255))
                        : FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                };
                Grid.SetColumn(label, 0);
                row.Children.Add(label);

                var arrowTxt = new TextBlock { Text = "→", HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush };
                Grid.SetColumn(arrowTxt, 1);
                row.Children.Add(arrowTxt);

                var combo = new ComboBox
                {
                    ItemsSource = tgtOptions,
                    SelectedIndex = 0,
                    IsEnabled = !isReadonly,
                    Tag = srcProp.Name,
                    MinWidth = 180,
                };

                // Auto-match: try to find target property with same name
                if (!isReadonly)
                {
                    for (int i = 0; i < _tgtProperties.Count; i++)
                    {
                        if (string.Equals(_tgtProperties[i].Name, srcProp.Name, StringComparison.OrdinalIgnoreCase))
                        {
                            combo.SelectedIndex = i + 1; // +1 for "(不映射)"
                            break;
                        }
                    }
                }

                Grid.SetColumn(combo, 2);
                row.Children.Add(combo);
                _mappingCombos.Add(combo);

                MappingPanel.Children.Add(row);
            }
        }

        private void MigBackToStep1_Click(object sender, RoutedEventArgs e)
        {
            _migCts?.Cancel();
            MigrateStep2.Visibility = Visibility.Collapsed;
            MigrateStep1.Visibility = Visibility.Visible;
        }

        private async void MigStartMigration_Click(object sender, RoutedEventArgs e)
        {
            // Build property mapping from combo selections
            var mapping = new Dictionary<string, string>();
            var usedTargets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var combo in _mappingCombos)
            {
                if (combo.SelectedIndex <= 0) continue; // "(不映射)"

                string srcName = combo.Tag?.ToString() ?? "";
                int tgtIdx = combo.SelectedIndex - 1; // -1 for "(不映射)"
                if (_tgtProperties == null || tgtIdx < 0 || tgtIdx >= _tgtProperties.Count) continue;

                string tgtName = _tgtProperties[tgtIdx].Name;

                // Check for duplicate target mapping
                if (usedTargets.Contains(tgtName))
                {
                    MessageBox.Show($"目标属性「{tgtName}」被多次映射，请确保每个目标属性只映射一次。");
                    return;
                }

                usedTargets.Add(tgtName);
                mapping[srcName] = tgtName;
            }

            if (mapping.Count == 0)
            {
                MessageBox.Show("请至少选择一个属性映射。");
                return;
            }

            // Parse workers
            if (!int.TryParse(MigWorkersInput.Text?.Trim(), out int workers) || workers < 1 || workers > 16)
            {
                MessageBox.Show("并发线程数应为 1-16 的整数。");
                return;
            }

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            string srcId = MigSourceIdInput.Text?.Trim() ?? "";
            string tgtId = MigTargetIdInput.Text?.Trim() ?? "";

            BtnMigStart.IsEnabled = false;

            try
            {
                _migCts?.Cancel();
                _migCts = new CancellationTokenSource();
                var token = _migCts.Token;

                // Start migration
                string result = await _svc.StartMigrationAsync(srcId, tgtId, mapping, workers, token);

                if (result.StartsWith("Error", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("启动迁移失败：" + result);
                    return;
                }

                Logger.Info($"Migration started: {srcId} -> {tgtId}, mapping count={mapping.Count}, workers={workers}");

                // Show progress step
                MigrateStep2.Visibility = Visibility.Collapsed;
                MigrateStep3.Visibility = Visibility.Visible;
                MigProgressBar.Value = 0;
                MigProgressStatus.Text = "正在查询源数据源页面…";
                MigStatTotal.Text = "0";
                MigStatDone.Text = "0";
                MigStatFailed.Text = "0";
                MigErrorBorder.Visibility = Visibility.Collapsed;
                BtnMigCancel.IsEnabled = true;

                // Poll progress
                await PollMigrationProgress(token);
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("迁移失败：" + ex.Message);
                Logger.Error("MigStartMigration failed", ex);
            }
            finally
            {
                BtnMigStart.IsEnabled = true;
            }
        }

        private async Task PollMigrationProgress(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    var p = await _svc.GetMigrationProgressAsync(token);

                    MigProgressBar.Value = p.Percent;
                    MigStatTotal.Text = p.Total.ToString();
                    MigStatDone.Text = p.Done.ToString();
                    MigStatFailed.Text = p.Failed.ToString();

                    string statusText = p.Status switch
                    {
                        "querying" => "正在查询源数据源页面…",
                        "migrating" => $"迁移中 {p.Percent:0.0}%（{p.Done + p.Failed}/{p.Total}）",
                        "done" => "迁移完成！",
                        "cancelled" => "迁移已取消。",
                        "error" => "迁移出错。",
                        _ => p.Status,
                    };
                    MigProgressStatus.Text = statusText;

                    // Show errors
                    if (p.Errors.Count > 0)
                    {
                        MigErrorBorder.Visibility = Visibility.Visible;
                        MigErrorList.Text = string.Join("\n", p.Errors);
                    }

                    // Terminal states
                    if (p.Status is "done" or "cancelled" or "error")
                    {
                        BtnMigCancel.IsEnabled = false;
                        if (p.Status == "done")
                        {
                            MigProgressBar.Value = 100;
                        }
                        break;
                    }
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Error("PollMigrationProgress error", ex);
                }

                await Task.Delay(500, token);
            }
        }

        private async void MigCancel_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                BtnMigCancel.IsEnabled = false;
                await _svc.CancelMigrationAsync(CancellationToken.None);
                MigProgressStatus.Text = "迁移已取消。";
                Logger.Info("User cancelled migration");
            }
            catch (Exception ex)
            {
                MessageBox.Show("取消失败：" + ex.Message);
                Logger.Error("MigCancel failed", ex);
            }
        }

        // =================================================================
        // Batch Remove Suffix (v1.3.0-Status)
        // =================================================================

        private void OpenBatchSuffixModal_Click(object sender, RoutedEventArgs e)
        {
            ModalOverlay.Visibility = Visibility.Visible;
            HideAllModalSteps();
            SuffixStep1.Visibility = Visibility.Visible;

            SuffixDsIdInput.Text = "";
            SuffixInput.Text = "";
            SuffixWorkersInput.Text = "3";
            try { SuffixDsIdError.Text = ""; } catch { }
        }

        private void SuffixDsId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox tb)
                PageIdInputHelper.HandleTextChanged(tb, SuffixDsIdError, ref _isFormattingSuffixDsId);
        }

        private async void SuffixStart_Click(object sender, RoutedEventArgs e)
        {
            // Validate data source ID
            if (!NotionPageId.TryNormalize(SuffixDsIdInput.Text, out string dsId, out string dsErr))
            {
                try { SuffixDsIdError.Text = dsErr; } catch { }
                MessageBox.Show("数据源 ID：" + dsErr);
                return;
            }
            SuffixDsIdInput.Text = dsId;

            // Validate suffix
            string suffix = SuffixInput.Text ?? "";
            if (string.IsNullOrEmpty(suffix))
            {
                MessageBox.Show("请输入要去除的后缀。");
                return;
            }

            // Validate workers
            if (!int.TryParse(SuffixWorkersInput.Text?.Trim(), out int workers) || workers < 1 || workers > 16)
            {
                MessageBox.Show("并发线程数应为 1-16 的整数。");
                return;
            }

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnSuffixStart.IsEnabled = false;

            try
            {
                _suffixCts?.Cancel();
                _suffixCts = new CancellationTokenSource();
                var token = _suffixCts.Token;

                // Start task
                string result = await _svc.StartBatchRemoveSuffixAsync(dsId, suffix, workers, token);

                if (result.StartsWith("Error", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("启动失败：" + result);
                    return;
                }

                Logger.Info($"BatchRemoveSuffix started: ds={dsId}, suffix='{suffix}', workers={workers}");

                // Show progress step
                SuffixStep1.Visibility = Visibility.Collapsed;
                SuffixStep2.Visibility = Visibility.Visible;
                SuffixProgressBar.Value = 0;
                SuffixProgressStatus.Text = "正在查询数据源页面…";
                SuffixStatScanned.Text = "0";
                SuffixStatTotal.Text = "0";
                SuffixStatDone.Text = "0";
                SuffixStatFailed.Text = "0";
                SuffixErrorBorder.Visibility = Visibility.Collapsed;
                BtnSuffixCancel.IsEnabled = true;

                // Poll progress
                await PollSuffixProgress(token);
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("操作失败：" + ex.Message);
                Logger.Error("SuffixStart failed", ex);
            }
            finally
            {
                BtnSuffixStart.IsEnabled = true;
            }
        }

        private async Task PollSuffixProgress(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    var p = await _svc.GetBatchRemoveSuffixProgressAsync(token);

                    SuffixProgressBar.Value = p.Percent;
                    SuffixStatScanned.Text = p.Scanned.ToString();
                    SuffixStatTotal.Text = p.Total.ToString();
                    SuffixStatDone.Text = p.Done.ToString();
                    SuffixStatFailed.Text = p.Failed.ToString();

                    string statusText = p.Status switch
                    {
                        "querying" => "正在查询数据源页面…",
                        "processing" => $"处理中 {p.Percent:0.0}%（{p.Done + p.Failed}/{p.Total}）",
                        "done" => p.Total == 0
                            ? $"扫描完成，共 {p.Scanned} 个页面，无匹配后缀。"
                            : $"完成！成功 {p.Done}，失败 {p.Failed}，跳过 {p.Skipped}。",
                        "cancelled" => "已取消。",
                        "error" => "出错。",
                        _ => p.Status,
                    };
                    SuffixProgressStatus.Text = statusText;

                    // Show errors
                    if (p.Errors.Count > 0)
                    {
                        SuffixErrorBorder.Visibility = Visibility.Visible;
                        SuffixErrorList.Text = string.Join("\n", p.Errors);
                    }

                    // Terminal states
                    if (p.Status is "done" or "cancelled" or "error")
                    {
                        BtnSuffixCancel.IsEnabled = false;
                        if (p.Status == "done")
                        {
                            SuffixProgressBar.Value = 100;
                        }
                        break;
                    }
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Error("PollSuffixProgress error", ex);
                }

                await Task.Delay(500, token);
            }
        }

        private async void SuffixCancel_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                BtnSuffixCancel.IsEnabled = false;
                await _svc.CancelBatchRemoveSuffixAsync(CancellationToken.None);
                SuffixProgressStatus.Text = "已取消。";
                Logger.Info("User cancelled batch remove suffix");
            }
            catch (Exception ex)
            {
                MessageBox.Show("取消失败：" + ex.Message);
                Logger.Error("SuffixCancel failed", ex);
            }
        }

        // =================================================================
        // Page Size Auto-Update (v1.4.0-Status)
        // =================================================================

        private void SuDsId_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (sender is TextBox tb)
                PageIdInputHelper.HandleTextChanged(tb, SuDsIdError, ref _isFormattingSuDsId);
        }

        private void OpenSizeUpdateStep1()
        {
            ModalOverlay.Visibility = Visibility.Visible;
            HideAllModalSteps();
            SizeUpdateStep1.Visibility = Visibility.Visible;

            SuDsIdInput.Text = "";
            SuSizePropCombo.ItemsSource = null;
            SuSizePropCombo.Items.Clear();
            try { SuDsIdError.Text = ""; } catch { }
        }

        private async void SuFetchProperties_Click(object sender, RoutedEventArgs e)
        {
            if (!NotionPageId.TryNormalize(SuDsIdInput.Text, out string dsId, out string dsErr))
            {
                try { SuDsIdError.Text = dsErr; } catch { }
                MessageBox.Show("数据源 ID：" + dsErr);
                return;
            }
            SuDsIdInput.Text = dsId;

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnSuFetchProps.IsEnabled = false;
            try
            {
                _suCts?.Cancel();
                _suCts = new CancellationTokenSource();
                var token = _suCts.Token;

                var result = await _svc.GetDatabasePropertiesAsync(dsId, token);
                if (!string.Equals(result.Status, "success", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("获取数据源属性失败：" + result.Error);
                    return;
                }

                _suProperties = result.Properties.ToList();

                // Filter for number type properties only
                var numberProps = _suProperties.Where(p =>
                    string.Equals(p.Type, "number", StringComparison.OrdinalIgnoreCase)).ToList();

                if (numberProps.Count == 0)
                {
                    MessageBox.Show("该数据源没有数字 (number) 类型的属性。\n请先在 Notion 中为数据源添加一个数字属性用于存储大小。");
                    return;
                }

                var items = numberProps.Select(p => $"{p.Name} [number]").ToList();
                SuSizePropCombo.ItemsSource = items;
                SuSizePropCombo.SelectedIndex = 0;

                Logger.Info($"SizeUpdate: fetched {_suProperties.Count} properties, {numberProps.Count} number props");
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("获取属性失败：" + ex.Message);
                Logger.Error("SuFetchProperties failed", ex);
            }
            finally
            {
                BtnSuFetchProps.IsEnabled = true;
            }
        }

        private async void SuNextToPageSelection_Click(object sender, RoutedEventArgs e)
        {
            // Validate
            if (!NotionPageId.TryNormalize(SuDsIdInput.Text, out string dsId, out string dsErr))
            {
                try { SuDsIdError.Text = dsErr; } catch { }
                MessageBox.Show("数据源 ID：" + dsErr);
                return;
            }

            if (SuSizePropCombo.SelectedItem == null)
            {
                MessageBox.Show("请先获取属性并选择大小属性。");
                return;
            }

            // Extract property name from "PropName [number]"
            string selectedText = SuSizePropCombo.SelectedItem.ToString() ?? "";
            string sizePropName = selectedText.Contains(" [")
                ? selectedText[..selectedText.LastIndexOf(" [")]
                : selectedText;

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnSuNext1.IsEnabled = false;
            try
            {
                _suCts?.Cancel();
                _suCts = new CancellationTokenSource();
                var token = _suCts.Token;

                // Scan pages
                var result = await _svc.ScanDataSourcePagesAsync(dsId, sizePropName, token);
                if (!string.Equals(result.Status, "success", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("扫描页面失败：" + result.Error);
                    return;
                }

                _suPagesWithoutSize = result.PagesWithoutSize.ToList();
                _suPagesWithSize = result.PagesWithSize.ToList();

                // Build page selection UI
                BuildPageSelectionUI();

                // Show step 2
                SizeUpdateStep1.Visibility = Visibility.Collapsed;
                SizeUpdateStep2.Visibility = Visibility.Visible;

                SuPageCountHint.Text = $"共 {result.Total} 个页面（未设置 {_suPagesWithoutSize.Count}，已设置 {_suPagesWithSize.Count}）";

                Logger.Info($"SizeUpdate: scanned {result.Total} pages, without={_suPagesWithoutSize.Count}, with={_suPagesWithSize.Count}");
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("扫描页面失败：" + ex.Message);
                Logger.Error("SuNextToPageSelection failed", ex);
            }
            finally
            {
                BtnSuNext1.IsEnabled = true;
            }
        }

        private void BuildPageSelectionUI()
        {
            _suEmptyCheckboxes.Clear();
            _suSetCheckboxes.Clear();
            SuEmptyPagesPanel.Children.Clear();
            SuSetPagesPanel.Children.Clear();

            SuEmptyHeader.Text = $"未设置大小 ({_suPagesWithoutSize.Count})";
            SuSetHeader.Text = $"已设置大小 ({_suPagesWithSize.Count})";

            // Empty pages (default selected)
            foreach (var page in _suPagesWithoutSize)
            {
                var cb = new CheckBox
                {
                    Content = $"{page.Title}",
                    Tag = page.Id,
                    IsChecked = true,
                    Margin = new Thickness(0, 1, 0, 1),
                    Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush,
                };
                _suEmptyCheckboxes.Add(cb);
                SuEmptyPagesPanel.Children.Add(cb);
            }

            // Set pages (default NOT selected)
            foreach (var page in _suPagesWithSize)
            {
                var cb = new CheckBox
                {
                    Content = $"{page.Title}  ({page.SizeValue:0.###} GB)",
                    Tag = page.Id,
                    IsChecked = false,
                    Margin = new Thickness(0, 1, 0, 1),
                    Foreground = FindResource("TextFillColorPrimaryBrush") as System.Windows.Media.Brush,
                };
                _suSetCheckboxes.Add(cb);
                SuSetPagesPanel.Children.Add(cb);
            }
        }

        private void SuSelectAllEmpty_Click(object sender, RoutedEventArgs e)
        {
            foreach (var cb in _suEmptyCheckboxes) cb.IsChecked = true;
        }

        private void SuDeselectAllEmpty_Click(object sender, RoutedEventArgs e)
        {
            foreach (var cb in _suEmptyCheckboxes) cb.IsChecked = !cb.IsChecked;
        }

        private void SuSelectAllSet_Click(object sender, RoutedEventArgs e)
        {
            foreach (var cb in _suSetCheckboxes) cb.IsChecked = true;
        }

        private void SuDeselectAllSet_Click(object sender, RoutedEventArgs e)
        {
            foreach (var cb in _suSetCheckboxes) cb.IsChecked = !cb.IsChecked;
        }

        private void SuBackToStep1_Click(object sender, RoutedEventArgs e)
        {
            _suCts?.Cancel();
            SizeUpdateStep2.Visibility = Visibility.Collapsed;
            SizeUpdateStep1.Visibility = Visibility.Visible;
        }

        private async void SuStartUpdate_Click(object sender, RoutedEventArgs e)
        {
            // Collect selected page IDs
            var selectedIds = new List<string>();
            foreach (var cb in _suEmptyCheckboxes)
            {
                if (cb.IsChecked == true && cb.Tag is string id)
                    selectedIds.Add(id);
            }
            foreach (var cb in _suSetCheckboxes)
            {
                if (cb.IsChecked == true && cb.Tag is string id)
                    selectedIds.Add(id);
            }

            if (selectedIds.Count == 0)
            {
                MessageBox.Show("请至少选择一个页面。");
                return;
            }

            // Validate thread counts
            if (!int.TryParse(SuLinkWorkersInput.Text?.Trim(), out int linkWorkers) || linkWorkers < 1 || linkWorkers > 8)
            {
                MessageBox.Show("链接查询线程数应为 1-8 的整数。");
                return;
            }
            if (!int.TryParse(SuSizeWorkersInput.Text?.Trim(), out int sizeWorkers) || sizeWorkers < 1 || sizeWorkers > 16)
            {
                MessageBox.Show("大小查询线程数应为 1-16 的整数。");
                return;
            }

            // Get property name
            string selectedText = SuSizePropCombo.SelectedItem?.ToString() ?? "";
            string sizePropName = selectedText.Contains(" [")
                ? selectedText[..selectedText.LastIndexOf(" [")]
                : selectedText;

            if (!NotionPageId.TryNormalize(SuDsIdInput.Text, out string dsId, out _))
            {
                MessageBox.Show("数据源 ID 无效。");
                return;
            }

            var (ok, err) = await _svc.EnsureBackendReadyFromConfigAsync();
            if (!ok)
            {
                MessageBox.Show(err);
                return;
            }

            BtnSuStartUpdate.IsEnabled = false;

            try
            {
                _suCts?.Cancel();
                _suCts = new CancellationTokenSource();
                var token = _suCts.Token;

                // Start update task
                string result = await _svc.StartPageSizeUpdateAsync(
                    dsId, sizePropName, selectedIds, linkWorkers, sizeWorkers, token);

                if (result.StartsWith("Error", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("启动失败：" + result);
                    return;
                }

                Logger.Info($"PageSizeUpdate started: ds={dsId}, prop={sizePropName}, pages={selectedIds.Count}, linkW={linkWorkers}, sizeW={sizeWorkers}");

                // Show progress step
                SizeUpdateStep2.Visibility = Visibility.Collapsed;
                SizeUpdateStep3.Visibility = Visibility.Visible;
                SuProgressBar.Value = 0;
                SuProgressStatus.Text = "正在扫描页面文件链接…";
                SuElapsedText.Text = "";
                SuStatTotal.Text = selectedIds.Count.ToString();
                SuStatLinkQueried.Text = "0";
                SuStatUpdated.Text = "0";
                SuStatFailed.Text = "0";
                SuStatFilesDiscovered.Text = "0";
                SuStatFilesProbed.Text = "0";
                SuErrorBorder.Visibility = Visibility.Collapsed;
                BtnSuCancel.IsEnabled = true;

                // Start elapsed timer
                StartSuElapsedTimer();

                // Poll progress
                await PollSizeUpdateProgress(token);
            }
            catch (OperationCanceledException) { }
            catch (Exception ex)
            {
                MessageBox.Show("操作失败：" + ex.Message);
                Logger.Error("SuStartUpdate failed", ex);
            }
            finally
            {
                BtnSuStartUpdate.IsEnabled = true;
            }
        }

        private async Task PollSizeUpdateProgress(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    var p = await _svc.GetPageSizeUpdateProgressAsync(token);

                    SuProgressBar.Value = p.Percent;
                    SuStatTotal.Text = p.Total.ToString();
                    SuStatLinkQueried.Text = p.LinkQueried.ToString();
                    SuStatUpdated.Text = p.SizeUpdated.ToString();
                    SuStatFailed.Text = p.Failed.ToString();
                    SuStatFilesDiscovered.Text = p.FilesDiscovered.ToString();
                    SuStatFilesProbed.Text = p.FilesProbed.ToString();

                    string statusText = p.Status switch
                    {
                        "scanning" when p.FilesDiscovered > 0 =>
                            $"扫描中…（页面 {p.LinkQueried}/{p.Total}，文件 {p.FilesProbed}/{p.FilesDiscovered} 已探测）",
                        "scanning" =>
                            $"扫描页面文件链接中…（{p.LinkQueried}/{p.Total}）",
                        "updating" =>
                            $"更新中 {p.Percent:0.0}%（已更新 {p.SizeUpdated}，文件 {p.FilesProbed}/{p.FilesDiscovered}）",
                        "done" =>
                            $"完成！已更新 {p.SizeUpdated}，失败 {p.Failed}（共探测 {p.FilesProbed} 个文件）。",
                        "cancelled" => "已取消。",
                        "error" => "出错。",
                        _ => p.Status,
                    };
                    SuProgressStatus.Text = statusText;

                    // Show errors
                    if (p.Errors.Count > 0)
                    {
                        SuErrorBorder.Visibility = Visibility.Visible;
                        SuErrorList.Text = string.Join("\n", p.Errors);
                    }

                    // Terminal states
                    if (p.Status is "done" or "cancelled" or "error")
                    {
                        BtnSuCancel.IsEnabled = false;
                        StopSuElapsedTimer();
                        if (p.Status == "done")
                        {
                            SuProgressBar.Value = 100;
                        }
                        break;
                    }
                }
                catch (OperationCanceledException)
                {
                    StopSuElapsedTimer();
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Error("PollSizeUpdateProgress error", ex);
                }

                await Task.Delay(500, token);
            }
        }

        private async void SuCancel_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                BtnSuCancel.IsEnabled = false;
                StopSuElapsedTimer();
                await _svc.CancelPageSizeUpdateAsync(CancellationToken.None);
                SuProgressStatus.Text = "已取消。";
                Logger.Info("User cancelled page size update");
            }
            catch (Exception ex)
            {
                MessageBox.Show("取消失败：" + ex.Message);
                Logger.Error("SuCancel failed", ex);
            }
        }
    }
}
