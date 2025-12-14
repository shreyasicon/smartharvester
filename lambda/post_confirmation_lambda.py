import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USERS_TABLE = os.environ.get("DYNAMO_USERS_TABLE", "users")
USERS_PK = os.environ.get("DYNAMO_USERS_PK", "username")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
users_table = dynamodb.Table(USERS_TABLE)

def _extract_attrs_from_cognito_event(event: Dict[str, Any]) -> Dict[str, Any]:
    attrs = event.get("request", {}).get("userAttributes", {}) or {}
    return {
        "user_id": attrs.get("sub"),
        "email": attrs.get("email"),
        "name": attrs.get("name") or attrs.get("given_name"),
        "preferred_username": attrs.get("preferred_username"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def _upsert_user(username: str, attrs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not username:
        logger.error("No username provided for upsert")
        return None

    clean = {k: v for k, v in attrs.items() if v is not None}
    if not clean:
        logger.info("No attributes to write for user=%s", username)
        return None

    expr_names = {}
    expr_values = {}
    sets = []

    for i, (k, v) in enumerate(clean.items()):
        nk = f"#k{i}"
        vk = f":v{i}"
        expr_names[nk] = k
        expr_values[vk] = v
        sets.append(f"{nk} = {vk}")

    update_expr = "SET " + ", ".join(sets)

    try:
        resp = users_table.update_item(
            Key={USERS_PK: username},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW"
        )
        logger.info("Upserted user=%s attrs=%s", username, list(clean.keys()))
        return resp.get("Attributes")
    except ClientError:
        logger.exception("Failed to upsert user=%s", username)
        return None

def _delete_user(username: str) -> bool:
    if not username:
        logger.error("No username provided for delete")
        return False

    try:
        users_table.delete_item(Key={USERS_PK: username})
        logger.info("Deleted user=%s", username)
        return True
    except ClientError:
        logger.exception("Failed to delete user=%s", username)
        return False

def lambda_handler(event: Dict[str, Any], context):
    logger.info("User CRUD manager invoked")

    if isinstance(event, dict) and event.get("Records"):
        logger.info("Received stream-style event, ignoring in Cognito function.")
        return event

    trigger = event.get("triggerSource", "") or ""

    if "PostConfirmation" in trigger:
        username = event.get("userName")
        attrs = _extract_attrs_from_cognito_event(event)
        _upsert_user(username, attrs)
        return event

    op = (event.get("operation") or "").lower()

    if op in ("create", "update"):
        username = event.get("username")
        attrs = event.get("attributes") or {}
        if not username and event.get("cognito"):
            username = event["cognito"].get("userName")
            attrs = attrs or _extract_attrs_from_cognito_event(event["cognito"])
        _upsert_user(username, attrs)
        return event

    elif op == "delete":
        username = event.get("username")
        _delete_user(username)
        return event

    logger.info("No action taken (no PostConfirmation trigger and no operation specified)")
    return event
