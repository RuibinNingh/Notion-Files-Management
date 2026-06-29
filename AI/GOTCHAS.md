# 已知的坑 & 临时方案

> **格式**：每条坑说明「现象 → 原因 → 解决」。

---

## 1. keep-alive 缓存 Download 页后，不要用 `useTask.start()` 恢复 SSE

**现象**：切回 Download 页时，下载进度先闪成空白，过几秒才重新出现。

**原因**：`useTask.start()` 会重置 `state.progress = {}`。keep-alive 切回页面只是想「重新连接 SSE」，不需要清空已经收到的进度。

**解决**：keep-alive 的 `onActivated` 里用 `useTask.reconnect(taskId, callback)`——它只关闭旧 EventSource、打开新 EventSource，**不重置 state**。`reconnect()` 内部还会判断 `if (state.done) return`，对已终态任务不会空开连接。

---

## 2. 后端端口统一为 18765

**现象**：旧文档/旧脚本里可能还残留 8000 或 8765，导致前端代理、Docker 映射、systemd 和 Windows exe 不一致。

**原因**：早期本地开发避开 8000 时临时用过 8765；现在 8765 也可能被其他程序占用。

**解决**：统一使用 `18765`，并保持 `frontend/vite.config.ts`、Docker、systemd、PyInstaller/Windows 入口一致。只有确实需要迁移端口时，才全局同步修改。

**生产建议**：公网仍建议用 nginx/Caddy 做 TLS 反代，把外部 443 转发到 `127.0.0.1:18765`。

---

## 2. uvicorn 没开 `--reload`，改了后端代码不生效

**现象**：改了 `backend/app/routers/...` 里的代码，但 curl 行为不变。

**原因**：启动时没加 `--reload`（避免和后台任务状态冲突）。

**解决**：
```bash
kill <uvicorn-pid>
# 重启
NFM_DATA_DIR=/tmp/nfm-run .venv/bin/python -m uvicorn app.main:app --app-dir backend --port 18765
```

**或者临时**调试用 `--reload`（但它会重启 worker，包括正在跑的 task）：
```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 18765 --reload
```

---

## 3. Notion API 速率限制（429）

**现象**：`429 Too Many Requests`。

**当前状态**：每个任务类**内部**有限流：
- `Upload`：自带 `TokenBucketRateLimiter(rps=3, burst=4)` + Retry-After
- `migrate` / `batch_rename`：每 0.4s 一次请求
- `page_size_update`：Notion API 0.34s 间隔

但**没有跨任务全局限流**。同时跑两个大任务（如同时迁移 + 页面大小更新）可能合计超过 3 req/s。

**后果**：单次请求 429 → 上传侧有 Retry-After 自动重试，**OK**。但如果两个任务的轮询协程同时触发，可能堆压。

**当前缓解**：把 `Upload.rps` 调小（比如 2.0）。设置页可调并发数。

**待办（未实现）**：写一个 `app/ratelimit.py`，全局 `TokenBucketRateLimiter(3, burst=4)`，让 `notion.py` 的所有 `requests.*` 调用通过它。**风险**：要改 `notion.py` 大量代码，可能引入 bug。

---

## 4. 前端 `useTask` 早版本：模板访问 `task.progress.x` 报错

**现象**：
```
Property 'files_probed' does not exist on type 'Ref<any, any>'.
```

**原因**：vue 模板只对**顶层 setup 返回的 ref**自动解包。`const scanTask = useTask()` 然后 `scanTask.progress` 是嵌套属性访问，**不会**自动解包。

**已修**（✅ 当前代码）：`useTask` 改成返回 `{ state: reactive(...), start, stop, cancel }`，模板用 `scanTask.state.progress.files_probed`。

**避免再犯**：
- composable 返回的 ref 要么放在顶层 const，要么包在 `reactive({})` 里
- 不要在 setup 里写 `const progress = task.progress` 然后在模板用 `progress.x`

---

## 5. EventSource 自带 `error` 事件 vs 自定义 SSE `error` 事件冲突

**现象**：如果后端 SSE 推送 `event: "error"`，浏览器既把它当成「后端报告错误」也当成「连接断开」，无法区分。

**现状（✅ 已避坑）**：后端所有终态都用 `event: "done"`，`data.status` 区分 `done/error/cancelled`：
```python
yield {"event": "done", "data": json.dumps({"status": h.status, "error": h.error})}
```

**不要**改回发 `event: "error"`，除非前端用 `addEventListener` 显式区分。

---

## 6. Download 实例**绝对不能**跨任务共享

**原因**：
- `Download.status_map` 不是线程安全的
- 跨任务共享会导致：两个任务的 URL 状态互相污染、A 任务的取消导致 B 任务中断

**现状（✅ 已修）**：`facade.start_download` 每次都 `new Download(max_workers=...)`，task 结束调 `dl.shutdown(wait=False)`。

**不要**「优化」成单例 Download。如果担心线程开销，可以加对象池，但**不要**直接共享。

---

## 7. 上传后立刻查询可能查不到

**现象**：调用 `/api/upload/start` 后立刻 `GET /api/tasks/{tid}/events`，可能收不到 `progress` 事件。

**原因**：`Upload.upload_file` 是 enqueue + 立即返回，workers 异步取任务。任务进 `status_map` 有微小延迟。

**现状**：前端 SSE 自动重连 + 轮询一般 0.4s 起步，几秒后能稳定看到进度。如果要严格保证，可以在 poll 函数里加个最小轮询次数。

---

## 8. 文件名冲突：同 batch 内两个文件 real_name 相同

**现象**：第二个文件覆盖第一个。

**现状**：`facade.start_download` 里：
```python
if base in used_names:
    used_names[base] += 1
    stem, dot, ext = base.rpartition(".")
    unique = f"{stem} ({used_names[base]}){dot}{ext}" if dot else f"{base} ({used_names[base]})"
```
会自动重命名为 `name (1).ext`。`dl_file` 接口用 `save_name` 找到正确文件。

**不要**在 router 里直接用 `real_name` 拼路径。

---

## 9. SPA 路由 fallback 与 `/api` 冲突

**现象**：访问 `http://.../download`（Vue Router 路径）时，期望返回 index.html，但可能命中某个 `/api/*`。

**现状**（`main.py`）：
```python
@app.api_route("/{path:path}", methods=["GET"])
async def spa_fallback(path: str, request: Request):
    if path.startswith("api"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"detail": "Not Found"}, status_code=404)
```

✅ `/api/*` 不会触发 fallback，会返回 404 JSON。

⚠️ **但** `/api/auth/login` 等 router 是 `include_router` 在 fallback 之前注册的，所以 POST 也走 router。fallback 只对未匹配的路径生效。

---

## 10. `itsdangerous` 的 SessionMiddleware 与 `samesite="lax"` 在 iframe 里失效

**场景**：如果未来想嵌入到 Notion 页面（iframe），`SameSite=Lax` 不发送第三方 cookie。

**当前**：`samesite="lax"`，开发/独立部署够用。

**未来**：要嵌入时改成 `None` + `https_only=True`。

---

## 11. Notion 页面 ID 输入支持 URL 提取

**现状**：`utils/pageId.ts`（前端）+ `NotionPageId`（**后端没有对应实现！**）支持：
- 32 hex
- 带连字符 UUID
- 含 URL 的字符串（自动提取）

**坑**：后端 `routers/scan.py` `ScanIn` 接收 `page_id`，**没有做 normalize**。如果用户粘贴 URL 进来，会直接传给 Notion API 报错。

**当前缓解**：前端 `onPageIdInput` 调 `normalizePageId` 规范化后才发送。

**彻底解决**：后端也加 `from utils.pageId import normalizePageId`（需要把 utils 暴露出来），或在 facade 里做。

---

## 12. 断点续传未实现

**状态**：所有下载/上传都从 0 开始。

**影响**：大文件（> 1GB）网络中断后无法续传，必须重下。

**实现思路（未做）**：
- 下载：HEAD 拿 Content-Range，GET 带 `Range: bytes=X-`
- 上传：Notion File Upload API 支持 `part_size`，断点续传 = 重新上传未完成的 part

优先级低。

---

## 13. `backend/.venv` 误创建

**现象**：`cd backend && pip install` 时会创建 `backend/.venv`（因为 venv 默认在 cwd）。

**影响**：占用空间，但 .gitignore 已排除，不影响提交。

**避免**：始终在**项目根目录**执行 venv 命令：
```bash
# 错
cd backend && python -m venv .venv

# 对
python -m venv .venv
```

---

## 14. Vite proxy 必须跟统一后端端口一致

**当前**：`frontend/vite.config.ts` 的 proxy target 是 `http://127.0.0.1:18765`。

**如果统一端口以后再次变更**：
```bash
sed -i "s|target: 'http://127.0.0.1:18765'|target: 'http://127.0.0.1:<new-port>'|" frontend/vite.config.ts
```

然后重启 vite（不会自动热重载 config）。

---

## 15. 后端日志两个 logger 重复

**现象**：后端启动后，日志既写到 console 也写到 `${NFM_DATA_DIR}/logs/`。`logger.py` 已分别 init Python logger 和 .NET 风格 logger。

**现状**（`main.py`）：
```python
PythonLogger.init(str(LOG_DIR))   # scripts/logger.py
logging.basicConfig(...)            # C# 风格的
```

两个 logger 都接到了同一些消息，但格式不同（Python 格式 vs `[HH:mm:ss][T<id>][LEVEL]`）。如果觉得冗余，把 `PythonLogger.init` 那一行删了即可。

---

## 16. 工具路由的 `NotionToken` 鉴权

**现状**：所有 `/api/tools/*` 和 `/api/upload/*` 等业务接口，都只检查 session（即「你能访问这个 Web」），**不检查 Notion Token**。Notion Token 在 `config.json` 里，全局共享。

**后果**：A 登录后，能操作 B 的 Notion 页面（用同一个 Token）。

**这是单租户设计**，见 `OVERVIEW.md`「不在范围内」。如果以后要多租户，Token 要从 cookie 转到「每个 session 一个 token」，改动会很大。

---

## 17. 探测期间点不动 Download 页的文件复选框（选了就被刷掉）

**现象**：扫描进行中勾选文件列表里的某一行，约 800ms 后自己变成未选中；用户体感是「根本选不上」。

**原因**：`Download.vue` 的 `refreshList()` 每 800ms 拉一次 `/api/scan/{tid}/list`，整组 `scanItems.value = r.data.items` —— 数组里每个 row 都是 `JSON.parse` 出来的新对象。`<el-table>` 没设 `row-key`，默认按**对象引用**追踪选中行，引用一换 el-table 找不到旧 row，立刻派发 `selection-change=[]`，`selected.value` 被清空。

**解决**：给 `<el-table>` 加 `row-key="url"`（`backend/scripts/notion.py:163-212` 的 `get_download_url_no_recurse` 保证每个 item 有唯一 `url`），并给 selection 列加 `reserve-selection`：
```vue
<el-table :data="scanItems" row-key="url">
  <el-table-column type="selection" reserve-selection />
</el-table>
```
`row-key` 提供稳定身份，`reserve-selection` 告诉 Element Plus 在 `data` 刷新后保留已选行。

**不要**改成"刷新前记下 selectedUrls、刷新后 `setSelectedRows` 回填"那种手动方案 —— `row-key + reserve-selection` 是组件内建能力。

---

## 18. 上传任务重试依赖 staging 缓存仍存在

**现象**：任务看板里点击上传任务「重试」,后端可能返回「上传缓存已不存在，请重新选择文件。」

**原因**：浏览器选择的本地文件不会被后端永久持有。`POST /api/upload/files` 先把文件保存到 `${NFM_DATA_DIR}/staging/upload-<id>/`,云端上传任务重试只能复用这份 staging 文件。如果缓存被手动删除或 TTL 自动清理,后端没有办法重新读取用户本地文件。

**解决**：上传任务的 `retry_fn` 会先检查缓存路径是否存在;不存在时返回 400,前端提示重新选择文件。缓存自动清理会跳过运行中任务的 `cache_refs`,但不会永久保留已终态任务缓存。

---

## 19. 缓存清理必须跳过运行中任务

**现象**：如果清理掉运行中上传任务的 `upload-<id>/` 或下载任务的 `download-<id>/`,任务会失败或完成后无法下载产物。

**原因**：上传/下载任务的文件产物和中间缓存都在 `${NFM_DATA_DIR}/staging`。缓存页面和自动清理线程如果只按 mtime 删除,会误删仍被任务使用的目录。

**解决**：任务创建时把缓存目录写入 `TaskHandle.cache_refs`;清理走 `registry.active_cache_refs()` 得到保护路径。`DELETE /api/cache/items/{id}` 遇到 busy 缓存返回 409,前端禁用删除按钮。

---

## 20. 缓存可读名称不能替代 `cache_id`

**现象**：缓存页如果只显示 `upload-<id>` / `download-<id>` / `generated-*.zip`,用户无法判断是哪一次上传或下载;但如果直接把目录/文件名改成中文业务名,又会影响任务 artifact、下载 URL、清理保护和日志排查。

**解决**：底层存储名继续作为稳定 `id`;可读名称写入缓存元数据:

- 目录缓存: `${NFM_DATA_DIR}/staging/<cache_id>/.nfm-cache.json`
- 文件缓存: `${NFM_DATA_DIR}/staging/<cache_id>.meta.json`

`GET /api/cache/items` 返回 `id`、`name` 和 `storage_name`。前端用 `name` 做主展示,用 `storage_name` 做辅助排查信息。后端下载、删除、任务 `cache_refs` 必须继续使用 `id` / 真实路径。

---

## 21. Range 分片下载是实验性能力,必须能回退

**现象**：大文件单连接下载慢时,提高 `max_download_workers` 没效果,因为只有一个文件在活跃下载。分片下载可能提升吞吐,但 Notion 的签名 URL/CDN 不保证稳定支持多 Range 并发。

**解决**：`enable_range_download` 默认关闭。开启后 `Download` 先用 `Range: bytes=0-0` 探测,只有能拿到 `Content-Range` 且文件大小超过 `range_download_min_mb` 才分片。探测失败、低于阈值、分片数退化为 1 时必须回退单连接。

**注意**：

- 配置值可能来自 JSON/env/Web 表单,不要直接 `bool(value)`:字符串 `"False"` 在 Python 里是真值。`Download` 内部用 `_coerce_bool()` 归一化。
- 分片会生成 `*.partNNN` 和 `*.merge`,失败/重试前必须清理。
- 分片临时文件会增加磁盘占用,大文件合并阶段峰值可能接近 2 倍。
- 如果日志里出现 `[DownloadRange] failed expired=True`,说明分片请求遇到 401/403/410,会走 URL 刷新重试整个文件。
- 不要把分片开关默认打开;先用真实 Notion 文件日志确认 CDN 行为。

---

## 22. API Key 鉴权:session 优先,明文只显一次

**现象**：用浏览器(已登录)同时带 `Authorization: Bearer` 调接口，无论 key 给了什么 scope 都能访问，scope 校验「不生效」。

**原因**：`deps.resolve_auth` **先**判 `request.session['auth']`，session 登录即管理员，全权限放行，根本不会走到 key 的 scope 校验。测试时若用同一个 `TestClient` 既登录又带 Bearer，就会踩到这点(见 `backend/tests/test_apikeys_auth.py` 的 `fresh` fixture)。

**解决**：测 Bearer 鉴权必须用**未登录**的全新 client。生产上这是设计意图——浏览器管理员永远全权限，key 只管第三方。

---

## 23. API Key 明文只创建时返回一次

**现象**：用户丢了 key 明文，想再「查看」拿不回来。

**原因**：`config.json` 里只存 `sha256(plaintext)` 的 hash(`apikeys.hash_key`)，不可逆。列表接口(`GET /api/apikeys`)只返回 `prefix`(`nfm_` + 8 位)，永不返回明文或 hash。

**解决**：创建时(`POST /api/apikeys`)返回一次 `plaintext`，前端弹窗强提示「立即复制保存」。丢失只能删除重建。**不要**为了「方便」把明文落盘。

---

## 24. SSE 不接受 ?api_key=，改用短期 events_token

**现象**：第三方用 `EventSource` 订阅 `/api/tasks/{tid}/events`，没法塞 `Authorization: Bearer`；想用 `?api_key=` 走 query 参数，被 401 拒绝。

**原因**：长期 API Key **永远只走 Bearer 头**，不接受任何 query 参数（避免明文进访问日志/Referer 被泄漏）。`deps.resolve_auth` / `require_events_access` 都不读 `?api_key=`。浏览器 `EventSource` 又不能自定义请求头。

**解决**：先换短期 token，再用 query 订阅：
1. `POST /api/tasks/{tid}/events-token`（需 session 或带 `tasks` scope 的 Bearer key）→ 返回 `nfmsse_...`，10 分钟有效，**绑定单个 task_id**。
2. `new EventSource('/api/tasks/{tid}/events?events_token=nfmsse_xxx')`。

`?events_token=` 是唯一允许出现在 URL 里的凭据，且短期、单任务绑定。token 进程内存储，重启失效（可接受）。`GET /{tid}/events` 的鉴权走 `deps.require_events_access`（session / Bearer+tasks / events_token 三选一），**没有**挂在路由级 `require_scope` 上——否则 query token 会被 401 拦掉。

**不要**把 `?api_key=` 加回来。第三方 SSE 之外的所有接口都只认 Bearer。

---

## 25. PATCH 清空过期时间必须显式传 null

**现象**：`PATCH /api/apikeys/{id}` 想把过期时间清空成「永不过期」，传 `{"expires_at": null}` 没生效，过期时间没变。

**原因**：早期版本用 `body.model_dump(exclude_none=True)`，`null` 被当成「未传」一起剔除，区分不出「不修改」和「清空」。

**解决**：改用 `body.model_fields_set` 判断字段是否**显式出现**在请求体里；`update_key` 用 `_UNSET` 哨兵区分「未传」与「显式 None」。只有 `expires_at` 真的出现在 body 里（哪怕值是 null）才写盘，`None` → 清空。**不要**改回 `exclude_none`。

---

## 26. bootstrap 预置 key 拒绝弱值

**现象**：`NFM_BOOTSTRAP_API_KEY=short` 启动后没有预置 key，日志里一条 warning。

**原因**：预置 key 现在严格要求 `nfm_` 前缀 + 前缀后有效负载 ≥ 32 字符。不合格直接忽略并记 warning，**不**自动补前缀（避免把任意弱值包装成全权限 key）。

**解决**：部署时给一个强明文，如 `NFM_BOOTSTRAP_API_KEY=nfm_<≥32字符随机串>`。重复启动按前缀/hash 去重，不重建。

---

## 27. CORS 白名单是动态的，改设置无需重启

**现象**：在「API 密钥」页改了跨域白名单，第三方浏览器跨域调用立刻生效，不用重启后端。

**原因**：`app/cors.py` 的 `DynamicCORSMiddleware` **每次请求**实时读 `config["api_cors_allowed_origins"]`，不是启动时一次性读取。非法 origin（`*`、`null`、带 path/query）在 `is_valid_origin` 里被静默丢弃，永远不放行。

**注意**：本中间件始终 `allow_credentials=true`，所以 `*` 永远不可能放行（浏览器规范禁止 `*` + credentials）。要开放就显式列具体 origin。

---

## 28. VitePress docs:dev 不要暴露公网

**现象**：根目录 `npm audit` 报 VitePress 依赖链上的 Vite/esbuild dev server 漏洞，当前最新 `vitepress@1.6.4` 暂无上游修复。

**原因**：这是文档站开发服务器链路的问题，不是 NFM FastAPI 后端，也不是静态文档构建产物。`npm run docs:build` 生成的静态站点不需要暴露 Vite dev server。

**解决**：`npm run docs:dev` 只用于本机或可信内网预览，不要直接暴露到公网。发布文档时使用 `npm run docs:build` 的静态产物（`docs/.vitepress/dist/`），由 GitHub Pages、Nginx、Caddy 等静态托管。
