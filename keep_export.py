import json
from pathlib import Path
from typing import Iterable

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/keep"]
TOKEN_FILE = Path("token_keep.json")
CREDENTIALS_FILE = Path("credentials.json")


def get_google_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                "credentials.json not found. Download your OAuth client file from Google Cloud."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            SCOPES,
        )
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return creds


def create_keep_list_note(title: str, items: Iterable[str]) -> dict:
    creds = get_google_credentials()

    payload = {
        "title": title,
        "body": {
            "list": {
                "listItems": [
                    {
                        "text": {"text": item},
                        "checked": False,
                    }
                    for item in items
                ]
            }
        },
    }

    response = requests.post(
        "https://keep.googleapis.com/v1/notes",
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )

    response.raise_for_status()
    return response.json()