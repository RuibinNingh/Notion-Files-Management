# systemd + venv 部署

`systemd + venv` 适合不使用 Docker 的 Linux 服务器。这个方式会把后端代码、前端构建产物和 Python 虚拟环境放在 `/opt/nfm`，运行数据放在 `/var/lib/nfm`。

## 端口与目录

| 项目 | 默认值 | 说明 |
|------|--------|------|
| 监听地址 | `127.0.0.1:18765` | `deploy/systemd/nfm.service` 的默认配置 |
| 对外访问 | 建议经反向代理 | Nginx/Caddy 转发到 `127.0.0.1:18765` |
| 程序目录 | `/opt/nfm` | 后端、前端 dist、venv |
| 数据目录 | `/var/lib/nfm` | `NFM_DATA_DIR` |
| 配置文件 | `/var/lib/nfm/config.json` | 保存运行配置 |
| 日志目录 | `/var/lib/nfm/logs` | Python 业务日志 |
| 缓存目录 | `/var/lib/nfm/staging` | 上传、下载、ZIP 打包等临时文件 |

## 准备系统用户

```bash
sudo useradd --system --home /var/lib/nfm --shell /usr/sbin/nologin nfm
sudo install -d -o nfm -g nfm /opt/nfm /var/lib/nfm
```

## 构建前端

在仓库根目录执行：

```bash
cd frontend
npm ci
npm run build
cd ..
```

构建产物会生成到 `frontend/dist`。

## 安装后端

复制后端和前端产物：

```bash
sudo rsync -a --delete backend/ /opt/nfm/backend/
sudo install -d -o nfm -g nfm /opt/nfm/frontend
sudo rsync -a --delete frontend/dist/ /opt/nfm/frontend/dist/
```

创建 Python 虚拟环境并安装依赖：

```bash
sudo python3 -m venv /opt/nfm/venv
sudo /opt/nfm/venv/bin/pip install --upgrade pip
sudo /opt/nfm/venv/bin/pip install -r /opt/nfm/backend/requirements.txt
sudo chown -R nfm:nfm /opt/nfm /var/lib/nfm
```

## 安装 systemd 服务

```bash
sudo cp deploy/systemd/nfm.service /etc/systemd/system/nfm.service
sudo systemctl daemon-reload
sudo systemctl enable --now nfm
```

查看状态：

```bash
sudo systemctl status nfm
```

查看启动日志和首次生成的登录密码：

```bash
sudo journalctl -u nfm -f
```

启动后后端监听：

```text
http://127.0.0.1:18765
```

如果没有设置 `NFM_PASSWORD`，首次启动会随机生成登录密码并打印到 journal。

## 固定环境变量

默认 service 已包含：

```ini
Environment=NFM_DATA_DIR=/var/lib/nfm
Environment=NFM_HOST=127.0.0.1
Environment=NFM_PORT=18765
```

生产环境建议用 drop-in 覆盖密码、Notion Token 或 API 配置，不直接改仓库里的 unit 文件：

```bash
sudo systemctl edit nfm
```

写入：

```ini
[Service]
Environment=NFM_PASSWORD=your-strong-password
Environment=NFM_NOTION_TOKEN=ntn_xxxxxxxxxxxxxxxxx
Environment=NFM_API_CORS_ALLOWED_ORIGINS=https://your-app.example.com
```

保存后重启：

```bash
sudo systemctl daemon-reload
sudo systemctl restart nfm
```

## 反向代理

systemd 默认只监听 `127.0.0.1:18765`。如果要公网访问，建议在同机配置 Nginx 或 Caddy，并启用 HTTPS。

Nginx 示例：

```nginx
server {
    listen 443 ssl http2;
    server_name nfm.example.com;

    location / {
        proxy_pass http://127.0.0.1:18765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }
}
```

`proxy_buffering off` 用于保证任务进度 SSE 能及时推送到浏览器。

## 更新

拉取新代码并重新构建前端：

```bash
git pull
cd frontend && npm ci && npm run build && cd ..
```

同步文件并更新依赖：

```bash
sudo rsync -a --delete backend/ /opt/nfm/backend/
sudo rsync -a --delete frontend/dist/ /opt/nfm/frontend/dist/
sudo /opt/nfm/venv/bin/pip install -r /opt/nfm/backend/requirements.txt
sudo chown -R nfm:nfm /opt/nfm /var/lib/nfm
sudo systemctl restart nfm
```

## 备份与恢复

备份运行数据：

```bash
sudo tar czf nfm-var-lib-backup.tar.gz -C /var/lib/nfm .
```

恢复到新机器：

```bash
sudo install -d -o nfm -g nfm /var/lib/nfm
sudo tar xzf nfm-var-lib-backup.tar.gz -C /var/lib/nfm
sudo chown -R nfm:nfm /var/lib/nfm
sudo systemctl restart nfm
```

## 排查

确认端口监听：

```bash
ss -tlnp | grep ':18765'
```

测试 API：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18765/api/version
```

查看业务日志：

```bash
sudo ls -la /var/lib/nfm/logs
sudo tail -f /var/lib/nfm/logs/$(sudo ls -t /var/lib/nfm/logs | head -1)
```

查看 systemd 日志：

```bash
sudo journalctl -u nfm -n 200 --no-pager
```
