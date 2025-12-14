#!/bin/bash
# Setup script for AWS services as per architecture
# This script helps set up all AWS services required for SmartHarvester

set -e

AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-518029233624}"

echo "=== SmartHarvester AWS Services Setup ==="
echo "Region: $AWS_REGION"
echo "Account ID: $ACCOUNT_ID"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}AWS CLI is not installed. Please install it first.${NC}"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}AWS credentials not configured. Please run 'aws configure' first.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ AWS CLI configured${NC}"
echo ""

# Function to create DynamoDB table
create_dynamodb_table() {
    local table_name=$1
    local partition_key=$2
    local key_type=$3
    
    echo "Creating DynamoDB table: $table_name"
    
    if aws dynamodb describe-table --table-name "$table_name" --region "$AWS_REGION" &> /dev/null; then
        echo -e "${YELLOW}  Table $table_name already exists${NC}"
        return 0
    fi
    
    aws dynamodb create-table \
        --table-name "$table_name" \
        --attribute-definitions AttributeName="$partition_key",AttributeType="$key_type" \
        --key-schema AttributeName="$partition_key",KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "$AWS_REGION" \
        --tags Key=Project,Value=SmartHarvester Key=Environment,Value=Production
    
    echo "  Waiting for table to be active..."
    aws dynamodb wait table-exists --table-name "$table_name" --region "$AWS_REGION"
    echo -e "${GREEN}  ✓ Table $table_name created${NC}"
}

# Function to create GSI on DynamoDB table
create_gsi() {
    local table_name=$1
    local index_name=$2
    local partition_key=$3
    local key_type=$4
    
    echo "Creating GSI $index_name on table: $table_name"
    
    aws dynamodb update-table \
        --table-name "$table_name" \
        --attribute-definitions AttributeName="$partition_key",AttributeType="$key_type" \
        --global-secondary-index-updates \
        "[{
            \"Create\": {
                \"IndexName\": \"$index_name\",
                \"KeySchema\": [{\"AttributeName\": \"$partition_key\", \"KeyType\": \"HASH\"}],
                \"Projection\": {\"ProjectionType\": \"ALL\"}
            }
        }]" \
        --region "$AWS_REGION" &> /dev/null || echo -e "${YELLOW}  GSI may already exist${NC}"
    
    echo -e "${GREEN}  ✓ GSI $index_name created${NC}"
}

# Function to create S3 bucket
create_s3_bucket() {
    local bucket_name=$1
    
    echo "Creating S3 bucket: $bucket_name"
    
    if aws s3 ls "s3://$bucket_name" &> /dev/null; then
        echo -e "${YELLOW}  Bucket $bucket_name already exists${NC}"
    else
        if [ "$AWS_REGION" == "us-east-1" ]; then
            aws s3api create-bucket \
                --bucket "$bucket_name" \
                --region "$AWS_REGION"
        else
            aws s3api create-bucket \
                --bucket "$bucket_name" \
                --region "$AWS_REGION" \
                --create-bucket-configuration LocationConstraint="$AWS_REGION"
        fi
        
        # Set bucket policy for public read access to media files
        cat > /tmp/bucket-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::$bucket_name/media/*"
        }
    ]
}
EOF
        
        aws s3api put-bucket-policy --bucket "$bucket_name" --policy file:///tmp/bucket-policy.json
        rm /tmp/bucket-policy.json
        
        echo -e "${GREEN}  ✓ Bucket $bucket_name created with public read access for media${NC}"
    fi
}

# Function to create SNS topic
create_sns_topic() {
    local topic_name=$1
    
    echo "Creating SNS topic: $topic_name"
    
    local topic_arn=$(aws sns list-topics --region "$AWS_REGION" --query "Topics[?contains(TopicArn, '$topic_name')].TopicArn" --output text)
    
    if [ -z "$topic_arn" ]; then
        topic_arn=$(aws sns create-topic \
            --name "$topic_name" \
            --region "$AWS_REGION" \
            --tags Key=Project,Value=SmartHarvester \
            --query 'TopicArn' --output text)
        echo -e "${GREEN}  ✓ Topic $topic_name created: $topic_arn${NC}"
    else
        echo -e "${YELLOW}  Topic $topic_name already exists: $topic_arn${NC}"
    fi
    
    echo "$topic_arn"
}

# 1. Create DynamoDB Tables
echo "=== Step 1: Creating DynamoDB Tables ==="
create_dynamodb_table "users" "username" "S"
create_dynamodb_table "plantings" "planting_id" "S"
echo ""

# 2. Create GSI on plantings table
echo "=== Step 2: Creating GSI on plantings table ==="
create_gsi "plantings" "user_id-index" "user_id" "S"
echo ""

# 3. Create S3 Bucket
echo "=== Step 3: Creating S3 Bucket ==="
create_s3_bucket "terratrack-media"
echo ""

# 4. Create SNS Topic
echo "=== Step 4: Creating SNS Topic ==="
TOPIC_ARN=$(create_sns_topic "harvest-notifications")
echo ""

# 5. Deploy Lambda Functions
echo "=== Step 5: Deploying Lambda Functions ==="
echo "Note: Lambda functions need to be deployed separately using AWS Console or CLI"
echo "Functions to deploy:"
echo "  1. cognito-auto-confirm (Pre Sign-up trigger)"
echo "  2. post-confirmation (Post Confirmation trigger)"
echo "  3. notification-lambda (Scheduled notifications - optional)"
echo ""
echo "Use: scripts/deploy_cognito_lambda.sh to deploy Cognito triggers"
echo ""

# 6. Summary
echo "=== Setup Summary ==="
echo -e "${GREEN}✓ DynamoDB Tables:${NC}"
echo "  - users (PK: username)"
echo "  - plantings (PK: planting_id, GSI: user_id-index)"
echo ""
echo -e "${GREEN}✓ S3 Bucket:${NC}"
echo "  - terratrack-media"
echo ""
echo -e "${GREEN}✓ SNS Topic:${NC}"
echo "  - $TOPIC_ARN"
echo ""
echo -e "${YELLOW}⚠ Next Steps:${NC}"
echo "1. Configure Cognito User Pool (already exists: us-east-1_HGEM2vRNI)"
echo "2. Deploy Lambda functions (use scripts/deploy_cognito_lambda.sh)"
echo "3. Attach Lambda triggers to Cognito User Pool"
echo "4. Set up RDS PostgreSQL (use infrastructure.yml CloudFormation template)"
echo "5. Configure IAM roles and permissions (see docs/AWS_IAM_SETUP.md)"
echo "6. Set environment variables (see docs/AWS_ENV_TEMPLATE.md)"
echo ""
echo -e "${GREEN}Setup complete!${NC}"

