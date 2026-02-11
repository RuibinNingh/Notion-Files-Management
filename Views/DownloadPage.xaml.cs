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
using Notion_Files_Management.Utils;
using System.Diagnostics;

namespace Notion_Files_Management.Views
{
	public partial class DownloadPage : Page
	{
        internal sealed record ProbeProgress(string Status, double Percent, int Done, int Total, string Error, string RawRepr);

        // ===== UI 数据 (moved to session) =====
        private readonly Services.DownloadSession _session = Services.DownloadSession.Instance;

        public ObservableCollection<FileSelectItem> FileSelectionList => _session.FileSelectionList;
        public ObservableCollection<DownloadTaskStatus> DisplayTasks => _session.DisplayTasks;

        private string _saveDirectory
        {
            get => _session.SaveDirectory;
            set => _session.SaveDirectory = value;
        }

		private async Task RefreshStatusesAsync(CancellationToken token)
		{
			if (!_backend.IsReady)
				return;

			var statuses = await _backend.RunPython(py =>
			{
				dynamic pyMain = py;
				using (Logger.Time("Py:Main.get_download_statuses"))
				{
					dynamic pyStatuses = pyMain.get_download_statuses();
					var result = new List<DownloadTaskStatus>();

					foreach (var s in pyStatuses)
					{
						string status = s["status"]?.ToString() ?? "";

						if (string.Equals(status, "completed", StringComparison.OrdinalIgnoreCase))
							continue;

						result.Add(new DownloadTaskStatus
						{
							url = s["url"]?.ToString(),
							name = s["name"]?.ToString(),
							real_name = s["real_name"]?.ToString(),
							status = status,
							progress = ToDoubleSafe(s, "progress"),
							downloaded_mb = ToDoubleSafe(s, "downloaded_mb"),
							total_mb = ToDoubleSafe(s, "total_mb"),
							speed_mb_s = ToDoubleSafe(s, "speed_mb_s"),
							ETA = ToIntSafe(s, "ETA"),
							error = NormalizePythonNone(s, "error")
						});
					}

					return result;
				}
			}, token);

			// 更新 Session.DisplayTasks（尽量复用已有对象）
			var map = _session.DisplayTasks.ToDictionary(x => x.url ?? "", x => x, StringComparer.OrdinalIgnoreCase);

			foreach (var s in statuses)
			{
				string key = s.url ?? "";
				if (string.IsNullOrWhiteSpace(key))
					continue;

				if (!map.TryGetValue(key, out var item))
				{
					_session.DisplayTasks.Add(s);
					map[key] = s;
				}
				else
				{
					item.name = s.name;
					item.real_name = s.real_name;
					item.status = s.status;
					item.progress = s.progress;
					item.downloaded_mb = s.downloaded_mb;
					item.total_mb = s.total_mb;
					item.speed_mb_s = s.speed_mb_s;
					item.ETA = s.ETA;
					item.error = s.error;
				}
			}

			var alive = new HashSet<string>(statuses.Select(x => x.url ?? ""), StringComparer.OrdinalIgnoreCase);
			for (int i = _session.DisplayTasks.Count - 1; i >= 0; i--)
			{
				var u = _session.DisplayTasks[i].url ?? "";
				if (!alive.Contains(u))
					_session.DisplayTasks.RemoveAt(i);
			}

			// 更新 HasActiveDownloads 标记
			_session.HasActiveDownloads = _session.DisplayTasks.Count > 0;
		}

		// ===== Python =====
		private readonly Services.PythonBackendHost _backend = Services.PythonBackendHost.Instance;

		// ===== 获取列表：取消支持 =====
		private CancellationTokenSource? _getListCts;
		private int _getListReqId = 0;

		// ===== 下载状态轮询 =====
		private readonly DispatcherTimer _downloadStatusTimer = new DispatcherTimer();

		public DownloadPage()
		{
			InitializeComponent();
			DataContext = this;
			Logger.Info("DownloadPage initialized");

			Services.TaskResetNotifier.TasksReset += OnTasksReset;

			// 如果 XAML 没有绑 ItemsSource，也能跑
			try
			{
				FileListSelector.ItemsSource = FileSelectionList;
			}
			catch { }
			try
			{
				DownloadTaskListView.ItemsSource = DisplayTasks;
			}
			catch { }

			_downloadStatusTimer.Interval = TimeSpan.FromSeconds(1);
			_downloadStatusTimer.Tick += UpdateDownloadStatusesTick;

			Loaded += async (_, __) =>
			{
				// 页面恢复时，如果会话有活跃下载，尝试先刷新一次并恢复轮询
				try
				{
					if (_session.HasActiveDownloads)
					{
						await RefreshStatusesAsync(CancellationToken.None);
						if (!_downloadStatusTimer.IsEnabled)
							_downloadStatusTimer.Start();
					}
				}
				catch (Exception ex)
				{
					Logger.Warn($"Restore polling failed: {ex.Message}");
				}
			};

			Unloaded += (_, __) =>
			{
				Services.TaskResetNotifier.TasksReset -= OnTasksReset;
				if (_downloadStatusTimer.IsEnabled)
					_downloadStatusTimer.Stop();
			};

			// 预热 Python（不阻塞 UI）
			_ = Task.Run(() => EnsureBackendReady(out _));
		}

		// =========================
		// UI：打开 / 关闭模态
		// =========================
		private void BtnOpenDownloadDialog_Click(object sender, RoutedEventArgs e)
		{
			Logger.Info("Open download dialog");
			ModalOverlay.Visibility = Visibility.Visible;
			ModalStep1.Visibility = Visibility.Visible;
			ModalStep2.Visibility = Visibility.Collapsed;

			BtnConfirmId.IsEnabled = true;
		}

		private void CloseModal_Click(object sender, RoutedEventArgs e)
		{
			Logger.Info("Close download dialog (cancel probe if running)");
			_getListCts?.Cancel();

			ModalOverlay.Visibility = Visibility.Collapsed;
			ModalStep1.Visibility = Visibility.Collapsed;
			ModalStep2.Visibility = Visibility.Collapsed;

			BtnConfirmId.IsEnabled = true;
		}

		private void BackToStep1_Click(object sender, RoutedEventArgs e)
		{
			Logger.Info("Back to Step1");
			ModalStep2.Visibility = Visibility.Collapsed;
			ModalStep1.Visibility = Visibility.Visible;
		}

		// =========================
		// 核心：获取列表（按 API 文档：get_download_list -> probe -> download_list）
		// 1) Main.get_download_list(page_id) 触发查询，返回 dict{status,msg,probe_id,total}
		// 2) 循环 Main.download_list_processing(probe_id) 轮询进度，直到 status=="done"
		// 3) done 后 Main.download_list 为最终列表（list[dict]）
		// =========================
		private async void ConfirmId_Click(object sender, RoutedEventArgs e)
		{
			var confirmBtn = sender as Button;
			object? confirmOldContent = null;
			if (confirmBtn != null)
			{
				confirmOldContent = confirmBtn.Content;
				confirmBtn.Content = "稍等";
			}

			if (!EnsureBackendReady(out string err))
			{
				MessageBox.Show(err);
				if (confirmBtn != null)
				{
					confirmBtn.Content = confirmOldContent;
				}
				return;
			}

			string pageId = (PageIdInput.Text ?? "").Trim().Replace(" ", "");
			if (string.IsNullOrWhiteSpace(pageId))
			{
				MessageBox.Show("请输入目标页面 ID。");
				if (confirmBtn != null)
				{
					confirmBtn.Content = confirmOldContent;
				}
				return;
			}

			// 新请求：取消旧请求
			_getListCts?.Cancel();
			_getListCts = new CancellationTokenSource();
			var token = _getListCts.Token;
			int reqId = ++_getListReqId;

			BtnConfirmId.IsEnabled = false;
			Logger.Info($"Get list clicked. pageId={pageId}");

			try
			{
				// 1) get_download_list：触发后端查询并返回 probe_id
				var (probeId, total, msg, status) = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					using (Logger.Time("Py:Main.get_download_list"))
					{
						dynamic ret = pyMain.get_download_list(pageId);
						int pid = 0;
						int tot = 0;
						string m = "";
						string st = "";
						try
						{
							pid = PyConvert.ToInt(ret["probe_id"], 0);
						}
						catch { }
						try
						{
							tot = PyConvert.ToInt(ret["total"], 0);
						}
						catch { }
						try
						{
							m = ret["msg"]?.ToString() ?? "";
						}
						catch { }
						try
						{
							st = ret["status"]?.ToString() ?? "";
						}
						catch { }
						return (pid, tot, m, st);
					}
				}, token);

				Logger.Info($"get_download_list => status={status}, total={total}, probe_id={probeId}, msg={msg}");
				token.ThrowIfCancellationRequested();
				if (reqId != _getListReqId)
					return;

				if (probeId <= 0)
				{
					// 文档契约：probeId 非正通常表示失败/无文件
					MessageBox.Show(string.IsNullOrWhiteSpace(msg) ? "获取列表失败或页面无文件" : msg);
					Logger.Warn($"probe_id invalid. status={status}, msg={msg}");
					return;
				}

				// Python-side introspection: log object ids and downloader contents to help debug probe registration
				try
				{
					await _backend.RunPython<object>(py =>
					{
						dynamic pyMain = py;
						using (Logger.Time("Py:Introspect downloader"))
						{
							dynamic builtins = Py.Import("builtins");
							dynamic idFn = builtins.id;
							try { Logger.Info($"id(_pyMain)={idFn(pyMain)}"); } catch { }
							try { Logger.Info($"id(_pyMain.downloader)={idFn(pyMain.downloader)}"); } catch { }

							dynamic d = pyMain.downloader;
							try
							{
								var dObj = (PyObject)d;
								using var dirList = dObj.Dir(); // list[str]
								var names = dirList.As<string[]>();
								Logger.Info("downloader dir contains: " + string.Join(", ", names));
							}
							catch (Exception ex)
							{
								Logger.Warn($"downloader dir introspect failed: {ex.Message}");
							}

							// 尝试输出 probe keys（常见字段名 probe_statuses / probe_tasks）
							try
							{
								var dObj = (PyObject)d;
								if (dObj.HasAttr("probe_statuses"))
								{
									using var ps = dObj.GetAttr("probe_statuses");
									using var keysMethod = ps.GetAttr("keys");
									using var keys = keysMethod.Invoke();
									var keyNums = keys.As<int[]>();
									Logger.Info("probe keys = " + string.Join(", ", keyNums));
								}
								else if (dObj.HasAttr("probe_tasks"))
								{
									using var pt = dObj.GetAttr("probe_tasks");
									using var keysMethod = pt.GetAttr("keys");
									using var keys = keysMethod.Invoke();
									var keyNums = keys.As<int[]>();
									Logger.Info("probe keys = " + string.Join(", ", keyNums));
								}
							}
							catch (Exception ex)
							{
								Logger.Warn($"probe keys introspect failed: {ex.Message}");
							}
						}
						return 0;
					}, token);
				}
				catch (Exception ex)
				{
					Logger.Warn($"Introspection failed: {ex.Message}");
				}

				// 2) 轮询 probe：download_list_processing(probe_id) 直到 done
				double lastPct = -1;

				// 给后端一点时间注册 probe
				await Task.Delay(200, token);

				{
					var sw = Stopwatch.StartNew();
					int notFoundCount = 0;
					while (true)
					{
						token.ThrowIfCancellationRequested();
						if (reqId != _getListReqId)
							return;

						var p = await GetProbeProgressAsync(probeId, token);

						string pStatus = p.Status;
						int dn = p.Done;
						int pTotal = p.Total;
						double percent = p.Percent;
						string pError = p.Error ?? "";

						Logger.Info($"probe => status={pStatus}, percent={percent}, done={dn}/{pTotal}, error={(pError ?? "")}");

						if (string.Equals(pStatus, "done", StringComparison.OrdinalIgnoreCase))
							break;

						if (string.Equals(pStatus, "not_found", StringComparison.OrdinalIgnoreCase))
						{
							notFoundCount++;
							await Application.Current.Dispatcher.InvokeAsync(() => BtnConfirmId.Content = $"准备探测任务…（{notFoundCount}）");
							if (sw.Elapsed.TotalSeconds > 5)
								throw new Exception("Probe task not found after 5s (backend returned status=not_found).");
							await Task.Delay(250, token);
							continue;
						}

						if (string.Equals(pStatus, "error", StringComparison.OrdinalIgnoreCase) || string.Equals(pStatus, "failed", StringComparison.OrdinalIgnoreCase))
						{
							throw new Exception($"Probe failed: {pError}");
						}

						// 正常进度显示（只在变化时输出/更新UI）
						if (Math.Abs(percent - lastPct) > 0.01)
						{
							lastPct = percent;
							Logger.Info($"probe => status={pStatus}, percent={percent:0.0}, done={dn}/{pTotal}, error={(pError ?? "")}");
							await Application.Current.Dispatcher.InvokeAsync(() => BtnConfirmId.Content = $"探测中 {percent:0}% ({dn}/{pTotal})");
						}

						await Task.Delay(400, token);
					}
				}

				// 3) done 后：main.download_list 才是最终列表
				var list = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					using (Logger.Time("Py:Read main.download_list"))
					{
						var result = new List<FileSelectItem>();
						dynamic pyList = pyMain.download_list;
						foreach (var item in pyList)
						{
							if (!IsPyMapping(item))
							{
								string repr = "";
								try
								{
									repr = item?.ToString() ?? "";
								}
								catch { }
								throw new Exception($"main.download_list 的元素不是 dict（mapping），实际={item?.GetPythonType()?.ToString() ?? "unknown"}，值={repr}");
							}

							string realName = item["real_name"]?.ToString() ?? "";
							string url = "";
							try
							{
								url = item["url"]?.ToString() ?? "";
							}
							catch { }
							double size = 0.0;
							try
							{
								size = PyConvert.ToDouble(item["size_mb"], 0.0);
							}
							catch { }

							result.Add(new FileSelectItem
							{
								url = url,
								real_name = realName,
								size_mb = size,
								raw_dict = item,
								IsSelected = true
							});
						}
						return result;
					}
				}, token);

				token.ThrowIfCancellationRequested();
				if (reqId != _getListReqId)
					return;

				// UI：更新列表（保留勾选状态） - 使用 url 作为唯一 key
				var selected = FileSelectionList.ToDictionary(x => x.url ?? "", x => x.IsSelected, StringComparer.OrdinalIgnoreCase);

				FileSelectionList.Clear();
				foreach (var x in list)
				{
					if (!string.IsNullOrWhiteSpace(x.url) && selected.TryGetValue(x.url, out bool sel))
						x.IsSelected = sel;

					FileSelectionList.Add(x);
				}

				// 切到 Step2
				ModalStep1.Visibility = Visibility.Collapsed;
				ModalStep2.Visibility = Visibility.Visible;
				Logger.Info($"Download list ready. count={FileSelectionList.Count}");

				if (FileSelectionList.Count == 0)
					MessageBox.Show("该页面没有可下载的文件。");
			}
			catch (OperationCanceledException)
			{
				// ignore
				Logger.Warn("Get list canceled");
			}
			catch (Exception ex)
			{
				MessageBox.Show("获取列表失败: " + ex.Message);
				Logger.Error("Get list failed", ex);
			}
			finally
			{
				if (reqId == _getListReqId)
				{
					BtnConfirmId.IsEnabled = true;
					if (confirmBtn != null)
						confirmBtn.Content = confirmOldContent;
					else
						BtnConfirmId.Content = "获取列表";
				}
			}
		}

		// =========================
		// UI：选目录（不使用 WinForms）
		// =========================
		private void SelectFolder_Click(object sender, RoutedEventArgs e)
		{
			Logger.Info("SelectFolder clicked");
			// WPF 无原生 FolderPicker：用 OpenFileDialog 取所在目录
			var dlg = new OpenFileDialog
			{
				Title = "请选择保存目录（进入目标文件夹后点“打开”即可）",
				CheckFileExists = false,
				CheckPathExists = true,
				FileName = "选择此文件夹",
				Filter = "文件夹|*.folder"
			};

			if (dlg.ShowDialog() == true)
			{
				string? dir = Path.GetDirectoryName(dlg.FileName);
				if (!string.IsNullOrWhiteSpace(dir) && Directory.Exists(dir))
				{
					_saveDirectory = dir;
					SavePathDisplay.Text = _saveDirectory;
					Logger.Info($"SaveDirectory set: {_saveDirectory}");
				}
			}
		}

		private void SelectAll_Click(object sender, RoutedEventArgs e)
		{
			foreach (var x in FileSelectionList)
				x.IsSelected = true;
		}

		private void InvertSelect_Click(object sender, RoutedEventArgs e)
		{
			foreach (var x in FileSelectionList)
				x.IsSelected = !x.IsSelected;
		}

		// =========================
		// 核心：开始下载
		// main.download_notion_files(download_list, save_directory)
		// =========================
		private async void SubmitDownload_Click(object sender, RoutedEventArgs e)
		{
			// UI: show temporary feedback
			var btn = sender as Button;
			object? oldContent = null;
			if (btn != null)
			{
				oldContent = btn.Content;
				btn.Content = "稍等";
			}

			Logger.Info("SubmitDownload clicked");
			if (!EnsureBackendReady(out string err))
			{
				MessageBox.Show(err);
				return;
			}

			var selected = FileSelectionList.Where(x => x.IsSelected).ToList();
			if (selected.Count == 0)
			{
				MessageBox.Show("请至少选择一个下载项。");
				return;
			}

			if (string.IsNullOrWhiteSpace(_saveDirectory) || !Directory.Exists(_saveDirectory))
			{
				MessageBox.Show("请选择有效的保存目录。");
				return;
			}

			try
			{
				Logger.Info($"Starting download. selected={selected.Count}, saveDir={_saveDirectory}");
				string ret = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					using (Logger.Time("Py:Main.download_notion_files"))
					{
						using var pyListToDownload = new PyList();
						foreach (var s in selected)
							pyListToDownload.Append(s.raw_dict);

						var r = pyMain.download_notion_files(pyListToDownload, _saveDirectory);
						//return r?.ToString() ?? "";
						return "";
					}
				}, CancellationToken.None);

				// 关闭模态
				ModalOverlay.Visibility = Visibility.Collapsed;
				ModalStep1.Visibility = Visibility.Collapsed;
				ModalStep2.Visibility = Visibility.Collapsed;

				Logger.Info($"download_notion_files returned: {ret}");
				if (!string.IsNullOrWhiteSpace(ret))
					MessageBox.Show(ret);

				// 启动状态轮询
				if (!_downloadStatusTimer.IsEnabled)
					_downloadStatusTimer.Start();

				// 标记会话有活跃下载
				_session.HasActiveDownloads = true;
			}
			catch (Exception ex)
			{
				MessageBox.Show("启动下载失败: " + ex.Message);
				Logger.Error("Start download failed", ex);
			}
			finally
			{
				// restore button state
				var btn2 = sender as Button;
				if (btn2 != null)
				{
					btn2.Content = oldContent;
					btn2.IsEnabled = true;
				}
			}
		}

		// =========================
		// 轮询下载状态（完成后移除）
		// main.get_download_statuses()
		// =========================
		private async void UpdateDownloadStatusesTick(object? sender, EventArgs e)
		{
			if (!_backend.IsReady)
				return;

			Logger.Debug($"Polling download statuses. currentDisplayed={DisplayTasks.Count}");

			try
			{
				var statuses = await _backend.RunPython(py =>
				{
					dynamic pyMain = py;
					using (Logger.Time("Py:Main.get_download_statuses"))
					{
						dynamic pyStatuses = pyMain.get_download_statuses();
						var result = new List<DownloadTaskStatus>();

						foreach (var s in pyStatuses)
						{
							string status = s["status"]?.ToString() ?? "";

							// 完成：不展示（你要"完成就从列表删"）
							if (string.Equals(status, "completed", StringComparison.OrdinalIgnoreCase))
								continue;

							result.Add(new DownloadTaskStatus
							{
								url = s["url"]?.ToString(),
								name = s["name"]?.ToString(),
								real_name = s["real_name"]?.ToString(),
								status = status,
								progress = ToDoubleSafe(s, "progress"),
								downloaded_mb = ToDoubleSafe(s, "downloaded_mb"),
								total_mb = ToDoubleSafe(s, "total_mb"),
								speed_mb_s = ToDoubleSafe(s, "speed_mb_s"),
								ETA = ToIntSafe(s, "ETA"),
								error = NormalizePythonNone(s, "error")
							});
						}

						return result;
					}
				}, CancellationToken.None);

				Logger.Debug($"Statuses polled. count={statuses.Count}");

				// 增量更新（按 url）
				var map = DisplayTasks.ToDictionary(x => x.url ?? "", x => x, StringComparer.OrdinalIgnoreCase);

				foreach (var s in statuses)
				{
					string key = s.url ??("");
					if (string.IsNullOrWhiteSpace(key))
						continue;

					if (!map.TryGetValue(key, out var item))
					{
						DisplayTasks.Add(s);
						map[key] = s;
					}
					else
					{
						item.name = s.name;
						item.real_name = s.real_name;
						item.status = s.status;
						item.progress = s.progress;
						item.downloaded_mb = s.downloaded_mb;
						item.total_mb = s.total_mb;
						item.speed_mb_s = s.speed_mb_s;
						item.ETA = s.ETA;
						item.error = s.error;
					}
				}

				// 删除差集（后端不再返回的任务 or 已完成）
				var alive = new HashSet<string>(statuses.Select(x => x.url ?? ""), StringComparer.OrdinalIgnoreCase);
				for (int i = DisplayTasks.Count - 1; i >= 0; i--)
				{
					var u = DisplayTasks[i].url ?? "";
					if (!alive.Contains(u))
						DisplayTasks.RemoveAt(i);
				}

				if (DisplayTasks.Count == 0 && _downloadStatusTimer.IsEnabled)
				{
					_downloadStatusTimer.Stop();
					_session.HasActiveDownloads = false;
				}
			}
			catch (Exception ex)
			{
				// ignore UI 弹窗，但保留日志
				Logger.Error("Polling download statuses failed", ex);
			}
		}

		// =========================
		// Python 初始化 & 工具
		// =========================
		private async Task<(bool success, string error)> EnsureBackendReadyAsync()
		{
			try
			{
				Logger.Debug("EnsureBackendReady called");
				ConfigManager.Load();
				string token = ConfigManager.Current?.NotionToken?.Trim() ?? "";
				string url = ConfigManager.Current?.NotionBaseUrl ?? "https://api.notion.com/v1";
				int dl = ConfigManager.Current?.MaxDownloadWorkers ?? 3;
				int ul = ConfigManager.Current?.MaxUploadWorkers ?? 3;
				if (string.IsNullOrEmpty(token))
				{
					return (false, "未检测到 Notion Token，请先到【设置】页保存 Token。");
				}

				await _backend.EnsureBackendReady(token, dl, ul, url);
				return (true, "");
			}
			catch (Exception ex)
			{
				return (false, "初始化失败: " + ex.Message);
			}
		}

		private bool EnsureBackendReady(out string error)
		{
			var task = EnsureBackendReadyAsync();
			task.Wait();
			var (success, err) = task.Result;
			error = err;
			return success;
		}

		private async Task<T> RunPython<T>(Func<T> func, CancellationToken token)
		{
			return await _backend.RunPython(func, token);
		}

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

		private static bool IsPyMapping(dynamic obj)
		{
			try
			{
				// 用 Python 的 collections.abc.Mapping 判断
				dynamic collections = Py.Import("collections.abc");
				dynamic mapping = collections.Mapping;
				return mapping.__instancecheck__(obj);
			}
			catch
			{
				// 保底：常见 dict 类型
				try
				{
					return obj is PyDict;
				}
				catch { return false; }
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
			catch { return 0.0; }
		}

		private static int ToIntSafe(dynamic dict, string key)
		{
			try
			{
				var v = dict[key];
				if (v == null)
					return 0;
				return Convert.ToInt32(v);
			}
			catch { return 0; }
		}

		private static string? NormalizePythonNone(dynamic dict, string key)
		{
			try
			{
				var v = dict[key];
				if (v == null)
					return null;
				var s = v.ToString();
				if (string.IsNullOrWhiteSpace(s) || string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
					return null;
				return s;
			}
			catch { return null; }
		}

		private Task<ProbeProgress> GetProbeProgressAsync(int probeId, CancellationToken token)
		{
			return _backend.RunPython(py =>
			{
				dynamic pyMain = py;
				using (Logger.Time("Py:Main.download_list_processing"))
				{
					dynamic prog = pyMain.download_list_processing(probeId);
					string st = prog["status"]?.ToString() ?? "";
					double pct = 0.0;
					int dn = 0;
					int tt = 0;
					string errText = "";
					try { pct = PyConvert.ToDouble(prog["percent"], 0.0); } catch { }
					try { dn = PyConvert.ToInt(prog["done"], 0); } catch { }
					try { tt = PyConvert.ToInt(prog["total"], 0); } catch { }
					try
					{
						var eobj = prog["error"];
						if (eobj != null)
						{
							var s = eobj.ToString();
							if (!string.IsNullOrWhiteSpace(s) && !string.Equals(s, "None", StringComparison.OrdinalIgnoreCase))
								errText = s;
						}
					}
					catch { }
					string raw = "";
					try { raw = ((Python.Runtime.PyObject)prog).Repr().ToString(); } catch { }
					return new ProbeProgress(st, pct, dn, tt, errText ?? "", raw);
				}
			}, token);
		}
		private void OnTasksReset()
		{
			try
			{
				// Stop polling and clear UI
				if (_downloadStatusTimer.IsEnabled)
					_downloadStatusTimer.Stop();

				_session.HasActiveDownloads = false;

				Application.Current.Dispatcher.Invoke(() =>
				{
					try
					{
						DisplayTasks.Clear();
						FileSelectionList.Clear();
					}
					catch { }
				});
			}
			catch { }
		}

	}

	// =========================
	// ViewModel
	// =========================
	public class FileSelectItem : INotifyPropertyChanged
	{
		private bool _isSelected;
		public bool IsSelected
		{
			get => _isSelected;
			set
			{
				_isSelected = value;
				OnPropertyChanged();
			}
		}

		public string? url { get; set; }
		public string? real_name
		{
			get; set;
		}
		public double size_mb
		{
			get; set;
		}

		// PyDict：回传给 download_notion_files 用
		public dynamic raw_dict { get; set; } = null!;

		public event PropertyChangedEventHandler? PropertyChanged;
		private void OnPropertyChanged([CallerMemberName] string? name = null)
			=> PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
	}

	public class DownloadTaskStatus : INotifyPropertyChanged
	{
		private string? _url;
		private string? _name;
		private string? _real_name;
		private string? _status;
		private double _progress;
		private double _downloaded;
		private double _total;
		private double _speed;
		private int _eta;
		private string? _error;

		public string? url
		{
			get => _url; set
			{
				_url = value;
				OnPropertyChanged();
			}
		}
		public string? name
		{
			get => _name; set
			{
				_name = value;
				OnPropertyChanged();
			}
		}
		public string? real_name
		{
			get => _real_name; set
			{
				_real_name = value;
				OnPropertyChanged();
			}
		}

		public string? status
		{
			get => _status; set
			{
				_status = value;
				OnPropertyChanged();
			}
		}
		public double progress
		{
			get => _progress; set
			{
				_progress = value;
				OnPropertyChanged();
			}
		}
		public double downloaded_mb
		{
			get => _downloaded; set
			{
				_downloaded = value;
				OnPropertyChanged();
			}
		}
		public double total_mb
		{
			get => _total; set
			{
				_total = value;
				OnPropertyChanged();
			}
		}
		public double speed_mb_s
		{
			get => _speed; set
			{
				_speed = value;
				OnPropertyChanged();
			}
		}
		public int ETA
		{
			get => _eta; set
			{
				_eta = value;
				OnPropertyChanged();
			}
		}
		public string? error
		{
			get => _error; set
			{
				_error = value;
				OnPropertyChanged();
			}
		}

		public event PropertyChangedEventHandler? PropertyChanged;
		private void OnPropertyChanged([CallerMemberName] string? name = null)
			=> PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
	}
}
