from download import Download
from notion import Notion
class Main:
    def __init__(self, notion_token,max_workers=3):
        self.notion = Notion(notion_token)
        self.downloader = Download(max_workers=max_workers)
        self.download_statuses = []
        self.download_list = []
    
    def get_download_list(self, page_id):
        """
        下载链接的格式:
        [
            {
                "name": "example.zip.txt"
                "real_name": "example.zip"
                "url": "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/...."
                "expiry_time": "2024-10-01T12:00:00.000Z",
                "size_mb": 2.5
            }
        ]
        """
        page_data = self.notion.query_page(page_id, True)
        self.download_list = self.notion.get_download_url(page_data)
        return self.download_list

    def download_notion_files(self, download_list, save_directory):
        """
        下载指定 Notion 页面中的所有文件到指定目录,即启动一个任务
        参数:
            page_id: Notion 页面 ID
            save_directory: 文件保存目录
        返回:
            下载状态列表
        """
        self.download_list = download_list
        
        for file_info in self.download_list:
            url = file_info["url"]
            real_name = file_info["real_name"]
            save_path = f"{save_directory}/{real_name}"
            size_mb = file_info.get("size_mb",0.0)
            self.downloader.download(url, save_path,size=size_mb)
        return "Download tasks started"
    def get_download_statuses(self):
        """
        获取当前所有下载任务的状态
        """
        statuses = []
        for file_info in self.download_list:
            url = file_info["url"]
            name = file_info["name"]
            real_name = file_info["real_name"]
            
            status_info = self.downloader.get_status(url)
            
            statuses.append({
                "url": url,
                "name": name,
                "real_name": real_name,
                "status": status_info.get("status", "not_found"),
                "progress": status_info.get("progress", 0),
                "downloaded_mb": status_info.get("downloaded_mb", 0.0),
                "total_mb": status_info.get("total_mb", 0.0),
                "speed_mb_s": status_info.get("speed_mb_s", 0.0),
                "usedTime": status_info.get("usedTime", 0), 
                "ETA": status_info.get("ETA", 0),
                "error": status_info.get("error")
            })
        return statuses
    """
    状态列表:
    [
        {
            "url": "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/....",
            "name": "example.zip.txt",
            "real_name": "example.zip",
            "status": "completed",
            "progress": 100,  # 0-100
            "downloaded_mb": 20.5,
            "total_mb": 20.5,
            "speed_mb_s": 2.5,
            "usedTime": 0,
            "ETA": 0,
            "error": null
        }
    ]
    """
if __name__ == "__main__":
    main=Main(notion_token="[这里我调试的时候是notion-token，不能泄露，所以在调试过后换成了这个占位符]")
    download_list=main.get_download_list(page_id="2fc644ea-d11a-8010-9665-e5fbaba0fd58")
    print(download_list)
