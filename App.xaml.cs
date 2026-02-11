using System;
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

			// 先确保应用主题已正确应用（避免资源刷子与视觉不一致）
			ApplicationThemeManager.Apply(ApplicationTheme.Dark);
			
			// 直接修改应用资源中的 Accent 颜色，绕过 WpfUI 的内部转换
			try
			{
				var accentColor = Color.FromArgb(0xFF, 0x1E, 0x90, 0xFF); // #1E90FF
				if (this.Resources.Contains("SystemAccentColor"))
				{
					this.Resources["SystemAccentColor"] = accentColor;
				}
				System.Diagnostics.Debug.WriteLine($"[App.OnStartup] Accent color set to #1E90FF (RGB: {accentColor.R}, {accentColor.G}, {accentColor.B})");
			}
			catch (Exception ex)
			{
				System.Diagnostics.Debug.WriteLine($"[App.OnStartup] Failed to set accent color: {ex.Message}");
			}

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
