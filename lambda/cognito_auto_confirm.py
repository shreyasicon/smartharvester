import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    try:
        response = event.setdefault("response", {})
        response["autoConfirmUser"] = True

        if "request" in event and "userAttributes" in event["request"]:
            attrs = event["request"]["userAttributes"]
            if attrs.get("email"):
                response["autoVerifyEmail"] = True
            if attrs.get("phone_number"):
                response["autoVerifyPhone"] = True

        return event
    except Exception as e:
        logger.exception("Error in Pre Sign-up Lambda")
        response = event.setdefault("response", {})
        response["autoConfirmUser"] = True
        return event

