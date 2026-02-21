using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace Notion_Files_Management.Models
{
    /// <summary>
    /// 公告数据模型（对应 idx.json 中的单条公告 + 正文内容）
    /// </summary>
    public class NoticeItem : INotifyPropertyChanged
    {
        public string Id { get; set; } = "";
        public string Title { get; set; } = "";
        public string Date { get; set; } = "";
        public List<string> Tags { get; set; } = new();
        public bool Pinned { get; set; }

        // ══ 内联渲染所需 ══

        private string _content = "";
        /// <summary>
        /// 公告 Markdown 正文内容（从 {id}.md 加载）
        /// </summary>
        public string Content
        {
            get => _content;
            set { _content = value; OnPropertyChanged(); }
        }

        private bool _isLoading = true;
        /// <summary>
        /// 正文是否正在加载中
        /// </summary>
        public bool IsLoading
        {
            get => _isLoading;
            set { _isLoading = value; OnPropertyChanged(); }
        }

        public event PropertyChangedEventHandler? PropertyChanged;
        protected void OnPropertyChanged([CallerMemberName] string? name = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
