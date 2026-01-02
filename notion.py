# Notion-Files-Management - Notion API封装模块
# Copyright (C) 2025 Ruibin_Ningh & Zyx_2012
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

import os
import requests
import asyncio
import aiohttp
import aiofiles
from dotenv import load_dotenv
import logging
import json
import time
import math
import mimetypes
import subprocess
import threading
import shutil
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple, Callable
import collections
import hashlib
from pathlib import Path
import random
import base64
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 现代化UI库
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.style import Style
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RateLimiter:
    """令牌桶算法限流器"""
    def __init__(self, rate):
        self.rate = rate
        self.tokens = rate
        self.last_update = time.time()
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now
            if self.tokens < 1:
                time.sleep((1 - self.tokens) / self.rate)
                self.tokens = 0
            else:
                self.tokens -= 1

class NotionFileManager:
    def __init__(self,token:str,version:str,base_url:str="https://api.notion.com/v1"):
        """
        初始化NotionFileManager类的实例
        """
        load_dotenv()
        self.token = token
        self.version = version
        self.base_url = base_url
        self.current_page_id = None  # 当前操作的页面ID
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
            "Content-Type": "application/json"
        }

        # 上传相关配置
        self.upload_config = {
            "min_chunk_size": 5 * 1024 * 1024,  # 5MB分片
            "max_workers": 3,  # 最大并发数
            "max_chunk_retries": 20,  # 分片最大重试次数
            "rate_limit": 2.8,  # API请求频率限制
        }

        # 设置会话和重试机制
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version
            # 移除自定义User-Agent，让requests使用默认值
        })
        # 启用基本的自动重试，但只重试连接错误
        basic_retries = Retry(
            total=2,  # 只重试2次
            connect=2,  # 只重试连接错误
            read=0,  # 不重试读取错误
            status=0,  # 不重试HTTP状态错误
            backoff_factor=0.5,
            raise_on_status=False
        )
        self.session.mount('https://', HTTPAdapter(max_retries=basic_retries))

        # 非常保守的限流器 - 大幅降低请求频率到0.5 req/s
        self.rate_limiter = RateLimiter(0.5)  # 每2秒最多1个请求

        # 下载相关配置
        self.download_config = {
            "chunk_size": 1024 * 1024,  # 1MB下载块
            "max_workers": 4,  # 下载并发数
            "timeout": 30,  # 请求超时时间
        }

        # 文件链接缓存配置
        self.link_cache_config = {
            "cache_expiry_seconds": 40 * 60,  # 40分钟缓存过期
            "force_refresh_threshold": 30 * 60,  # 30分钟后显示刷新提示
        }

        # 多页面文件链接缓存: {page_id: {"data": [], "timestamp": float, "expiry": float}}
        self._page_caches = {}

    def set_page(self, page_id: str):
        """设置当前操作的页面ID"""
        if self.current_page_id != page_id:
            # 页面切换时清除缓存
            self.clear_cache()
            self.current_page_id = page_id
            logger.info(f"已切换到页面: {page_id}")

    def _is_cache_expired(self, page_id: str = None) -> bool:
        """检查指定页面的缓存是否过期"""
        if page_id is None:
            page_id = self.current_page_id
        if not page_id or page_id not in self._page_caches:
            return True
        cache_info = self._page_caches[page_id]
        return time.time() - cache_info["timestamp"] > self.link_cache_config["cache_expiry_seconds"]

    def _should_warn_cache_old(self, page_id: str = None) -> bool:
        """检查是否应该警告指定页面的缓存即将过期"""
        if page_id is None:
            page_id = self.current_page_id
        if not page_id or page_id not in self._page_caches:
            return False
        cache_info = self._page_caches[page_id]
        return time.time() - cache_info["timestamp"] > self.link_cache_config["force_refresh_threshold"]

    def _get_cache_age(self, page_id: str = None) -> float:
        """获取指定页面的缓存年龄（秒）"""
        if page_id is None:
            page_id = self.current_page_id
        if not page_id or page_id not in self._page_caches:
            return float('inf')
        cache_info = self._page_caches[page_id]
        return time.time() - cache_info["timestamp"]

    def _update_cache(self, file_list: list, page_id: str = None):
        """更新指定页面的缓存"""
        if page_id is None:
            page_id = self.current_page_id
        if not page_id:
            return

        current_time = time.time()
        self._page_caches[page_id] = {
            "data": file_list,
            "timestamp": current_time,
            "expiry": current_time + self.link_cache_config["cache_expiry_seconds"]
        }
        logger.info(f"页面 {page_id} 的文件链接缓存已更新，共 {len(file_list)} 个文件")

    def clear_cache(self, page_id: str = None):
        """清除指定页面的缓存"""
        if page_id is None:
            # 清除所有页面的缓存
            self._page_caches.clear()
            logger.info("所有页面的文件链接缓存已清除")
        elif page_id in self._page_caches:
            del self._page_caches[page_id]
            logger.info(f"页面 {page_id} 的文件链接缓存已清除")

    def _get_children(self, block_id, max_retries=3):
        """
        获取指定 block 的子节点，并过滤仅保留文件类型的块
        添加重试机制和更好的错误处理
        """
        children = []
        cursor = None
        FILE_TYPES = ["file", "image", "video", "pdf", "audio"]

        for attempt in range(max_retries):
            try:
                logger.info(f"正在获取页面子节点 (尝试 {attempt + 1}/{max_retries})...")

                while True:
                    url = f"{self.base_url}/blocks/{block_id}/children"
                    params = {"page_size": 25}  # 进一步减少到25，避免大数据请求
                    if cursor:
                        params["start_cursor"] = cursor

                    # 添加小的请求间隔，避免过于频繁的请求
                    if attempt > 0 or cursor:  # 不是第一次请求时添加间隔
                        time.sleep(0.5)

                    response = self.session.get(url, params=params, timeout=30)
                    response.raise_for_status()

                    data = response.json()
                    results = data.get("results", [])

                    for block in results:
                        if block.get("type") in FILE_TYPES:
                            children.append(block)

                    if not data.get("has_more"):
                        break
                    cursor = data.get("next_cursor")

                logger.info(f"成功获取 {len(children)} 个文件块")
                return children

            except requests.exceptions.ConnectionError as e:
                logger.warning(f"网络连接错误 (尝试 {attempt + 1}/{max_retries}): {str(e)[:100]}...")
                if attempt < max_retries - 1:
                    wait_time = min(30, 2 ** (attempt + 1))  # 指数退避: 2s, 4s, 8s, 16s, 30s
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"网络连接失败，已达到最大重试次数: {e}")
                    return []

            except requests.exceptions.Timeout as e:
                logger.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 3 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"请求超时，已达到最大重试次数: {e}")
                    return []

            except requests.exceptions.HTTPError as e:
                # 获取响应状态码
                status_code = getattr(e.response, 'status_code', None)
                if status_code == 429:  # Too Many Requests
                    logger.warning(f"API请求频率限制 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        wait_time = 10 * (attempt + 1)  # 更长的等待时间: 10s, 20s, 30s
                        logger.info(f"等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"API频率限制，已达到最大重试次数")
                        return []
                else:
                    logger.error(f"HTTP错误 {status_code}: {e}")
                    return []

            except Exception as e:
                logger.error(f"获取并过滤子节点失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 3 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"未知错误，已达到最大重试次数: {e}")
                    return []

        return children
    def file_list(self, force_refresh: bool = False) -> list:
        """
        获取并返回指定页面的所有文件信息列表
        返回格式: [["name", "url", "url加载的时间"], ...]

        Args:
            force_refresh: 是否强制刷新缓存
        """
        if not self.current_page_id:
            raise ValueError("请先设置页面ID (使用 set_page 方法)")

        # 检查是否需要刷新缓存
        if force_refresh or self._is_cache_expired():
            logger.info(f"正在刷新页面 {self.current_page_id} 的文件链接缓存...")
            blocks = self._get_children(self.current_page_id)
            result_list = []
            load_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for block in blocks:
                try:
                    b_type = block.get("type")
                    content = block.get(b_type, {})
                    name = content.get("name")
                    file_type = content.get("type")
                    url = ""
                    if file_type == "file":
                        url = content["file"].get("url", "")
                    elif file_type == "external":
                        url = content["external"].get("url", "")
                    if not name and url:
                        name = url.split('/')[-1].split('?')[0]

                    if not name:
                        name = "未命名文件"
                    result_list.append([name, url, load_time])

                except Exception as e:
                    logger.error(f"处理 Block {block.get('id')} 失败: {e}")
                    continue

            # 更新缓存
            self._update_cache(result_list)
            return result_list

        else:
            # 使用缓存
            cache_age = self._get_cache_age()
            if self._should_warn_cache_old():
                logger.warning(".0f" % (cache_age / 60))
            cache_info = self._page_caches.get(self.current_page_id, {})
            return cache_info.get("data", []).copy()

    def _api_request(self, method, url, max_retries=3, **kwargs):
        """统一的API请求方法，包含限流和错误处理"""
        for attempt in range(max_retries):
            try:
                self.rate_limiter.wait()
                resp = self.session.request(method, url, timeout=(10, 60), **kwargs)

                # 检查特殊的状态码
                if resp.status_code == 400:
                    err = resp.text.lower()
                    if "status" in err or "pending" in err:
                        raise BlockingIOError("SessionInvalid")

                # 检查频率限制
                if resp.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                        logger.warning(f"API请求频率限制，等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        resp.raise_for_status()

                resp.raise_for_status()
                return resp

            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"网络连接错误，等待 {wait_time} 秒后重试: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"网络连接失败，已达到最大重试次数: {e}")
                    raise

            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    wait_time = 3 ** attempt  # 更长的等待时间: 1s, 3s, 9s
                    logger.warning(f"请求超时，等待 {wait_time} 秒后重试: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"请求超时，已达到最大重试次数: {e}")
                    raise

            except requests.exceptions.HTTPError as e:
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 429:  # Too Many Requests
                        if attempt < max_retries - 1:
                            wait_time = 10 * (attempt + 1)  # 更长的等待时间: 10s, 20s, 30s
                            logger.warning(f"API请求频率限制，等待 {wait_time} 秒后重试...")
                            time.sleep(wait_time)
                            continue  # 重试
                        else:
                            logger.error(f"API频率限制，已达到最大重试次数")
                            raise
                    else:
                        logger.error(f"HTTP错误 {status_code}: {e}")
                        raise
                else:
                    logger.error(f"HTTP错误: {e}")
                    raise

            except BlockingIOError:
                # Session失效，不重试，直接抛出
                raise

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 3 ** attempt
                    logger.warning(f"API请求失败，等待 {wait_time} 秒后重试: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API请求失败，已达到最大重试次数: {e}")
                    raise

    def _get_upload_strategy(self, filepath):
        """获取文件上传策略（后缀伪装等）"""
        fsize = os.path.getsize(filepath)
        fname = os.path.basename(filepath)
        name, ext = os.path.splitext(fname)

        # 白名单：这些扩展名可以直接上传，不需要伪装
        whitelist = {
            # 音频格式
            '.aac', '.adts', '.mid', '.midi', '.mp3', '.mpga', '.m4a', '.m4b',
            '.oga', '.ogg', '.wav', '.wma',
            # 视频格式
            '.amv', '.asf', '.wmv', '.avi', '.f4v', '.flv', '.gifv', '.m4v',
            '.mp4', '.mkv', '.webm', '.mov', '.qt', '.mpeg',
            # 图片格式
            '.gif', '.heic', '.jpeg', '.jpg', '.png', '.svg', '.tif', '.tiff',
            '.webp', '.ico',
            # 文档格式
            '.pdf', '.txt', '.json', '.doc', '.dot', '.docx', '.dotx',
            '.xls', '.xlt', '.xla', '.xlsx', '.xltx',
            '.ppt', '.pot', '.pps', '.ppa', '.pptx', '.potx'
        }

        # 后缀伪装：对于不支持的格式，伪装成.txt或.bin
        if ext.lower() not in whitelist:
            upload_name = f"{fname}.txt"  # 伪装成txt文件
            mime = "text/plain"
        else:
            upload_name = fname
            mime = mimetypes.guess_type(filepath)[0] or "application/octet-stream"

        # 计算分片大小：确保不超过990个分片（Notion限制）
        chunk_size = max(self.upload_config["min_chunk_size"], math.ceil(fsize / 990))
        parts = max(1, math.ceil(fsize / chunk_size))

        return fname, upload_name, mime, fsize, chunk_size, parts

    def upload_file(self, filepath, progress_callback=None):
        """
        上传单个文件到Notion
        支持分片上传、后缀伪装、三级异常防御
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"文件不存在: {filepath}")

        # 获取上传策略
        fname, up_name, mime, fsize, chunk_size, parts = self._get_upload_strategy(filepath)

        logger.info(f"开始上传文件: {fname} ({fsize/1024/1024:.1f}MB), 分片数: {parts}")

        session_uploaded = 0
        start_time = time.time()

        while True:
            try:
                # 1. 初始化上传会话
                if progress_callback:
                    progress_callback(fname, 0, fsize, "申请上传令牌...")

                resp = self._api_request("POST", f"{self.base_url}/file_uploads",
                    json={
                        "filename": up_name,
                        "content_type": mime,
                        "mode": "multi_part",
                        "number_of_parts": parts
                    })
                upload_data = resp.json()
                upload_id = upload_data["id"]

                # 2. 分片上传循环
                with open(filepath, "rb") as f:
                    for part_num in range(1, parts + 1):
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break

                        # 分片重试循环
                        for attempt in range(self.upload_config["max_chunk_retries"]):
                            try:
                                status = f"上传分片 {part_num}/{parts}"
                                if attempt > 0:
                                    status += f" (重试 {attempt})"

                                if progress_callback:
                                    progress_callback(fname, session_uploaded, fsize, status)

                                # 上传分片
                                self._api_request("POST", f"{self.base_url}/file_uploads/{upload_id}/send",
                                    files={"file": (up_name, chunk, mime)},
                                    data={"part_number": part_num})

                                session_uploaded += len(chunk)
                                break

                            except BlockingIOError:
                                raise  # 会话失效，重新开始
                            except Exception as e:
                                logger.warning(f"分片 {part_num} 上传失败 (尝试 {attempt+1}): {str(e)[:50]}")
                                if attempt < self.upload_config["max_chunk_retries"] - 1:
                                    # 指数退避：1s, 2s, 4s, 8s, 16s, 32s, 60s
                                    delay = min(60, 2 ** attempt)
                                    time.sleep(delay)
                                else:
                                    raise Exception(f"分片 {part_num} 重试失败")

                # 3. 完成上传
                if progress_callback:
                    progress_callback(fname, session_uploaded, fsize, "云端合成中...")

                self._api_request("POST", f"{self.base_url}/file_uploads/{upload_id}/complete", json={})

                # 4. 挂载到页面
                if progress_callback:
                    progress_callback(fname, fsize, fsize, "挂载到页面...")

                self._api_request("PATCH", f"{self.base_url}/blocks/{self.current_page_id}/children",
                    json={
                        "children": [{
                            "object": "block",
                            "type": "file",
                            "file": {
                                "type": "file_upload",
                                "file_upload": {"id": upload_id},
                                "caption": [{"type": "text", "text": {"content": fname}}]
                            }
                        }]
                    })

                # 挂载完成后发送完成状态
                if progress_callback:
                    progress_callback(fname, fsize, fsize, "上传完成")

                elapsed = time.time() - start_time
                speed = fsize / elapsed / 1024 / 1024 if elapsed > 0 else 0
                logger.info(f"上传完成: {fname} ({fsize/1024/1024:.1f}MB, {speed:.1f}MB/s)")
                return True

            except BlockingIOError:
                logger.warning(f"会话失效，重新开始上传: {fname}")
                session_uploaded = 0
                time.sleep(3)  # 会话重建延迟
            except Exception as e:
                logger.error(f"上传失败: {fname} - {str(e)}")
                session_uploaded = 0
                time.sleep(5)  # 链路重启延迟

    def upload_files_batch(self, filepaths, progress_callback=None):
        """批量上传文件"""
        if not filepaths:
            return []

        results = []
        for filepath in filepaths:
            try:
                success = self.upload_file(filepath, progress_callback)
                results.append((filepath, success))
            except Exception as e:
                logger.error(f"上传失败: {filepath} - {e}")
                results.append((filepath, False))

        return results

    async def download_file(self, file_info, save_path, progress_callback=None):
        """
        下载单个文件
        file_info: (name, url, load_time)
        """
        name, url, _ = file_info

        # 刷新下载链接（防止过期）
        try:
            fresh_url = await self._refresh_download_url(name, url)
        except Exception as e:
            logger.warning(f"无法刷新下载链接，使用原有链接: {e}")
            fresh_url = url

        save_file = os.path.join(save_path, name)
        os.makedirs(save_path, exist_ok=True)

        # 检查是否已存在断点续传文件
        temp_file = f"{save_file}.downloading"
        downloaded_size = 0
        if os.path.exists(temp_file):
            downloaded_size = os.path.getsize(temp_file)

        headers = {}
        if downloaded_size > 0:
            headers['Range'] = f'bytes={downloaded_size}-'

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(fresh_url, headers=headers) as response:
                    if response.status not in [200, 206]:
                        raise Exception(f"HTTP {response.status}")

                    total_size = int(response.headers.get('Content-Length', 0)) + downloaded_size

                    with open(temp_file, 'ab' if downloaded_size > 0 else 'wb') as f:
                        downloaded_in_session = 0
                        async for chunk in response.content.iter_chunked(self.download_config["chunk_size"]):
                            if chunk:
                                f.write(chunk)
                                downloaded_in_session += len(chunk)
                                current_size = downloaded_size + downloaded_in_session

                                if progress_callback:
                                    progress_callback(name, current_size, total_size,
                                                    f"下载中... ({current_size/1024/1024:.1f}MB)")

                    # 下载完成，重命名文件
                    if os.path.exists(save_file):
                        os.remove(save_file)
                    os.rename(temp_file, save_file)

                    # 恢复原始文件名（如果有伪装后缀）
                    if save_file.endswith('.txt') and not name.endswith('.txt'):
                        # 检查是否为伪装文件，需要进一步的逻辑来判断
                        pass

                    logger.info(f"下载完成: {name}")
                    return True

        except Exception as e:
            logger.error(f"下载失败: {name} - {e}")
            return False

    async def _refresh_download_url(self, name, original_url):
        """刷新下载链接"""
        # 通过API重新获取文件块信息来刷新URL
        # 这里需要根据文件名找到对应的block
        try:
            children = self._get_children(self.current_page_id)
            for block in children:
                if block.get("type") in ["file", "image", "video", "pdf", "audio"]:
                    b_type = block.get("type")
                    content = block.get(b_type, {})
                    block_name = content.get("name", "")

                    # 简单匹配文件名
                    if block_name == name or name in block_name:
                        if b_type == "file":
                            return content["file"].get("url", original_url)
                        elif b_type == "external":
                            return content["external"].get("url", original_url)

            return original_url
        except Exception as e:
            logger.warning(f"刷新下载链接失败: {e}")
            return original_url

    async def download_files_batch(self, file_indices, save_path, progress_callback=None):
        """批量下载文件"""
        files = self.file_list()
        if not files:
            return []

        # 选择要下载的文件
        selected_files = []
        for idx in file_indices:
            if 1 <= idx <= len(files):
                selected_files.append(files[idx-1])

        if not selected_files:
            return []

        results = []
        for file_info in selected_files:
            try:
                success = await self.download_file(file_info, save_path, progress_callback)
                results.append((file_info[0], success))
            except Exception as e:
                logger.error(f"下载失败: {file_info[0]} - {e}")
                results.append((file_info[0], False))

        return results

class Aria2Downloader:
    """Aria2高速下载器"""
    def __init__(self):
        self.aria2_path = self._find_aria2()

    def _find_aria2(self):
        """查找aria2c可执行文件"""
        # 检查系统PATH
        if shutil.which("aria2c"):
            return "aria2c"

        # 检查当前目录
        if os.path.exists("aria2c.exe"):
            return "aria2c.exe"

        return None

    def is_available(self):
        """检查Aria2是否可用"""
        return self.aria2_path is not None

    def download_files(self, file_urls, save_path, progress_callback=None):
        """
        使用Aria2批量下载文件
        file_urls: [(filename, url), ...]
        """
        if not self.is_available():
            raise Exception("Aria2不可用")

        os.makedirs(save_path, exist_ok=True)

        # 创建Aria2下载列表文件
        aria2_input = os.path.join(save_path, "aria2_input.txt")

        try:
            with open(aria2_input, 'w', encoding='utf-8') as f:
                for filename, url in file_urls:
                    f.write(f"{url}\n")
                    f.write(f"  out={filename}\n")
                    f.write(f"  dir={save_path}\n")
                    f.write("\n")  # 空行分隔任务

            # 验证文件是否创建成功
            if not os.path.exists(aria2_input):
                raise Exception(f"无法创建Aria2输入文件: {aria2_input}")

            logger.info(f"Aria2输入文件已创建: {aria2_input}")

            # 构建Aria2命令
            cmd = [
                self.aria2_path,
                "--input-file=" + aria2_input,
                "--max-concurrent-downloads=3",  # 降低并发数
                "--split=3",
                "--min-split-size=1M",
                "--max-connection-per-server=3",
                "--continue=true",
                "--allow-overwrite=true",
                "--quiet=false",
                "--summary-interval=1",
                "--log=" + os.path.join(save_path, "aria2.log"),  # 添加日志文件
                "--log-level=info"
            ]

            logger.info(f"执行Aria2命令: {' '.join(cmd)}")

            # 执行下载
            process = subprocess.Popen(cmd, cwd=save_path)
            process.wait()

            if process.returncode == 0:
                logger.info("Aria2下载完成")
                return True
            else:
                # 读取日志文件获取更多信息
                log_file = os.path.join(save_path, "aria2.log")
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        log_content = f.read()
                    logger.error(f"Aria2日志内容:\n{log_content}")

                raise Exception(f"Aria2下载失败，返回码: {process.returncode}")

        except Exception as e:
            logger.error(f"Aria2下载异常: {e}")
            raise
        finally:
            # 清理临时文件
            try:
                if os.path.exists(aria2_input):
                    os.remove(aria2_input)
                log_file = os.path.join(save_path, "aria2.log")
                if os.path.exists(log_file):
                    os.remove(log_file)
            except:
                pass

class IDMExporter:
    """IDM任务文件导出器"""
    def __init__(self):
        pass

    def export_tasks(self, file_urls, save_path):
        """
        导出IDM .ef2任务文件
        file_urls: [(filename, url), ...]
        """
        if not file_urls:
            return None

        os.makedirs(save_path, exist_ok=True)
        ef2_file = os.path.join(save_path, "idm_tasks.ef2")

        try:
            with open(ef2_file, 'w', encoding='utf-8') as f:
                for filename, url in file_urls:
                    # 智能提取referer
                    referer = self._extract_referer(url)

                    # IDM任务文件格式（参考GitHub release下载格式）
                    f.write("<\n")
                    f.write(f"{url}\n")
                    f.write(f"referer: {referer}\n")
                    f.write("User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0\n")
                    f.write(">\n")

            logger.info(f"IDM任务文件已导出: {ef2_file} ({len(file_urls)} 个任务)")
            return ef2_file

        except Exception as e:
            logger.error(f"导出IDM任务文件失败: {e}")
            return None

    def _extract_referer(self, url):
        """
        从URL智能提取referer
        """
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)

            # GitHub release assets
            if "github-production-release-asset" in url:
                return "https://github.com"

            # GitHubusercontent
            if "githubusercontent.com" in url:
                return "https://github.com"

            # 其他域名直接使用协议+域名
            if parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

            return ""

        except Exception:
            return ""

if __name__ == "__main__":
    load_dotenv()
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    NOTION_VERSION = os.getenv("NOTION_VERSION")
    NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
    NOTION_URL= os.getenv("NOTION_URL","https://api.notion.com/v1")
    notion_manager = NotionFileManager(NOTION_TOKEN, NOTION_VERSION, NOTION_PAGE_ID,NOTION_URL)
    children = notion_manager._get_children(NOTION_PAGE_ID)
    print(notion_manager.file_list())
