using System;
using Wpf.Ui.Controls;
using Notion_Files_Management.Views;

namespace Notion_Files_Management
{
	public partial class MainWindow : FluentWindow
	{
		public MainWindow()
		{
			InitializeComponent();

			Loaded += (sender, args) =>
			{
				RootNavigation.Navigate(typeof(DashboardPage));
			};
		}
	}
}
