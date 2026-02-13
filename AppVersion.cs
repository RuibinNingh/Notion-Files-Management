using System.Reflection;

namespace Notion_Files_Management
{
    /// <summary>
    /// 应用版本号管理类
    /// 版本号统一在 .csproj 的 InformationalVersion 属性中配置
    /// </summary>
    public static class AppVersion
    {
        /// <summary>
        /// 获取当前应用版本号（格式：X.X.X-Status）
        /// 示例：2.4.0-Stable, 2.5.0-Beta
        /// </summary>
        public static string Current
        {
            get
            {
                var assembly = Assembly.GetExecutingAssembly();
                var version = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
                
                if (string.IsNullOrEmpty(version))
                    return "Unknown";
                
                // 清理 Git commit hash (+ 号后面的部分)
                var plusIndex = version.IndexOf('+');
                if (plusIndex > 0)
                    version = version.Substring(0, plusIndex);
                
                return version;
            }
        }

        /// <summary>
        /// 获取版本号的数字部分（不含状态标识）
        /// 示例：2.4.0-Stable → 2.4.0
        /// </summary>
        public static string NumericVersion
        {
            get
            {
                var fullVersion = Current;
                var dashIndex = fullVersion.IndexOf('-');
                return dashIndex > 0 ? fullVersion.Substring(0, dashIndex) : fullVersion;
            }
        }

        /// <summary>
        /// 获取版本状态（Stable/Beta/等）
        /// 示例：2.4.0-Stable → Stable
        /// </summary>
        public static string Status
        {
            get
            {
                var fullVersion = Current;
                var dashIndex = fullVersion.IndexOf('-');
                return dashIndex > 0 ? fullVersion.Substring(dashIndex + 1) : "Unknown";
            }
        }

        /// <summary>
        /// 获取完整的版本信息字符串
        /// 格式：v{版本号}
        /// 示例：v2.4.0-Stable
        /// </summary>
        public static string FullVersionString => $"v{Current}";
    }
}
