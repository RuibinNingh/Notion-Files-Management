# 常用命令

> 当前服务在跑：vite (5173) + uvicorn (8765)。本机 8000 被 `homepage` 占着。

## 🚀 启动

### 后端（FastAPI）

```bash
cd /home/ruibinningh/projects/Notion-Files-Management

# 标准端口（如果 8000 空闲）
NFM_DATA_DIR=/tmp/nfm-run NFM_PASSWORD=admin123 \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# 当前用的：端口 8765
NFM_DATA_DIR=/tmp/nfm-run NFM_PASSWORD=admin123 \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765
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

⚠️ **dev 模式 proxy 目标在 `vite.config.ts`**：当前是 `127.0.0.1:8765`（避开 8000）。改回标准后端时同步修改。

### 前端构建（生产用）

```bash
cd frontend
npm run build   # 产物到 frontend/dist/
```

构建产物会被后端作为静态文件托管（`main.py` 的 SPA fallback）。

### Docker（生产推荐）

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker logs -f nfm                  # 看初始密码
```

访问 `http://<服务器>:8000`。

---

## 🛑 停止

```bash
# 找进程
ps -ef | grep -E "uvicorn|vite|npm run dev" | grep -v grep

# 或按端口
ss -tlnp 2>/dev/null | grep -E ":(5173|8765|8000)\s"

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
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/api/version

# 2. 登录拿 cookie
curl -s -c /tmp/cookie -X POST -H 'Content-Type: application/json' \
  -d '{"password":"admin123"}' http://127.0.0.1:8765/api/auth/login

# 3. 用 cookie 拉设置
curl -s -b /tmp/cookie http://127.0.0.1:8765/api/settings

# 4. SSE 探测（找一个不存在的任务）
curl -s -b /tmp/cookie -w "\nstatus=%{http_code}\n" http://127.0.0.1:8765/api/tasks/nonexistent/events

# 5. 真实扫描（需要先在设置页填 Notion Token 并加 Integration）
curl -s -b /tmp/cookie -X POST -H 'Content-Type: application/json' \
  -d '{"page_id":"<your-page-id>","probe_workers":4}' http://127.0.0.1:8765/api/scan
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
curl -s -b /tmp/cookie http://127.0.0.1:8765/api/tasks | python3 -m json.tool
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

### PyInstaller 单文件

```bash
# 先构建前端（前端产物会被 PyInstaller 打进 nfm 二进制）
cd frontend && npm run build && cd ..

.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller deploy/nfm.spec --noconfirm
# 产物：dist/nfm

NFM_DATA_DIR=/var/lib/nfm ./dist/nfm
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
curl -s -b /tmp/cookie -X POST http://127.0.0.1:8765/api/cache/clear

# 查看缓存项
curl -s -b /tmp/cookie http://127.0.0.1:8765/api/cache/items

# 按当前 TTL 策略清理
curl -s -b /tmp/cookie -X POST http://127.0.0.1:8765/api/cache/cleanup
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
NFM_ENABLE_RANGE_DOWNLOAD=false .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765

# 实验:开启分片,128MB 以上文件分 4 片
NFM_ENABLE_RANGE_DOWNLOAD=true \
NFM_RANGE_DOWNLOAD_MIN_MB=128 \
NFM_RANGE_DOWNLOAD_CHUNKS=4 \
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765
```

看日志时重点比较 `[DownloadPerf]` 的 `speed_mb_s` / `avg_mb_s`,以及 `[DownloadRange] probe/start/completed/fallback/failed`。
