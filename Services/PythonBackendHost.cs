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

		public async Task EnsureBackendReady(string notionToken)
		{
			await _pyLock.WaitAsync();
			try
			{
				if (_pyMain != null && _currentToken == notionToken)
				{
					Logger.Info("Python backend already initialized (token unchanged)");
					return;
				}

				Logger.Info("BEGIN Init Python Main(token)");
				if (!_isInitialized)
				{
					PythonEngine.Initialize();
					_isInitialized = true;
				}

				using (Py.GIL())
				{
					InjectDotenvStubIfMissing();

					dynamic sys = Py.Import("sys");
					string scriptsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Scripts");
					sys.path.append(scriptsPath);

					dynamic mainMod = Py.Import("main");
					_pyMain = mainMod.Main(notionToken, 3);
					_currentToken = notionToken;
					Logger.Info("END Init Python Main(token)");
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
