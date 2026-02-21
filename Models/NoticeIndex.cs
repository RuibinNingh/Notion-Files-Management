using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Notion_Files_Management.Models
{
    /// <summary>
    /// 公告索引模型（对应 idx.json 反序列化）
    /// </summary>
    public class NoticeIndex
    {
        [JsonPropertyName("notices")]
        public List<NoticeItem> Notices { get; set; } = new();
    }
}
