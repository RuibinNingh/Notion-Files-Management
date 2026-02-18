using System;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
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
				if (string.IsNullOrWhiteSpace(material) || 
				    (material != "Mica" && material != "Acrylic" && material != "Image"))
					material = "Mica";

				// 先清理之前的背景图片/视频状态
				CleanupBackgroundMedia();

				if (material == "Image")
				{
					ApplyImageBackground();
				}
				else if (material == "Acrylic")
				{
					WindowBackdropType = WindowBackdropType.Acrylic;

					double opacity = ConfigManager.Current?.AcrylicOpacity ?? 0.8;
					if (opacity < 0.0 || opacity > 1.0)
						opacity = 0.8;
				}
				else
				{
					WindowBackdropType = WindowBackdropType.Mica;
				}
			}
			catch (ArgumentException argEx)
			{
				Utils.Logger.Error($"[MainWindow] Apply background material failed (ArgumentException): {argEx.Message}", argEx);
			}
			catch (Exception ex)
			{
				Utils.Logger.Error("[MainWindow] Apply background material failed", ex);
			}
		}

		/// <summary>
		/// 应用图片/视频背景
		/// </summary>
		private void ApplyImageBackground()
		{
			try
			{
				string imagePath = ConfigManager.Current?.BackgroundImagePath ?? "";
				double blur = ConfigManager.Current?.BackgroundImageBlur ?? 0;
				double opacity = ConfigManager.Current?.BackgroundImageOpacity ?? 0.3;

				// 校验参数
				if (blur < 0) blur = 0;
				if (blur > 50) blur = 50;
				if (opacity < 0.0) opacity = 0.0;
				if (opacity > 1.0) opacity = 1.0;

				if (string.IsNullOrWhiteSpace(imagePath) || !File.Exists(imagePath))
				{
					Utils.Logger.Warn($"[MainWindow] Background image path invalid or not found: {imagePath}");
					// 回退到 Mica
					WindowBackdropType = WindowBackdropType.Mica;
					return;
				}

				string ext = Path.GetExtension(imagePath).ToLowerInvariant();
				bool isVideo = ext == ".mp4";
				bool isImage = ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".gif";

				if (!isVideo && !isImage)
				{
					Utils.Logger.Warn($"[MainWindow] Unsupported background file format: {ext}");
					WindowBackdropType = WindowBackdropType.Mica;
					return;
				}

				// 设置为 None 背景，因为我们自己绘制背景
				WindowBackdropType = WindowBackdropType.None;

				// 设置模糊效果
				BlurEffect? blurEffect = blur > 0 ? new BlurEffect { Radius = blur, KernelType = KernelType.Gaussian } : null;

				if (isImage)
				{
					var bitmap = new BitmapImage();
					bitmap.BeginInit();
					bitmap.UriSource = new Uri(imagePath, UriKind.Absolute);
					bitmap.CacheOption = BitmapCacheOption.OnLoad;
					bitmap.EndInit();
					bitmap.Freeze();

					BackgroundImage.Source = bitmap;
					BackgroundImage.Opacity = opacity;
					BackgroundImage.Effect = blurEffect;
					BackgroundImage.Visibility = Visibility.Visible;
					BackgroundVideo.Visibility = Visibility.Collapsed;
				}
				else // isVideo
				{
					BackgroundVideo.Source = new Uri(imagePath, UriKind.Absolute);
					BackgroundVideo.Opacity = opacity;
					BackgroundVideo.Effect = blurEffect;
					BackgroundVideo.Visibility = Visibility.Visible;
					BackgroundImage.Visibility = Visibility.Collapsed;

					// 循环播放
					BackgroundVideo.MediaEnded += OnBackgroundVideoEnded;
					BackgroundVideo.Play();
				}

				// 设置覆盖层不透明度（反向：背景越不透明，覆盖层越透明）
				BackgroundOverlay.Opacity = 1.0 - opacity;
				BackgroundMediaLayer.Visibility = Visibility.Visible;

				Utils.Logger.Info($"[MainWindow] Applied background {(isVideo ? "video" : "image")}: {imagePath}, blur={blur}, opacity={opacity}");
			}
			catch (Exception ex)
			{
				Utils.Logger.Error("[MainWindow] Apply image background failed", ex);
				// 回退到 Mica
				WindowBackdropType = WindowBackdropType.Mica;
				CleanupBackgroundMedia();
			}
		}

		/// <summary>
		/// 背景视频播放结束事件处理（循环播放）
		/// </summary>
		private void OnBackgroundVideoEnded(object? sender, RoutedEventArgs e)
		{
			if (BackgroundVideo != null)
			{
				BackgroundVideo.Position = TimeSpan.Zero;
				BackgroundVideo.Play();
			}
		}

		/// <summary>
		/// 清理背景图片/视频资源
		/// </summary>
		private void CleanupBackgroundMedia()
		{
			try
			{
				BackgroundMediaLayer.Visibility = Visibility.Collapsed;
				BackgroundImage.Source = null;
				BackgroundImage.Visibility = Visibility.Collapsed;
				BackgroundImage.Effect = null;

				BackgroundVideo.MediaEnded -= OnBackgroundVideoEnded;
				BackgroundVideo.Stop();
				BackgroundVideo.Source = null;
				BackgroundVideo.Visibility = Visibility.Collapsed;
				BackgroundVideo.Effect = null;
			}
			catch (Exception ex)
			{
				Utils.Logger.Error("[MainWindow] Cleanup background media failed", ex);
			}
		}
	}
}
