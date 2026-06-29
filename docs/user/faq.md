# 常见问题

## NFM 是什么？

NFM 是 Notion Files Management 的简称。它是一个自部署 Web 工具，用来批量下载 Notion 文件、上传本地文件到 Notion，并提供页面大小统计、数据源迁移等工具。

它不是 Notion 官方产品，也不替代 Notion 客户端。

## 默认访问地址是什么？

后端/API 默认端口统一为 `18765`。

常见地址：

| 场景 | 地址 |
|------|------|
| Docker / systemd | `http://<服务器>:18765` |
| Windows exe | `http://127.0.0.1:18765` |
| 本地开发前端 | `http://127.0.0.1:5173` |

旧的 `8765` 端口口径已废弃。

## 18765 端口被占用了怎么办？

常规部署建议保持默认 `18765`。如果这台机器上已有程序占用该端口，可以设置 `NFM_PORT` 改成其他端口，并同步更新你的反向代理或访问地址。

示例：

```bash
NFM_PORT=19000
```

如果你使用本地开发前端，还需要确认前端代理目标和后端端口一致。

## 忘记登录密码怎么办？

先查看启动日志。如果首次启动时没有设置 `NFM_PASSWORD`，NFM 会生成随机密码并打印在日志中。

如果仍找不到，可以停止服务后编辑数据目录中的 `config.json`，修改 `password` 字段，再重启服务。

常见数据目录：

| 环境 | 位置 |
|------|------|
| Linux / macOS | `~/.notion-files-management` |
| Docker 容器内 | `/data` |
| Windows exe | `%LOCALAPPDATA%\Notion-Files-Management` |

## Notion 页面扫描不到文件怎么办？

优先检查这几项：

1. Notion Integration Token 是否填写正确。
2. 目标页面是否已添加该 Integration。
3. 粘贴的是页面链接或页面 ID，而不是无权限的分享链接。
4. 当前网络是否能访问 Notion API。
5. 页面中是否真的包含 NFM 支持扫描的文件块或属性。

如果是数据源相关功能，还要确认 Integration 对整个数据源和相关页面都有访问权限。

## 为什么上传或下载任务很慢？

常见原因包括：

- Notion API 限流。
- 文件数量很多，单个文件较大。
- 服务器到 Notion 或文件源的网络较慢。
- 下载或上传并发设置过低。

可以在设置页适当调整并发。遇到频繁失败时，反而应先降低并发，避免触发更多限流。

## 缓存会一直占用磁盘吗？

NFM 会把下载产物、临时 ZIP 和上传缓存放在数据目录的 `staging/` 下，并按缓存策略自动清理。

你也可以在 Web 界面的缓存管理中手动查看、下载或删除缓存项。

## Windows exe 的日志和配置在哪里？

默认位置：

```text
%LOCALAPPDATA%\Notion-Files-Management
```

常用文件夹：

| 内容 | 位置 |
|------|------|
| 配置 | `%LOCALAPPDATA%\Notion-Files-Management\config.json` |
| 日志 | `%LOCALAPPDATA%\Notion-Files-Management\logs` |
| 缓存 | `%LOCALAPPDATA%\Notion-Files-Management\staging` |

这个路径不包含空格，适合脚本和打包后的本地运行。

## 可以从旧桌面版迁移吗？

可以。Web 版保留了核心 Python 业务逻辑，并提供 Windows exe 作为迁移入口。

迁移时建议：

1. 使用 Windows exe 启动 NFM。
2. 登录后在设置页填写 Notion Token。
3. 先用少量页面测试扫描、下载和上传。
4. 确认结果正确后，再处理大批量任务。

## 第三方程序怎么调用 NFM？

在 Web 界面的 API 密钥页创建 API Key，然后用 Bearer 请求头调用接口：

```bash
curl -H "Authorization: Bearer nfm_xxxxxxxx" \
  http://127.0.0.1:18765/api/tasks
```

API Key 可以限制权限范围。给第三方程序时，只授予它需要的最小权限。

## 可以把 API Key 放在 URL 里吗？

不可以。长期 API Key 不应出现在 URL 查询参数里，因为 URL 可能进入浏览器历史、代理日志、服务器日志或 Referer。

NFM 的长期 API Key 只支持：

```text
Authorization: Bearer nfm_...
```

任务 SSE 进度因为浏览器 `EventSource` 不能自定义请求头，所以使用短期 `events_token`。这个 token 有效期短，并且只用于指定任务的事件订阅。

## CORS 应该怎么配？

只有第三方浏览器页面需要跨域调用 NFM API 时，才需要配置 CORS。

配置时填写完整 origin，例如：

```text
https://example.com
http://localhost:3000
```

不要填写 `*`、`null` 或带路径的地址。

## NFM 会把我的 Notion Token 上传到哪里吗？

不会。NFM 是自部署工具，Token 保存在你的数据目录配置文件中。

但请注意：拥有这个 Token 的程序可以访问你授权给 Integration 的 Notion 内容。请保护好服务器、配置文件和 API Key。

## AI 目录是不是用户文档？

不是。仓库中的 `AI/` 目录是开发协作和 Agent 交接文档，不面向普通用户。

普通用户应该阅读 `docs/` 和 README。
