using Python.Runtime;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Notion_Files_Management.Utils;

namespace Notion_Files_Management.Services
{
	public sealed class PythonBackendHost
	{
		private static readonly Lazy<PythonBackendHost> _instance = new(() => new PythonBackendHost());
		public static PythonBackendHost Instance => _instance.Value;

		private PythonBackendHost() { }

		private dynamic? _pyMain;
		private string _currentToken = "";
		private int _currentDownloadWorkers = -1;
		private int _currentUploadWorkers = -1;
		private string _currentUrl = "";
		private readonly SemaphoreSlim _pyLock = new(1, 1);
		private bool _isInitialized = false;

		public async Task<T> RunPython<T>(Func<object, T> func, CancellationToken token = default)
		{
			await _pyLock.WaitAsync(token);
			try
			{
				return await Task.Run(() =>
				{
					token.ThrowIfCancellationRequested();
					using (Logger.Time("Py:GIL scope"))
					using (Py.GIL())
					{
						return func(_pyMain!);
					}
				}, token);
			}
			catch (Exception ex)
			{
				Logger.Error("RunPython failed", ex);
				throw;
			}
			finally
			{
				_pyLock.Release();
			}
		}

		public async Task<T> RunPython<T>(Func<T> func, CancellationToken token = default)
		{
			await _pyLock.WaitAsync(token);
			try
			{
				return await Task.Run(() =>
				{
					token.ThrowIfCancellationRequested();
					using (Logger.Time("Py:GIL scope"))
					using (Py.GIL())
					{
						return func();
					}
				}, token);
			}
			catch (Exception ex)
			{
				Logger.Error("RunPython failed", ex);
				throw;
			}
			finally
			{
				_pyLock.Release();
			}
		}

		public async Task EnsureBackendReady(string notionToken, int maxDownloadWorkers, int maxUploadWorkers, string notionBaseUrl = "https://api.notion.com/v1")
		{
			await _pyLock.WaitAsync();
			try
			{
				if (_pyMain != null && _currentToken == notionToken
					&& _currentDownloadWorkers == maxDownloadWorkers
					&& _currentUploadWorkers == maxUploadWorkers
					&& _currentUrl == notionBaseUrl)
				{
					Logger.Info("Python backend already initialized (token unchanged)");
					return;
				}

				Logger.Info("BEGIN Init Python Main(token, workers, url)");
				if (!_isInitialized)
				{
					try
					{
						PythonEngine.Initialize();
					}
					catch (Exception ex)
					{
						// App.xaml.cs may initialize PythonEngine already. Treat as idempotent.
						Logger.Warn($"PythonEngine.Initialize skipped/failed: {ex.Message}");
					}
					_isInitialized = true;
				}

				using (Py.GIL())
				{
					InjectDotenvStubIfMissing();

					dynamic sys = Py.Import("sys");
					string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
					sys.path.append(scriptsPath);

					dynamic mainMod = Py.Import("main");
					_pyMain = mainMod.Main(notionToken, maxDownloadWorkers, maxUploadWorkers, notionBaseUrl);
					_currentToken = notionToken;
					_currentDownloadWorkers = maxDownloadWorkers;
					_currentUploadWorkers = maxUploadWorkers;
					_currentUrl = notionBaseUrl;
					Logger.Info($"END Init Python Main(token, dl={maxDownloadWorkers}, ul={maxUploadWorkers}, url={notionBaseUrl})");
				}
			}
			finally
			{
				_pyLock.Release();
			}
		}


		/// <summary>
		/// Cancel all current download/upload tasks (if backend supports it) and recreate Main instance.
		/// This is used when changing concurrency settings and user chooses to reset running tasks.
		/// </summary>
		public async Task ResetTasksAndReinitialize(string notionToken, int maxDownloadWorkers, int maxUploadWorkers, string notionBaseUrl = "https://api.notion.com/v1")
		{
			await _pyLock.WaitAsync();
			try
			{
				if (_pyMain != null)
				{
					Logger.Info("BEGIN ResetTasks: cancel all + shutdown python Main");
					try
					{
						using (Py.GIL())
						{
							// Best-effort cancel
							try { _pyMain.cancel_all_downloads(); } catch { }
							try { _pyMain.cancel_all_uploads(); } catch { }
							try { _pyMain.shutdown(); } catch { }
						}
					}
					catch (Exception ex)
					{
						Logger.Error("ResetTasks: python cancel/shutdown failed", ex);
					}
					finally
					{
						_pyMain = null;
						_currentToken = "";
						_currentDownloadWorkers = -1;
						_currentUploadWorkers = -1;
						_currentUrl = "";
					}
					Logger.Info("END ResetTasks");
				}

				// Ensure Python engine is up, then re-init
				if (!_isInitialized)
				{
					try
					{
						PythonEngine.Initialize();
					}
					catch (Exception ex)
					{
						// App.xaml.cs may initialize PythonEngine already. Treat as idempotent.
						Logger.Warn($"PythonEngine.Initialize skipped/failed: {ex.Message}");
					}
					_isInitialized = true;
				}

				using (Py.GIL())
				{
					InjectDotenvStubIfMissing();

					dynamic sys = Py.Import("sys");
					string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
					sys.path.append(scriptsPath);

					dynamic mainMod = Py.Import("main");
					_pyMain = mainMod.Main(notionToken, maxDownloadWorkers, maxUploadWorkers, notionBaseUrl);
					_currentToken = notionToken;
					_currentDownloadWorkers = maxDownloadWorkers;
					_currentUploadWorkers = maxUploadWorkers;
					_currentUrl = notionBaseUrl;
					Logger.Info($"ResetTasks: Reinitialized Main(dl={maxDownloadWorkers}, ul={maxUploadWorkers}, url={notionBaseUrl})");
				}
			}
			finally
			{
				_pyLock.Release();
			}
		}

		public bool IsReady => _pyMain != null;

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
	}
}
