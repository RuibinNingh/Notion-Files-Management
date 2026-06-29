# 快速开始

本页带你完成从启动 NFM 到第一次连接 Notion 的基本流程。默认后端/API 端口统一为 `18765`。

## 准备工作

使用 NFM 前，你需要：

- 一个可以访问 Notion 的网络环境
- 一个 Notion Integration Token
- 把这个 Integration 添加到你要管理的 Notion 页面或数据源

如果你还没有 Notion Integration Token，可以在 Notion 的集成管理页面创建内部集成，然后复制 token。NFM 目前使用 Integration Token，不使用 Notion OAuth。

## 方式一：Docker 启动

Docker 是服务器部署的推荐方式。

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker logs nfm | grep "初始登录密码"
```

启动后访问：

```text
http://<服务器地址>:18765
```

如果你想固定登录密码，可以在部署环境里设置：

```bash
NFM_PASSWORD=你的密码
```

未设置 `NFM_PASSWORD` 时，NFM 会在首次启动时生成随机密码，并打印在启动日志里。

## 方式二：Windows exe 启动

Windows exe 适合从旧桌面版迁移，或只想在本机使用 NFM 的用户。

双击运行后，NFM 会在本机启动后端，并打开浏览器访问：

```text
http://127.0.0.1:18765
```

默认数据目录：

```text
%LOCALAPPDATA%\Notion-Files-Management
```

常用位置：

| 内容 | 位置 |
|------|------|
| 配置文件 | `%LOCALAPPDATA%\Notion-Files-Management\config.json` |
| 日志 | `%LOCALAPPDATA%\Notion-Files-Management\logs` |
| 缓存和临时文件 | `%LOCALAPPDATA%\Notion-Files-Management\staging` |

如需改端口，可以在启动前设置 `NFM_PORT`，但常规使用建议保持默认 `18765`。

## 方式三：本地开发启动

开发或调试时，可以分别启动后端和前端。

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 18765
```

另开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

开发模式访问：

```text
http://127.0.0.1:5173
```

前端会把 `/api` 请求代理到 `127.0.0.1:18765`。

## 第一次登录

打开 NFM 页面后，输入启动时设置或生成的登录密码。

登录成功后，建议先进入设置页完成：

1. 填写 Notion Integration Token。
2. 根据机器性能调整下载和上传并发。
3. 如果需要第三方浏览器跨域调用，配置允许的 CORS Origin。

## 连接 Notion 页面

NFM 只能访问已授权给 Integration 的页面或数据源。使用前请在 Notion 里打开目标页面，添加你创建的 Integration。

常见流程：

1. 在 Notion 创建或打开目标页面。
2. 把 NFM 使用的 Integration 添加到该页面。
3. 在 NFM 中粘贴页面 ID 或页面链接。
4. 开始扫描、下载、上传或执行工具任务。

如果页面扫描失败，优先检查 Integration 是否已加入目标页面，以及 Token 是否填写正确。

## 下一步

- 查看 [配置说明](/user/configuration)，了解密码、端口、数据目录、缓存和 API Key。
- 查看 [常见问题](/user/faq)，处理端口占用、密码丢失、Notion 授权失败等问题。
