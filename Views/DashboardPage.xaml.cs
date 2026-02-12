using System;
using System.Windows;
using System.Windows.Controls;

namespace Notion_Files_Management.Views
{
    public partial class DashboardPage : Page
    {
        private const string WebsiteUrl = "https://nfm.ruibin-ningh.top";
        private const string GitHubUrl  = "https://github.com/RuibinNingh/Notion-Files-Management";
        private const string SponsorUrl = "https://nfm.ruibin-ningh.top/sponsor";

        public DashboardPage()
        {
            InitializeComponent();

            // 从 ConfigManager 读取版本号并展示
            ConfigManager.Load();
            var version = ConfigManager.Current?.AppVersion;
            TxtVersion.Text = string.IsNullOrWhiteSpace(version) ? "" : $"v{version}";
        }

        private void OnWebsiteClick(object sender, RoutedEventArgs e)
            => OpenUrl(WebsiteUrl);

        private void OnGitHubClick(object sender, RoutedEventArgs e)
            => OpenUrl(GitHubUrl);

        private void OnSponsorClick(object sender, RoutedEventArgs e)
            => OpenUrl(SponsorUrl);

        private static void OpenUrl(string url)
        {
            try
            {
                System.Diagnostics.Process.Start(
                    new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch { /* 静默失败，不弹窗 */ }
        }
    }
}
