# GitHub Actions SSH私钥设置指南

## 问题诊断

如果您看到错误：`ssh: no key found` 或 `can't connect without a private SSH key`

这说明SSH私钥格式有问题或未正确设置。

## 解决方案

### 步骤1: 在服务器上获取私钥

在您的**服务器**上运行以下命令，找到正确的私钥：

```bash
# 查看可用的私钥
ls -la ~/.ssh/

# 常见的私钥文件名：
# - id_rsa (RSA私钥)
# - id_ed25519 (ED25519私钥)
# - id_ecdsa (ECDSA私钥)
```

### 步骤2: 读取私钥内容

```bash
# 显示私钥内容 (根据实际文件名选择)
cat ~/.ssh/id_rsa
# 或
cat ~/.ssh/id_ed25519
```

**正确的私钥格式示例：**

```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
NhAAAAAwEAAQAAAYEAy8K... (很多行)
...
-----END OPENSSH PRIVATE KEY-----
```

或者：

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAy8K... (很多行)
...
-----END RSA PRIVATE KEY-----
```

### 步骤3: 如果服务器上没有私钥，生成新的密钥对

```bash
# 在服务器上生成新的SSH密钥对
ssh-keygen -t ed25519 -C "github-actions"

# 按回车使用默认路径 (~/.ssh/id_ed25519)
# 可以设置密码，也可以直接回车留空（留空更简单）

# 将公钥添加到授权列表
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 显示私钥（用于复制到GitHub）
cat ~/.ssh/id_ed25519
```

### 步骤4: 在GitHub中设置私钥

1. **复制完整的私钥内容**（从`-----BEGIN`到`-----END`，包括这两行）

2. 访问GitHub仓库：
   ```
   https://github.com/WilliamsMiao/Headache_trade/settings/secrets/actions
   ```

3. 找到或创建 `SSH_PRIVATE_KEY` secret：
   - 如果已存在，点击"Update"
   - 如果不存在，点击"New repository secret"
   
4. 粘贴**完整的私钥内容**

### 步骤5: 验证设置

提交代码后，GitHub Actions会自动运行。如果还是失败：

**常见错误排查：**

1. **复制了公钥（.pub文件）**
   - ❌ 错误：`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...`
   - ✅ 正确：以`-----BEGIN`开头的多行内容

2. **私钥不完整**
   - 确保包含开头和结尾标记
   - 确保没有额外的空格或空行

3. **权限问题**
   ```bash
   # 在服务器上检查权限
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/id_*
   ```

4. **测试SSH连接**
   ```bash
   # 从本地测试（使用服务器私钥）
   ssh -i ~/.ssh/id_ed25519 root@你的服务器IP
   ```

## 替代方案：使用密码认证

如果私钥设置太复杂，可以改用密码：

1. 编辑 `.github/workflows/deploy.yml`
2. 将 `key:` 改为 `password:`：
   ```yaml
   - name: Deploy to Server via SSH
     uses: appleboy/ssh-action@master
     with:
       host: ${{ secrets.SERVER_IP }}
       username: ${{ secrets.SERVER_USER }}
       password: ${{ secrets.SSH_PASSWORD }}  # 使用密码
   ```

3. 在GitHub Secrets添加 `SSH_PASSWORD`

**注意**：密码认证不如密钥安全，但更简单。
