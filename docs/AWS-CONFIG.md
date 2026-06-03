# AWS CLI 配置指南

## 🔑 当前配置状态

### ✅ 已完成
- AWS CLI 已安装: `aws-cli/2.34.54`
- SSH 密钥已配置: `~/Desktop/AWSEC2.pem`
- SSH 密钥已添加到 ssh-agent
- SSH 配置文件已创建: `~/.ssh/config`
- AWS CLI 配置文件已创建: `~/.aws/config`

### ⚠️ 需要完成
- AWS SSO 会话已过期，需要重新登录

## 🔐 AWS 认证方式

### 方式一: AWS SSO (推荐 - 之前使用的方式)

之前配置中使用的是 `aws login` SSO 登录方式。会话已过期，需要重新认证：

```bash
# 1. 执行 AWS SSO 登录
aws login

# 2. 浏览器会打开并要求授权
# 3. 登录成功后，配置区域
aws configure set region ap-northeast-1

# 4. 验证登录
aws sts get-caller-identity
```

### 方式二: Access Key (备选方案)

如果没有 SSO，可以手动配置 Access Key：

```bash
# 1. 运行配置命令
aws configure

# 2. 按提示输入:
AWS Access Key ID [None]: AKIAXXXXXXXXXXXXX
AWS Secret Access Key [None]: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Default region name [None]: ap-northeast-1
Default output format [None]: json

# 3. 验证配置
aws sts get-caller-identity
```

## 📋 获取 AWS 凭证

### 从 AWS 控制台获取 Access Key
1. 登录 AWS 控制台: https://console.aws.amazon.com/
2. 点击右上角用户名 → "安全凭证"
3. 展开 "访问密钥"
4. 点击 "创建新的访问密钥"
5. 下载密钥文件或复制 Access Key ID 和 Secret Access Key

⚠️ **注意**: Secret Access Key 只显示一次，请立即保存！

### 从现有 SSO 会话恢复
```bash
# 检查 SSO 令牌状态
cat ~/.aws/login/cache/*.json | jq -r '.accessToken' 2>/dev/null

# 如果令牌过期，重新登录
aws login --profile default
```

## 🧪 测试 AWS CLI

```bash
# 测试区域配置
aws ec2 describe-availability-zones --region ap-northeast-1

# 查看 EC2 实例
aws ec2 describe-instances --instance-ids i-038a113c7202a07f6

# 测试 S3 访问 (如果有)
aws s3 ls
```

## 🔒 安全建议

1. **不要提交凭证到 Git**
   ```bash
   # 在 .gitignore 中添加
   echo ".env" >> .gitignore
   echo "credentials" >> .gitignore
   ```

2. **使用环境变量** (可选)
   ```bash
   export AWS_ACCESS_KEY_ID="AKIA..."
   export AWS_SECRET_ACCESS_KEY="..."
   export AWS_DEFAULT_REGION="ap-northeast-1"
   ```

3. **定期轮换密钥**
   - 建议每 90 天更换一次 Access Key
   - 使用 AWS Organizations 可以强制执行密钥轮换策略

4. **启用 MFA**
   - 在 AWS 控制台为 root 账户启用 MFA
   - 为 IAM 用户启用虚拟 MFA 设备

## 📊 当前服务器状态

### EC2 V1 (i-038a113c7202a07f6)
- ✅ **状态**: 运行中
- ✅ **健康检查**: HTTP 200
- 📊 **磁盘**: 28GB 总容量, 14% 已使用 (3.8GB)
- 💾 **内存**: 908MB 总计, 416MB 使用中
- 🖥️ **系统**: Ubuntu 24.04 LTS
- ⏰ **运行时间**: 12 小时 19 分钟

### 服务端点
- **HTTP**: http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080
- **健康检查**: http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health

---
*配置日期: 2026-05-28*
