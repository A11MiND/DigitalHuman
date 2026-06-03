# AWS EC2 运维手册 - DigitalHuman 项目

## 📋 实例信息

### EC2 V1 (当前主服务器)
- **实例 ID**: `i-038a113c7202a07f6`
- **公有 DNS**: `ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com`
- **私有 IP**: `172.31.14.31`
- **区域**: ap-northeast-1 (亚太东北 1 - 东京)
- **安全组**: `sg-087e94d85e18d473f`
- **AMI**: Ubuntu Server 24.04 LTS

### EC2 V2 (备份服务器)
- **公有 DNS**: `ec2-35-78-82-64.ap-northeast-1.compute.amazonaws.com`
- **区域**: ap-northeast-1 (亚太东北 1 - 东京)

## 🔐 SSH 连接

### 方式一：使用快捷命令 (推荐)
```bash
# 添加 SSH 快捷配置后，直接使用:
ssh ec2-dh           # 连接到 V1
ssh ec2-dh-v2        # 连接到 V2
```

### 方式二：使用连接脚本
```bash
cd ~/Desktop/Work/DigitalHuman
./connect-ec2.sh
```

### 方式三：直接 SSH 命令
```bash
ssh -i ~/Desktop/AWSEC2.pem ubuntu@ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com
```

## 🔧 AWS CLI 配置

### 1. 重新认证 (如果会话过期)
```bash
# 方法一: 使用 AWS SSO 登录
aws login

# 方法二: 手动配置 Access Key
aws configure
# 输入以下信息:
# AWS Access Key ID: [你的Access Key]
# AWS Secret Access Key: [你的Secret Key]
# Default region name: ap-northeast-1
# Default output format: json
```

### 2. 配置区域环境变量
```bash
export AWS_REGION=ap-northeast-1
export AWS_DEFAULT_REGION=ap-northeast-1
```

### 3. 测试 AWS CLI
```bash
aws sts get-caller-identity
aws ec2 describe-instances --instance-ids i-038a113c7202a07f6
```

## 🌐 服务管理

### 健康检查
```bash
# 在本地执行
curl http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health

# 在服务器上执行
curl http://localhost:8080/health
```

### 远程执行命令
```bash
# 查看系统资源
ssh ec2-dh "free -h && df -h /"

# 查看服务日志
ssh ec2-dh "tail -100 /var/log/nginx/access.log"

# 查看应用日志
ssh ec2-dh "tail -50 ~/app.log"

# 重启服务
ssh ec2-dh "sudo systemctl restart nginx"
```

## 📊 监控命令

### 服务器状态
```bash
# 系统运行时间
ssh ec2-dh "uptime"

# 磁盘使用
ssh ec2-dh "df -h"

# 内存使用
ssh ec2-dh "free -h"

# CPU 负载
ssh ec2-dh "top -bn1 | head -10"
```

### Docker 容器
```bash
# 查看容器状态
ssh ec2-dh "docker ps -a"

# 查看日志
ssh ec2-dh "docker logs [container_name]"

# 重启容器
ssh ec2-dh "docker restart [container_name]"
```

## 🔒 安全组配置

### 当前入站规则
- **SSH**: 端口 22 (来源: 0.0.0.0/0)
- **HTTP**: 端口 80 (来源: 0.0.0.0/0)
- **HTTPS**: 端口 443 (来源: 0.0.0.0/0)
- **自定义 TCP**: 端口 8080 (来源: 0.0.0.0/0)

## 📝 常用操作

### 部署更新
```bash
# 1. 打包本地代码
cd ~/Desktop/Work/DigitalHuman
tar -czvf ../deploy.tar.gz --exclude='.venv' --exclude='.git' --exclude='__pycache__' .

# 2. 上传到服务器
scp ~/Desktop/deploy.tar.gz ec2-dh:~/

# 3. 在服务器上解压并重启服务
ssh ec2-dh "cd ~ && tar -xzvf deploy.tar.gz && ./run.sh"
```

### 备份数据
```bash
# 从服务器下载备份
scp -r ec2-dh:/path/to/data ~/Desktop/backup/
```

### 查看错误日志
```bash
ssh ec2-dh "journalctl -u nginx --no-pager -n 50"
ssh ec2-dh "tail -100 ~/app.log | grep ERROR"
```

## ⚠️ 故障排除

### SSH 连接问题
```bash
# 1. 检查密钥权限
chmod 400 ~/Desktop/AWSEC2.pem

# 2. 添加主机密钥
ssh-keyscan -H ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com >> ~/.ssh/known_hosts

# 3. 测试连接
ssh -v ec2-dh
```

### 服务无响应
```bash
# 1. 检查服务状态
ssh ec2-dh "systemctl status nginx"

# 2. 检查端口占用
ssh ec2-dh "netstat -tlnp | grep 8080"

# 3. 查看进程
ssh ec2-dh "ps aux | grep python"
```

## 🔄 定期维护

### 每周检查
- [ ] 服务健康状态
- [ ] 磁盘空间使用率
- [ ] 内存使用情况
- [ ] 日志文件大小
- [ ] 安全组规则

### 每月维护
- [ ] 系统更新
- [ ] 安全补丁
- [ ] 备份验证
- [ ] 性能优化

## 📞 紧急联系人

- **AWS 支持**: https://aws.amazon.com/contact-us/
- **EC2 控制台**: https://ap-northeast-1.console.aws.amazon.com/ec2/

---
*最后更新: 2026-05-28*
