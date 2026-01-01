# 📂 Notion-Files-Management

> **一款工业级 Notion 文件自动化管理系统：实现私有云盘级的大文件备份与高速同步。**
> *An industrial-grade CLI tool that turns Notion into your private, unlimited cloud storage.*

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)](https://www.python.org/)
[![Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## 📖 项目概述 (Project Overview)

**Notion-Files-Management** 是一个基于 Python 的高性能 CLI 工具，旨在突破 Notion 官方客户端在文件传输方面的限制。

它不仅仅是一个下载器，更是一个**高容错、自动化的私有云存储解决方案**。它允许用户将本地海量数据（如大型压缩包、视频课程、日志归档）安全地“搬运”到 Notion，同时解决原生环境下的连接中断、格式限制和下载链接过期问题。

## 🏗️ 系统架构与核心特性 (System Architecture)

本项目采用模块化设计，主要包含**上传引擎**、**下载引擎**和**网络中间件**三大核心模块。

### 1. 📤 工业级上传引擎 (The Uploader)
*针对 5GB+ 超大文件、弱网环境设计的自动化备份方案。*

* **🛡️ 后缀名伪装技术 (Suffix Camouflage)**
    * **原理**: 针对 Notion API 拒绝上传 `.7z`, `.001`, `.rar`, `.exe` 等特定格式的问题，程序在上传流中自动将其伪装为 `.txt` 或 `.bin`。
    * **效果**: 成功绕过服务器端校验，下载回来后文件内容无损。
* **🤖 三级异常防御机制 (Triple-Layer Defense)**
    * **L1 分片重试**: 将大文件切割为 5MB 的数据块 (Chunk)。单个分片上传失败时，仅重传该分片，绝不从头开始。
    * **L2 指数退避 (Exponential Backoff)**: 遇到网络波动或 API 报错时，自动执行 `1s -> 2s -> 4s ... -> 60s` 的等待策略，防止触发 Notion 的 IP 封禁。
    * **L3 会话自愈 (Session Recovery)**: 针对 `10054 Connection Reset` 或 `400 Bad Request` 等致命错误（导致 `upload_id` 失效），程序自动扣除已上传进度，重新申请会话 ID 并从断点处继续，实现无人值守。
* **🌊 智能流控**: 内置令牌桶算法，严格控制 API 请求速率 `< 3 req/s`。
* **📂 批量自动化**: 支持递归遍历文件夹，自动建立上传队列。

### 2. 📥 极速下载引擎 (The Downloader)
*解决 Notion S3 链接 1 小时过期的下载难题。*

* **🔄 动态链接保活**: 在执行下载动作前的毫秒级时间内，实时请求 Block API 刷新 Signed URL，彻底杜绝 `403 Forbidden`。
* 支持断点续传
* 详细进度实时展示
* **🚀 多策略下载引擎 (Strategy Pattern)**:
    * Aria2高速下载
    * **Python Native**: 纯 Python 实现，零依赖。
    * **IDM Export**: 生成 `.ef2` 导入文件，无缝对接 Internet Download Manager。

### 3. 🌐 网络与环境适配 (Network & Environment)
* **🪞 镜像站支持 (Mirror Support)**: 允许在配置中自定义 `BASE_URL`（如使用 Cloudflare Worker 搭建的 Notion API 代理），加速国内访问。
* **🎨 现代化 TUI**: 基于 `Rich` 和 `Questionary` 构建的 Vite 风格交互界面，提供实时速度监控、剩余时间预测和彩色日志。

---

## ⚙️ 配置与使用 (Configuration)

### 环境变量配置

在项目根目录创建 `.env` 文件（可参考 `config.example.env`）：

```env
# Notion API 配置
NOTION_TOKEN=your_notion_integration_token
NOTION_VERSION=2022-06-28
NOTION_PAGE_ID=your_page_id

# 可选配置
NOTION_URL=https://api.notion.com/v1  # API 基础URL，可用于配置代理
```

### 使用方法

#### 1. 命令行界面

运行主程序：
```bash
python main.py
```

选择相应的功能进行上传或下载操作。

#### 2. 编程核心特性详解

#### 📄 支持的文件类型
**Notion API 原生支持的文件类型无需伪装：**

- **音频**: `.aac`, `.mp3`, `.wav`, `.ogg`, `.wma`, `.mid`, `.midi`, `.m4a`, `.m4b`
- **文档**: `.pdf`, `.txt`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`, `.json`
- **图片**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.svg`, `.webp`, `.tiff`, `.ico`, `.heic`
- **视频**: `.mp4`, `.avi`, `.mkv`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.f4v`

其他文件类型将自动伪装为 `.txt` 格式上传，下载时恢复原始格式。
