using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Microsoft.Win32;
using Python.Runtime;

namespace Notion_Files_Management.Views
{
	// C# 端用来勾选的包装类
	public class FileSelectItem
	{
		public string? real_name
		{
			get; set;
		}
		public double size_mb
		{
			get; set;
		}
		public bool IsSelected { get; set; } = true;
		public dynamic? raw_dict
		{
			get; set;
		} // 存储 Python 返回的原始字典
	}

	// 对应文档中 get_download_statuses 的返回结构
	public class DownloadTaskStatus
	{
		public string? real_name
		{
			get; set;
		}
		public string? status
		{
			get; set;
		}
		public double progress
		{
			get; set;
		}
		public double downloaded_mb
		{
			get; set;
		}
		public double total_mb
		{
			get; set;
		}
		public double speed_mb_s
		{
			get; set;
		}
		public int ETA
		{
			get; set;
		}
		public string? error
		{
			get; set;
		}
	}

	public partial class DownloadPage : Page
	{
		private dynamic? _pyMain;
		private DispatcherTimer _statusTimer;

		public ObservableCollection<FileSelectItem> FileSelectionList { get; set; } = new();
		public ObservableCollection<DownloadTaskStatus> DisplayTasks { get; set; } = new();

		public DownloadPage()
		{
			InitializeComponent();
			FileListSelector.ItemsSource = FileSelectionList;
			DownloadTaskListView.ItemsSource = DisplayTasks;

			_statusTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
			_statusTimer.Tick += UpdateStatusLoop;

			InitBackend();
		}

		private string _currentNotionToken = "";

		private void InitBackend()
		{
			Task.Run(() =>
			{
				using (Py.GIL())
				{
					try
					{
						// ✅ 1) 确保读取到最新配置（你 Settings 保存到 AppData 的就是这里）
						ConfigManager.Load();
						string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";

						if (string.IsNullOrEmpty(token))
						{
							Dispatcher.BeginInvoke(() =>
								MessageBox.Show("未检测到 Notion Token，请先到【设置】页保存 Token。"));
							return;
						}

						// ✅ 2) 设置 python 脚本路径
						dynamic sys = Py.Import("sys");
						string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
						sys.path.append(scriptsPath);

						// ✅ 3) 导入 main，并把 token 传进去
						dynamic mainMod = Py.Import("main");

						// 如果你希望 max_workers 可配，这里可以加第二个参数
						_pyMain = mainMod.Main(token);

						_currentNotionToken = token;
					}
					catch (Exception ex)
					{
						Dispatcher.BeginInvoke(() =>
							MessageBox.Show("初始化失败: " + ex.Message));
					}
				}
			});
		}

		private CancellationTokenSource? _getListCts;
		private int _getListReqId = 0; // 每次获取列表自增，防止旧任务回写UI


		// ========== 新增：打开下载对话框 ==========
		private void BtnOpenDownloadDialog_Click(object sender, RoutedEventArgs e)
		{
			ModalOverlay.Visibility = Visibility.Visible;
			ModalStep1.Visibility = Visibility.Visible;
			ModalStep2.Visibility = Visibility.Collapsed;
		}

		// --- 动作 1: 获取列表 (对应 get_download_list) ---
		private async void ConfirmId_Click(object sender, RoutedEventArgs e)
		{
			// 1) 读取 token，确保后端已用最新 token 初始化
			ConfigManager.Load();
			string latestToken = ConfigManager.Current?.NotionToken?.Trim() ?? "";
			if (string.IsNullOrEmpty(latestToken))
			{
				MessageBox.Show("Token 为空，请先到【设置】页保存 Token。");
				return;
			}

			if (_pyMain == null || latestToken != _currentNotionToken)
			{
				InitBackend();
				MessageBox.Show("检测到 Token 更新或后端未初始化，已重新初始化。请再点一次【获取列表】。");
				return;
			}

			// 2) 处理 PageId
			string pidRaw = PageIdInput.Text.Trim();
			if (string.IsNullOrEmpty(pidRaw) || _pyMain == null)
				return;

			// 你当前代码只去空格；这里我保留你的策略（不动业务假设）
			string pid = pidRaw.Replace(" ", "");

			// 3) 取消上一次请求
			_getListCts?.Cancel();
			_getListCts = new CancellationTokenSource();
			var token = _getListCts.Token;

			int reqId = ++_getListReqId;
			BtnConfirmId.IsEnabled = false;

			// 可选：给用户一个“正在获取”的可见反馈（如果你有状态栏/文本控件可以替换）
			// 这里用 Title 临时提示，不改 XAML 也能看到变化
			string oldTitle = Application.Current.MainWindow?.Title ?? "";
			if (Application.Current.MainWindow != null)
				Application.Current.MainWindow.Title = "正在获取文件列表…（可能需要 10~40 秒）";

			try
			{
				// 4) 后台跑 Python，并捕获 Python stdout/stderr
				var workTask = Task.Run(() =>
				{
					token.ThrowIfCancellationRequested();

					using (Py.GIL())
					{
						// ---- 捕获 Python 输出 ----
						dynamic sys = Py.Import("sys");
						dynamic io = Py.Import("io");

						dynamic oldOut = sys.stdout;
						dynamic oldErr = sys.stderr;
						dynamic bufOut = io.StringIO();
						dynamic bufErr = io.StringIO();

						sys.stdout = bufOut;
						sys.stderr = bufErr;

						try
						{
							dynamic pyList = _pyMain.get_download_list(pid);

							int pyLen = 0;
							try
							{
								pyLen = (int)pyList.__len__();
							}
							catch { }

							var result = new List<FileSelectItem>();
							foreach (var item in pyList)
							{
								token.ThrowIfCancellationRequested();

								result.Add(new FileSelectItem
								{
									real_name = item["real_name"]?.ToString(),
									size_mb = (double)(item["size_mb"] ?? 0.0),
									raw_dict = item // 先保留：不改 Py 的情况下，你下载还在用它
								});
							}

							string outText = "";
							string errText = "";
							try
							{
								outText = bufOut.getvalue().ToString();
							}
							catch { }
							try
							{
								errText = bufErr.getvalue().ToString();
							}
							catch { }

							return (result, pyLen, outText, errText);
						}
						finally
						{
							// 还原输出
							sys.stdout = oldOut;
							sys.stderr = oldErr;
						}
					}
				}, token);

				//// 5) C# 侧超时（比如 20 秒）
				//var timeoutTask = Task.Delay(TimeSpan.FromSeconds(20), token);
				//var finished = await Task.WhenAny(workTask, timeoutTask);

				//if (finished == timeoutTask)
				//{
				//	// 注意：不能强杀 Python 内部 requests，但我们可以“不再等它”，并给用户解释
				//	_getListCts.Cancel();

				//	MessageBox.Show(
				//		"获取列表超时（20 秒）。\n\n" +
				//		"可能原因：\n" +
				//		"1) Token 无效/无权限（常见：401/403）\n" +
				//		"2) 被 Notion 限流（429）\n" +
				//		"3) 网络超时（requests timeout=10 且最多重试 4 次，最差可接近 47 秒）\n\n" +
				//		"你可以再点一次获取，或先检查 Token / 页面权限。"
				//	);

				//	return;
				//}

				// 6) 取结果
				var res = await workTask;

				if (token.IsCancellationRequested || reqId != _getListReqId)
					return;

				var list = res.Item1;
				int pyLen = res.Item2;
				string pyOut = res.Item3;
				string pyErr = res.Item4;

				// 7) 为空就把 Python 输出直接给你（这是定位关键）
				if (list.Count == 0)
				{
					string msg =
						$"Python 返回 0 个文件项（pyList.__len__() = {pyLen}）。\n\n" +
						"Python 输出(stdout)：\n" + (string.IsNullOrWhiteSpace(pyOut) ? "(空)" : pyOut) + "\n\n" +
						"Python 输出(stderr)：\n" + (string.IsNullOrWhiteSpace(pyErr) ? "(空)" : pyErr) + "\n";

					MessageBox.Show(msg, "获取列表为空（用于定位）");
				}

				// 8) 更新 UI
				FileSelectionList.Clear();
				foreach (var x in list)
					FileSelectionList.Add(x);

				ModalStep1.Visibility = Visibility.Collapsed;
				ModalStep2.Visibility = Visibility.Visible;
			}
			catch (OperationCanceledException)
			{
				// ignore
			}
			catch (Exception ex)
			{
				MessageBox.Show("获取列表失败: " + ex.Message);
			}
			finally
			{
				if (Application.Current.MainWindow != null)
					Application.Current.MainWindow.Title = oldTitle;

				if (reqId == _getListReqId)
					BtnConfirmId.IsEnabled = true;
			}
		}





		// --- 动作 2: 提交下载 (对应 download_notion_files) ---
		private async void SubmitDownload_Click(object sender, RoutedEventArgs e)
		{
			if (string.IsNullOrEmpty(SavePathDisplay.Text) || _pyMain == null)
				return;

			// 过滤出用户勾选的项目
			var selected = FileSelectionList.Where(x => x.IsSelected).ToList();
			if (selected.Count == 0)
				return;

			string saveDir = SavePathDisplay.Text;

			await Task.Run(() => {
				using (Py.GIL())
				{
					// 构建符合文档要求的 download_list (Python 字典列表)
					PyList pyListToDownload = new PyList();
					foreach (var s in selected)
					{
						pyListToDownload.Append(s.raw_dict);
					}

					// 调用文档中的 download_notion_files
					_pyMain.download_notion_files(pyListToDownload, saveDir);
				}
			});

			ModalOverlay.Visibility = Visibility.Collapsed;
			if (!_statusTimer.IsEnabled)
				_statusTimer.Start();
		}

		// --- 动作 3: 状态更新轮询 (对应 get_download_statuses) ---
		private async void UpdateStatusLoop(object? sender, EventArgs e)
		{
			if (_pyMain == null)
				return;

			try
			{
				var statuses = await Task.Run(() =>
				{
					using (Py.GIL())
					{
						dynamic pyStatuses = _pyMain.get_download_statuses();

						var result = new List<DownloadTaskStatus>();
						foreach (var s in pyStatuses)
						{
							// 取字段时做容错
							string status = s["status"]?.ToString() ?? "";

							// ✅ 关键：过滤 completed（不动 Python 的情况下只能前端过滤）
							if (string.Equals(status, "completed", StringComparison.OrdinalIgnoreCase))
								continue;

							// 你也可以顺便过滤 cancelled/failed，看你想不想保留失败任务显示
							// if (status == "cancelled") continue;

							result.Add(new DownloadTaskStatus
							{
								real_name = s["real_name"]?.ToString(),
								status = status,
								progress = Convert.ToDouble(s["progress"] ?? 0.0),
								downloaded_mb = Convert.ToDouble(s["downloaded_mb"] ?? 0.0),
								total_mb = Convert.ToDouble(s["total_mb"] ?? 0.0),
								speed_mb_s = Convert.ToDouble(s["speed_mb_s"] ?? 0.0),
								ETA = Convert.ToInt32(s["ETA"] ?? 0),
								error = s["error"]?.ToString()
							});
						}

						return result;
					}
				});

				// UI 线程更新
				DisplayTasks.Clear();
				foreach (var x in statuses)
					DisplayTasks.Add(x);
			}
			catch
			{
				// 保持安静即可
			}
		}



		private void SelectFolder_Click(object sender, RoutedEventArgs e)
		{
			var dialog = new OpenFolderDialog();
			if (dialog.ShowDialog() == true)
				SavePathDisplay.Text = dialog.FolderName;
		}

		private void SelectAll_Click(object sender, RoutedEventArgs e)
		{
			foreach (var i in FileSelectionList)
				i.IsSelected = true;
			FileListSelector.Items.Refresh();
		}

		private void InvertSelect_Click(object sender, RoutedEventArgs e)
		{
			foreach (var i in FileSelectionList)
				i.IsSelected = !i.IsSelected;
			FileListSelector.Items.Refresh();
		}

		// ========== 新增：返回 Step1 ==========
		private void BackToStep1_Click(object sender, RoutedEventArgs e)
		{
			ModalStep2.Visibility = Visibility.Collapsed;
			ModalStep1.Visibility = Visibility.Visible;
		}

		private void CloseModal_Click(object sender, RoutedEventArgs e)
		{
			// 取消获取列表（只能做到“取消回写UI/取消等待”，不能强杀Python内部请求）
			_getListCts?.Cancel();

			// 立刻恢复按钮，避免下次打开还是灰
			BtnConfirmId.IsEnabled = true;

			ModalOverlay.Visibility = Visibility.Collapsed;
			ModalStep1.Visibility = Visibility.Collapsed;
			ModalStep2.Visibility = Visibility.Collapsed;
		}

	}
}