namespace Notion_Files_Management.Models
{
    /// <summary>
    /// Download task status item returned by python backend.
    /// Property names keep snake_case so existing XAML bindings keep working.
    /// </summary>
    public sealed class DownloadTaskStatus : ObservableObject
    {
        private string? _url;
        private string? _name;
        private string? _real_name;
        private string? _status;
        private double _progress;
        private double _downloaded;
        private double _total;
        private double _speed;
        private int _eta;
        private string? _error;
        private string? _created_time;

        public string? url
        {
            get => _url;
            set => SetProperty(ref _url, value);
        }

        public string? name
        {
            get => _name;
            set => SetProperty(ref _name, value);
        }

        public string? real_name
        {
            get => _real_name;
            set => SetProperty(ref _real_name, value);
        }

        public string? status
        {
            get => _status;
            set => SetProperty(ref _status, value);
        }

        public double progress
        {
            get => _progress;
            set => SetProperty(ref _progress, value);
        }

        public double downloaded_mb
        {
            get => _downloaded;
            set => SetProperty(ref _downloaded, value);
        }

        public double total_mb
        {
            get => _total;
            set => SetProperty(ref _total, value);
        }

        public double speed_mb_s
        {
            get => _speed;
            set => SetProperty(ref _speed, value);
        }

        public int ETA
        {
            get => _eta;
            set => SetProperty(ref _eta, value);
        }

        public string? error
        {
            get => _error;
            set => SetProperty(ref _error, value);
        }

        public string? created_time
        {
            get => _created_time;
            set => SetProperty(ref _created_time, value);
        }
    }
}
