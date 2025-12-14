"""
Script to create the DynamoDB users table.

Run this script once to create the table:
    python scripts/create_users_table.py

Requirements:
    - AWS credentials configured (via environment variables, IAM role, or ~/.aws/credentials)
    - boto3 installed
    - Appropriate AWS permissions to create DynamoDB tables

Environment Variables:
    - AWS_ACCESS_KEY_ID: Your AWS access key
    - AWS_SECRET_ACCESS_KEY: Your AWS secret key
    - DYNAMODB_USERS_TABLE_NAME: Table name (default: 'users')
    - AWS_S3_REGION_NAME: AWS region (default: 'us-east-1')
"""

import boto3
import os
import sys
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# Load environment variables
load_dotenv()

# Configuration
TABLE_NAME = os.getenv('DYNAMODB_USERS_TABLE_NAME', 'users')
REGION = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

def create_table():
    """Create the DynamoDB users table."""
    # Initialize DynamoDB client with credentials
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        dynamodb = boto3.client(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=REGION
        )
    else:
        # Try to use default credentials (from IAM role or ~/.aws/credentials)
        dynamodb = boto3.client('dynamodb', region_name=REGION)
    
    # Check if table already exists
    try:
        response = dynamodb.describe_table(TableName=TABLE_NAME)
        print(f"✓ Table '{TABLE_NAME}' already exists.")
        print(f"  Table ARN: {response['Table']['TableArn']}")
        print(f"  Status: {response['Table']['TableStatus']}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] != 'ResourceNotFoundException':
            print(f"Error checking table: {e}")
            return False
    
    # Table doesn't exist, create it
    try:
        print(f"Creating table '{TABLE_NAME}' in region '{REGION}'...")
        print(f"  Partition Key: username (String)")
        print(f"  Billing Mode: PAY_PER_REQUEST (On-demand)")
        
        response = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {
                    'AttributeName': 'username',
                    'KeyType': 'HASH'  # Partition key
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'username',
                    'AttributeType': 'S'  # String
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # On-demand pricing
        )
        
        print(f"  Table ARN: {response['TableDescription']['TableArn']}")
        print("  Waiting for table to become active...")
        
        # Wait for table to be created
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=TABLE_NAME)
        
        print(f"✓ Table '{TABLE_NAME}' created successfully!")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceInUseException':
            print(f"Table '{TABLE_NAME}' already exists.")
            return True
        else:
            print(f"✗ Error creating table: {e}")
            print(f"  Error Code: {error_code}")
            return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False

if __name__ == '__main__':
    success = create_table()
    sys.exit(0 if success else 1)

