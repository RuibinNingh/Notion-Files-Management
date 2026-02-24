using System;
using System.ComponentModel;

namespace Notion_Files_Management.Models
{
    public sealed class PageInfoItem : INotifyPropertyChanged
    {
        private double _sizeGb;
        private bool _isProbing;

        public string RealName { get; set; } = "";
        public string Url { get; set; } = "";

        public double SizeGb
        {
            get => _sizeGb;
            set
            {
                if (Math.Abs(_sizeGb - value) < 1e-12) return;
                _sizeGb = value;
                OnPropertyChanged(nameof(SizeGb));
                OnPropertyChanged(nameof(SizeGbText));
                OnPropertyChanged(nameof(SizeUnitText));
            }
        }

        /// <summary>
        /// true = 该文件的大小尚未探测完成，UI 应显示"正在查询中"
        /// </summary>
        public bool IsProbing
        {
            get => _isProbing;
            set
            {
                if (_isProbing == value) return;
                _isProbing = value;
                OnPropertyChanged(nameof(IsProbing));
                OnPropertyChanged(nameof(SizeGbText));
                OnPropertyChanged(nameof(SizeUnitText));
            }
        }

        public string SizeGbText
        {
            get
            {
                if (IsProbing) return "正在查询中";
                if (SizeGb <= 0) return "0.000";
                return Math.Round(SizeGb, 3).ToString("0.000");
            }
        }

        public string SizeUnitText
        {
            get
            {
                if (IsProbing) return "";
                return "GB";
            }
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        private void OnPropertyChanged(string name) =>
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
