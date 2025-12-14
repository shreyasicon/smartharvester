#!/bin/bash
# Script to deploy Cognito auto-confirm Lambda function
# Usage: bash scripts/deploy_cognito_lambda.sh

set -e

FUNCTION_NAME="cognito-auto-confirm"
RUNTIME="python3.9"
REGION="${AWS_REGION:-us-east-1}"
ROLE_NAME="${FUNCTION_NAME}-role"

echo "=========================================="
echo "Deploying Cognito Auto-Confirm Lambda"
echo "=========================================="
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed. Please install it first."
    echo "   Visit: https://aws.amazon.com/cli/"
    exit 1
fi

# Check if AWS credentials are configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS credentials not configured. Please run 'aws configure'"
    exit 1
fi

echo "✅ AWS CLI configured"
echo ""

# Check if function exists
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &> /dev/null; then
    echo "📦 Function exists, updating code..."
    
    # Create deployment package
    cd lambda
    zip -q function.zip cognito_auto_confirm.py
    cd ..
    
    # Update function code
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb://lambda/function.zip \
        --region "$REGION" \
        --output json > /dev/null
    
    echo "✅ Function code updated"
    rm -f lambda/function.zip
else
    echo "📦 Creating new function..."
    
    # Create IAM role for Lambda (if it doesn't exist)
    if ! aws iam get-role --role-name "$ROLE_NAME" &> /dev/null; then
        echo "Creating IAM role..."
        aws iam create-role \
            --role-name "$ROLE_NAME" \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }' > /dev/null
        
        # Attach basic execution role
        aws iam attach-role-policy \
            --role-name "$ROLE_NAME" \
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
        
        echo "✅ IAM role created"
    fi
    
    # Get role ARN
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
    
    # Create deployment package
    cd lambda
    zip -q function.zip cognito_auto_confirm.py
    cd ..
    
    # Create function
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime "$RUNTIME" \
        --role "$ROLE_ARN" \
        --handler cognito_auto_confirm.lambda_handler \
        --zip-file fileb://lambda/function.zip \
        --description "Auto-confirms and auto-verifies Cognito users on sign-up" \
        --timeout 10 \
        --memory-size 128 \
        --region "$REGION" \
        --output json > /dev/null
    
    echo "✅ Function created"
    rm -f lambda/function.zip
fi

echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Grant Cognito permission to invoke the Lambda:"
echo "   - Go to Lambda → $FUNCTION_NAME → Configuration → Permissions"
echo "   - Add resource-based policy to allow cognito-idp.amazonaws.com"
echo ""
echo "2. Attach Lambda to Cognito User Pool:"
echo "   - Go to Cognito → User Pools → Your Pool → Triggers"
echo "   - Select '$FUNCTION_NAME' in Pre sign-up dropdown"
echo "   - Save changes"
echo ""
echo "3. Test by signing up a new user via Hosted UI"
echo ""
echo "Function ARN:"
aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text
echo ""

