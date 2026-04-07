# discord_bot.py
# Discord notification helper for cn4m.
# Sends messages to a configured channel via the Discord REST API.
# No persistent bot connection needed — each call is a simple HTTP POST.

import os
import requests
import logging

logger = logging.getLogger(__name__)

# Read credentials once at import time
_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")


def _send(message: str) -> bool:
    """
    POST a single message to the configured Discord channel.
    Returns True on success, False on any error (never raises).
    """
    if not _BOT_TOKEN or not _CHANNEL_ID:
        logger.warning("Discord credentials not set — skipping notification")
        return False

    url = f"https://discord.com/api/v10/channels/{_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, json={"content": message}, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Discord notification failed: {e}")
        return False


def _send_chunked(lines: list) -> bool:
    """
    Send a list of text lines as one or more Discord messages,
    respecting Discord's 2000 character limit per message.
    Splits at line boundaries so no single line is ever cut in half.
    """
    chunks = []
    current = []
    current_len = 0

    for line in lines:
        # +1 for the newline that joins lines, except before the first line
        addition = len(line) + (1 if current else 0)
        if current and current_len + addition > 2000:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += addition

    if current:
        chunks.append("\n".join(current))

    return all(_send(chunk) for chunk in chunks)


# ── Public notification functions ─────────────────────────────────────────────

def notify_approved(assets: dict) -> bool:
    """
    Send a Discord message listing newly approved assets.
    assets: dict of {fileid: asset_data} — only parent and name are included.
    """
    if not assets:
        return True
    lines = ["## new files approved"]
    for asset in assets.values():
        lines.append(f"- **{asset['parent']}** / {asset['name']}")
    return _send_chunked(lines)


def notify_quarantined(assets: dict) -> bool:
    """
    Send a Discord message listing newly quarantined assets.
    assets: dict of {fileid: asset_data} — only parent and name are included.
    """
    if not assets:
        return True
    lines = ["## new files quarantined"]
    for asset in assets.values():
        lines.append(f"- **{asset['parent']}** / {asset['name']}")
    return _send_chunked(lines)


def notify_tracked() -> bool:
    """Send a Discord message confirming assets were pushed to Google Sheets."""
    return _send("## assets updated on google sheet")
