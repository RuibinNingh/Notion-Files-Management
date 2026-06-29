# 变更日志

> 记录重构过程中已发生的重要变更。新增条目请加到最上面。

## v2.0.0-Beta-7(2026-06-29)

### 发布自动化

- 新增 `.github/workflows/windows-exe.yml`：支持手动触发选择 `Beta` / `Status` 渠道，在 `windows-latest` 上构建前端、安装后端依赖和 PyInstaller，打包真正可运行的 Windows exe。
- 推送 `v*` tag 时自动打包并上传 workflow artifact；tag 运行还会把 exe 上传到对应 GitHub Release asset。Linux 本机不再尝试交叉编译 Windows exe。
- 更新 `AI/COMMANDS.md`、`AI/OVERVIEW.md`、`AI/ARCHITECTURE.md`，记录 Windows exe 自动化打包流程、触发方式和 Linux 不能直接产出 Windows exe 的限制。

## v2.0.0-Beta-6(2026-06-29)

### 文档站

- 新增根目录 VitePress 文档站工程：`package.json` 提供 `docs:dev` / `docs:build` / `docs:preview`，配置位于 `docs/.vitepress/config.mts`。
- `docs/` 从历史版本说明扩展为用户文档、部署文档、第三方开放 API 文档和版本记录的统一入口；`AI/` 继续作为 Agent/开发交接文档，不面向普通用户。
- 文档站默认使用统一后端端口 `18765`，导航覆盖用户指南、部署、开放 API、版本记录。
- 新增 `.github/workflows/docs.yml`，推送 `main` 后通过 GitHub Actions 构建并发布 VitePress 到 GitHub Pages；自定义域名为 `nfm-docs.ruibin-ningh.top`，构建时设置 `DOCS_BASE=/`，并通过 `docs/public/CNAME` 写入 Pages 域名。

## v2.0.0-Beta-5(2026-06-29)

### Windows 迁移包

- 新增 `deploy/windows_entry.py` 作为 PyInstaller/Windows exe 专用入口：默认使用 `%LOCALAPPDATA%\Notion-Files-Management` 数据目录，启动窗口打印 config/logs/staging 路径，监听统一后端端口 `127.0.0.1:18765`（可用 `NFM_PORT` 覆盖），并在启动后打开默认浏览器。
- `deploy/nfm.spec` 改为使用 Windows 专用入口，产物名为 `NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe`。Docker/systemd/源码运行仍使用原服务端入口，不受影响。

### 安全加固（API Key 开放能力）

- **移除 `?api_key=` query 用法**：长期 API Key 永远只走 `Authorization: Bearer`，任何接口都不再接受 URL query 参数（避免明文进访问日志/Referer）。`deps._resolve_token` 删除，`resolve_auth`/`require_events_access` 不再读 query。
- **短期 SSE token**：新增 `app/ssetokens.py` 与 `POST /api/tasks/{tid}/events-token`（需 session 或 `tasks` scope），返回 `nfmsse_` token，10 分钟有效、绑定单个 task_id、进程内存储。`GET /{tid}/events` 改用 `deps.require_events_access`（session / Bearer+tasks / events_token 三选一），不再挂路由级 `require_scope`。`?events_token=` 是唯一允许出现在 URL 的凭据。
- **hash 常量时间比较**：`apikeys.verify_key` 改用 `secrets.compare_digest`。
- **弱 bootstrap key 拒绝**：`NFM_BOOTSTRAP_API_KEY` 必须是 `nfm_` 前缀 + 负载 ≥ 32 字符；不合格忽略并 warning，不自动补前缀。
- **严格 scope 校验**：`_normalize_scopes` 遇到未知 scope 直接抛 ValueError（路由转 400），不再静默过滤。
- **PATCH 清空过期时间**：`PATCH /api/apikeys/{id}` 改用 `body.model_fields_set` + `update_key` 的 `_UNSET` 哨兵，`{"expires_at": null}` 可清空过期时间。过期时间统一存 UTC ISO。
- **动态 CORS**：新增 `app/cors.py` `DynamicCORSMiddleware`，常驻、每次请求实时读 `config["api_cors_allowed_origins"]`，改设置无需重启。仅放行 `http(s)` origin，拒绝 `*`/`null`/带 path 的值；preflight 只对白名单 origin 返回 CORS 头。`SettingsIn` 增加 `api_cors_allowed_origins` 字段及校验。

### 前端

- `ApiKeys.vue`：过期时间按本地时间选择、提交转 UTC ISO（`toISOString`）、展示本地；创建明文弹窗关闭后立即清空 `plaintext`；`--text-muted` 修正为项目已有的 `--app-muted`；新增「跨域允许源」面板（读 `/api/settings`、增删、`PUT` 保存）。
- SSE 示例改为先换 `events_token`，不展示长期 key 放 URL 的用法。

### 文档

- 更新 `AI/ARCHITECTURE.md`、`AI/COMMANDS.md`、`AI/GOTCHAS.md`(第 24-27 条)、`AI/SECURITY_AUDIT.md`、`CLAUDE.md`：明确「长期 API Key 永远只走 Bearer；URL query 只允许短期 SSE token」。

## v2.0.0-Beta-4(2026-06-29)

### 新增

- **第三方开放 API + API Key 鉴权**：业务接口除原有 session cookie 外，新增 `Authorization: Bearer nfm_...` 双通道鉴权。API Key 支持命名、权限范围(scope)、可选过期、启停、删除、轻量限流(每分钟请求数)、最后使用记录；明文只创建时返回一次，落盘只存 sha256 hash。新增 `backend/app/apikeys.py` 与 `backend/app/routers/apikeys.py`(`GET/POST /api/apikeys`、`PATCH/DELETE /api/apikeys/{id}`)。新增前端 `frontend/src/views/ApiKeys.vue` 与 `/api-keys` 路由、侧栏入口。
- **scope 权限模型**：业务能力 `scan/download/upload/tools/tasks`，高危能力 `settings/system/logs/cache/apikeys`(需显式授权)。每个路由用 `deps.require_scope(...)` 声明所需 scope；session 登录的浏览器始终是全权限管理员，不受 scope 约束。`system` 路由按端点拆 `logs/cache/system` 三个 scope。
- **SSE/EventSource 兜底**：EventSource 不能自定义请求头，第三方用 `?api_key=<plaintext>` 查询参数访问 `/api/tasks/{tid}/events`。
- **CORS 白名单**：新增配置 `api_cors_allowed_origins`(env `NFM_API_CORS_ALLOWED_ORIGINS`，逗号分隔)，默认空(不开放跨域)。非空时启用 `CORSMiddleware`，仅允许白名单 origin，不允许 `*` 搭配凭据。
- **预置 key**：env `NFM_BOOTSTRAP_API_KEY` 可在首启时以 hash 落盘一条全权限 key，便于部署/CI 注入；重复启动不重复创建。

### 调整

- `backend/app/deps.py` 由「单一 session 校验」重写为双通道：session 优先，否则校验 Bearer/query key；未认证 401、缺 scope 403、限流超限 429、禁用/过期/伪造 key 一律 401。
- `backend/app/config.py` 新增 `api_keys`/`api_cors_allowed_origins` 默认值；`public_dict` 剔除 `api_keys`(避免 hash 经 `/api/settings` 泄露)。
- `scan/download/upload/tools/tasks/settings` 路由由 `require_auth` 改为 `require_scope(...)`；`system` 路由改为按端点声明 scope。

## v2.0.0-Beta-3(2026-06-28)

### 修复

- **Download 页探测期间选中文件仍会被刷新清空**：`<el-table>` 只有 `row-key="url"` 不够,selection 列也需要 `reserve-selection` 才会在 `scanItems` 整组替换后保留选择。已给 `frontend/src/views/Download.vue` 的 selection column 补上 `reserve-selection`。
- **扫描页面文件完成后进度不是 100%**：扫描 poll 在 `done=true` 时可能保留 `status=probing`,任务看板不会按完成任务显示 100%。已在 `notion_facade.py` 中为扫描任务补 `percent`,终态统一 `status=done`;前端任务看板也对非错误终态做 100% 兜底。
- **Range 分片实验开关误判和未知大小回退**：日志显示 `enable_range_download=False` 时仍进入 `[DownloadRange] fallback`,原因是字符串 `"False"` 被 `bool()` 判真。已新增布尔归一化,关闭分片时不再进入 Range 分支。另修复 `manual_size_mb=0` 时大文件被 `below_threshold` 错误回退的问题:开启分片后未知大小会先 Range 探测总大小,再按阈值决策。

### 新增

- **启动日志信息块**：后端 logger 初始化后立即输出 `NFM STARTUP` 固定块,包含程序版本、渠道、启动时间、构建时间、发行时间、Python/平台、数据目录、日志目录、staging 目录和关键配置。Token 只记录是否配置,不记录密钥内容。`NFM_BUILD_TIME` / `NFM_RELEASE_TIME` 可由打包/发布流程注入。
- **全局任务看板**：新增 `frontend/src/views/Tasks.vue` 和 `/tasks` 路由,任务不再局限在上传/下载页面内查看。任务看板支持列表筛选、运行中取消、终态任务重试、下载任务 ZIP 入口。
- **任务详情展开区**：任务看板每个任务新增「详情」折叠区。上传/下载任务展示每个文件的进度条、状态、已传/已下载大小、总大小、速率、ETA 和错误信息;其它任务展示关键进度字段。
- **扫描任务详情结果**：任务看板展开扫描任务详情时,懒加载 `/api/scan/{task_id}/list` 并展示扫描到的文件名、大小和来源标识,避免每次 SSE 都携带完整扫描结果。
- **下载性能诊断**：下载任务进度新增 `perf` 聚合指标,包括下载并发、排队文件数、当前总速率、平均速率、已下载量、耗时和排队压力。任务看板详情区展示性能诊断和每个文件的等待/耗时,用于排查下载慢的问题。
- **下载性能日志**：下载底层新增单文件 start/completed 日志;任务 poll 每 30 秒写一条 `[DownloadPerf]` 汇总,包含文件完成数、活跃/排队、总速率、平均速率、已下载量、耗时和活跃文件速率。
- **实验性 Range 分片下载**：新增 `enable_range_download`、`range_download_min_mb`、`range_download_chunks` 配置,默认关闭。开启后仅对超过阈值且 Range 探测成功的文件分片下载;任务详情展示单连接/分片模式,日志输出 `[DownloadRange] probe/start/completed/fallback/failed`。
- **缓存可读名称**：上传/下载/生成 zip 缓存新增 `.nfm-cache.json` / `*.meta.json` 元数据,`GET /api/cache/items` 同时返回稳定 `id`、可读 `name` 和 `storage_name`。缓存页主展示业务名称,辅助展示底层存储 ID,避免纯随机 ID 难以识别。
- **全局任务 store**：新增 `frontend/src/stores/tasks.ts`,统一 `GET /api/tasks`、SSE 订阅、取消和重试。主页 `Dashboard.vue` 增加最近任务小面板。
- **任务元数据/重试 API**：`backend/app/taskregistry.py` 的 `TaskHandle` 增加 `title/source/input/artifact/cache_refs/retry_fn` 等字段;`backend/app/routers/tasks.py` 新增 `GET /api/tasks/{tid}` 和 `POST /api/tasks/{tid}/retry`。
- **云端缓存页面**：新增 `frontend/src/views/Cache.vue` 和 `/cache` 路由,可查看、下载、删除、按策略清理 `${NFM_DATA_DIR}/staging` 下的上传缓存、下载产物和生成 zip。
- **缓存管理 API**：`backend/app/staging.py` 新增缓存列表、单项删除、单项下载定位、保护路径清理;`backend/app/routers/system.py` 新增 `/api/cache/items`、`/api/cache/items/{id}/download`、`DELETE /api/cache/items/{id}`、`/api/cache/cleanup`。
- **缓存策略配置**：`config.py` / `settings.py` / `Settings.vue` 增加 `cache_auto_cleanup_enabled`、`cache_ttl_seconds`、`cache_cleanup_interval_seconds`。`main.py` 启动时清理一次,并在非 pytest 环境启动 daemon `CacheCleanup` 线程定期清理。

### 调整

- `Upload.vue` / `Download.vue` 创建云端上传/下载任务后,把任务注册到全局 `tasks` store,再询问是否前往任务看板管理。
- `Upload.vue` / `Download.vue` 创建任务后不再自动跳转任务看板,改为弹窗提示「已创建任务，是否前往任务看板查看？」,用户确认后再跳转。
- `Tasks.vue` 任务列表 UI 重构为紧凑任务队列:顶部统计改为小型状态 pill,单条任务横向展示状态、标题、进度、摘要和操作;详情区改为指标条 + 明细表,移动端纵向堆叠避免横向溢出。
- 新建上传缓存目录改为 `upload-<id>`,下载产物目录改为 `download-<id>`,生成 zip 改为 `generated-*.zip`,便于缓存页面分类。
- 下载单文件接口优先使用 `save_name`,避免同名文件去重后按 `real_name` 找不到实际保存文件。

## v2.0.0-Beta-2(2026-06-28)

### 修复

- **Download 页探测期间无法选中文件**：扫描进行中每 800ms 刷新 `scanItems`，整组对象被替换后 `<el-table>`（无 `row-key`）按对象引用追踪选中行，引用一变就派发 `selection-change=[]` 把 `selected.value` 清空，用户体感"选不上"。给 `frontend/src/views/Download.vue:57` 的 `<el-table>` 加 `row-key="url"`（item 的 `url` 在 `backend/scripts/notion.py:163-212` 唯一）。后续在 `v2.0.0-Beta-3` 补齐 selection column 的 `reserve-selection`。

## v2.0.0-Beta-1(2026-06-28)

### 新增

- `frontend/src/views/Download.vue` —— 下载完成后显示「重新下载」按钮，可用上一次下载的文件列表再次发起下载任务。
- 全部文件下载成功后自动弹出 `ElMessageBox.confirm` 提示「是否再下载一次」；确认后清空当前表单（Page ID、扫描结果、选中项、任务状态），回到初始空白状态。
- `frontend/src/layouts/MainLayout.vue` + `frontend/src/views/Download.vue` + `frontend/src/composables/useTask.ts` —— Download 页通过 `<keep-alive>` 缓存组件实例，切到其它页面再回来保留扫描结果、选中文件、下载进度；切走时自动关闭 SSE/轮询，切回时通过 `useTask.reconnect()` 无闪烁恢复订阅。

## v2.0.0-Beta-0(2026-06-28)（重构首发）

**时间**：2026-06-28
**Tag 归档**：`v1.5.2-legacy-wpf` 指向重构前的最后一个 C# 提交（`c46c08d`）。

### 移除

- 全部 C# / WPF 桌面代码：
  - `.cs` / `.xaml` / `.csproj` / `.sln` / `.csproj.user`
  - `Models/` `Services/` `Utils/` `Views/` `.vs/`
  - `PUBLIST-*.bat`
  - `AppConfig.cs` `AppVersion.cs` `AssemblyInfo.cs`
  - `MainWindow.xaml(.cs)` `App.xaml(.cs)`
- 旧 `Scripts/` 目录（已平移到 `backend/scripts/`）
- `screenshot/`（WPF 截图）

### 新增

#### 后端 (`backend/`)

- `app/main.py` —— FastAPI 入口，SessionMiddleware、路由聚合、缓存清理线程、前端静态托管、SPA fallback
- `app/config.py` —— `Config` 类：env + `config.json` 合并
- `app/deps.py` —— `require_auth` 依赖
- `app/taskregistry.py` —— **任务注册表 + SSE 推送**（核心）
- `app/staging.py` —— 暂存目录 / zip 打包 / TTL 清理 / 日志列表
- `app/notion_facade.py` —— **Notion 业务 facade**（替代原 C# 的 `Main` 类，按任务隔离）
- `app/app_version.py` —— `BASE_VERSION = "2.0.0"`，按当前渠道派生 `2.0.0-Beta`；文档修订号 `N` 仅用于 CHANGELOG/docs 的章节区分，代码 `APP_VERSION` 不带 `N`
- `app/routers/auth.py` —— 登录/登出/检查
- `app/routers/settings.py` —— 配置读写
- `app/routers/version.py` —— 代理远程 `version.json`（公开）
- `app/routers/notices.py` —— 公告列表/详情（已读管理 + 本地缓存）
- `app/routers/scan.py` —— 启动扫描 + 拉取文件列表
- `app/routers/download.py` —— 启动下载 + 单文件/zip 流式取回
- `app/routers/upload.py` —— 收文件 + 启动上传（文件/文件夹）
- `app/routers/tools.py` —— 4 个 Notion 工具（页面大小、迁移、去后缀、属性查询）
- `app/routers/tasks.py` —— 任务列表 / SSE 事件流 / 取消
- `app/routers/system.py` —— 日志/清缓存/重启
- `scripts/scan.py` —— **新的** `ScanSession`（从 `main.py` 流式扫描逻辑提取，每任务独立）
- `scripts/{notion,download,upload,migrate,batch_rename,page_size_update,logger}.py` —— 从原 `Scripts/` **几乎未改**地平移
- `tests/__init__.py` `tests/test_smoke.py` —— pytest 冒烟测试

#### 前端 (`frontend/`)

- `package.json` + `vite.config.ts` + `tsconfig.json` + `index.html`
- `src/main.ts` —— createApp、Pinia、Router、Element Plus（暗色 + zh-cn）、全局注册 icons
- `src/App.vue` —— 根路由 + 全局主题色注入
- `src/router.ts` —— 路由表 + 鉴权守卫
- `src/api/client.ts` —— axios 实例 + 401 自动跳转登录
- `src/stores/auth.ts` —— 鉴权状态
- `src/stores/config.ts` —— 配置状态
- `src/composables/useTask.ts` —— **SSE 订阅 composable**（`reactive state` 模式）
- `src/utils/pageId.ts` —— NotionPageId TS 移植
- `src/utils/format.ts` —— 大小/时间格式化
- `src/assets/main.css` —— 全局暗色样式
- `src/layouts/MainLayout.vue` —— 侧栏 + 顶栏 + router-view
- `src/views/Login.vue` —— 登录页
- `src/views/Dashboard.vue` —— 主页
- `src/views/Notice.vue` —— 公告（markdown-it 渲染）
- `src/views/Upload.vue` —— 上传（文件/文件夹）
- `src/views/Download.vue` —— 下载（流式扫描→勾选→下载）
- `src/views/Tools.vue` —— 4 工具（4 个 tab）
- `src/views/Settings.vue` —— 设置

#### 部署

- `docker/Dockerfile` —— 多阶段：node 构建前端 → python:3.11-slim 运行
- `docker/docker-compose.yml` —— 单容器 + volume
- `deploy/nfm.spec` —— PyInstaller 打包规范
- `deploy/run.py` —— PyInstaller 入口
- `deploy/systemd/nfm.service` —— systemd unit（venv+uvicorn）

#### 文档

- `README.md` —— **完全重写**为 Web 版（Docker / 独立部署 / 功能表）
- `AI/README.md` + `AI/OVERVIEW.md` + `AI/ARCHITECTURE.md` + `AI/COMMANDS.md` + `AI/GOTCHAS.md` + `AI/CHANGELOG.md` —— **新增**的 AI 交接文档系统

### 关键设计决策

1. **每任务一个 `Download` 实例**：原 C# 的 `Main.downloader` 全局状态会导致多用户冲突。Facade 每次 `start_download` 都 `new Download`。
2. **每任务一个 `Upload` 实例**：同理，文件路径按 `file_path` 隔离。
3. **`ScanSession` 独立实例**：流式扫描的 `_scan_status` / `download_list` / `_stream_probe_queue` 是状态，跨任务会污染。
4. **SSE 终态事件统一为 `done`**：避免与 EventSource 原生 `error` 事件冲突。
5. **`useTask` 返回 `reactive state`**：避免 vue 模板中嵌套 ref 不自动解包的坑。
6. **同步 facade 方法直接调用**：fastapi 路由 async 调 sync facade，省去 `anyio.to_thread` 开销（`start_*` 都不阻塞）。

### 验证

- ✅ 后端 `py_compile` 通过
- ✅ 后端 app 加载 34 个路由
- ✅ pytest 冒烟 4/4 通过
- ✅ 前端 `vue-tsc` 零错误
- ✅ 前端 `vite build` 成功
- ✅ 集成：vite (5173) → uvicorn (18765) 全链路
- ✅ 鉴权：未登录 401 / 错密码 401 / 正密码 200 / cookie 携带
- ✅ 公开端点（`/api/version`）无需鉴权

### 已知限制

- 后端默认端口已统一为 `:18765`；`vite.config.ts`、Docker/systemd/Windows 入口需保持一致。
- 全局 Notion 速率限制器（`ratelimit.py`）未实现。
- 后端没有 `pageId` normalize 工具（依赖前端 `utils/pageId.ts`）。
- 断点续传未实现。
- PyInstaller / systemd 文档已写但未在干净环境实际部署验证。

## 渠道机制（Status / Beta）

**时间**：2026-06-28
**背景**：原 C# 版本区分 Status（正式版）和 Beta（预发布）两个渠道，重构时未保留。补上。

### 设计

- **语义**：`Status` = 正式版，`Beta` = 预发布。`channel` 字段在 `config.json` 中，启动时通过 `NFM_CHANNEL` 环境变量覆盖。
- **默认值**：`Beta`。
- **API 隔离**：`Status` 调 `nfm.ruibin-ningh.top/*`，`Beta` 调 `beta.nfm.ruibin-ningh.top/*`。**不同渠道的版本更新/公告走不同 endpoint**，避免 Beta 用户被 Status 强升，也避免 Status 用户收到 Beta 内容。
- **Web 不可改**：Settings 页不暴露 channel 字段（防止误改），仅展示当前渠道。

### 变更

- `backend/app/app_version.py` —— 新增 `VALID_CHANNELS` / `DEFAULT_CHANNEL` / `current_channel()`
- `backend/app/config.py` —— `channel` 加入 `_DEFAULTS`；`load()` 让 `NFM_CHANNEL` env 覆盖；`_bootstrap` 首次启动写入 channel；新增 `Config.channel` 属性
- `backend/app/routers/version.py` —— 按 channel 选择 endpoint；新增 `GET /api/version/channel` 公开端点返回当前渠道
- `backend/app/routers/notices.py` —— 按 channel 选择公告 endpoint
- `backend/app/routers/settings.py` —— `SettingsIn` 显式排除 channel（仅 env 改）
- `frontend/src/views/Settings.vue` —— 当前版本后展示渠道徽章（正式版/预发布 Beta）
- `frontend/src/layouts/MainLayout.vue` —— 顶栏新增渠道徽章

### 启动方式

```bash
# Status（正式版，默认）
NFM_CHANNEL=Status uvicorn app.main:app --app-dir backend

# Beta（预发布）
NFM_CHANNEL=Beta uvicorn app.main:app --app-dir backend
```

### 验证

```
$ curl -s http://127.0.0.1:18765/api/version/channel
{"channel":"Status","valid":["Status","Beta"]}

$ NFM_CHANNEL=Beta ... curl -s .../api/version/channel
{"channel":"Beta","valid":["Status","Beta"]}

$ curl -s -b cookie .../api/settings
{...,"channel":"Status"}

✓ 前端 vue-tsc 零错误
✓ vite (5173) → uvicorn (18765) 全链路，channel 字段经 vite proxy 透传
