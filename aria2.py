# Notion-Files-Management - Aria2下载服务模块 (优化版)
# Copyright (C) 2025 Ruibin_Ningh & Zyx_2012
# License: GPL v3

import os
import re
import time
import uuid
import socket
import logging
import webbrowser
import subprocess
from subprocess import DEVNULL
from typing import List, Tuple, Optional, Dict

import requests

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """清理文件名"""
    if not name:
        return "unnamed_file"
    
    # 移除非法字符和控制字符
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name)
    
    # 截断过长文件名
    if len(name) > 200:
        base, ext = os.path.splitext(name)
        name = base[:200 - len(ext)] + ext
    
    return name.strip() or "unnamed_file"


class Aria2Client:
    """Aria2 RPC客户端"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 6800, token: str = ""):
        self.url = f"http://{host}:{port}/jsonrpc"
        self.token = f"token:{token}" if token else ""
    
    def _call(self, method: str, params: list = None) -> Optional[dict]:
        """发送RPC请求"""
        request_params = [self.token] + (params or []) if self.token else (params or [])
        
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": request_params
        }
        
        try:
            resp = requests.post(self.url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            
            if "error" in result:
                raise Exception(result['error']['message'])
            return result.get("result")
            
        except Exception as e:
            logger.error(f"Aria2 RPC调用失败: {e}")
            return None
    
    def is_connected(self) -> bool:
        """检查连接"""
        stat = self._call("aria2.getGlobalStat")
        return stat is not None
    
    def get_version(self) -> Optional[dict]:
        """获取版本信息"""
        return self._call("aria2.getVersion")
    
    def get_status(self, gid: str) -> Optional[dict]:
        """获取任务状态"""
        return self._call("aria2.tellStatus", [gid])
    
    def add_download(self, url: str, filename: str, save_dir: str = "downloads") -> Optional[str]:
        """添加下载任务"""
        params = [
            [url],
            {"out": sanitize_filename(filename), "dir": os.path.abspath(save_dir)}
        ]
        return self._call("aria2.addUri", params)
    
    def add_downloads_batch(self, file_urls: List[Tuple[str, str]], save_dir: str = "downloads") -> List[str]:
        """批量添加下载任务"""
        gids = []
        for filename, url in file_urls:
            gid = self.add_download(url, filename, save_dir)
            if gid:
                gids.append(gid)
                print(f"✅ 已添加: {sanitize_filename(filename)}")
            else:
                print(f"❌ 添加失败: {filename}")
            time.sleep(0.1)
        return gids
    
    def add_downloads_queued(self, file_urls: List[Tuple[str, str]], save_dir: str = "downloads",
                            max_active: int = 3, check_interval: int = 10) -> List[str]:
        """
        队列式添加下载任务
        
        Args:
            file_urls: [(filename, url), ...]
            save_dir: 保存目录
            max_active: 最大并发数
            check_interval: 检查间隔(秒)
        """
        gids = []
        active: Dict[str, Tuple[str, float]] = {}  # gid -> (filename, start_time)
        
        print(f"🎯 开始队列下载 (共{len(file_urls)}个, 并发{max_active})")
        
        for i, (filename, url) in enumerate(file_urls):
            # 等待队列有空位
            while len(active) >= max_active:
                self._cleanup_completed(active)
                if len(active) >= max_active:
                    time.sleep(1)
            
            # 添加任务
            clean_name = sanitize_filename(filename)
            print(f"📥 [{i+1}/{len(file_urls)}] {clean_name}")
            
            gid = self.add_download(url, clean_name, save_dir)
            if gid:
                gids.append(gid)
                active[gid] = (clean_name, time.time())
            
            time.sleep(0.1)
        
        # 等待所有任务完成
        print("📊 等待任务完成...")
        timeout = 3600  # 1小时超时
        start = time.time()
        
        while active and (time.time() - start) < timeout:
            self._cleanup_completed(active)
            if active:
                time.sleep(check_interval)
        
        if active:
            print(f"⚠️ 超时，还有{len(active)}个任务未完成")
        else:
            print("🎉 所有任务已完成！")
        
        return gids
    
    def _cleanup_completed(self, active: Dict[str, Tuple[str, float]]):
        """清理已完成的任务"""
        for gid in list(active.keys()):
            status = self.get_status(gid)
            if status and status.get('status') in ['complete', 'error', 'removed']:
                filename, start_time = active.pop(gid)
                elapsed = time.time() - start_time
                icon = "✅" if status['status'] == 'complete' else "❌"
                print(f"{icon} {filename} ({elapsed:.1f}秒)")


class Aria2Server:
    """Aria2 RPC服务器管理"""
    
    def __init__(self, aria2_path: str = "aria2c.exe", port: int = 6800, token: str = ""):
        self.aria2_path = aria2_path
        self.port = port
        self.token = token
        self.process = None
    
    def start(self, max_concurrent: int = 3, max_conn_per_server: int = 16) -> bool:
        """启动服务器"""
        # 检查可执行文件
        if not os.path.exists(self.aria2_path):
            print(f"❌ 找不到aria2c: {self.aria2_path}")
            return False
        
        # 检查端口
        if self._is_port_in_use():
            print(f"❌ 端口{self.port}已被占用")
            return False
        
        # 构建命令
        cmd = [
            self.aria2_path,
            "--enable-rpc",
            "--rpc-listen-all=false",
            "--rpc-allow-origin-all=true",
            f"--rpc-listen-port={self.port}",
            f"--max-concurrent-downloads={max_concurrent}",
            f"--max-connection-per-server={max_conn_per_server}",
            "--continue=true",
            "--disk-cache=64M",
            "--file-allocation=none",
            f"--log={os.path.join(os.getcwd(), 'aria2.log')}",
            "--log-level=warn",
        ]
        
        if self.token:
            cmd.append(f"--rpc-secret={self.token}")
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=DEVNULL,
                stderr=DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
            # 等待启动
            time.sleep(3)
            
            if self.process.poll() is not None:
                print("❌ Aria2进程异常退出")
                return False
            
            # 验证连接
            client = Aria2Client(port=self.port, token=self.token)
            for _ in range(3):
                if client.is_connected():
                    print(f"✅ Aria2服务器已启动 (端口{self.port})")
                    return True
                time.sleep(1)
            
            print("❌ 无法连接到Aria2服务器")
            self.stop()
            return False
            
        except Exception as e:
            print(f"❌ 启动失败: {e}")
            return False
    
    def stop(self):
        """停止服务器"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                print("✅ Aria2服务器已停止")
            except subprocess.TimeoutExpired:
                self.process.kill()
                print("⚠️ Aria2服务器被强制终止")
            finally:
                self.process = None
    
    def is_running(self) -> bool:
        """检查是否运行中"""
        if not self.process or self.process.poll() is not None:
            return False
        client = Aria2Client(port=self.port, token=self.token)
        return client.is_connected()
    
    def _is_port_in_use(self) -> bool:
        """检查端口是否被占用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', self.port)) == 0
    
    def open_ariang(self) -> bool:
        """打开AriaNG界面"""
        ariang_path = os.path.join(os.getcwd(), "AriaNG.html")
        if os.path.exists(ariang_path):
            webbrowser.open(f"file://{ariang_path}")
            return True
        print(f"❌ AriaNG.html不存在")
        return False


# 兼容旧API的别名
Aria2LocalClient = Aria2Client
Aria2RPCServer = Aria2Server
