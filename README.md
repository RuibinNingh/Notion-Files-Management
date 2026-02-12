<div align="center">
<img src="https://github.com/RuibinNingh/Notion-Files-Management/blob/main/icon.png?raw=true" alt="Notion Files Management Icon" width="120" />

# Notion Files Management

一个用于 **下载 / 上传 / 工具箱** 的 Notion 文件管理桌面工具

<p>
  <a href="#功能特性">功能特性</a> ·
  <a href="#页面说明">页面说明</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#配置说明">配置说明</a> ·
  <a href="#常见问题">常见问题</a>
</p>

</div>

---

## 功能特性

- **下载页面**
  - 输入 PageID 获取目标内容
  - 支持自动格式化 PageID（32 位 hex → UUID 带连字符）
  - PageID 不合规时给出提示并阻止执行
- **上传页面**
  - 选择文件并上传到指定 Notion 页面（PageID 校验同上）
- **工具箱页面**
  - 常用工具入口（例如：ID 处理/调试/批量操作等，按项目实际补充）
- **统一的 PageID 处理**
  - 支持输入 **32 位 hex / 标准 UUID / Notion 页面 URL**
  - 自动提取并规范化为 `8-4-4-4-12` 格式

---

## 页面说明

### 下载（Download）
- 目标：从 Notion 页面拉取内容并保存到本地（按实际逻辑补充）
- PageID 输入支持：
  - `2fc644ead11a80109665e5fbaba0fd58` → `2fc644ea-d11a-8010-9665-e5fbaba0fd58`
  - 直接粘贴 Notion 页面 URL（会自动提取 ID）

### 上传（Upload）
- 目标：选择本地文件并上传到指定 Notion 页面
- 提交前会强校验 PageID 合规

### 工具箱（Toolbox）
- 目标：提供常用辅助功能（按项目实际补充）

---

## 快速开始

1. 启动应用
2. 进入 **下载 / 上传 / 工具箱** 任意页面
3. 在 PageID 输入框：
   - 可输入 32 位 hex / 标准 UUID / Notion URL
   - 程序会自动格式化并提示错误
4. 按页面操作按钮执行对应任务

---

## 配置说明

> 具体字段以项目实际 `config.json` / 设置页为准；这里给出常见示例结构，按你们工程补全。

- Notion Token（建议放在本地配置，不要提交到 git）
- API BaseUrl（默认 `https://api.notion.com`，若项目支持可配置）
- 并发/重试参数（如果项目支持）

---

## PageID 规则与示例

### 合规输入（任意一种即可）
- **32 位 hex（无连字符）**
  - `2fc644ead11a80109665e5fbaba0fd58`
- **标准 UUID（带连字符）**
  - `2fc644ea-d11a-8010-9665-e5fbaba0fd58`
- **Notion 页面 URL**
  - `https://www.notion.so/.../Some-Title-2fc644ead11a80109665e5fbaba0fd58`

### 不合规示例
- 长度不足/超出
- 含非十六进制字符（例如 `g-z`、中文空格等）

---

## 常见问题

### 1) 我输入了 PageID 但提示不合规？
- 请确认：
  - 去掉连字符后是否 **恰好 32 位**
  - 是否仅包含 `0-9a-fA-F`
- 你也可以直接粘贴 Notion 页面 URL，让程序自动提取

### 2) Token/权限不足导致失败？
- 确认 Token 有访问目标页面的权限
- 确认 Integration 已被添加到页面（Share / Invite）

---

## 开发与构建（可选）

> 按你们实际技术栈填写（.NET / WPF / WinUI / Electron 等）。

- IDE：Visual Studio / Rider
- 构建：`Release` 模式
- 打包：见 `AI/HANDOVER_GUIDE.md`

---

## License
暂无


