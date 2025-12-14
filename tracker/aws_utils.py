"""
Helper utilities for publishing harvest reminders to AWS SNS.

Usage:
- Set environment variables:
    AWS_REGION (e.g. us-east-1)
    SNS_TOPIC_ARN (the topic you created)

This module provides:
- ensure_email_subscribed(topic_arn, email): ensures the given email is subscribed (may be "PendingConfirmation")
- publish_to_topic(topic_arn, subject, message): publishes a message to topic

Notes:
- For email delivery each recipient must confirm the SNS subscription emailed to them.
- If you prefer direct user-specific emails without subscriptions, use SES or Django's email backend instead.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")  # e.g. arn:aws:sns:us-east-1:123456789012:harvest-notifications


def sns_client():
    return boto3.client("sns", region_name=AWS_REGION)


def ensure_email_subscribed(topic_arn: str, email: str) -> Optional[str]:
    """
    Ensure the given email address is subscribed to the SNS topic.
    If already subscribed, returns the SubscriptionArn (may be 'PendingConfirmation' until user confirms).
    If newly created, returns the subscription response ARN or None on error.
    """
    client = sns_client()
    try:
        # List subscriptions and check if the email is already subscribed to avoid duplicate subscribes.
        paginator = client.get_paginator("list_subscriptions_by_topic")
        for page in paginator.paginate(TopicArn=topic_arn):
            for sub in page.get("Subscriptions", []):
                endpoint = sub.get("Endpoint")
                protocol = sub.get("Protocol")
                sub_arn = sub.get("SubscriptionArn")
                if protocol == "email" and (endpoint or "").lower() == email.lower():
                    logger.debug("Found existing subscription for %s: %s", email, sub_arn)
                    return sub_arn  # may be 'PendingConfirmation'

        # Not found: subscribe
        resp = client.subscribe(
            TopicArn=topic_arn,
            Protocol="email",
            Endpoint=email,
            ReturnSubscriptionArn=True,
        )
        sub_arn = resp.get("SubscriptionArn")
        logger.info("Created SNS email subscription for %s (SubscriptionArn=%s). User must confirm via email.", email, sub_arn)
        return sub_arn
    except ClientError as e:
        logger.exception("Failed to ensure subscription for %s: %s", email, e)
        return None


def publish_to_topic(topic_arn: str, subject: str, message: str) -> bool:
    """
    Publish a message to the SNS topic.
    Returns True on success, False otherwise.
    """
    client = sns_client()
    try:
        client.publish(TopicArn=topic_arn, Subject=subject, Message=message)
        logger.debug("Published message to %s subject=%s", topic_arn, subject)
        return True
    except ClientError as e:
        logger.exception("Failed to publish SNS message: %s", e)
        return False