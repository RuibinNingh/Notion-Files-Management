using System;

namespace Notion_Files_Management.Models
{
    /// <summary>
    /// A selectable file entry shown in Download dialog.
    /// Property names intentionally keep snake_case to match python dict keys
    /// and minimize binding churn in existing XAML.
    /// </summary>
    public sealed class FileSelectItem : ObservableObject
    {
        private bool _isSelected = true;

        public bool IsSelected
        {
            get => _isSelected;
            set => SetProperty(ref _isSelected, value);
        }

        public string? url { get; set; }
        public string? name { get; set; }
        public string? real_name { get; set; }
        public string? expiry_time { get; set; }
        public double size_mb { get; set; }
        public string? block_id { get; set; }
        public string? block_type { get; set; }
        public string? created_time { get; set; }

        /// <summary>
        /// Best-effort parse of Notion file expiry_time (ISO 8601).
        /// Not all files have expiry_time (e.g. external urls).
        /// </summary>
        public DateTimeOffset? expiry_utc
        {
            get
            {
                if (string.IsNullOrWhiteSpace(expiry_time))
                    return null;

                if (DateTimeOffset.TryParse(expiry_time, out var dto))
                    return dto;

                return null;
            }
        }
    }
}
