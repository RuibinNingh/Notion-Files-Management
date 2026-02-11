using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;

namespace Notion_Files_Management.Views.Dialogs
{
    public partial class PageInfoResultWindow : Window
    {
        public PageInfoResultWindow(PageInfoResultVm vm)
        {
            InitializeComponent();
            DataContext = vm;
        }
    }

    public sealed class PageInfoResultVm : INotifyPropertyChanged
    {
        public ObservableCollection<PageFileInfoItem> Items { get; } = new();

        private int _fileCount;
        public int FileCount { get => _fileCount; set { _fileCount = value; OnPropertyChanged(); } }

        private double _totalSizeMb;
        public double TotalSizeMb { get => _totalSizeMb; set { _totalSizeMb = value; OnPropertyChanged(); } }

        public event PropertyChangedEventHandler? PropertyChanged;
        private void OnPropertyChanged([CallerMemberName] string? name = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    public sealed class PageFileInfoItem
    {
        public string RealName { get; set; } = "";
        public double SizeMb { get; set; }
        public string Url { get; set; } = "";
    }
}
