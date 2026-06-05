#!/bin/bash
# setup_aws.sh - Provision AWS VPC and EC2 for GeoShardDB

set -e

# Configuration
REGION=$(aws configure get region || echo "us-east-1")
AMI_ID="ami-02013f5b15758f4d4" # Ubuntu 22.04 LTS in us-east-1
INSTANCE_TYPE="t3.medium"
KEY_NAME="geoshard-key"
KEY_FILE="${KEY_NAME}.pem"
VPC_CIDR="10.0.0.0/16"
SUBNET_CIDR="10.0.1.0/24"

echo "=================================================="
echo "Starting AWS Infrastructure Setup for GeoShardDB"
echo "Region: $REGION"
echo "AMI: $AMI_ID"
echo "Instance Type: $INSTANCE_TYPE"
echo "=================================================="

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI is not installed. Please install it first."
    exit 1
fi

# 1. Create VPC
echo "Creating VPC ($VPC_CIDR)..."
VPC_ID=$(aws ec2 create-vpc --cidr-block $VPC_CIDR \
    --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=GeoShard-VPC}]' \
    --query Vpc.VpcId --output text)
echo "Created VPC: $VPC_ID"

# Enable DNS support & hostnames
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-support "{\"Value\":true}"
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames "{\"Value\":true}"

# 2. Create Internet Gateway
echo "Creating Internet Gateway..."
IGW_ID=$(aws ec2 create-internet-gateway \
    --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=GeoShard-IGW}]' \
    --query InternetGateway.InternetGatewayId --output text)
echo "Created Internet Gateway: $IGW_ID"

# Attach Internet Gateway to VPC
echo "Attaching Internet Gateway to VPC..."
aws ec2 attach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID

# 3. Create Subnet
echo "Creating Subnet ($SUBNET_CIDR)..."
SUBNET_ID=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block $SUBNET_CIDR \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=GeoShard-Public-Subnet}]' \
    --query Subnet.SubnetId --output text)
echo "Created Subnet: $SUBNET_ID"

# Enable Auto-assign Public IP
aws ec2 modify-subnet-attribute --subnet-id $SUBNET_ID --map-public-ip-on-launch

# 4. Create Route Table
echo "Creating Route Table..."
ROUTE_TABLE_ID=$(aws ec2 create-route-table --vpc-id $VPC_ID \
    --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=GeoShard-Public-RouteTable}]' \
    --query RouteTable.RouteTableId --output text)
echo "Created Route Table: $ROUTE_TABLE_ID"

# Add route to internet gateway
aws ec2 create-route --route-table-id $ROUTE_TABLE_ID --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID

# Associate Route Table with Subnet
aws ec2 associate-route-table --subnet-id $SUBNET_ID --route-table-id $ROUTE_TABLE_ID

# 5. Create Security Group
echo "Creating Security Group..."
SG_ID=$(aws ec2 create-security-group --group-name GeoShard-SG --description "Security group for GeoShardDB server" --vpc-id $VPC_ID \
    --tag-specifications 'ResourceType=security-group,Tags=[{Key=Name,Value=GeoShard-SG}]' \
    --query GroupId --output text)
echo "Created Security Group: $SG_ID"

# Authorize Security Group Inbound Rules
echo "Configuring Security Group Rules..."
# SSH
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0
# FastAPI
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0
# Redis Commander
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 8081 --cidr 0.0.0.0/0
# Grafana
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 3000 --cidr 0.0.0.0/0
# Prometheus
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 9090 --cidr 0.0.0.0/0
# PostgreSQL Shards (US: 5433, EU: 5434, ASIA: 5435)
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 5433-5435 --cidr 0.0.0.0/0

# 6. Create Key Pair
echo "Configuring SSH Key Pair..."
# Delete old key if it exists
aws ec2 delete-key-pair --key-name $KEY_NAME &> /dev/null || true
rm -f $KEY_FILE

# Create new key pair and save private key locally
aws ec2 create-key-pair --key-name $KEY_NAME --query KeyMaterial --output text > $KEY_FILE
chmod 400 $KEY_FILE
echo "Created key pair and saved to $KEY_FILE"

# 7. Create User Data script to install Docker & Docker Compose
echo "Generating User Data Script for Docker installation..."
cat << 'EOF' > user_data.sh
#!/bin/bash
apt-get update -y
apt-get install -y docker.io docker-compose git python3-pip python3-venv
systemctl start docker
systemctl enable docker
usermod -aG docker ubuntu
EOF

# 8. Launch Instance
echo "Launching EC2 instance ($INSTANCE_TYPE)..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type $INSTANCE_TYPE \
    --key-name $KEY_NAME \
    --security-group-ids $SG_ID \
    --subnet-id $SUBNET_ID \
    --user-data file://user_data.sh \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=GeoShard-Server}]' \
    --query 'Instances[0].InstanceId' --output text)

# Clean up temp file
rm -f user_data.sh

echo "Launched EC2 Instance: $INSTANCE_ID"

# Wait for instance to be running
echo "Waiting for instance to reach running state..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# Get Public IP
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
PUBLIC_DNS=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

echo "=================================================="
echo "AWS Infrastructure Setup Complete!"
echo "=================================================="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP  : $PUBLIC_IP"
echo "Public DNS : $PUBLIC_DNS"
echo "Key File   : $KEY_FILE"
echo ""
echo "SSH Access Command:"
echo "ssh -i $KEY_FILE ubuntu@$PUBLIC_IP"
echo ""
echo "To copy your code to the instance:"
echo "rsync -avz -e \"ssh -i $KEY_FILE\" --exclude 'venv' --exclude '*.pem' ./ ubuntu@$PUBLIC_IP:~/GeoShardDB/"
echo "=================================================="
