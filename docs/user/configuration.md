# 配置说明

NFM 的配置主要来自环境变量和 Web 设置页。环境变量适合部署时固定配置，设置页适合运行后调整 Notion Token、并发、主题、缓存和 API 相关选项。

## 默认端口

后端/API 默认端口统一为：

```text
18765
```

常见访问地址：

| 场景 | 地址 |
|------|------|
| Docker / systemd / Windows exe | `http://<主机>:18765` |
| Windows 本机 | `http://127.0.0.1:18765` |
| 本地开发前端 | `http://127.0.0.1:5173` |
| 本地开发后端 API | `http://127.0.0.1:18765` |

开发模式下，Vite 前端会把 `/api` 请求代理到 `127.0.0.1:18765`。

## 数据目录

`NFM_DATA_DIR` 决定 NFM 保存配置、缓存和日志的位置。

| 环境 | 默认值 |
|------|--------|
| Linux / macOS | `~/.notion-files-management` |
| Docker 容器内 | `/data` |
| Windows exe | `%LOCALAPPDATA%\Notion-Files-Management` |

数据目录通常包含：

| 路径 | 说明 |
|------|------|
| `config.json` | 登录密码、Notion 配置、API Key hash、界面设置等 |
| `logs/` | Python 运行日志 |
| `staging/` | 下载暂存、上传缓存、临时 ZIP 等 |
| `notices_cache/` | 公告和版本信息缓存 |

建议备份 `config.json`。如果你需要完整迁移运行状态，也可以同时迁移 `staging/`。

## 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NFM_DATA_DIR` | `~/.notion-files-management` | 配置、日志和缓存根目录 |
| `NFM_PASSWORD` | 首次启动随机生成 | Web 登录密码 |
| `NFM_PORT` | `18765` | 后端/API 监听端口 |
| `NFM_NOTION_TOKEN` | 空 | Notion Integration Token |
| `NFM_NOTION_BASE_URL` | `https://api.notion.com/v1` | Notion API 地址 |
| `NFM_MAX_DOWNLOAD_WORKERS` | `3` | 下载并发数 |
| `NFM_MAX_UPLOAD_WORKERS` | `3` | 上传并发数 |
| `NFM_API_CORS_ALLOWED_ORIGINS` | 空 | 第三方浏览器跨域白名单，逗号分隔 |
| `NFM_BOOTSTRAP_API_KEY` | 空 | 启动时预置全权限 API Key |
| `NFM_FRONTEND_DIST` | 自动推断 | 前端构建产物目录 |

如果同一配置同时存在于环境变量和设置文件中，部署入口会按后端配置逻辑合并。普通用户优先通过设置页修改 Notion Token、并发、主题色和缓存策略。

## 登录密码

如果设置了 `NFM_PASSWORD`，NFM 会使用该值作为登录密码。

如果没有设置，NFM 会在首次启动时生成随机密码，并写入 `config.json`。请查看启动日志获取初始密码。

修改密码有两种方式：

- 登录后在设置页修改。
- 停止服务后编辑数据目录中的 `config.json`，再重启服务。

## Notion Token

NFM 需要 Notion Integration Token 才能访问你的页面或数据源。

推荐做法：

1. 在 Notion 创建内部集成。
2. 复制 Integration Token。
3. 登录 NFM 后进入设置页保存 Token。
4. 在 Notion 页面中添加该 Integration 的访问权限。

Token 不会发送给 NFM 项目维护者。它保存在你自己的 `NFM_DATA_DIR/config.json` 中。

## 下载和上传并发

下载并发和上传并发会影响速度，也会影响 Notion API 限流风险。

| 配置 | 建议 |
|------|------|
| 下载并发 | 默认 `3`，网络稳定时可适当提高 |
| 上传并发 | 默认 `3`，大量小文件建议谨慎提高 |

如果遇到 Notion API 频繁报错或任务失败，先把并发调低。

## 缓存和日志

NFM 会把下载产物、临时 ZIP、上传缓存等放在 `staging/` 中。缓存默认会自动清理，避免长期占用磁盘。

日志保存在 `logs/` 中，用于排查登录、Notion API、上传下载和任务执行问题。

Windows exe 的日志路径：

```text
%LOCALAPPDATA%\Notion-Files-Management\logs
```

## 第三方 API 和 API Key

NFM 支持给第三方程序创建 API Key。API Key 使用权限范围控制能力，例如扫描、下载、上传、任务查询或系统管理。

安全规则：

- 长期 API Key 只通过 `Authorization: Bearer nfm_...` 请求头传递。
- 不要把长期 API Key 放进 URL 查询参数。
- API Key 明文只在创建时显示一次。
- 配置文件中只保存 API Key 的 hash。
- 第三方浏览器跨域调用需要配置 CORS 白名单。

示例：

```bash
curl -H "Authorization: Bearer nfm_xxxxxxxx" \
  http://127.0.0.1:18765/api/tasks
```

如果要订阅任务 SSE 进度，第三方程序应先换取短期 `events_token`，再用该短期 token 建立 EventSource 或流式连接。

## CORS 跨域白名单

默认情况下，NFM 不开放跨域访问。只有你确实需要从另一个浏览器站点调用 NFM API 时，才需要配置 CORS。

允许值示例：

```text
https://example.com
http://localhost:3000
```

不要配置：

```text
*
null
https://example.com/path
```

CORS 白名单只接受 `http` 或 `https` origin，不接受通配符、`null` 或带路径的地址。
