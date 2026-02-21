using System;
using System.IO;
using System.Net.Http;
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
		private static readonly HttpClient _bgHttpClient = new HttpClient
		{
			Timeout = TimeSpan.FromSeconds(30)
		};

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
				string material = ConfigManager.Current?.BackgroundMaterial ?? "AutoPush";
				if (string.IsNullOrWhiteSpace(material) || 
				    (material != "Mica" && material != "Acrylic" && material != "Image" && material != "AutoPush"))
					material = "AutoPush";

				// 先清理之前的背景图片/视频状态
				CleanupBackgroundMedia();

				if (material == "AutoPush")
				{
					_ = ApplyAutoPushBackgroundAsync();
				}
				else if (material == "Image")
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
		/// 应用自动推送背景（异步：检查缓存→下载→应用）
		/// </summary>
		private async System.Threading.Tasks.Task ApplyAutoPushBackgroundAsync()
		{
			try
			{
				string src = ConfigManager.Current?.AutoPushBackgroundSrc ?? "";
				string name = ConfigManager.Current?.AutoPushBackgroundName ?? "";
				double transparency = ConfigManager.Current?.AutoPushTransparency ?? 0.3;
				if (transparency < 0.0) transparency = 0.0;
				if (transparency > 1.0) transparency = 1.0;

				// 如果没有配置 src，尝试从远端获取默认
				if (string.IsNullOrWhiteSpace(src))
				{
					Utils.Logger.Info("[MainWindow] AutoPush: No src configured, fetching default from server...");
					try
					{
						string json = "";
						try { json = await _bgHttpClient.GetStringAsync("https://nfm.ruibin-ningh.top/background/config.json"); }
						catch { json = await _bgHttpClient.GetStringAsync("http://nfm.ruibin-ningh.top/background/config.json"); }

						var config = System.Text.Json.JsonSerializer.Deserialize<AutoPushBgConfig>(json);
						if (config?.@default != null)
						{
							src = config.@default.src;
							name = config.@default.name;
							// 保存到配置以便下次使用
							ConfigManager.Current.AutoPushBackgroundSrc = src;
							ConfigManager.Current.AutoPushBackgroundName = name;
							ConfigManager.Save();
						}
					}
					catch (Exception fetchEx)
					{
						Utils.Logger.Warn($"[MainWindow] AutoPush: Failed to fetch config: {fetchEx.Message}");
						// 回退到 Mica
						Dispatcher.Invoke(() => { WindowBackdropType = WindowBackdropType.Mica; });
						return;
					}
				}

				if (string.IsNullOrWhiteSpace(src))
				{
					Utils.Logger.Warn("[MainWindow] AutoPush: src still empty after fetch, falling back to Mica");
					Dispatcher.Invoke(() => { WindowBackdropType = WindowBackdropType.Mica; });
					return;
				}

				// 检查本地缓存
				string cacheDir = GetBgCacheDir();
				string fileName = Path.GetFileName(src);
				string cachedPath = Path.Combine(cacheDir, fileName);

				if (!File.Exists(cachedPath))
				{
					Utils.Logger.Info($"[MainWindow] AutoPush: Downloading {src} → {cachedPath}");
					try
					{
						string fullUrl;
						try
						{
							fullUrl = "https://nfm.ruibin-ningh.top" + src;
							var testBytes = await _bgHttpClient.GetByteArrayAsync(fullUrl);
							await File.WriteAllBytesAsync(cachedPath, testBytes);
						}
						catch
						{
							fullUrl = "http://nfm.ruibin-ningh.top" + src;
							var testBytes = await _bgHttpClient.GetByteArrayAsync(fullUrl);
							await File.WriteAllBytesAsync(cachedPath, testBytes);
						}
					}
					catch (Exception dlEx)
					{
						Utils.Logger.Error($"[MainWindow] AutoPush: Download failed: {dlEx.Message}");
						Dispatcher.Invoke(() => { WindowBackdropType = WindowBackdropType.Mica; });
						return;
					}
				}

				// 应用缓存的文件
				Dispatcher.Invoke(() =>
				{
					try
					{
						ApplyAutoPushFile(cachedPath, transparency);
					}
					catch (Exception applyEx)
					{
						Utils.Logger.Error("[MainWindow] AutoPush: Apply failed", applyEx);
						WindowBackdropType = WindowBackdropType.Mica;
					}
				});
			}
			catch (Exception ex)
			{
				Utils.Logger.Error("[MainWindow] ApplyAutoPushBackgroundAsync failed", ex);
				try { Dispatcher.Invoke(() => { WindowBackdropType = WindowBackdropType.Mica; }); } catch { }
			}
		}

		/// <summary>
		/// 应用自动推送的本地缓存文件（在 UI 线程调用）
		/// </summary>
		private void ApplyAutoPushFile(string filePath, double transparency)
		{
			string ext = Path.GetExtension(filePath).ToLowerInvariant();
			bool isVideo = ext == ".mp4";
			bool isImage = ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".gif" || ext == ".webp";

			if (!isVideo && !isImage)
			{
				Utils.Logger.Warn($"[MainWindow] AutoPush: Unsupported file format: {ext}");
				WindowBackdropType = WindowBackdropType.Mica;
				return;
			}

			// 透明度：值越大越透明，所以 opacity = 1 - transparency
			double opacity = 1.0 - transparency;
			if (opacity < 0.0) opacity = 0.0;
			if (opacity > 1.0) opacity = 1.0;

			WindowBackdropType = WindowBackdropType.None;

			if (isImage)
			{
				var bitmap = new BitmapImage();
				bitmap.BeginInit();
				bitmap.UriSource = new Uri(filePath, UriKind.Absolute);
				bitmap.CacheOption = BitmapCacheOption.OnLoad;
				bitmap.EndInit();
				bitmap.Freeze();

				BackgroundImage.Source = bitmap;
				BackgroundImage.Opacity = opacity;
				BackgroundImage.Effect = null;
				BackgroundImage.Visibility = Visibility.Visible;
				BackgroundVideo.Visibility = Visibility.Collapsed;
			}
			else // isVideo
			{
				BackgroundVideo.Source = new Uri(filePath, UriKind.Absolute);
				BackgroundVideo.Opacity = opacity;
				BackgroundVideo.Effect = null;
				BackgroundVideo.Visibility = Visibility.Visible;
				BackgroundImage.Visibility = Visibility.Collapsed;

				BackgroundVideo.MediaEnded += OnBackgroundVideoEnded;
				BackgroundVideo.Play();
			}

			BackgroundOverlay.Opacity = transparency;
			BackgroundMediaLayer.Visibility = Visibility.Visible;

			Utils.Logger.Info($"[MainWindow] AutoPush applied: {filePath}, transparency={transparency}");
		}

		/// <summary>
		/// 获取背景缓存目录
		/// </summary>
		private static string GetBgCacheDir()
		{
			string dir = Path.Combine(
				Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
				"NotionFilesManagement", "background_cache");
			if (!Directory.Exists(dir))
				Directory.CreateDirectory(dir);
			return dir;
		}

		// 简易数据模型供 MainWindow 反序列化远端配置
		private sealed class AutoPushBgConfig
		{
			public AutoPushBgPreset? @default { get; set; }
			public AutoPushBgPreset[] list { get; set; } = Array.Empty<AutoPushBgPreset>();
		}
		private sealed class AutoPushBgPreset
		{
			public string name { get; set; } = "";
			public string src { get; set; } = "";
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
