"""Pluggable ticket summaries.

``aixo_desk.ai_provider`` selects the provider: ``local`` (default, offline and
deterministic) or ``openai`` (any OpenAI compatible chat completions API; the
key lives in ``aixo_desk.ai_api_key``, never in code). A remote failure always
falls back to the local summary so the ticket page keeps working.
"""
import logging
import re

import requests

from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

DEADLINE_RE = re.compile(
    r"\b(?:by|before|until|due(?: on)?)\s+((?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|tomorrow|today|tonight|eod|end of (?:the )?(?:day|week|month)|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9}))",
    re.I)
URGENT_WORDS = ('urgent', 'asap', 'immediately', 'critical', 'blocked', 'down', 'angry', 'unacceptable')
DEFAULT_URL = 'https://api.openai.com/v1/chat/completions'
DEFAULT_MODEL = 'gpt-4o-mini'
MAX_CHARS = 6000


def _text(html):
    return re.sub(r'\s+', ' ', html2plaintext(html or '')).strip()


def local_summary(subject, texts):
    """First sentences of the conversation, a detected deadline and a tone flag."""
    body = ' '.join(t for t in texts if t)
    sentences = re.split(r'(?<=[.!?])\s+', body)
    summary = ' '.join(sentences[:2]).strip()
    if len(summary) > 240:
        summary = summary[:237].rstrip() + '...'
    deadline = DEADLINE_RE.search(body)
    lowered = f"{subject} {body}".lower()
    return {
        'summary': summary or subject,
        'deadline': deadline.group(1) if deadline else None,
        'tone': 'urgent' if any(w in lowered for w in URGENT_WORDS) else 'neutral',
        'provider': 'local',
    }


def summarize(env, ticket, message_bodies):
    """Summary dict for ``ticket``. ``message_bodies`` are the public message HTML bodies."""
    texts = [_text(ticket.description)] + [_text(b) for b in message_bodies]
    result = local_summary(ticket.name, texts)
    icp = env['ir.config_parameter'].sudo()
    if icp.get_param('aixo_desk.ai_provider') != 'openai':
        return result
    key = icp.get_param('aixo_desk.ai_api_key')
    if not key:
        return result
    try:
        response = requests.post(
            icp.get_param('aixo_desk.ai_base_url') or DEFAULT_URL,
            headers={'Authorization': f'Bearer {key}'},
            json={
                'model': icp.get_param('aixo_desk.ai_model') or DEFAULT_MODEL,
                'messages': [
                    {'role': 'system', 'content': 'Summarise this support ticket in two sentences.'},
                    {'role': 'user', 'content': f"{ticket.name}\n\n" + '\n'.join(texts)[:MAX_CHARS]},
                ],
            },
            timeout=10,
        )
        response.raise_for_status()
        result['summary'] = response.json()['choices'][0]['message']['content'].strip()
        result['provider'] = 'openai'
    except (requests.RequestException, KeyError, IndexError, ValueError):
        _logger.warning("AI provider failed, using the local summary", exc_info=True)
    return result
