# 交接文档索引

新会话先读这个文件，再按需展开对应子文档。

## 项目一句话

**Notion Files Management** —— 一个帮你批量下载/上传 Notion 文件、管理数据库的工具。

## 当前状态

**正在运行**（由你之前的会话启动）：

| 服务 | 地址 | 进程 / 端口 |
|------|------|------------|
| 前端 dev server (Vite + Vue 3) | http://localhost:5173 | vite, 端口 5173 |
| 后端 API (FastAPI) | http://127.0.0.1:18765 | uvicorn, 端口 18765 |
| 登录密码 | `admin123` | — |

⚠️ **注意**：后端默认端口已统一为 `18765`，`frontend/vite.config.ts` 的 proxy 也指向 `127.0.0.1:18765`。不要再按 8000/8765 的旧口径改配置。

## 文档结构

```
AI/
├── README.md          ← 本文件（索引）
├── OVERVIEW.md        ← 项目概述、技术栈、目录结构
├── ARCHITECTURE.md    ← 架构原理：后端模块关系、前后端交互、SSE 机制
├── COMMANDS.md        ← 常用命令：启动/测试/调试/打包
├── GOTCHAS.md         ← 已知的坑、容易踩雷的地方、临时方案
└── CHANGELOG.md       ← 重构过程中已发生的重要变更
```

## 快速决策表（先看这张）

| 你想做什么 | 看哪份文档 |
|-----------|-----------|
| 了解项目能做什么、怎么组织的 | `OVERVIEW.md` |
| 修改功能（比如加一个新工具） | `ARCHITECTURE.md` → 找到对应模块 |
| 第三方开放 API / API Key 鉴权 | `ARCHITECTURE.md`「鉴权流(双通道)」+ `COMMANDS.md`「第三方开放 API 调用示例」 |
| 启动/调试/打包 / Windows exe | `COMMANDS.md` |
| 解决一个奇怪问题 | `GOCHAS.md` |
| 看历史改了什么 | `CHANGELOG.md` |

## 紧急情况

- **服务挂了**：见 `COMMANDS.md` 的「启动」一节
- **改了代码前端没刷新**：Vite HMR 自动处理；强制刷新：Ctrl+Shift+R
- **改了后端代码**：uvicorn 没用 `--reload`，需要 `kill` 重启，见 `COMMANDS.md`
- **遇到 Notion API 报错**：先看 `GOTCHAS.md` → 「Notion API 速率限制」
