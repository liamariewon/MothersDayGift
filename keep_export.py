import json
from pathlib import Path
from typing import Iterable

import requests


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

