using System;
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace Notion_Files_Management.Models
{
    /// <summary>
    /// UI model for an upload task.
    /// </summary>
    public sealed class UploadTaskStatus : ObservableObject
    {
        private string? _filePath;
        private string? _fileName;
        private string? _status;
        private string? _stage;
        private double _progress;
        private double _uploadedMB;
        private double _totalMB;
        private double _smoothedSpeed;
        private int _etaSeconds;
        private string? _error;

        public string? FilePath
        {
            get => _filePath;
            set
            {
                if (SetProperty(ref _filePath, value))
                    OnPropertyChanged(nameof(StatusText));
            }
        }

        public string? FileName
        {
            get => _fileName;
            set => SetProperty(ref _fileName, value);
        }

        public string? Status
        {
            get => _status;
            set
            {
                if (SetProperty(ref _status, value))
                    OnPropertyChanged(nameof(StatusText));
            }
        }

        public string? Stage
        {
            get => _stage;
            set
            {
                if (SetProperty(ref _stage, value))
                    OnPropertyChanged(nameof(StatusText));
            }
        }

        public double Progress
        {
            get => _progress;
            set => SetProperty(ref _progress, value);
        }

        public double UploadedMB
        {
            get => _uploadedMB;
            set => SetProperty(ref _uploadedMB, value);
        }

        public double TotalMB
        {
            get => _totalMB;
            set => SetProperty(ref _totalMB, value);
        }

        public double SmoothedSpeedMBps
        {
            get => _smoothedSpeed;
            set => SetProperty(ref _smoothedSpeed, value);
        }

        public int ETASeconds
        {
            get => _etaSeconds;
            set => SetProperty(ref _etaSeconds, value);
        }

        public string? Error
        {
            get => _error;
            set
            {
                if (SetProperty(ref _error, value))
                    OnPropertyChanged(nameof(StatusText));
            }
        }

        public string StatusText
        {
            get
            {
                var s = Status ?? "";
                var st = Stage ?? "";

                if (!string.IsNullOrWhiteSpace(Error) &&
                    !string.Equals(Error, "None", StringComparison.OrdinalIgnoreCase))
                    return $"状态: {s} / 阶段: {st} / 错误: {Error}";

                bool connecting =
                    string.Equals(s, "uploading", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(st, "uploading", StringComparison.OrdinalIgnoreCase) &&
                    Progress <= 0.1 && UploadedMB <= 0.01 && SmoothedSpeedMBps <= 0.05;

                return connecting
                    ? "正在连接 Notion 服务器…（准备上传）"
                    : $"状态: {s} / 阶段: {st}";
            }
        }
    }
}
