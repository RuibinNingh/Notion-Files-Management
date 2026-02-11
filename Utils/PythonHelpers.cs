using System;
using Python.Runtime;

namespace Notion_Files_Management.Utils
{
    /// <summary>
    /// Shared helpers for safely reading values from Python dict-like objects.
    /// Keeps WPF pages slim and consistent.
    /// </summary>
    internal static class PythonHelpers
    {
        public static double ToDoubleSafe(dynamic dict, string key)
        {
            try
            {
                var v = dict[key];
                if (v == null) return 0.0;
                return Convert.ToDouble(v);
            }
            catch
            {
                return 0.0;
            }
        }

        public static int ToIntSafe(dynamic dict, string key)
        {
            try
            {
                var v = dict[key];
                if (v == null) return 0;
                return Convert.ToInt32(v);
            }
            catch
            {
                return 0;
            }
        }

        /// <summary>
        /// Python None / "None" / null / empty -> C# null
        /// </summary>
        public static string? NormalizePythonNone(dynamic dict, string key)
        {
            try
            {
                var v = dict[key];
                if (v == null) return null;

                var s = v.ToString();
                if (string.IsNullOrWhiteSpace(s) ||
                    string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
                    return null;

                return s;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Best-effort check whether a python object behaves like a Mapping (dict).
        /// </summary>
        public static bool IsPyMapping(dynamic obj)
        {
            try
            {
                dynamic collections = Py.Import("collections.abc");
                return collections.Mapping.__instancecheck__(obj);
            }
            catch
            {
                try { return obj is PyDict; }
                catch { return false; }
            }
        }
    }
}
