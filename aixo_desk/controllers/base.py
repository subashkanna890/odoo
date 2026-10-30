import functools
import re
from urllib.parse import urlparse

from odoo import _
from odoo.http import request

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
ROLE_HOME = {'admin': '/desk/admin', 'agent': '/desk', 'customer': '/desk/my'}
PORTAL_ROLES = {'admin': {'admin'}, 'employee': {'agent', 'admin'}, 'customer': {'customer'}}
PORTAL_LABELS = {'admin': 'Admin', 'employee': 'Employee', 'customer': 'Customer'}
PASSWORD_CHANGE_PATH = '/desk/password/change'


def client_ip():
    return request.httprequest.environ.get('REMOTE_ADDR') or 'n/a'


def clean_email(value):
    return (value or '').strip().lower()


def valid_email(value):
    return bool(EMAIL_RE.match(value or ''))


def home_for(user):
    """Landing path of ``user`` according to their Aixo Desk role."""
    return ROLE_HOME.get(user.desk_role, '/desk/login')


def safe_redirect(target, user):
    """Only follow ``redirect`` to local /desk paths; otherwise use the role home."""
    if target:
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc and target.startswith('/desk') \
                and not target.startswith('//'):
            return target
    return home_for(user)


def password_problem(password, confirm=None):
    """Return an error message when ``password`` is not acceptable, else None."""
    if len(password or '') < 8:
        return _("Password must be at least 8 characters.")
    if confirm is not None and password != confirm:
        return _("Passwords do not match.")
    return None


def desk_page(roles=None):
    """Guard for website pages: login, forced password change, role check.

    ``roles`` is an iterable of ``admin`` / ``agent`` / ``customer``. An admin
    also passes where ``agent`` is allowed, because the admin group implies it.
    """
    allowed = set(roles or ())
    if 'agent' in allowed:
        allowed.add('admin')

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            user = request.env.user
            if user._is_public():
                return request.redirect('/desk/login?redirect=' + request.httprequest.path)
            if user.desk_force_password_change and request.httprequest.path != PASSWORD_CHANGE_PATH:
                return request.redirect(PASSWORD_CHANGE_PATH)
            role = user.desk_role
            if not role:
                return request.redirect('/desk/login?error=norole')
            if allowed and role not in allowed:
                return request.redirect(home_for(user))
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


def system_param(name, default=''):
    return request.env['ir.config_parameter'].sudo().get_param(f'aixo_desk.{name}', default)


def base_url():
    return request.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')


def send_mail(email_to, subject, template, values, reply_to=None):
    """Render a QWeb mail body and send it right away (never raises on SMTP errors)."""
    body = request.env['ir.qweb']._render(template, {
        **values, 'company_name': system_param('company_name', 'Aixo Desk')})
    sender = system_param('support_email') or request.env.company.email_formatted
    request.env['mail.mail'].sudo().create({
        'subject': subject,
        'body_html': body,
        'email_to': email_to,
        'email_from': sender,
        'reply_to': reply_to or False,
        'auto_delete': True,
    }).send(raise_exception=False)
