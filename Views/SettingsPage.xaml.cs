using System.Windows;
using System.Windows.Controls;
using Notion_Files_Management;

namespace Notion_Files_Management.Views
{
	public partial class SettingsPage : Page
	{
		public SettingsPage()
		{
			InitializeComponent();

			// 页面初始化时，自动读取已保存的 Token
			// 这样用户切回这个页面时能看到自己填过的内容
			if (ConfigManager.Current != null)
			{
				TokenInput.Password = ConfigManager.Current.NotionToken;
			}
		}

		private void OnSaveClick(object sender, RoutedEventArgs e)
		{
			// 1. 获取输入框内容
			string inputToken = TokenInput.Password;

			// 2. 更新到全局配置单例（更新数据）
			ConfigManager.Current.NotionToken = inputToken;

			// 3. 直接调用静态保存方法（执行存盘）
			ConfigManager.Save();

			// 4. 漂亮的成功提示
			var messageBox = new Wpf.Ui.Controls.MessageBox
			{
				Title = "保存成功",
				Content = "Notion Token 已存入系统 AppData，程序重启后依然有效。",
				CloseButtonText = "我知道了"
			};
			messageBox.ShowDialogAsync();
		}
	}
}