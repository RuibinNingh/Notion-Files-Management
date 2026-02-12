namespace Notion_Files_Management.Models
{
    /// <summary>
    /// Raw upload status returned from python backend.
    /// This DTO is not directly bound to UI (UI uses <see cref="UploadTaskStatus"/>).
    /// </summary>
    public sealed class UploadStatusDto
    {
        public string FilePath { get; set; } = "";
        public string Status { get; set; } = "";
        public string Stage { get; set; } = "";
        public double Progress { get; set; }
        public double UploadedMB { get; set; }
        public double TotalMB { get; set; }
        public double Speed { get; set; }
        public int ETA { get; set; }
        public string? Error { get; set; }
    }
}
