import urllib.request
import threading
import os
class Download:
    def __init__(self):
        self.status_map = {}
        self.lock=threading.Lock()#锁，保护status_map的线程安全

    def download(self, url, save_name):#save_name是保存的路径+文件名
        if url in self.status_map and self.status_map[url]["status"] == "downloading":
            return {"msg": "Task already running"}

        self.status_map[url] = {
            "progress": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "status": "downloading",
            "save_name": save_name
        }

        thread = threading.Thread(target=self._worker, args=(url, save_name))
        thread.daemon = False
        thread.start()
        return {"msg": "Download started", "url": url}

    def _worker(self, url, save_name):
        def report(block_num, block_size, total_size):
            if total_size > 0:
                downloaded_bytes=min(block_num*block_size,total_size)
                downloaded_mb = downloaded_bytes / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                percent = min(100.0, (downloaded_bytes / total_size) * 100)
                with self.lock:
                    self.status_map[url]["downloaded_mb"] = round(downloaded_mb, 2)
                    self.status_map[url]["total_mb"] = round(total_mb, 2)
                    self.status_map[url]["progress"] = round(percent, 2)

        try:
            d=os.path.dirname(save_name)
            if d:
                os.makedirs(d,exist_ok=True)
            urllib.request.urlretrieve(url, save_name, reporthook=report)
            with self.lock:
                self.status_map[url]["status"] = "completed"
                self.status_map[url]["progress"] = 100.0
                size = os.path.getsize(save_name)
                size_mb = size / (1024 * 1024)

                self.status_map[url]["downloaded_mb"] = round(size_mb, 2)
                self.status_map[url]["total_mb"] = round(size_mb, 2)
        except Exception as e:
            with self.lock:
                self.status_map[url]["status"] = f"error"
                self.status_map[url]["error"]=str(e)

    def get_status(self, url):
        return self.status_map.get(url, {"status": "not_found"})#没查到返回not_found
"""
格式:
{
    "url": "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/....",
    "save_name": "downloads/example.zip",
    "status": "downloading/completed/error",
    "progress": 75.5,  # 0-100
    "downloaded_mb": 15.2,
    "total_mb": 20.0,
    "error": null
}
"""