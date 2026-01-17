# Notion-Files-Management - 主程序文件
# Copyright (C) 2025-2026 Ruibin_Ningh & Zyx_2012
# License: GPL v3

import os
import sys
import time
import math
import queue
import platform
import shutil
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import List, Tuple, Optional, Dict

import questionary
import requests
from questionary import Choice, Style
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn, 
    TaskProgressColumn, TimeRemainingColumn, DownloadColumn,
    TransferSpeedColumn
)
from rich import box
from dotenv import load_dotenv

from notion import (
    NotionFileManager, IDMExporter, UploadProgress, UploadStatus,
    UploadFileInfo, MAX_FILE_SIZE, PART_SIZE, logger as notion_logger
)
from aria2 import Aria2Client, Aria2Server
from rich_ui import ModernUploadUI, TaskStatus as UITaskStatus

# ============ 全局配置 ============

VERSION = "2.1.0"  # 版本更新
PROJECT_NAME = "Notion-Files-Management"

console = Console()

STYLE = Style([
    ('qmark', 'fg:#646cff bold'),
    ('question', 'bold'),
    ('answer', 'fg:#53d769 bold'),
    ('pointer', 'fg:#646cff bold'),
    ('selected', 'fg:#cc5454'),
])


# ============ 工具函数 ============

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_banner():
    clear_screen()
    console.print(Panel(
        f"[dim cyan]🔗 github.com/RuibinNingh/Notion-Files-Management[/]\n"
        f"[white]👥 Developers: Ruibin_Ningh & Zyx_2012[/]\n"
        f"[green]📦 Version: {VERSION}[/]",
        title=f"[bold #646cff]{PROJECT_NAME}[/]",
        border_style="#646cff",
        width=55
    ))
    console.print()


def check_env() -> Tuple[str, str]:
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    version = os.getenv("NOTION_VERSION", "2025-09-03")
    
    if not token:
        console.print(Panel(
            "[bold red]❌ 未检测到 NOTION_TOKEN[/]\n\n"
            "请在目录下创建 .env 文件:\n"
            "NOTION_TOKEN=your_token_here",
            border_style="red"
        ))
        sys.exit(1)
    
    return token, version


def get_page_id() -> str:
    while True:
        page_id = questionary.text(
            "请输入Notion页面ID:",
            instruction="(从页面URL或分享菜单获取)"
        ).ask()
        
        if page_id and page_id.strip():
            console.print(f"[green]✅ 页面ID: {page_id.strip()}[/]")
            return page_id.strip()


def check_aria2() -> Tuple[bool, str]:
    if shutil.which("aria2c"):
        return True, "system"
    if platform.system() == "Windows" and os.path.exists("aria2c.exe"):
        return True, "local"
    return False, ""


def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_time(seconds: float) -> str:
    if seconds < 0:
        return "--:--"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ============ 状态映射 ============

def map_status(upload_status: UploadStatus) -> UITaskStatus:
    """将 notion.py 的 UploadStatus 映射到 rich_ui 的 TaskStatus"""
    mapping = {
        UploadStatus.PENDING: UITaskStatus.PENDING,
        UploadStatus.UPLOADING: UITaskStatus.UPLOADING,
        UploadStatus.COMPLETING: UITaskStatus.COMPLETING,
        UploadStatus.ATTACHING: UITaskStatus.ATTACHING,
        UploadStatus.COMPLETED: UITaskStatus.COMPLETED,
        UploadStatus.FAILED: UITaskStatus.FAILED,
        UploadStatus.RETRYING: UITaskStatus.RETRYING,
        UploadStatus.CHECKING: UITaskStatus.CHECKING,
        UploadStatus.RECOVERING: UITaskStatus.RECOVERING,
    }
    return mapping.get(upload_status, UITaskStatus.PENDING)


# ============ 上传任务数据类 ============

class UploadTask:
    """上传任务"""
    def __init__(self, task_id: int, file_info: UploadFileInfo, target_page_id: str):
        self.id = task_id
        self.file_info = file_info
        self.target_page_id = target_page_id
        self.status = UploadStatus.PENDING
        self.progress = 0.0
        self.uploaded_bytes = 0
        self.part_current = 0
        self.part_total = 0
        self.retry_count = 0
        self.error_message = ""
        self.thread_id: Optional[int] = None
        self.start_time: Optional[float] = None


# ============ 适配器类：保持原有API，内部使用新UI ============

class RichUploadUI:
    """
    适配器类 - 保持原有API不变，内部使用新的 ModernUploadUI
    这样不需要修改 NotionUploader 类的任何代码
    """
    
    def __init__(self, total_files: int, total_size: int, num_threads: int):
        # 使用新的现代UI
        self._ui = ModernUploadUI(total_files, total_size, num_threads)
        self.console = self._ui.console
        self.lock = self._ui.lock
        
        # 兼容性属性
        self.total_files = total_files
        self.total_size = total_size
        self.num_threads = num_threads
        
        # 任务存储（兼容原有接口）
        self.tasks: Dict[int, UploadTask] = {}
        
    @property
    def completed_count(self):
        return self._ui.completed_count
    
    @property
    def failed_count(self):
        return self._ui.failed_count
    
    def add_task(self, task: UploadTask):
        """添加任务 (保持原有签名)"""
        self.tasks[task.id] = task
        self._ui.add_task(
            task_id=task.id,
            filename=task.file_info.original_name,
            filesize=task.file_info.size,
            target_page_id=task.target_page_id,
        )
    
    def update_task(self, task_id: int, **kwargs):
        """更新任务 (保持原有签名)"""
        # 更新本地任务对象
        if task_id in self.tasks:
            task = self.tasks[task_id]
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
        
        # 转换状态枚举
        ui_kwargs = kwargs.copy()
        if 'status' in ui_kwargs:
            ui_kwargs['status'] = map_status(ui_kwargs['status'])
        
        self._ui.update_task(task_id, **ui_kwargs)
    
    def add_uploaded_bytes(self, bytes_count: int):
        """增加已上传字节数"""
        self._ui.add_uploaded_bytes(bytes_count)
    
    def mark_completed(self, task_id: int, success: bool):
        """标记任务完成"""
        self._ui.mark_completed(task_id, success)
    
    def start(self):
        """启动UI"""
        self._ui.start()
    
    def refresh(self):
        """刷新UI"""
        self._ui.refresh()
    
    def stop(self):
        """停止UI"""
        self._ui.stop()
        
        # 显示日志文件路径
        try:
            log_path = getattr(notion_logger, 'log_file_path', None)
            if log_path:
                console.print(f"\n[dim]📋 详细日志已保存到: {log_path}[/dim]")
        except:
            pass


# ============ 上传器 ============

class NotionUploader:
    """Notion上传器 - 多线程上传支持"""
    
    def __init__(self, manager: NotionFileManager, num_threads: int = 3):
        self.manager = manager
        self.num_threads = num_threads
        self.task_queue: queue.Queue = queue.Queue()
        self.ui: Optional[RichUploadUI] = None
        self.stop_event = threading.Event()
        self.console = Console()
    
    def upload_files(self, filepaths: List[str], target_page_id: str = None):
        """上传多个文件"""
        page_id = target_page_id or self.manager.current_page_id
        if not page_id:
            raise ValueError("请指定目标页面ID")
        
        # 过滤有效文件
        valid_files = []
        for fp in filepaths:
            if os.path.exists(fp) and os.path.getsize(fp) <= MAX_FILE_SIZE:
                valid_files.append(UploadFileInfo.from_path(fp))
        
        if not valid_files:
            self.console.print("[yellow]没有有效的文件可上传[/yellow]")
            return
        
        total_size = sum(f.size for f in valid_files)
        
        # 显示文件信息
        self.console.print(f"\n[green]共 {len(valid_files)} 个文件, 总计 {format_size(total_size)}[/green]")
        spoofed = [f for f in valid_files if f.is_spoofed]
        if spoofed:
            self.console.print(f"[yellow]⚠️  {len(spoofed)} 个文件将使用后缀伪装上传[/yellow]")
        
        self.console.print("\n[dim]3秒后开始上传...[/dim]")
        time.sleep(3)
        
        # 初始化UI - 使用新的适配器
        self.ui = RichUploadUI(len(valid_files), total_size, self.num_threads)
        
        # 创建任务
        for i, file_info in enumerate(valid_files):
            task = UploadTask(task_id=i, file_info=file_info, target_page_id=page_id)
            self.ui.add_task(task)
            self.task_queue.put(task)
        
        self.ui.start()
        
        # 启动工作线程
        threads = []
        for i in range(self.num_threads):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)
        
        # 主线程刷新UI
        try:
            while not self.task_queue.empty() or any(t.is_alive() for t in threads):
                self.ui.refresh()
                time.sleep(0.25)
                
                with self.ui.lock:
                    done = self.ui.completed_count + self.ui.failed_count >= self.ui.total_files
                if done:
                    break
        except KeyboardInterrupt:
            self.console.print("\n\n[yellow]⏹️  正在停止...[/yellow]")
            self.stop_event.set()
        
        try:
            self.task_queue.join()
        except:
            pass
        
        self.stop_event.set()
        self.ui.stop()
    
    def upload_directory(self, directory: Path, parent_page_id: str = None):
        """上传整个目录（保持目录结构）"""
        page_id = parent_page_id or self.manager.current_page_id
        if not page_id:
            raise ValueError("请指定目标页面ID")
        
        # 扫描目录
        with self.console.status("[bold green]正在扫描目录结构...", spinner="dots"):
            all_files = []
            for item in directory.rglob('*'):
                if item.is_file():
                    file_info = UploadFileInfo.from_path(str(item))
                    if file_info.size <= MAX_FILE_SIZE:
                        all_files.append((item, file_info))
        
        if not all_files:
            self.console.print("[yellow]⚠️  目录中没有找到可上传的文件[/yellow]")
            return
        
        total_size = sum(f.size for _, f in all_files)
        
        # 统计子目录
        subdirs = set()
        for item, _ in all_files:
            rel_path = item.relative_to(directory)
            if len(rel_path.parts) > 1:
                subdirs.add(rel_path.parts[0])
        
        self.console.print(f"\n[green]✅ 找到 {len(all_files)} 个文件，总大小 {format_size(total_size)}[/green]")
        if subdirs:
            self.console.print(f"[cyan]📁 包含 {len(subdirs)} 个子目录[/cyan]")
        self.console.print(f"[cyan]🧵 使用 {self.num_threads} 个线程进行上传[/cyan]")
        
        spoofed = [f for _, f in all_files if f.is_spoofed]
        if spoofed:
            self.console.print(f"[yellow]⚠️  {len(spoofed)} 个文件将使用后缀伪装上传[/yellow]")
        
        # 创建目录对应的页面
        page_mapping: Dict[Path, str] = {directory: page_id}
        
        if subdirs:
            self.console.print("\n[bold green]正在创建目录结构...[/bold green]")
            page_mapping = self._prepare_directory_pages(directory, page_id)
            self.console.print(f"[green]✅ 创建了 {len(page_mapping) - 1} 个子页面[/green]")
        
        self.console.print("\n[dim]3秒后开始上传...[/dim]")
        time.sleep(3)
        
        # 初始化UI - 使用新的适配器
        self.ui = RichUploadUI(len(all_files), total_size, self.num_threads)
        
        # 创建任务，分配到对应页面
        for i, (item, file_info) in enumerate(all_files):
            target_page = page_id
            file_dir = item.parent
            
            while file_dir != directory.parent:
                if file_dir in page_mapping:
                    target_page = page_mapping[file_dir]
                    break
                file_dir = file_dir.parent
            
            task = UploadTask(task_id=i, file_info=file_info, target_page_id=target_page)
            self.ui.add_task(task)
            self.task_queue.put(task)
        
        self.ui.start()
        
        # 启动工作线程
        threads = []
        for i in range(self.num_threads):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)
        
        # 主线程刷新UI
        try:
            while not self.task_queue.empty() or any(t.is_alive() for t in threads):
                self.ui.refresh()
                time.sleep(0.25)
                
                with self.ui.lock:
                    done = self.ui.completed_count + self.ui.failed_count >= self.ui.total_files
                if done:
                    break
        except KeyboardInterrupt:
            self.console.print("\n\n[yellow]⏹️  正在停止...[/yellow]")
            self.stop_event.set()
        
        try:
            self.task_queue.join()
        except:
            pass
        
        self.stop_event.set()
        self.ui.stop()
    
    def _prepare_directory_pages(self, directory: Path, parent_page_id: str) -> Dict[Path, str]:
        """递归创建目录对应的页面"""
        page_mapping: Dict[Path, str] = {directory: parent_page_id}
        
        def create_recursive(current_dir: Path, current_page_id: str):
            for item in sorted(current_dir.iterdir()):
                if item.is_dir():
                    success, result = self.manager.create_child_page(current_page_id, item.name)
                    if success:
                        child_page_id = result['id']
                        page_mapping[item] = child_page_id
                        create_recursive(item, child_page_id)
                    else:
                        self.console.print(f"[yellow]⚠️  创建页面失败 {item.name}: {result}[/yellow]")
        
        create_recursive(directory, parent_page_id)
        return page_mapping
    
    def _worker(self, thread_id: int):
        """工作线程"""
        while not self.stop_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.5)
                self._upload_task(task, thread_id)
                self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass
    
    def _upload_task(self, task: UploadTask, thread_id: int):
        """执行单个上传任务"""
        task.thread_id = thread_id
        task.start_time = time.time()
        self.ui.update_task(task.id, thread_id=thread_id)
        
        def progress_callback(progress: UploadProgress):
            task.status = progress.status
            task.part_current = progress.part_current
            task.part_total = progress.part_total
            task.retry_count = progress.retry_count
            
            # 先计算差值，再更新已上传字节数
            bytes_diff = progress.uploaded - task.uploaded_bytes
            task.uploaded_bytes = progress.uploaded
            task.progress = progress.uploaded / progress.total if progress.total else 0
            
            self.ui.update_task(
                task.id,
                status=progress.status,
                progress=task.progress,
                part_current=progress.part_current,
                part_total=progress.part_total,
                retry_count=progress.retry_count
            )
            
            # 更新已上传字节数
            if progress.status == UploadStatus.UPLOADING and bytes_diff > 0:
                self.ui.add_uploaded_bytes(bytes_diff)
        
        try:
            success = self.manager.upload_file(
                task.file_info.path,
                target_page_id=task.target_page_id,
                progress_callback=progress_callback
            )
            
            if success:
                self.ui.update_task(task.id, status=UploadStatus.COMPLETED, progress=1.0)
                self.ui.mark_completed(task.id, True)
                # 确保最终字节数正确
                remaining = task.file_info.size - task.uploaded_bytes
                if remaining > 0:
                    self.ui.add_uploaded_bytes(remaining)
            else:
                self.ui.update_task(task.id, status=UploadStatus.FAILED, error_message="上传失败")
                self.ui.mark_completed(task.id, False)
                
        except Exception as e:
            self.ui.update_task(task.id, status=UploadStatus.FAILED, error_message=str(e))
            self.ui.mark_completed(task.id, False)


# ============ 下载流程 ============

def run_download():
    token, version = check_env()
    page_id = get_page_id()
    
    console.print("[dim]正在获取文件列表...[/]")
    manager = NotionFileManager(token, version)
    manager.set_page(page_id)
    
    try:
        files = manager.file_list()
    except Exception as e:
        console.print(f"[red]❌ 获取文件列表失败: {e}[/]")
        return
    
    if not files:
        console.print("[yellow]⚠ 当前页面没有文件[/]")
        return
    
    console.print(f"\n[green]发现 {len(files)} 个文件:[/]")
    for i, (name, _, _) in enumerate(files[:20], 1):
        console.print(f"  [{i:02d}] {name}")
    if len(files) > 20:
        console.print(f"  [dim]... 还有 {len(files) - 20} 个文件[/]")
    
    has_aria2, aria2_mode = check_aria2()
    
    download_method = questionary.select("下载方式:", choices=[
        Choice("📋 导出IDM任务", "idm"),
        Choice("📥 Aria2下载" + (" (需安装)" if not has_aria2 else ""), "aria2"),
        Choice("🔙 返回", "back")
    ], style=STYLE).ask()
    
    if download_method == "back":
        return
    
    # 选择文件
    file_selection = questionary.select("选择范围:", choices=[
        Choice("全部文件", "all"),
        Choice("选择序号", "select"),
    ], style=STYLE).ask()
    
    if file_selection == "all":
        indices = list(range(len(files)))
    else:
        ranges = questionary.text(
            "输入序号(如: 1-5,8,10-15):",
        ).ask()
        
        if not ranges:
            return
        
        indices = []
        for part in ranges.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-', 1)
                indices.extend(range(int(start) - 1, int(end)))
            else:
                indices.append(int(part) - 1)
        
        indices = [i for i in indices if 0 <= i < len(files)]
    
    if not indices:
        console.print("[yellow]未选择任何文件[/]")
        return
    
    console.print(f"[green]已选择 {len(indices)} 个文件[/]")
    
    save_dir = questionary.text("保存目录:", default="downloads").ask()
    os.makedirs(save_dir, exist_ok=True)
    
    if download_method == "aria2":
        _download_aria2(files, indices, save_dir, has_aria2, aria2_mode)
    else:
        _export_idm(files, indices, save_dir)


def _download_aria2(files: list, indices: list, save_dir: str, has_aria2: bool, aria2_mode: str):
    if not has_aria2:
        console.print("[red]❌ Aria2不可用[/]")
        return
    
    aria2_path = "aria2c" if aria2_mode == "system" else "aria2c.exe"
    server = Aria2Server(aria2_path)
    
    concurrent = questionary.select("并发数:", choices=[
        Choice("3 (推荐)", 3),
        Choice("5", 5),
        Choice("10", 10),
    ], default=3, style=STYLE).ask()
    concurrent = concurrent if concurrent else 3
    
    if not server.start(max_concurrent=concurrent):
        console.print("[red]❌ Aria2启动失败[/]")
        return
    
    try:
        server.open_ariang()
        console.print("[blue]已打开AriaNG界面[/]")
        
        client = Aria2Client(port=6800)
        file_urls = [(files[i][0], files[i][1]) for i in indices]
        
        gids = client.add_downloads_batch(file_urls, save_dir)
        console.print(f"\n[green]已添加 {len(gids)} 个任务[/]")
        console.print("[yellow]请在AriaNG中查看进度，输入'stop'关闭服务器...[/]")
        
        # 等待用户输入stop
        while True:
            user_input = input().strip().lower()
            if user_input == "stop":
                break
            else:
                console.print("[yellow]请输入'stop'来关闭服务器[/]")
        
    finally:
        server.stop()


def _export_idm(files: list, indices: list, save_dir: str):
    file_urls = [(files[i][0], files[i][1]) for i in indices]
    ef2_file = IDMExporter.export_tasks(file_urls, save_dir)
    
    if ef2_file:
        console.print(f"[green]✅ 已导出: {ef2_file}[/]")
    else:
        console.print("[red]❌ 导出失败[/]")
    
    # 添加用户确认，防止直接跳转
    questionary.text("按回车返回...").ask()


# ============ 上传流程 ============

def run_upload():
    token, version = check_env()
    page_id = get_page_id()
    
    upload_type = questionary.select("上传类型:", choices=[
        Choice("📄 单个文件", "file"),
        Choice("📁 整个文件夹", "folder"),
        Choice("🔙 返回", "back")
    ], style=STYLE).ask()
    
    if upload_type == "back":
        return
    
    if upload_type == "file":
        path = questionary.text("文件路径:").ask()
        if not path or not os.path.isfile(path):
            console.print("[red]文件不存在[/]")
            return
        filepaths = [path]
    else:
        path = questionary.text("文件夹路径:").ask()
        if not path or not os.path.isdir(path):
            console.print("[red]文件夹不存在[/]")
            return
        filepaths = [os.path.join(root, f) for root, _, files in os.walk(path) for f in files]
    
    if not filepaths:
        console.print("[yellow]没有找到文件[/]")
        return
    
    total_size = sum(os.path.getsize(f) for f in filepaths if os.path.exists(f))
    console.print(f"\n[green]共 {len(filepaths)} 个文件, 总计 {format_size(total_size)}[/]")
    
    for f in filepaths[:5]:
        console.print(f"  • {os.path.basename(f)} ({format_size(os.path.getsize(f))})")
    if len(filepaths) > 5:
        console.print(f"  [dim]... 还有 {len(filepaths) - 5} 个文件[/]")
    
    if not questionary.confirm("确认上传?", default=False).ask():
        return
    
    concurrent = questionary.select("并发线程:", choices=[
        Choice("1 (稳定)", 1),
        Choice("2 (推荐)", 2),
        Choice("3 (高速)", 3),
    ], default=2, style=STYLE).ask()
    concurrent = concurrent if concurrent else 2
    
    console.print("[dim]连接Notion API...[/]")
    manager = NotionFileManager(token, version)
    manager.set_page(page_id)
    
    uploader = NotionUploader(manager, num_threads=concurrent)
    
    if upload_type == "folder":
        uploader.upload_directory(Path(path), page_id)
    else:
        uploader.upload_files(filepaths, page_id)
    
    questionary.text("按回车返回...").ask()


# ============ 文件处理 ============

def run_file_processing():
    folder = questionary.text("输入文件夹路径:").ask()
    
    if not folder or not os.path.isdir(folder):
        console.print("[red]文件夹不存在[/]")
        return
    
    all_files = []
    for root, _, files in os.walk(folder):
        for f in files:
            all_files.append(os.path.join(root, f))
    
    if not all_files:
        console.print("[yellow]文件夹为空[/]")
        return
    
    console.print(f"\n[green]发现 {len(all_files)} 个文件[/]")
    
    action = questionary.select("操作:", choices=[
        Choice("🗑️ 去除.txt后缀", "remove_txt"),
        Choice("📝 查看文件列表", "list"),
        Choice("🔙 返回", "back")
    ], style=STYLE).ask()
    
    if action == "back":
        return
    
    if action == "list":
        for f in all_files[:20]:
            console.print(f"  • {os.path.relpath(f, folder)}")
        if len(all_files) > 20:
            console.print(f"  [dim]... 还有 {len(all_files) - 20} 个[/]")
        return
    
    txt_files = [f for f in all_files if f.endswith('.txt')]
    
    if not txt_files:
        console.print("[yellow]没有.txt文件[/]")
        return
    
    console.print(f"[green]找到 {len(txt_files)} 个.txt文件[/]")
    
    if not questionary.confirm(f"确认去除后缀?", default=False).ask():
        return
    
    success, failed = 0, 0
    for f in txt_files:
        try:
            new_name = f[:-4]
            if not os.path.exists(new_name):
                os.rename(f, new_name)
                console.print(f"[green]✓[/] {os.path.basename(f)} → {os.path.basename(new_name)}")
                success += 1
            else:
                console.print(f"[yellow]跳过[/] {os.path.basename(f)} (目标已存在)")
                failed += 1
        except Exception as e:
            console.print(f"[red]✗[/] {os.path.basename(f)}: {e}")
            failed += 1
    
    console.print(f"\n[bold]完成: 成功{success}, 失败{failed}[/]")
    questionary.text("按回车返回...").ask()


# ============ 设置 ============

def run_settings():
    console.print("\n[bold]系统状态:[/]")
    
    has_aria2, mode = check_aria2()
    status = f"[green]可用 ({mode})[/]" if has_aria2 else "[red]未检测到[/]"
    console.print(f"  Aria2: {status}")
    console.print(f"  Python: {platform.python_version()}")
    console.print(f"  系统: {platform.system()} {platform.release()}")
    
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    console.print(f"  Token: {'[green]已配置[/]' if token else '[red]未配置[/]'}")
    console.print(f"  API版本: 2025-09-03")
    
    questionary.text("按回车返回...").ask()


def check_update():
    console.print("[dim]检查更新...[/]")
    
    try:
        resp = requests.get(
            "https://api.github.com/repos/RuibinNingh/Notion-Files-Management/releases/latest",
            timeout=10
        )
        resp.raise_for_status()
        
        data = resp.json()
        latest = data.get("tag_name", "").lstrip("v")
        
        from packaging import version
        if version.parse(latest) > version.parse(VERSION):
            console.print(f"[green]发现新版本: {latest}[/]")
            console.print(f"当前版本: {VERSION}")
            console.print(f"[dim]{data.get('html_url', '')}[/]")
        else:
            console.print(f"[green]已是最新版本 ({VERSION})[/]")
            
    except Exception as e:
        console.print(f"[red]检查失败: {e}[/]")
    
    questionary.text("按回车返回...").ask()


# ============ 主函数 ============

def main():
    try:
        while True:
            print_banner()
            
            action = questionary.select(
                "选择操作:",
                choices=[
                    Choice("📥 下载文件", "download"),
                    Choice("📤 上传文件", "upload"),
                    Choice("🛠️ 文件处理", "process"),
                    Choice("⚙️ 设置检测", "settings"),
                    Choice("🔄 检查更新", "update"),
                    questionary.Separator(),
                    Choice("🚪 退出", "exit"),
                ],
                style=STYLE,
                pointer="❯"
            ).ask()
            
            if action == "download":
                run_download()
            elif action == "upload":
                run_upload()
            elif action == "process":
                run_file_processing()
            elif action == "settings":
                run_settings()
            elif action == "update":
                check_update()
            elif action == "exit" or action is None:
                console.print("\n[bold #646cff]感谢使用! 👋[/]")
                break
                
    except KeyboardInterrupt:
        console.print("\n[bold red]程序中断[/]")


if __name__ == "__main__":
    main()
