import os
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeDeserializer
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

USERS_TABLE = os.environ.get("USERS_TABLE", "users")
USERS_PK = os.environ.get("USERS_PK", "username")
PLANTINGS_TABLE = os.environ.get("PLANTINGS_TABLE", "plantings")
PLANTINGS_GSI = os.environ.get("PLANTINGS_GSI", "username-index")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
users_table = dynamodb.Table(USERS_TABLE)
plantings_table = dynamodb.Table(PLANTINGS_TABLE)
deserializer = TypeDeserializer()

def _dynamo_to_py(dd: Dict[str, Any]) -> Dict[str, Any]:
    if not dd:
        return {}
    return {k: deserializer.deserialize(v) for k, v in dd.items()}

def _recompute_and_update_user_counts(username: str):
    try:
        resp = plantings_table.query(
            IndexName=PLANTINGS_GSI,
            KeyConditionExpression=Key("username").eq(username),
            Select="COUNT",
        )
        count = resp.get("Count", 0)
    except ClientError:
        logger.exception("Failed to query plantings count for username=%s", username)
        return

    ts = datetime.now(timezone.utc).isoformat()
    try:
        users_table.update_item(
            Key={USERS_PK: username},
            UpdateExpression="SET planting_count = :c, last_planting_update = :t",
            ExpressionAttributeValues={":c": count, ":t": ts},
        )
        logger.info("Updated user %s planting_count=%d", username, count)
    except ClientError:
        logger.exception("Failed to update user %s", username)

def stream_handler(event, context):
    records = event.get("Records", [])
    logger.info("Plantings stream handler invoked with %d records", len(records))

    processed = 0
    for rec in records:
        processed += 1
        try:
            ddb = rec.get("dynamodb", {})
            new_py = _dynamo_to_py(ddb.get("NewImage", {})) if ddb.get("NewImage") else {}
            old_py = _dynamo_to_py(ddb.get("OldImage", {})) if ddb.get("OldImage") else {}
            username = (new_py or {}).get("username") or (old_py or {}).get("username")

            if username:
                _recompute_and_update_user_counts(username)
        except Exception:
            logger.exception("Error processing planting record")

        if processed % 200 == 0:
            time.sleep(0.1)

    logger.info("Plantings stream processing complete processed=%d", processed)
    return {"status": "ok", "processed": processed}

def lambda_handler(event, context):
    return stream_handler(event, context)

