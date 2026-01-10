# Notion-Files-Management - Aria2下载服务模块
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

import requests
import json
import uuid
import os
import subprocess
import time
import webbrowser
import re
from typing import List, Tuple, Optional
from subprocess import DEVNULL

def sanitize_filename(name):
    """清理文件名，移除Windows非法字符和过长问题"""
    if not name:
        return "unnamed_file"

    # 1. 去除 Windows 非法字符
    name = re.sub(r'[\\/:*?"<>|]', '_', name)

    # 2. 去除控制字符
    name = re.sub(r'[\x00-\x1f]', '', name)

    # 3. 截断过长文件名 (保留后缀)
    if len(name) > 200:
        base, ext = os.path.splitext(name)
        name = base[:200-len(ext)] + ext

    # 4. 确保不为空
    name = name.strip()
    if not name:
        name = "unnamed_file"

    return name

class Aria2LocalClient:
    def __init__(self, host="127.0.0.1", port=6800, token="", server=None):
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}/jsonrpc"
        self.token = f"token:{token}" if token else ""
        self.server = server  # 关联的Aria2RPCServer实例

    def is_connected(self):
        """检查是否能连接到Aria2"""
        try:
            stat = self.get_global_stat()
            return stat is not None and isinstance(stat, dict)
        except:
            return False

    def is_running(self):
        """检查Aria2服务器是否正在运行"""
        if self.server:
            return self.server.is_running()
        else:
            # 如果没有关联的服务器实例，尝试通过连接测试
            return self.is_connected()

    def stop_server(self):
        """停止关联的Aria2服务器"""
        if self.server:
            self.server.stop_server()
        else:
            print("⚠️ 没有关联的Aria2服务器实例，无法停止")

    def start_server(self, max_concurrent_downloads=3, max_connection_per_server=16):
        """启动关联的Aria2服务器"""
        if self.server:
            return self.server.start_server(max_concurrent_downloads, max_connection_per_server)
        else:
            print("⚠️ 没有关联的Aria2服务器实例，无法启动")
            return False

    def get_version(self):
        """获取Aria2版本信息"""
        return self._send_request("aria2.getVersion")

    def _send_request(self, method, params=None):
        """通用请求发送逻辑"""
        # 构建params数组
        if self.token:
            # 如果有token，将其放在params数组的开头
            request_params = [self.token] + (params or [])
        else:
            # 如果没有token，直接使用params
            request_params = params or []

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()), # 唯一的请求ID
            "method": method,
            "params": request_params
        }
        
        try:
            response = requests.post(self.url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                raise Exception(f"Aria2 Error: {result['error']['message']}")
            return result.get("result")
        except Exception as e:
            print(f"连接 Aria2 失败: {e}")
            return None

    def add_download(self, uri, filename, save_dir="downloads", retries=5):
        """添加单个下载任务，带重试机制"""
        # 参数说明: [ [下载链接], {配置项} ]
        # 使用简化的参数配置，不设置split和max-connection-per-server
        params = [
            [uri],
            {
                "out": filename,
                "dir": os.path.abspath(save_dir)
            }
        ]

        for attempt in range(retries):
            try:
                result = self._send_request("aria2.addUri", params)
                if result:
                    return result
            except Exception as e:
                if attempt < retries - 1:
                    print(f"添加下载任务失败 (尝试 {attempt + 1}/{retries}): {e}")
                    import time
                    time.sleep(2)  # 等待2秒后重试
                else:
                    print(f"添加下载任务最终失败: {e}")

        return None

    def add_downloads_batch(self, file_urls: List[Tuple[str, str]], save_dir="downloads"):
        """批量添加下载任务"""
        gids = []
        for filename, url in file_urls:
            # 清理文件名以避免Windows兼容性问题
            clean_filename = sanitize_filename(filename)

            gid = self.add_download(url, clean_filename, save_dir)
            if gid:
                gids.append(gid)
                print(f"✅ 已添加下载任务: {clean_filename}")
            else:
                print(f"❌ 添加下载任务失败: {clean_filename}")

            # 添加微小延迟避免RPC洪泛
            time.sleep(0.05)

        return gids

    def add_downloads_queued(self, file_urls: List[Tuple[str, str]], save_dir="downloads",
                           max_active_tasks=3, monitor_interval=10):
        """
        队列式添加下载任务：先添加所有任务，然后定期监控
        max_active_tasks: 同时运行的最大任务数
        monitor_interval: 监控间隔(秒)
        """
        import time

        gids = []
        active_tasks = {}  # gid -> (filename, start_time)

        print(f"🎯 开始队列式添加下载任务 (共{len(file_urls)}个)")
        print(f"   最大并发: {max_active_tasks} | 监控间隔: {monitor_interval}秒")

        # 第一阶段：添加所有任务（控制并发数）
        for i, (filename, url) in enumerate(file_urls):
            # 等待队列有空位
            while len(active_tasks) >= max_active_tasks:
                self._check_and_remove_completed_tasks(active_tasks)
                if len(active_tasks) >= max_active_tasks:
                    time.sleep(1)  # 短暂等待

            # 添加新任务
            clean_filename = sanitize_filename(filename)
            print(f"📥 添加任务 {i+1}/{len(file_urls)}: {clean_filename}")
            gid = self.add_download(url, clean_filename, save_dir)

            if gid:
                gids.append(gid)
                active_tasks[gid] = (clean_filename, time.time())
                print(f"✅ 任务已添加 (GID: {gid})")
            else:
                print(f"❌ 添加失败: {clean_filename}")

            # 添加微小延迟避免RPC洪泛
            time.sleep(0.1)

        # 第二阶段：监控任务完成情况
        print(f"🎉 所有任务已添加完毕 (共{len(gids)}个)")
        print("📊 开始监控任务完成情况...")

        last_active_count = len(active_tasks)
        max_wait_time = 3600  # 最多等待1小时
        start_monitor_time = time.time()

        while active_tasks and (time.time() - start_monitor_time) < max_wait_time:
            self._check_and_remove_completed_tasks(active_tasks)

            current_active_count = len(active_tasks)
            if current_active_count != last_active_count:
                # 只有当活跃任务数量发生变化时才输出
                if current_active_count > 0:
                    elapsed_total = time.time() - start_monitor_time
                    print(f"📋 [{int(elapsed_total)}秒] 剩余活跃任务: {current_active_count}")
                    # 显示前3个活跃任务作为示例
                    for i, (gid, (filename, start_time)) in enumerate(list(active_tasks.items())[:3]):
                        elapsed = time.time() - start_time
                        print(f"   • {filename} ({elapsed:.0f}秒)")
                    if current_active_count > 3:
                        print(f"   ... 还有 {current_active_count - 3} 个任务")
                else:
                    print("🎉 所有任务已完成！")
                last_active_count = current_active_count

            if active_tasks:
                time.sleep(monitor_interval)

        if active_tasks:
            elapsed_total = time.time() - start_monitor_time
            print(f"⚠️  [{int(elapsed_total)}秒] 监控超时，还有 {len(active_tasks)} 个任务未完成")
            for gid, (filename, start_time) in list(active_tasks.items()):
                elapsed = time.time() - start_time
                print(f"   • {filename} (运行时间: {elapsed:.0f}秒)")

        print("✅ 队列处理完成！")
        return gids

    def _check_and_remove_completed_tasks(self, active_tasks):
        """检查并移除已完成的任务"""
        completed_gids = []

        for gid in list(active_tasks.keys()):
            try:
                status = self.get_status(gid)
                if status:
                    status_code = status.get('status')
                    if status_code in ['complete', 'error', 'removed']:
                        filename, start_time = active_tasks[gid]
                        elapsed = time.time() - start_time
                        if status_code == 'complete':
                            print(f"✅ 任务完成: {filename} ({elapsed:.1f}秒)")
                        elif status_code == 'error':
                            print(f"❌ 任务失败: {filename} ({elapsed:.1f}秒)")
                        else:
                            print(f"⚠️ 任务停止: {filename} ({elapsed:.1f}秒)")
                        completed_gids.append(gid)
            except Exception as e:
                # 如果获取状态失败，可能是网络问题，暂时保留
                pass

        # 移除已完成的任务
        for gid in completed_gids:
            del active_tasks[gid]

    def get_status(self, gid):
        """获取指定任务的状态"""
        return self._send_request("aria2.tellStatus", [gid])

    def get_global_stat(self):
        """获取全局下载统计（总速度等）"""
        return self._send_request("aria2.getGlobalStat")

    def list_active(self):
        """列出正在下载的任务"""
        return self._send_request("aria2.tellActive")

class Aria2RPCServer:
    """Aria2 RPC服务器管理器"""
    def __init__(self, aria2_path="aria2c.exe", port=6800, token=""):
        self.aria2_path = aria2_path
        self.port = port
        self.token = token
        self.process = None

    def start_server(self, max_concurrent_downloads=3, max_connection_per_server=16):
        """启动Aria2 RPC服务器"""
        print(f"检查Aria2可执行文件: {self.aria2_path}")
        if not os.path.exists(self.aria2_path):
            print(f"❌ Aria2可执行文件不存在: {self.aria2_path}")
            print("请确保aria2c.exe在当前目录中")
            return False

        # 检查端口是否被占用
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(('127.0.0.1', self.port))
            if result == 0:
                print(f"❌ 端口 {self.port} 已被占用")
                print("请尝试使用不同的端口或关闭占用该端口的程序")
                return False
        except:
            pass
        finally:
            sock.close()

        # 完整的稳定配置
        cmd = [
            self.aria2_path,
            "--enable-rpc",
            "--rpc-listen-all=false",  # 为了安全，只允许本地访问
            "--rpc-allow-origin-all=true",
            f"--rpc-listen-port={self.port}",
            f"--max-concurrent-downloads={max_concurrent_downloads}",
            f"--max-connection-per-server={max_connection_per_server}",
            "--continue=true",
            "--log=" + os.path.join(os.getcwd(), "aria2_rpc.log"),
            "--log-level=info",  # 改为info以便排查崩溃
            "--disk-cache=64M",  # 减少磁盘碎片和IO压力
            "--file-allocation=none",  # Windows上强烈建议设为none，防止预分配导致卡死
            "--force-save=false"  # 禁止频繁保存会话，减少崩溃概率
        ]

        if self.token:
            cmd.append(f"--rpc-secret={self.token}")

        print(f"启动Aria2 RPC服务器命令: {' '.join(cmd)}")

        try:
            # 创建日志目录
            log_dir = os.path.dirname(os.path.join(os.getcwd(), "aria2_rpc.log"))
            os.makedirs(log_dir, exist_ok=True)

            self.process = subprocess.Popen(
                cmd,
                stdout=DEVNULL,  # 既然已经有--log参数，标准输出就不要了，防止堵塞
                stderr=DEVNULL,  # 错误输出也重定向到空，防止堵塞
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )

            print(f"等待Aria2 RPC服务器启动 (端口 {self.port})...")
            time.sleep(8)  # 增加等待时间到8秒

            # 检查进程是否还在运行
            if self.process.poll() is not None:
                # 进程已经退出，读取错误信息
                stdout, stderr = self.process.communicate()
                print(f"❌ Aria2进程异常退出")
                print(f"退出码: {self.process.returncode}")
                if stdout:
                    print(f"标准输出: {stdout}")
                if stderr:
                    print(f"错误输出: {stderr}")

                # 检查日志文件
                log_file = os.path.join(os.getcwd(), "aria2_rpc.log")
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        log_content = f.read()
                    print(f"Aria2日志内容:\n{log_content}")
                return False

            # 检查服务器是否启动成功 - 多重验证
            print("正在验证RPC连接...")
            for attempt in range(3):
                if self.is_running():
                    print("✅ Aria2 RPC服务器启动成功！")
                    print(f"📊 RPC地址: http://127.0.0.1:{self.port}/jsonrpc")
                    return True
                else:
                    if attempt < 2:
                        print(f"等待重试 ({attempt + 1}/3)...")
                        time.sleep(2)
                    else:
                        print("❌ Aria2 RPC服务器启动失败 - 无法连接RPC接口")

                        # 检查日志文件
                        log_file = os.path.join(os.getcwd(), "aria2_rpc.log")
                        if os.path.exists(log_file):
                            with open(log_file, 'r', encoding='utf-8') as f:
                                log_content = f.read()
                            print(f"Aria2日志内容:\n{log_content}")
                        return False

        except Exception as e:
            print(f"启动Aria2 RPC服务器失败: {e}")
            return False

    def stop_server(self):
        """停止Aria2 RPC服务器"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                print("✅ Aria2 RPC服务器已停止")
            except subprocess.TimeoutExpired:
                self.process.kill()
                print("⚠️ Aria2 RPC服务器被强制终止")
            except Exception as e:
                print(f"停止Aria2 RPC服务器失败: {e}")
            finally:
                self.process = None

    def is_running(self):
        """检查服务器是否正在运行"""
        if not self.process:
            return False

        # 检查进程是否还在运行
        if self.process.poll() is not None:
            print(f"❌ Aria2进程已退出，退出码: {self.process.returncode}")
            # 尝试读取错误信息
            try:
                if hasattr(self.process, 'stdout') and self.process.stdout:
                    stdout, stderr = self.process.communicate(timeout=1)
                    if stdout:
                        print(f"Aria2标准输出:\n{stdout.decode()}")
                    if stderr:
                        print(f"Aria2错误输出:\n{stderr.decode()}")
            except:
                pass
            return False

        # 尝试连接测试
        try:
            client = Aria2LocalClient("127.0.0.1", self.port, self.token)
            stat = client.get_global_stat()
            return stat is not None and isinstance(stat, dict)
        except Exception as e:
            print(f"RPC连接测试失败: {e}")
            return False

    def open_ariang(self):
        """打开AriaNG Web界面"""
        ariang_path = os.path.join(os.getcwd(), "AriaNG.html")
        if os.path.exists(ariang_path):
            print(f"打开AriaNG界面: file://{ariang_path}")
            webbrowser.open(f"file://{ariang_path}")
            return True
        else:
            print(f"❌ AriaNG.html文件不存在: {ariang_path}")
            return False
    
