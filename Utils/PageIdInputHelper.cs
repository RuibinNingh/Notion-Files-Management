using System;
using System.Windows.Controls;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// 辅助类：处理 PageId 输入框的格式化逻辑
    /// 避免在多个页面中重复相同的代码
    /// </summary>
    public static class PageIdInputHelper
    {
        /// <summary>
        /// 处理 PageId 输入框的 TextChanged 事件
        /// 自动格式化输入的 PageId，并显示错误提示
        /// </summary>
        /// <param name="textBox">输入框控件</param>
        /// <param name="errorTextBlock">用于显示错误提示的 TextBlock（可选）</param>
        /// <param name="isFormattingFlag">用于避免递归格式化的标志引用</param>
        public static void HandleTextChanged(TextBox textBox, TextBlock? errorTextBlock, ref bool isFormattingFlag)
        {
            if (isFormattingFlag)
                return;

            try
            {
                var (formatted, isValid, hint) = NotionPageId.AutoFormat(textBox.Text);
                
                if (errorTextBlock != null)
                    errorTextBlock.Text = hint;

                if (isValid && !string.Equals(textBox.Text, formatted, StringComparison.Ordinal))
                {
                    isFormattingFlag = true;
                    textBox.Text = formatted;
                    textBox.CaretIndex = formatted.Length;
                }
            }
            finally
            {
                isFormattingFlag = false;
            }
        }
    }
}
