using System;
using System.IO;
using System.Text.Json;
namespace Notion_Files_Management
{
	public class ConfigData
	{
		/// <summary>
		/// 默认主题色常量
		/// </summary>
		public const string DefaultThemeAccentColor = "#1E90FF";

		public string NotionToken { get; set; } = "";
		public string NotionBaseUrl { get; set; } = "https://api.notion.com/v1";
		// Download/Upload concurrency configured in Settings page
		public int MaxDownloadWorkers { get; set; } = 3;
		public int MaxUploadWorkers { get; set; } = 3;
		/// <summary>
		/// 主题色（Accent Color），格式为十六进制颜色值，如 "#1E90FF"
		/// </summary>
		public string ThemeAccentColor { get; set; } = DefaultThemeAccentColor;

		/// <summary>
		/// 背景材质类型，可选值："Mica"（云母）、"Acrylic"（亚克力）或 "Image"（图片/视频）
		/// 默认值："Mica"
		/// </summary>
		public string BackgroundMaterial { get; set; } = "Mica";

		/// <summary>
		/// 亚克力材质不透明度，范围 0.0-1.0
		/// 仅在 BackgroundMaterial 为 "Acrylic" 时生效
		/// 默认值：0.8
		/// </summary>
		public double AcrylicOpacity { get; set; } = 0.8;

		/// <summary>
		/// 背景图片/视频路径（仅在 BackgroundMaterial 为 "Image" 时生效）
		/// 支持 .png, .jpg, .jpeg, .bmp, .gif, .mp4 格式
		/// </summary>
		public string BackgroundImagePath { get; set; } = "";

		/// <summary>
		/// 背景图片/视频模糊度，范围 0-50（像素）
		/// 仅在 BackgroundMaterial 为 "Image" 时生效
		/// 默认值：0（不模糊）
		/// </summary>
		public double BackgroundImageBlur { get; set; } = 0;

		/// <summary>
		/// 背景图片/视频不透明度，范围 0.0-1.0
		/// 仅在 BackgroundMaterial 为 "Image" 时生效
		/// 默认值：0.3
		/// </summary>
		public double BackgroundImageOpacity { get; set; } = 0.3;
	}

	public static class ConfigManager
	{
		private static readonly string AppDataPath = Path.Combine(
			Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
			"NotionFilesManagement");

		private static readonly string FilePath = Path.Combine(AppDataPath, "config.json");

		public static ConfigData Current { get; private set; } = new ConfigData();

		static ConfigManager() => Load();

		public static void Load()
		{
			if (!File.Exists(FilePath))
				return;
			try
			{
				string json = File.ReadAllText(FilePath);
				Current = JsonSerializer.Deserialize<ConfigData>(json) ?? new ConfigData();
				// 兼容处理：如果 NotionBaseUrl 为空，设置默认值
				if (string.IsNullOrWhiteSpace(Current.NotionBaseUrl))
					Current.NotionBaseUrl = "https://api.notion.com/v1";
			}
			catch { }
		}

		public static void Save()
		{
			if (!Directory.Exists(AppDataPath))
				Directory.CreateDirectory(AppDataPath);
			string json = JsonSerializer.Serialize(Current, new JsonSerializerOptions { WriteIndented = true });
			File.WriteAllText(FilePath, json);
		}
	}
}
