using System.Collections.ObjectModel;
using Notion_Files_Management.Models;

namespace Notion_Files_Management.Services
{
    public sealed class DownloadSession
    {
        public static DownloadSession Instance { get; } = new DownloadSession();

        public ObservableCollection<FileSelectItem> FileSelectionList { get; } = new();
        public ObservableCollection<DownloadTaskStatus> DisplayTasks { get; } = new();

        // persisted state
        public string SaveDirectory { get; set; } = "";
        public string PageId { get; set; } = "";

        // whether there are active downloads (used to decide to resume polling)
        public bool HasActiveDownloads { get; set; } = false;

        private DownloadSession() { }
    }
}
