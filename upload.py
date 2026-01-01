import os, math, csv, httpx, time
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
notion = Client(auth=NOTION_TOKEN)
NOTION_VERSION = "2025-09-03"

def print_progress(sent, total, start_time, bar_length=30):
    """
    打印上传进度条、速率和预计剩余时间
    sent: 已上传字节数
    total: 文件总字节数
    start_time: 上传开始时间，time.time()
    """
    percent = sent / total
    filled = int(bar_length * percent)
    bar = "█" * filled + "-" * (bar_length - filled)

    elapsed = time.time() - start_time
    speed = sent / (1024*1024) / elapsed if elapsed > 0 else 0  # MB/s
    remaining = (total - sent) / (sent / elapsed) if sent > 0 else 0
    print(f"\r[{bar}] {percent*100:6.2f}% ({sent/1000000:.2f}/{total/1000000:.2f} MB) "
          f"{speed:6.2f} MB/s, ETA: {int(remaining)} s", end="", flush=True)


class NotionUploader:
    def __init__(self, notion, token, version):
        self.notion = notion
        self.token = token
        self.version = version
        self.total = 0
        self.sent = 0

    def upload_file(self, filepath, page_id, part_size=18*1024*1024, log_progress=True):
        import os, math, httpx
        self.total = os.path.getsize(filepath)
        self.sent = 0
        name = os.path.basename(filepath)+".txt"
        mime = "text/plain"

        parts = math.ceil(self.total / part_size)
        create_resp = self.notion.file_uploads.create(
            mode="multi_part",
            filename=name,
            content_type=mime,
            number_of_parts=parts
        )
        upload_id = create_resp["id"]
        print(f"开始上传文件: {name} 大小: {self.total} 字节, 分片数: {parts}")
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": self.version}

        start_time = time.time()
        with open(filepath, "rb") as f, httpx.Client(timeout=120.0) as client:
            for i in range(1, parts + 1):
                chunk = f.read(part_size)
                files = {"file": (name, chunk, mime)}
                url = f"https://api.notion.com/v1/file_uploads/{upload_id}/send"
                data = {"part_number": i}
                r = client.post(url, headers=headers, files=files, data=data)
                r.raise_for_status()
                self.sent += len(chunk)
                if log_progress:
                    print_progress(self.sent, self.total, start_time)

        # 完成上传
        self.notion.file_uploads.complete(file_upload_id=upload_id)

        # 附加到页面
        self.notion.blocks.children.append(
            block_id=page_id,
            children=[
                {"object": "block", "type": "file",
                 "file": {"type": "file_upload", "file_upload": {"id": upload_id}}}
            ]
        )
        if log_progress:
            print()  # 换行
        return upload_id

    def get_progress(self):
        if self.total == 0:
            return 0.0
        return [self.sent, self.total]


if __name__ == "__main__":
    folder_path = r"D:\Users\ADMIN\Desktop\备份"
    pid = "2cf644ea-d11a-80ae-81b7-e5b940a4fdcf"
    uploader = NotionUploader(notion, NOTION_TOKEN, NOTION_VERSION)

    files = sorted([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))])
    for f in files:
        filepath = os.path.join(folder_path, f)
        print(f"\n开始上传: {filepath}")
        uploader.upload_file(filepath, pid)
        print(f"完成上传: {filepath}")

    print("\n所有文件上传完成！")
