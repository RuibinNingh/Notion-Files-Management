using System;
using System.Diagnostics;
using System.Text;
using System.IO;

namespace Notion_Files_Management.Utils
{
	/// <summary>
	/// 简单、稳定、零依赖的日志。
	/// - 时间戳 + 线程 + 级别
	/// - 可选输出异常
	/// - 支持文件日志
	/// </summary>
	internal static class Logger
	{
		public enum Level { Debug, Info, Warn, Error }

		private static readonly object _lock = new();
		public static Level MinLevel { get; set; } = Level.Debug;
		public static bool Enabled { get; set; } = true;

		private static StreamWriter? _file;
		private static string? _filePath;

		/// <summary>
		/// 获取日志文件夹路径
		/// </summary>
		public static string? LogDirectory { get; private set; }

		public static void InitFileLogging()
		{
			try
			{
				// 使用 AppData 目录（与配置文件保持一致）
				var appDataDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
				var appFolder = Path.Combine(appDataDir, "NotionFilesManagement");
				var logDir = Path.Combine(appFolder, "logs");
				
				// 确保日志目录存在
				if (!Directory.Exists(logDir))
				{
					Directory.CreateDirectory(logDir);
				}
				
				LogDirectory = logDir;

				var ts = DateTime.Now.ToString("yyyyMMddHHmmss"); // 20260210161308
				_filePath = Path.Combine(logDir, $"{ts}-C#.logs");
				_file = new StreamWriter(_filePath, append: true, Encoding.UTF8) { AutoFlush = true };

				Info($"File logging enabled: {_filePath}");
			}
			catch (Exception ex)
			{
				// 如果无法创建日志文件，至少尝试输出到控制台
				try
				{
					Console.WriteLine($"[Logger] Failed to initialize file logging: {ex.Message}");
				}
				catch { }
			}
		}

		public static void ShutdownFileLogging()
		{
			try { _file?.Dispose(); } catch { }
			_file = null;
		}

		public static void Debug(string message) => Write(Level.Debug, message);
		public static void Info(string message) => Write(Level.Info, message);
		public static void Warn(string message) => Write(Level.Warn, message);
		public static void Error(string message, Exception? ex = null) => Write(Level.Error, message, ex);

		public static IDisposable Time(string scopeName)
		{
			return new ScopeTimer(scopeName);
		}

		private static void Write(Level level, string message, Exception? ex = null)
		{
			if (!Enabled || level < MinLevel)
				return;

			var ts = DateTime.Now.ToString("HH:mm:ss.fff");
			var tid = Environment.CurrentManagedThreadId;
			var lvl = level.ToString().ToUpperInvariant();

			lock (_lock)
			{
				var line = $"[{ts}][T{tid}][{lvl}] {message}";
				Console.WriteLine(line);
				if (_file != null) _file.WriteLine(line);

				if (ex != null)
				{
					Console.WriteLine(ex);
					if (_file != null) _file.WriteLine(ex.ToString());
				}
			}
		}

		private sealed class ScopeTimer : IDisposable
		{
			private readonly Stopwatch _sw = Stopwatch.StartNew();
			private readonly string _name;
			public ScopeTimer(string name)
			{
				_name = name;
				Logger.Debug($"BEGIN {_name}");
			}
			public void Dispose()
			{
				_sw.Stop();
				Logger.Debug($"END   {_name} ({_sw.ElapsedMilliseconds} ms)");
			}
		}

	}
}
