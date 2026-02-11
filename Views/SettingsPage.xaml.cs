using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Threading.Tasks;
using System.Diagnostics;
using Notion_Files_Management.Services;

namespace Notion_Files_Management.Views
{
    public partial class SettingsPage : Page
    {
        public SettingsPage()
        {
            InitializeComponent();

            // Load persisted user config
            ConfigManager.Load();
            if (ConfigManager.Current != null)
            {
                TokenInput.Password = ConfigManager.Current.NotionToken;
                NotionUrlInput.Text = ConfigManager.Current.NotionBaseUrl ?? "https://api.notion.com/v1";
                SelectComboByInt(DownloadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxDownloadWorkers));
                SelectComboByInt(UploadWorkersCombo, ClampWorkers(ConfigManager.Current.MaxUploadWorkers));
            }
        }

        private void OnSaveClick(object sender, RoutedEventArgs e)
        {
            try
            {
                ConfigManager.Load();

                // 1) Read inputs
                string inputToken = TokenInput.Password?.Trim() ?? "";
                string inputUrl = NotionUrlInput.Text?.Trim() ?? "";
                int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
                int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo, fallback: 3));

                // 2) Validate and clean URL
                string cleanedUrl = CleanAndValidateUrl(inputUrl);

                // 3) Persist to user data
                ConfigManager.Current.NotionToken = inputToken;
                ConfigManager.Current.NotionBaseUrl = cleanedUrl;
                ConfigManager.Current.MaxDownloadWorkers = dl;
                ConfigManager.Current.MaxUploadWorkers = ul;
                ConfigManager.Save();
            }
            catch (Exception ex)
            {
                // No popup per requirement; keep trace for debugging
                Debug.WriteLine($"[SettingsPage] Save config failed: {ex}");
            }
        }

        private async void OnApplyWorkersResetClick(object sender, RoutedEventArgs e)
        {
            try
            {
                ConfigManager.Load();

                string inputToken = TokenInput.Password?.Trim() ?? "";
                string inputUrl = NotionUrlInput.Text?.Trim() ?? "";
                int dl = ClampWorkers(ReadComboInt(DownloadWorkersCombo, fallback: 3));
                int ul = ClampWorkers(ReadComboInt(UploadWorkersCombo, fallback: 3));

                // Validate and clean URL
                string cleanedUrl = CleanAndValidateUrl(inputUrl);

                // Persist first (so next app start is consistent)
                ConfigManager.Current.NotionToken = inputToken;
                ConfigManager.Current.NotionBaseUrl = cleanedUrl;
                ConfigManager.Current.MaxDownloadWorkers = dl;
                ConfigManager.Current.MaxUploadWorkers = ul;
                ConfigManager.Save();

                BtnApplyWorkersReset.IsEnabled = false;

                // Reset tasks + reinitialize backend (best-effort)
                await PythonBackendHost.Instance.ResetTasksAndReinitialize(inputToken, dl, ul, cleanedUrl);

                // Clear in-app UI state
                var ds = DownloadSession.Instance;
                ds.FileSelectionList.Clear();
                ds.DisplayTasks.Clear();
                ds.HasActiveDownloads = false;

                TaskResetNotifier.NotifyTasksReset();
            }
            catch (Exception ex)
            {
                // No popup per requirement; keep trace for debugging
                Debug.WriteLine($"[SettingsPage] Apply+Reset failed: {ex}");
            }
            finally
            {
                BtnApplyWorkersReset.IsEnabled = true;
            }
        }

        private static int ClampWorkers(int v)
        {
            // Keep within sane bounds to avoid accidental huge thread-pools
            if (v < 1) return 1;
            if (v > 16) return 16;
            return v;
        }

        private static int ReadComboInt(ComboBox combo, int fallback)
        {
            try
            {
                if (combo.SelectedItem is ComboBoxItem item &&
                    int.TryParse(item.Content?.ToString(), out int v))
                    return v;
            }
            catch { }
            return fallback;
        }

        private static void SelectComboByInt(ComboBox combo, int value)
        {
            foreach (var obj in combo.Items.OfType<ComboBoxItem>())
            {
                if (int.TryParse(obj.Content?.ToString(), out int v) && v == value)
                {
                    combo.SelectedItem = obj;
                    return;
                }
            }

            // fallback to first item
            if (combo.Items.Count > 0)
                combo.SelectedIndex = 0;
        }

        private string CleanAndValidateUrl(string inputUrl)
        {
            string url = inputUrl?.Trim() ?? "";
            if (string.IsNullOrWhiteSpace(url))
                return "https://api.notion.com/v1";
            
            if (!url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
                !url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                return "https://api.notion.com/v1";
            }
            
            // 去掉尾部的斜杠
            return url.TrimEnd('/');
        }
    }
}
