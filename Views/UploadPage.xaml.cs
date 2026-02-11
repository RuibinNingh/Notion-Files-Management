using Microsoft.Win32;
using Python.Runtime;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Notion_Files_Management.Services;
using Notion_Files_Management.Utils;
using static Notion_Files_Management.Utils.PythonHelpers;

namespace Notion_Files_Management.Views
{
	public partial class UploadPage : Page
	{
		// ====== UI 数据源 ======
		public ObservableCollection<string> SelectedUploadFiles { get; } = new();
		public ObservableCollection<UploadTaskStatus> DisplayUploads { get; } = new();

		private readonly PythonBackendHost _backend = PythonBackendHost.Instance;

		// ====== 轮询 & EMA ======
		private readonly DispatcherTimer _statusTimer = new DispatcherTimer();
		private readonly Dictionary<string, double> _speedEma = new(StringComparer.OrdinalIgnoreCase);
		private const double SpeedEmaAlpha = 0.2; // 0.1~0.3 越小越平滑

		public UploadPage()
		{
			InitializeComponent();
			DataContext = this;

			_statusTimer.Interval = TimeSpan.FromSeconds(1);
			_statusTimer.Tick += UploadStatusTick;

			TaskResetNotifier.TasksReset += OnTasksReset;
			Unloaded += (_, __) => { TaskResetNotifier.TasksReset -= OnTasksReset; };
		}

		// ========== UI：打开/关闭模态 ==========
		private void BtnOpenUploadDialog_Click(object sender, RoutedEventArgs e)
		{
			ModalHint.Text = "";
			BtnConfirmStart.IsEnabled = true;

			ModalOverlay.Visibility = Visibility.Visible;
			ModalStep1.Visibility = Visibility.Visible;
		}

		private void CloseModal_Click(object sender, RoutedEventArgs e)
		{
			ModalOverlay.Visibility = Visibility.Collapsed;
			ModalStep1.Visibility = Visibility.Collapsed;
		}

		// ========== UI：选择文件 ==========
		private void SelectUploadFiles_Click(object sender, RoutedEventArgs e)
		{
			bool multiselect = ToggleMultiSelect.IsChecked == true;

			var dlg = new OpenFileDialog
			{
				Multiselect = multiselect,
				Title = multiselect ? "选择要上传的文件（可多选）" : "选择要上传的文件（单选）"
			};

			if (dlg.ShowDialog() == true)
			{
				SelectedUploadFiles.Clear();
				foreach (var f in dlg.FileNames)
					SelectedUploadFiles.Add(f);

				ModalHint.Text = $"已选择 {SelectedUploadFiles.Count} 个文件";
			}
		}

		private void ClearUploadFiles_Click(object sender, RoutedEventArgs e)
		{
			SelectedUploadFiles.Clear();
			ModalHint.Text = "已清空";
		}

		// ========== 核心：确认开始上传（真实调用 Python） ==========
		private async void ConfirmStart_Click(object sender, RoutedEventArgs e)
		{
			if (SelectedUploadFiles.Count == 0)
			{
				MessageBox.Show("请先选择至少一个文件。");
				return;
			}

			string pageId = (PageIdInput.Text ?? "").Trim();
			if (string.IsNullOrEmpty(pageId))
			{
				MessageBox.Show("请输入 Notion Page ID。");
				return;
			}

			var (ok, err) = await EnsureBackendAsync();
			if (!ok)
			{
				MessageBox.Show(err);
				return;
			}

			BtnConfirmStart.IsEnabled = false;
			ModalHint.Text = "正在创建上传任务…";

			try
			{
				// 快照文件列表（避免 ObservableCollection 在后台线程枚举）
				var filePaths = SelectedUploadFiles.ToList();

				string ret = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					var pyFiles = new PyList();
					foreach (var path in filePaths)
						pyFiles.Append(path.ToPython());

					var r = pyMain.upload_notion_files(pageId, pyFiles);
					return r?.ToString() ?? "";
				});

				// 关闭模态
				ModalOverlay.Visibility = Visibility.Collapsed;
				ModalStep1.Visibility = Visibility.Collapsed;

				// 先把任务放进列表（立即可见），EMA 初始化
				foreach (var path in filePaths)
				{
					if (DisplayUploads.Any(x => string.Equals(x.FilePath, path, StringComparison.OrdinalIgnoreCase)))
						continue;

					DisplayUploads.Add(new UploadTaskStatus
					{
						FilePath = path,
						FileName = Path.GetFileName(path),
						Status = "waiting",
						Stage = "waiting",
						Progress = 0,
						UploadedMB = 0,
						TotalMB = GuessSizeMB(path),
						SmoothedSpeedMBps = 0,
						ETASeconds = 0,
						Error = null
					});

					_speedEma[path] = 0.0;
				}

				// 启动轮询
				if (!_statusTimer.IsEnabled)
					_statusTimer.Start();

				if (!string.IsNullOrWhiteSpace(ret))
					MessageBox.Show(ret);
			}
			catch (Exception ex)
			{
				MessageBox.Show("启动上传失败: " + ex.Message);
			}
			finally
			{
				BtnConfirmStart.IsEnabled = true;
				ModalHint.Text = "";
			}
		}

		// ========== 轮询：get_upload_statuses + EMA 平滑 + completed 移除 ==========
		private async void UploadStatusTick(object? sender, EventArgs e)
		{
			if (!_backend.IsReady)
				return;

			try
			{
				var statuses = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					dynamic pyStatuses = pyMain.get_upload_statuses();

					var list = new List<UploadStatusDto>();
					foreach (var s in pyStatuses)
					{
						list.Add(new UploadStatusDto
						{
							FilePath = s["file_path"]?.ToString() ?? "",
							Status = s["status"]?.ToString() ?? "",
							Stage = s["stage"]?.ToString() ?? "",
							Progress = ToDoubleSafe(s, "progress"),
							UploadedMB = ToDoubleSafe(s, "uploaded_mb"),
							TotalMB = ToDoubleSafe(s, "total_mb"),
							Speed = ToDoubleSafe(s, "speed_mb_s"),
							ETA = ToIntSafe(s, "ETA"),
							Error = NormalizePythonNone(s, "error")
						});
					}

					return list;
				});

				// 用 file_path 做 key 增量更新
				var map = DisplayUploads.ToDictionary(x => x.FilePath ?? "", x => x, StringComparer.OrdinalIgnoreCase);

				foreach (var s in statuses)
				{
					if (string.IsNullOrWhiteSpace(s.FilePath))
						continue;

					// completed：立刻移除
					if (string.Equals(s.Status, "completed", StringComparison.OrdinalIgnoreCase))
					{
						var toRemove = DisplayUploads.FirstOrDefault(x =>
							string.Equals(x.FilePath, s.FilePath, StringComparison.OrdinalIgnoreCase));

						if (toRemove != null)
							DisplayUploads.Remove(toRemove);

						_speedEma.Remove(s.FilePath);
						continue;
					}

					if (!map.TryGetValue(s.FilePath, out var item))
					{
						item = new UploadTaskStatus
						{
							FilePath = s.FilePath,
							FileName = Path.GetFileName(s.FilePath),
						};
						DisplayUploads.Add(item);
						map[s.FilePath] = item;
						_speedEma[s.FilePath] = 0.0;
					}

					item.Status = s.Status;
					item.Stage = s.Stage;
					item.Progress = s.Progress;
					item.UploadedMB = s.UploadedMB;
					item.TotalMB = s.TotalMB;
					item.ETASeconds = s.ETA;
					item.Error = string.IsNullOrWhiteSpace(s.Error) ? null : s.Error;

					// EMA 平滑速度
					double raw = Math.Max(0.0, s.Speed);
					double prev = _speedEma.TryGetValue(s.FilePath, out var old) ? old : 0.0;
					double ema = (SpeedEmaAlpha * raw) + ((1.0 - SpeedEmaAlpha) * prev);
					_speedEma[s.FilePath] = ema;
					item.SmoothedSpeedMBps = ema;
				}

				if (DisplayUploads.Count == 0 && _statusTimer.IsEnabled)
					_statusTimer.Stop();
			}
			catch
			{
				// 不弹窗：避免每秒刷屏
			}
		}

		// ========== 后端初始化 ==========
		private async Task<(bool ok, string error)> EnsureBackendAsync()
		{
			try
			{
				ConfigManager.Load();
				string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";
				string url = ConfigManager.Current?.NotionBaseUrl ?? "https://api.notion.com/v1";
				int dl = ConfigManager.Current?.MaxDownloadWorkers ?? 3;
				int ul = ConfigManager.Current?.MaxUploadWorkers ?? 3;

				if (string.IsNullOrEmpty(token))
					return (false, "未检测到 Notion Token，请先到【设置】页保存 Token。");

				await _backend.EnsureBackendReady(token, dl, ul, url);
				return (true, "");
			}
			catch (Exception ex)
			{
				return (false, "初始化失败: " + ex.Message);
			}
		}

		// ====== 小工具 ======
		private static double GuessSizeMB(string filePath)
		{
			try
			{
				var fi = new FileInfo(filePath);
				return Math.Max(0.1, fi.Length / 1024.0 / 1024.0);
			}
			catch
			{
				return 0.0;
			}
		}

		private void OnTasksReset()
		{
			try
			{
				if (_statusTimer.IsEnabled)
					_statusTimer.Stop();

				Application.Current?.Dispatcher?.Invoke(() =>
				{
					try
					{
						DisplayUploads.Clear();
						SelectedUploadFiles.Clear();
						ModalHint.Text = "";
					}
					catch { }
				});
			}
			catch { }
		}
	}

	internal sealed class UploadStatusDto
	{
		public string FilePath { get; set; } = "";
		public string Status { get; set; } = "";
		public string Stage { get; set; } = "";
		public double Progress { get; set; }
		public double UploadedMB { get; set; }
		public double TotalMB { get; set; }
		public double Speed { get; set; }
		public int ETA { get; set; }
		public string? Error { get; set; }
	}

	public class UploadTaskStatus : INotifyPropertyChanged
	{
		private string? _filePath;
		private string? _fileName;
		private string? _status;
		private string? _stage;
		private double _progress;
		private double _uploadedMB;
		private double _totalMB;
		private double _smoothedSpeed;
		private int _etaSeconds;
		private string? _error;

		public string? FilePath
		{
			get => _filePath;
			set
			{
				_filePath = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}
		public string? FileName
		{
			get => _fileName;
			set
			{
				_fileName = value;
				OnPropertyChanged();
			}
		}

		public string? Status
		{
			get => _status;
			set
			{
				_status = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}
		public string? Stage
		{
			get => _stage;
			set
			{
				_stage = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}

		public double Progress
		{
			get => _progress;
			set
			{
				_progress = value;
				OnPropertyChanged();
			}
		}
		public double UploadedMB
		{
			get => _uploadedMB;
			set
			{
				_uploadedMB = value;
				OnPropertyChanged();
			}
		}
		public double TotalMB
		{
			get => _totalMB;
			set
			{
				_totalMB = value;
				OnPropertyChanged();
			}
		}

		public double SmoothedSpeedMBps
		{
			get => _smoothedSpeed;
			set
			{
				_smoothedSpeed = value;
				OnPropertyChanged();
			}
		}

		public int ETASeconds
		{
			get => _etaSeconds;
			set
			{
				_etaSeconds = value;
				OnPropertyChanged();
			}
		}

		public string? Error
		{
			get => _error;
			set
			{
				_error = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}

		public string StatusText
		{
			get
			{
				var s = Status ?? "";
				var st = Stage ?? "";

				if (!string.IsNullOrWhiteSpace(Error) &&
					!string.Equals(Error, "None", StringComparison.OrdinalIgnoreCase))
					return $"状态: {s} / 阶段: {st} / 错误: {Error}";

				bool connecting =
					string.Equals(s, "uploading", StringComparison.OrdinalIgnoreCase) &&
					!string.Equals(st, "uploading", StringComparison.OrdinalIgnoreCase) &&
					Progress <= 0.1 && UploadedMB <= 0.01 && SmoothedSpeedMBps <= 0.05;

				return connecting
					? "正在连接 Notion 服务器…（准备上传）"
					: $"状态: {s} / 阶段: {st}";
			}
		}

		public event PropertyChangedEventHandler? PropertyChanged;
		private void OnPropertyChanged([CallerMemberName] string? name = null)
			=> PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
	}
}
