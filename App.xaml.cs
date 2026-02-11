using System.Configuration;
using System.Data;
using System.Windows;
using Python.Runtime;
using Notion_Files_Management.Views;
using Wpf.Ui.Controls;
using System.Windows.Controls;
using System.IO;
using System;
using System.Runtime;
using Notion_Files_Management.Utils;
using Wpf.Ui.Appearance;
using System.Windows.Media;

namespace Notion_Files_Management
{
    public partial class App : Application
    {
		protected override void OnStartup(StartupEventArgs e)
		{
			base.OnStartup(e);

			// 设置更蓝的主题色
			ApplicationAccentColorManager.Apply(
				Color.FromArgb(0xFF, 0x00, 0x66, 0xCC),
				ApplicationTheme.Dark
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
