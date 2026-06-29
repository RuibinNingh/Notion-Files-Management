# 调用示例

以下示例默认：

```bash
BASE="http://127.0.0.1:18765"
KEY="nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

Docker、systemd、Windows exe、本地开发都使用相同的默认端口。如果你配置了反向代理，把 `BASE` 换成自己的域名。

## curl

### 检查版本

`/api/version` 是公开接口：

```bash
curl -s "$BASE/api/version" | python3 -m json.tool
```

### 发起扫描

需要 scope：`scan`。通常还需要 `tasks` 来查看进度。

```bash
curl -s -X POST "$BASE/api/scan" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"page_id":"YOUR_NOTION_PAGE_ID","probe_workers":8}' \
  | python3 -m json.tool
```

响应示例：

```json
{
  "task_id": "t_xxxxxxxxxxxx"
}
```

### 读取任务详情

需要 scope：`tasks`。

```bash
TASK_ID="t_xxxxxxxxxxxx"

curl -s "$BASE/api/tasks/$TASK_ID" \
  -H "Authorization: Bearer $KEY" \
  | python3 -m json.tool
```

### 订阅 SSE 进度

换取短期 token 需要 scope：`tasks`。

```bash
TASK_ID="t_xxxxxxxxxxxx"

EVENTS_TOKEN=$(
  curl -s -X POST "$BASE/api/tasks/$TASK_ID/events-token" \
    -H "Authorization: Bearer $KEY" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])"
)

curl -N -H "Accept: text/event-stream" \
  "$BASE/api/tasks/$TASK_ID/events?events_token=$EVENTS_TOKEN"
```

典型事件流：

```text
event: progress
data: {"status":"running","progress":{}}

event: done
data: {"status":"done","error":null}
```

### 列出扫描结果

需要 scope：`scan`。

```bash
curl -s "$BASE/api/scan/$TASK_ID/list" \
  -H "Authorization: Bearer $KEY" \
  | python3 -m json.tool
```

### 从扫描结果创建下载任务

需要 scope：`download`。

扫描结果里的文件记录可以传给下载接口。每个下载 item 至少需要安全的远程 `url`。

```bash
curl -s -X POST "$BASE/api/download/start" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "url": "https://example.com/file.pdf",
        "real_name": "file.pdf",
        "size_mb": 1.2,
        "block_id": "optional-notion-block-id"
      }
    ]
  }' \
  | python3 -m json.tool
```

### 下载完成后的 ZIP

需要 scope：`download`。

```bash
DOWNLOAD_TASK_ID="t_downloadxxxx"

curl -L "$BASE/api/download/$DOWNLOAD_TASK_ID/zip" \
  -H "Authorization: Bearer $KEY" \
  -o nfm-download.zip
```

### 上传文件

需要 scope：`upload`。通常还需要 `tasks` 来查看进度。

先暂存文件：

```bash
curl -s -X POST "$BASE/api/upload/files" \
  -H "Authorization: Bearer $KEY" \
  -F "files=@./report.pdf" \
  -F "rels=report.pdf" \
  | python3 -m json.tool
```

响应里会包含 `session_id`。再启动上传：

```bash
SESSION_ID="upload-session-id-from-response"

curl -s -X POST "$BASE/api/upload/start" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"page_id\": \"YOUR_NOTION_PAGE_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"folder_mode\": false
  }" \
  | python3 -m json.tool
```

### 创建受限 API Key

需要 scope：`apikeys`，或浏览器管理员 session。

```bash
ADMIN_KEY="nfm_adminxxxxxxxxxxxxxxxxxxxxxxxx"

curl -s -X POST "$BASE/api/apikeys" \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "scan-download-bot",
    "scopes": ["scan", "download", "tasks"],
    "expires_at": null,
    "rate_limit_rpm": 120,
    "enabled": true
  }' \
  | python3 -m json.tool
```

## Python

下面示例使用 `requests` 发起扫描并跟随 SSE 进度。

```python
import json
import requests

BASE = "http://127.0.0.1:18765"
KEY = "nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {KEY}"})

scan_resp = session.post(
    f"{BASE}/api/scan",
    json={"page_id": "YOUR_NOTION_PAGE_ID", "probe_workers": 8},
    timeout=30,
)
scan_resp.raise_for_status()
task_id = scan_resp.json()["task_id"]
print("task:", task_id)

token_resp = session.post(f"{BASE}/api/tasks/{task_id}/events-token", timeout=30)
token_resp.raise_for_status()
events_token = token_resp.json()["token"]

with requests.get(
    f"{BASE}/api/tasks/{task_id}/events",
    params={"events_token": events_token},
    headers={"Accept": "text/event-stream"},
    stream=True,
    timeout=600,
) as resp:
    resp.raise_for_status()
    event = None
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if raw.startswith("event:"):
            event = raw.split(":", 1)[1].strip()
            continue
        if raw.startswith("data:"):
            data = json.loads(raw.split(":", 1)[1].strip())
            print(event, data)
            if event == "done":
                break
```

按状态码处理错误：

```python
try:
    r = session.get(f"{BASE}/api/tasks", timeout=30)
    r.raise_for_status()
except requests.HTTPError as exc:
    status = exc.response.status_code
    detail = exc.response.text
    if status == 401:
        raise RuntimeError("Missing or invalid API Key") from exc
    if status == 403:
        raise RuntimeError("API Key lacks required scope") from exc
    if status == 429:
        raise RuntimeError("API Key rate limit exceeded") from exc
    raise RuntimeError(f"NFM API error {status}: {detail}") from exc
```

## JavaScript

### Node.js Fetch

```js
const BASE = 'http://127.0.0.1:18765'
const KEY = 'nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

async function nfm(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${KEY}`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`NFM API ${res.status}: ${body}`)
  }
  return res.json()
}

const { task_id } = await nfm('/api/scan', {
  method: 'POST',
  body: JSON.stringify({
    page_id: 'YOUR_NOTION_PAGE_ID',
    probe_workers: 8,
  }),
})

console.log(task_id)
```

### 浏览器 EventSource

浏览器里不要把长期 API Key 放进 `EventSource` URL。先换短期 token：

```js
const BASE = 'http://127.0.0.1:18765'
const KEY = 'nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
const taskId = 't_xxxxxxxxxxxx'

const tokenRes = await fetch(`${BASE}/api/tasks/${taskId}/events-token`, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${KEY}`,
  },
})

if (!tokenRes.ok) {
  throw new Error(`events-token failed: ${tokenRes.status}`)
}

const { token } = await tokenRes.json()
const es = new EventSource(`${BASE}/api/tasks/${taskId}/events?events_token=${encodeURIComponent(token)}`)

es.addEventListener('progress', event => {
  const data = JSON.parse(event.data)
  console.log('progress', data)
})

es.addEventListener('done', event => {
  const data = JSON.parse(event.data)
  console.log('done', data.status, data.error)
  es.close()
})

es.onerror = () => {
  console.warn('SSE transport error')
}
```

如果浏览器应用运行在其他 origin，需要在 NFM 设置里添加 CORS 白名单。白名单必须是 origin，例如 `https://app.example.com`，不能带路径。
