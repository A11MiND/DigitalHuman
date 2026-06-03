#!/bin/bash
# EC2 快速连接工具

echo "╔══════════════════════════════════════════╗"
echo "║    AWS EC2 快速连接工具 - DigitalHuman   ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "选择操作:"
echo ""
echo "  [1] 连接 V1 服务器 (主要)"
echo "  [2] 连接 V2 服务器 (备份)"
echo "  [3] V1 服务器状态检查"
echo "  [4] V2 服务器状态检查"
echo "  [5] 打开 V1 健康检查页面"
echo "  [6] 打开 V1 管理界面"
echo ""
echo "  [0] 退出"
echo ""
read -p "请输入选项: " choice

case $choice in
    1)
        echo "正在连接 V1 服务器..."
        ssh ec2-dh
        ;;
    2)
        echo "正在连接 V2 服务器..."
        ssh ec2-dh-v2
        ;;
    3)
        echo "检查 V1 服务器状态..."
        echo ""
        ssh ec2-dh "echo '主机名:' && hostname && echo '' && echo '运行时间:' && uptime && echo '' && echo '内存使用:' && free -h && echo '' && echo '磁盘使用:' && df -h /"
        echo ""
        echo "HTTP 健康检查:"
        curl -s -o /dev/null -w "状态码: %{http_code}\n" http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health
        ;;
    4)
        echo "检查 V2 服务器状态..."
        echo ""
        ssh ec2-dh-v2 "echo '主机名:' && hostname && echo '' && echo '运行时间:' && uptime && echo '' && echo '内存使用:' && free -h && echo '' && echo '磁盘使用:' && df -h /"
        echo ""
        echo "HTTP 健康检查:"
        curl -s -o /dev/null -w "状态码: %{http_code}\n" http://ec2-35-78-82-64.ap-northeast-1.compute.amazonaws.com:8080/health
        ;;
    5)
        echo "打开健康检查页面..."
        curl -s http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health
        ;;
    6)
        echo "打开管理界面..."
        open http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/
        ;;
    0)
        echo "再见!"
        exit 0
        ;;
    *)
        echo "无效选项!"
        exit 1
        ;;
esac
