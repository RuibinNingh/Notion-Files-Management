# Notion-Files-Management - 现代化Rich UI模块
# 解决任务过多导致显示问题，添加虚拟滚动和自动折叠
# Copyright (C) 2025-2026 Ruibin_Ningh & Zyx_2012
# License: GPL v3

import time
from collections import deque
from threading import Lock
from typing import Dict, List, Optional, Any
from enum import Enum, auto

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress, BarColumn, TextColumn, 
    TaskProgressColumn, DownloadColumn,
    TransferSpeedColumn, TimeRemainingColumn
)
from rich.text import Text
from rich.columns import Columns
from rich import box


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = auto()
    UPLOADING = auto()
    COMPLETING = auto()
    ATTACHING = auto()
    COMPLETED = auto()
    FAILED = auto()
    RETRYING = auto()


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_time(seconds: float) -> str:
    """格式化时间"""
    if seconds < 0:
        return "--:--"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class TaskInfo:
    """任务信息"""
    def __init__(self, task_id: int, filename: str, filesize: int, target_page_id: str):
        self.id = task_id
        self.filename = filename
        self.filesize = filesize
        self.target_page_id = target_page_id
        self.status = TaskStatus.PENDING
        self.progress = 0.0
        self.uploaded_bytes = 0
        self.part_current = 0
        self.part_total = 0
        self.retry_count = 0
        self.error_message = ""
        self.thread_id: Optional[int] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None


class ModernUploadUI:
    """
    现代化上传UI
    
    特点:
    - 虚拟滚动：只显示固定数量的任务(默认8条)
    - 自动折叠：已完成任务折叠到统计区
    - 优先显示：进行中的任务优先显示
    - 日志区域：最近日志独立显示
    - 分模块布局：统计、进度、任务、日志分区
    """
    
    # 显示配置
    MAX_VISIBLE_TASKS = 8  # 最大可见任务数
    MAX_LOG_ENTRIES = 3    # 最大日志条目数
    
    # 状态图标
    STATUS_ICONS = {
        TaskStatus.PENDING: ("⏳", "dim"),
        TaskStatus.UPLOADING: ("📤", "cyan"),
        TaskStatus.COMPLETING: ("🔄", "yellow"),
        TaskStatus.ATTACHING: ("🔗", "blue"),
        TaskStatus.COMPLETED: ("✅", "green"),
        TaskStatus.FAILED: ("❌", "red"),
        TaskStatus.RETRYING: ("🔁", "yellow"),
    }
    
    def __init__(self, total_files: int, total_size: int, num_threads: int):
        self.console = Console()
        self.total_files = total_files
        self.total_size = total_size
        self.num_threads = num_threads
        
        # 任务存储
        self.tasks: Dict[int, TaskInfo] = {}
        self.lock = Lock()
        
        # 统计数据
        self.start_time = time.time()
        self.completed_count = 0
        self.failed_count = 0
        self.total_uploaded = 0
        
        # 日志队列(最近N条)
        self.log_entries: deque = deque(maxlen=self.MAX_LOG_ENTRIES)
        
        # 最近完成的任务(用于显示)
        self.recent_completed: deque = deque(maxlen=5)
        
        # 总进度条
        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40, complete_style="green", finished_style="green"),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        )
        self.overall_task_id = self.overall_progress.add_task("总进度", total=total_size)
        
        self.live: Optional[Live] = None
    
    def add_task(self, task_id: int, filename: str, filesize: int, target_page_id: str):
        """添加任务"""
        with self.lock:
            task = TaskInfo(task_id, filename, filesize, target_page_id)
            self.tasks[task_id] = task
    
    def update_task(self, task_id: int, **kwargs):
        """更新任务状态"""
        with self.lock:
            if task_id not in self.tasks:
                return
            
            task = self.tasks[task_id]
            old_status = task.status
            
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            
            # 状态变更时记录日志
            new_status = task.status
            if old_status != new_status:
                self._log_status_change(task, old_status, new_status)
    
    def add_uploaded_bytes(self, bytes_count: int):
        """增加已上传字节数"""
        with self.lock:
            self.total_uploaded += bytes_count
            self.overall_progress.update(self.overall_task_id, completed=self.total_uploaded)
    
    def mark_completed(self, task_id: int, success: bool):
        """标记任务完成"""
        with self.lock:
            if success:
                self.completed_count += 1
            else:
                self.failed_count += 1
            
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.end_time = time.time()
                self.recent_completed.append(task)
    
    def add_log(self, message: str, level: str = "info"):
        """添加日志"""
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.log_entries.append((timestamp, level, message))
    
    def _log_status_change(self, task: TaskInfo, old_status: TaskStatus, new_status: TaskStatus):
        """记录状态变更"""
        name = self._truncate_name(task.filename, 20)
        
        if new_status == TaskStatus.COMPLETED:
            elapsed = (task.end_time or time.time()) - (task.start_time or time.time())
            self.add_log(f"✅ {name} 完成 ({format_time(elapsed)})", "success")
        elif new_status == TaskStatus.FAILED:
            self.add_log(f"❌ {name} 失败: {task.error_message[:30]}", "error")
        elif new_status == TaskStatus.UPLOADING and old_status == TaskStatus.PENDING:
            self.add_log(f"📤 开始上传 {name}", "info")
    
    def _truncate_name(self, name: str, max_len: int = 30) -> str:
        """截断文件名"""
        if len(name) <= max_len:
            return name
        return name[:max_len - 3] + "..."
    
    def _get_visible_tasks(self) -> List[TaskInfo]:
        """
        获取应该显示的任务列表
        优先级: 上传中 > 重试中 > 等待中 > 已完成/失败
        """
        with self.lock:
            all_tasks = list(self.tasks.values())
        
        # 分类任务
        uploading = []
        pending = []
        finished = []
        
        for task in all_tasks:
            if task.status in (TaskStatus.UPLOADING, TaskStatus.COMPLETING, 
                               TaskStatus.ATTACHING, TaskStatus.RETRYING):
                uploading.append(task)
            elif task.status == TaskStatus.PENDING:
                pending.append(task)
            else:
                finished.append(task)
        
        # 按优先级合并
        visible = uploading + pending
        
        # 如果活跃任务不足，补充最近完成的
        if len(visible) < self.MAX_VISIBLE_TASKS:
            remaining = self.MAX_VISIBLE_TASKS - len(visible)
            visible.extend(finished[-remaining:])
        
        return visible[:self.MAX_VISIBLE_TASKS]
    
    def _create_stats_panel(self) -> Panel:
        """创建统计面板"""
        elapsed = time.time() - self.start_time
        speed = self.total_uploaded / elapsed if elapsed > 0 else 0
        
        # 进度计算
        progress_pct = (self.completed_count + self.failed_count) / self.total_files * 100 if self.total_files > 0 else 0
        
        # 左侧统计
        left_stats = Table(show_header=False, box=None, padding=(0, 1))
        left_stats.add_column("k", style="cyan", width=8)
        left_stats.add_column("v", width=12)
        
        left_stats.add_row("📁 文件", f"{self.completed_count + self.failed_count}/{self.total_files}")
        left_stats.add_row("✅ 成功", f"[green]{self.completed_count}[/green]")
        left_stats.add_row("❌ 失败", f"[red]{self.failed_count}[/red]" if self.failed_count else "[dim]0[/dim]")
        
        # 右侧统计
        right_stats = Table(show_header=False, box=None, padding=(0, 1))
        right_stats.add_column("k", style="cyan", width=8)
        right_stats.add_column("v", width=15)
        
        right_stats.add_row("🧵 线程", f"{self.num_threads}")
        right_stats.add_row("⚡ 速度", f"{format_size(int(speed))}/s")
        right_stats.add_row("⏱️  耗时", format_time(elapsed))
        
        # 合并两列
        stats_columns = Columns([left_stats, right_stats], equal=True, expand=True)
        
        return Panel(
            stats_columns,
            title="[bold white]📊 统计[/bold white]",
            border_style="cyan",
            padding=(0, 1),
        )
    
    def _create_task_table(self) -> Panel:
        """创建任务列表表格"""
        table = Table(
            show_header=True, 
            header_style="bold cyan",
            box=box.SIMPLE,
            padding=(0, 1),
            expand=True,
        )
        
        table.add_column("", width=2, justify="center")  # 状态图标
        table.add_column("T", width=2, justify="center")  # 线程
        table.add_column("文件名", width=32, overflow="ellipsis")
        table.add_column("进度", width=22)
        table.add_column("状态", width=12, justify="right")
        
        visible_tasks = self._get_visible_tasks()
        
        for task in visible_tasks:
            icon, color = self.STATUS_ICONS.get(task.status, ("•", "white"))
            thread_str = f"[cyan]{task.thread_id}[/cyan]" if task.thread_id is not None else "[dim]-[/dim]"
            
            # 进度条
            progress_bar = self._create_mini_progress_bar(task.progress, 15)
            progress_text = f"{progress_bar} {task.progress * 100:5.1f}%"
            
            # 状态文字
            status_text = self._get_status_text(task)
            
            table.add_row(
                f"[{color}]{icon}[/{color}]",
                thread_str,
                self._truncate_name(task.filename, 30),
                progress_text,
                status_text,
            )
        
        # 如果有更多任务，显示提示
        total_pending = sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING)
        if total_pending > 0:
            table.add_row(
                "", "", 
                f"[dim]... 还有 {total_pending} 个任务等待中[/dim]",
                "", ""
            )
        
        return Panel(
            table,
            title=f"[bold white]📋 任务列表[/bold white] [dim]({len(visible_tasks)}/{len(self.tasks)})[/dim]",
            border_style="blue",
            padding=(0, 0),
        )
    
    def _create_mini_progress_bar(self, progress: float, width: int = 15) -> str:
        """创建迷你进度条"""
        filled = int(progress * width)
        empty = width - filled
        
        if progress >= 1.0:
            return f"[green]{'━' * width}[/green]"
        elif progress > 0:
            return f"[cyan]{'━' * filled}[/cyan][dim]{'─' * empty}[/dim]"
        else:
            return f"[dim]{'─' * width}[/dim]"
    
    def _get_status_text(self, task: TaskInfo) -> str:
        """获取状态文字"""
        if task.status == TaskStatus.PENDING:
            return "[dim]等待中[/dim]"
        elif task.status == TaskStatus.UPLOADING:
            if task.part_total > 1:
                return f"[cyan]分片 {task.part_current}/{task.part_total}[/cyan]"
            return "[cyan]上传中[/cyan]"
        elif task.status == TaskStatus.COMPLETING:
            return "[yellow]合并中[/yellow]"
        elif task.status == TaskStatus.ATTACHING:
            return "[blue]附加中[/blue]"
        elif task.status == TaskStatus.COMPLETED:
            return "[green]完成[/green]"
        elif task.status == TaskStatus.FAILED:
            return "[red]失败[/red]"
        elif task.status == TaskStatus.RETRYING:
            return f"[yellow]重试({task.retry_count})[/yellow]"
        return ""
    
    def _create_log_panel(self) -> Optional[Panel]:
        """创建日志面板"""
        with self.lock:
            if not self.log_entries:
                return None
            
            log_lines = []
            for timestamp, level, message in self.log_entries:
                color = {"info": "dim", "success": "green", "error": "red"}.get(level, "white")
                log_lines.append(f"[dim]{timestamp}[/dim] [{color}]{message}[/{color}]")
        
        return Panel(
            "\n".join(log_lines),
            title="[bold white]📝 最近日志[/bold white]",
            border_style="dim",
            padding=(0, 1),
            height=5,
        )
    
    def create_layout(self) -> Panel:
        """创建完整布局"""
        components: List[RenderableType] = []
        
        # 1. 统计面板
        components.append(self._create_stats_panel())
        components.append("")
        
        # 2. 总进度条
        components.append(self.overall_progress)
        components.append("")
        
        # 3. 任务列表
        components.append(self._create_task_table())
        
        # 4. 日志面板(如果有)
        log_panel = self._create_log_panel()
        if log_panel:
            components.append("")
            components.append(log_panel)
        
        return Panel(
            Group(*components),
            title="[bold white]🚀 Notion 文件上传[/bold white]",
            subtitle="[dim]按 Ctrl+C 中断[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    
    def start(self):
        """启动UI"""
        self.live = Live(
            self.create_layout(),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        )
        self.live.start()
    
    def refresh(self):
        """刷新UI"""
        if self.live:
            self.live.update(self.create_layout())
    
    def stop(self):
        """停止UI"""
        if self.live:
            self.live.stop()
        self._print_summary()
    
    def _print_summary(self):
        """打印最终摘要"""
        elapsed = time.time() - self.start_time
        avg_speed = self.total_uploaded / elapsed if elapsed > 0 else 0
        
        self.console.print()
        
        # 成功摘要
        summary = f"""[bold green]✨ 上传完成[/bold green]

  [green]✅ 成功:[/green] {self.completed_count}
  [red]❌ 失败:[/red] {self.failed_count}
  [blue]📊 总大小:[/blue] {format_size(self.total_size)}
  [yellow]⚡ 平均速度:[/yellow] {format_size(int(avg_speed))}/s
  [cyan]⏱️  总耗时:[/cyan] {format_time(elapsed)}"""
        
        self.console.print(Panel(
            summary,
            title="📈 上传结果",
            border_style="green" if self.failed_count == 0 else "yellow",
        ))
        
        # 失败文件列表
        with self.lock:
            failed_tasks = [t for t in self.tasks.values() if t.status == TaskStatus.FAILED]
        
        if failed_tasks:
            self.console.print()
            self.console.print("[bold red]❌ 失败的文件:[/bold red]")
            for task in failed_tasks[:10]:
                self.console.print(f"   • {task.filename}: {task.error_message}")
            if len(failed_tasks) > 10:
                self.console.print(f"   [dim]... 还有 {len(failed_tasks) - 10} 个失败[/dim]")


# ============ 下载UI ============

class ModernDownloadUI:
    """
    现代化下载UI
    
    特点:
    - 虚拟滚动：只显示固定数量的任务
    - 自动折叠：已完成任务折叠到统计区
    - 优先显示：进行中的任务优先显示
    """
    
    MAX_VISIBLE_TASKS = 10
    
    def __init__(self, total_files: int, total_size: int):
        self.console = Console()
        self.total_files = total_files
        self.total_size = total_size
        
        self.tasks: Dict[int, Dict[str, Any]] = {}
        self.lock = Lock()
        
        self.start_time = time.time()
        self.completed_count = 0
        self.failed_count = 0
        self.total_downloaded = 0
        
        # 总进度条
        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40, complete_style="green"),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        )
        self.overall_task_id = self.overall_progress.add_task("总进度", total=total_size)
        
        self.live: Optional[Live] = None
    
    def add_task(self, task_id: int, filename: str, filesize: int):
        """添加下载任务"""
        with self.lock:
            self.tasks[task_id] = {
                "id": task_id,
                "filename": filename,
                "filesize": filesize,
                "status": "pending",  # pending, downloading, completed, failed
                "progress": 0.0,
                "downloaded": 0,
                "speed": 0,
                "error": "",
            }
    
    def update_task(self, task_id: int, **kwargs):
        """更新任务"""
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(kwargs)
    
    def add_downloaded_bytes(self, bytes_count: int):
        """增加已下载字节"""
        with self.lock:
            self.total_downloaded += bytes_count
            self.overall_progress.update(self.overall_task_id, completed=self.total_downloaded)
    
    def mark_completed(self, task_id: int, success: bool):
        """标记完成"""
        with self.lock:
            if success:
                self.completed_count += 1
            else:
                self.failed_count += 1
    
    def _get_visible_tasks(self) -> List[Dict]:
        """获取可见任务"""
        with self.lock:
            all_tasks = list(self.tasks.values())
        
        downloading = [t for t in all_tasks if t["status"] == "downloading"]
        pending = [t for t in all_tasks if t["status"] == "pending"]
        finished = [t for t in all_tasks if t["status"] in ("completed", "failed")]
        
        visible = downloading + pending
        if len(visible) < self.MAX_VISIBLE_TASKS:
            remaining = self.MAX_VISIBLE_TASKS - len(visible)
            visible.extend(finished[-remaining:])
        
        return visible[:self.MAX_VISIBLE_TASKS]
    
    def _truncate_name(self, name: str, max_len: int = 35) -> str:
        if len(name) <= max_len:
            return name
        return name[:max_len - 3] + "..."
    
    def _create_progress_bar(self, progress: float, width: int = 20) -> str:
        filled = int(progress * width)
        empty = width - filled
        if progress >= 1.0:
            return f"[green]{'━' * width}[/green]"
        elif progress > 0:
            return f"[cyan]{'━' * filled}[/cyan][dim]{'─' * empty}[/dim]"
        return f"[dim]{'─' * width}[/dim]"
    
    def create_layout(self) -> Panel:
        """创建布局"""
        # 统计
        elapsed = time.time() - self.start_time
        speed = self.total_downloaded / elapsed if elapsed > 0 else 0
        
        stats = Table(show_header=False, box=None, padding=(0, 2))
        stats.add_column("k1", style="cyan")
        stats.add_column("v1")
        stats.add_column("k2", style="cyan")
        stats.add_column("v2")
        
        stats.add_row(
            "📁 文件", f"{self.completed_count + self.failed_count}/{self.total_files}",
            "⚡ 速度", f"{format_size(int(speed))}/s"
        )
        stats.add_row(
            "✅ 成功", f"[green]{self.completed_count}[/green]",
            "⏱️  耗时", format_time(elapsed)
        )
        
        # 任务表格
        task_table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.SIMPLE,
            expand=True,
        )
        task_table.add_column("", width=2)
        task_table.add_column("文件名", width=38)
        task_table.add_column("进度", width=28)
        task_table.add_column("状态", width=10, justify="right")
        
        visible = self._get_visible_tasks()
        for t in visible:
            icon = {"pending": "⏳", "downloading": "📥", "completed": "✅", "failed": "❌"}.get(t["status"], "•")
            color = {"pending": "dim", "downloading": "cyan", "completed": "green", "failed": "red"}.get(t["status"], "white")
            
            bar = self._create_progress_bar(t["progress"])
            progress_text = f"{bar} {t['progress'] * 100:5.1f}%"
            
            status_text = {"pending": "[dim]等待[/dim]", "downloading": "[cyan]下载中[/cyan]", 
                          "completed": "[green]完成[/green]", "failed": "[red]失败[/red]"}.get(t["status"], "")
            
            task_table.add_row(
                f"[{color}]{icon}[/{color}]",
                self._truncate_name(t["filename"]),
                progress_text,
                status_text,
            )
        
        total_pending = sum(1 for t in self.tasks.values() if t["status"] == "pending")
        if total_pending > 0:
            task_table.add_row("", f"[dim]... 还有 {total_pending} 个任务等待中[/dim]", "", "")
        
        content = Group(
            Panel(stats, title="📊 统计", border_style="cyan", padding=(0, 1)),
            "",
            self.overall_progress,
            "",
            Panel(task_table, title=f"📋 任务列表 ({len(visible)}/{len(self.tasks)})", border_style="blue", padding=(0, 0)),
        )
        
        return Panel(
            content,
            title="[bold white]📥 文件下载[/bold white]",
            subtitle="[dim]按 Ctrl+C 中断[/dim]",
            border_style="green",
            padding=(1, 2),
        )
    
    def start(self):
        self.live = Live(self.create_layout(), console=self.console, refresh_per_second=4, transient=True)
        self.live.start()
    
    def refresh(self):
        if self.live:
            self.live.update(self.create_layout())
    
    def stop(self):
        if self.live:
            self.live.stop()
        self._print_summary()
    
    def _print_summary(self):
        elapsed = time.time() - self.start_time
        avg_speed = self.total_downloaded / elapsed if elapsed > 0 else 0
        
        self.console.print()
        self.console.print(Panel(
            f"""[bold green]✨ 下载完成[/bold green]

  [green]✅ 成功:[/green] {self.completed_count}
  [red]❌ 失败:[/red] {self.failed_count}
  [blue]📊 总大小:[/blue] {format_size(self.total_size)}
  [yellow]⚡ 平均速度:[/yellow] {format_size(int(avg_speed))}/s
  [cyan]⏱️  总耗时:[/cyan] {format_time(elapsed)}""",
            title="📈 下载结果",
            border_style="green" if self.failed_count == 0 else "yellow",
        ))
