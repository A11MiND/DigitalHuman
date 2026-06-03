# 🚀 AWS EC2 快速开始指南

## ⚡ 快速连接

### SSH 连接服务器
```bash
ssh ec2-dh                    # 连接 V1 (主要服务器)
ssh ec2-dh-v2                 # 连接 V2 (备份服务器)
```

### 或者使用菜单工具
```bash
cd ~/Desktop/Work/DigitalHuman
./ec2-quick-connect.sh       # 交互式菜单
./connect-ec2.sh              # 简化菜单
```

### 健康检查
```bash
curl http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health
```

### 打开管理界面
```bash
open http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/
```

## 📝 快速命令参考

| 操作 | 命令 |
|------|------|
| 连接 V1 | `ssh ec2-dh` |
| 连接 V2 | `ssh ec2-dh-v2` |
| 检查状态 | `./ec2-quick-connect.sh` 然后选 3 |
| 查看日志 | `ssh ec2-dh "tail -50 ~/app.log"` |
| 重启服务 | `ssh ec2-dh "sudo systemctl restart nginx"` |
| 磁盘使用 | `ssh ec2-dh "df -h /"` |
| 内存使用 | `ssh ec2-dh "free -h"` |

## ⚠️ AWS CLI 配置

如果看到 "session has expired" 错误：

```bash
# 方法 1: AWS SSO 登录 (推荐)
aws login

# 方法 2: 手动配置 Access Key
aws configure
# 输入: Access Key ID
# 输入: Secret Access Key  
# 输入: ap-northeast-1
# 输入: json
```

## 📂 文档位置

- **完整运维手册**: `docs/AWS-EC2-OPERATION.md`
- **AWS 配置指南**: `docs/AWS-CONFIG.md`
- **连接脚本**: `connect-ec2.sh` 或 `ec2-quick-connect.sh`

## 🔧 故障排除

### SSH 连接失败
```bash
# 1. 检查密钥权限
chmod 400 ~/Desktop/AWSEC2.pem

# 2. 更新主机密钥
ssh-keyscan -H ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com >> ~/.ssh/known_hosts

# 3. 手动测试
ssh -v ec2-dh
```

### AWS CLI 报错
```bash
# 设置区域
export AWS_REGION=ap-northeast-1

# 重新配置
aws configure
```

## 📊 当前服务器状态

### EC2 V1 ✓ 运行中
- 公有 DNS: `ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com`
- 运行时间: 12+ 小时
- 磁盘: 14% 使用
- 内存: 46% 使用
- HTTP 服务: ✓ 正常 (200)

### EC2 V2
- 公有 DNS: `ec2-35-78-82-64.ap-northeast-1.compute.amazonaws.com`
- 状态: 可用

---
*配置日期: 2026-05-28*
