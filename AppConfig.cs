using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

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
		/// 当前应用版本，格式为 {major}.{minor}.{patch}-{State}
		/// 状态可选：Stable / Beta
		/// 由构建/安装程序写入；运行时只读。
		/// </summary>
		[JsonPropertyName("version")]
		public string AppVersion { get; set; } = "1.0.2-Beta";
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
				// 兼容处理：版本号为空则使用默认值
				if (string.IsNullOrWhiteSpace(Current.AppVersion))
					Current.AppVersion = "1.0.0-Beta";
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
