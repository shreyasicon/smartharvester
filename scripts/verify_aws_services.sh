#!/bin/bash
# Verification script for AWS services
# Checks if all required AWS services are properly configured

set -e

AWS_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-518029233624}"

echo "=== Verifying AWS Services Configuration ==="
echo "Region: $AWS_REGION"
echo "Account ID: $ACCOUNT_ID"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}✗ AWS CLI not installed${NC}"
    ERRORS=$((ERRORS + 1))
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}✗ AWS credentials not configured${NC}"
    ERRORS=$((ERRORS + 1))
    exit 1
fi

echo -e "${GREEN}✓ AWS CLI configured${NC}"
echo ""

# Check DynamoDB Tables
echo "=== DynamoDB Tables ==="
for table in users plantings; do
    if aws dynamodb describe-table --table-name "$table" --region "$AWS_REGION" &> /dev/null; then
        echo -e "${GREEN}✓ Table '$table' exists${NC}"
        
        # Check for GSI on plantings table
        if [ "$table" == "plantings" ]; then
            if aws dynamodb describe-table --table-name "$table" --region "$AWS_REGION" --query 'Table.GlobalSecondaryIndexes[?IndexName==`user_id-index`]' --output text | grep -q "user_id-index"; then
                echo -e "${GREEN}  ✓ GSI 'user_id-index' exists${NC}"
            else
                echo -e "${YELLOW}  ⚠ GSI 'user_id-index' not found${NC}"
                WARNINGS=$((WARNINGS + 1))
            fi
        fi
    else
        echo -e "${RED}✗ Table '$table' does not exist${NC}"
        ERRORS=$((ERRORS + 1))
    fi
done
echo ""

# Check S3 Bucket
echo "=== S3 Bucket ==="
BUCKET="terratrack-media"
if aws s3 ls "s3://$BUCKET" &> /dev/null; then
    echo -e "${GREEN}✓ Bucket '$BUCKET' exists${NC}"
    
    # Check bucket policy
    if aws s3api get-bucket-policy --bucket "$BUCKET" &> /dev/null; then
        echo -e "${GREEN}  ✓ Bucket policy configured${NC}"
    else
        echo -e "${YELLOW}  ⚠ Bucket policy not configured (public read may not work)${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}✗ Bucket '$BUCKET' does not exist${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check SNS Topic
echo "=== SNS Topic ==="
TOPIC_NAME="harvest-notifications"
TOPIC_ARN=$(aws sns list-topics --region "$AWS_REGION" --query "Topics[?contains(TopicArn, '$TOPIC_NAME')].TopicArn" --output text 2>/dev/null || echo "")
if [ -n "$TOPIC_ARN" ]; then
    echo -e "${GREEN}✓ Topic '$TOPIC_NAME' exists: $TOPIC_ARN${NC}"
else
    echo -e "${YELLOW}⚠ Topic '$TOPIC_NAME' not found (optional for notifications)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# Check Cognito User Pool
echo "=== Cognito User Pool ==="
POOL_ID="us-east-1_HGEM2vRNI"
if aws cognito-idp describe-user-pool --user-pool-id "$POOL_ID" --region "$AWS_REGION" &> /dev/null; then
    echo -e "${GREEN}✓ User Pool '$POOL_ID' exists${NC}"
    
    # Check for domain
    DOMAIN=$(aws cognito-idp describe-user-pool --user-pool-id "$POOL_ID" --region "$AWS_REGION" --query 'UserPool.Domain' --output text 2>/dev/null || echo "")
    if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "None" ]; then
        echo -e "${GREEN}  ✓ Domain configured: $DOMAIN${NC}"
    else
        echo -e "${YELLOW}  ⚠ Domain not configured${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check for Lambda triggers
    TRIGGERS=$(aws cognito-idp describe-user-pool --user-pool-id "$POOL_ID" --region "$AWS_REGION" --query 'UserPool.LambdaConfig' --output json 2>/dev/null || echo "{}")
    if echo "$TRIGGERS" | grep -q "PreSignUp\|PostConfirmation"; then
        echo -e "${GREEN}  ✓ Lambda triggers configured${NC}"
    else
        echo -e "${YELLOW}  ⚠ Lambda triggers not configured${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}✗ User Pool '$POOL_ID' does not exist${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check Lambda Functions
echo "=== Lambda Functions ==="
for func in cognito-auto-confirm post-confirmation notification-lambda; do
    if aws lambda get-function --function-name "$func" --region "$AWS_REGION" &> /dev/null; then
        echo -e "${GREEN}✓ Function '$func' exists${NC}"
    else
        if [ "$func" == "notification-lambda" ]; then
            echo -e "${YELLOW}⚠ Function '$func' not found (optional)${NC}"
            WARNINGS=$((WARNINGS + 1))
        else
            echo -e "${RED}✗ Function '$func' does not exist${NC}"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done
echo ""

# Check RDS (optional - may not exist)
echo "=== RDS Database ==="
RDS_INSTANCES=$(aws rds describe-db-instances --region "$AWS_REGION" --query 'DBInstances[?contains(DBInstanceIdentifier, `terratrack`) || contains(DBInstanceIdentifier, `smartharvester`)].DBInstanceIdentifier' --output text 2>/dev/null || echo "")
if [ -n "$RDS_INSTANCES" ]; then
    echo -e "${GREEN}✓ RDS instance found: $RDS_INSTANCES${NC}"
else
    echo -e "${YELLOW}⚠ RDS instance not found (optional - SQLite fallback available)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# Summary
echo "=== Verification Summary ==="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All required services are configured correctly!${NC}"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ All required services exist, but $WARNINGS warning(s) found${NC}"
    exit 0
else
    echo -e "${RED}✗ Found $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo ""
    echo "Run: scripts/setup_aws_services.sh to set up missing services"
    exit 1
fi

