#!/usr/bin/env bash
# setup_aws.sh - provision a VPC + one Ubuntu EC2 host for running GeoShardDB.
#
# Requires the AWS CLI with credentials. Only SSH (22) and the API load balancer
# (8000) are opened, and only to ALLOWED_CIDR (defaults to your current public
# IP). Reach Grafana/Prometheus through an SSH tunnel, e.g.:
#   ssh -i geoshard-key.pem -L 3000:localhost:3000 -L 9090:localhost:9090 ubuntu@<ip>
#
# Configuration (environment variables):
#   AWS_REGION      region to deploy into (default: AWS CLI default, else us-east-1)
#   INSTANCE_TYPE   EC2 instance type (default: t3.medium)
#   KEY_NAME        EC2 key pair name (default: geoshard-key)
#   ALLOWED_CIDR    CIDR allowed to reach SSH and the API (default: <your IP>/32)

set -euo pipefail

REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.medium}"
KEY_NAME="${KEY_NAME:-geoshard-key}"
KEY_FILE="${KEY_NAME}.pem"
VPC_CIDR="10.0.0.0/16"
SUBNET_CIDR="10.0.1.0/24"
export AWS_DEFAULT_REGION="$REGION"

if ! command -v aws >/dev/null 2>&1; then
    echo "Error: the AWS CLI is not installed." >&2
    exit 1
fi

if [[ -z "${ALLOWED_CIDR:-}" ]]; then
    MY_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
    ALLOWED_CIDR="${MY_IP}/32"
fi

# Latest Ubuntu 22.04 LTS AMI for this region (published by Canonical in SSM).
AMI_ID="$(aws ssm get-parameter \
    --name /aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id \
    --query Parameter.Value --output text)"

echo "=================================================="
echo "GeoShardDB AWS setup"
echo "Region        : $REGION"
echo "AMI           : $AMI_ID"
echo "Instance type : $INSTANCE_TYPE"
echo "Allowed CIDR  : $ALLOWED_CIDR"
echo "=================================================="

# Refuse to clobber an existing key pair: deleting it would lock out any
# instance that still uses it.
if aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
    if [[ ! -f "$KEY_FILE" ]]; then
        echo "Error: key pair '$KEY_NAME' exists in AWS but $KEY_FILE is not here." >&2
        echo "Set KEY_NAME to a new name, or place the matching private key in $KEY_FILE." >&2
        exit 1
    fi
    echo "Reusing existing key pair $KEY_NAME"
else
    (umask 077 && aws ec2 create-key-pair --key-name "$KEY_NAME" \
        --query KeyMaterial --output text > "$KEY_FILE")
    echo "Created key pair; private key saved to $KEY_FILE"
fi

VPC_ID="$(aws ec2 create-vpc --cidr-block "$VPC_CIDR" \
    --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=GeoShard-VPC}]' \
    --query Vpc.VpcId --output text)"
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-support '{"Value":true}'
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}'
echo "Created VPC $VPC_ID"

IGW_ID="$(aws ec2 create-internet-gateway \
    --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=GeoShard-IGW}]' \
    --query InternetGateway.InternetGatewayId --output text)"
aws ec2 attach-internet-gateway --vpc-id "$VPC_ID" --internet-gateway-id "$IGW_ID"
echo "Attached internet gateway $IGW_ID"

SUBNET_ID="$(aws ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$SUBNET_CIDR" \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=GeoShard-Public-Subnet}]' \
    --query Subnet.SubnetId --output text)"
aws ec2 modify-subnet-attribute --subnet-id "$SUBNET_ID" --map-public-ip-on-launch

ROUTE_TABLE_ID="$(aws ec2 create-route-table --vpc-id "$VPC_ID" \
    --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=GeoShard-Public-RouteTable}]' \
    --query RouteTable.RouteTableId --output text)"
aws ec2 create-route --route-table-id "$ROUTE_TABLE_ID" \
    --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID" >/dev/null
aws ec2 associate-route-table --subnet-id "$SUBNET_ID" --route-table-id "$ROUTE_TABLE_ID" >/dev/null
echo "Created public subnet $SUBNET_ID"

SG_ID="$(aws ec2 create-security-group --group-name GeoShard-SG \
    --description "GeoShardDB host: SSH and API only" --vpc-id "$VPC_ID" \
    --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=GeoShard-SG}]' \
    --query GroupId --output text)"
for port in 22 8000; do
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port "$port" --cidr "$ALLOWED_CIDR" >/dev/null
done
echo "Created security group $SG_ID (22, 8000 from $ALLOWED_CIDR)"

USER_DATA="$(mktemp)"
trap 'rm -f "$USER_DATA"' EXIT
cat > "$USER_DATA" <<'EOF'
#!/bin/bash
apt-get update -y
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker
usermod -aG docker ubuntu
EOF

INSTANCE_ID="$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --subnet-id "$SUBNET_ID" \
    --user-data "file://$USER_DATA" \
    --metadata-options HttpTokens=required \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=GeoShard-Server}]' \
    --query 'Instances[0].InstanceId' --output text)"
echo "Launched instance $INSTANCE_ID; waiting for it to run..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

PUBLIC_IP="$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"

cat <<EOF
==================================================
Done.
Instance : $INSTANCE_ID
Public IP: $PUBLIC_IP

SSH:
  ssh -i $KEY_FILE ubuntu@$PUBLIC_IP
Copy the project (without secrets or local data):
  rsync -avz -e "ssh -i $KEY_FILE" --exclude .git --exclude .venv --exclude '*.pem' \\
    --exclude .env --exclude data ./ ubuntu@$PUBLIC_IP:~/GeoShardDB/
Then on the host: cp .env.example .env, set real secrets, docker compose up -d --build
==================================================
EOF
