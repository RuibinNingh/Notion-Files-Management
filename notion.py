<<<<<<< HEAD
# Notion-Files-Management - Notion API封装模块 (重构版)
# 基于 Notion API 2025-09-03 版本
# Copyright (C) 2025 Ruibin_Ningh & Zyx_2012
# License: GPL v3
=======
# Notion-Files-Management - Notion API封装模块
# Copyright (C) 2025-2026 Ruibin_Ningh & Zyx_2012
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Contact: ruibinningh@outlook.com
>>>>>>> dd9e024ca52a7abc178aae543491e25f7b46820e

import os
import math
import time
import logging
import mimetypes
from datetime import datetime
from typing import List, Tuple, Optional, Callable, Dict, Any
from dataclasses import dataclass
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============ 配置常量 ============

NOTION_API_VERSION = "2025-09-03"
NOTION_BASE_URL = "https://api.notion.com/v1"

# 文件大小限制
SMALL_FILE_LIMIT = 20 * 1024 * 1024   # 20MB - 小文件直传
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB - 最大文件
PART_SIZE = 10 * 1024 * 1024           # 10MB - 分片大小

# 重试配置
MAX_RETRIES = 10
RETRY_BACKOFF_FACTOR = 2
INITIAL_RETRY_DELAY = 1

# Notion 支持的文件类型及MIME映射
SUPPORTED_EXTENSIONS = {
    '.aac': 'audio/aac', '.adts': 'audio/aac', '.mid': 'audio/midi',
    '.midi': 'audio/midi', '.mp3': 'audio/mpeg', '.mpga': 'audio/mpeg',
    '.m4a': 'audio/mp4', '.m4b': 'audio/mp4',
    '.oga': 'audio/ogg', '.ogg': 'audio/ogg', '.wav': 'audio/wav',
    '.wma': 'audio/x-ms-wma',
    '.pdf': 'application/pdf', '.txt': 'text/plain', '.json': 'application/json',
    '.doc': 'application/msword', '.dot': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.dotx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
    '.xls': 'application/vnd.ms-excel', '.xlt': 'application/vnd.ms-excel',
    '.xla': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xltx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
    '.ppt': 'application/vnd.ms-powerpoint', '.pot': 'application/vnd.ms-powerpoint',
    '.pps': 'application/vnd.ms-powerpoint', '.ppa': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.potx': 'application/vnd.openxmlformats-officedocument.presentationml.template',
    '.gif': 'image/gif', '.heic': 'image/heic', '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml',
    '.tif': 'image/tiff', '.tiff': 'image/tiff', '.webp': 'image/webp',
    '.ico': 'image/vnd.microsoft.icon',
    '.amv': 'video/x-amv', '.asf': 'video/x-ms-asf', '.wmv': 'video/x-ms-asf',
    '.avi': 'video/x-msvideo', '.f4v': 'video/x-f4v', '.flv': 'video/x-flv',
    '.gifv': 'video/mp4', '.m4v': 'video/mp4', '.mp4': 'video/mp4',
    '.mkv': 'video/webm', '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.qt': 'video/quicktime', '.mpeg': 'video/mpeg',
}

# Block类型映射
FILE_TYPE_TO_BLOCK = {
    'image': ['image/gif', 'image/heic', 'image/jpeg', 'image/png',
              'image/svg+xml', 'image/tiff', 'image/webp', 'image/vnd.microsoft.icon'],
    'video': ['video/x-amv', 'video/x-ms-asf', 'video/x-msvideo', 'video/x-f4v',
              'video/x-flv', 'video/mp4', 'video/webm', 'video/quicktime', 'video/mpeg'],
    'audio': ['audio/aac', 'audio/midi', 'audio/mpeg', 'audio/mp4',
              'audio/ogg', 'audio/wav', 'audio/x-ms-wma'],
    'pdf': ['application/pdf'],
}

# 缓存配置
CACHE_EXPIRY = 40 * 60     # 40分钟
CACHE_WARNING = 30 * 60    # 30分钟提示


# ============ 数据类 ============

class UploadStatus(Enum):
    """上传状态枚举"""
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETING = "completing"
    ATTACHING = "attaching"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class FileInfo:
    """文件信息"""
    name: str
    url: str
    load_time: str
    
    def to_list(self) -> list:
        return [self.name, self.url, self.load_time]


@dataclass 
class UploadProgress:
    """上传进度"""
    filename: str
    uploaded: int
    total: int
    status: UploadStatus
    part_current: int = 0
    part_total: int = 0
    retry_count: int = 0


@dataclass
class UploadFileInfo:
    """上传文件信息"""
    path: str
    original_name: str
    upload_name: str
    size: int
    mime_type: str
    is_spoofed: bool = False
    
    @classmethod
    def from_path(cls, filepath: str) -> 'UploadFileInfo':
        """从文件路径创建"""
        original_name = os.path.basename(filepath)
        ext = os.path.splitext(original_name)[1].lower()
        size = os.path.getsize(filepath)
        
        if ext in SUPPORTED_EXTENSIONS:
            mime_type = SUPPORTED_EXTENSIONS[ext]
            upload_name = original_name
            is_spoofed = False
        else:
            mime_type = 'text/plain'
            upload_name = original_name + '.txt'
            is_spoofed = True
        
        return cls(
            path=filepath,
            original_name=original_name,
            upload_name=upload_name,
            size=size,
            mime_type=mime_type,
            is_spoofed=is_spoofed
        )
    
    def get_block_type(self) -> str:
        """获取Notion block类型"""
        for block_type, mime_types in FILE_TYPE_TO_BLOCK.items():
            if self.mime_type in mime_types:
                return block_type
        return 'file'


# ============ 主类 ============

class NotionFileManager:
    """Notion文件管理器 - 支持大文件上传下载"""
    
    def __init__(self, token: str, version: str = None):
        load_dotenv()
        self.token = token
        self.version = version or NOTION_API_VERSION
        self.base_url = NOTION_BASE_URL
        self.current_page_id: Optional[str] = None
        
        # HTTP会话
        self.session = self._create_session()
        
        # 文件列表缓存
        self._cache: Dict[str, dict] = {}
    
    def _create_session(self) -> requests.Session:
        """创建带重试的HTTP会话"""
        session = requests.Session()
        retry = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PATCH"],
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session
    
    def _get_headers(self, content_type: str = "application/json") -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers
    
    def _api_request(self, method: str, endpoint: str,
                     data: Optional[Dict] = None, files: Optional[Dict] = None,
                     params: Optional[Dict] = None,
                     retry_count: int = 0) -> Tuple[bool, Any]:
        """统一的API请求方法"""
        url = f"{self.base_url}/{endpoint}"
        
        try:
            if files:
                headers = self._get_headers(content_type=None)
                resp = self.session.request(method, url, headers=headers, 
                                           files=files, data=data, timeout=300)
            else:
                headers = self._get_headers()
                resp = self.session.request(method, url, headers=headers, 
                                           json=data, params=params, timeout=60)
            
            if resp.status_code in [200, 201]:
                return True, resp.json()
            
            error_data = {}
            try:
                error_data = resp.json()
            except:
                pass
            
            error_msg = error_data.get('message', resp.text[:200])
            
            # 可重试的错误
            if resp.status_code in [429, 500, 502, 503, 504]:
                if retry_count < MAX_RETRIES:
                    delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count)
                    time.sleep(delay)
                    return self._api_request(method, endpoint, data, files, params, retry_count + 1)
            
            return False, f"HTTP {resp.status_code}: {error_msg}"
            
        except requests.exceptions.Timeout:
            if retry_count < MAX_RETRIES:
                delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count)
                time.sleep(delay)
                return self._api_request(method, endpoint, data, files, params, retry_count + 1)
            return False, "请求超时"
            
        except requests.exceptions.RequestException as e:
            if retry_count < MAX_RETRIES:
                delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count)
                time.sleep(delay)
                return self._api_request(method, endpoint, data, files, params, retry_count + 1)
            return False, f"网络错误: {e}"
    
    # ============ 页面管理 ============
    
    def set_page(self, page_id: str):
        """设置当前页面"""
        if self.current_page_id != page_id:
            self._cache.pop(self.current_page_id, None)
            self.current_page_id = page_id
            logger.info(f"切换到页面: {page_id}")
    
    def create_child_page(self, parent_id: str, title: str) -> Tuple[bool, Any]:
        """在父页面下创建子页面"""
        data = {
            "parent": {"page_id": parent_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            }
        }
        return self._api_request("POST", "pages", data)
    
    # ============ 缓存管理 ============
    
    def _is_cache_valid(self) -> bool:
        if not self.current_page_id or self.current_page_id not in self._cache:
            return False
        age = time.time() - self._cache[self.current_page_id]['timestamp']
        return age < CACHE_EXPIRY
    
    def clear_cache(self, page_id: Optional[str] = None):
        if page_id:
            self._cache.pop(page_id, None)
        else:
            self._cache.clear()
    
    # ============ 文件列表 ============
    
    def file_list(self, force_refresh: bool = False) -> List[list]:
        """获取当前页面的文件列表"""
        if not self.current_page_id:
            raise ValueError("请先调用 set_page() 设置页面ID")
        
        if not force_refresh and self._is_cache_valid():
            return self._cache[self.current_page_id]['data'].copy()
        
        logger.info("正在获取文件列表...")
        blocks = self._get_file_blocks(self.current_page_id)
        
        result = []
        load_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for block in blocks:
            try:
                info = self._parse_file_block(block, load_time)
                if info:
                    result.append(info.to_list())
            except Exception as e:
                logger.error(f"解析block失败: {e}")
        
        self._cache[self.current_page_id] = {
            'data': result,
            'timestamp': time.time()
        }
        logger.info(f"获取到 {len(result)} 个文件")
        return result
    
    def _get_file_blocks(self, block_id: str) -> list:
        """获取页面下的所有文件block"""
        FILE_TYPES = ["file", "image", "video", "pdf", "audio"]
        blocks = []
        cursor = None
        
        while True:
            params = {"page_size": 50}
            if cursor:
                params["start_cursor"] = cursor
            
            success, data = self._api_request("GET", f"blocks/{block_id}/children", params=params)
            if not success:
                break
            
            for block in data.get("results", []):
                if block.get("type") in FILE_TYPES:
                    blocks.append(block)
            
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            time.sleep(0.3)
        
        return blocks
    
    def _parse_file_block(self, block: dict, load_time: str) -> Optional[FileInfo]:
        """解析文件block"""
        block_type = block.get("type")
        content = block.get(block_type, {})
        
        name = content.get("name", "")
        file_type = content.get("type")
        
        if file_type == "file":
            url = content.get("file", {}).get("url", "")
        elif file_type == "external":
            url = content.get("external", {}).get("url", "")
        else:
            url = ""
        
        if not name and url:
            name = url.split('/')[-1].split('?')[0]
        
        if not name:
            name = "未命名文件"
        
        return FileInfo(name=name, url=url, load_time=load_time)
    
    # ============ 文件上传 (核心重构) ============
    
    def upload_file(self, filepath: str, target_page_id: str = None,
                    progress_callback: Optional[Callable[[UploadProgress], None]] = None) -> bool:
        """
        上传单个文件到Notion
        
        Args:
            filepath: 文件路径
            target_page_id: 目标页面ID，默认使用current_page_id
            progress_callback: 进度回调函数
        
        Returns:
            是否上传成功
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"文件不存在: {filepath}")
        
        page_id = target_page_id or self.current_page_id
        if not page_id:
            raise ValueError("请指定目标页面ID或先调用 set_page()")
        
        # 获取文件信息
        file_info = UploadFileInfo.from_path(filepath)
        
        if file_info.size > MAX_FILE_SIZE:
            raise ValueError(f"文件过大: {file_info.size / 1024 / 1024 / 1024:.1f}GB > 5GB")
        
        logger.info(f"开始上传: {file_info.original_name} ({file_info.size / 1024 / 1024:.1f}MB)")
        
        def report(status: UploadStatus, uploaded: int = 0, 
                   part_current: int = 0, part_total: int = 0, retry: int = 0):
            if progress_callback:
                progress_callback(UploadProgress(
                    filename=file_info.original_name,
                    uploaded=uploaded,
                    total=file_info.size,
                    status=status,
                    part_current=part_current,
                    part_total=part_total,
                    retry_count=retry
                ))
        
        try:
            # 根据文件大小选择上传方式
            if file_info.size <= SMALL_FILE_LIMIT:
                return self._upload_small_file(file_info, page_id, report)
            else:
                return self._upload_large_file(file_info, page_id, report)
                
        except Exception as e:
            logger.error(f"上传失败: {e}")
            report(UploadStatus.FAILED)
            return False
    
    def _upload_small_file(self, file_info: UploadFileInfo, page_id: str,
                           report: Callable) -> bool:
        """上传小文件 (<=20MB) - 单次上传"""
        report(UploadStatus.UPLOADING, 0, 0, 1)
        
        # 1. 创建上传会话
        success, result = self._api_request("POST", "file_uploads", {
            "filename": file_info.upload_name,
            "content_type": file_info.mime_type
        })
        if not success:
            logger.error(f"创建上传会话失败: {result}")
            return False
        
        upload_id = result['id']
        
        # 2. 读取并上传文件内容
        with open(file_info.path, 'rb') as f:
            file_content = f.read()
        
        report(UploadStatus.UPLOADING, file_info.size // 2, 1, 1)
        
        success, result = self._api_request("POST", f"file_uploads/{upload_id}/send",
            files={'file': ('file', file_content)}
        )
        if not success:
            logger.error(f"上传文件内容失败: {result}")
            return False
        
        report(UploadStatus.UPLOADING, file_info.size, 1, 1)
        
        # 3. 附加到页面
        report(UploadStatus.ATTACHING, file_info.size, 1, 1)
        
        success = self._attach_file_to_page(upload_id, file_info, page_id)
        if not success:
            return False
        
        report(UploadStatus.COMPLETED, file_info.size, 1, 1)
        logger.info(f"上传完成: {file_info.original_name}")
        return True
    
    def _upload_large_file(self, file_info: UploadFileInfo, page_id: str,
                           report: Callable) -> bool:
        """上传大文件 (>20MB) - 分片上传"""
        num_parts = math.ceil(file_info.size / PART_SIZE)
        
        report(UploadStatus.UPLOADING, 0, 0, num_parts)
        
        # 1. 创建分片上传会话
        success, result = self._api_request("POST", "file_uploads", {
            "filename": file_info.upload_name,
            "content_type": file_info.mime_type,
            "mode": "multi_part",
            "number_of_parts": num_parts
        })
        if not success:
            logger.error(f"创建上传会话失败: {result}")
            return False
        
        upload_id = result['id']
        bytes_uploaded = 0
        
        # 2. 分片上传
        with open(file_info.path, 'rb') as f:
            for part_num in range(1, num_parts + 1):
                f.seek((part_num - 1) * PART_SIZE)
                chunk = f.read(PART_SIZE)
                chunk_size = len(chunk)
                
                # 分片上传带重试和会话重建
                part_success = False
                retry_count = 0
                
                while not part_success and retry_count < MAX_RETRIES:
                    if retry_count > 0:
                        report(UploadStatus.RETRYING, bytes_uploaded, part_num, num_parts, retry_count)
                    else:
                        report(UploadStatus.UPLOADING, bytes_uploaded, part_num, num_parts)
                    
                    success, result = self._api_request("POST", f"file_uploads/{upload_id}/send",
                        files={'file': ('file', chunk)},
                        data={'part_number': str(part_num)}
                    )
                    
                    if success:
                        part_success = True
                        bytes_uploaded += chunk_size
                        report(UploadStatus.UPLOADING, bytes_uploaded, part_num, num_parts)
                    else:
                        retry_count += 1
                        
                        if retry_count < MAX_RETRIES:
                            # 检查会话是否失效
                            status_ok, status_result = self._api_request("GET", f"file_uploads/{upload_id}")
                            
                            if not status_ok or status_result.get('status') == 'archived':
                                # 会话失效，重新创建
                                logger.warning(f"会话失效，重新创建上传会话...")
                                success, new_result = self._api_request("POST", "file_uploads", {
                                    "filename": file_info.upload_name,
                                    "content_type": file_info.mime_type,
                                    "mode": "multi_part",
                                    "number_of_parts": num_parts
                                })
                                if success:
                                    upload_id = new_result['id']
                                    # 从头开始上传
                                    f.seek(0)
                                    bytes_uploaded = 0
                                    part_num = 0
                                    break
                            
                            delay = INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count)
                            time.sleep(delay)
                        else:
                            logger.error(f"分片 {part_num} 上传失败，已达最大重试次数")
                            report(UploadStatus.FAILED)
                            return False
        
        # 3. 完成分片上传
        report(UploadStatus.COMPLETING, file_info.size, num_parts, num_parts)
        
        success, result = self._api_request("POST", f"file_uploads/{upload_id}/complete")
        if not success:
            logger.error(f"完成上传失败: {result}")
            return False
        
        # 4. 附加到页面
        report(UploadStatus.ATTACHING, file_info.size, num_parts, num_parts)
        
        success = self._attach_file_to_page(upload_id, file_info, page_id)
        if not success:
            return False
        
        report(UploadStatus.COMPLETED, file_info.size, num_parts, num_parts)
        logger.info(f"上传完成: {file_info.original_name}")
        return True
    
    def _attach_file_to_page(self, upload_id: str, file_info: UploadFileInfo, 
                             page_id: str) -> bool:
        """将上传的文件附加到页面"""
        block_type = file_info.get_block_type()
        caption = [{"type": "text", "text": {"content": file_info.original_name}}]
        
        block_configs = {
            'image': {
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": caption
                }
            },
            'video': {
                "type": "video",
                "video": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": caption
                }
            },
            'audio': {
                "type": "audio",
                "audio": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": caption
                }
            },
            'pdf': {
                "type": "pdf",
                "pdf": {
                    "type": "file_upload",
                    "file_upload": {"id": upload_id},
                    "caption": caption
                }
            },
        }
        
        block_data = block_configs.get(block_type, {
            "type": "file",
            "file": {
                "type": "file_upload",
                "file_upload": {"id": upload_id},
                "caption": caption,
                "name": file_info.original_name
            }
        })
        
        success, result = self._api_request("PATCH", f"blocks/{page_id}/children", 
                                            {"children": [block_data]})
        if not success:
            logger.error(f"附加文件失败: {result}")
            return False
        
        return True
    
    # ============ 文件下载 ============
    
    def download_file(self, file_info: list, save_path: str,
                      progress_callback: Optional[Callable] = None) -> bool:
        """下载单个文件"""
        name, url, _ = file_info
        os.makedirs(save_path, exist_ok=True)
        save_file = os.path.join(save_path, name)
        
        try:
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            
            with open(save_file, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(name, downloaded, total, "下载中")
            
            if progress_callback:
                progress_callback(name, total, total, "完成")
            
            logger.info(f"下载完成: {name}")
            return True
            
        except Exception as e:
            logger.error(f"下载失败 {name}: {e}")
            return False


# ============ IDM导出器 ============

class IDMExporter:
    """IDM任务文件导出器"""
    
    @staticmethod
    def export_tasks(file_urls: List[Tuple[str, str]], save_path: str) -> Optional[str]:
        """导出IDM .ef2任务文件"""
        if not file_urls:
            return None
        
        os.makedirs(save_path, exist_ok=True)
        ef2_file = os.path.join(save_path, "idm_tasks.ef2")
        
        try:
            with open(ef2_file, 'w', encoding='utf-8') as f:
                for filename, url in file_urls:
                    referer = IDMExporter._extract_referer(url)
                    f.write("<\n")
                    f.write(f"{url}\n")
                    f.write(f"referer: {referer}\n")
                    f.write("User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0\n")
                    f.write(">\n")
            
            logger.info(f"IDM任务文件已导出: {ef2_file}")
            return ef2_file
            
        except Exception as e:
            logger.error(f"导出IDM任务失败: {e}")
            return None
    
    @staticmethod
    def _extract_referer(url: str) -> str:
        from urllib.parse import urlparse
        try:
            if "github" in url:
                return "https://github.com"
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
        except:
            return ""


if __name__ == "__main__":
    load_dotenv()
    manager = NotionFileManager(
        os.getenv("NOTION_TOKEN"),
        os.getenv("NOTION_VERSION")
    )
    manager.set_page(os.getenv("NOTION_PAGE_ID"))
    print(manager.file_list())
