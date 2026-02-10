using Microsoft.Win32;
using Python.Runtime;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace Notion_Files_Management.Views
{
	public partial class UploadPage : Page
	{
		// ====== UI 数据源 ======
		public ObservableCollection<string> SelectedUploadFiles { get; } = new();
		public ObservableCollection<UploadTaskStatus> DisplayUploads { get; } = new();

		// ====== Python 相关 ======
		private dynamic? _pyMain;
		private string _currentNotionToken = "";
		private static readonly SemaphoreSlim _pyLock = new(1, 1);

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

			int concurrency = GetSelectedConcurrency();

			if (!EnsureBackendReady(out string err))
			{
				MessageBox.Show(err);
				return;
			}

			BtnConfirmStart.IsEnabled = false;
			ModalHint.Text = "正在创建上传任务…";

			try
			{
				// 1) 调用后端：upload_notion_files(page_id, files_list, max_workers)
				string ret = await RunPython(() =>
				{
					// 注意：RunPython 已经持有 GIL，这里不再重复 using (Py.GIL())
					var pyFiles = new PyList();
					foreach (var path in SelectedUploadFiles)
						pyFiles.Append(path.ToPython());

					var r = _pyMain!.upload_notion_files(pageId, pyFiles, concurrency);
					return r?.ToString() ?? "";
				});

				// 2) 关闭模态
				ModalOverlay.Visibility = Visibility.Collapsed;
				ModalStep1.Visibility = Visibility.Collapsed;

				// 3) 先把任务放进列表（立即可见），EMA 初始化
				foreach (var path in SelectedUploadFiles)
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

				// 4) 启动轮询
				if (!_statusTimer.IsEnabled)
					_statusTimer.Start();

				// 5) 可选：提示 Success / Success x Failed y
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
			if (_pyMain == null)
				return;

			try
			{
				var statuses = await RunPython(() =>
				{
					dynamic pyStatuses = _pyMain!.get_upload_statuses();

					var list = new List<UploadStatusDto>();
					foreach (var s in pyStatuses)
					{
						string filePath = s["file_path"]?.ToString() ?? "";

						string status = s["status"]?.ToString() ?? "";
						string stage = s["stage"]?.ToString() ?? "";

						double progress = ToDoubleSafe(s, "progress");
						double uploaded = ToDoubleSafe(s, "uploaded_mb");
						double total = ToDoubleSafe(s, "total_mb");
						double speed = ToDoubleSafe(s, "speed_mb_s");
						int eta = (int)ToDoubleSafe(s, "ETA");

						string? errStr = NormalizePythonNone(s);

						list.Add(new UploadStatusDto
						{
							FilePath = filePath,
							Status = status,
							Stage = stage,
							Progress = progress,
							UploadedMB = uploaded,
							TotalMB = total,
							Speed = speed,
							ETA = eta,
							Error = errStr
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

					// ✅ completed：立刻移除
					if (string.Equals(s.Status, "completed", StringComparison.OrdinalIgnoreCase))
					{
						var toRemove = DisplayUploads.FirstOrDefault(x =>
							string.Equals(x.FilePath, s.FilePath, StringComparison.OrdinalIgnoreCase));

						if (toRemove != null)
							DisplayUploads.Remove(toRemove);

						_speedEma.Remove(s.FilePath);
						continue;
					}

					// 不存在则新增（容错：后端可能返回了新任务）
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

					// ✅ 防止 "None" 显示成错误
					item.Error = string.IsNullOrWhiteSpace(s.Error) ? null : s.Error;

					// ✅ EMA 平滑速度
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

		// ========== 后端初始化（同下载页：ConfigManager 读 Token + dotenv stub） ==========
		private bool EnsureBackendReady(out string error)
		{
			error = "";

			try
			{
				ConfigManager.Load();
				string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";

				if (string.IsNullOrEmpty(token))
				{
					error = "未检测到 Notion Token，请先到【设置】页保存 Token。";
					return false;
				}

				if (_pyMain != null && token == _currentNotionToken)
					return true;

				using (Py.GIL())
				{
					InjectDotenvStubIfMissing();

					dynamic sys = Py.Import("sys");
					string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
					sys.path.append(scriptsPath);

					dynamic mainMod = Py.Import("main");
					_pyMain = mainMod.Main(token, 3);
					_currentNotionToken = token;
				}

				return true;
			}
			catch (Exception ex)
			{
				error = "初始化失败: " + ex.Message;
				return false;
			}
		}

		private async Task<T> RunPython<T>(Func<T> func)
		{
			await _pyLock.WaitAsync();
			try
			{
				return await Task.Run(() =>
				{
					using (Py.GIL())
						return func();
				});
			}
			finally
			{
				_pyLock.Release();
			}
		}

		// ====== dotenv stub：避免 no module named dotenv ======
		private static void InjectDotenvStubIfMissing()
		{
			try
			{
				Py.Import("dotenv");
			}
			catch
			{
				dynamic types = Py.Import("types");
				dynamic sys = Py.Import("sys");

				dynamic mod = types.ModuleType("dotenv");
				mod.__dict__["load_dotenv"] = new Action(() => { });

				sys.modules["dotenv"] = mod;
			}
		}

		// ====== 把 Python 的 None 归一化成 null（避免 "None" 出现在 UI） ======
		private static string? NormalizePythonNone(dynamic s)
		{
			try
			{
				var errObj = s["error"];
				if (errObj == null)
					return null;

				string? txt = errObj.ToString();
				if (string.IsNullOrWhiteSpace(txt) || string.Equals(txt, "None", StringComparison.OrdinalIgnoreCase))
					return null;

				return txt;
			}
			catch
			{
				return null;
			}
		}

		// ====== 小工具 ======
		private int GetSelectedConcurrency()
		{
			if (UploadConcurrencyCombo.SelectedItem is ComboBoxItem item &&
				int.TryParse(item.Content?.ToString(), out int v))
				return v;

			return 3;
		}

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

		private static double ToDoubleSafe(dynamic dict, string key)
		{
			try
			{
				var v = dict[key];
				if (v == null)
					return 0.0;
				return Convert.ToDouble(v);
			}
			catch
			{
				return 0.0;
			}
		}
	}

	internal sealed class UploadStatusDto
	{
		public string FilePath { get; set; } = "";
		public string Status { get; set; } = "";
		public string Stage { get; set; } = "";
		public double Progress
		{
			get; set;
		}
		public double UploadedMB
		{
			get; set;
		}
		public double TotalMB
		{
			get; set;
		}
		public double Speed
		{
			get; set;
		}
		public int ETA
		{
			get; set;
		}
		public string? Error
		{
			get; set;
		}
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
			get => _filePath; set
			{
				_filePath = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}
		public string? FileName
		{
			get => _fileName; set
			{
				_fileName = value;
				OnPropertyChanged();
			}
		}

		public string? Status
		{
			get => _status; set
			{
				_status = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}
		public string? Stage
		{
			get => _stage; set
			{
				_stage = value;
				OnPropertyChanged();
				OnPropertyChanged(nameof(StatusText));
			}
		}

		public double Progress
		{
			get => _progress; set
			{
				_progress = value;
				OnPropertyChanged();
			}
		}
		public double UploadedMB
		{
			get => _uploadedMB; set
			{
				_uploadedMB = value;
				OnPropertyChanged();
			}
		}
		public double TotalMB
		{
			get => _totalMB; set
			{
				_totalMB = value;
				OnPropertyChanged();
			}
		}

		public double SmoothedSpeedMBps
		{
			get => _smoothedSpeed; set
			{
				_smoothedSpeed = value;
				OnPropertyChanged();
			}
		}

		public int ETASeconds
		{
			get => _etaSeconds; set
			{
				_etaSeconds = value;
				OnPropertyChanged();
			}
		}
		public string? Error
		{
			get => _error; set
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

				// 1) 错误优先显示（排除 None）
				if (!string.IsNullOrWhiteSpace(Error) &&
					!string.Equals(Error, "None", StringComparison.OrdinalIgnoreCase))
				{
					return $"状态: {s} / 阶段: {st} / 错误: {Error}";
				}

				// 2) 连接/准备阶段提示：
				// 常见：status=uploading 但 stage=creating/backoff_wait/attaching 等，且 progress/速度都还为 0
				bool looksLikeConnecting =
					string.Equals(s, "uploading", StringComparison.OrdinalIgnoreCase) &&
					!string.Equals(st, "uploading", StringComparison.OrdinalIgnoreCase) &&
					Progress <= 0.1 &&
					UploadedMB <= 0.01 &&
					SmoothedSpeedMBps <= 0.05;

				if (looksLikeConnecting)
				{
					// 你想要的文案
					return "正在连接 Notion 服务器…（准备上传）";
				}

				// 3) 正常显示
				return $"状态: {s} / 阶段: {st}";
			}
		}


		public event PropertyChangedEventHandler? PropertyChanged;
		private void OnPropertyChanged([CallerMemberName] string? name = null)
			=> PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
	}
}
