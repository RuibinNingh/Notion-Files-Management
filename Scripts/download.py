import urllib.request
import threading
import os
import time
from concurrent.futures import ThreadPoolExecutor
class Download:
    def __init__(self,max_workers):
        self.status_map = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock=threading.Lock()

    def download(self, url, save_name,size):#save_name是保存的路径+文件名
        with self.lock:
            if url in self.status_map and self.status_map[url]["status"] in ["waiting", "downloading", "completed"]:
                return {"msg": "Task already exists", "status": self.status_map[url]["status"]}

            self.status_map[url] = {
                "progress": 0,
                "downloaded_mb": 0.0,
                "total_mb": size,
                "status": "waiting",
                "save_name": save_name,
                "speed_mb_s": 0.0,
                "usedTime": 0,
                "ETA": 0,
                "error": None
            }
        self.executor.submit(self._worker, url, save_name, size)
        return {"msg": "Task submitted", "url": url}

    def _worker(self, url, save_name,manual_size_mb):
        start_time = time.time()
        last_update_time = start_time
        last_downloaded_bytes = 0
        current_speed_bps = 0.0 # 字节/秒

        with self.lock:
            if url in self.status_map:
                self.status_map[url]["status"] = "downloading"

        def report(block_num, block_size, total_size):
            nonlocal last_update_time, last_downloaded_bytes, current_speed_bps
            if total_size <= 0:
                total_size = manual_size_mb * 1024 * 1024
            if total_size > 0:
                now = time.time()
                elapsed_since_last = now - last_update_time
                
                # 策略1：每 0.5 秒计算一次，保证采样准确
                if elapsed_since_last >= 0.5:
                    downloaded_bytes = min(block_num * block_size, total_size)
                    newly_downloaded = downloaded_bytes - last_downloaded_bytes
                    
                    # 瞬时速度
                    instant_speed = newly_downloaded / elapsed_since_last
                    
                    # 策略2：滑动平均 (加权移动平均)
                    # 新速度占 70%，旧速度占 30%，减少数据跳变
                    if current_speed_bps == 0:
                        current_speed_bps = instant_speed
                    else:
                        current_speed_bps = (current_speed_bps * 0.3) + (instant_speed * 0.7)
                    
                    # 计算剩余时间 (ETA)
                    remaining_bytes = total_size - downloaded_bytes
                    # 策略3：速度过慢时 ETA 设为 0 或极大值，防止除零
                    eta = int(remaining_bytes / current_speed_bps) if current_speed_bps > 1024 else 0
                    
                    # 记录快照
                    last_update_time = now
                    last_downloaded_bytes = downloaded_bytes

                    with self.lock:
                        if url in self.status_map:
                            item = self.status_map[url]
                            item["downloaded_mb"] = round(downloaded_bytes / (1024 * 1024), 2)
                            item["total_mb"] = round(total_size / (1024 * 1024), 2)
                            item["progress"] = round((downloaded_bytes / total_size) * 100, 2)
                            item["speed_mb_s"] = round(current_speed_bps / (1024 * 1024), 2)
                            item["usedTime"] = int(now - start_time)
                            item["ETA"] = eta

        try:
            d = os.path.dirname(save_name)
            if d: os.makedirs(d, exist_ok=True)
            urllib.request.urlretrieve(url, save_name, reporthook=report)
            
            # 完成后的清理动作
            with self.lock:
                if url in self.status_map:
                    self.status_map[url].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_mb": self.status_map[url]["total_mb"],
                        "speed_mb_s": 0.0,
                        "ETA": 0
                    })
        except Exception as e:
            with self.lock:
                if url in self.status_map:
                    self.status_map[url]["status"] = "error"
                    self.status_map[url]["error"] = str(e)

    def get_status(self, url):
        with self.lock:
            return self.status_map.get(url, {"status": "not_found"})
"""
下载类的状态格式:(内部使用)
[
    {
        "progress": 100,  # 0-100
        "downloaded_mb": 20.5,
        "total_mb": 20.5,
        "status": "completed",
        "save_name": "path/to/file.ext",
        "speed_mb_s": 2.5,
        "usedTime": 0,
        "ETA": 0,
        "error": null
    }
]
"""