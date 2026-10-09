# 一键推 GitHub 并部署正式服

Cursor 改完代码后：你说 **「提交并推送部署」** → 推到 `main` → GitHub Actions 构建镜像 → SSH 登录正式服 `docker compose pull && up`。

## 1. 正式服只做一次

在服务器项目目录的 `.env`（给 compose 用的那个，不是 backend.env）写入你的 fork 镜像，不要再用官方 `brokermr810`：

```env
FRONTEND_IMAGE=ghcr.io/yangyang28/quantdinger-frontend
BACKEND_IMAGE=ghcr.io/yangyang28/quantdinger-backend
IMAGE_TAG=latest
```

若 GHCR 包是私有的，服务器先登录一次：

```bash
echo YOUR_GITHUB_PAT | docker login ghcr.io -u yangyang28 --password-stdin
```

确认 compose 文件在该目录（`docker-compose.yml` 或 `docker-compose.ghcr.yml`）。

## 2. GitHub 只做一次

打开 https://github.com/yangyang28/QuantDinger/settings/secrets/actions

**Variables（变量）**

| 名称 | 值 |
|------|-----|
| `ENABLE_PROD_DEPLOY` | `true` |

**Secrets（密钥）**

| 名称 | 含义 |
|------|------|
| `PROD_SSH_HOST` | 正式服 IP 或域名 |
| `PROD_SSH_USER` | SSH 用户 |
| `PROD_SSH_KEY` | 能登录该用户的私钥全文（含 `BEGIN`/`END`） |
| `PROD_DEPLOY_PATH` | 服务器上 compose 所在绝对路径，如 `/opt/quantdinger` |
| `PROD_SSH_PORT` | 可选，默认 `22` |

服务器 `~/.ssh/authorized_keys` 要放对应公钥。建议单独建一个只用于部署的 SSH 密钥。

第一次 Actions 把镜像推到 GHCR 后，到  
https://github.com/yangyang28?tab=packages  
把 `quantdinger-frontend` / `quantdinger-backend` 设为 Public（或保持私有并 docker login）。

## 3. 之后怎么用

在 Cursor 说：

> 改完后提交并推送到 origin/main。

或：

> 提交并推送部署。

我执行 `git push origin main` 后，仓库 Actions 里会出现 **Publish main and deploy production**。绿了就表示镜像已更新且正式服已 pull。

也可在 GitHub Actions 里手动 **Run workflow**。

## 4. 没配密钥时

没设 `ENABLE_PROD_DEPLOY=true` 时，只会构建并推送 GHCR 镜像，**不会 SSH**。可在服务器手动：

```bash
cd /opt/quantdinger   # 改成你的路径
./scripts/prod-deploy-remote.sh
```
