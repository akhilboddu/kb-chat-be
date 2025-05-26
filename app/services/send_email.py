import os
from pathlib import Path
import boto3
from typing import List
import json
from pydantic import BaseModel

SES_ACCESS_KEY = os.getenv("SES_ACCESS_KEY")
SES_SECRET_ACCESS_KEY = os.getenv("SES_SECRET_ACCESS_KEY")
SES_REGION = os.getenv("SES_REGION")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_EMAIL = "tilakreddy19102000@gmail.com"


class EmailContent(BaseModel):
    emailAddress: List[str]
    subject: str
    message: str


ses_client = boto3.client(
    "ses",
    region_name=SES_REGION,
    aws_access_key_id=SES_ACCESS_KEY,
    aws_secret_access_key=SES_SECRET_ACCESS_KEY,  # ✅ fixed key name
)


def notify_client_message(
    user_name: str, message: str, user_email: str, conversation_id: str
):
    ses_client = boto3.client(
        "ses",
        region_name=SES_REGION,
        aws_access_key_id=SES_ACCESS_KEY,
        aws_secret_access_key=SES_SECRET_ACCESS_KEY,
    )
    url = os.getenv("FRONTEND_LINK")
    converssationLink = f"{url}/chat-convo/{conversation_id}"
    user_email = (
        SENDER_EMAIL or ""
    )  # to be removed in production after we get ses access

    try:
        TEMPLATE_PATH = (
            Path(__file__).resolve().parent.parent
            / "html_templates"
            / "client_message_template.html"
        )
        print(TEMPLATE_PATH)
        with open(TEMPLATE_PATH, "r") as f:
            html_template = f.read()

        html_body = (
            html_template.replace("{{name}}", user_name)
            .replace("{{conversation_reply}}", message)
            .replace("{{conversation_link}}", converssationLink)
        )

        response = ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [user_email]},
            Message={
                "Subject": {
                    "Charset": "UTF-8",
                    "Data": " New Reply to Your Conversation in Deskforce!",
                },
                "Body": {
                    "Html": {"Charset": "UTF-8", "Data": html_body},
                    "Text": {
                        "Charset": "UTF-8",
                        "Data": f"Link to your conversation {converssationLink}",
                    },
                },
            },
        )
        print("User notified with link:", response)
    except Exception as e:
        print("Error sending linked email to admin:", e)


def notify_admin_on_user_message(
    user_name: str, user_email: str, message: str, conversation_id: str
):
    conversation_link = f"http://localhost:8080/conversations/{conversation_id}"

    ses_client = boto3.client(
        "ses",
        region_name=SES_REGION,
        aws_access_key_id=SES_ACCESS_KEY,
        aws_secret_access_key=SES_SECRET_ACCESS_KEY,
    )

    try:
        response = ses_client.send_templated_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [SENDER_EMAIL]},
            Template="DeskforceUserMessageWithLink",
            TemplateData=json.dumps(
                {
                    "user_name": user_name,
                    "user_email": user_email,
                    "message": message,
                    "conversation_link": conversation_link,
                }
            ),
        )
        print("Admin notified with link:", response)
    except Exception as e:
        print("Error sending linked email to admin:", e)


def create_ses_template():
    ses_client.create_template(
        Template={
            "TemplateName": "DeskforceUserMessageWithLink",
            "SubjectPart": "💬 New message from {{user_name}} via Deskforce",
            "TextPart": (
                "User {{user_name}} ({{user_email}}) sent a message:\n\n"
                "{{message}}\n\n"
                "View the full conversation: {{conversation_link}}\n\n"
                "— Deskforce Notification System"
            ),
            "HtmlPart": """
        <html>
            <body>
                <h2>New message received from {{user_name}}</h2>
                <p><strong>Email:</strong> {{user_email}}</p>
                <p><strong>Message:</strong></p>
                <blockquote style="border-left: 4px solid #ccc; padding-left: 12px; font-style: italic;">
                    {{message}}
                </blockquote>
                <p>
                    🔗 <a href="{{conversation_link}}" style="color: #007bff; text-decoration: none;">
                        View Conversation in Deskforce
                    </a>
                </p>
                <p>— Deskforce Notification System</p>
            </body>
        </html>
        """,
        }
    )
    print(SES_REGION)
