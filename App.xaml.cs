﻿using System;
using System.IO;
using System.Windows;
using System.Windows.Media;
using Python.Runtime;
using Notion_Files_Management.Utils;
using Wpf.Ui.Appearance;

namespace Notion_Files_Management
{
	public partial class App : System.Windows.Application
	{
		protected override void OnStartup(StartupEventArgs e)
		{
			base.OnStartup(e);

			// 1. 应用深色主题 (这步会从系统读取默认颜色)
			ApplicationThemeManager.Apply(ApplicationTheme.Dark);

		// 2. 应用主题色配置
			ConfigManager.Load();
			string themeColorHex = ConfigManager.Current?.ThemeAccentColor ?? ConfigData.DefaultThemeAccentColor;
			if (string.IsNullOrWhiteSpace(themeColorHex))
				themeColorHex = ConfigData.DefaultThemeAccentColor;
			
			// 确保颜色值格式正确
			if (!themeColorHex.StartsWith("#"))
				themeColorHex = "#" + themeColorHex;
			
			// 解析颜色值
			System.Windows.Media.Color accentColor;
			try
			{
				accentColor = (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString(themeColorHex);
			}
			catch
			{
				// 如果解析失败，使用默认颜色
				accentColor = System.Windows.Media.Color.FromRgb(0x1E, 0x90, 0xFF);
			}
			
			// 应用主题色到所有 Accent 颜色变体
			ApplicationAccentColorManager.Apply(
				systemAccent: accentColor,
				primaryAccent: accentColor,
				secondaryAccent: accentColor,
				tertiaryAccent: accentColor
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
			try
			{
				PythonEngine.Shutdown(); // 彻底释放内存，关闭 Python 引擎
			}
			catch (Exception ex)
			{
				// Python 引擎关闭失败不应阻止应用退出（重启场景中尤为重要）
				System.Diagnostics.Debug.WriteLine($"PythonEngine.Shutdown failed: {ex.Message}");
			}
			// Shutdown file logging
			Logger.ShutdownFileLogging();
			base.OnExit(e);
		}
	}
}