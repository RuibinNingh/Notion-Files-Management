using System;

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
            string[] okKeywords = new[] { "success", "started", "已启动", "started" };
            foreach (var k in okKeywords)
            {
                if (s.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }
    }
}
