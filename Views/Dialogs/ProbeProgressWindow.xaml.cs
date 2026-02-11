using System;
using System.Windows;

namespace Notion_Files_Management.Views.Dialogs
{
    public partial class ProbeProgressWindow : Window
    {
        public event Action? CancelRequested;

        public ProbeProgressWindow()
        {
            InitializeComponent();
        }

        public void SetProgress(double percent, string text)
        {
            StatusText.Text = text ?? "";
            if (percent < 0) percent = 0;
            if (percent > 100) percent = 100;
            Bar.Value = percent;
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            CancelRequested?.Invoke();
            CancelBtn.IsEnabled = false;
            StatusText.Text = "正在取消…";
        }
    }
}
