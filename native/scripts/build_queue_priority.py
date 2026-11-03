"""Read-only queue admission shared by the Mac guard and durable uploader."""
import json
import os
from pathlib import Path
import time

STORE = Path(os.environ.get('IOS_PUSH_MAC_STORE', Path.home() / 'Library/Application Support/ios-tools/push'))
TERMINAL = {'installed', 'validated', 'failed', 'cancelled', 'superseded'}


def queued_delivery(now=None):
    now = time.time() if now is None else now
    for job in sorted((STORE / 'jobs').glob('*')):
        try:
            state = json.loads((job / 'state.json').read_text()) if (job / 'state.json').exists() else {}
            if state.get('phase') in TERMINAL or (job / 'cancelled.json').exists(): continue
            if (job / 'ready.json').exists():
                if state.get('nextAttempt', 0) <= now: return job.name
            elif (job / 'incoming.json').exists():
                incoming = json.loads((job / 'incoming.json').read_text())
                if 0 <= now - incoming['at'] < 600: return job.name
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None
