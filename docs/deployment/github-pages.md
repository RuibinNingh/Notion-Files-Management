# GitHub Pages 部署文档站

NFM 的用户文档使用 VitePress 构建，可以通过 GitHub Actions 自动发布到 GitHub Pages。

默认文档地址：

```text
https://nfm-docs.ruibin-ningh.top/
```

## 已内置的工作流

仓库包含：

```text
.github/workflows/docs.yml
```

它会在 `main` 分支推送以下文件时自动运行：

- `docs/**`
- `package.json`
- `package-lock.json`
- `.github/workflows/docs.yml`

流程做三件事：

1. `npm ci` 安装根目录 VitePress 依赖。
2. 设置 `DOCS_BASE=/` 并运行 `npm run docs:build`。
3. 上传 `docs/.vitepress/dist` 并部署到 GitHub Pages。

## GitHub 仓库设置

第一次启用时，在 GitHub 仓库页面设置：

1. 进入 `Settings`。
2. 打开 `Pages`。
3. `Build and deployment` 的 `Source` 选择 `GitHub Actions`。
4. 推送到 `main` 后等待 `Deploy Docs` workflow 完成。

部署成功后，Actions 页面会显示 Pages URL。仓库已在 `docs/public/CNAME` 写入自定义域名：

```text
nfm-docs.ruibin-ningh.top
```

## DOCS_BASE

使用自定义域名时，文档站挂在域名根路径：

```text
https://nfm-docs.ruibin-ningh.top/
```

所以 workflow 构建时设置：

```bash
DOCS_BASE=/
```

本地预览同样不需要设置，默认也是 `/`：

```bash
npm run docs:dev
```

## DNS 设置

在你的 DNS 服务商处给子域名添加 CNAME：

```text
nfm-docs.ruibin-ningh.top CNAME ruibinningh.github.io
```

然后在 GitHub 仓库 `Settings` → `Pages` 里填写自定义域名：

```text
nfm-docs.ruibin-ningh.top
```

建议打开 `Enforce HTTPS`。DNS 生效和证书签发可能需要等待一段时间。

## 手动触发

工作流支持手动触发：

1. 打开 GitHub 仓库的 `Actions`。
2. 选择 `Deploy Docs`。
3. 点击 `Run workflow`。

## 本地验证

推送前可以先在本地构建：

```bash
npm ci
npm run docs:build
```

如果想显式模拟线上自定义域名根路径：

```bash
DOCS_BASE=/ npm run docs:build
```

构建产物在：

```text
docs/.vitepress/dist/
```

## 提交示例

新增或修改文档站后，可以按这个范围提交：

```bash
git add \
  .github/workflows/docs.yml \
  package.json package-lock.json \
  docs \
  README.md \
  AI/OVERVIEW.md AI/COMMANDS.md AI/CHANGELOG.md AI/GOTCHAS.md \
  CLAUDE.md .gitignore

git commit -m "docs: deploy VitePress site to custom GitHub Pages domain"
git push origin main
```

推送后到 GitHub 仓库的 `Actions` 页面查看 `Deploy Docs` 运行结果。
