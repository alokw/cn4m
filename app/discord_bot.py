# discord_bot.py
# Discord notification helper for cn4m.
# Sends messages to a configured channel via a Discord webhook URL.
# No persistent bot connection needed — each call is a simple HTTP POST.

import os
import requests
import logging

from app.helpers import _file_type_emoji

logger = logging.getLogger(__name__)

# Read webhook URL once at import time
_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


def _send(message: str) -> bool:
    """
    POST a single message to the configured Discord webhook.
    Returns True on success, False on any error (never raises).
    """
    if not _WEBHOOK_URL:
        logger.warning("Discord webhook URL not set — skipping notification")
        return False

    try:
        response = requests.post(_WEBHOOK_URL, json={"content": message}, timeout=10)
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

def _asset_line_prefix(asset: dict) -> str:
    """
    Build the two-emoji prefix used in approved/quarantined notifications:
      first emoji  — ☝️ if this is a version-up of an existing asset, otherwise 🆕
      second emoji — 🎵 audio, 🖼️ image, 🎬 video (or empty if extension unrecognized)
    """
    version_emoji = "☝️" if asset.get("is_version_up") else "🆕"
    type_emoji = _file_type_emoji(asset.get("extension", "")).strip()
    # Trailing space if a type emoji was returned, otherwise just the version emoji + space
    return f"{version_emoji} {type_emoji} ".replace("  ", " ")


def notify_approved(assets: dict) -> bool:
    """
    Send a Discord message listing newly approved assets.
    Each item is prefixed with a version-status emoji and a file-type emoji.
    """
    if not assets:
        return True
    count = len(assets)
    label = "asset" if count == 1 else "assets"
    lines = [f"✅ **{count} {label} approved:**"]
    for asset in assets.values():
        lines.append(f"• {_asset_line_prefix(asset)}`{asset['parent']}/{asset['name']}`")
    return _send_chunked(lines)


def notify_quarantined(assets: dict) -> bool:
    """
    Send a Discord message listing newly quarantined assets.
    Each item is prefixed with a version-status emoji and a file-type emoji.
    """
    if not assets:
        return True
    count = len(assets)
    label = "asset" if count == 1 else "assets"
    lines = [f"🗑️ **{count} {label} quarantined:**"]
    for asset in assets.values():
        lines.append(f"• {_asset_line_prefix(asset)}`{asset['parent']}/{asset['name']}`")
    return _send_chunked(lines)


def notify_tracked() -> bool:
    """Send a Discord message confirming assets were pushed to Google Sheets."""
    return _send("📊 **Assets pushed to Google Sheet**")
