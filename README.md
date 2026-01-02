<p align="center">
  <img src="https://github.com/RuibinNingh/Notion-Files-Management/blob/main/icon.png?raw=true" alt="Notion-Files-Management Icon" width="200">
</p>

<h1 align="center">🚀 Notion-Files-Management</h1>

<p align="center">
  <strong>将 Notion 变身为你的无限容量私有云盘</strong><br>
  <em>Transform Notion into your unlimited private cloud storage</em>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python 3.8+">
  </a>
  <a href="https://github.com/RuibinNingh/Notion-Files-Management">
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-green.svg" alt="Platform">
  </a>
</p>

---

## 📖 项目简介

**Notion-Files-Management** 是一款功能强大的命令行工具，将 Notion 页面转换为无限容量的私有云存储解决方案。它突破了 Notion 官方客户端的文件传输限制，支持大文件上传下载、批量操作、多线程并发等高级功能。

### 🎯 核心优势

- 🔥 **高性能**: 支持 5GB+ 大文件分片上传，突破单文件大小限制(需要Notion会员)
- 🛡️ **高可靠**: 多层错误重试机制，网络不稳定环境下仍能稳定工作
- ⚡ **高效率**: 并发上传下载，多引擎支持，充分利用网络带宽
- 🎨 **易使用**: 现代化中文界面，一键操作，无需复杂配置

---

## ✨ 功能特性

### 📤 文件上传 (Upload)

#### 🚀 分片上传引擎
- ✅ **大文件支持**: 自动将大文件分割为 5MB 数据块
- ✅ **智能重试**: 分片级重试，避免重复上传已完成部分
- ✅ **并发上传**: 1-5 线程并发配置，支持自定义并发数
- ✅ **进度监控**: 实时显示上传进度、速度、剩余时间

#### 🛡️ 文件格式适配
- ✅ **自动伪装**: 不支持的文件类型自动添加 `.txt` 后缀上传
- ✅ **无缝恢复**: 下载时自动恢复原始文件名和格式
- ✅ **类型检测**: 智能识别文件类型，选择最佳上传策略

#### 📊 上传状态管理
```
[147.5GB 总量] 📂 1/31 ⚡ 3.4MB/s ⏳ 11h33m [░░░░░░░░░░░░░░░░░░░░] 3.2%
──────────────────────────────────────────────────────────────────────
⬆️  1_1_2.7z.003 [4.9GB] 🧩 55/990 |▌         | 5% ⚡ 1.9MB/s
⬆️  2_1_2.7z.004 [4.9GB] 🧩 50/990 |          | 4% ⚡ 2.1MB/s
🔗  3_1_2.7z.005 [4.9GB] 🧩 990/990 |██████████| 100% (挂载中)
```

### 📥 文件下载 (Download)

#### 🎯 多引擎下载
- ✅ **Python 原生**: 稳定可靠的异步下载引擎
- ✅ **Aria2 集成**: 高速多线程下载，支持分片和断点续传
- ✅ **IDM 导出**: 生成 `.ef2` 格式文件，无缝对接 Internet Download Manager

#### 🔄 智能缓存系统
- ✅ **动态刷新**: 自动刷新过期的下载链接
- ✅ **缓存管理**: 40分钟智能缓存，减少API请求
- ✅ **状态监控**: 实时显示缓存状态和过期时间

#### 📋 灵活选择
- ✅ **批量下载**: 一键下载页面内所有文件
- ✅ **选择下载**: 交互式选择需要下载的文件
- ✅ **断点续传**: 支持中断恢复，避免重复下载

### ⚙️ 系统管理 (Settings)

#### 🔍 系统状态监控
- ✅ **Aria2 状态**: 检测 Aria2 服务运行状态
- ✅ **缓存信息**: 显示缓存状态、文件数量、过期时间
- ✅ **系统信息**: Python版本、操作系统信息

#### 📊 性能监控
- ✅ **网络连接**: 实时检测 API 连接状态
- ✅ **缓存统计**: 文件数量、缓存大小、使用情况
- ✅ **错误日志**: 详细的操作日志和错误记录

---

## 🛠️ 安装使用

### 📋 系统要求

- **操作系统**: Windows 10+ / macOS 10.15+ / Ubuntu 18.04+
- **网络**: 稳定的互联网连接
- **磁盘空间**: 根据文件大小需求而定

### 🚀 快速开始

如果你是Windows系统,直接在releases下载解压使用

如果你是Linux或者MacOS,你可能需要下载整个项目然后自己配置好环境运行

相关教程可以看https://www.ruibin-ningh.top/archives/Notion-Files-Management

## 📁 支持上传的文件类型

这受限于Notion的政策

### 🎵 音频文件
`aac`, `adts`, `mid`, `midi`, `mp3`, `mpga`, `m4a`, `m4b`, `oga`, `ogg`, `wav`, `wma`

### 🎬 视频文件
`amv`, `asf`, `wmv`, `avi`, `f4v`, `flv`, `gifv`, `m4v`, `mp4`, `mkv`, `webm`, `mov`, `qt`, `mpeg`

### 🖼️ 图片文件
`gif`, `heic`, `jpeg`, `jpg`, `png`, `svg`, `tif`, `tiff`, `webp`, `ico`

### 📄 文档文件
`pdf`, `txt`, `json`, `doc`, `dot`, `docx`, `dotx`, `xls`, `xlt`, `xla`, `xlsx`, `xltx`, `ppt`, `pot`, `pps`, `ppa`, `pptx`, `potx`

### ⚠️ 其他文件类型
- **自动处理**: 自动添加 `.txt` 后缀伪装上传
- **透明恢复**: 下载时自动恢复原始格式
- **内容无损**: 文件内容完全保持不变

---

## 🔧 高级配置

### Aria2 配置

项目支持 Aria2 高速下载，需要单独安装：

#### Windows
```bash
# 下载 aria2c.exe 放置在项目目录
# 项目会自动检测和启动
```

#### Linux/macOS
```bash
# 使用包管理器安装
sudo apt install aria2    # Ubuntu
brew install aria2        # macOS
```

### 使用镜像站

你可以搭建镜像站实现上传加速：

(Nginx转发https://api.notion.com/v1即可实现)

```env
# 在 .env 文件中添加
NOTION_URL=http://your-proxy-url:port
```

### 性能调优

```python
# 修改 main.py 中的并发配置
MAX_CONCURRENT_UPLOADS = 3  # 上传并发数
MAX_CONCURRENT_DOWNLOADS = 4  # 下载并发数
```

---

## 🏗️ 技术架构

### 📦 核心模块

```
├── main.py          # 主程序和用户界面
├── notion.py        # Notion API 封装和文件管理
├── aria2.py         # Aria2 下载服务集成
└── requirements.txt # Python 依赖包
```

### 🏛️ 设计模式

- **MVC 架构**: 清晰的模型-视图-控制器分离
- **状态机**: 文件上传下载的状态管理
- **策略模式**: 多下载引擎支持
- **观察者模式**: 进度监控和状态更新

### 🔧 核心技术

#### 网络层
- **智能重试**: 多层重试机制 (urllib3 + 手动重试)
- **请求间隔**: 防止API限流和连接重置
- **连接池**: 高效的HTTP连接管理

#### 并发处理
- **多线程上传**: 1-5线程并发配置
- **异步下载**: 非阻塞的下载操作
- **资源控制**: 合理的资源使用和内存管理

#### 错误处理
- **异常分类**: 连接错误 vs 业务错误
- **自动恢复**: 智能的重试和恢复策略
- **用户友好**: 清晰的错误提示和解决建议

---

## ❓ 常见问题

### 🔌 连接问题

**Q: 出现 ConnectionResetError 怎么办？**
A: 这是网络连接问题，解决方案：
1. 检查网络连接稳定性
2. 尝试使用代理
3. 等待网络恢复后重试

**Q: 上传/下载速度很慢怎么办？**
A: 尝试：

1. 调整并发线程数
2. 使用Aria2下载引擎
3. 检查网络带宽

### 📁 文件问题

**Q: 某些文件无法上传？**
A: Notion有文件类型限制，不支持的文件会自动伪装为 `.txt` 格式上传，下载时会自动恢复。

**Q: 上传的文件名不对？**
A: 程序会自动处理文件名，特殊字符会被处理，过长的文件名会被截断。

### ⚙️ 配置问题

**Q: 如何获取 Notion Token？**
A: 访问 https://developers.notion.com 创建集成，复制 Token，并在页面中分享给集成。

**Q: Aria2 无法启动？**
A: 确保 aria2c.exe 在项目目录中，或者系统已安装 aria2。

---

## 🤝 贡献指南

首先声明,制作团队是初中生,这是我们第一次项目实践

其中使用了AI生成技术

如果你发现了问题可以提issues,但我们大概率没有时间处理

## 🙏 致谢

感谢所有贡献者和用户对项目的支持！

特别感谢：
- [Notion](https://notion.so) 提供的优秀API
- [Aria2](https://aria2.github.io/) 提供的下载引擎
- 开源社区提供的优秀Python库

---

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=date&legend=top-left)](https://www.star-history.com/#RuibinNingh/Notion-Files-Management&type=date&legend=top-left)
