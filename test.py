import os
import math
import requests
import mimetypes
from dotenv import load_dotenv

# ================= ⚙️ 加载环境变量 =================
# 加载同级目录下的 .env 文件
load_dotenv()

# 从环境变量读取配置
TOKEN = os.getenv("NOTION_TOKEN")
PAGE_ID = os.getenv("NOTION_PAGE_ID")

# 验证必要的环境变量
if not TOKEN:
    raise ValueError("❌ 请在 .env 文件中设置 NOTION_TOKEN")
if not PAGE_ID:
    raise ValueError("❌ 请在 .env 文件中设置 NOTION_PAGE_ID")

# ================= ⚙️ 配置区域 =================
CONFIG = {
    "TOKEN": TOKEN,
    "PAGE_ID": PAGE_ID,
    "FILE_PATH": r"C:\path\to\your\file.pdf",  # 指定单个文件路径用于测试
    "NOTION_VERSION": "2025-09-03"  # 保持与原代码一致
}
# ==============================================

def format_page_id(page_id):
    # 移除所有连字符和空格
    clean_id = page_id.replace("-", "").replace(" ", "")
    
    if len(clean_id) != 32:
        raise ValueError(f"无效的页面ID: {page_id}。应为32个字符")
    
    # 格式化为标准格式：8-4-4-4-12
    formatted_id = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"
    
    return formatted_id

def upload_single_file():
    filepath = CONFIG["FILE_PATH"]
    
    # 0. 基础信息准备
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        return

    # 格式化页面ID
    try:
        formatted_page_id = format_page_id(CONFIG["PAGE_ID"])
        print(f"📋 页面ID已格式化: {CONFIG['PAGE_ID']} -> {formatted_page_id}")
    except ValueError as e:
        print(f"❌ 页面ID格式错误: {e}")
        return

    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    mimetype = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    
    # 设置分片大小 (5MB)
    chunk_size = 5 * 1024 * 1024 
    num_parts = max(1, math.ceil(filesize / chunk_size))

    headers = {
        "Authorization": f"Bearer {CONFIG['TOKEN']}",
        "Notion-Version": CONFIG["NOTION_VERSION"],
        "User-Agent": "Notion-Minimal-Uploader/1.0"
    }

    print(f"🚀 开始上传: {filename} ({filesize/1024/1024:.2f} MB)")

    try:
        # === 1. 申请上传令牌 (Init) ===
        init_resp = requests.post(
            "https://api.notion.com/v1/file_uploads",
            headers=headers,
            json={
                "filename": filename,
                "content_type": mimetype,
                "mode": "multi_part",
                "number_of_parts": num_parts
            }
        )
        init_resp.raise_for_status()
        upload_data = init_resp.json()
        upload_id = upload_data["id"]
        print(f"✅ 获取令牌成功 ID: {upload_id}")

        # === 2. 分片上传循环 (Upload Loop) ===
        with open(filepath, "rb") as f:
            for i in range(1, num_parts + 1):
                chunk = f.read(chunk_size)
                if not chunk: break

                print(f"⏳ 正在传输分片 {i}/{num_parts}...")
                
                # 发送分片数据
                chunk_resp = requests.post(
                    f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
                    headers=headers,
                    files={"file": (filename, chunk, mimetype)},
                    data={"part_number": i}
                )
                chunk_resp.raise_for_status()

        # === 3. 标记上传完成 (Finish) ===
        print("☁️ 正在云端合成...")
        finish_resp = requests.post(
            f"https://api.notion.com/v1/file_uploads/{upload_id}/complete",
            headers=headers,
            json={}
        )
        finish_resp.raise_for_status()

        # === 4. 挂载到 Notion 页面 (Mount) ===
        print("🔗 正在挂载到页面...")
        mount_payload = {
            "children": [{
                "object": "block",
                "type": "file",
                "file": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": [{"type": "text", "text": {"content": filename}}]
                }
            }]
        }
        
        mount_resp = requests.patch(
            f"https://api.notion.com/v1/blocks/{formatted_page_id}/children",  # 使用格式化后的页面ID
            headers=headers,
            json=mount_payload
        )
        mount_resp.raise_for_status()

        print(f"🎉 成功! 文件已上传至页面: {formatted_page_id}")  # 使用格式化后的页面ID

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        # 如果是 API 错误，打印详细信息
        if isinstance(e, requests.exceptions.HTTPError):
            print(f"🔍 API 响应: {e.response.text}")

if __name__ == "__main__":
    upload_single_file()