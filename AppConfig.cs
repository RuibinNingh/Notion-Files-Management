using System;
using System.IO;
using System.Text.Json;

namespace Notion_Files_Management
{
	public class ConfigData
	{
		public string NotionToken { get; set; } = "";
		public string NotionBaseUrl { get; set; } = "https://api.notion.com/v1";
		// Download/Upload concurrency configured in Settings page
		public int MaxDownloadWorkers { get; set; } = 3;
		public int MaxUploadWorkers { get; set; } = 3;
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
			string json = JsonSerializer.Serialize(Current);
			File.WriteAllText(FilePath, json);
		}
	}
}