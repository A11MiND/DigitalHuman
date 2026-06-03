#!/bin/bash
# AWS EC2 连接脚本 - DigitalHuman 项目

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}  AWS EC2 连接工具 - DigitalHuman${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# 显示实例信息
echo -e "${YELLOW}实例信息:${NC}"
echo "  V1: i-038a113c7202a07f6 (当前)"
echo "  V2: ec2-35-78-82-64.ap-northeast-1.compute.amazonaws.com"
echo ""

echo "选择要连接的实例:"
echo "  1) EC2 V1 (当前 - i-038a113c7202a07f6)"
echo "  2) EC2 V2 (备份)"
echo "  3) 仅测试连接"
echo "  4) 退出"
echo ""

read -p "请输入选项 (1-4): " choice

case $choice in
    1)
        echo "正在连接到 EC2 V1..."
        ssh ec2-dh
        ;;
    2)
        echo "正在连接到 EC2 V2..."
        ssh ec2-dh-v2
        ;;
    3)
        echo "测试 V1 连接..."
        ssh -o ConnectTimeout=10 ec2-dh "echo 'V1 连接成功!' && hostname && uptime"
        echo ""
        echo "测试 V2 连接..."
        ssh -o ConnectTimeout=10 ec2-dh-v2 "echo 'V2 连接成功!' && hostname && uptime"
        ;;
    4)
        echo "退出"
        exit 0
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac
