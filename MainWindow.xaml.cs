using System;
using System.Windows;
using Notion_Files_Management.Views;
using Python.Runtime;
using Wpf.Ui.Controls;
using System.Windows.Controls;
using System.IO;
using System;
using System.Runtime;

namespace Notion_Files_Management {
	public partial class MainWindow : FluentWindow {
		public MainWindow() {
			InitializeComponent();

			// 等待窗口加载完成
			Loaded += (sender, args) => {
				RootNavigation.Navigate(typeof(DashboardPage));
			};
			// 填坑： NavigationView 会自动处理导航页面，无需 Frame 控件
		}
		
	}
}