using System.Windows.Controls;
using System.IO;
using System.Windows;
using System;
using System.Runtime;
using Python.Runtime;


namespace Notion_Files_Management.Views {
	public partial class ToolsPage : Page
    {
        public ToolsPage()
        {
            InitializeComponent();

			
		}
        public static string InvokePython(string input)
        {
            using (Py.GIL())
            {
                try
                {
                    dynamic pyModule = Py.Import("notion");// 导入notion.py
                    dynamic pyModuleObj = pyModule.Notion("notionToken");// 实例化，将 Notion 类提取，这里的传参是要传notion的token，我传了个假的占位
                    dynamic result = pyModuleObj.ceshi_pythonnet(input);// 调用并获取返回值
                    return result;
                }
                catch(PythonException ex)
                {
                    return $"Python报错:{ex.Message}";
                }
                catch(Exception ex)
                {
                    return $"C#报错:{ex.Message}";
                }
            }
        }
        private void btn_Click(object sender, RoutedEventArgs e)
        {
            string reply = InvokePython("Are you ok?");
            MessageBox.Show($"Python返回结果：{reply}");
        }
    }
}