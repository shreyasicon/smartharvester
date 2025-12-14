"""
tracker/dynamo.py

Runtime DynamoDB helper for application views.
Provides simple functions to interact with users and plantings tables.
Designed to work with Cognito user IDs (sub) and usernames.
"""
import os
import uuid
import logging
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr
from typing import Dict, List, Optional, Any
from decimal import Decimal

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_S3_REGION_NAME", "us-east-1"))

USERS_TABLE = os.getenv("DYNAMODB_USERS_TABLE_NAME", os.getenv("DYNAMO_USERS_TABLE", "users"))
PLANTINGS_TABLE = os.getenv("DYNAMODB_PLANTINGS_TABLE_NAME", os.getenv("DYNAMO_PLANTINGS_TABLE", "plantings"))

_dynamo_resource = None


def _resource():
    """Get or create DynamoDB resource."""
    global _dynamo_resource
    if _dynamo_resource is None:
        _dynamo_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamo_resource


def get_users_table():
    """Get users table."""
    return _resource().Table(USERS_TABLE)


def get_plantings_table():
    """Get plantings table."""
    return _resource().Table(PLANTINGS_TABLE)


def _to_dynamo_value(obj: Any) -> Any:
    """Convert Python types to DynamoDB-compatible types."""
    if isinstance(obj, dict):
        return {k: _to_dynamo_value(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_to_dynamo_value(v) for v in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


# --- Users helpers ---
def get_user(username_or_userid: str) -> Optional[Dict[str, Any]]:
    """
    Get user by username (PK) or user_id.
    Tries PK first, then scans by user_id if not found.
    """
    try:
        # Try direct get by username (assuming username is PK)
        resp = get_users_table().get_item(Key={"username": username_or_userid})
        item = resp.get("Item")
        if item:
            return item
        
        # Fallback: scan by user_id
        resp = get_users_table().scan(
            FilterExpression=Attr("user_id").eq(username_or_userid),
            Limit=1
        )
        items = resp.get("Items", [])
        if items:
            return items[0]
        return None
    except ClientError as e:
        logger.exception("DynamoDB get_user failed for %s: %s", username_or_userid, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error in get_user for %s: %s", username_or_userid, e)
        return None


def put_user(user_item: Dict[str, Any]) -> bool:
    """
    Save or update user. Ensures username is present (used as PK).
    """
    if "username" not in user_item:
        # Try to extract from user_id or email
        user_item["username"] = user_item.get("user_id") or user_item.get("email") or user_item.get("sub", "")
        if not user_item["username"]:
            raise ValueError("user_item must include 'username' or 'user_id' or 'email'")
    
    try:
        item = _to_dynamo_value(user_item)
        get_users_table().put_item(Item=item)
        logger.info("Saved user to DynamoDB: %s", user_item.get("username"))
        return True
    except ClientError as e:
        logger.exception("DynamoDB put_user failed for %s: %s", user_item.get("username"), e)
        return False
    except Exception as e:
        logger.exception("Unexpected error in put_user: %s", e)
        return False


def list_users(limit=100, exclusive_start_key=None):
    """List users with pagination."""
    kwargs = {}
    if limit:
        kwargs["Limit"] = limit
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key
    try:
        resp = get_users_table().scan(**kwargs)
        return resp.get("Items", []), resp.get("LastEvaluatedKey")
    except ClientError as e:
        logger.exception("DynamoDB scan users failed: %s", e)
        return [], None
    except Exception as e:
        logger.exception("Unexpected error in list_users: %s", e)
        return [], None


# --- Plantings helpers ---
def create_planting(username_or_userid: str, planting_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Create a planting for a user. Accepts username or user_id.
    Returns the created planting item or None on failure.
    """
    planting_id = planting_data.get("planting_id") or str(uuid.uuid4())
    item = {
        "planting_id": planting_id,
        **planting_data,
    }
    
    # Support both username (PK) and user_id patterns
    if "username" not in item and "user_id" not in item:
        # Try to determine if username_or_userid is a username or user_id
        # For now, assume it's a username if it doesn't look like a UUID
        if not (len(username_or_userid) == 36 and username_or_userid.count('-') == 4):
            item["username"] = username_or_userid
        else:
            item["user_id"] = username_or_userid
    elif "username" not in item:
        item["username"] = username_or_userid
    elif "user_id" not in item:
        item["user_id"] = username_or_userid
    
    try:
        item = _to_dynamo_value(item)
        get_plantings_table().put_item(Item=item)
        logger.info("Created planting %s for user %s", planting_id, username_or_userid)
        return item
    except ClientError as e:
        logger.exception("DynamoDB put planting failed for %s/%s: %s", username_or_userid, planting_id, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error in create_planting: %s", e)
        return None


def get_plantings_for_user(username_or_userid: str) -> List[Dict[str, Any]]:
    """
    Get all plantings for a user. Supports both username (PK) and user_id.
    Tries GSI query first, then scan fallback.
    """
    try:
        table = get_plantings_table()
        
        # Try GSI query by user_id first
        try:
            resp = table.query(
                IndexName="user_id-index",
                KeyConditionExpression=Key("user_id").eq(username_or_userid)
            )
            items = resp.get("Items", [])
            if items:
                logger.debug("Queried %d plantings via GSI for %s", len(items), username_or_userid)
                return items
        except ClientError:
            # GSI might not exist, continue to fallback
            pass
        
        # Try direct query by username (if username is PK)
        try:
            resp = table.query(KeyConditionExpression=Key("username").eq(username_or_userid))
            items = resp.get("Items", [])
            if items:
                logger.debug("Queried %d plantings by username for %s", len(items), username_or_userid)
                return items
        except ClientError:
            pass
        
        # Fallback: scan with filter
        items = []
        scan_kwargs = {
            "FilterExpression": Attr("user_id").eq(username_or_userid) | Attr("username").eq(username_or_userid)
        }
        start_key = None
        while True:
            if start_key:
                scan_kwargs["ExclusiveStartKey"] = start_key
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []) or [])
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        
        logger.debug("Scanned and found %d plantings for %s", len(items), username_or_userid)
        return items
    except ClientError as e:
        logger.exception("DynamoDB query plantings failed for %s: %s", username_or_userid, e)
        return []
    except Exception as e:
        logger.exception("Unexpected error in get_plantings_for_user: %s", e)
        return []


def get_planting(username_or_userid: str, planting_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific planting. Tries direct get by PK, then scan fallback.
    """
    try:
        table = get_plantings_table()
        
        # Try direct get if planting_id is PK
        try:
            resp = table.get_item(Key={"planting_id": planting_id})
            item = resp.get("Item")
            if item:
                # Verify it belongs to the user
                if item.get("username") == username_or_userid or item.get("user_id") == username_or_userid:
                    return item
        except ClientError:
            pass
        
        # Fallback: scan and filter
        resp = table.scan(
            FilterExpression=Attr("planting_id").eq(planting_id) & (
                Attr("username").eq(username_or_userid) | Attr("user_id").eq(username_or_userid)
            ),
            Limit=1
        )
        items = resp.get("Items", [])
        if items:
            return items[0]
        return None
    except ClientError as e:
        logger.exception("DynamoDB get planting failed for %s/%s: %s", username_or_userid, planting_id, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error in get_planting: %s", e)
        return None


def update_planting(username_or_userid: str, planting_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a planting. Returns updated item or None."""
    if not updates:
        return None
    
    try:
        # First get the planting to find its key
        planting = get_planting(username_or_userid, planting_id)
        if not planting:
            logger.warning("Planting %s not found for user %s", planting_id, username_or_userid)
            return None
        
        # Build update expression
        expression_parts = []
        expression_vals = {}
        for i, (k, v) in enumerate(updates.items()):
            placeholder = f":v{i}"
            expression_parts.append(f"{k} = {placeholder}")
            expression_vals[placeholder] = _to_dynamo_value(v)
        
        update_expr = "SET " + ", ".join(expression_parts)
        
        # Determine key - try planting_id as PK, or composite key
        key = {"planting_id": planting_id}
        if "username" in planting:
            key = {"username": planting["username"], "planting_id": planting_id}
        
        resp = get_plantings_table().update_item(
            Key=key,
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expression_vals,
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")
    except ClientError as e:
        logger.exception("DynamoDB update planting failed for %s/%s: %s", username_or_userid, planting_id, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error in update_planting: %s", e)
        return None


def delete_planting(username_or_userid: str, planting_id: str) -> bool:
    """Delete a planting. Returns True on success."""
    try:
        # First get the planting to find its key
        planting = get_planting(username_or_userid, planting_id)
        if not planting:
            logger.warning("Planting %s not found for user %s", planting_id, username_or_userid)
            return False
        
        # Determine key - try planting_id as PK, or composite key
        key = {"planting_id": planting_id}
        if "username" in planting:
            key = {"username": planting["username"], "planting_id": planting_id}
        
        get_plantings_table().delete_item(Key=key)
        logger.info("Deleted planting %s for user %s", planting_id, username_or_userid)
        return True
    except ClientError as e:
        logger.exception("DynamoDB delete planting failed for %s/%s: %s", username_or_userid, planting_id, e)
        return False
    except Exception as e:
        logger.exception("Unexpected error in delete_planting: %s", e)
        return False