import os
import boto3
from typing import List
import json
from pydantic import BaseModel

SES_ACCESS_KEY = os.getenv("SES_ACCESS_KEY")
SES_SECRET_ACCESS_KEY = os.getenv("SES_SECRET_ACCESS_KEY")
SES_REGION = os.getenv("SES_REGION")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
VITE_BASE_URL = os.getenv("VITE_BASE_URL")
SENDER_EMAIL = "asif@liorra.io"


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
     company_name: str, company_email: str, message: str, conversation_id: str
):
    ses_client = boto3.client(
        "ses",
        region_name=SES_REGION,
        aws_access_key_id=SES_ACCESS_KEY,
        aws_secret_access_key=SES_SECRET_ACCESS_KEY,
    )
    converssationLink = f"{VITE_BASE_URL}/chat-convo/{conversation_id}"
    try:
        response = ses_client.send_templated_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [SENDER_EMAIL]},
            Template="DeskforceClientMessageWithLink",
            TemplateData=json.dumps(
                {
                    "company_name": company_name,
                    "company_email": company_email,
                    "message": message,
                    "conversation_link": converssationLink,
                }
            ),
        )
        print("User notified with link:", response)
    except Exception as e:
        print("Error sending linked email to admin:", e)

    pass


def notify_admin_on_user_message(
    user_name: str, user_email: str, message: str, bot_id: str
):
    conversation_link = f"{VITE_BASE_URL}/conversations/{bot_id}"
   

    ses_client = boto3.client(
        "ses",
        region_name=SES_REGION,
        aws_access_key_id=SES_ACCESS_KEY,
        aws_secret_access_key=SES_SECRET_ACCESS_KEY,
    )

    print("Sending email to admin...........")

    try:
        response = ses_client.send_templated_email(
            Source="asif@liorra.io",
            Destination={"ToAddresses": ["asif@liorra.io"]},
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

def create_ses_template_client():
    ses_client.create_template(
        Template={
            "TemplateName": "DeskforceClientMessageWithLink",
            "SubjectPart": "💬 New message from {{company_name}} via Deskforce",
            "TextPart": (
                "Company {{company_name}} ({{company_email}}) sent a message:\n\n"
                "{{message}}\n\n"
                "View the full conversation: {{conversation_link}}\n\n"
                "— Deskforce Notification System"
            ),
            "HtmlPart": """
        <html>
            <body>
                <h2>New message received from {{company_name}}</h2>
                <p><strong>Email:</strong> {{company_email}}</p>
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


# notify_admin_on_user_message(
#     user_name="Asif",
#     user_email="asif@liorra.io",
#     message="Hello, this is a test message",
#     conversation_id="123",
# )

