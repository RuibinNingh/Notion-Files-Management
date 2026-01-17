# Notion-Files-Management - Notion API封装模块 (改进版)
# 优化大文件上传重试机制
# Copyright (C) 2025-2026 Ruibin_Ningh & Zyx_2012
# License: GPL v3

import os
import math
import time
import logging
import mimetypes
from datetime import datetime
from typing import List, Tuple, Optional, Callable, Dict, Any, Set
from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv


# ============ 日志配置 ============

def setup_file_logger(log_dir: str = None, log_level: int = logging.DEBUG) -> logging.Logger:
    """
    设置文件日志记录器
    
    Args:
        log_dir: 日志目录，默认为当前目录下的 logs 文件夹
        log_level: 日志级别，默认 DEBUG
    
    Returns:
        配置好的 logger
    """
    logger = logging.getLogger("notion_upload")
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    logger.setLevel(log_level)
    
    # 日志目录
    if log_dir is None:
        log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # 日志文件名：upload_YYYYMMDD_HHMMSS.log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"upload_{timestamp}.log")
    
    # 文件Handler - 详细日志（只输出到文件，不干扰进度UI）
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(funcName)-25s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # 注意：不添加控制台Handler，避免日志干扰进度条显示
    # 所有日志都会写入文件，上传完成后提示用户查看日志文件
    
    logger.addHandler(file_handler)
    
    # 静默记录日志文件位置（不打印到控制台）
    logger.debug(f"日志文件: {log_file}")
    
    # 保存日志文件路径供外部访问
    logger.log_file_path = log_file
    
    return logger


# 初始化日志
logger = setup_file_logger()


# ============ 配置常量 ============

NOTION_API_VERSION = "2025-09-03"
NOTION_BASE_URL = "https://api.notion.com/v1"

# 文件大小限制
SMALL_FILE_LIMIT = 20 * 1024 * 1024   # 20MB - 小文件直传
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB - 最大文件
PART_SIZE = 10 * 1024 * 1024           # 10MB - 分片大小

# 重试配置 - 改为无限重试
MAX_PART_RETRIES = float('inf')  # 单个分片无限重试
RETRY_BACKOFF_FACTOR = 2
INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 60  # 最大重试延迟60秒

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
    CHECKING = "checking"
    RECOVERING = "recovering"


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
    message: str = ""


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


@dataclass
class UploadSession:
    """上传会话信息"""
    upload_id: str
    filename: str
    num_parts: int
    uploaded_parts: Set[int]
    status: str
    created_time: float


# ============ 主类 ============

class NotionFileManager:
    """Notion文件管理器 - 支持大文件上传下载 (改进版)"""
    
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
        request_id = f"{method}:{endpoint}:{retry_count}"
        
        # 记录请求开始
        logger.debug(f"[{request_id}] 开始请求: {url}")
        if data and not files:
            # 记录请求数据（排除敏感信息）
            safe_data = {k: v for k, v in data.items() if k not in ['file', 'content']}
            logger.debug(f"[{request_id}] 请求数据: {safe_data}")
        if files:
            file_info = {k: f"<{type(v).__name__}, {len(v[1]) if isinstance(v, tuple) else 'unknown'} bytes>" 
                        for k, v in files.items()}
            logger.debug(f"[{request_id}] 上传文件: {file_info}")
        
        start_time = time.time()
        
        try:
            if files:
                headers = self._get_headers(content_type=None)
                resp = self.session.request(method, url, headers=headers, 
                                           files=files, data=data, timeout=300)
            else:
                headers = self._get_headers()
                resp = self.session.request(method, url, headers=headers, 
                                           json=data, params=params, timeout=60)
            
            elapsed = time.time() - start_time
            
            if resp.status_code in [200, 201]:
                logger.debug(f"[{request_id}] ✓ 成功 (HTTP {resp.status_code}, {elapsed:.2f}s)")
                return True, resp.json()
            
            error_data = {}
            try:
                error_data = resp.json()
            except:
                pass
            
            error_msg = error_data.get('message', resp.text[:200])
            error_code = error_data.get('code', 'unknown')
            
            # 详细记录错误信息
            logger.warning(f"[{request_id}] ✗ 失败 (HTTP {resp.status_code}, {elapsed:.2f}s)")
            logger.warning(f"[{request_id}] 错误代码: {error_code}")
            logger.warning(f"[{request_id}] 错误信息: {error_msg}")
            logger.debug(f"[{request_id}] 响应头: {dict(resp.headers)}")
            
            # 可重试的错误
            if resp.status_code in [429, 500, 502, 503, 504]:
                if retry_count < 10:  # API级别限制10次重试
                    delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
                    logger.info(f"[{request_id}] 可重试错误，{delay}秒后进行第{retry_count + 1}次重试")
                    time.sleep(delay)
                    return self._api_request(method, endpoint, data, files, params, retry_count + 1)
                else:
                    logger.error(f"[{request_id}] 已达最大重试次数(10次)，放弃请求")
            
            return False, f"HTTP {resp.status_code}: {error_msg}"
            
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - start_time
            logger.warning(f"[{request_id}] ✗ 请求超时 ({elapsed:.2f}s): {e}")
            
            if retry_count < 10:
                delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
                logger.info(f"[{request_id}] 超时重试，{delay}秒后进行第{retry_count + 1}次重试")
                time.sleep(delay)
                return self._api_request(method, endpoint, data, files, params, retry_count + 1)
            
            logger.error(f"[{request_id}] 超时达最大重试次数，放弃请求")
            return False, "请求超时"
            
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            logger.warning(f"[{request_id}] ✗ 网络错误 ({elapsed:.2f}s): {type(e).__name__}: {e}")
            
            if retry_count < 10:
                delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
                logger.info(f"[{request_id}] 网络错误重试，{delay}秒后进行第{retry_count + 1}次重试")
                time.sleep(delay)
                return self._api_request(method, endpoint, data, files, params, retry_count + 1)
            
            logger.error(f"[{request_id}] 网络错误达最大重试次数，放弃请求")
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
            try:
                name = unquote(name)
            except Exception as e:
                logger.warning(f"URL解码失败: {e}")
        
        if not name:
            name = "未命名文件"
        
        return FileInfo(name=name, url=url, load_time=load_time)
    
    # ============ 上传会话管理 (新增) ============
    
    def _get_upload_session_status(self, upload_id: str) -> Optional[UploadSession]:
        """
        查询上传会话状态
        
        Returns:
            UploadSession 包含会话信息和已上传的分片列表
        """
        success, result = self._api_request("GET", f"file_uploads/{upload_id}")
        
        if not success:
            logger.error(f"查询会话状态失败: {result}")
            return None
        
        # 解析已上传的分片
        uploaded_parts = set()
        parts_info = result.get('parts', [])
        
        for part in parts_info:
            if part.get('status') == 'uploaded':
                uploaded_parts.add(part.get('part_number'))
        
        return UploadSession(
            upload_id=upload_id,
            filename=result.get('filename', ''),
            num_parts=result.get('number_of_parts', 0),
            uploaded_parts=uploaded_parts,
            status=result.get('status', ''),
            created_time=time.time()
        )
    
    def _is_session_valid(self, upload_id: str) -> bool:
        """检查上传会话是否有效"""
        success, result = self._api_request("GET", f"file_uploads/{upload_id}")
        
        if not success:
            return False
        
        status = result.get('status', '')
        return status not in ['archived', 'completed', 'error']
    
    # ============ 文件上传 (改进核心逻辑) ============
    
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
        
        # 记录上传开始
        logger.info("=" * 60)
        logger.info(f"开始上传文件: {file_info.original_name}")
        logger.info(f"  文件路径: {filepath}")
        logger.info(f"  文件大小: {file_info.size / 1024 / 1024:.2f} MB ({file_info.size} bytes)")
        logger.info(f"  MIME类型: {file_info.mime_type}")
        logger.info(f"  上传名称: {file_info.upload_name}")
        logger.info(f"  目标页面: {page_id}")
        logger.info(f"  是否伪装: {file_info.is_spoofed}")
        logger.info(f"  上传模式: {'小文件直传' if file_info.size <= SMALL_FILE_LIMIT else '分片上传'}")
        
        upload_start_time = time.time()
        
        def report(status: UploadStatus, uploaded: int = 0, 
                   part_current: int = 0, part_total: int = 0, retry: int = 0, message: str = ""):
            # 记录状态变化
            if status in [UploadStatus.RETRYING, UploadStatus.FAILED, UploadStatus.COMPLETED]:
                logger.info(f"[{file_info.original_name}] 状态: {status.value}, "
                           f"进度: {uploaded}/{file_info.size} ({uploaded*100/file_info.size:.1f}%), "
                           f"分片: {part_current}/{part_total}, 重试: {retry}")
                if message:
                    logger.info(f"[{file_info.original_name}] 消息: {message}")
            
            if progress_callback:
                progress_callback(UploadProgress(
                    filename=file_info.original_name,
                    uploaded=uploaded,
                    total=file_info.size,
                    status=status,
                    part_current=part_current,
                    part_total=part_total,
                    retry_count=retry,
                    message=message
                ))
        
        try:
            # 根据文件大小选择上传方式
            if file_info.size <= SMALL_FILE_LIMIT:
                result = self._upload_small_file(file_info, page_id, report)
            else:
                result = self._upload_large_file_improved(file_info, page_id, report)
            
            elapsed = time.time() - upload_start_time
            
            if result:
                speed = file_info.size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                logger.info(f"✓ 上传成功: {file_info.original_name}")
                logger.info(f"  耗时: {elapsed:.2f}秒")
                logger.info(f"  平均速度: {speed:.2f} MB/s")
            else:
                logger.error(f"✗ 上传失败: {file_info.original_name}")
                logger.error(f"  耗时: {elapsed:.2f}秒")
            
            logger.info("=" * 60)
            return result
                
        except Exception as e:
            elapsed = time.time() - upload_start_time
            logger.error(f"✗ 上传异常: {file_info.original_name}")
            logger.error(f"  异常类型: {type(e).__name__}")
            logger.error(f"  异常信息: {e}")
            logger.error(f"  耗时: {elapsed:.2f}秒")
            logger.info("=" * 60)
            report(UploadStatus.FAILED, message=str(e))
            return False
    
    def _upload_small_file(self, file_info: UploadFileInfo, page_id: str,
                           report: Callable) -> bool:
        """上传小文件 (<=20MB) - 单次上传"""
        logger.debug(f"[小文件上传] 开始: {file_info.original_name}")
        report(UploadStatus.UPLOADING, 0, 0, 1)
        
        # 1. 创建上传会话
        logger.debug(f"[小文件上传] 创建上传会话...")
        success, result = self._api_request("POST", "file_uploads", {
            "filename": file_info.upload_name,
            "content_type": file_info.mime_type
        })
        if not success:
            logger.error(f"[小文件上传] 创建上传会话失败: {result}")
            return False
        
        upload_id = result['id']
        logger.debug(f"[小文件上传] 会话ID: {upload_id}")
        
        # 2. 读取并上传文件内容
        logger.debug(f"[小文件上传] 读取文件内容...")
        with open(file_info.path, 'rb') as f:
            file_content = f.read()
        
        logger.debug(f"[小文件上传] 文件内容大小: {len(file_content)} bytes")
        report(UploadStatus.UPLOADING, file_info.size // 2, 1, 1)
        
        # 带无限重试的上传
        retry_count = 0
        upload_start = time.time()
        
        while True:
            logger.debug(f"[小文件上传] 发送文件数据 (尝试 {retry_count + 1})...")
            # 必须指定正确的 MIME 类型，否则会报 content type mismatch 错误
            success, result = self._api_request("POST", f"file_uploads/{upload_id}/send",
                files={'file': (file_info.upload_name, file_content, file_info.mime_type)}
            )
            if success:
                elapsed = time.time() - upload_start
                logger.debug(f"[小文件上传] 文件数据发送成功，耗时: {elapsed:.2f}s")
                break
            
            retry_count += 1
            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
            logger.warning(f"[小文件上传] 上传失败，{delay}秒后重试 (第{retry_count}次)")
            logger.warning(f"[小文件上传] 失败原因: {result}")
            report(UploadStatus.RETRYING, file_info.size // 2, 1, 1, retry_count, 
                   f"上传失败，重试中...")
            time.sleep(delay)
        
        report(UploadStatus.UPLOADING, file_info.size, 1, 1)
        
        # 3. 附加到页面
        logger.debug(f"[小文件上传] 附加文件到页面...")
        report(UploadStatus.ATTACHING, file_info.size, 1, 1)
        
        success = self._attach_file_to_page(upload_id, file_info, page_id)
        if not success:
            logger.error(f"[小文件上传] 附加文件到页面失败")
            return False
        
        report(UploadStatus.COMPLETED, file_info.size, 1, 1)
        logger.debug(f"[小文件上传] 完成: {file_info.original_name}")
        return True
    
    def _upload_large_file_improved(self, file_info: UploadFileInfo, page_id: str,
                                    report: Callable) -> bool:
        """
        上传大文件 (>20MB) - 改进的分片上传
        
        关键改进:
        1. 跟踪已上传的分片
        2. 会话失效时尝试恢复
        3. 只重试失败的分片
        4. 无限重试直到成功
        """
        num_parts = math.ceil(file_info.size / PART_SIZE)
        uploaded_parts: Set[int] = set()  # 已成功上传的分片
        
        logger.debug(f"[大文件上传] 开始: {file_info.original_name}")
        logger.debug(f"[大文件上传] 总分片数: {num_parts} (每片 {PART_SIZE/1024/1024:.1f}MB)")
        
        report(UploadStatus.UPLOADING, 0, 0, num_parts)
        
        # 1. 创建分片上传会话
        upload_id = None
        retry_count = 0
        session_create_start = time.time()
        
        logger.debug(f"[大文件上传] 创建分片上传会话...")
        
        while upload_id is None:
            success, result = self._api_request("POST", "file_uploads", {
                "filename": file_info.upload_name,
                "content_type": file_info.mime_type,
                "mode": "multi_part",
                "number_of_parts": num_parts
            })
            
            if success:
                upload_id = result['id']
                elapsed = time.time() - session_create_start
                logger.info(f"[大文件上传] 创建会话成功: {upload_id} (耗时 {elapsed:.2f}s)")
            else:
                retry_count += 1
                delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
                logger.warning(f"[大文件上传] 创建会话失败 (第{retry_count}次)，{delay}秒后重试")
                logger.warning(f"[大文件上传] 失败原因: {result}")
                report(UploadStatus.RETRYING, 0, 0, num_parts, retry_count, 
                       "创建上传会话失败，重试中...")
                time.sleep(delay)
        
        # 2. 分片上传 - 支持断点续传
        upload_round = 0
        with open(file_info.path, 'rb') as f:
            # 循环直到所有分片都上传成功
            while len(uploaded_parts) < num_parts:
                upload_round += 1
                logger.debug(f"[大文件上传] === 上传轮次 {upload_round} ===")
                
                # 检查会话状态
                report(UploadStatus.CHECKING, len(uploaded_parts) * PART_SIZE, 
                       len(uploaded_parts), num_parts, 0, "检查上传状态...")
                
                logger.debug(f"[大文件上传] 检查会话状态: {upload_id}")
                session_info = self._get_upload_session_status(upload_id)
                
                if session_info is None or session_info.status == 'archived':
                    # 会话失效，需要重新创建
                    logger.warning(f"[大文件上传] 会话已失效 (状态: {session_info.status if session_info else 'None'})")
                    logger.warning(f"[大文件上传] 已上传分片: {len(uploaded_parts)}/{num_parts}")
                    report(UploadStatus.RECOVERING, len(uploaded_parts) * PART_SIZE, 
                           len(uploaded_parts), num_parts, 0, "会话失效，重新创建...")
                    
                    retry_count = 0
                    upload_id = None
                    
                    while upload_id is None:
                        logger.debug(f"[大文件上传] 重新创建会话 (尝试 {retry_count + 1})...")
                        success, result = self._api_request("POST", "file_uploads", {
                            "filename": file_info.upload_name,
                            "content_type": file_info.mime_type,
                            "mode": "multi_part",
                            "number_of_parts": num_parts
                        })
                        
                        if success:
                            upload_id = result['id']
                            logger.info(f"[大文件上传] 重新创建会话成功: {upload_id}")
                            # 注意：重新创建会话后，之前的上传记录会丢失
                            # 但我们本地保存了uploaded_parts，可以跳过这些分片
                        else:
                            retry_count += 1
                            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
                            logger.warning(f"[大文件上传] 重新创建会话失败，{delay}秒后重试: {result}")
                            time.sleep(delay)
                    
                    # 重置会话信息
                    session_info = UploadSession(
                        upload_id=upload_id,
                        filename=file_info.upload_name,
                        num_parts=num_parts,
                        uploaded_parts=set(),  # 新会话，服务器端没有已上传的分片
                        status='active',
                        created_time=time.time()
                    )
                
                # 更新本地已上传分片记录（与服务器同步）
                # 注意：这里我们信任本地记录，因为即使服务器重置，Notion支持重复上传分片
                if session_info:
                    logger.debug(f"[大文件上传] 服务器已有 {len(session_info.uploaded_parts)} 个分片，本地记录 {len(uploaded_parts)} 个")
                
                # 找出未上传的分片
                pending_parts = set(range(1, num_parts + 1)) - uploaded_parts
                
                if not pending_parts:
                    logger.info(f"[大文件上传] 所有分片已上传完成")
                    break
                
                logger.info(f"[大文件上传] 待上传分片: {len(pending_parts)} 个 (已完成: {len(uploaded_parts)}/{num_parts})")
                
                # 上传每个未完成的分片
                for part_num in sorted(pending_parts):
                    # 读取分片数据
                    f.seek((part_num - 1) * PART_SIZE)
                    chunk = f.read(PART_SIZE)
                    chunk_size = len(chunk)
                    
                    logger.debug(f"[大文件上传] 准备分片 {part_num}/{num_parts}, 大小: {chunk_size} bytes")
                    
                    # 无限重试直到分片上传成功
                    part_retry_count = 0
                    part_uploaded = False
                    part_start_time = time.time()
                    
                    while not part_uploaded:
                        if part_retry_count > 0:
                            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** part_retry_count), MAX_RETRY_DELAY)
                            logger.info(f"[大文件上传] 分片 {part_num}/{num_parts} 重试 (第{part_retry_count}次，等待{delay}秒)")
                            report(UploadStatus.RETRYING, len(uploaded_parts) * PART_SIZE, 
                                   part_num, num_parts, part_retry_count,
                                   f"分片 {part_num} 上传失败，重试中...")
                            time.sleep(delay)
                        else:
                            logger.info(f"[大文件上传] 上传分片 {part_num}/{num_parts} ({chunk_size / 1024 / 1024:.1f}MB)")
                            report(UploadStatus.UPLOADING, len(uploaded_parts) * PART_SIZE, 
                                   part_num, num_parts, 0)
                        
                        # 尝试上传分片 - 必须指定正确的 MIME 类型
                        success, result = self._api_request("POST", f"file_uploads/{upload_id}/send",
                            files={'file': (file_info.upload_name, chunk, file_info.mime_type)},
                            data={'part_number': str(part_num)}
                        )
                        
                        if success:
                            part_uploaded = True
                            uploaded_parts.add(part_num)
                            part_elapsed = time.time() - part_start_time
                            part_speed = chunk_size / part_elapsed / 1024 / 1024 if part_elapsed > 0 else 0
                            logger.info(f"[大文件上传] ✓ 分片 {part_num}/{num_parts} 上传成功 "
                                       f"(耗时: {part_elapsed:.2f}s, 速度: {part_speed:.2f}MB/s)")
                            report(UploadStatus.UPLOADING, len(uploaded_parts) * PART_SIZE, 
                                   part_num, num_parts, 0)
                        else:
                            part_retry_count += 1
                            logger.warning(f"[大文件上传] ✗ 分片 {part_num} 上传失败 (第{part_retry_count}次)")
                            logger.warning(f"[大文件上传] 失败原因: {result}")
                            
                            # 检查会话是否仍然有效
                            if not self._is_session_valid(upload_id):
                                logger.warning(f"[大文件上传] 检测到会话失效，将在下一轮重新创建")
                                break  # 跳出当前分片上传，重新检查会话
        
        # 3. 完成分片上传
        logger.info(f"[大文件上传] 所有分片上传完成，开始完成上传流程")
        report(UploadStatus.COMPLETING, file_info.size, num_parts, num_parts)
        
        retry_count = 0
        complete_start = time.time()
        while True:
            logger.debug(f"[大文件上传] 调用 complete API (尝试 {retry_count + 1})...")
            success, result = self._api_request("POST", f"file_uploads/{upload_id}/complete")
            if success:
                complete_elapsed = time.time() - complete_start
                logger.info(f"[大文件上传] ✓ 完成上传成功 (耗时: {complete_elapsed:.2f}s)")
                break
            
            retry_count += 1
            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
            logger.warning(f"[大文件上传] 完成上传失败 (第{retry_count}次)，{delay}秒后重试")
            logger.warning(f"[大文件上传] 失败原因: {result}")
            report(UploadStatus.RETRYING, file_info.size, num_parts, num_parts, retry_count,
                   "完成上传失败，重试中...")
            time.sleep(delay)
        
        # 4. 附加到页面
        logger.debug(f"[大文件上传] 附加文件到页面: {page_id}")
        report(UploadStatus.ATTACHING, file_info.size, num_parts, num_parts)
        
        retry_count = 0
        attach_start = time.time()
        while True:
            success = self._attach_file_to_page(upload_id, file_info, page_id)
            if success:
                attach_elapsed = time.time() - attach_start
                logger.info(f"[大文件上传] ✓ 附加文件成功 (耗时: {attach_elapsed:.2f}s)")
                break
            
            retry_count += 1
            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** retry_count), MAX_RETRY_DELAY)
            logger.warning(f"[大文件上传] 附加文件失败 (第{retry_count}次)，{delay}秒后重试")
            report(UploadStatus.RETRYING, file_info.size, num_parts, num_parts, retry_count,
                   "附加文件失败，重试中...")
            time.sleep(delay)
        
        report(UploadStatus.COMPLETED, file_info.size, num_parts, num_parts)
        logger.debug(f"[大文件上传] 完成: {file_info.original_name}")
        return True
    
    def _attach_file_to_page(self, upload_id: str, file_info: UploadFileInfo, 
                             page_id: str) -> bool:
        """将上传的文件附加到页面"""
        block_type = file_info.get_block_type()
        caption = [{"type": "text", "text": {"content": file_info.original_name}}]
        
        logger.debug(f"[附加文件] 文件: {file_info.original_name}")
        logger.debug(f"[附加文件] Block类型: {block_type}")
        logger.debug(f"[附加文件] 上传ID: {upload_id}")
        logger.debug(f"[附加文件] 目标页面: {page_id}")
        
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
            logger.error(f"[附加文件] 失败: {result}")
            return False
        
        logger.debug(f"[附加文件] 成功")
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