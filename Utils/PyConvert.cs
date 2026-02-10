using System;
using System.Globalization;
using Python.Runtime;

namespace Notion_Files_Management.Utils
{
    internal static class PyConvert
    {
        public static int ToInt(dynamic? v, int fallback = 0)
        {
            if (v is null) return fallback;
            try
            {
                if (v is PyObject po) return po.As<int>();
            }
            catch { /* ignore */ }

            try
            {
                var s = v.ToString();
                if (string.IsNullOrWhiteSpace(s) || string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                    return fallback;
                if (int.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out int i))
                    return i;
            }
            catch { /* ignore */ }

            return fallback;
        }

        public static double ToDouble(dynamic? v, double fallback = 0)
        {
            if (v is null) return fallback;
            try
            {
                if (v is PyObject po) return po.As<double>();
            }
            catch { /* ignore */ }

            try
            {
                var s = v.ToString();
                if (string.IsNullOrWhiteSpace(s) || string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                    return fallback;
                if (double.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out double d))
                    return d;
            }
            catch { /* ignore */ }

            return fallback;
        }
    }
}
