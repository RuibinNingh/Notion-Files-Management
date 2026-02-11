using System;

namespace Notion_Files_Management.Services
{
    /// <summary>
    /// Simple app-wide event hub for "tasks were reset" notifications.
    /// Pages can subscribe and clear their local UI state.
    /// </summary>
    public static class TaskResetNotifier
    {
        public static event Action? TasksReset;

        public static void NotifyTasksReset()
        {
            TasksReset?.Invoke();
        }
    }
}
