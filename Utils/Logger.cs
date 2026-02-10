using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

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
				Console.WriteLine($"[{ts}][T{tid}][{lvl}] {message}");
				if (ex != null)
				{
					Console.WriteLine(ex);
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
