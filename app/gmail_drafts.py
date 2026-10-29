
import base64
import os
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

PROJECT_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = PROJECT_DIR / "credentials.json"
TOKEN_FILE = PROJECT_DIR / "token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def get_gmail_service():
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE), SCOPES
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES
        )
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)

    return build("gmail", "v1", credentials=creds)


def create_draft(recipient, subject, body):
    """Create a Gmail draft without sending it."""
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    encoded_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("utf-8")

    service = get_gmail_service()

    result = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": encoded_message}},
    ).execute()

    return result["id"]
def send_email(recipient, subject, body):
    """Send one email through Gmail when explicitly called."""
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    encoded_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("utf-8")

    service = get_gmail_service()

    result = service.users().messages().send(
        userId="me",
        body={"raw": encoded_message},
    ).execute()

    return result["id"]

def main():
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found: {CREDENTIALS_FILE}"
        )

    recipient = input("Enter your own Gmail address: ").strip()

    if not recipient or "@" not in recipient:
        print("Please enter a valid email address.")
        return

    print("\nThis creates a draft only. It will not send anything.")
    confirmation = input("Type CREATE DRAFT to continue: ").strip()

    if confirmation != "CREATE DRAFT":
        print("Cancelled. No draft was created.")
        return

    draft_id = create_draft(
        recipient=recipient,
        subject="EGAST AI Sales Agent - Draft Test",
        body=(
            "Hello,\n\n"
            "This is a test draft from the EGAST AI Sales Agent.\n"
            "The Gmail draft integration is being tested locally.\n\n"
            "EGAST works with fresh produce, including oranges, "
            "grapes, and pomegranates.\n\n"
            "This message was saved as a draft for review and "
            "was not sent.\n"
        ),
    )

    print("\nDraft created successfully!")
    print(f"Draft ID: {draft_id}")
    print("Open Gmail and check your Drafts folder.")


if __name__ == "__main__":
    main()

