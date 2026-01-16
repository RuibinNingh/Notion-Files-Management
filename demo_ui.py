#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI演示脚本 - 展示新的ModernUploadUI效果
运行: python demo_ui.py

模拟100个文件上传，展示:
- 虚拟滚动 (只显示8个任务)
- 自动折叠完成的任务
- 优先显示进行中的任务
- 日志区域独立显示
"""

import time
import random
import threading
from rich_ui import ModernUploadUI, TaskStatus

def demo():
    """模拟上传100个文件"""
    
    # 模拟100个文件
    NUM_FILES = 100
    files = [
        (f"{i+1:03d}.{random.choice(['mp4', 'pdf', 'docx', 'zip', 'jpg', 'png'])}", 
         random.randint(1024*1024, 500*1024*1024))  # 1MB - 500MB
        for i in range(NUM_FILES)
    ]
    
    total_size = sum(size for _, size in files)
    num_threads = 3
    
    # 初始化UI
    ui = ModernUploadUI(
        total_files=NUM_FILES,
        total_size=total_size,
        num_threads=num_threads
    )
    
    # 添加所有任务
    for i, (filename, filesize) in enumerate(files):
        ui.add_task(
            task_id=i,
            filename=filename,
            filesize=filesize,
            target_page_id="demo-page"
        )
    
    ui.start()
    
    # 模拟上传
    active_tasks = {}  # thread_id -> task_id
    pending_ids = list(range(NUM_FILES))
    completed_ids = []
    
    try:
        while pending_ids or active_tasks:
            # 分配新任务给空闲线程
            for thread_id in range(num_threads):
                if thread_id not in active_tasks and pending_ids:
                    task_id = pending_ids.pop(0)
                    active_tasks[thread_id] = task_id
                    
                    ui.update_task(task_id, 
                                   status=TaskStatus.UPLOADING,
                                   thread_id=thread_id,
                                   start_time=time.time())
            
            # 模拟进度
            for thread_id, task_id in list(active_tasks.items()):
                task = ui.tasks[task_id]
                
                # 增加进度
                progress_increment = random.uniform(0.05, 0.15)
                new_progress = min(task.progress + progress_increment, 1.0)
                
                bytes_added = int((new_progress - task.progress) * task.filesize)
                ui.add_uploaded_bytes(bytes_added)
                
                # 模拟分片
                if task.filesize > 50 * 1024 * 1024:
                    part_total = (task.filesize // (10 * 1024 * 1024)) + 1
                    part_current = int(new_progress * part_total) + 1
                    ui.update_task(task_id, 
                                   progress=new_progress,
                                   part_current=min(part_current, part_total),
                                   part_total=part_total)
                else:
                    ui.update_task(task_id, progress=new_progress)
                
                # 检查完成
                if new_progress >= 1.0:
                    # 随机失败 (5%概率)
                    if random.random() < 0.05:
                        ui.update_task(task_id, 
                                       status=TaskStatus.FAILED,
                                       error_message="网络超时")
                        ui.mark_completed(task_id, False)
                    else:
                        # 模拟合并和附加阶段
                        ui.update_task(task_id, status=TaskStatus.COMPLETING)
                        ui.refresh()
                        time.sleep(0.1)
                        
                        ui.update_task(task_id, status=TaskStatus.ATTACHING)
                        ui.refresh()
                        time.sleep(0.1)
                        
                        ui.update_task(task_id, status=TaskStatus.COMPLETED)
                        ui.mark_completed(task_id, True)
                    
                    completed_ids.append(task_id)
                    del active_tasks[thread_id]
            
            ui.refresh()
            time.sleep(0.1)  # 模拟网络延迟
            
    except KeyboardInterrupt:
        print("\n中断")
    
    ui.stop()


def demo_comparison():
    """
    对比演示: 显示旧UI的问题
    """
    from rich.console import Console
    from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn
    from rich.panel import Panel
    from rich.live import Live
    
    console = Console()
    
    console.print(Panel(
        "[bold red]⚠️ 旧UI的问题演示[/bold red]\n\n"
        "当任务数量超过终端高度时，Rich Progress会尝试渲染所有任务，\n"
        "导致:\n"
        "  • 终端被撑爆\n"
        "  • 滚动混乱\n"
        "  • 无法看到正在进行的任务\n"
        "  • 性能下降",
        border_style="red"
    ))
    
    console.print("\n[dim]3秒后展示新UI效果...[/dim]")
    time.sleep(3)
    
    console.print(Panel(
        "[bold green]✅ 新UI的改进[/bold green]\n\n"
        "ModernUploadUI 特点:\n"
        "  • 虚拟滚动 - 只渲染8条任务\n"
        "  • 优先显示 - 进行中的任务始终可见\n"
        "  • 自动折叠 - 完成的任务收起到统计区\n"
        "  • 日志独立 - 不干扰主进度显示\n"
        "  • 性能稳定 - 不受任务数量影响",
        border_style="green"
    ))
    
    console.print("\n[cyan]开始演示 100 个文件上传...[/cyan]\n")
    time.sleep(2)
    
    demo()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        demo_comparison()
    else:
        demo()
