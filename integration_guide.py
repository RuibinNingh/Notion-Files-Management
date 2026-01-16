# ============================================
# main.py 修改指南
# 将新的 ModernUploadUI 集成到现有代码
# ============================================

"""
修改步骤:

1. 在 main.py 顶部添加导入:
   from rich_ui import ModernUploadUI, TaskStatus

2. 将原有的 RichUploadUI 类替换为适配器类 (见下方代码)

3. 修改 UploadTask 类，添加与新UI的兼容性
"""

# ============ 替换原有 RichUploadUI 的适配器代码 ============

from rich_ui import ModernUploadUI, TaskStatus as UITaskStatus

# 状态映射: notion.py 的 UploadStatus -> rich_ui 的 TaskStatus
def map_status(upload_status) -> UITaskStatus:
    """将 UploadStatus 映射到 TaskStatus"""
    mapping = {
        "PENDING": UITaskStatus.PENDING,
        "UPLOADING": UITaskStatus.UPLOADING,
        "COMPLETING": UITaskStatus.COMPLETING,
        "ATTACHING": UITaskStatus.ATTACHING,
        "COMPLETED": UITaskStatus.COMPLETED,
        "FAILED": UITaskStatus.FAILED,
        "RETRYING": UITaskStatus.RETRYING,
    }
    return mapping.get(upload_status.name, UITaskStatus.PENDING)


class RichUploadUI:
    """
    适配器类 - 保持原有API不变，内部使用新的 ModernUploadUI
    
    这样你不需要修改 NotionUploader 类的任何代码!
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
        
    @property
    def completed_count(self):
        return self._ui.completed_count
    
    @property
    def failed_count(self):
        return self._ui.failed_count
    
    def add_task(self, task):
        """添加任务 (保持原有签名)"""
        self._ui.add_task(
            task_id=task.id,
            filename=task.file_info.original_name,
            filesize=task.file_info.size,
            target_page_id=task.target_page_id,
        )
    
    def update_task(self, task_id: int, **kwargs):
        """更新任务 (保持原有签名)"""
        # 转换状态枚举
        if 'status' in kwargs:
            kwargs['status'] = map_status(kwargs['status'])
        
        self._ui.update_task(task_id, **kwargs)
    
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


# ============ 完整的集成示例 ============

"""
在 main.py 中，你只需要:

1. 删除原有的 RichUploadUI 类 (约150-360行)

2. 在文件顶部添加:
   from rich_ui import ModernUploadUI, TaskStatus as UITaskStatus

3. 粘贴上面的 map_status 函数和新的 RichUploadUI 适配器类

就这样! 不需要修改 NotionUploader 或其他任何代码。
"""


# ============ 或者，完全重写的简化版 ============

class NotionUploaderV2:
    """
    简化版上传器 - 直接使用新UI
    如果你想完全重构，可以参考这个版本
    """
    
    def __init__(self, manager, num_threads: int = 3):
        self.manager = manager
        self.num_threads = num_threads
        self.console = Console()
    
    def upload_files(self, filepaths: list, target_page_id: str):
        """上传多个文件"""
        from notion import UploadFileInfo, MAX_FILE_SIZE, UploadStatus
        import queue
        import threading
        
        # 过滤有效文件
        valid_files = []
        for fp in filepaths:
            if os.path.exists(fp) and os.path.getsize(fp) <= MAX_FILE_SIZE:
                valid_files.append(UploadFileInfo.from_path(fp))
        
        if not valid_files:
            self.console.print("[yellow]没有有效的文件可上传[/yellow]")
            return
        
        total_size = sum(f.size for f in valid_files)
        
        # 初始化新UI
        ui = ModernUploadUI(len(valid_files), total_size, self.num_threads)
        
        # 添加任务
        task_queue = queue.Queue()
        for i, file_info in enumerate(valid_files):
            ui.add_task(i, file_info.original_name, file_info.size, target_page_id)
            task_queue.put((i, file_info))
        
        ui.start()
        stop_event = threading.Event()
        
        def worker(thread_id):
            while not stop_event.is_set():
                try:
                    task_id, file_info = task_queue.get(timeout=0.5)
                    
                    ui.update_task(task_id, 
                                   status=UITaskStatus.UPLOADING, 
                                   thread_id=thread_id)
                    
                    def progress_callback(progress):
                        ui.update_task(
                            task_id,
                            status=map_status(progress.status),
                            progress=progress.uploaded / progress.total if progress.total else 0,
                            part_current=progress.part_current,
                            part_total=progress.part_total,
                            retry_count=progress.retry_count,
                        )
                        
                        # 更新总进度
                        if progress.status == UploadStatus.UPLOADING:
                            ui.add_uploaded_bytes(progress.uploaded - getattr(progress_callback, '_last', 0))
                            progress_callback._last = progress.uploaded
                    
                    progress_callback._last = 0
                    
                    try:
                        success = self.manager.upload_file(
                            file_info.path,
                            target_page_id=target_page_id,
                            progress_callback=progress_callback
                        )
                        
                        status = UITaskStatus.COMPLETED if success else UITaskStatus.FAILED
                        ui.update_task(task_id, status=status, progress=1.0 if success else 0)
                        ui.mark_completed(task_id, success)
                        
                    except Exception as e:
                        ui.update_task(task_id, status=UITaskStatus.FAILED, error_message=str(e))
                        ui.mark_completed(task_id, False)
                    
                    task_queue.task_done()
                    
                except queue.Empty:
                    continue
        
        # 启动工作线程
        threads = []
        for i in range(self.num_threads):
            t = threading.Thread(target=worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)
        
        # 主循环
        try:
            while not task_queue.empty() or any(t.is_alive() for t in threads):
                ui.refresh()
                time.sleep(0.25)
                
                if ui.completed_count + ui.failed_count >= len(valid_files):
                    break
        except KeyboardInterrupt:
            self.console.print("\n[yellow]正在停止...[/yellow]")
            stop_event.set()
        
        stop_event.set()
        ui.stop()
