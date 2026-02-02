# 🚀Headache Trade V2 自动部署指南 (CI/CD)

本项目使用 GitHub Actions 实现全自动化的 CI/CD 部署流程。只要将代码推送 (Push) 到 `main` 分支，系统就会自动部署到生产服务器。

## 📋 部署流程概览

1. **代码推送**: 开发人员将代码 Push 到 `main` 分支。
2. **环境检查**: GitHub Actions 检查是否配置了必要的 Secrets。
3. **SSH 连接**: 通过 SSH 连接到远程服务器。
4. **拉取代码**: 在服务器上执行 `git pull` 获取最新代码。
5. **更新配置**: 根据 GitHub Secrets 自动更新 `.env` 配置文件（API Key等）。
6. **重启服务**: 使用平滑重启脚本重启交易机器人，不中断现有持仓监控。

---

## 🛠️ 第一步：服务器准备

确保您的服务器满足以下条件：

1. **Python环境**: 安装 Python 3.10+
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip python3-venv git
   ```
2. **克隆代码**: 首次部署需要在服务器上手动克隆代码
   ```bash
   # 推荐放在 Home 目录
   cd ~
   git clone https://github.com/WilliamsMiao/Headache_trade.git Headache_trade-1
   ```
3. **SSH 密钥认证 (关键)**:
   服务器必须能从 GitHub 拉取代码。
   ```bash
   # 1. 生成密钥
   ssh-keygen -t ed25519 -C "your_email@example.com"
   
   # 2. 获取公钥内容
   cat ~/.ssh/id_ed25519.pub
   
   # 3. 将公钥添加到 GitHub 仓库 -> Settings -> Deploy keys
   ```

---

## 🔐 第二步：配置 GitHub Secrets

在 GitHub 仓库页面，进入 **Settings** -> **Secrets and variables** -> **Actions**，点击 **New repository secret** 添加以下变量：

### 1. 服务器连接信息 (必填)

| Secret名称 | 说明 | 示例 |
|------------|------|------|
| `SERVER_IP` | 服务器公网 IP 地址 | `123.45.67.89` |
| `SERVER_USER` | SSH 登录用户名 | `root` 或 `ubuntu` |
| `SSH_PRIVATE_KEY` | **服务器登录私钥** (用于GitHub连接服务器) | `-----BEGIN OPENSSH PRIVATE KEY-----...` |

> **注意**: `SSH_PRIVATE_KEY` 是您**本地电脑**连接服务器用的私钥，或者是专门生成的用于 CI/CD 的私钥对的私钥部分。**请把公钥追加到服务器的 `~/.ssh/authorized_keys` 中。**

### 2. 交易API配置 (推荐)

配置这些 Secrets 后，部署脚本会自动生成/更新服务器上的 `.env` 文件。

| Secret名称 | 说明 |
|------------|------|
| `DEEPSEEK_API_KEY` | DeepSeek AI 的 API Key |
| `OKX_API_KEY` | OKX 交易所 API Key |
| `OKX_SECRET` | OKX 交易所 Secret Key |
| `OKX_PASSWORD` | OKX 交易所 Passphrase |

---

## 🚀 第三步：触发部署

### 自动部署
只需提交代码并推送到 `main` 分支：
```bash
git add .
git commit -m "Update trading logic"
git push origin main
```

### 手动部署
1. 进入 GitHub 仓库的 **Actions** 标签页。
2. 选择左侧的 **CI/CD Deployment**。
3. 点击右侧的 **Run workflow** 按钮。

---

## ❓ 常见问题排查

### 1. `ssh: handshake failed: ssh: unable to authenticate`
- **原因**:通过 `SSH_PRIVATE_KEY` 无法登录服务器。
- **解决**: 
  - 确保 Secrets 中的私钥格式正确（包含 BEGIN/END header）。
  - 确保对应的公钥已添加到服务器的 `~/.ssh/authorized_keys`。
  - 检查服务器防火墙是否允许 GitHub IP（通常无需额外配置）。

### 2. `fatal: could not read Username for 'https://github.com'`
- **原因**: 服务器上的 git 无法拉取 GitHub 代码。
- **解决**: 参考"第一步"中的 SSH 密钥认证，在服务器上配置 Deploy Key，并将远程 URL 改为 SSH 格式：
  ```bash
  # 在服务器项目目录下
  git remote set-url origin git@github.com:WilliamsMiao/Headache_trade.git
  ```

### 3. `ModuleNotFoundError`
- **原因**: 环境变量或路径问题。
- **解决**: 部署脚本会自动处理 `PYTHONPATH`，如果手动运行，请使用 `./run.sh` 或 `./restart_bot_safe.sh`，不要直接运行 python 文件。
