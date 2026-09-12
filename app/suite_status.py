# suite_status.py
# A small shared feed of status messages from the cn4m suite.
#
# The other tools (inbound, smartsync, symmetry, cascade) POST short lines here
# and they appear in the status rail at the top of the cn4m UI, alongside cn4m's
# own activity. See "Suite status feed" in the README for the wire format.
#
# Backed by Redis, which is already running as the Celery broker: it means the
# feed survives a page reload and a Flask restart, and every open browser sees
# the same entries. A module-level list would do neither.

import json
import os
import time
from datetime import datetime

import redis

# Two lists, one counter. The feed is what the rail polls: newest first, capped
# short, because it is an activity glance. The log is the full record behind
# the "full log" link in the rail's tray — everything that goes into the feed
# goes into the log too, and cn4m's own outcomes go into the log only (they
# are painted on the rail locally by the browser that caused them). Ids come
# from one counter so a "since" cursor means the same thing against either.
FEED_KEY = "cn4m:suite:status"
LOG_KEY = "cn4m:suite:log"
COUNTER_KEY = "cn4m:suite:status:id"
FEED_LIMIT = 20
LOG_LIMIT = 2000

# A status line has to fit a narrow rail; anything longer is truncated rather
# than rejected, so a chatty caller still gets seen instead of silently failing.
MESSAGE_LIMIT = 160
APP_LIMIT = 32

# ── Levels ───────────────────────────────────────────────────────────────────
# The level colours the dot in cn4m's status rail. cn4m owns this list: LEVELS
# below is the definition, the colours are in app/static/cn4m.css and the class
# map (STATUS_LEVEL_CLASS) is in app/static/cn4m.js. The other suite tools
# document the vocabulary on their own side, but nothing there validates it —
# this file is the authority if the two ever disagree.
#
#   idle      grey     Nothing happening. The resting state.
#   working   orange   In progress right now.
#   ok        green    Finished, nothing to do.
#   warning   yellow   Finished, but not cleanly. Nothing is broken and nobody
#                      must act now, but it should not read as green — a run
#                      that completed partially, say one destination skipped
#                      because a NAS was off.
#   blocked   purple   Not finished: waiting on a person, with a timeout
#                      running. Actionable now, unlike warning — a destination
#                      is unreachable and the run is awaiting a decision.
#   error     red      Finished badly, or could not run at all.
#
# warning and blocked are the pair worth getting right, and they split on two
# questions: is the run over, and does someone have to do something?
#
# A warning is historical. The run has ended and this is the record of how it
# went; it will never change on its own. A blocked is live — it is still on the
# clock, it wants a person, and it resolves into something else by itself when
# they act or when the timeout expires. Reaching for warning when you mean
# blocked is how something waiting on a human quietly turns into something
# nobody is waiting on.
#
# An unrecognised level is not an error. clean_entry() strips and lowercases it,
# then falls back to idle if it still doesn't match: a typo costs a colour,
# never a message. Nothing is reported back to the caller, so a line turning up
# grey is the only symptom.
LEVELS = ("idle", "working", "ok", "warning", "blocked", "error")

_client = None


def _redis():
    """Lazily connect, so importing this module never needs Redis to be up."""
    global _client
    if _client is None:
        url = os.getenv("CELERY_BROKER_URL") or "redis://redis:6379/0"
        _client = redis.Redis.from_url(url, decode_responses=True)
    return _client


def clean_entry(app_name, message, level):
    """
    Normalise a pushed status into what the feed stores, or raise ValueError
    with a message meant for the caller.

    Lenient where being strict would only lose information (an over-long message
    is trimmed, an unknown level falls back to "idle") and strict about the two
    things that can't be guessed: which app it came from, and what it says.
    """
    app_name = (app_name or "").strip()
    message = " ".join((message or "").split())   # collapse newlines/runs of space

    if not app_name:
        raise ValueError("'app' is required — name the tool the update came from")
    if not message:
        raise ValueError("'message' is required")

    if len(app_name) > APP_LIMIT:
        raise ValueError("'app' is too long (%d characters maximum)" % APP_LIMIT)
    if len(message) > MESSAGE_LIMIT:
        message = message[:MESSAGE_LIMIT - 1].rstrip() + "…"

    level = (level or "idle").strip().lower()
    if level not in LEVELS:
        level = "idle"

    return app_name, message, level


def push_status(app_name, message, level="idle", feed=True):
    """
    Add one entry to the log — and, unless feed=False, to the feed — and
    return it. Ids come from a Redis counter so the UI can ask for "everything
    after the last one I saw" and never show a message twice, which a
    timestamp alone can't promise.

    feed=False is for cn4m's own outcomes, which the browser has already put on
    its rail: they are worth keeping in the log, but re-broadcasting them
    through the feed would paint them twice.
    """
    app_name, message, level = clean_entry(app_name, message, level)
    client = _redis()
    now = datetime.now()

    entry = {
        "id": client.incr(COUNTER_KEY),
        "app": app_name,
        "message": message,
        "level": level,
        # ts orders the merge against cn4m's own browser-side events; time is
        # what the rail shows, datetime what the log page shows — a log that
        # outlives the session needs the date to be honest about "when".
        "ts": time.time(),
        "time": now.strftime("%H:%M"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    raw = json.dumps(entry)
    pipe = client.pipeline()
    pipe.lpush(LOG_KEY, raw)
    pipe.ltrim(LOG_KEY, 0, LOG_LIMIT - 1)
    if feed:
        pipe.lpush(FEED_KEY, raw)
        pipe.ltrim(FEED_KEY, 0, FEED_LIMIT - 1)
    pipe.execute()
    return entry


def _read_list(key, limit, since):
    entries = []
    for raw in _redis().lrange(key, 0, limit - 1):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue                       # skip anything that isn't ours
        if entry.get("id", 0) > since:
            entries.append(entry)
    return entries


def read_status(since=0):
    """
    Feed entries newer than `since`, newest first. since=0 returns the whole
    feed, which is what a freshly loaded page wants.
    """
    return _read_list(FEED_KEY, FEED_LIMIT, since)


def read_log(since=0):
    """The log, newest first — same shape and same `since` cursor as the feed."""
    return _read_list(LOG_KEY, LOG_LIMIT, since)
