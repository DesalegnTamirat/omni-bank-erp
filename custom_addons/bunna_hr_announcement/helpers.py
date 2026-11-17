# -*- coding: utf-8 -*-
"""Small helpers with no Odoo imports, so they can be tested on their own."""
import hashlib
import hmac
import random
import re
import time

LINK_PATTERN = re.compile(
    r'(https?://|ftp://|www\.|\b[a-z0-9-]+\.(?:com|net|org|info|biz|et|gov|edu|io|co|me|ly|xyz)\b)',
    re.IGNORECASE)
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

MIN_FORM_AGE = 3        # seconds: a real person needs a moment to write
MAX_FORM_AGE = 3600     # seconds: an old form is refused


def clean_comment(text):
    """Plain text only: control characters removed, spaces tidied, at most one blank line in a row."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = CONTROL_CHARS.sub('', text)
    lines = [' '.join(line.split()) for line in text.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def has_link(text):
    return bool(LINK_PATTERN.search(text or ''))


def shorten(text, limit=300):
    text = text or ''
    if len(text) <= limit:
        return text
    return '%s... (+%d more characters)' % (text[:limit], len(text) - limit)


def sign(secret, message):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def fingerprint(secret, utc_date, ip, user_agent):
    """One-way code that changes every day. Used only to count requests; never stored with a comment."""
    return sign(secret, 'fp|%s|%s|%s' % (utc_date, ip or '', user_agent or ''))[:32]


def new_challenge(secret, now=None):
    """A small sum the visitor must answer. Stateless: the answer is hidden inside a signed token."""
    chooser = random.SystemRandom()
    first, second = chooser.randint(2, 9), chooser.randint(2, 9)
    stamp = int(now if now is not None else time.time())
    return {
        'question': '%d + %d' % (first, second),
        'ts': stamp,
        'token': sign(secret, 'c|%d|%d' % (first + second, stamp)),
    }


def verify_challenge(secret, answer, ts, token, now=None):
    """'ok', 'expired' (form too new or too old) or 'challenge' (wrong answer)."""
    try:
        stamp = int(ts)
    except (TypeError, ValueError):
        return 'expired'
    age = (now if now is not None else time.time()) - stamp
    if age < MIN_FORM_AGE or age > MAX_FORM_AGE:
        return 'expired'
    try:
        value = int(str(answer).strip())
    except (TypeError, ValueError):
        return 'challenge'
    expected = sign(secret, 'c|%d|%d' % (value, stamp))
    return 'ok' if hmac.compare_digest(expected, str(token or '')) else 'challenge'
