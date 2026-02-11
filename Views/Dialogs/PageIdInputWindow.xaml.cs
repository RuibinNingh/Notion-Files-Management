using System.Windows;

namespace Notion_Files_Management.Views.Dialogs
{
    public partial class PageIdInputWindow : Window
    {
        public string PageId { get; private set; } = "";

        public PageIdInputWindow()
        {
            InitializeComponent();
            PageIdTextBox.Focus();
        }

        private void Ok_Click(object sender, RoutedEventArgs e)
        {
            PageId = (PageIdTextBox.Text ?? "").Trim().Replace(" ", "");
            if (string.IsNullOrWhiteSpace(PageId))
            {
                MessageBox.Show("Page ID ²»ÄÜÎª¿Õ¡£");
                return;
            }
            DialogResult = true;
            Close();
        }

        private void Cancel_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
    }
}
