import os
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

class NotionData:
    def __init__(self, token: str, version: str = "2025-09-03"):
        self.notion = Client(auth=token)
        self.version = version

    # --------------------
    # 查询数据源列表
    # --------------------
    def query_data_source(self, data_source_id: str, page_size: int = 100) -> list:
        """查询数据源下的条目列表"""
        all_items = []
        next_cursor = None

        while True:
            resp = self.notion.data_sources.query(
                data_source_id=data_source_id,
                start_cursor=next_cursor,
                page_size=page_size
            )
            all_items.extend(resp.get("results", []))
            next_cursor = resp.get("next_cursor")
            if not next_cursor:
                break
        return all_items

    # --------------------
    # 获取页面块（包括文件）
    # --------------------
    def get_page_blocks(self, page_id: str) -> list:
        """获取页面子块列表"""
        all_blocks = []
        next_cursor = None

        while True:
            resp = self.notion.blocks.children.list(
                block_id=page_id,
                start_cursor=next_cursor,
                page_size=100
            )
            all_blocks.extend(resp.get("results", []))
            next_cursor = resp.get("next_cursor")
            if not next_cursor:
                break
        return all_blocks

    # --------------------
    # 获取页面下的文件块
    # --------------------
    def get_page_files(self, page_id: str) -> list:
        """
        获取页面下所有文件块，返回格式:
        [{"name": 文件名, "uploaded_time": 上传时间, "url": 链接}, ...]
        """
        blocks = self.get_page_blocks(page_id)
        files_info = []
        for b in blocks:
            if b.get("type") == "file":
                f = b["file"]
                inner = f.get("file")
                if inner:
                    files_info.append({
                        "name": inner.get("name") or f.get("name") or "",
                        "uploaded_time": b.get("created_time", ""),
                        "url": inner.get("url", "")
                    })
        return files_info

    # --------------------
    # 获取页面下的所有内容块
    # --------------------
    def get_page_all_contents(self, page_id: str) -> list:
        """获取页面下所有内容块"""
        return self.get_page_blocks(page_id)

# --------------------
# 使用示例
# --------------------
if __name__ == "__main__":
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    DATA_SOURCE_ID = "2c9644ea-d11a-8061-9707-000be0590cf4"

    nd = NotionData(NOTION_TOKEN)

    # 查询数据源条目
    items = nd.query_data_source(DATA_SOURCE_ID)
    print(f"数据源条目数量: {len(items)}")
    print(items)
    # 如果有页面 id，获取文件块
    if items:
        first_page_id = items[0]["id"]
        print(first_page_id)
        files = nd.get_page_files(first_page_id)
        print(f"页面文件块数量: {len(files)}")
        print(files)
        print("获取页面所有:")
        print(nd.get_page_all_contents(first_page_id))
