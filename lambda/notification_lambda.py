import os
import json
import logging
import time
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMO_TABLE = os.environ.get("DYNAMO_USERS_TABLE", "")
PK_NAME = os.environ.get("DYNAMO_USERS_PK", "username")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "25"))
BATCH_PAUSE_SECONDS = float(os.environ.get("BATCH_PAUSE_SECONDS", "0.5"))

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMO_TABLE)
sns = boto3.client("sns", region_name=REGION)


def build_message(user_item):
    name = user_item.get("name") or user_item.get("preferred_username") or user_item.get(PK_NAME)
    subject = f"SmartHarvester daily update — {datetime.utcnow().strftime('%Y-%m-%d')}"
    body = (
        f"Hello {name},\n\n"
        "Here is your SmartHarvester daily update about your plantings:\n"
        "- Active plantings: X (replace with your logic)\n"
        "- Next watering: tomorrow (replace with your logic)\n\n"
        "Thanks,\nSmartHarvester"
    )
    return subject, body


def scan_all_users():
    if not DYNAMO_TABLE:
        raise RuntimeError("DYNAMO_USERS_TABLE not configured")
    users = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items = resp.get("Items", [])
        users.extend(items)
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            break
    return users


def publish_to_sns(subject, message):
    if not SNS_TOPIC_ARN:
        raise RuntimeError("SNS_TOPIC_ARN not configured")
    try:
        resp = sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=message)
        return True, resp.get("MessageId")
    except ClientError:
        logger.exception("SNS publish failed")
        return False, None


def lambda_handler(event, context):
    logger.info("Notification run started")
    try:
        users = scan_all_users()
    except Exception:
        logger.exception("Failed scanning DynamoDB")
        return {"status": "error", "reason": "scan_failed"}

    total = len(users)
    sent = 0
    skipped = 0
    failed = 0

    for i, u in enumerate(users, start=1):
        # skip users without email
        email = u.get("email")
        if not email:
            logger.debug("Skipping user without email: %s", u.get(PK_NAME))
            skipped += 1
            continue

        # Optional: check opt-in flag, e.g., u.get("notify", True)

        subject, message = build_message(u)
        # You can include email in message body if needed; SNS will send to subscribed email addresses
        ok, mid = publish_to_sns(subject, message)
        if ok:
            sent += 1
            logger.info("Published for user=%s MessageId=%s", u.get(PK_NAME), mid)
        else:
            failed += 1

        # pacing to avoid throttles (simple)
        if i % BATCH_SIZE == 0:
            logger.info("Processed %d users so far (sent=%d failed=%d skipped=%d)", i, sent, failed, skipped)
            time.sleep(BATCH_PAUSE_SECONDS)

    logger.info("Done: total=%d sent=%d failed=%d skipped=%d", total, sent, failed, skipped)
    return {"status": "ok", "total": total, "sent": sent, "failed": failed, "skipped": skipped}