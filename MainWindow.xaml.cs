using System;
using Wpf.Ui.Controls;
using Wpf.Ui.Appearance;
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

			// 使用 ContentRendered 事件，确保窗口内容完全渲染后再设置背景材质
			ContentRendered += (sender, args) =>
			{
				// 延迟一小段时间，确保窗口完全显示
				Dispatcher.BeginInvoke(new Action(() =>
				{
					ApplyBackgroundMaterial();
				}), System.Windows.Threading.DispatcherPriority.Background);
			};
		}

		/// <summary>
		/// 应用背景材质配置
		/// </summary>
		private void ApplyBackgroundMaterial()
		{
			// 确保窗口已经显示
			if (!IsLoaded || !IsVisible)
			{
				Utils.Logger.Warn("[MainWindow] Window not ready, skip applying background material");
				return;
			}

			try
			{
				ConfigManager.Load();
				string material = ConfigManager.Current?.BackgroundMaterial ?? "Mica";
				if (string.IsNullOrWhiteSpace(material) || (material != "Mica" && material != "Acrylic"))
					material = "Mica";

				// 应用背景材质类型
				if (material == "Acrylic")
				{
					WindowBackdropType = WindowBackdropType.Acrylic;
					
					// 应用不透明度（WPF-UI 的 Acrylic 不透明度通过 TintOpacity 设置）
					double opacity = ConfigManager.Current?.AcrylicOpacity ?? 0.8;
					if (opacity < 0.0 || opacity > 1.0)
						opacity = 0.8;
					
					// 注意：WPF-UI 4.2.0 的 FluentWindow 可能不直接支持 TintOpacity 属性
					// 这里我们设置 WindowBackdropType，不透明度由系统控制
					// 如果需要更精细的控制，可能需要使用其他方法
				}
				else
				{
					WindowBackdropType = WindowBackdropType.Mica;
				}
			}
			catch (ArgumentException argEx)
			{
				// ArgumentException 通常表示系统不支持该背景材质类型或窗口状态不正确
				Utils.Logger.Error($"[MainWindow] Apply background material failed (ArgumentException): {argEx.Message}", argEx);
				// 不再次尝试设置，避免循环错误
			}
			catch (Exception ex)
			{
				Utils.Logger.Error("[MainWindow] Apply background material failed", ex);
				// 不再次尝试设置，避免循环错误
			}
		}
	}
}
