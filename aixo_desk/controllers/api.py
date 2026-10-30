"""Shared plumbing for the website JSON API: role guard, error mapping, serializers."""
import functools
import logging

import pytz

from odoo import _, fields
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from .base import PASSWORD_CHANGE_PATH

_logger = logging.getLogger(__name__)

AVATAR_PALETTE = [('#FFE3CC', '#8A3B00'), ('#D7F2E3', '#0F5F34'), ('#E1F2CF', '#2F6B0E'),
                  ('#F1E4FF', '#5B1E99'), ('#FDE7E7', '#A11A1A')]
STATE_LABELS = {'open': 'Open', 'on_hold': 'On Hold', 'escalated': 'Escalated', 'closed': 'Closed'}
PRIORITY_RANK = {'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}


def ok(data=None):
    return {'ok': True, 'data': data if data is not None else {}}


def err(message, code=None):
    return {'ok': False, 'error': message, 'code': code}


def desk_api(roles=('agent',)):
    """Guard + error mapping for ``type='jsonrpc'`` routes.

    The wrapped function returns plain data; this wraps it in ``{ok, data}``.
    Business errors become ``{ok: False, error}``. The call runs in a savepoint
    so a failed request never leaves half-applied changes behind.
    """
    allowed = set(roles)
    if 'agent' in allowed:
        allowed.add('admin')

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            user = request.env.user
            if user._is_public():
                return err(_("Your session has expired. Please log in again."), 'auth')
            if user.desk_force_password_change:
                return err(_("Change your password to continue."), 'password')
            if user.desk_role not in allowed:
                return err(_("You don't have access to this."), 'forbidden')
            try:
                with request.env.cr.savepoint():
                    return ok(func(self, *args, **kwargs))
            except (AccessError, AccessDenied) as exc:
                _logger.info("Desk API access denied for %s on %s: %s", user.login, func.__name__, exc)
                return err(_("You don't have access to this."), 'forbidden')
            except MissingError:
                return err(_("This record no longer exists."), 'missing')
            except (UserError, ValidationError) as exc:
                return err(str(exc.args[0] if exc.args else exc))
        return wrapper
    return decorator


# ----------------------------------------------------------------- serializers

def initials(name):
    return ''.join(w[0] for w in (name or '').split()[:2]).upper() or '?'


def avatar(user_or_partner):
    name = user_or_partner.name or ''
    bg, fg = AVATAR_PALETTE[(user_or_partner.id or 0) % len(AVATAR_PALETTE)]
    return {'id': user_or_partner.id, 'name': name, 'initials': initials(name), 'bg': bg, 'fg': fg}


def user_tz():
    return pytz.timezone(request.env.user.tz or request.env['ir.config_parameter'].sudo().get_param(
        'aixo_desk.timezone') or 'UTC')


def local(dt):
    if not dt:
        return None
    return pytz.utc.localize(dt).astimezone(user_tz())


def fmt_dt(dt, with_time=True):
    """'17 Oct 10:15 PM' in the user's time zone (the design's date style)."""
    value = local(dt)
    if not value:
        return ''
    text = value.strftime('%d %b')
    if with_time:
        text += value.strftime(' %I:%M %p').replace(' 0', ' ')
    return text


def iso(dt):
    return fields.Datetime.to_string(dt).replace(' ', 'T') + 'Z' if dt else None


def ticket_row(ticket):
    return {
        'id': ticket.id,
        'number': ticket.number,
        'subject': ticket.name,
        'channel': ticket.channel,
        'contact': ticket.partner_id.name,
        'account': ticket.account_id.name if ticket.account_id != ticket.partner_id else '',
        'created': fmt_dt(ticket.create_date, with_time=False),
        'due': fmt_dt(ticket.due_date),
        'overdue': ticket.is_overdue,
        'state': ticket.state,
        'state_label': STATE_LABELS[ticket.state],
        'priority': ticket.priority,
        'replies': ticket.reply_count,
        'owner': avatar(ticket.owner_id) if ticket.owner_id else None,
    }


def check_attachment_policy(filename, size):
    """Raise UserError when an upload breaks the size/type limits from settings."""
    icp = request.env['ir.config_parameter'].sudo()
    max_mb = int(icp.get_param('aixo_desk.attachment_max_mb') or 40)
    blocked = {e.strip().lower().lstrip('.') for e in (icp.get_param('aixo_desk.attachment_blocked') or '').split(',') if e.strip()}
    extension = (filename.rsplit('.', 1)[-1] if '.' in filename else '').lower()
    if size > max_mb * 1024 * 1024:
        raise UserError(_("%(name)s is larger than %(mb)s MB.", name=filename, mb=max_mb))
    if extension in blocked:
        raise UserError(_("Files of type .%s are not allowed.", extension))


def human_ago(dt):
    """'Today', 'Yesterday', '3 days ago', 'Last week'... as the design's customer list shows."""
    if not dt:
        return 'Never'
    days = (fields.Datetime.now() - dt).days
    if days <= 0:
        return 'Today'
    if days == 1:
        return 'Yesterday'
    if days < 7:
        return f'{days} days ago'
    if days < 14:
        return 'Last week'
    if days < 31:
        return f'{days // 7} weeks ago'
    return 'Last month' if days < 60 else f'{days // 30} months ago'
