# Notion-Files-Management - 双终端UI模块
# 进度终端 + 日志终端分离设计
# Copyright (C) 2025-2026 Ruibin_Ningh & Zyx_2012
# License: GPL v3

import os
import sys
import time
import threading
import subprocess
import tempfile
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Callable
from threading import Lock


# ============ 状态枚举 ============

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETING = "completing"
    ATTACHING = "attaching"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CHECKING = "checking"
    RECOVERING = "recovering"


# ============ 状态显示配置 ============

STATUS_DISPLAY = {
    TaskStatus.PENDING:    ("⏳", "等待中"),
    TaskStatus.UPLOADING:  ("📤", "上传中"),
    TaskStatus.COMPLETING: ("🔄", "完成中"),
    TaskStatus.ATTACHING:  ("📎", "附加中"),
    TaskStatus.COMPLETED:  ("✅", "已完成"),
    TaskStatus.FAILED:     ("❌", "失败"),
    TaskStatus.RETRYING:   ("🔁", "重试中"),
    TaskStatus.CHECKING:   ("🔍", "检查中"),
    TaskStatus.RECOVERING: ("🔧", "恢复中"),
}


# ============ 数据类 ============

@dataclass
class TaskInfo:
    """任务信息"""
    task_id: int
    filename: str
    filesize: int
    target_page_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    part_current: int = 0
    part_total: int = 0
    retry_count: int = 0
    thread_id: Optional[int] = None
    error_message: str = ""
    start_time: Optional[float] = None


# ============ 工具函数 ============

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


def make_bar(progress: float, width: int = 30, filled: str = "█", empty: str = "░") -> str:
    """生成进度条"""
    filled_len = int(width * progress)
    return filled * filled_len + empty * (width - filled_len)


def str_width(s: str) -> int:
    """计算字符串显示宽度（考虑中文字符占2格）"""
    width = 0
    for char in s:
        if '\u4e00' <= char <= '\u9fff' or \
           '\u3000' <= char <= '\u303f' or \
           '\uff00' <= char <= '\uffef':
            width += 2
        else:
            width += 1
    return width


def pad_to_width(s: str, target_width: int) -> str:
    """将字符串填充到指定显示宽度"""
    current_width = str_width(s)
    if current_width >= target_width:
        return s
    return s + " " * (target_width - current_width)


def truncate_to_width(s: str, max_width: int, suffix: str = "...") -> str:
    """截断字符串到指定显示宽度"""
    if str_width(s) <= max_width:
        return s
    
    suffix_width = str_width(suffix)
    target = max_width - suffix_width
    
    result = ""
    current_width = 0
    for char in s:
        char_width = 2 if ('\u4e00' <= char <= '\u9fff' or 
                          '\u3000' <= char <= '\u303f' or 
                          '\uff00' <= char <= '\uffef') else 1
        if current_width + char_width > target:
            break
        result += char
        current_width += char_width
    
    return result + suffix


def clear_screen():
    """清屏"""
    print("\033[2J\033[H", end="", flush=True)


def move_cursor(row: int, col: int = 1):
    """移动光标到指定位置"""
    print(f"\033[{row};{col}H", end="", flush=True)


def hide_cursor():
    """隐藏光标"""
    print("\033[?25l", end="", flush=True)


def show_cursor():
    """显示光标"""
    print("\033[?25h", end="", flush=True)


# ============ 日志管道 ============

class LogPipe:
    """
    日志管道 - 将日志发送到单独的终端
    """
    
    def __init__(self):
        self.log_file = None
        self.log_process = None
        self.enabled = False
        
    def start(self) -> bool:
        """启动日志终端"""
        try:
            # 创建临时文件作为日志管道
            self.log_file = tempfile.NamedTemporaryFile(
                mode='w', 
                suffix='.log', 
                delete=False,
                prefix='notion_upload_'
            )
            
            # 根据系统选择终端
            if sys.platform == 'win32':
                # Windows: 使用 start 命令打开新终端
                cmd = f'start "Upload Logs" cmd /k "type {self.log_file.name} && powershell -c Get-Content {self.log_file.name} -Wait"'
                subprocess.Popen(cmd, shell=True)
            elif sys.platform == 'darwin':
                # macOS: 使用 osascript 打开终端
                script = f'''
                tell application "Terminal"
                    do script "tail -f {self.log_file.name}"
                    activate
                end tell
                '''
                subprocess.Popen(['osascript', '-e', script])
            else:
                # Linux: 尝试多种终端
                terminals = [
                    ['gnome-terminal', '--', 'tail', '-f', self.log_file.name],
                    ['konsole', '-e', 'tail', '-f', self.log_file.name],
                    ['xfce4-terminal', '-e', f'tail -f {self.log_file.name}'],
                    ['xterm', '-e', 'tail', '-f', self.log_file.name],
                ]
                
                for terminal_cmd in terminals:
                    try:
                        self.log_process = subprocess.Popen(
                            terminal_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        break
                    except FileNotFoundError:
                        continue
                else:
                    # 没有找到可用终端，回退到打印
                    return False
            
            self.enabled = True
            self.write("=" * 60)
            self.write("  📋 Notion Upload Logs")
            self.write("=" * 60)
            self.write("")
            return True
            
        except Exception as e:
            print(f"[警告] 无法启动日志终端: {e}")
            return False
    
    def write(self, message: str):
        """写入日志"""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        
        if self.enabled and self.log_file:
            try:
                self.log_file.write(line)
                self.log_file.flush()
            except:
                pass
        else:
            # 回退到标准输出（但在进度模式下不打印）
            pass
    
    def stop(self):
        """停止日志终端"""
        if self.log_file:
            try:
                self.log_file.close()
                # 清理临时文件
                os.unlink(self.log_file.name)
            except:
                pass


# ============ 简单日志收集器 ============

class SimpleLogger:
    """
    简单日志收集器 - 不开新终端，直接缓存日志
    上传完成后统一显示
    """
    
    def __init__(self):
        self.logs: List[str] = []
        self.lock = Lock()
    
    def write(self, message: str):
        """写入日志"""
        timestamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{timestamp}] {message}")
    
    def get_recent(self, count: int = 5) -> List[str]:
        """获取最近的日志"""
        with self.lock:
            return self.logs[-count:] if self.logs else []
    
    def print_all(self):
        """打印所有日志"""
        with self.lock:
            print("\n" + "=" * 60)
            print("  📋 Upload Logs")
            print("=" * 60)
            for log in self.logs:
                print(log)


# ============ 主UI类 ============

class ModernUploadUI:
    """
    现代化上传UI
    - 主终端显示：总进度条 + 子任务平铺进度条
    - 日志：缓存收集，可选输出到文件或新终端
    """
    
    def __init__(self, total_files: int, total_size: int, num_threads: int):
        self.total_files = total_files
        self.total_size = total_size
        self.num_threads = num_threads
        
        self.tasks: Dict[int, TaskInfo] = {}
        self.lock = Lock()
        
        # 兼容性: 提供console属性 (用于RichUploadUI适配器)
        # 创建一个简单的mock对象，有print方法即可
        class SimpleConsole:
            def print(self, *args, **kwargs):
                # 在UI运行时不打印，避免干扰
                pass
        self.console = SimpleConsole()
        
        # 统计
        self.completed_count = 0
        self.failed_count = 0
        self.uploaded_bytes = 0
        
        # 时间追踪
        self.start_time: Optional[float] = None
        
        # 日志
        self.logger = SimpleLogger()
        
        # 显示状态
        self._running = False
        self._last_render = 0
        
        # 终端尺寸
        self._term_width = 80
        self._term_height = 24
        self._update_terminal_size()
    
    def _update_terminal_size(self):
        """更新终端尺寸"""
        try:
            size = os.get_terminal_size()
            self._term_width = size.columns
            self._term_height = size.lines
        except:
            pass
    
    def add_task(self, task_id: int, filename: str, filesize: int, target_page_id: str):
        """添加任务"""
        with self.lock:
            self.tasks[task_id] = TaskInfo(
                task_id=task_id,
                filename=filename,
                filesize=filesize,
                target_page_id=target_page_id,
            )
        self.logger.write(f"添加任务 #{task_id}: {filename} ({format_size(filesize)})")
    
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
            
            # 记录状态变化
            if 'status' in kwargs and kwargs['status'] != old_status:
                icon, name = STATUS_DISPLAY.get(kwargs['status'], ("?", "未知"))
                self.logger.write(f"[#{task_id}] {task.filename[:20]}... → {icon} {name}")
            
            # 记录重试
            if kwargs.get('retry_count', 0) > 0:
                self.logger.write(f"[#{task_id}] 重试 #{kwargs['retry_count']}")
    
    def add_uploaded_bytes(self, bytes_count: int):
        """增加已上传字节数"""
        with self.lock:
            self.uploaded_bytes += bytes_count
    
    def mark_completed(self, task_id: int, success: bool):
        """标记任务完成"""
        with self.lock:
            if success:
                self.completed_count += 1
                if task_id in self.tasks:
                    self.logger.write(f"✅ 完成: {self.tasks[task_id].filename}")
            else:
                self.failed_count += 1
                if task_id in self.tasks:
                    self.logger.write(f"❌ 失败: {self.tasks[task_id].filename}")
    
    def start(self):
        """启动UI"""
        self._running = True
        self.start_time = time.time()
        hide_cursor()
        clear_screen()
        self.logger.write("上传开始")
    
    def refresh(self):
        """刷新UI显示"""
        if not self._running:
            return
        
        # 限制刷新频率
        now = time.time()
        if now - self._last_render < 0.1:
            return
        self._last_render = now
        
        self._update_terminal_size()
        self._render()
    
    def _render(self):
        """渲染UI"""
        with self.lock:
            self._update_terminal_size()
            lines = []
            
            # 计算总进度
            if self.total_files > 0:
                total_progress = (self.completed_count + self.failed_count) / self.total_files
                for t in self.tasks.values():
                    if t.status in (TaskStatus.UPLOADING, TaskStatus.COMPLETING, 
                                   TaskStatus.ATTACHING, TaskStatus.RETRYING):
                        total_progress += t.progress / self.total_files
                total_progress = min(total_progress, 1.0)
            else:
                total_progress = 0
            
            elapsed = time.time() - self.start_time if self.start_time else 0
            speed = self.uploaded_bytes / elapsed if elapsed > 0 else 0
            remaining = self.total_size - self.uploaded_bytes
            eta = remaining / speed if speed > 0 and remaining > 0 else -1
            
            # 标题和进度条
            lines.append("")
            lines.append("  📤 Notion Upload Progress")
            lines.append("  " + "=" * 50)
            bar = make_bar(total_progress, 40)
            lines.append(f"  [{bar}] {total_progress*100:5.1f}%")
            
            # 统计
            stats = f"  📁 {self.completed_count}/{self.total_files}"
            if self.failed_count > 0:
                stats += f" ❌{self.failed_count}"
            stats += f"  📦 {format_size(self.uploaded_bytes)}/{format_size(self.total_size)}"
            stats += f"  ⚡{format_size(int(speed))}/s"
            if eta > 0:
                stats += f"  ⏱{format_time(eta)}"
            lines.append(stats)
            lines.append("")
            lines.append("  -- 任务详情 --")
            
            # 收集任务：正在上传的 + 等待中的
            active = [t for t in self.tasks.values() 
                     if t.status not in (TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED)]
            pending = [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
            
            active.sort(key=lambda t: t.task_id)
            pending.sort(key=lambda t: t.task_id)
            
            # 自适应终端高度：总高度 - 已用行数 - 底部留白
            max_tasks = max(self._term_height - len(lines) - 2, 3)
            to_show = (active + pending)[:max_tasks]
            
            for task in to_show:
                lines.append(self._render_task_line(task))
            
            lines.append("")
            
            # 输出
            move_cursor(1, 1)
            print("\n".join(lines) + "\033[J", end="", flush=True)
    
    def _render_task_line(self, task: TaskInfo) -> str:
        """渲染单个任务行 - 简洁格式"""
        icon, status_text = STATUS_DISPLAY.get(task.status, ("?", "未知"))
        
        # 文件名（截断到20个显示宽度）
        name = truncate_to_width(task.filename, 20)
        name = pad_to_width(name, 20)
        
        # 文件大小
        size_str = format_size(task.filesize)
        
        # 子进度条
        bar_width = 12
        bar = make_bar(task.progress, bar_width)
        
        # 状态详情
        if task.status == TaskStatus.UPLOADING and task.part_total > 0:
            detail = f"{task.part_current}/{task.part_total}"
        elif task.status == TaskStatus.RETRYING:
            detail = f"重试{task.retry_count}"
        elif task.status == TaskStatus.COMPLETING:
            detail = "合并"
        elif task.status == TaskStatus.ATTACHING:
            detail = "附加"
        elif task.status == TaskStatus.CHECKING:
            detail = "检查"
        elif task.status == TaskStatus.RECOVERING:
            detail = "恢复"
        elif task.status == TaskStatus.COMPLETED:
            detail = "完成"
        elif task.status == TaskStatus.FAILED:
            detail = "失败"
        elif task.status == TaskStatus.PENDING:
            detail = "等待"
        else:
            detail = status_text[:4]
        
        # 线程ID
        thread_str = f"T{task.thread_id}" if task.thread_id is not None else "--"
        
        # 组装行: icon [T0] filename size [bar] pct% detail
        line = f"  {icon} [{thread_str:>2}] {name} {size_str:>7} {bar} {task.progress*100:5.1f}% {detail}"
        
        return line
    
    def stop(self):
        """停止UI"""
        self._running = False
        show_cursor()
        
        # 最终渲染
        clear_screen()
        
        elapsed = time.time() - self.start_time if self.start_time else 0
        avg_speed = self.uploaded_bytes / elapsed if elapsed > 0 else 0
        
        print("")
        print("  📤 上传完成")
        print("  " + "=" * 40)
        print(f"  ✅ 成功: {self.completed_count}    ❌ 失败: {self.failed_count}")
        print(f"  📦 总计: {format_size(self.uploaded_bytes)}    ⏱ 耗时: {format_time(elapsed)}")
        print(f"  ⚡ 平均速度: {format_size(int(avg_speed))}/s")
        print("")
        
        # 打印失败任务
        if self.failed_count > 0:
            print("  ❌ 失败任务:")
            with self.lock:
                for task in self.tasks.values():
                    if task.status == TaskStatus.FAILED:
                        print(f"     - {task.filename}")
                        if task.error_message:
                            print(f"       原因: {task.error_message}")
            print("")
        
        print(f"  [提示] 共记录 {len(self.logger.logs)} 条日志")
        print("")


# ============ 测试代码 ============

if __name__ == "__main__":
    import random
    
    print("测试双终端UI...")
    print("进度将在此终端显示，日志会缓存起来")
    print("按 Ctrl+C 可以中断测试")
    print()
    time.sleep(2)
    
    # 测试UI
    ui = ModernUploadUI(total_files=5, total_size=100 * 1024 * 1024, num_threads=2)
    
    # 添加测试任务
    test_files = [
        ("document.pdf", 10 * 1024 * 1024),
        ("video.mp4", 50 * 1024 * 1024),
        ("image.png", 5 * 1024 * 1024),
        ("archive.zip", 25 * 1024 * 1024),
        ("music.mp3", 10 * 1024 * 1024),
    ]
    
    for i, (name, size) in enumerate(test_files):
        ui.add_task(i, name, size, "page-123")
    
    ui.start()
    
    try:
        # 模拟上传
        for i, (name, size) in enumerate(test_files):
            ui.update_task(i, status=TaskStatus.UPLOADING, thread_id=i % 2)
            
            # 模拟分片上传
            parts = max(size // (10 * 1024 * 1024), 1)
            for part in range(1, parts + 1):
                time.sleep(0.2)
                progress = part / parts
                ui.update_task(i, progress=progress, part_current=part, part_total=parts)
                ui.add_uploaded_bytes(size // parts)
                ui.refresh()
            
            # 模拟完成阶段
            ui.update_task(i, status=TaskStatus.COMPLETING, progress=1.0)
            ui.refresh()
            time.sleep(0.1)
            
            ui.update_task(i, status=TaskStatus.ATTACHING)
            ui.refresh()
            time.sleep(0.1)
            
            # 随机成功或失败
            if random.random() > 0.2:
                ui.update_task(i, status=TaskStatus.COMPLETED, progress=1.0)
                ui.mark_completed(i, True)
            else:
                ui.update_task(i, status=TaskStatus.FAILED, error_message="网络错误")
                ui.mark_completed(i, False)
            
            ui.refresh()
    
    except KeyboardInterrupt:
        print("\n中断...")
    
    finally:
        ui.stop()
        print("\n测试完成！")