using System.Collections.Generic;
using System.Collections.ObjectModel;
using Notion_Files_Management.Models;

namespace Notion_Files_Management.Services
{
    /// <summary>
    /// 上传页面会话状态（单例），用于在页面切换时保留上传任务和状态
    /// </summary>
    public sealed class UploadSession
    {
        public static UploadSession Instance { get; } = new UploadSession();

        // 上传任务显示列表
        public ObservableCollection<UploadTaskStatus> DisplayUploads { get; } = new();

        // 已选择要上传的文件列表
        public ObservableCollection<string> SelectedUploadFiles { get; } = new();

        // EMA速度平滑字典
        public Dictionary<string, double> SpeedEma { get; } = new(System.StringComparer.OrdinalIgnoreCase);

        // 持久化状态
        public string PageId { get; set; } = "";

        // 选中的文件夹路径（文件夹上传模式）
        public string? SelectedFolderPath { get; set; } = null;

        // 是否有活跃的上传任务（用于决定是否恢复轮询）
        public bool HasActiveUploads { get; set; } = false;

        private UploadSession() { }
    }
}
