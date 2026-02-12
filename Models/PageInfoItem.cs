using System;

namespace Notion_Files_Management.Models
{
    public sealed class PageInfoItem
    {
        public string RealName { get; set; } = "";
        public string Url { get; set; } = "";
        public double SizeGb { get; set; }

        public string SizeGbText => Math.Round(SizeGb, 3).ToString("0.###");
    }
}
