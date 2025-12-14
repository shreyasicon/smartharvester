"""
Django signals for Tracker app.

- On User post_save, persist a corresponding item in the DynamoDB users table (best-effort).
- On User post_delete, delete user item (best-effort).

Signals use lazy imports to avoid circular imports during app startup.
"""
import logging
import os
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

User = get_user_model()


@receiver(post_save, sender=User)
def sync_user_to_dynamo(sender, instance, created, **kwargs):
    """
    On user create/update, write to DynamoDB users table.
    Uses lazy import to avoid import-time cycles.
    """
    try:
        from .dynamodb_helper import save_user_to_dynamodb

        # choose a stable id for Django-created users
        user_id_value = f"django_{instance.pk}"
        payload = {
            "username": instance.username,
            "email": instance.email,
            "name": f"{instance.get_full_name() or instance.username}",
            "country": getattr(instance, "userprofile", None) and getattr(instance.userprofile, "country", None)
        }

        ok = save_user_to_dynamodb(user_id_value, payload)
        if ok:
            logger.info("Synced Django user %s -> Dynamo (id=%s)", instance.username, user_id_value)
        else:
            logger.warning("Failed to sync Django user %s to Dynamo", instance.username)
    except Exception as e:
        logger.exception("Exception in sync_user_to_dynamo for user %s: %s", getattr(instance, "username", None), e)


@receiver(post_delete, sender=User)
def delete_user_from_dynamo(sender, instance, **kwargs):
    try:
        # best-effort removal by user_id value
        from .dynamodb_helper import dynamo_resource, DYNAMO_USERS_TABLE, DYNAMO_USERS_PK  # type: ignore
        table = dynamo_resource().Table(os.getenv("DYNAMO_USERS_TABLE", "users"))
        pk_attr = os.getenv("DYNAMO_USERS_PK", "username")
        key = {pk_attr: str(instance.username if pk_attr == "username" else f"django_{instance.pk}")}
        table.delete_item(Key=key)
        logger.info("Deleted user %s from Dynamo (key=%s)", instance.username, key)
    except Exception:
        logger.exception("Failed to delete user %s from Dynamo", getattr(instance, "username", None))