import requests
import time
from datetime import datetime, timezone
from logger import PythonLogger

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

    # =========================================================================
    # 不可通过 API 写入的属性类型 (Notion 自动生成的值，或不支持创建时写入的)
    # =========================================================================
    READONLY_PROPERTY_TYPES = frozenset({
        "rollup", "created_by", "created_time",
        "last_edited_by", "last_edited_time",
        "formula", "unique_id", "button",
    })

    # =========================================================================
    # 可下载的媒体块类型 (v1.4.2-Status+)
    # 这些块类型的结构相同: block[block_type][hosting_type].url
    # =========================================================================
    MEDIA_BLOCK_TYPES = frozenset({"file", "image", "pdf", "audio", "video"})

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
                        PythonLogger.warning(f"触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    
                    # 成功请求，跳出重试循环
                    res.raise_for_status() 
                    break
                    
                except (requests.exceptions.RequestException, Exception) as e:
                    wait_time = 2 ** attempt
                    if attempt < max_retries - 1:
                        PythonLogger.warning(f"请求异常: {e}，等待 {wait_time}s 后重试...")
                        time.sleep(wait_time)
                    else:
                        PythonLogger.error(f"已达到最大重试次数，任务失败: {e}")
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
        从 blocks 列表中提取所有可下载文件的信息。
        支持的块类型 (v1.4.2-Status): file, image, pdf, audio, video

        下载链接的格式:
        [
            {
                "name": "example.zip.txt"
                "real_name": "example.zip"
                "url": "https://s3.us-west-2.amazonaws.com/secure.notion-static.com/...."
                "expiry_time": "2024-10-01T12:00:00.000Z",
                "size_mb": 2.5,
                "block_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "block_type": "file",
                "created_time": "2026-02-18T12:00:00.000Z"
            }
        ]
        """
        download_list = []
        if not body:
            return download_list

        # 记录链接创建时间（即本次获取列表的时间）
        created_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        for block in body:
            block_type = block.get("type")

            if block_type in self.MEDIA_BLOCK_TYPES:
                media_info = block.get(block_type, {})
                block_id = block.get("id", "")

                # 提取 URL 和过期时间
                hosting_type = media_info.get("type")
                if hosting_type == "file":
                    url = media_info.get("file", {}).get("url")
                    expiry_time = media_info.get("file", {}).get("expiry_time")
                elif hosting_type == "external":
                    url = media_info.get("external", {}).get("url")
                    expiry_time = None
                else:
                    url = None
                    expiry_time = None

                if not url:
                    continue

                # 提取文件名: file 块有 name 字段，其他媒体块从 URL 推断
                original_name = media_info.get("name") or self._filename_from_url(url) or f"unknown_{block_type}"

                size_mb = self._get_remote_file_size(url)

                # caption 作为显示名
                captions = media_info.get("caption", [])
                caption_text = "".join([t.get("plain_text", "") for t in captions]).strip()
                real_name = caption_text if caption_text else original_name

                download_list.append({
                    "name": original_name,
                    "real_name": real_name,
                    "url": url,
                    "expiry_time": expiry_time,
                    "size_mb": size_mb,
                    "block_id": block_id,
                    "block_type": block_type,
                    "created_time": created_time,
                })

            # 递归处理子块
            if block.get("has_children") and "children" in block:
                child_downloads = self.get_download_url(block["children"])
                download_list.extend(child_downloads)

        return download_list

    def get_page_object(self, page_id: str) -> dict | None:
        """
        获取页面对象（含 icon、cover、properties）。
        使用 GET /v1/pages/{page_id}

        返回: 页面对象 dict 或 None（失败时）
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.get(
                    f"{self.url}/pages/{page_id}",
                    headers=self.default_headers,
                    timeout=10
                )
                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[get_page_object] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                res.raise_for_status()
                return res.json()
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    PythonLogger.error(f"[get_page_object] page_id={page_id} 失败: {e}")
                    return None
        return None

    def extract_page_level_files(self, page_obj: dict) -> list[dict]:
        """
        从页面对象中提取页面级文件：icon、cover、files 类型属性。(v1.4.2-Status)

        返回格式与 get_download_url 一致的列表。
        """
        if not page_obj:
            return []

        created_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        result = []

        # 1) icon
        icon = page_obj.get("icon")
        if icon:
            icon_url, icon_expiry = self._extract_hosted_url(icon)
            if icon_url:
                fname = self._filename_from_url(icon_url) or "page_icon"
                result.append({
                    "name": fname,
                    "real_name": f"[icon] {fname}",
                    "url": icon_url,
                    "expiry_time": icon_expiry,
                    "size_mb": self._get_remote_file_size(icon_url),
                    "block_id": "",
                    "block_type": "icon",
                    "created_time": created_time,
                })

        # 2) cover
        cover = page_obj.get("cover")
        if cover:
            cover_url, cover_expiry = self._extract_hosted_url(cover)
            if cover_url:
                fname = self._filename_from_url(cover_url) or "page_cover"
                result.append({
                    "name": fname,
                    "real_name": f"[cover] {fname}",
                    "url": cover_url,
                    "expiry_time": cover_expiry,
                    "size_mb": self._get_remote_file_size(cover_url),
                    "block_id": "",
                    "block_type": "cover",
                    "created_time": created_time,
                })

        # 3) files 类型属性
        properties = page_obj.get("properties", {})
        for prop_name, prop_val in properties.items():
            if prop_val.get("type") != "files":
                continue
            files_arr = prop_val.get("files", [])
            for file_obj in files_arr:
                file_url, file_expiry = self._extract_hosted_url(file_obj)
                if not file_url:
                    continue
                fname = file_obj.get("name") or self._filename_from_url(file_url) or "property_file"
                result.append({
                    "name": fname,
                    "real_name": f"[{prop_name}] {fname}",
                    "url": file_url,
                    "expiry_time": file_expiry,
                    "size_mb": self._get_remote_file_size(file_url),
                    "block_id": "",
                    "block_type": "property_file",
                    "created_time": created_time,
                })

        return result

    @staticmethod
    def _extract_hosted_url(obj: dict) -> tuple[str | None, str | None]:
        """从 Notion 文件对象中提取 URL 和过期时间。支持 file/external 两种 hosting。"""
        hosting = obj.get("type")
        if hosting == "file":
            inner = obj.get("file", {})
            return inner.get("url"), inner.get("expiry_time")
        elif hosting == "external":
            return obj.get("external", {}).get("url"), None
        return None, None

    @staticmethod
    def _filename_from_url(url: str) -> str:
        """从 URL 中提取文件名（去掉查询参数）。"""
        try:
            from urllib.parse import urlparse, unquote
            path = urlparse(url).path
            name = unquote(path.split("/")[-1])
            # 去掉 Notion 特有的 UUID 前缀 (格式: uuid/filename)
            if name:
                return name
        except Exception:
            pass
        return ""

    def refresh_file_url(self, block_id: str) -> dict | None:
        """
        通过 block_id 重新获取单个媒体块的最新下载链接。
        用于下载过程中链接过期时自动刷新。
        支持: file, image, pdf, audio, video 块类型 (v1.4.2-Status)

        返回: {"url": "...", "expiry_time": "..."} 或 None（失败时）
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.get(
                    f"{self.url}/blocks/{block_id}",
                    headers=self.default_headers,
                    timeout=10
                )

                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[refresh_file_url] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                res.raise_for_status()
                block = res.json()

                block_type = block.get("type")
                if block_type not in self.MEDIA_BLOCK_TYPES:
                    PythonLogger.warning(f"[refresh_file_url] block {block_id} type={block_type}，不是媒体类型")
                    return None

                media_info = block.get(block_type, {})
                hosting_type = media_info.get("type")

                if hosting_type == "file":
                    new_url = media_info.get("file", {}).get("url")
                    new_expiry = media_info.get("file", {}).get("expiry_time")
                elif hosting_type == "external":
                    # external 类型没有过期问题
                    new_url = media_info.get("external", {}).get("url")
                    new_expiry = None
                else:
                    PythonLogger.warning(f"[refresh_file_url] block {block_id} 未知 hosting type={hosting_type}")
                    return None

                PythonLogger.info(f"[refresh_file_url] block_id={block_id} type={block_type} 刷新成功，new_expiry={new_expiry}")
                return {
                    "url": new_url,
                    "expiry_time": new_expiry,
                }

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[refresh_file_url] 异常: {e}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    PythonLogger.error(f"[refresh_file_url] block_id={block_id} 刷新失败: {e}")
                    return None

        return None

    # =========================================================================
    # Data Sources API (v1.3.0-Status+, Notion API 2025-09-03)
    # =========================================================================

    def get_database_properties(self, data_source_id: str) -> dict:
        """
        获取数据源属性 Schema。
        使用 Data Sources API: GET /v1/data_sources/{data_source_id}

        返回格式:
        {
            "status": "success" | "error",
            "data_source_id": "...",
            "title": "...",
            "properties": {
                "属性名": {
                    "id": "...",
                    "type": "title" | "rich_text" | "number" | ...
                },
                ...
            },
            "error": "..." (仅在 status=error 时)
        }
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.get(
                    f"{self.url}/data_sources/{data_source_id}",
                    headers=self.default_headers,
                    timeout=15
                )

                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[get_database_properties] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                if res.status_code == 404:
                    return {
                        "status": "error",
                        "data_source_id": data_source_id,
                        "title": "",
                        "properties": {},
                        "error": f"数据源 {data_source_id} 不存在或无权限访问。请确认 ID 是数据源 ID（而非数据库 ID），并检查 Integration 权限。"
                    }

                res.raise_for_status()
                data = res.json()

                # 提取属性 Schema（只保留 id 和 type 用于映射）
                raw_props = data.get("properties", {})
                properties = {}
                for name, config in raw_props.items():
                    properties[name] = {
                        "id": config.get("id", ""),
                        "type": config.get("type", "unknown"),
                    }

                # 提取标题
                title_arr = data.get("title", [])
                title = "".join([t.get("plain_text", "") for t in title_arr]).strip() if title_arr else ""

                PythonLogger.info(f"[get_database_properties] data_source_id={data_source_id}, title={title}, properties_count={len(properties)}")
                return {
                    "status": "success",
                    "data_source_id": data_source_id,
                    "title": title,
                    "properties": properties,
                }

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[get_database_properties] 异常: {e}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    PythonLogger.error(f"[get_database_properties] data_source_id={data_source_id} 失败: {e}")
                    return {
                        "status": "error",
                        "data_source_id": data_source_id,
                        "title": "",
                        "properties": {},
                        "error": str(e)
                    }

        return {"status": "error", "data_source_id": data_source_id, "title": "", "properties": {}, "error": "未知错误"}

    def query_database(self, data_source_id: str) -> list:
        """
        查询数据源中的所有页面（自动分页）。
        使用 Data Sources API: POST /v1/data_sources/{data_source_id}/query

        返回: 页面对象列表 (list of page objects)
        """
        all_pages = []
        cursor = None
        max_retries = 4

        while True:
            body = {}
            if cursor:
                body["start_cursor"] = cursor
            body["page_size"] = 100  # 每页最大 100

            for attempt in range(max_retries):
                try:
                    res = requests.post(
                        f"{self.url}/data_sources/{data_source_id}/query",
                        headers={**self.default_headers, "Content-Type": "application/json"},
                        json=body,
                        timeout=30
                    )

                    if res.status_code in [429, 500, 502, 503, 504]:
                        wait_time = 2 ** attempt
                        PythonLogger.warning(f"[query_database] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                        time.sleep(wait_time)
                        continue

                    res.raise_for_status()
                    break

                except (requests.exceptions.RequestException, Exception) as e:
                    wait_time = 2 ** attempt
                    if attempt < max_retries - 1:
                        PythonLogger.warning(f"[query_database] 异常: {e}，等待 {wait_time}s 后重试...")
                        time.sleep(wait_time)
                    else:
                        PythonLogger.error(f"[query_database] 已达到最大重试次数: {e}")
                        return all_pages

            data = res.json()
            pages = data.get("results", [])
            all_pages.extend(pages)

            PythonLogger.info(f"[query_database] 已获取 {len(all_pages)} 页，has_more={data.get('has_more')}")

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return all_pages

    def create_page_in_database(self, data_source_id: str, properties: dict, children: list | None = None) -> dict:
        """
        在数据源中创建新页面。
        使用 POST /v1/pages，parent 使用 data_source_id（2025-09-03 API）。

        参数:
            data_source_id: 目标数据源 ID
            properties: 页面属性字典（键=属性名，值=属性值对象）
            children: 页面内容 blocks 列表（可选，最多 100 个一级 block）

        返回: 创建的页面对象（dict）
        """
        max_retries = 4
        body = {
            "parent": {
                "type": "data_source_id",
                "data_source_id": data_source_id,
            },
            "properties": properties,
        }
        if children:
            # Notion API 在创建页面时最多允许 100 个一级 block
            body["children"] = children[:100]

        for attempt in range(max_retries):
            try:
                res = requests.post(
                    f"{self.url}/pages",
                    headers={**self.default_headers, "Content-Type": "application/json"},
                    json=body,
                    timeout=30
                )

                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[create_page_in_database] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                res.raise_for_status()
                return res.json()

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[create_page_in_database] 异常: {e}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    PythonLogger.error(f"[create_page_in_database] 失败: {e}")
                    raise

        raise RuntimeError("create_page_in_database: 未知错误")

    def move_page(self, page_id: str, target_data_source_id: str) -> dict:
        """
        移动页面到目标数据源。
        使用 POST /v1/pages/{page_id}/move

        参数:
            page_id: 要移动的页面 ID
            target_data_source_id: 目标数据源 ID

        返回: 移动后的页面对象（dict）
        """
        max_retries = 4
        body = {
            "parent": {
                "type": "data_source_id",
                "data_source_id": target_data_source_id,
            }
        }

        for attempt in range(max_retries):
            try:
                res = requests.post(
                    f"{self.url}/pages/{page_id}/move",
                    headers={**self.default_headers, "Content-Type": "application/json"},
                    json=body,
                    timeout=30
                )

                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[move_page] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                if res.status_code >= 400:
                    try:
                        err_body = res.json()
                        PythonLogger.error(f"[move_page] API 错误 {res.status_code}: code={err_body.get('code')}, message={err_body.get('message')}")
                    except Exception:
                        PythonLogger.error(f"[move_page] API 错误 {res.status_code}: {res.text[:500]}")

                res.raise_for_status()
                return res.json()

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[move_page] 异常: {e}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    PythonLogger.error(f"[move_page] page_id={page_id} 失败: {e}")
                    raise

        raise RuntimeError("move_page: 未知错误")

    def update_page_properties(self, page_id: str, properties: dict) -> dict:
        """
        更新页面属性。
        使用 PATCH /v1/pages/{page_id}

        参数:
            page_id: 页面 ID
            properties: 属性字典（键=属性名，值=属性值对象）

        返回: 更新后的页面对象（dict）
        """
        max_retries = 4
        body = {"properties": properties}

        for attempt in range(max_retries):
            try:
                res = requests.patch(
                    f"{self.url}/pages/{page_id}",
                    headers={**self.default_headers, "Content-Type": "application/json"},
                    json=body,
                    timeout=30
                )

                if res.status_code in [429, 500, 502, 503, 504]:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[update_page_properties] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                if res.status_code >= 400:
                    try:
                        err_body = res.json()
                        PythonLogger.error(f"[update_page_properties] API 错误 {res.status_code}: code={err_body.get('code')}, message={err_body.get('message')}")
                    except Exception:
                        PythonLogger.error(f"[update_page_properties] API 错误 {res.status_code}: {res.text[:500]}")

                res.raise_for_status()
                return res.json()

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    PythonLogger.warning(f"[update_page_properties] 异常: {e}，等待 {wait_time}s 后重试...")
                    time.sleep(wait_time)
                else:
                    PythonLogger.error(f"[update_page_properties] page_id={page_id} 失败: {e}")
                    raise

        raise RuntimeError("update_page_properties: 未知错误")

    def append_blocks(self, page_id: str, children: list) -> None:
        """
        向页面追加 blocks（自动分批，每批最多 100 个）。
        使用 PATCH /v1/blocks/{page_id}/children

        参数:
            page_id: 目标页面 ID
            children: block 对象列表
        """
        max_retries = 4
        # 分批，每批最多 100
        for i in range(0, len(children), 100):
            batch = children[i:i+100]

            for attempt in range(max_retries):
                try:
                    res = requests.patch(
                        f"{self.url}/blocks/{page_id}/children",
                        headers={**self.default_headers, "Content-Type": "application/json"},
                        json={"children": batch},
                        timeout=30
                    )

                    if res.status_code in [429, 500, 502, 503, 504]:
                        wait_time = 2 ** attempt
                        PythonLogger.warning(f"[append_blocks] 触发限制({res.status_code})，第 {attempt+1} 次重试，等待 {wait_time}s...")
                        time.sleep(wait_time)
                        continue

                    res.raise_for_status()
                    break

                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        PythonLogger.warning(f"[append_blocks] 异常: {e}，等待 {wait_time}s 后重试...")
                        time.sleep(wait_time)
                    else:
                        PythonLogger.error(f"[append_blocks] page_id={page_id} 批次 {i//100+1} 失败: {e}")
                        raise

    def _get_remote_file_size(self, url):
        """探测远程文件大小，返回 MB"""
        try:
            # 使用 stream=True 或 head 请求来避免下载文件体
            response = requests.head(url, allow_redirects=True, timeout=5)
            size_bytes = response.headers.get('content-length')
            if size_bytes:
                return round(int(size_bytes) / (1024 * 1024), 2)
        except Exception as e:
            PythonLogger.warning(f"获取文件大小失败: {e}")
        return 0
        
        
if __name__ == "__main__":
    notion = Notion("your_integration_token_here")
    page_data = notion.query_page("your_page_id",True)
    download_urls = notion.get_download_url(page_data)
    print(download_urls)
