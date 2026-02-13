using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.IO;

namespace Notion_Files_Management.Utils
{
	/// <summary>
	/// 简单、稳定、零依赖的控制台日志。
	/// - 时间戳 + 线程 + 级别
	/// - 可选输出异常
	/// - 启动时确保 Console 可用（必要时 AllocConsole）
	/// </summary>
	internal static class Logger
	{
		public enum Level { Debug, Info, Warn, Error }

		private static readonly object _lock = new();
		public static Level MinLevel { get; set; } = Level.Debug;
		public static bool Enabled { get; set; } = true;

		private static StreamWriter? _file;
		private static string? _filePath;

		public static void InitConsole(bool forceAllocConsole = false)
		{
			try
			{
				// 如果没有控制台（例如 WinExe 或双击启动），可选择创建一个。
				if (forceAllocConsole && GetConsoleWindow() == IntPtr.Zero)
				{
					AllocConsole();
				}

				Console.OutputEncoding = Encoding.UTF8;
				Console.InputEncoding = Encoding.UTF8;

				// 让 Trace/Debug 也走到 Console（可选）。
				if (Trace.Listeners.Count == 0)
				{
					Trace.Listeners.Add(new TextWriterTraceListener(Console.Out));
					Trace.AutoFlush = true;
				}
			}
			catch
			{
				// ignore
			}
		}

		public static void InitFileLogging()
		{
			try
			{
				var baseDir = AppContext.BaseDirectory;
				var logDir = Path.Combine(baseDir, "logs");
				Directory.CreateDirectory(logDir);

				var ts = DateTime.Now.ToString("yyyyMMddHHmmss"); // 20260210161308
				_filePath = Path.Combine(logDir, $"{ts}-C#.logs");
				_file = new StreamWriter(_filePath, append: true, Encoding.UTF8) { AutoFlush = true };

				Info($"File logging enabled: {_filePath}");
			}
			catch
			{
				// ignore
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
		// Backwards-compatible alias used in some files
		public static void Warning(string message) => Warn(message);
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

		[DllImport("kernel32.dll")] private static extern bool AllocConsole();
		[DllImport("kernel32.dll")] private static extern IntPtr GetConsoleWindow();
	}
}
