using System;
using System.Collections.Generic;
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
            HideAllMigrateSteps();
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
            _migCts?.Cancel();
            _suffixCts?.Cancel();
            ModalOverlay.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;
            HideAllMigrateSteps();
        }

        private void BackToStep1_Click(object sender, RoutedEventArgs e)
        {
            _cts?.Cancel();
            ModalStep2.Visibility = Visibility.Collapsed;
            ModalStep1.Visibility = Visibility.Visible;
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

        private void OpenMigrateModal_Click(object sender, RoutedEventArgs e)
        {
            ModalOverlay.Visibility = Visibility.Visible;
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;
            HideAllMigrateSteps();
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
            ModalStep1.Visibility = Visibility.Collapsed;
            ModalStep2.Visibility = Visibility.Collapsed;
            HideAllMigrateSteps();
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
    }
}
