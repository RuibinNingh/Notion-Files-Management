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
                    try { raw = ((PyObject)prog).Repr().ToString(); } catch { }

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

                        result.Add(new FileSelectItem
                        {
                            url = url,
                            name = name,
                            real_name = realName,
                            expiry_time = expiry,
                            size_mb = size,
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
                            error = PythonHelpers.NormalizePythonNone(s, "error")
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
    }
}
