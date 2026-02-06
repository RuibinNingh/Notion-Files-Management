using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Navigation;
using System.Windows.Shapes;
using System.IO;
using System;
using System.Runtime;

namespace Notion_Files_Management
{
    /// <summary>
    /// Interaction logic for MainWindow.xaml
    /// </summary>
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();

            // 配置并启动Python内置
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string pythonPath = Path.Combine(baseDir, "PythonEnv", "python311.dll");
            Runtime.PythonDLL = pythonPath;
            PythonEngine.Initialize();
		}
    }
}