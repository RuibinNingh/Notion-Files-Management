using System;
using System.Diagnostics;
using System.Windows.Input;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// 在默认浏览器中打开 URL 的 ICommand 实现。
    /// 用于 MdXaml MarkdownScrollViewer 的 HyperlinkCommand 属性，
    /// Execute 参数为 URL 字符串（MdXaml 传入）。
    /// </summary>
    public sealed class OpenBrowserCommand : ICommand
    {
        public static OpenBrowserCommand Instance { get; } = new();

        public event EventHandler? CanExecuteChanged
        {
            add { }
            remove { }
        }

        public bool CanExecute(object? parameter) => true;

        public void Execute(object? parameter)
        {
            var url = parameter?.ToString();
            if (string.IsNullOrWhiteSpace(url)) return;

            try
            {
                // 安全校验：仅允许 http/https 协议
                if (Uri.TryCreate(url, UriKind.Absolute, out var uri)
                    && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                {
                    Logger.Info($"[OpenBrowserCommand] Opening URL: {url}");
                    Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
                }
                else
                {
                    Logger.Warn($"[OpenBrowserCommand] Blocked non-HTTP URL: {url}");
                }
            }
            catch (Exception ex)
            {
                Logger.Warn($"[OpenBrowserCommand] Failed to open URL '{url}': {ex.Message}");
            }
        }
    }
}
