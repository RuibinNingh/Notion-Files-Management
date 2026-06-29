# 常用命令

> 当前统一端口：vite (5173) + uvicorn (18765)。后端/API 默认都用 18765。

## 🚀 启动

### 后端（FastAPI）

```bash
cd /home/ruibinningh/projects/Notion-Files-Management

# 统一后端端口 18765
NFM_DATA_DIR=/tmp/nfm-run NFM_PASSWORD=admin123 \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765
```

**首次启动**会生成：
- `${NFM_DATA_DIR}/config.json` —— 含 `secret_key` 和初始 `password`
- 控制台打印初始密码

**环境变量**（`AI/OVERVIEW.md` 也列过）：
| 变量 | 默认 | 用途 |
|------|------|------|
| `NFM_DATA_DIR` | `~/.notion-files-management` | 配置/暂存/日志/缓存根 |
| `NFM_PASSWORD` | （启动时随机生成）| 访问密码 |
| `NFM_NOTION_TOKEN` | （设置页填）| Notion Integration Token |
| `NFM_NOTION_BASE_URL` | `https://api.notion.com/v1` | Notion API 地址 |
| `NFM_MAX_DOWNLOAD_WORKERS` | `3` | 下载并发 |
| `NFM_MAX_UPLOAD_WORKERS` | `3` | 上传并发 |
| `NFM_CACHE_AUTO_CLEANUP_ENABLED` | `true` | 是否自动清理 staging 缓存 |
| `NFM_CACHE_TTL_SECONDS` | `3600` | 缓存保留时间 |
| `NFM_CACHE_CLEANUP_INTERVAL_SECONDS` | `900` | 自动清理间隔 |
| `NFM_BUILD_TIME` | `development` | 构建时间,写入启动日志 |
| `NFM_RELEASE_TIME` | `development` | 发行时间,写入启动日志 |
| `NFM_FRONTEND_DIST` | `frontend/dist` | 前端构建产物路径（PyInstaller 用）|

### 前端（Vite dev）

```bash
cd frontend
npm run dev    # http://localhost:5173

# 指定端口 / host
npm run dev -- --host 0.0.0.0 --port 5173
```

⚠️ **dev 模式 proxy 目标在 `vite.config.ts`**：当前是 `127.0.0.1:18765`。如果以后改端口，Docker/systemd/Windows 入口也要同步。

### 前端构建（生产用）

```bash
cd frontend
npm run build   # 产物到 frontend/dist/
```

构建产物会被后端作为静态文件托管（`main.py` 的 SPA fallback）。

### 文档站（VitePress）

```bash
# 根目录执行；不要在 frontend/ 下执行
npm install
npm run docs:dev      # 本地预览 VitePress 文档站
npm run docs:build    # 构建到 docs/.vitepress/dist/
npm run docs:preview  # 预览构建产物
```

文档站源码在 `docs/`，配置在 `docs/.vitepress/config.mts`。`AI/` 仍是 Agent/开发交接文档，不作为普通用户文档发布。

GitHub Pages 部署走 `.github/workflows/docs.yml`，文档站自定义域名为 `nfm-docs.ruibin-ningh.top`。自定义域名挂在根路径，workflow 构建时设置：

```bash
DOCS_BASE=/
```

`docs/public/CNAME` 会被 VitePress 复制到构建产物根目录，用于 GitHub Pages 识别自定义域名。DNS 侧需要配置 `nfm-docs.ruibin-ningh.top CNAME ruibinningh.github.io`。

⚠️ 当前 VitePress 最新版 `1.6.4` 依赖链里 `npm audit` 会报告 Vite/esbuild dev server 漏洞且暂无上游修复；不要把 `docs:dev` 暴露到公网。发布静态构建产物不受 dev server 影响。

### Docker（生产推荐）

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker logs -f nfm                  # 看初始密码
```

访问 `http://<服务器>:18765`。

---

## 🛑 停止

```bash
# 找进程
ps -ef | grep -E "uvicorn|vite|npm run dev" | grep -v grep

# 或按端口
ss -tlnp 2>/dev/null | grep -E ":(5173|18765|8000)\s"

# kill
kill <PID>
# 强杀
kill -9 <PID>
```

如果 npm run dev 起了一坨子进程：`pkill -f "vite --host"`。

---

## 🧪 测试

### 冒烟测试（pytest）

```bash
cd /home/ruibinningh/projects/Notion-Files-Management
.venv/bin/pytest backend/tests -q
```

包含：未鉴权 401、错误密码 401、登录+配置+任务列表流程、SSE 404。

### 手工测试清单

```bash
# 1. 后端进程在吗？
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18765/api/version

# 2. 登录拿 cookie
curl -s -c /tmp/cookie -X POST -H 'Content-Type: application/json' \
  -d '{"password":"admin123"}' http://127.0.0.1:18765/api/auth/login

# 3. 用 cookie 拉设置
curl -s -b /tmp/cookie http://127.0.0.1:18765/api/settings

# 4. SSE 探测（找一个不存在的任务）
curl -s -b /tmp/cookie -w "\nstatus=%{http_code}\n" http://127.0.0.1:18765/api/tasks/nonexistent/events

# 5. 真实扫描（需要先在设置页填 Notion Token 并加 Integration）
curl -s -b /tmp/cookie -X POST -H 'Content-Type: application/json' \
  -d '{"page_id":"<your-page-id>","probe_workers":4}' http://127.0.0.1:18765/api/scan
```

### 浏览器调试

- F12 → Network → 看 `/api/*` 请求
- F12 → Console → 输入 `localStorage` / 检查 cookie `session=...`
- F12 → Network → EventStream 看 SSE 实时事件

---

## 🐛 调试技巧

### 后端日志

```bash
# 当前后端日志
tail -f /tmp/nfm-run/backend.log

# Python 日志目录（持久化）
ls -la ~/.notion-files-management/logs/    # 或 ${NFM_DATA_DIR}/logs/
```

格式：`[HH:mm:ss.fff][T<thread>][LEVEL] message`

### 临时改 logger level

`main.py` 里 uvicorn 用默认 log_level。加 `--reload --log-level debug` 启动也行（但 dev 时 reload 会清掉任务状态）。

### 看任务列表

```bash
curl -s -b /tmp/cookie http://127.0.0.1:18765/api/tasks | python3 -m json.tool
```

### 跑单独的 Python 脚本

```bash
cd backend
NFM_DATA_DIR=/tmp/nfm-run ../.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from notion import Notion
n = Notion('ntn_xxx')
print(n.get_database_properties('your-ds-id'))
"
```

---

## 📦 打包

### PyInstaller 单文件 / Windows exe

```bash
# 先构建前端（前端产物会被 PyInstaller 打进 nfm 二进制）
cd frontend && npm run build && cd ..

.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller deploy/nfm.spec --noconfirm
# 产物：dist/NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe
#
# Windows exe 使用 deploy/windows_entry.py：
# - 默认数据目录：%LOCALAPPDATA%\Notion-Files-Management
# - 配置文件：%LOCALAPPDATA%\Notion-Files-Management\config.json
# - 日志目录：%LOCALAPPDATA%\Notion-Files-Management\logs
# - 缓存目录：%LOCALAPPDATA%\Notion-Files-Management\staging
# - 默认监听：127.0.0.1:18765
# - 如需覆盖端口，可设置 NFM_PORT
# - 启动后自动打开浏览器

# Linux 服务器仍推荐 Docker 或 systemd + venv；此 spec 面向 Windows 迁移包。
```

### systemd 部署

```bash
sudo install -d /opt/nfm && sudo cp -r backend /opt/nfm/
sudo cp -r frontend/dist /opt/nfm/frontend/
sudo /opt/nfm/venv/bin/pip install -r /opt/nfm/backend/requirements.txt
sudo install -d /var/lib/nfm
sudo cp deploy/systemd/nfm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nfm
sudo journalctl -u nfm -f
```

---

## 🔧 维护常用

### 清理 staging 缓存（默认 1h 自动清理）

```bash
# 手动：删 staging/ 下所有
rm -rf /tmp/nfm-run/staging/*

# 或调 API（认证后）
curl -s -b /tmp/cookie -X POST http://127.0.0.1:18765/api/cache/clear

# 查看缓存项
curl -s -b /tmp/cookie http://127.0.0.1:18765/api/cache/items

# 按当前 TTL 策略清理
curl -s -b /tmp/cookie -X POST http://127.0.0.1:18765/api/cache/cleanup
```

### 重置密码（编辑 config.json）

```bash
# 改 JSON 中的 password 字段（重启后生效）
vim /tmp/nfm-run/config.json
# 重启后端
kill <PID>; NFM_DATA_DIR=/tmp/nfm-run NFM_PASSWORD=新密码 .venv/bin/python -m uvicorn ...
```

### 重置 secret_key（让所有 session 失效）

```bash
# 删 config.json 重启，secret_key 会重新生成
rm /tmp/nfm-run/config.json
```

### 看 Python 日志

```bash
ls -la /tmp/nfm-run/logs/ | tail
tail -f /tmp/nfm-run/logs/$(ls -t /tmp/nfm-run/logs/ | head -1)
```

### 实验性 Range 分片下载对比

```bash
# 基线:关闭分片
NFM_ENABLE_RANGE_DOWNLOAD=false .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765

# 实验:开启分片,128MB 以上文件分 4 片
NFM_ENABLE_RANGE_DOWNLOAD=true \
NFM_RANGE_DOWNLOAD_MIN_MB=128 \
NFM_RANGE_DOWNLOAD_CHUNKS=4 \
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765
```

看日志时重点比较 `[DownloadPerf]` 的 `speed_mb_s` / `avg_mb_s`,以及 `[DownloadRange] probe/start/completed/fallback/failed`。

## 🔌 第三方开放 API 调用示例

业务接口除浏览器 session 外，支持 `Authorization: Bearer nfm_<明文>`。API Key 在「API 密钥」页(`/api-keys`)创建，明文只显示一次。

### 鉴权与扫描

```bash
# 用 Bearer key 发起扫描（key 需带 scan scope）
curl -X POST http://127.0.0.1:18765/api/scan \
  -H "Authorization: Bearer nfm_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"page_id":"<32位页面ID>","probe_workers":8}'
# => {"task_id":"t_xxx"}
```

### 查询任务

```bash
# 列表（需 tasks scope）
curl -H "Authorization: Bearer nfm_xxxxxxxx" http://127.0.0.1:18765/api/tasks

# 单任务详情
curl -H "Authorization: Bearer nfm_xxxxxxxx" http://127.0.0.1:18765/api/tasks/<task_id>
```

### SSE 进度（长期 key 不放 URL，先换短期 events_token）

`EventSource` 不能自定义请求头，长期 API Key 又永远只走 Bearer、不放进 URL。所以先换一个 10 分钟有效的短期 token：

```bash
# 1) 用 Bearer key（需 tasks scope）换短期 token
TOK=$(curl -s -X POST -H "Authorization: Bearer nfm_xxxxxxxx" \
  http://127.0.0.1:18765/api/tasks/<task_id>/events-token | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
# => nfmsse_...

# 2) 用 events_token 订阅 SSE（curl）
curl -N -H "Accept: text/event-stream" \
  "http://127.0.0.1:18765/api/tasks/<task_id>/events?events_token=$TOK"
```

> `?events_token=` 是唯一允许出现在 URL 的凭据，短期（10 分钟）且绑定单个 task。`?api_key=` 已废弃，任何接口都返回 401。

浏览器 JS：

```js
// 先换 token（用 fetch 带 Bearer），再用 EventSource 订阅
const r = await fetch('/api/tasks/<task_id>/events-token', {
  headers: { Authorization: 'Bearer nfm_xxxxxxxx' },
})
const { token } = await r.json()
const es = new EventSource(`/api/tasks/<task_id>/events?events_token=${token}`)
es.addEventListener('progress', e => console.log(JSON.parse(e.data)))
es.addEventListener('done', e => {
  const d = JSON.parse(e.data)   // d.status: 'done' | 'error' | 'cancelled'
  es.close()
})
```

> 浏览器 session 登录时不需要这套——直接 `new EventSource('/api/tasks/<tid>/events', { withCredentials: true })` 即可（cookie 鉴权）。events_token 只给第三方用。

### 错误码

| 状态 | 含义 |
|------|------|
| 401 | 未登录 / API Key 无效、已禁用、已过期、伪造 / SSE token 无效或过期 |
| 403 | API Key 缺少所需 scope |
| 429 | 触发该 Key 的限流（每分钟请求数超限） |

### 跨域（CORS）

默认不开放跨域。白名单是**动态**的：在「API 密钥」页增删后立即生效，或启动时用 env 设置。仅允许 `http(s)` origin，禁 `*`/`null`/带路径。

```bash
NFM_API_CORS_ALLOWED_ORIGINS="https://your-app.example.com" \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 18765
```

### 部署时预置一条全权限 key

```bash
# 必须是 nfm_ 前缀 + 负载 ≥ 32 字符；弱值会被忽略并记 warning
NFM_BOOTSTRAP_API_KEY="nfm_<≥32字符随机串>" \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --port 18765
```

> 预置 key 以 hash 落盘，重复启动不重建；明文由部署方自行保管。
