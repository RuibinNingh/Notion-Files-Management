# 鉴权与权限

第三方程序应使用 NFM API Key 调用接口：

```http
Authorization: Bearer nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

默认本地 API 地址：

```text
http://127.0.0.1:18765
```

## API Key 规则

- 长期 API Key 必须使用 `Authorization: Bearer` 请求头。
- NFM 不接受任何接口上的 `?api_key=`。
- API Key 明文只在创建时返回一次。
- 后端只保存 `sha256(明文)`，不保存明文。
- 禁用、过期、格式错误、伪造的 key 都返回 `401`。
- scope 不匹配返回 `403`。
- 单 key 限流超限返回 `429`。

这些规则是有意设计的：URL query 凭据很容易进入访问日志、浏览器历史、代理日志和 `Referer`。

## 创建 API Key

可以在浏览器的 API 密钥页面创建 key，也可以通过 API 创建。

通过 API 创建 key 需要满足其中之一：

- 浏览器管理员 session；
- 现有 API Key 拥有 `apikeys` scope。

```bash
curl -X POST http://127.0.0.1:18765/api/apikeys \
  -H "Authorization: Bearer nfm_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "automation-bot",
    "scopes": ["scan", "download", "tasks"],
    "expires_at": null,
    "rate_limit_rpm": 120,
    "enabled": true
  }'
```

响应：

```json
{
  "key": {
    "id": "k_abc123def456",
    "name": "automation-bot",
    "prefix": "nfm_abcd1234",
    "scopes": ["scan", "download", "tasks"],
    "enabled": true,
    "expires_at": null,
    "rate_limit_rpm": 120,
    "created_at": "2026-06-29T00:00:00+00:00",
    "last_used_at": null,
    "last_used_ip": ""
  },
  "plaintext": "nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

请立即保存 `plaintext`。后续列表和详情接口不会再返回明文。

## 更新 API Key

禁用 key：

```bash
curl -X PATCH http://127.0.0.1:18765/api/apikeys/k_abc123def456 \
  -H "Authorization: Bearer nfm_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

显式清空过期时间：

```bash
curl -X PATCH http://127.0.0.1:18765/api/apikeys/k_abc123def456 \
  -H "Authorization: Bearer nfm_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"expires_at": null}'
```

未知 scope 和空 scope 列表都会返回 `400`。

## Scope

Scope 严格、粗粒度。

| Scope | 风险 | 授权范围 |
|-------|------|----------|
| `scan` | 业务 | `/api/scan/*` |
| `download` | 业务 | `/api/download/*` |
| `upload` | 业务 | `/api/upload/*` |
| `tools` | 业务 | `/api/tools/*` |
| `tasks` | 业务 | `/api/tasks/*`，包括任务详情和 SSE token 换取 |
| `settings` | 高 | `/api/settings` |
| `logs` | 高 | `/api/logs*` |
| `cache` | 高 | `/api/cache/*` |
| `system` | 高 | `/api/system/restart` |
| `apikeys` | 高 | `/api/apikeys/*` |

推荐最小权限：

| 集成类型 | 建议 scope |
|----------|------------|
| 只扫描 | `scan`、`tasks` |
| 扫描并下载 | `scan`、`download`、`tasks` |
| 上传文件 | `upload`、`tasks` |
| 工具自动化 | `tools`、`tasks` |
| 运维自动化 | 只额外授予确实需要的高危 scope |

浏览器 session 管理员会跳过 scope 校验。这只适用于通过密码登录后的浏览器/session 通道。

## SSE `events_token`

长任务进度通过下面的 SSE 接口推送：

```text
GET /api/tasks/{task_id}/events
```

很多兼容浏览器的 SSE 客户端不能设置自定义请求头，而长期 API Key 又不能放进 URL。因此第三方客户端要先把 Bearer key 换成短期 SSE token：

```bash
curl -X POST http://127.0.0.1:18765/api/tasks/TASK_ID/events-token \
  -H "Authorization: Bearer nfm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

响应：

```json
{
  "token": "nfmsse_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "expires_in": 600
}
```

然后订阅：

```bash
curl -N -H "Accept: text/event-stream" \
  "http://127.0.0.1:18765/api/tasks/TASK_ID/events?events_token=nfmsse_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

`events_token` 属性：

- 前缀：`nfmsse_`
- 有效期：`600` 秒
- 绑定单个 task ID
- 存在进程内存中
- 后端重启后失效
- 是唯一允许出现在 URL query 里的凭据

`GET /api/tasks/{task_id}/events` 接受任意一种凭据：

| 方式 | 要求 |
|------|------|
| Session Cookie | 浏览器管理员 session |
| Bearer API Key | 有效 key，且拥有 `tasks` scope |
| `?events_token=` | 对应该 task 的有效短期 token |

## SSE 事件

当前 SSE 使用这些事件名：

```text
event: progress
data: {...}

event: done
data: {"status":"done","error":null}
```

终态统一使用 `event: done`，通过 `data.status` 区分：

| `data.status` | 含义 |
|---------------|------|
| `done` | 任务完成 |
| `error` | 任务失败，查看 `data.error` |
| `cancelled` | 任务已取消 |

不要等待自定义 `error` 事件；`EventSource` 已经把 `error` 用作传输错误事件。

## CORS

默认情况下，NFM 不允许浏览器跨域调用 API。服务端到服务端请求不受 CORS 影响。

如果另一个浏览器站点需要调用 NFM，进入设置页配置 `api_cors_allowed_origins`，或设置环境变量：

```bash
NFM_API_CORS_ALLOWED_ORIGINS="https://your-app.example.com"
```

规则：

- 只接受 `http://` 和 `https://` origin。
- 拒绝 `*`。
- 拒绝 `null`。
- 拒绝带 path、query、fragment 的地址。
- 修改后动态生效，不需要重启后端。

有效示例：

```text
https://app.example.com
http://localhost:3000
```

无效示例：

```text
*
null
https://app.example.com/path
https://app.example.com?x=1
```

## Bootstrap API Key

部署自动化可以预置一个全权限 key：

```bash
NFM_BOOTSTRAP_API_KEY="nfm_<至少32位随机字符>" \
  .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 18765
```

Bootstrap key 必须：

- 以 `nfm_` 开头；
- 前缀后至少 32 个字符。

弱值会被忽略并写 warning 日志。重复启动不会创建重复记录。

## 错误码

| 状态码 | 常见原因 |
|--------|----------|
| `400` | scope 非法、scope 为空、过期时间非法、上传 session 非法、不支持重试 |
| `401` | 无 session、缺 Bearer key、key 无效/禁用/过期、SSE token 无效 |
| `403` | API Key 有效但缺少所需 scope |
| `404` | key、task、文件、日志或缓存项不存在 |
| `409` | 缓存项仍被运行中的任务引用 |
| `422` | 请求体未通过 Pydantic 校验 |
| `429` | API Key 超过 `rate_limit_rpm` |
