using System;
using System.Threading.Tasks;
using Notion_Files_Management.Services;

namespace Notion_Files_Management.Utils
{
    internal static class UiHelpers
    {
        public static bool IsSuccessResponse(string? ret)
        {
            if (string.IsNullOrWhiteSpace(ret))
                return true;
            string s = ret.Trim();
            if (s.StartsWith("OK", StringComparison.OrdinalIgnoreCase))
                return true;
            string[] okKeywords = new[] { "success", "started", "已启动" };
            foreach (var k in okKeywords)
            {
                if (s.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }

        /// <summary>
        /// 后端预热：在后台异步初始化后端服务，不阻塞 UI
        /// 用于页面构造函数中提前准备后端，提升用户体验
        /// </summary>
        public static void WarmUpBackend()
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await NotionBackendService.Instance.EnsureBackendReadyFromConfigAsync();
                }
                catch
                {
                    // 静默失败，不影响 UI
                }
            });
        }
    }
}
