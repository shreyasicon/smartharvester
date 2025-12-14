#!/usr/bin/env python
"""
Debug script to test save_planting functionality
Run this to check what errors occur when saving a planting
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from tracker.dynamodb_helper import save_planting_to_dynamodb
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Test planting data
test_planting = {
    'crop_name': 'Test Crop',
    'planting_date': '2025-01-01',
    'batch_id': 'batch-20250101',
    'notes': 'Test notes',
    'image_url': '',
    'user_id': 'test-user-123',
    'username': 'testuser',
    'plan': []
}

print("Testing save_planting_to_dynamodb...")
print(f"Test data: {test_planting}")

try:
    result = save_planting_to_dynamodb(test_planting)
    if result:
        print(f"✅ Success! Planting ID: {result}")
    else:
        print("❌ Failed - function returned None")
        print("Check logs above for errors")
except Exception as e:
    print(f"❌ Exception occurred: {e}")
    import traceback
    traceback.print_exc()

