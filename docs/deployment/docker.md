# Docker 部署

Docker 是生产环境推荐的部署方式。镜像会在构建阶段编译前端，运行时由 FastAPI 后端托管 `frontend/dist`，浏览器直接访问后端端口即可。

## 端口与目录

| 项目 | 默认值 | 说明 |
|------|--------|------|
| 访问地址 | `http://<服务器>:18765` | 统一后端/API 端口 |
| 容器端口 | `18765` | `docker/Dockerfile` 中 `EXPOSE 18765` |
| 宿主机端口 | `18765` | `docker/docker-compose.yml` 中 `18765:18765` |
| 数据目录 | Docker volume `nfm-data` | 挂载到容器内 `/data` |
| 配置文件 | `/data/config.json` | 保存密码、Notion Token、API Key hash 等配置 |
| 日志目录 | `/data/logs` | Python 业务日志 |
| 缓存目录 | `/data/staging` | 上传、下载、ZIP 打包等临时文件 |

## 快速启动

在仓库根目录执行：

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

查看启动日志和首次生成的登录密码：

```bash
docker logs -f nfm
```

启动后访问：

```text
http://<服务器>:18765
```

如果没有设置 `NFM_PASSWORD`，首次启动会随机生成登录密码并打印到容器日志。

## 固定登录密码

可以在启动前通过环境变量指定密码：

```bash
NFM_PASSWORD='your-strong-password' \
docker compose -f docker/docker-compose.yml up -d --build
```

也可以在仓库根目录创建 `.env`：

```dotenv
NFM_PASSWORD=your-strong-password
NFM_NOTION_TOKEN=ntn_xxxxxxxxxxxxxxxxx
NFM_NOTION_BASE_URL=https://api.notion.com/v1
```

然后启动：

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

## 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NFM_PASSWORD` | 启动时随机生成 | Web 登录密码 |
| `NFM_NOTION_TOKEN` | 空 | Notion Integration Token，也可登录后在设置页填写 |
| `NFM_NOTION_BASE_URL` | `https://api.notion.com/v1` | Notion API 地址 |
| `NFM_API_CORS_ALLOWED_ORIGINS` | 空 | 第三方浏览器跨域白名单，逗号分隔 |
| `NFM_BOOTSTRAP_API_KEY` | 空 | 预置全权限 API Key，必须是 `nfm_` 前缀且负载不少于 32 字符 |

长期 API Key 只通过 `Authorization: Bearer nfm_...` 传递，不要放在 URL 参数里。

## 反向代理

如果需要绑定域名和 HTTPS，建议让 Nginx、Caddy 或其他网关代理到容器暴露的 `18765`：

```text
https://nfm.example.com  ->  http://127.0.0.1:18765
```

反向代理需要保留 SSE 流式连接能力。Nginx 示例：

```nginx
location / {
    proxy_pass http://127.0.0.1:18765;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
```

如果前端由第三方站点调用开放 API，需要在 NFM 的 API 密钥页面配置 CORS 白名单，或设置 `NFM_API_CORS_ALLOWED_ORIGINS`。白名单只接受 `http(s)` origin，不接受 `*`、`null` 或带路径的地址。

## 更新

拉取新代码后重新构建镜像：

```bash
git pull
docker compose -f docker/docker-compose.yml up -d --build
```

数据保存在 `nfm-data` volume 中，重建容器不会删除配置和缓存。

## 备份与恢复

备份 Docker volume：

```bash
docker run --rm \
  -v nfm-data:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/nfm-data-backup.tar.gz -C /data .
```

恢复到空 volume：

```bash
docker run --rm \
  -v nfm-data:/data \
  -v "$PWD":/backup \
  alpine sh -c 'cd /data && tar xzf /backup/nfm-data-backup.tar.gz'
```

## 排查

查看容器状态：

```bash
docker ps --filter name=nfm
```

查看服务日志：

```bash
docker logs -f nfm
```

测试后端是否响应：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18765/api/version
```

查看持久化数据：

```bash
docker volume inspect nfm-data
```
