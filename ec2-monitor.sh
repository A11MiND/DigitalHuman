#!/bin/bash
# EC2 监控脚本 - DigitalHuman

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║          AWS EC2 监控面板 - DigitalHuman               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 获取身份信息
echo -e "${YELLOW}[1/5] AWS 身份验证${NC}"
IDENTITY=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} 已认证: 账户 $IDENTITY"
else
    echo -e "${RED}✗${NC} 未认证，请运行 aws login"
    exit 1
fi

# 实例信息
echo ""
echo -e "${YELLOW}[2/5] EC2 实例信息${NC}"
aws ec2 describe-instances \
    --instance-ids i-038a113c7202a07f6 \
    --query 'Reservations[0].Instances[0].{
        Instance:InstanceId,
        State:State.Name,
        Type:InstanceType,
        DNS:PublicDnsName,
        IP:PublicIpAddress,
        AZ:Placement.AvailabilityZone,
        Name:Tags[?Key==`Name`].Value|[0]
    }' \
    --output table

# 实例状态
echo ""
echo -e "${YELLOW}[3/5] 实例状态详情${NC}"
aws ec2 describe-instance-status \
    --instance-ids i-038a113c7202a07f6 \
    --query 'InstanceStatuses[0].{
        Status:InstanceStatus.Status,
        System:SystemStatus.Status,
        Instance:InstanceId
    }' \
    --output table

# 安全组规则
echo ""
echo -e "${YELLOW}[4/5] 入站规则 (端口)${NC}"
aws ec2 describe-security-groups \
    --group-ids sg-087e94d85e18d473f \
    --query 'SecurityGroups[0].IpPermissions[*].[FromPort,ToPort,IpProtocol,length(IpRanges)]' \
    --output table 2>/dev/null || echo "无法获取安全组信息"

# 网络配置
echo ""
echo -e "${YELLOW}[5/5] VPC 和网络信息${NC}"
VPC_ID=$(aws ec2 describe-instances \
    --instance-ids i-038a113c7202a07f6 \
    --query 'Reservations[0].Instances[0].VpcId' \
    --output text)
echo "VPC ID: $VPC_ID"

SUBNET_ID=$(aws ec2 describe-instances \
    --instance-ids i-038a113c7202a07f6 \
    --query 'Reservations[0].Instances[0].SubnetId' \
    --output text)
echo "Subnet ID: $SUBNET_ID"

# SSH 连接测试
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}SSH 连接测试${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if ssh -o ConnectTimeout=5 -o BatchMode=yes ec2-dh "echo '${GREEN}✓${NC} SSH 连接成功'" 2>/dev/null; then
    echo ""
    ssh -o ConnectTimeout=5 ec2-dh "echo '  主机名:'; hostname; echo ''; echo '  运行时间:'; uptime -p; echo ''; echo '  内存:'; free -h | grep Mem"
else
    echo -e "${RED}✗${NC} SSH 连接失败"
fi

# HTTP 服务测试
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}HTTP 服务测试${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://ec2-13-114-64-14.ap-northeast-1.compute.amazonaws.com:8080/health 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓${NC} HTTP 服务正常 (状态码: $HTTP_CODE)"
else
    echo -e "${RED}✗${NC} HTTP 服务异常 (状态码: $HTTP_CODE)"
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  监控完成 - $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
