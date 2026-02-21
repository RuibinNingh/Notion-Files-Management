namespace Notion_Files_Management.Services
{
    /// <summary>
    /// 自动更新会话状态（单例）
    /// 解决设置页面切换后自动更新进度条消失的问题。
    /// 与 DownloadSession / UploadSession 采用相同的单例模式。
    /// </summary>
    public sealed class AutoUpdateSession
    {
        public static AutoUpdateSession Instance { get; } = new AutoUpdateSession();

        /// <summary>是否正在下载中</summary>
        public bool IsDownloading { get; set; } = false;

        /// <summary>下载进度百分比（0-100），-1 表示不确定进度</summary>
        public double ProgressPercent { get; set; } = 0;

        /// <summary>按钮显示文本（如 "下载中（线路1）..."）</summary>
        public string StatusText { get; set; } = "自动更新";

        /// <summary>下载完成标志</summary>
        public bool IsCompleted { get; set; } = false;

        /// <summary>下载失败标志</summary>
        public bool HasFailed { get; set; } = false;

        /// <summary>下载完成后的文件路径</summary>
        public string? DownloadedFilePath { get; set; }

        /// <summary>成功线路的类型 ("installer" / "exe")</summary>
        public string? SuccessRouteType { get; set; }

        /// <summary>失败时的错误信息</summary>
        public string? ErrorMessage { get; set; }

        /// <summary>
        /// 重置所有状态（下载完成或用户再次点击时调用）
        /// </summary>
        public void Reset()
        {
            IsDownloading = false;
            ProgressPercent = 0;
            StatusText = "自动更新";
            IsCompleted = false;
            HasFailed = false;
            DownloadedFilePath = null;
            SuccessRouteType = null;
            ErrorMessage = null;
        }

        private AutoUpdateSession() { }
    }
}
