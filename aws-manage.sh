#!/bin/bash
# AWS EC2 管理工具 - DigitalHuman

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTANCE_ID="i-038a113c7202a07f6"
INSTANCE_DNS="ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com"
SG_ID="sg-087e94d85e18d473f"

show_menu() {
    clear
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║     AWS EC2 管理工具 - DigitalHuman (AWS CLI)          ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${CYAN}实例: ${NC}$INSTANCE_ID"
    echo -e "${CYAN}DNS:  ${NC}$INSTANCE_DNS"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}📊 监控与状态${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  1) 完整监控报告"
    echo "  2) 查看实例状态"
    echo "  3) 查看 CloudWatch 指标"
    echo "  4) 查看安全组规则"
    echo "  5) 查看 VPC 配置"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🔧 实例管理${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  6) 启动实例"
    echo "  7) 停止实例"
    echo "  8) 重启实例"
    echo "  9) 查看实例信息"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🌐 网络与安全${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  10) 查看弹性 IP"
    echo "  11) 查看入站规则"
    echo "  12) 添加安全组规则"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🖥️  服务器操作${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  21) SSH 连接服务器"
    echo "  22) 查看服务器状态"
    echo "  23) 查看服务器日志"
    echo "  24) 服务器性能监控"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}📤 部署与备份${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  31) 创建快照备份"
    echo "  32) 查看快照"
    echo "  33) 部署更新包"
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}❌ 退出${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  0) 退出"
    echo ""
}

# 辅助函数
check_aws() {
    aws sts get-caller-identity >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ AWS 未认证，请运行 aws login${NC}"
        return 1
    fi
    return 0
}

# 监控与状态
monitor_full() {
    echo -e "${GREEN}执行完整监控报告...${NC}"
    cd ~/Desktop/Work/DigitalHuman && ./ec2-monitor.sh
    read -p "按回车继续..."
}

status_instance() {
    echo -e "${GREEN}查看实例状态...${NC}"
    aws ec2 describe-instance-status --instance-ids $INSTANCE_ID
    read -p "按回车继续..."
}

cloudwatch_metrics() {
    echo -e "${GREEN}获取 CloudWatch 指标 (最近1小时)...${NC}"
    END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)
    START_TIME=$(date -u -v-1H +%Y-%m-%dT%H:%M:%S)
    
    echo -e "${YELLOW}CPU 利用率:${NC}"
    aws cloudwatch get-metric-statistics \
        --namespace AWS/EC2 \
        --metric-name CPUUtilization \
        --dimensions Name=InstanceId,Value=$INSTANCE_ID \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 300 \
        --statistics Average,Maximum \
        --output table
    read -p "按回车继续..."
}

security_groups() {
    echo -e "${GREEN}查看安全组配置...${NC}"
    aws ec2 describe-security-groups --group-ids $SG_ID
    read -p "按回车继续..."
}

vpc_config() {
    echo -e "${GREEN}查看 VPC 配置...${NC}"
    VPC_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].VpcId' --output text)
    SUBNET_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].SubnetId' --output text)
    
    echo "VPC ID: $VPC_ID"
    aws ec2 describe-vpcs --vpc-ids $VPC_ID
    echo ""
    echo "Subnet ID: $SUBNET_ID"
    aws ec2 describe-subnets --subnet-ids $SUBNET_ID
    read -p "按回车继续..."
}

# 实例管理
start_instance() {
    echo -e "${YELLOW}启动实例 $INSTANCE_ID ...${NC}"
    aws ec2 start-instances --instance-ids $INSTANCE_ID
    echo -e "${GREEN}✓ 实例启动中...${NC}"
    read -p "按回车继续..."
}

stop_instance() {
    echo -e "${YELLOW}停止实例 $INSTANCE_ID ...${NC}"
    read -p "确认停止? (y/n): " confirm
    if [ "$confirm" = "y" ]; then
        aws ec2 stop-instances --instance-ids $INSTANCE_ID
        echo -e "${GREEN}✓ 实例停止中...${NC}"
    fi
    read -p "按回车继续..."
}

reboot_instance() {
    echo -e "${YELLOW}重启实例 $INSTANCE_ID ...${NC}"
    read -p "确认重启? (y/n): " confirm
    if [ "$confirm" = "y" ]; then
        aws ec2 reboot-instances --instance-ids $INSTANCE_ID
        echo -e "${GREEN}✓ 实例重启中...${NC}"
    fi
    read -p "按回车继续..."
}

describe_instance() {
    echo -e "${GREEN}查看实例详细信息...${NC}"
    aws ec2 describe-instances --instance-ids $INSTANCE_ID
    read -p "按回车继续..."
}

# 网络与安全
elastic_ips() {
    echo -e "${GREEN}查看弹性 IP...${NC}"
    aws ec2 describe-addresses --filters "Name=instance-id,Values=$INSTANCE_ID"
    read -p "按回车继续..."
}

inbound_rules() {
    echo -e "${GREEN}查看入站规则...${NC}"
    aws ec2 describe-security-groups \
        --group-ids $SG_ID \
        --query 'SecurityGroups[0].IpPermissions[]'
    read -p "按回车继续..."
}

add_rule() {
    echo -e "${GREEN}添加安全组规则...${NC}"
    read -p "协议 (tcp/udp/icmp): " protocol
    read -p "端口: " port
    read -p "来源 CIDR (例如 0.0.0.0/0): " cidr
    
    echo -e "${YELLOW}添加规则: $protocol/$port from $cidr${NC}"
    read -p "确认? (y/n): " confirm
    if [ "$confirm" = "y" ]; then
        aws ec2 authorize-security-group-ingress \
            --group-id $SG_ID \
            --protocol $protocol \
            --port $port \
            --cidr $cidr
        echo -e "${GREEN}✓ 规则已添加${NC}"
    fi
    read -p "按回车继续..."
}

# 服务器操作
ssh_connect() {
    echo -e "${GREEN}连接到服务器...${NC}"
    ssh ec2-dh
}

server_status() {
    echo -e "${GREEN}查看服务器状态...${NC}"
    ssh ec2-dh "echo '=== 系统信息 ===' && hostname && uptime && echo '' && echo '=== 内存 ===' && free -h && echo '' && echo '=== 磁盘 ===' && df -h"
    read -p "按回车继续..."
}

server_logs() {
    echo -e "${GREEN}查看服务器日志 (最近100行)...${NC}"
    ssh ec2-dh "tail -100 ~/app.log 2>/dev/null || echo '未找到应用日志'"
    read -p "按回车继续..."
}

server_performance() {
    echo -e "${GREEN}服务器性能监控...${NC}"
    ssh ec2-dh "echo '=== Top 10 进程 ===' && ps aux --sort=-%cpu | head -11 && echo '' && echo '=== 负载 ===' && uptime && echo '' && echo '=== 网络连接 ===' && netstat -tuln | grep LISTEN"
    read -p "按回车继续..."
}

# 部署与备份
create_snapshot() {
    echo -e "${GREEN}创建 EBS 快照...${NC}"
    VOLUME_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text)
    echo "卷 ID: $VOLUME_ID"
    SNAPSHOT_ID=$(aws ec2 create-snapshot \
        --volume-id $VOLUME_ID \
        --description "DigitalHuman Backup $(date +%Y-%m-%d)" \
        --query 'SnapshotId' \
        --output text)
    echo -e "${GREEN}✓ 快照创建中: $SNAPSHOT_ID${NC}"
    read -p "按回车继续..."
}

list_snapshots() {
    echo -e "${GREEN}查看快照列表...${NC}"
    aws ec2 describe-snapshots \
        --filters "Name=tag:Name,Values=DigitalHuman*" \
        --query 'Snapshots[*].[SnapshotId,State,StartTime,Description]'
    read -p "按回车继续..."
}

deploy_update() {
    echo -e "${GREEN}部署更新...${NC}"
    read -p "更新包路径: " package
    if [ -f "$package" ]; then
        echo "上传中..."
        scp "$package" ec2-dh:~/
        ssh ec2-dh "cd ~ && tar -xzvf $(basename $package) && ./run.sh"
        echo -e "${GREEN}✓ 部署完成${NC}"
    else
        echo -e "${RED}文件不存在${NC}"
    fi
    read -p "按回车继续..."
}

# 主循环
while true; do
    show_menu
    read -p "请输入选项 (0-33): " choice
    
    case $choice in
        1) monitor_full ;;
        2) status_instance ;;
        3) cloudwatch_metrics ;;
        4) security_groups ;;
        5) vpc_config ;;
        6) start_instance ;;
        7) stop_instance ;;
        8) reboot_instance ;;
        9) describe_instance ;;
        10) elastic_ips ;;
        11) inbound_rules ;;
        12) add_rule ;;
        21) ssh_connect ;;
        22) server_status ;;
        23) server_logs ;;
        24) server_performance ;;
        31) create_snapshot ;;
        32) list_snapshots ;;
        33) deploy_update ;;
        0) echo "再见!"; exit 0 ;;
        *) echo -e "${RED}无效选项${NC}"; sleep 1 ;;
    esac
done
