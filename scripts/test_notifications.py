#!/usr/bin/env python3
"""Test script to check if notifications are being saved and can be loaded."""

import boto3
import os
from datetime import datetime

REGION = os.getenv("AWS_REGION", "us-east-1")
TABLE_NAME = os.getenv("DYNAMO_NOTIFICATIONS_TABLE", "notifications")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

print("=== Checking Notifications Table ===")
print(f"Table: {TABLE_NAME}")
print(f"Region: {REGION}")
print()

# Scan all notifications
resp = table.scan()
items = resp.get("Items", [])

print(f"Total notifications in table: {len(items)}")
print()

if items:
    print("=== Sample Notifications ===")
    for i, item in enumerate(items[:5], 1):
        print(f"\nNotification {i}:")
        print(f"  Notification ID: {item.get('notification_id', 'N/A')}")
        print(f"  User ID: {item.get('user_id', 'N/A')}")
        print(f"  Type: {item.get('notification_type', 'N/A')}")
        print(f"  Title: {item.get('title', 'N/A')}")
        print(f"  Message: {item.get('message', 'N/A')[:50]}...")
        created_at = item.get('created_at', 0)
        if isinstance(created_at, (int, float)):
            dt = datetime.fromtimestamp(float(created_at))
            print(f"  Created: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"  Created: {created_at}")
        print(f"  Read: {item.get('read', False)}")
else:
    print("No notifications found in table.")
    print()
    print("To test notifications:")
    print("1. Add a plant in your app")
    print("2. Check server logs for: '✅ Saved notification'")
    print("3. Run this script again to verify the notification was saved")

