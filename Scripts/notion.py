import requests
import json
class Notion:
    def __init__(self, token, version="2025-09-03", url="https://api.notion.com/v1"):
        self.token = token
        self.version = version
        self.url = url
        if(self.url[-1] == '/'):
            self.url = self.url[:-1]
        self.default_headers = {#默认请求头模板
            "Notion-Version": self.version,
            "Authorization": f"Bearer {self.token}",
        }
    def query_page(self, page_id, fetch_all=False):
        all_blocks = []
        cursor = None#分页游标
        max_retries = 4 # 最大重试次数
        while True:
            # 1. 处理分页请求
            params = {"start_cursor": cursor} if cursor else {}#只有在有游标时才添加该参数
            #======请求重试机制=======
            for attempt in range(max_retries):
                try:
                    res = requests.get(
                        f"{self.url}/blocks/{page_id}/children", 
                        headers=self.default_headers,
                        params=params,
                        timeout=10 # 防止请求死锁
                    )
                    
                    # 如果是 429 (Too Many Requests) 或 5xx 错误，触发重试
                    if res.status_code in [429, 500, 502, 503, 504]:
                        wait_time = 2 ** attempt # 1, 2, 4, 8...
                        print(f"[Notion-query_page]⚠️ 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                    # 成功请求，跳出重试循环
                    res.raise_for_status() 
                    break
                    
                except (requests.exceptions.RequestException, Exception) as e:
                    wait_time = 2 ** attempt
                    if attempt < max_retries - 1:
                        print(f"[Notion-query_page]❌ 请求异常: {e}，等待 {wait_time}s 后重试...")
                        time.sleep(wait_time)
                    else:
                        print(f"[Notion-query_page]🚨 已达到最大重试次数，任务失败。")
                        return all_blocks # 返回已拿到的部分数据
            #======请求重试机制=======
            data = res.json()
            blocks = data.get("results", [])
            # 2. 如果开启了 fetch_all，处理递归嵌套
            if fetch_all:
                for block in blocks:
                    # 检查该块是否包含子块
                    if block.get("has_children"):
                        # 递归调用自身，获取该 block 的子内容
                        # 将结果存入 block 字典中，方便前端或后续逻辑解析
                        block["children"] = self.query_page(block["id"], fetch_all=True)
            all_blocks.extend(blocks)
            # 3. 检查是否还有更多分页
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return all_blocks
    def get_download_url(self, body):
        """
        下载链接的格式:
        [
            {
                "name": "example.zip.txt"
                "real_name": "example.zip"
                "url": "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/...."
                "expiry_time": "2024-10-01T12:00:00.000Z"
            }
        ]
        """
        download_list = []
        if not body:
            return download_list

        for block in body:
            # 1. 检查是否是文件块
            if block.get("type") == "file":
                file_info = block["file"]
                
                # 提取原始文件名
                original_name = file_info.get("name", "unknown")
                # 提取 URL 和 过期时间 (Notion 托管的文件在 file.file 下)
                # 兼容处理：Notion 也有 external 类型的链接
                if file_info["type"] == "file":
                    url = file_info["file"]["url"]
                    expiry_time = file_info["file"].get("expiry_time")
                else:
                    url = file_info["external"]["url"]
                    expiry_time = None
                # 提取 real_name (标题)
                # caption 是一个 rich_text 数组，需要拼接
                captions = file_info.get("caption", [])
                caption_text = "".join([t.get("plain_text", "") for t in captions]).strip()
                real_name = caption_text if caption_text else original_name
                download_list.append({
                    "name": original_name,
                    "real_name": real_name,
                    "url": url,
                    "expiry_time": expiry_time
                })
            # 3. 递归处理子块 (处理嵌套在页面、折叠框里的文件)
            if block.get("has_children") and "children" in block:
                child_downloads = self.get_download_url(block["children"])
                download_list.extend(child_downloads)
        return download_list
        
        
if __name__ == "__main__":
    notion = Notion("your_integration_token_here")
    page_data = notion.query_page("your_page_id",True)
    download_urls = notion.get_download_url(page_data)
    print(download_urls)