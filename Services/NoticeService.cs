using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using Notion_Files_Management.Models;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Services
{
    /// <summary>
    /// 公告服务：网络请求 + 本地缓存 + 已读管理
    /// 复用 SettingsPage 中的 HTTPS 优先 / HTTP 兜底模式
    /// </summary>
    public static class NoticeService
    {
        private const string BaseUrlHttps = "https://nfm.ruibin-ningh.top/notices";
        private const string BaseUrlHttp  = "http://nfm.ruibin-ningh.top/notices";
        private const string IndexFile    = "idx.json";

        private static readonly HttpClient _http = new()
        {
            Timeout = TimeSpan.FromSeconds(10)
        };

        // ═══ 本地缓存路径 ═══
        private static readonly string CacheDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "NotionFilesManagement", "notices_cache");

        private static readonly string IndexCachePath =
            Path.Combine(CacheDir, "idx.json");

        // ═══ 已读记录路径 ═══
        private static readonly string ReadIdsPath =
            Path.Combine(CacheDir, "read_ids.json");

        /// <summary>
        /// 静态缓存：应用运行期间的公告索引
        /// </summary>
        internal static NoticeIndex? CachedIndex { get; set; }

        // ═══════════════════ 公告索引 ═══════════════════

        /// <summary>
        /// 获取公告索引（优先网络，失败回退本地缓存）
        /// </summary>
        public static async Task<NoticeIndex?> FetchIndexAsync()
        {
            string? json = null;

            // 先尝试 HTTPS
            try
            {
                var url = $"{BaseUrlHttps}/{IndexFile}";
                var response = await _http.GetAsync(url);
                response.EnsureSuccessStatusCode();
                json = await response.Content.ReadAsStringAsync();
                Logger.Info("[NoticeService] Fetched idx.json via HTTPS");
            }
            catch
            {
                // 降级到 HTTP
                try
                {
                    var url = $"{BaseUrlHttp}/{IndexFile}";
                    var response = await _http.GetAsync(url);
                    response.EnsureSuccessStatusCode();
                    json = await response.Content.ReadAsStringAsync();
                    Logger.Info("[NoticeService] Fetched idx.json via HTTP fallback");
                }
                catch (Exception ex)
                {
                    Logger.Warn($"[NoticeService] Failed to fetch idx.json: {ex.Message}");
                }
            }

            if (!string.IsNullOrEmpty(json))
            {
                try
                {
                    var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                    var index = JsonSerializer.Deserialize<NoticeIndex>(json, options);
                    if (index != null)
                    {
                        // 写入本地缓存
                        EnsureCacheDir();
                        await File.WriteAllTextAsync(IndexCachePath, json);
                        CachedIndex = index;
                        return index;
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn($"[NoticeService] Failed to parse idx.json: {ex.Message}");
                }
            }

            // 回退到本地缓存
            return LoadIndexFromCache();
        }

        /// <summary>
        /// 从本地缓存读取公告索引
        /// </summary>
        private static NoticeIndex? LoadIndexFromCache()
        {
            try
            {
                if (!File.Exists(IndexCachePath)) return null;
                var json = File.ReadAllText(IndexCachePath);
                var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                var index = JsonSerializer.Deserialize<NoticeIndex>(json, options);
                if (index != null)
                {
                    CachedIndex = index;
                    Logger.Info("[NoticeService] Loaded idx.json from cache");
                }
                return index;
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticeService] Failed to load cached idx.json: {ex.Message}");
                return null;
            }
        }

        // ═══════════════════ 公告正文 ═══════════════════

        /// <summary>
        /// 根据 id 获取 Markdown 正文（优先网络，失败回退缓存）
        /// </summary>
        public static async Task<string?> FetchContentAsync(string id)
        {
            string? content = null;
            var fileName = $"{id}.md";

            // 先尝试 HTTPS
            try
            {
                var url = $"{BaseUrlHttps}/{fileName}";
                var response = await _http.GetAsync(url);
                response.EnsureSuccessStatusCode();
                content = await response.Content.ReadAsStringAsync();
            }
            catch
            {
                // 降级到 HTTP
                try
                {
                    var url = $"{BaseUrlHttp}/{fileName}";
                    var response = await _http.GetAsync(url);
                    response.EnsureSuccessStatusCode();
                    content = await response.Content.ReadAsStringAsync();
                }
                catch { }
            }

            if (!string.IsNullOrEmpty(content))
            {
                // 写入缓存
                try
                {
                    EnsureCacheDir();
                    var cachePath = Path.Combine(CacheDir, fileName);
                    await File.WriteAllTextAsync(cachePath, content);
                }
                catch { }
                return content;
            }

            // 回退到缓存
            return LoadContentFromCache(id);
        }

        /// <summary>
        /// 从本地缓存读取公告正文
        /// </summary>
        private static string? LoadContentFromCache(string id)
        {
            try
            {
                var cachePath = Path.Combine(CacheDir, $"{id}.md");
                return File.Exists(cachePath) ? File.ReadAllText(cachePath) : null;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// 批量预加载所有公告正文
        /// </summary>
        public static async Task PreloadAllContentAsync(List<NoticeItem> items)
        {
            var tasks = items.Select(async item =>
            {
                var content = await FetchContentAsync(item.Id);
                item.Content = content ?? "（加载失败）";
                item.IsLoading = false;
            });
            await Task.WhenAll(tasks);
        }

        // ═══════════════════ 已读管理 ═══════════════════

        /// <summary>
        /// 获取未读公告数量
        /// </summary>
        public static int GetUnreadCount(NoticeIndex? index)
        {
            if (index == null || index.Notices.Count == 0) return 0;
            var readIds = LoadReadIds();
            return index.Notices.Count(n => !readIds.Contains(n.Id));
        }

        /// <summary>
        /// 标记某条公告为已读
        /// </summary>
        public static void MarkAsRead(string id)
        {
            try
            {
                var readIds = LoadReadIds();
                if (readIds.Contains(id)) return;
                readIds.Add(id);
                SaveReadIds(readIds);
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticeService] MarkAsRead failed: {ex.Message}");
            }
        }

        /// <summary>
        /// 批量标记全部已读
        /// </summary>
        public static void MarkAllAsRead(IEnumerable<NoticeItem> items)
        {
            try
            {
                var readIds = LoadReadIds();
                bool changed = false;
                foreach (var item in items)
                {
                    if (!readIds.Contains(item.Id))
                    {
                        readIds.Add(item.Id);
                        changed = true;
                    }
                }
                if (changed) SaveReadIds(readIds);
            }
            catch (Exception ex)
            {
                Logger.Warn($"[NoticeService] MarkAllAsRead failed: {ex.Message}");
            }
        }

        private static HashSet<string> LoadReadIds()
        {
            try
            {
                if (!File.Exists(ReadIdsPath)) return new HashSet<string>();
                var json = File.ReadAllText(ReadIdsPath);
                var list = JsonSerializer.Deserialize<List<string>>(json);
                return list != null ? new HashSet<string>(list) : new HashSet<string>();
            }
            catch
            {
                return new HashSet<string>();
            }
        }

        private static void SaveReadIds(HashSet<string> readIds)
        {
            EnsureCacheDir();
            var json = JsonSerializer.Serialize(readIds.ToList());
            File.WriteAllText(ReadIdsPath, json);
        }

        // ═══════════════════ 工具 ═══════════════════

        private static void EnsureCacheDir()
        {
            if (!Directory.Exists(CacheDir))
                Directory.CreateDirectory(CacheDir);
        }
    }
}
