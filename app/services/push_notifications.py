import json
import os
from pywebpush import WebPushException, webpush


def send_push_notification(subscription_info, title, body):
    try:
        VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(
                {
                    "title": title,
                    "body": body,
                    "url": "https://jntuhresults.vercel.app/academicresult",
                }
            ),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": "mailto:admin@dhethi.com"},
        )
    except WebPushException as ex:
        print("Push failed:", ex)
