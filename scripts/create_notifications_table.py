#!/usr/bin/env python3
"""
Script to create the DynamoDB notifications table for in-app notifications.
This table stores user notifications (plant_added, plant_edited, plant_deleted, harvest_reminder, step_reminder).

Usage:
    python scripts/create_notifications_table.py
"""

import boto3
from botocore.exceptions import ClientError
import os

# Configuration
REGION = os.getenv("AWS_REGION", "us-east-1")
TABLE_NAME = os.getenv("DYNAMO_NOTIFICATIONS_TABLE", "notifications")

dynamodb = boto3.client("dynamodb", region_name=REGION)


def create_table():
    """Create the DynamoDB notifications table."""
    print(f"Checking for table '{TABLE_NAME}' in region '{REGION}'...")
    
    # Check if table exists
    try:
        response = dynamodb.describe_table(TableName=TABLE_NAME)
        table_status = response['Table']['TableStatus']
        print(f"[OK] Table '{TABLE_NAME}' already exists (Status: {table_status})")
        
        # Check if GSI exists
        gsi_exists = False
        for index in response['Table'].get('GlobalSecondaryIndexes', []):
            if index['IndexName'] == 'user_id-index':
                gsi_exists = True
                print(f"[OK] GSI 'user_id-index' already exists")
                break
        
        if not gsi_exists:
            print("[WARN] GSI 'user_id-index' does not exist. Creating it...")
            try:
                dynamodb.update_table(
                    TableName=TABLE_NAME,
                    AttributeDefinitions=[
                        {
                            'AttributeName': 'notification_id',
                            'AttributeType': 'S'
                        },
                        {
                            'AttributeName': 'user_id',
                            'AttributeType': 'S'
                        }
                    ],
                    GlobalSecondaryIndexUpdates=[
                        {
                            'Create': {
                                'IndexName': 'user_id-index',
                                'KeySchema': [
                                    {
                                        'AttributeName': 'user_id',
                                        'KeyType': 'HASH'
                                    }
                                ],
                                'Projection': {
                                    'ProjectionType': 'ALL'
                                },
                                'BillingMode': 'PAY_PER_REQUEST'
                            }
                        }
                    ]
                )
                print("[OK] GSI 'user_id-index' created successfully!")
                print("  Waiting for index to become active...")
                waiter = dynamodb.get_waiter('table_exists')
                waiter.wait(TableName=TABLE_NAME)
            except Exception as e:
                print(f"[ERROR] Error creating GSI: {e}")
        
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code != 'ResourceNotFoundException':
            print(f"[ERROR] Error checking table: {e}")
            return False
    
    # Table doesn't exist, create it
    try:
        print(f"Creating table '{TABLE_NAME}' in region '{REGION}'...")
        print(f"  Partition Key: notification_id (String)")
        print(f"  GSI: user_id-index (for querying by user_id)")
        print(f"  Billing Mode: PAY_PER_REQUEST (On-demand)")
        
        response = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {
                    'AttributeName': 'notification_id',
                    'KeyType': 'HASH'  # Partition key
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'notification_id',
                    'AttributeType': 'S'  # String
                },
                {
                    'AttributeName': 'user_id',
                    'AttributeType': 'S'  # String (for GSI)
                }
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'user_id-index',
                    'KeySchema': [
                        {
                            'AttributeName': 'user_id',
                            'KeyType': 'HASH'
                        }
                    ],
                    'Projection': {
                        'ProjectionType': 'ALL'
                    }
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # On-demand pricing
        )
        
        print(f"  Table ARN: {response['TableDescription']['TableArn']}")
        print("  Waiting for table to become active...")
        
        # Wait for table to be created
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=TABLE_NAME)
        
        print(f"[OK] Table '{TABLE_NAME}' created successfully!")
        print(f"[OK] GSI 'user_id-index' created successfully!")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceInUseException':
            print(f"Table '{TABLE_NAME}' already exists.")
            return True
        else:
            print(f"[ERROR] Error creating table: {e}")
            print(f"  Error Code: {error_code}")
            return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return False


if __name__ == '__main__':
    create_table()

