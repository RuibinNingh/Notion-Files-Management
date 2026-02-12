using System;
using System.Text.RegularExpressions;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// Notion Page ID helper.
    ///
    /// Notion API uses UUIDs (string&lt;uuid&gt;) as page IDs.
    /// Users often paste:
    /// - 32 hex chars without hyphens
    /// - Standard UUID with hyphens (8-4-4-4-12)
    /// - A full Notion URL that contains the ID
    ///
    /// This helper normalizes inputs into the canonical UUID string format.
    /// NOTE: Do NOT enforce UUID version bits (Notion IDs are documented as UUIDs,
    /// but in practice may not always match strict UUIDv4 patterns).
    /// </summary>
    internal static class NotionPageId
    {
        // 32 hex OR uuid with hyphens. We extract from anywhere (e.g., pasted URL).
        private static readonly Regex UuidLikeRegex = new Regex(
            @"(?i)([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            RegexOptions.Compiled);

        public static bool TryNormalize(string? input, out string normalized, out string error)
        {
            normalized = "";
            error = "";

            var raw = (input ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(raw))
            {
                error = "请输入目标页面 ID。";
                return false;
            }

            // Remove whitespace inside.
            raw = raw.Replace(" ", "").Replace("\r", "").Replace("\n", "").Replace("\t", "");

            // Extract UUID-like segment if user pasted a full URL or extra text.
            var m = UuidLikeRegex.Match(raw);
            var candidate = m.Success ? m.Groups[1].Value : raw;

            var compact = candidate.Replace("-", "");
            if (compact.Length != 32)
            {
                error = "Page ID 格式不正确：应为 32 位十六进制（可带连字符），例如 2fc644ea-d11a-8010-9665-e5fbaba0fd58。";
                return false;
            }

            for (int i = 0; i < compact.Length; i++)
            {
                char c = compact[i];
                bool isHex = (c >= '0' && c <= '9') ||
                            (c >= 'a' && c <= 'f') ||
                            (c >= 'A' && c <= 'F');
                if (!isHex)
                {
                    error = "Page ID 格式不正确：只能包含 0-9 / a-f 的字符。";
                    return false;
                }
            }

            compact = compact.ToLowerInvariant();
            normalized = $"{compact.Substring(0, 8)}-{compact.Substring(8, 4)}-{compact.Substring(12, 4)}-{compact.Substring(16, 4)}-{compact.Substring(20, 12)}";
            return true;
        }

        /// <summary>
        /// Best-effort auto-format for TextBox TextChanged.
        /// Returns:
        /// - formattedText: if input forms a valid 32-hex ID (with or without hyphens), returns normalized UUID.
        /// - isValid: true if it is a valid ID; false if empty/partial/invalid.
        /// - hint: a lightweight UI hint (empty for partial inputs).
        /// </summary>
        public static (string formattedText, bool isValid, string hint) AutoFormat(string? input)
        {
            var raw = (input ?? string.Empty);
            if (string.IsNullOrWhiteSpace(raw))
                return (raw, false, "");

            raw = raw.Trim().Replace(" ", "").Replace("\r", "").Replace("\n", "").Replace("\t", "");
            var m = UuidLikeRegex.Match(raw);
            var candidate = m.Success ? m.Groups[1].Value : raw;
            var compact = candidate.Replace("-", "");

            // If user is still typing/pasting partial content, do not show aggressive warnings.
            if (compact.Length < 32)
                return (raw, false, "");

            if (compact.Length > 32)
                return (raw, false, "Page ID 长度不正确（应为 32 位十六进制）。");

            if (!TryNormalize(candidate, out var normalized, out var err))
                return (raw, false, err);

            return (normalized, true, "");
        }
    }
}
