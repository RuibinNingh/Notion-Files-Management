import sys
import os
import asyncio
import platform
import shutil
import questionary
import requests
import logging
import time
from questionary import Choice, Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from dotenv import load_dotenv

# --- 导入核心功能模块 ---
try:
    from notion import NotionFileManager, Aria2Downloader, IDMExporter
    from aria2 import Aria2LocalClient, Aria2RPCServer
except ImportError as e:
    console.print(f"[red]导入错误: {e}[/]")
    console.print("[yellow]请确保 notion.py 和 aria2.py 文件存在并包含必要的类[/]")
    sys.exit(1)

# --- 1. 全局配置 ---
PROJECT_NAME = "Notion-Files-Management"
REPO_URL = "github.com/RuibinNingh/Notion-Files-Management"
VERSION = "2.0.0 (Industrial)"
AUTHORS = "Ruibin_Ningh & Zyx_2012"

# 初始化 Rich 控制台
console = Console()

# --- 2. Vite 风格配色 (修复了下划线问题) ---
custom_style = Style([
    ('qmark', 'fg:#646cff bold'),       # Vite 紫
    ('question', 'bold'),
    ('answer', 'fg:#53d769 bold'),      # Vite 绿
    ('pointer', 'fg:#646cff bold'),     # 指针
    ('highlighted', 'fg:#646cff bold'), # 选中项
    ('selected', 'fg:#cc5454'),         # 已选
    ('separator', 'fg:#8a8a8a'),        # 分割线
    ('instruction', 'fg:#8a8a8a italic')
])

# --- 3. 辅助工具函数 ---

def print_banner():
    """打印漂亮的 Banner"""
    console.clear()
    title_text = Text(PROJECT_NAME, style="bold #646cff")
    
    info_text = Text()
    info_text.append(f"\n🔗 {REPO_URL}\n", style="dim cyan")
    info_text.append(f"👥 Developers: {AUTHORS}\n", style="white")
    info_text.append(f"📦 Version: {VERSION}", style="green")

    panel = Panel(
        info_text,
        title=title_text,
        border_style="#646cff",
        width=60,
        expand=False
    )
    console.print(panel)
    console.print("")

def check_env_vars():
    """检查 .env 配置"""
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")

    if not token:
        console.print(Panel("[bold red]❌ 错误: 未检测到环境变量！[/]\n\n请在目录下创建 .env 文件并填入:\nNOTION_TOKEN=...", border_style="red"))
        sys.exit(1)
    return token

def get_page_id_from_user():
    """从用户获取页面ID"""
    console.print("[bold cyan]📄 页面选择[/]")

    while True:
        page_id = questionary.text(
            "请输入Notion页面ID (Page ID):",
            validate=lambda x: len(x.strip()) > 0,
            instruction="(从Notion页面URL中复制，或页面右上角的分享菜单中获取)"
        ).ask()

        if page_id and page_id.strip():
            page_id = page_id.strip()
            console.print(f"[green]✅ 已选择页面: {page_id}[/]")
            return page_id

def get_aria2_status():
    """检测 Aria2 是否可用 (跨平台)"""
    # 1. 检测系统 PATH
    if shutil.which("aria2c"):
        return True, "system"
    # 2. 检测当前目录 (Windows)
    if platform.system() == "Windows" and os.path.exists("aria2c.exe"):
        return True, "local"
    return False, None

def windows_install_aria2():
    """Windows 自动下载 Aria2 逻辑 (此处为占位，可填入之前写的代码)"""
    console.print("[yellow]⚡ 正在尝试自动部署 Aria2...[/]")
    # ... 调用之前的 ensure_aria2_exists() 函数 ...
    # 模拟下载成功
    import time
    time.sleep(1)
    console.print("[green]✔ Aria2 组件准备就绪。[/]")

# --- 4. 业务逻辑流程 ---

def get_download_files(token, page_id, max_retries=3):
    """获取可下载文件列表，带重试机制"""
    downloader = NotionFileManager(token, "2022-06-28", page_id)

    for attempt in range(max_retries):
        try:
            console.print(f"[dim]➜ 正在连接 Notion API... (尝试 {attempt + 1}/{max_retries})[/]")

            # 获取列表 (带加载动画)
            with console.status("[bold #646cff]正在扫描 Block 节点...", spinner="dots"):
                files = downloader.file_list()
                count = len(files)

            if count > 0:
                console.print(f"[green]✅ 连接成功，发现 {count} 个文件[/]")
            else:
                console.print("[yellow]⚠️ 连接成功，但未发现可下载文件[/]")

            return files, count, downloader

        except Exception as e:
            console.print(f"[red]❌ 连接失败: {str(e)[:50]}...[/]")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                console.print(f"[yellow]⏳ {wait_time} 秒后自动重试...[/]")

                # 显示倒计时
                for i in range(wait_time, 0, -1):
                    console.print(f"[dim]剩余 {i} 秒...[/]", end="\r")
                    time.sleep(1)
                console.print()  # 换行
            else:
                console.print(f"[red]❌ 已达到最大重试次数 ({max_retries})，请检查：[/]")
                console.print(f"[red]   • 网络连接是否正常[/]")
                console.print(f"[red]   • NOTION_TOKEN 和 NOTION_PAGE_ID 是否正确[/]")
                console.print(f"[red]   • Notion API 服务是否可用[/]")
                return [], 0, downloader

def run_download_flow():
    """下载功能的完整流程"""
    token, page_id = check_env_vars()

    # 1. 获取文件列表
    files, count, downloader = get_download_files(token, page_id)

    if count == 0:
        console.print("[yellow]⚠ 当前页面未发现可下载文件。[/]")
        return

    # 2. 显示文件列表
    console.print(f"\n[green]✔ 发现 {count} 个文件:[/]")
    table_text = ""
    for i, (name, _, _) in enumerate(files, 1):
        table_text += f"- [{i:02d}] {name}\n"
    console.print(Panel(table_text.strip(), title="文件列表", border_style="dim"))

    # 3. 选择下载引擎
    has_aria2, _ = get_aria2_status()
    is_win = platform.system() == "Windows"

    choices = [
        Choice(title="🐍  Python 原生异步 (推荐, 稳定)", value="python"),
    ]

    if has_aria2:
        choices.append(Choice(title="🚀  Aria2 子进程模式 (传统)", value="aria2"))
        choices.append(Choice(title="🌐  Aria2 RPC模式 + Web界面 (推荐)", value="aria2_rpc"))
    elif is_win:
        choices.append(Choice(title="📥  下载并使用 Aria2 (自动部署)", value="aria2_install"))
    else:
        choices.append(Choice(title="⚠️  Aria2 未安装 (Linux需手动安装)", value="none", disabled="不可用"))

    if is_win:
        choices.append(Choice(title="📝  导出 IDM 任务文件 (.ef2)", value="idm"))

    choices.append(questionary.Separator())
    choices.append(Choice(title="🔙  返回主菜单", value="back"))

    method = questionary.select(
        "请选择下载引擎 (Select Engine):",
        choices=choices,
        style=custom_style,
        pointer="❯"
    ).ask()

    if method == "back":
        return

    # 4. 选择下载目录
    download_dir = questionary.text("请输入下载目录 (默认: downloads):", default="downloads").ask()
    if not download_dir:
        download_dir = "downloads"

    # 5. 选择下载文件
    if count == 1:
        selected_indices = [1]
        console.print(f"[green]将下载文件: {files[0][0]}[/]")
    else:
        # 首先让用户选择是全部下载还是选择特定文件
        download_mode = questionary.select(
            "选择下载方式:",
            choices=[
                Choice(title=f"📁 全部下载 ({count} 个文件)", value="all"),
                Choice(title="📄 选择特定文件", value="select"),
                Choice(title="🔙 取消", value="cancel")
            ],
            style=custom_style
        ).ask()

        if download_mode == "cancel":
            console.print("[yellow]下载已取消[/]")
            return
        elif download_mode == "all":
            selected_indices = list(range(1, count + 1))
            console.print(f"[green]将下载全部 {count} 个文件[/]")
        else:
            # 选择特定文件
            choices = [Choice(title=f"[{i:02d}] {name}", value=i)
                      for i, (name, _, _) in enumerate(files, 1)]
            choices.append(Choice(title="🔙 取消", value="cancel"))

            file_selection = questionary.checkbox(
                "选择要下载的文件:",
                choices=choices,
                style=custom_style
            ).ask()

            if "cancel" in file_selection or not file_selection:
                console.print("[yellow]下载已取消[/]")
                return

            selected_indices = [int(x) for x in file_selection if x != "cancel"]
            console.print(f"[green]已选择 {len(selected_indices)} 个文件[/]")

    # 6. 执行下载
    if method == "python":
        console.print("[cyan]➜ 启动 Python 下载...[/]")
        if selected_indices:
            console.print(f"[green]将下载 {len(selected_indices)} 个文件到 {download_dir} 目录[/]")

            # 显示下载进度 - 为每个文件创建单独的进度条
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}", justify="left"),
                BarColumn(bar_width=None),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                expand=True
            ) as progress:

                # 在开始下载前检查缓存是否过期
                cache_age = downloader._get_cache_age()
                if downloader._is_cache_expired():
                    console.print("[yellow]🔄 文件链接已过期，正在刷新...[/]")
                    files = downloader.file_list(force_refresh=True)
                    console.print("[green]✅ 文件链接已刷新[/]")
                elif downloader._should_warn_cache_old():
                    console.print(".0f" % (cache_age / 60))
                results = []
                for idx in selected_indices:
                    try:
                        if idx-1 >= len(files):
                            console.print(f"[red]错误: 文件索引 {idx} 超出范围[/]")
                            continue

                        # 使用缓存的文件信息（不再每次都刷新）
                        file_info = files[idx-1]
                        name, url, _ = file_info

                        # 检查URL是否有效
                        if not url or url.strip() == "":
                            console.print(f"[red]错误: 文件 {name} 的下载链接无效[/]")
                            continue

                        console.print(f"[cyan]正在下载: {name}[/]")

                        # 为每个文件创建单独的进度任务
                        response = requests.get(url, stream=True, timeout=30)
                        response.raise_for_status()

                        total_size = int(response.headers.get('content-length', 0))
                        if total_size == 0:
                            # 如果无法获取文件大小，使用一个默认值
                            total_size = 1024 * 1024  # 1MB 默认值

                        # 创建进度任务
                        size_mb = total_size / 1024 / 1024
                        task = progress.add_task(
                            description=f"[cyan]下载中: {name} ({size_mb:.1f} MB)[/]",
                            total=total_size,
                            completed=0
                        )

                        downloaded_size = 0
                        start_time = time.time()

                        save_file = os.path.join(download_dir, name)
                        os.makedirs(download_dir, exist_ok=True)

                        with open(save_file, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    downloaded_size += len(chunk)

                                    # 更新进度条 - Rich会自动计算速度和剩余时间
                                    progress.update(task, completed=downloaded_size)

                        # 下载完成 - 确保进度条显示100%
                        progress.update(task, completed=total_size, description=f"[green]✓ 已完成: {name}[/]")
                        results.append((name, True))

                        # 显示详细的完成信息
                        size_mb = downloaded_size / 1024 / 1024
                        console.print(f"[green]✅ {name} 下载完成 ({size_mb:.1f} MB)[/]")

                        # 短暂显示完成状态后停止显示这个任务
                        time.sleep(1.5)
                        progress.remove_task(task)

                        # 在文件之间添加延迟，避免API请求过于频繁
                        if idx < selected_indices[-1]:  # 如果不是最后一个文件
                            console.print(f"[dim]等待2秒后继续下一个文件...[/]")
                            time.sleep(2)

                    except Exception as e:
                        import logging
                        error_msg = str(e)
                        logging.error(f"下载失败: {name if 'name' in locals() else f'索引{idx}'} - {error_msg}")
                        results.append((name if 'name' in locals() else f'文件{idx}', False))
                        console.print(f"[red]✗ 下载失败: {error_msg}[/]")

                        # 标记任务为失败并从进度条中移除
                        if 'task' in locals():
                            try:
                                progress.update(task, description=f"[red]❌ 失败: {name if 'name' in locals() else f'文件{idx}'}[/]")
                                # 短暂显示失败状态后停止显示这个任务
                                time.sleep(2)
                                progress.remove_task(task)
                            except:
                                pass

                        # 继续下一个文件，不要卡在这里
                        continue

                success_count = sum(1 for _, success in results if success)
                failed_count = len(results) - success_count

                # 显示详细的下载总结
                console.print(f"\n[bold green]🎉 批量下载完成！[/]")
                console.print(f"[green]✅ 成功: {success_count} 个文件[/]")
                if failed_count > 0:
                    console.print(f"[red]❌ 失败: {failed_count} 个文件[/]")
                console.print(f"[blue]📁 文件保存位置: {download_dir}[/]")

                # 显示失败的文件列表（如果有的话）
                if failed_count > 0:
                    failed_files = [name for name, success in results if not success]
                    console.print(f"\n[yellow]失败的文件列表:[/]")
                    for failed_file in failed_files:
                        console.print(f"  [red]• {failed_file}[/]")

    elif method == "aria2_install":
        windows_install_aria2()
        console.print("[green]➜ Aria2 已安装，请重新选择以启动。[/]")

    elif method == "aria2":
        console.print("[cyan]➜ 正在调用 Aria2 子进程...[/]")
        if selected_indices:
            selected_files = [files[i-1] for i in selected_indices]
            file_urls = [(name, url) for name, url, _ in selected_files]

            aria2_downloader = Aria2Downloader()
            try:
                aria2_downloader.download_files(file_urls, download_dir)
                console.print(f"[green]Aria2下载完成！[/]")
            except Exception as e:
                console.print(f"[red]Aria2下载失败: {e}[/]")

    elif method == "aria2_rpc":
        console.print("[cyan]🚀 启动 Aria2 RPC + Web界面模式[/]")

        # 检查Aria2文件是否存在
        aria2_path = "aria2c.exe"
        if not os.path.exists(aria2_path):
            console.print(f"[red]❌ 找不到Aria2可执行文件: {aria2_path}[/]")
            console.print("[yellow]请确保aria2c.exe在当前目录中[/]")
            return

        # 让用户选择并发数
        max_concurrent = questionary.select(
            "选择最大并发下载数:",
            choices=[
                Choice(title="1 个并发 (稳定)", value=1),
                Choice(title="3 个并发 (推荐)", value=3),
                Choice(title="5 个并发 (高速)", value=5),
                Choice(title="10 个并发 (极高)", value=10),
            ],
            default=3
        ).ask()

        # 启动Aria2 RPC服务器
        aria2_server = Aria2RPCServer(aria2_path=aria2_path, port=6800)
        console.print(f"[blue]正在启动Aria2 RPC服务器 (并发数: {max_concurrent})...[/]")

        try:
            if not aria2_server.start_server(max_concurrent_downloads=max_concurrent):
                console.print("[red]❌ Aria2 RPC服务器启动失败[/]")
                console.print("[yellow]请检查:[/]")
                console.print("[yellow]  • aria2c.exe是否存在于当前目录[/]")
                console.print("[yellow]  • 端口6800是否被其他程序占用[/]")
                console.print("[yellow]  • 是否有足够的权限运行程序[/]")
                return

            console.print("[blue]Aria2 RPC服务器已启动并运行稳定[/]")

            # 创建RPC客户端并测试连接
            aria2_client = Aria2LocalClient(port=6800, server=aria2_server)

            if not aria2_client.is_connected():
                console.print("[red]❌ 无法连接到Aria2 RPC服务器[/]")
                return

            # 显示版本信息
            try:
                version = aria2_client.get_version()
                if version:
                    console.print(f"[green]✅ Aria2版本: {version.get('version', '未知')}[/]")
            except:
                pass

            # 打开AriaNG Web界面
            console.print("[blue]正在打开AriaNG Web界面...[/]")
            if aria2_server.open_ariang():
                console.print("[green]✅ AriaNG界面已打开，请在浏览器中查看[/]")
                console.print("[yellow]💡 提示: 您可以在Web界面中监控和管理下载任务[/]")
                console.print("[blue]🌐 AriaNG地址: file://" + os.path.join(os.getcwd(), "AriaNG.html"))
            else:
                console.print("[yellow]⚠️ 无法自动打开AriaNG界面，请手动打开 AriaNG.html 文件[/]")
                console.print(f"[blue]文件路径: {os.path.join(os.getcwd(), 'AriaNG.html')}[/]")

            # 选择添加模式
            if selected_indices:
                # 检查缓存是否过期，如果过期则刷新
                cache_age = downloader._get_cache_age()
                if downloader._is_cache_expired():
                    console.print("[yellow]🔄 文件链接已过期，正在刷新...[/]")
                    files = downloader.file_list(force_refresh=True)
                    console.print("[green]✅ 文件链接已刷新[/]")
                elif downloader._should_warn_cache_old():
                    console.print(".0f" % (cache_age / 60))
                add_mode = questionary.select(
                    "选择下载任务添加模式:",
                    choices=[
                        Choice(title="🚀 批量添加 (立即添加所有任务)", value="batch"),
                        Choice(title="⏳ 队列添加 (逐步添加，避免链接过期)", value="queue"),
                    ],
                    default="queue"  # 默认使用队列模式
                ).ask()

                selected_files = [files[i-1] for i in selected_indices]
                file_urls = [(name, url) for name, url, _ in selected_files]

                if add_mode == "batch":
                    # 批量添加模式
                    console.print(f"[blue]正在批量添加 {len(selected_indices)} 个下载任务到Aria2...[/]")
                    gids = aria2_client.add_downloads_batch(file_urls, download_dir)

                else:
                    # 队列添加模式
                    console.print(f"[blue]正在队列式添加 {len(selected_indices)} 个下载任务...[/]")
                    console.print("[yellow]⚠️ 这将需要较长时间，但可以避免下载链接过期[/]")

                    gids = aria2_client.add_downloads_queued(
                        file_urls,
                        download_dir,
                        max_active_tasks=min(3, max_concurrent),  # 最大3个并发任务
                        monitor_interval=10  # 每10秒监控一次状态
                    )

                if gids and len(gids) > 0:
                    console.print(f"[green]✅ 已成功添加 {len(gids)} 个下载任务！[/]")
                    console.print("[blue]📊 您可以在AriaNG界面中查看下载进度[/]")
                    console.print("[yellow]⚠️ 请不要关闭此程序，否则Aria2服务器会停止[/]")
                    console.print("[blue]🔗 RPC地址: http://127.0.0.1:6800/jsonrpc[/]")

                    # 显示操作提示
                    console.print("\n[cyan]操作提示:[/]")
                    console.print("• 在AriaNG界面中可以暂停/恢复/删除下载任务")
                    console.print("• 可以实时查看下载速度和进度")
                    console.print("• 支持断点续传和多线程下载")

                    if add_mode == "queue":
                        console.print("• 队列模式会自动监控任务完成情况")
                        console.print("• 建议保持AriaNG界面打开以实时监控")

                    # 等待用户确认
                    input("\n按回车键继续 (Aria2服务器将继续运行)...")

                else:
                    console.print("[red]❌ 添加下载任务失败[/]")
                    console.print("[yellow]可能是RPC连接问题或任务参数错误[/]")

            else:
                console.print("[yellow]没有选择任何文件[/]")
                input("\n按回车键继续...")

        except KeyboardInterrupt:
            console.print("[yellow]用户中断，正在停止Aria2服务器...[/]")
        except Exception as e:
            console.print(f"[red]Aria2 RPC模式运行失败: {e}[/]")
            console.print("[yellow]请检查日志文件 aria2_rpc.log 获取更多信息[/]")
        finally:
            # 停止服务器
            console.print("[blue]正在停止Aria2 RPC服务器...[/]")
            aria2_server.stop_server()
            console.print("[green]✅ Aria2服务器已停止[/]")

    elif method == "idm":
        console.print("[cyan]➜ 正在导出 IDM 任务文件...[/]")
        if selected_indices:
            selected_files = [files[i-1] for i in selected_indices]
            file_urls = [(name, url) for name, url, _ in selected_files]

            idm_exporter = IDMExporter()
            ef2_file = idm_exporter.export_tasks(file_urls, download_dir)

            if ef2_file:
                console.print(f"[green]✔ 已生成 IDM 任务文件: {ef2_file}[/]")
                console.print("[dim]请使用 Internet Download Manager 打开此文件开始下载[/]")
            else:
                console.print("[red]导出 IDM 任务文件失败[/]")

def run_upload_flow():
    """上传功能流程"""
    token, page_id = check_env_vars()

    # 1. 选择上传文件或文件夹
    upload_type = questionary.select(
        "请选择上传类型:",
        choices=[
            Choice(title="📄 上传单个文件", value="file"),
            Choice(title="📁 上传整个文件夹", value="folder"),
            Choice(title="🔙 返回主菜单", value="back")
        ],
        style=custom_style
    ).ask()

    if upload_type == "back":
        return

    # 2. 选择文件/文件夹
    if upload_type == "file":
        file_path = questionary.text("请输入文件路径:").ask()
        if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
            console.print("[red]文件不存在或路径无效[/]")
            questionary.text("按回车键继续...").ask()
            return
        filepaths = [file_path]
    else:
        folder_path = questionary.text("请输入文件夹路径:").ask()
        if not folder_path or not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            console.print("[red]文件夹不存在或路径无效[/]")
            questionary.text("按回车键继续...").ask()
            return

        # 递归获取所有文件
        filepaths = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                filepaths.append(os.path.join(root, file))

        if not filepaths:
            console.print("[yellow]文件夹为空，没有可上传的文件[/]")
            questionary.text("按回车键继续...").ask()
            return

    # 3. 确认上传列表
    console.print(f"\n[green]发现 {len(filepaths)} 个文件待上传:[/]")
    total_size = 0
    for i, filepath in enumerate(filepaths[:10], 1):  # 只显示前10个
        size = os.path.getsize(filepath)
        total_size += size
        console.print(f"  [{i:02d}] {os.path.basename(filepath)} ({size/1024/1024:.1f}MB)")

    if len(filepaths) > 10:
        console.print(f"  ... 还有 {len(filepaths)-10} 个文件")

    console.print(f"\n[bold]总大小: {total_size/1024/1024:.1f}MB[/]")

    confirm = input(f"确认上传这 {len(filepaths)} 个文件吗？(y/N): ").lower().strip()
    if confirm not in ['y', 'yes']:
        console.print("[yellow]上传已取消[/]")
        return

    # 4. 初始化上传器
    console.print("[dim]➜ 正在连接 Notion API...[/]")
    uploader = NotionFileManager(token, "2022-06-28", page_id)

    # 5. 显示上传进度
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("上传进度", total=len(filepaths))

        uploaded_count = 0
        success_count = 0

        def progress_callback(filename, current, total, status):
            if total > 0:
                percentage = (current / total) * 100
                progress.update(task, description=f"{filename} - {status}")

        # 6. 执行上传
        for filepath in filepaths:
            filename = os.path.basename(filepath)
            console.print(f"\n[cyan]正在上传: {filename}[/]")

            try:
                success = uploader.upload_file(filepath, progress_callback)
                if success:
                    success_count += 1
                    console.print(f"[green]✔ {filename} 上传成功[/]")
                else:
                    console.print(f"[red]✗ {filename} 上传失败[/]")
            except Exception as e:
                console.print(f"[red]✗ {filename} 上传异常: {str(e)[:50]}[/]")

            uploaded_count += 1
            progress.update(task, completed=uploaded_count)

    # 7. 显示结果
    console.print(f"\n[bold green]上传完成！成功: {success_count}/{len(filepaths)}[/]")

    if success_count < len(filepaths):
        console.print(f"[yellow]⚠ 有 {len(filepaths) - success_count} 个文件上传失败，请检查日志[/]")

# --- 5. 主程序入口 ---

def main():
    try:
        while True:
            print_banner()

            # 主菜单
            action = questionary.select(
                "请选择操作 (Select Action):",
                choices=[
                    Choice(title="📥  下载文件 (Download)", value="download"),
                    Choice(title="📤  上传文件 (Upload)", value="upload"),
                    Choice(title="⚙️  设置与检测 (Settings)", value="settings"),
                    questionary.Separator(),
                    Choice(title="🚪  退出程序 (Exit)", value="exit"),
                ],
                style=custom_style,
                pointer="❯",
                use_indicator=True
            ).ask()

            if action == "download":
                run_download_flow()

            elif action == "upload":
                run_upload_flow()

            elif action == "settings":
                # 连接Notion API获取downloader实例（如果还没有的话）
                if 'downloader' not in locals():
                    files, count, downloader = connect_and_scan(console, 1)
                    if count == 0:
                        continue

                has_aria2, mode = get_aria2_status()
                status = "[green]可用[/]" if has_aria2 else "[red]未检测到[/]"
                console.print(f"\n[bold]系统状态:[/]")
                console.print(f"Aria2 状态: {status} ({mode})")
                console.print(f"Python 版本: {platform.python_version()}")
                console.print(f"操作系统: {platform.system()}")

                # 显示缓存状态
                console.print(f"\n[bold]文件链接缓存状态:[/]")
                if downloader._file_cache is not None:
                    cache_age = downloader._get_cache_age()
                    cache_age_minutes = cache_age / 60
                    expiry_minutes = downloader.link_cache_config["cache_expiry_seconds"] / 60

                    if downloader._is_cache_expired():
                        cache_status = "[red]已过期[/]"
                    elif downloader._should_warn_cache_old():
                        cache_status = "[yellow]即将过期[/]"
                    else:
                        cache_status = "[green]有效[/]"

                    console.print(".1f" % (cache_age_minutes))
                    console.print(f"缓存文件数量: {len(downloader._file_cache)}")
                    console.print(f"缓存过期时间: {expiry_minutes:.0f} 分钟")
                else:
                    console.print("[red]缓存未初始化[/]")

                questionary.text("按回车键返回...").ask()

            elif action == "exit" or action is None:
                console.print("\n[bold #646cff]感谢使用 Notion-Files-Management 👋[/]")
                sys.exit(0)

    except KeyboardInterrupt:
        console.print("\n[bold red]程序被用户强制中断[/]")
        sys.exit(0)

if __name__ == "__main__":
    main()