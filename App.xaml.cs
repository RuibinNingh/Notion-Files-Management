﻿using System;
using System.IO;
using System.Windows;
using System.Windows.Media;
using Python.Runtime;
using Notion_Files_Management.Utils;
using Wpf.Ui.Appearance;

namespace Notion_Files_Management
{
	public partial class App : Application
	{
		protected override void OnStartup(StartupEventArgs e)
		{
			base.OnStartup(e);

			// 1. 应用深色主题 (这步会从系统读取默认颜色)
			ApplicationThemeManager.Apply(ApplicationTheme.Dark);

		// 2. 【方案 A】强制覆盖所有 Accent 颜色变体为同色
			// 这样按钮、进度条等常用元素都会用到 #1E90FF，而不是自动生成的浅化版本
			var forcedAccent = System.Windows.Media.Color.FromRgb(0x1E, 0x90, 0xFF); // #1E90FF
			ApplicationAccentColorManager.Apply(
				systemAccent: forcedAccent,
				primaryAccent: forcedAccent,
				secondaryAccent: forcedAccent,
				tertiaryAccent: forcedAccent
			);




			// Init file logging first
			Logger.InitFileLogging();

			string baseDir = AppDomain.CurrentDomain.BaseDirectory;
			// 修正 DLL 名称和路径拼接
			Runtime.PythonDLL = Path.Combine(baseDir, "PythonEnv", "python311.dll");

			PythonEngine.Initialize();
			PythonEngine.BeginAllowThreads();

			// 重要：把 Scripts 目录告诉 Python
			using (Py.GIL())
			{
				dynamic sys = Py.Import("sys");
				string scriptsPath = Path.Combine(baseDir, "Scripts");
				sys.path.append(scriptsPath);
				// 下面可以在这个using里调用Python函数了
			}
		}

		protected override void OnExit(ExitEventArgs e)
		{
			PythonEngine.Shutdown(); // 彻底释放内存，关闭 Python 引擎
									 // Shutdown file logging
			Logger.ShutdownFileLogging();
			base.OnExit(e);
		}
	}
}