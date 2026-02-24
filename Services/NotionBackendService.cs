using Python.Runtime;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Notion_Files_Management.Models;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Services
{
    /// <summary>
    /// High-level C# facade for python backend.
    /// Keeps pages thin and avoids duplicated pythonnet glue code.
    /// </summary>
    public sealed class NotionBackendService
    {
        public static NotionBackendService Instance { get; } = new NotionBackendService();

        private readonly PythonBackendHost _backend = PythonBackendHost.Instance;

        private NotionBackendService() { }

        public bool IsReady => _backend.IsReady;

        public sealed record ProbeProgress(string Status, double Percent, int Done, int Total, string Error, string RawRepr);

        public sealed record DownloadListFetchResult(
            int ProbeId,
            int Total,
            string Status,
            string Msg,
            IReadOnlyList<FileSelectItem> Items);

        /// <summary>
        /// 流式扫描状态（v1.5.2-Status）
        /// </summary>
        public sealed record ScanStatus(string Status, int Discovered, bool Done, string? Error, int ProbeId, int TotalUrls, int FilesProbed, bool ProbingDone);

        /// <summary>
        /// Ensure python backend is initialized using persisted user config.
        /// </summary>
        public async Task<(bool ok, string error)> EnsureBackendReadyFromConfigAsync()
        {
            try
            {
                ConfigManager.Load();
                string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";
                string url = (ConfigManager.Current?.NotionBaseUrl ?? "https://api.notion.com/v1").Trim().TrimEnd('/');
                int dl = ConfigManager.Current?.MaxDownloadWorkers ?? 3;
                int ul = ConfigManager.Current?.MaxUploadWorkers ?? 3;

                if (string.IsNullOrWhiteSpace(token))
                    return (false, "未检测到 Notion Token，请先到【设置】页保存 Token。");

                await _backend.EnsureBackendReady(token, dl, ul, url);
                return (true, "");
            }
            catch (Exception ex)
            {
                Logger.Error("EnsureBackendReadyFromConfigAsync failed", ex);
                return (false, "初始化失败: " + ex.Message);
            }
        }

        public async Task<(int probeId, int total, string status, string msg)> StartDownloadListProbeAsync(string pageId, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_download_list"))
                {
                    dynamic ret = pyMain.get_download_list(pageId);

                    int pid = 0;
                    int tot = 0;
                    string m = "";
                    string st = "";
                    try { pid = PyConvert.ToInt(ret["probe_id"], 0); } catch { }
                    try { tot = PyConvert.ToInt(ret["total"], 0); } catch { }
                    try { m = ret["msg"]?.ToString() ?? ""; } catch { }
                    try { st = ret["status"]?.ToString() ?? ""; } catch { }

                    return (pid, tot, st, m);
                }
            }, token);
        }

        /// <summary>
        /// 取消下载列表的大小探测任务（前端点击"取消"时调用）。
        /// </summary>
        public async Task CancelDownloadListProbeAsync()
        {
            try
            {
                await _backend.RunPython(py =>
                {
                    dynamic pyMain = py;
                    pyMain.cancel_download_list_probe();
                    return 0;
                });
            }
            catch (Exception ex)
            {
                Logger.Warn($"CancelDownloadListProbeAsync failed (non-fatal): {ex.Message}");
            }
        }

        /// <summary>
        /// 启动流式扫描（v1.5.1-Status.6）：后台线程递归扫描页面，即时追加文件到 download_list。
        /// </summary>
        public async Task<(string status, string msg)> StartDownloadListStreamingAsync(string pageId, int probeWorkers, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.start_download_list_streaming"))
                {
                    dynamic ret = pyMain.start_download_list_streaming(pageId, probeWorkers);
                    string st = ret["status"]?.ToString() ?? "";
                    string m = ret["msg"]?.ToString() ?? "";
                    return (st, m);
                }
            }, token);
        }

        /// <summary>
        /// 取消流式扫描和探测（v1.5.2-Status）
        /// </summary>
        public async Task CancelDownloadListStreamingAsync(CancellationToken token)
        {
            await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                pyMain.cancel_download_list_streaming();
                return true;
            }, token);
        }

        /// <summary>
        /// 获取流式扫描状态（v1.5.1-Status.6）
        /// </summary>
        public async Task<ScanStatus> GetDownloadListScanStatusAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_download_list_scan_status"))
                {
                    dynamic ret = pyMain.get_download_list_scan_status();
                    string st = ret["status"]?.ToString() ?? "";
                    int disc = PyConvert.ToInt(ret["discovered"], 0);
                    bool done = false;
                    try
                    {
                        var d = ret["done"];
                        if (d != null) done = d.ToString().Equals("True", StringComparison.OrdinalIgnoreCase);
                    }
                    catch { }
                    string? err = null;
                    try
                    {
                        var e = ret["error"];
                        if (e != null)
                        {
                            var s = e.ToString();
                            if (!string.IsNullOrWhiteSpace(s) && !string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                                err = s;
                        }
                    }
                    catch { }
                    int pid = 0;
                    try
                    {
                        var p = ret["probe_id"];
                        if (p != null && !string.Equals(p.ToString(), "None", StringComparison.OrdinalIgnoreCase))
                            pid = PyConvert.ToInt(p, 0);
                    }
                    catch { }
                    int tu = PyConvert.ToInt(ret["total_urls"], 0);
                    int fp = 0;
                    try { fp = PyConvert.ToInt(ret["files_probed"], 0); } catch { }
                    bool probingDone = false;
                    try
                    {
                        var pd = ret["probing_done"];
                        if (pd != null) probingDone = pd.ToString().Equals("True", StringComparison.OrdinalIgnoreCase);
                    }
                    catch { }
                    return new ScanStatus(st, disc, done, err, pid, tu, fp, probingDone);
                }
            }, token);
        }

        public async Task<ProbeProgress> GetDownloadListProbeProgressAsync(int probeId, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.download_list_processing"))
                {
                    dynamic prog = pyMain.download_list_processing(probeId);

                    string st = prog["status"]?.ToString() ?? "";
                    double pct = 0.0;
                    int dn = 0;
                    int tt = 0;
                    try { pct = PyConvert.ToDouble(prog["percent"], 0.0); } catch { }
                    try { dn = PyConvert.ToInt(prog["done"], 0); } catch { }
                    try { tt = PyConvert.ToInt(prog["total"], 0); } catch { }

                    string errText = "";
                    try
                    {
                        // backend returns dict or None; keep string form for UI/log.
                        var eobj = prog["error"];
                        if (eobj != null)
                        {
                            var s = eobj.ToString();
                            if (!string.IsNullOrWhiteSpace(s) && !string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                                errText = s;
                        }
                    }
                    catch { }

                    string raw = "";
                    try { raw = ((PyObject)prog).Repr()?.ToString() ?? ""; } catch { }

                    return new ProbeProgress(st, pct, dn, tt, errText, raw);
                }
            }, token);
        }

        public async Task<IReadOnlyList<FileSelectItem>> ReadDownloadListAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Read main.download_list"))
                {
                    var result = new List<FileSelectItem>();
                    dynamic pyList = pyMain.download_list;
                    foreach (var item in pyList)
                    {
                        if (!PythonHelpers.IsPyMapping(item))
                        {
                            string repr = "";
                            try { repr = item?.ToString() ?? ""; } catch { }
                            throw new Exception($"main.download_list 的元素不是 dict（mapping），实际={item?.GetPythonType()?.ToString() ?? "unknown"}，值={repr}");
                        }

                        string url = "";
                        string name = "";
                        string realName = "";
                        string? expiry = null;
                        double size = 0.0;
                        string blockId = "";
                        string? createdTime = null;

                        try { url = item["url"]?.ToString() ?? ""; } catch { }
                        try { name = item["name"]?.ToString() ?? ""; } catch { }
                        try { realName = item["real_name"]?.ToString() ?? ""; } catch { }
                        try
                        {
                            var ex = item["expiry_time"];
                            expiry = ex == null ? null : ex.ToString();
                            if (string.Equals(expiry, "None", StringComparison.OrdinalIgnoreCase))
                                expiry = null;
                        }
                        catch { }
                        try { size = PyConvert.ToDouble(item["size_mb"], 0.0); } catch { }
                        try { blockId = item["block_id"]?.ToString() ?? ""; } catch { }
                        string blockType = "file";
                        try { blockType = item["block_type"]?.ToString() ?? "file"; } catch { }
                        try
                        {
                            var ct = item["created_time"];
                            createdTime = ct == null ? null : ct.ToString();
                            if (string.Equals(createdTime, "None", StringComparison.OrdinalIgnoreCase))
                                createdTime = null;
                        }
                        catch { }

                        result.Add(new FileSelectItem
                        {
                            url = url,
                            name = name,
                            real_name = realName,
                            expiry_time = expiry,
                            size_mb = size,
                            block_id = blockId,
                            block_type = blockType,
                            created_time = createdTime,
                            IsSelected = true
                        });
                    }
                    return result;
                }
            }, token);
        }

        /// <summary>
        /// One-shot: trigger get_download_list + poll download_list_processing until done, then read main.download_list.
        /// </summary>
        public async Task<DownloadListFetchResult> FetchDownloadListWithProbeAsync(
            string pageId,
            IProgress<ProbeProgress>? progress,
            CancellationToken token)
        {
            var (probeId, total, status, msg) = await StartDownloadListProbeAsync(pageId, token);
            Logger.Info($"get_download_list => status={status}, total={total}, probe_id={probeId}, msg={msg}");

            if (probeId <= 0)
            {
                // No files or backend decided not to start probe.
                return new DownloadListFetchResult(probeId, total, status, msg, Array.Empty<FileSelectItem>());
            }

            // 文件列表已获取，立即报告一次初始进度，让 UI 从"查询列表"切换到"探测中"
            progress?.Report(new ProbeProgress("probing", 0.0, 0, total, "", ""));

            // Give backend a short time to register probe.
            await Task.Delay(200, token);

            var sw = Stopwatch.StartNew();
            while (true)
            {
                token.ThrowIfCancellationRequested();

                var p = await GetDownloadListProbeProgressAsync(probeId, token);
                progress?.Report(p);

                if (string.Equals(p.Status, "done", StringComparison.OrdinalIgnoreCase))
                    break;

                if (string.Equals(p.Status, "not_found", StringComparison.OrdinalIgnoreCase))
                {
                    // Backoff a little, and fail fast if backend never registered the probe.
                    if (sw.Elapsed.TotalSeconds > 5)
                        throw new Exception("Probe task not found after 5s (backend returned status=not_found).");
                    await Task.Delay(250, token);
                    continue;
                }

                if (string.Equals(p.Status, "error", StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(p.Status, "failed", StringComparison.OrdinalIgnoreCase))
                {
                    throw new Exception(string.IsNullOrWhiteSpace(p.Error) ? "Probe failed" : p.Error);
                }

                await Task.Delay(350, token);
            }

            var items = await ReadDownloadListAsync(token);
            return new DownloadListFetchResult(probeId, total, status, msg, items);
        }

        public async Task<string> StartDownloadAsync(IEnumerable<FileSelectItem> files, string saveDirectory, CancellationToken token)
        {
            var list = files?.ToList() ?? new List<FileSelectItem>();
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.download_notion_files"))
                {
                    using var pyListToDownload = new PyList();

                    foreach (var f in list)
                    {
                        using var d = new PyDict();

                        using (var k = "url".ToPython())
                        using (var v = (f.url ?? "").ToPython())
                            d.SetItem(k, v);

                        using (var k = "real_name".ToPython())
                        using (var v = (f.real_name ?? "").ToPython())
                            d.SetItem(k, v);

                        if (!string.IsNullOrWhiteSpace(f.name))
                        {
                            using var k = "name".ToPython();
                            using var v = (f.name ?? "").ToPython();
                            d.SetItem(k, v);
                        }

                        if (!string.IsNullOrWhiteSpace(f.expiry_time))
                        {
                            using var k = "expiry_time".ToPython();
                            using var v = (f.expiry_time ?? "").ToPython();
                            d.SetItem(k, v);
                        }

                        using (var k = "size_mb".ToPython())
                        using (var v = f.size_mb.ToPython())
                            d.SetItem(k, v);

                        if (!string.IsNullOrWhiteSpace(f.block_id))
                        {
                            using var k = "block_id".ToPython();
                            using var v = (f.block_id ?? "").ToPython();
                            d.SetItem(k, v);
                        }

                        if (!string.IsNullOrWhiteSpace(f.created_time))
                        {
                            using var k = "created_time".ToPython();
                            using var v = (f.created_time ?? "").ToPython();
                            d.SetItem(k, v);
                        }

                        pyListToDownload.Append(d);
                    }

                    var r = pyMain.download_notion_files(pyListToDownload, saveDirectory);
                    return r?.ToString() ?? "";
                }
            }, token);
        }

        public async Task<List<DownloadTaskStatus>> GetDownloadStatusesAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_download_statuses"))
                {
                    dynamic pyStatuses = pyMain.get_download_statuses();
                    var result = new List<DownloadTaskStatus>();

                    foreach (var s in pyStatuses)
                    {
                        result.Add(new DownloadTaskStatus
                        {
                            url = s["url"]?.ToString(),
                            name = s["name"]?.ToString(),
                            real_name = s["real_name"]?.ToString(),
                            status = s["status"]?.ToString() ?? "",
                            progress = PythonHelpers.ToDoubleSafe(s, "progress"),
                            downloaded_mb = PythonHelpers.ToDoubleSafe(s, "downloaded_mb"),
                            total_mb = PythonHelpers.ToDoubleSafe(s, "total_mb"),
                            speed_mb_s = PythonHelpers.ToDoubleSafe(s, "speed_mb_s"),
                            ETA = PythonHelpers.ToIntSafe(s, "ETA"),
                            error = PythonHelpers.NormalizePythonNone(s, "error"),
                            created_time = PythonHelpers.NormalizePythonNone(s, "created_time"),
                        });
                    }

                    return result;
                }
            }, token);
        }

        public async Task<string> StartUploadAsync(string pageId, IEnumerable<string> filePaths, CancellationToken token)
        {
            var files = filePaths?.ToList() ?? new List<string>();
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.upload_notion_files"))
                {
                    using var pyFiles = new PyList();
                    foreach (var path in files)
                        pyFiles.Append((path ?? string.Empty).ToPython());

                    var r = pyMain.upload_notion_files(pageId, pyFiles);
                    return r?.ToString() ?? "";
                }
            }, token);
        }

        /// <summary>
        /// 上传整个文件夹到 Notion 页面。子文件夹会创建子页面。
        /// 返回 (filesQueued, pagesCreated, failed, message)。
        /// </summary>
        public async Task<(int files, int pages, int failed, string msg)> UploadFolderAsync(
            string pageId, string folderPath, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.upload_folder"))
                {
                    dynamic r = pyMain.upload_folder(pageId, folderPath);
                    int files = 0, pages = 0, failed = 0;
                    string msg = "";
                    try { files = PyConvert.ToInt(r["files"], 0); } catch { }
                    try { pages = PyConvert.ToInt(r["pages_created"], 0); } catch { }
                    try { failed = PyConvert.ToInt(r["failed"], 0); } catch { }
                    try { msg = r["msg"]?.ToString() ?? ""; } catch { }
                    return (files, pages, failed, msg);
                }
            }, token);
        }

        public async Task<List<UploadStatusDto>> GetUploadStatusesAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_upload_statuses"))
                {
                    dynamic pyStatuses = pyMain.get_upload_statuses();
                    var list = new List<UploadStatusDto>();
                    foreach (var s in pyStatuses)
                    {
                        list.Add(new UploadStatusDto
                        {
                            FilePath = s["file_path"]?.ToString() ?? "",
                            Status = s["status"]?.ToString() ?? "",
                            Stage = s["stage"]?.ToString() ?? "",
                            Progress = PythonHelpers.ToDoubleSafe(s, "progress"),
                            UploadedMB = PythonHelpers.ToDoubleSafe(s, "uploaded_mb"),
                            TotalMB = PythonHelpers.ToDoubleSafe(s, "total_mb"),
                            Speed = PythonHelpers.ToDoubleSafe(s, "speed_mb_s"),
                            ETA = PythonHelpers.ToIntSafe(s, "ETA"),
                            Error = PythonHelpers.NormalizePythonNone(s, "error")
                        });
                    }
                    return list;
                }
            }, token);
        }

        // ===================================================================
        // Migration (v1.3.0-Status)
        // ===================================================================

        /// <summary>
        /// Retrieve data source property schema (uses Data Sources API 2025-09-03).
        /// Returns: (status, title, properties dict as List of (name, type), error)
        /// </summary>
        public sealed record DataSourcePropertyInfo(string Name, string Type);

        public sealed record DataSourcePropertiesResult(
            string Status,
            string DataSourceId,
            string Title,
            IReadOnlyList<DataSourcePropertyInfo> Properties,
            string Error);

        public async Task<DataSourcePropertiesResult> GetDatabasePropertiesAsync(string dataSourceId, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_database_properties"))
                {
                    dynamic ret = pyMain.get_database_properties(dataSourceId);

                    string status = ret["status"]?.ToString() ?? "error";
                    string dsId = ret["data_source_id"]?.ToString() ?? "";
                    string title = ret["title"]?.ToString() ?? "";
                    string error = "";
                    try { error = ret["error"]?.ToString() ?? ""; } catch { }
                    if (string.Equals(error, "None", StringComparison.OrdinalIgnoreCase)) error = "";

                    var props = new List<DataSourcePropertyInfo>();
                    try
                    {
                        dynamic pyProps = ret["properties"];
                        dynamic builtins = Py.Import("builtins");
                        dynamic keys = builtins.list(pyProps.keys());
                        int count = (int)builtins.len(keys);
                        for (int i = 0; i < count; i++)
                        {
                            string name = keys[i]?.ToString() ?? "";
                            string type = pyProps[keys[i]]["type"]?.ToString() ?? "unknown";
                            props.Add(new DataSourcePropertyInfo(name, type));
                        }
                    }
                    catch (Exception ex)
                    {
                        Logger.Warn($"GetDatabasePropertiesAsync: parse properties failed: {ex.Message}");
                    }

                    return new DataSourcePropertiesResult(status, dsId, title, props, error);
                }
            }, token);
        }

        /// <summary>
        /// Migration progress data.
        /// </summary>
        public sealed record MigrationProgress(
            string Status, int Total, int Done, int Failed, double Percent, IReadOnlyList<string> Errors);

        public async Task<string> StartMigrationAsync(
            string sourceId, string targetId,
            Dictionary<string, string> propertyMapping,
            int maxWorkers,
            CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.start_migration"))
                {
                    // Build Python dict for property mapping
                    using var pyMapping = new PyDict();
                    foreach (var kv in propertyMapping)
                    {
                        using var k = kv.Key.ToPython();
                        using var v = kv.Value.ToPython();
                        pyMapping.SetItem(k, v);
                    }

                    dynamic ret = pyMain.start_migration(sourceId, targetId, pyMapping, maxWorkers);
                    string status = ret["status"]?.ToString() ?? "";
                    string error = "";
                    try { error = ret["error"]?.ToString() ?? ""; } catch { }
                    if (string.Equals(error, "None", StringComparison.OrdinalIgnoreCase)) error = "";

                    if (!string.IsNullOrEmpty(error))
                        return $"Error: {error}";
                    return status;
                }
            }, token);
        }

        public async Task<MigrationProgress> GetMigrationProgressAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_migration_progress"))
                {
                    dynamic ret = pyMain.get_migration_progress();

                    string status = ret["status"]?.ToString() ?? "idle";
                    int total = PyConvert.ToInt(ret["total"], 0);
                    int done = PyConvert.ToInt(ret["done"], 0);
                    int failed = PyConvert.ToInt(ret["failed"], 0);
                    double percent = PyConvert.ToDouble(ret["percent"], 0.0);

                    var errors = new List<string>();
                    try
                    {
                        dynamic pyErrors = ret["errors"];
                        dynamic builtins = Py.Import("builtins");
                        int count = (int)builtins.len(pyErrors);
                        for (int i = 0; i < count; i++)
                        {
                            string e = pyErrors[i]?.ToString() ?? "";
                            if (!string.IsNullOrEmpty(e)) errors.Add(e);
                        }
                    }
                    catch { }

                    return new MigrationProgress(status, total, done, failed, percent, errors);
                }
            }, token);
        }

        public async Task<string> CancelMigrationAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.cancel_migration"))
                {
                    dynamic ret = pyMain.cancel_migration();
                    return ret["status"]?.ToString() ?? "";
                }
            }, token);
        }

        // ===================================================================
        // Batch Remove Suffix (v1.3.0-Status)
        // ===================================================================

        /// <summary>
        /// Progress data for batch remove suffix task.
        /// </summary>
        public sealed record BatchRemoveSuffixProgress(
            string Status, int Total, int Scanned, int Done,
            int Failed, int Skipped, double Percent, IReadOnlyList<string> Errors);

        public async Task<string> StartBatchRemoveSuffixAsync(
            string dataSourceId, string suffix, int maxWorkers, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.start_batch_remove_suffix"))
                {
                    dynamic ret = pyMain.start_batch_remove_suffix(dataSourceId, suffix, maxWorkers);
                    string status = ret["status"]?.ToString() ?? "";
                    string error = "";
                    try { error = ret["error"]?.ToString() ?? ""; } catch { }
                    if (string.Equals(error, "None", StringComparison.OrdinalIgnoreCase)) error = "";

                    if (!string.IsNullOrEmpty(error))
                        return $"Error: {error}";
                    return status;
                }
            }, token);
        }

        public async Task<BatchRemoveSuffixProgress> GetBatchRemoveSuffixProgressAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_batch_remove_suffix_progress"))
                {
                    dynamic ret = pyMain.get_batch_remove_suffix_progress();

                    string status = ret["status"]?.ToString() ?? "idle";
                    int total = PyConvert.ToInt(ret["total"], 0);
                    int scanned = PyConvert.ToInt(ret["scanned"], 0);
                    int done = PyConvert.ToInt(ret["done"], 0);
                    int failed = PyConvert.ToInt(ret["failed"], 0);
                    int skipped = PyConvert.ToInt(ret["skipped"], 0);
                    double percent = PyConvert.ToDouble(ret["percent"], 0.0);

                    var errors = new List<string>();
                    try
                    {
                        dynamic pyErrors = ret["errors"];
                        dynamic builtins = Py.Import("builtins");
                        int count = (int)builtins.len(pyErrors);
                        for (int i = 0; i < count; i++)
                        {
                            string e = pyErrors[i]?.ToString() ?? "";
                            if (!string.IsNullOrEmpty(e)) errors.Add(e);
                        }
                    }
                    catch { }

                    return new BatchRemoveSuffixProgress(status, total, scanned, done, failed, skipped, percent, errors);
                }
            }, token);
        }

        public async Task<string> CancelBatchRemoveSuffixAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.cancel_batch_remove_suffix"))
                {
                    dynamic ret = pyMain.cancel_batch_remove_suffix();
                    return ret["status"]?.ToString() ?? "";
                }
            }, token);
        }
        // ===================================================================
        // Page Size Update (v1.4.0-Status)
        // ===================================================================

        /// <summary>
        /// Page info from data source scan for size update feature.
        /// </summary>
        public sealed record PageSizeInfo(string Id, string Title, double? SizeValue);

        public sealed record ScanPagesResult(
            string Status,
            IReadOnlyList<PageSizeInfo> PagesWithSize,
            IReadOnlyList<PageSizeInfo> PagesWithoutSize,
            int Total,
            string Error);

        public async Task<ScanPagesResult> ScanDataSourcePagesAsync(
            string dataSourceId, string sizePropertyName, CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.scan_data_source_pages"))
                {
                    dynamic ret = pyMain.scan_data_source_pages(dataSourceId, sizePropertyName);

                    string status = ret["status"]?.ToString() ?? "error";
                    int total = PyConvert.ToInt(ret["total"], 0);
                    string error = "";
                    try { error = ret["error"]?.ToString() ?? ""; } catch { }
                    if (string.Equals(error, "None", StringComparison.OrdinalIgnoreCase)) error = "";

                    var withSize = new List<PageSizeInfo>();
                    var withoutSize = new List<PageSizeInfo>();

                    try
                    {
                        dynamic builtins = Py.Import("builtins");

                        dynamic pyWith = ret["pages_with_size"];
                        int wc = (int)builtins.len(pyWith);
                        for (int i = 0; i < wc; i++)
                        {
                            string id = pyWith[i]["id"]?.ToString() ?? "";
                            string title = pyWith[i]["title"]?.ToString() ?? "";
                            double sv = PyConvert.ToDouble(pyWith[i]["size_value"], 0.0);
                            withSize.Add(new PageSizeInfo(id, title, sv));
                        }

                        dynamic pyWithout = ret["pages_without_size"];
                        int woc = (int)builtins.len(pyWithout);
                        for (int i = 0; i < woc; i++)
                        {
                            string id = pyWithout[i]["id"]?.ToString() ?? "";
                            string title = pyWithout[i]["title"]?.ToString() ?? "";
                            withoutSize.Add(new PageSizeInfo(id, title, null));
                        }
                    }
                    catch (Exception ex)
                    {
                        Logger.Warn($"ScanDataSourcePagesAsync parse failed: {ex.Message}");
                    }

                    return new ScanPagesResult(status, withSize, withoutSize, total, error);
                }
            }, token);
        }

        public async Task<string> StartPageSizeUpdateAsync(
            string dataSourceId, string sizePropertyName,
            List<string> pageIds, int linkWorkers, int sizeWorkers,
            CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.start_page_size_update"))
                {
                    using var pyPageIds = new PyList();
                    foreach (var id in pageIds)
                        pyPageIds.Append((id ?? "").ToPython());

                    dynamic ret = pyMain.start_page_size_update(
                        dataSourceId, sizePropertyName, pyPageIds,
                        linkWorkers, sizeWorkers);

                    string status = ret["status"]?.ToString() ?? "";
                    string error = "";
                    try { error = ret["error"]?.ToString() ?? ""; } catch { }
                    if (string.Equals(error, "None", StringComparison.OrdinalIgnoreCase)) error = "";

                    if (!string.IsNullOrEmpty(error))
                        return $"Error: {error}";
                    return status;
                }
            }, token);
        }

        /// <summary>
        /// Page size update progress data.
        /// </summary>
        public sealed record PageSizeUpdateProgress(
            string Status, int Total, int LinkQueried, int SizeUpdated,
            int Failed, double Percent, string CurrentPage, int CurrentFiles,
            int FilesDiscovered, int FilesProbed,
            IReadOnlyList<string> Errors);

        public async Task<PageSizeUpdateProgress> GetPageSizeUpdateProgressAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.get_page_size_update_progress"))
                {
                    dynamic ret = pyMain.get_page_size_update_progress();

                    string status = ret["status"]?.ToString() ?? "idle";
                    int total = PyConvert.ToInt(ret["total"], 0);
                    int linkQueried = PyConvert.ToInt(ret["link_queried"], 0);
                    int sizeUpdated = PyConvert.ToInt(ret["size_updated"], 0);
                    int failed = PyConvert.ToInt(ret["failed"], 0);
                    double percent = PyConvert.ToDouble(ret["percent"], 0.0);
                    string currentPage = "";
                    try { currentPage = ret["current_page"]?.ToString() ?? ""; } catch { }
                    int currentFiles = PyConvert.ToInt(ret["current_files"], 0);
                    int filesDiscovered = PyConvert.ToInt(ret["files_discovered"], 0);
                    int filesProbed = PyConvert.ToInt(ret["files_probed"], 0);

                    var errors = new List<string>();
                    try
                    {
                        dynamic pyErrors = ret["errors"];
                        dynamic builtins = Py.Import("builtins");
                        int count = (int)builtins.len(pyErrors);
                        for (int i = 0; i < count; i++)
                        {
                            string e = pyErrors[i]?.ToString() ?? "";
                            if (!string.IsNullOrEmpty(e)) errors.Add(e);
                        }
                    }
                    catch { }

                    return new PageSizeUpdateProgress(
                        status, total, linkQueried, sizeUpdated,
                        failed, percent, currentPage, currentFiles,
                        filesDiscovered, filesProbed, errors);
                }
            }, token);
        }

        public async Task<string> CancelPageSizeUpdateAsync(CancellationToken token)
        {
            return await _backend.RunPython(py =>
            {
                dynamic pyMain = py;
                using (Logger.Time("Py:Main.cancel_page_size_update"))
                {
                    dynamic ret = pyMain.cancel_page_size_update();
                    return ret["status"]?.ToString() ?? "";
                }
            }, token);
        }
    }
}
