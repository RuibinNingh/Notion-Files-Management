# Windows exe 迁移包

Windows exe 面向旧桌面版用户迁移到新 Web 版。它不是 WPF 桌面界面，而是一个本地 Web Console：双击 exe 后启动本机 FastAPI 服务，并自动打开浏览器访问 NFM。

## 文件名

Windows 产物命名规则：

```text
NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe
```

其中 `<版本>` 为 `version_for_channel()` 输出的 `2.0.0-Beta` / `2.0.0-Status`（不带文档修订号 N），`<渠道>` 为 `Beta` 或 `Status`。文档站使用 `v2.0.0-Beta-N` 协议记录迭代，N 不进入 exe 文件名。

示例：

```text
NOTION_FILES_MANAGEMENT_v2.0.0-Beta.exe
NOTION_FILES_MANAGEMENT_v2.0.0-Status.exe
```

文件名使用下划线，不包含空格，方便脚本、快捷方式和自动化工具调用。

## 默认端口

Windows exe 默认监听：

```text
http://127.0.0.1:18765
```

这个端口与 Docker、systemd、开发环境统一。启动后控制台会打印最终访问地址：

```text
Open: http://127.0.0.1:18765
```

如果 `18765` 已被占用，Windows 入口会尝试使用附近的可用本地端口，并在控制台打印提示：

```text
Port 18765 is busy; using 18766.
```

这种情况以控制台显示的 `Open:` 地址为准。

如需覆盖默认首选端口，可在 PowerShell 中设置 `NFM_PORT` 后启动：

```powershell
$env:NFM_PORT="18765"
.\NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe
```

## 数据和日志位置

Windows 默认数据目录：

```text
%LOCALAPPDATA%\Notion-Files-Management
```

常用路径：

| 内容 | 路径 |
|------|------|
| 配置文件 | `%LOCALAPPDATA%\Notion-Files-Management\config.json` |
| 日志目录 | `%LOCALAPPDATA%\Notion-Files-Management\logs` |
| 缓存目录 | `%LOCALAPPDATA%\Notion-Files-Management\staging` |
| 下载/上传暂存 | `%LOCALAPPDATA%\Notion-Files-Management\staging` |

启动时控制台也会打印这些路径：

```text
Data dir: C:\Users\<你>\AppData\Local\Notion-Files-Management
Config:   C:\Users\<你>\AppData\Local\Notion-Files-Management\config.json
Logs:     C:\Users\<你>\AppData\Local\Notion-Files-Management\logs
Cache:    C:\Users\<你>\AppData\Local\Notion-Files-Management\staging
```

## 首次启动

1. 双击 `NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe`。
2. 等待控制台打印 `Open: http://127.0.0.1:18765`。
3. 浏览器会自动打开 NFM。
4. 如果没有预设 `NFM_PASSWORD`，首次启动会生成随机登录密码并打印在控制台。
5. 登录后进入设置页，填写 Notion Integration Token。

如果浏览器没有自动打开，手动复制控制台中的 `Open:` 地址访问。

## 固定登录密码

临时设置本次启动密码：

```powershell
$env:NFM_PASSWORD="your-strong-password"
.\NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe
```

也可以在系统环境变量里长期设置 `NFM_PASSWORD`。未设置时，NFM 会在首次启动生成随机密码并写入配置。

## 迁移建议

旧 Windows 桌面版和新 Web 版是不同架构。建议迁移时按下面顺序处理：

1. 保留旧版 exe 和旧版数据，不要先删除。
2. 下载新的 `NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe`。
3. 启动新版 exe，确认浏览器能打开 `127.0.0.1:18765`。
4. 在设置页重新填写 Notion Integration Token。
5. 在 Notion 页面中确认对应 Integration 已添加到连接。
6. 先用小页面测试扫描、下载、上传流程。
7. 确认无误后，再把新版 exe 固定到常用目录或快捷方式。

## 第三方自动化调用

Windows exe 启动后，本机自动化程序可以调用同一个后端：

```text
http://127.0.0.1:18765/api
```

第三方程序应使用 API Key：

```http
Authorization: Bearer nfm_xxxxxxxxxxxxxxxxx
```

不要把长期 API Key 放进 GET 参数。SSE 进度订阅需要先用 API Key 换取短期 `events_token`，再用 `?events_token=` 连接任务事件流。

如果自动化程序运行在浏览器环境，需要在 NFM 的 API 密钥页面配置 CORS 白名单。

## 常见问题

### 双击后浏览器打不开

先看控制台是否有 `Open:` 地址。浏览器没有自动打开时，复制该地址手动访问。

### 提示端口被占用

默认端口是 `18765`。如果控制台显示使用了其他端口，以 `Open:` 地址为准。要稳定使用 `18765`，先关闭占用该端口的程序，再重新启动 exe。

### 找不到日志

日志目录固定在：

```text
%LOCALAPPDATA%\Notion-Files-Management\logs
```

也可以从启动控制台的 `Logs:` 行确认实际路径。

### 想清理缓存

优先在 NFM 设置页或缓存页面清理。手动清理时，关闭 exe 后删除：

```text
%LOCALAPPDATA%\Notion-Files-Management\staging
```

不要在任务运行中删除 `staging`，否则下载、上传或 ZIP 打包任务可能失败。

## 打包说明

维护者在仓库根目录执行：

```bash
cd frontend && npm run build && cd ..
.venv/bin/pyinstaller deploy/nfm.spec --noconfirm
```

`deploy/nfm.spec` 会使用 `deploy/windows_entry.py` 作为入口，并把 `frontend/dist` 打进 exe。Docker、systemd 和普通 uvicorn 部署不会触发这个 Windows 入口。
