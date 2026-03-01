<div align="center">

<br />

<img src="https://github.com/RuibinNingh/Notion-Files-Management/blob/main/icon.png?raw=true" alt="Notion Files Management" width="96" />

<br />

# Notion Files Management

**把 Notion 里的文件，真正变成你的文件。**

批量下载 · 批量上传 · 页面工具箱 · 自动更新

<br />

[![Windows](https://img.shields.io/badge/Windows_10%2F11-0078D4?style=flat-square&logo=windows&logoColor=white)](https://github.com/RuibinNingh/Notion-Files-Management/releases)
[![Release](https://img.shields.io/github/v/release/RuibinNingh/Notion-Files-Management?style=flat-square&color=22c55e&label=最新版本)](https://github.com/RuibinNingh/Notion-Files-Management/releases)
[![License](https://img.shields.io/badge/License-MIT-f59e0b?style=flat-square)](LICENSE)

<br />

</div>

---

## 为什么需要它？

Notion 的 Web 界面不支持批量下载文件，下载链接也会在一小时后过期。这个工具解决了这些问题：

- 一次性取回页面里所有图片、视频、音频、PDF
- 把本地素材批量推送到 Notion，自动匹配正确的块类型
- 统计页面体积、迁移数据库、批量处理标题——常见繁琐操作全部自动化

---

## 功能一览

| 功能 | 说明 |
|------|------|
| **📥 批量下载** | 获取页面全部文件，探测大小，勾选下载；支持 file / image / pdf / audio / video 及页面封面、图标 |
| **📤 批量上传** | 拖入本地文件即可上传，自动识别类型挂载为对应 Notion 块（图片→`image`，视频→`video`，以此类推） |
| **🔗 链接自动刷新** | 下载途中遇到过期链接，后台静默刷新后继续，无需任何手动操作 |
| **📊 页面大小查询** | 逐文件探测并汇总页面总占用，实时显示进度 |
| **🔄 页面大小自动更新** | 批量扫描数据库，将每个页面的文件总大小写入指定数字属性 |
| **↔️ 数据源迁移** | 按属性映射，把一个数据库的属性值批量同步到另一个 |
| **✂️ 批量去除后缀** | 一键去除数据库所有页面标题的指定后缀 |
| **🎨 外观自定义** | 主题色、云母 / 亚克力 / 自定义壁纸背景，支持图片和视频 |

---

## 快速开始

请见我的博客:

[Notion-Files-Management - 星尘客栈](https://www.ruibin-ningh.top/Notion-Files-Management)

## 下载

前往 [Releases](https://github.com/RuibinNingh/Notion-Files-Management/releases) 下载最新版本。

解压后直接运行 `Notion-Files-Management.exe`，无需安装 .NET 或 Python。

**系统要求**：Windows 10 / 11，64 位

---

## 常见问题

**提示「没有权限」**
> 确认 Integration 已添加到目标页面（见「第二步」）。子页面需要从父页面继承，或单独添加。

**文件下载到一半失败了**
> Notion 的下载链接有效期约一小时。应用会在后台自动刷新过期链接并重试，通常无需干预。如持续失败，请检查网络连接。

**上传速度很慢**
> Notion API 有速率限制（约 3 次/秒）。应用已内置限流策略，批量上传大量文件时速度受此约束，属正常现象。

**如何查看运行日志**
> 打开 **工具箱** → **查看日志文件**，可直接在文件资源管理器中打开日志目录（位于 `%LocalAppData%\NotionFilesManagement\logs\`）。

---

## Star History

<a href="https://star-history.com/#RuibinNingh/Notion-Files-Management&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date" />
  </picture>
</a>

---

## License

MIT © 2026 [Ruibin_Ningh](https://github.com/RuibinNingh) & Zyx_2012

---

<div align="center">
<sub>如果这个工具对你有用，欢迎 Star ⭐ 或提交 Issue / PR。</sub>
</div>
