import logging
from datetime import timedelta

from odoo import _, _lt, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .base import (
    PASSWORD_CHANGE_PATH, PORTAL_LABELS, PORTAL_ROLES, clean_email, client_ip,
    base_url, home_for, password_problem, safe_redirect, send_mail, system_param, valid_email,
)

_logger = logging.getLogger(__name__)

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK = timedelta(minutes=15)
SIGNUP_PER_HOUR = 10
OTP_SENDS_PER_HOUR = 5
OTP_VERIFIES_PER_HOUR = 20
RESET_SESSION_KEY = 'aixo_reset'
GENERIC_SENT = _lt("If an account exists for that email, we've sent a 6-digit code.")


def _ok(data=None):
    return {'ok': True, 'data': data or {}}


def _err(message, **extra):
    return {'ok': False, 'error': message, **extra}


class DeskAuth(http.Controller):

    # ------------------------------------------------------------------- login

    def _login_values(self, **extra):
        values = {
            'portal': (request.params.get('portal') or 'employee').lower(),
            'login': request.params.get('login', ''),
            'redirect': request.params.get('redirect', ''),
            'signup_enabled': system_param('signup_enabled', 'True') == 'True',
            'error': False,
        }
        if values['portal'] not in PORTAL_ROLES:
            values['portal'] = 'employee'
        values.update(extra)
        return values

    @http.route('/desk/login', type='http', auth='public', website=True, sitemap=False, methods=['GET', 'POST'])
    def login(self, **kw):
        user = request.env.user
        if request.httprequest.method == 'GET':
            if not user._is_public() and user.desk_role:
                return request.redirect(safe_redirect(kw.get('redirect'), user))
            error = {'norole': _("This account has no Aixo Desk access."),
                     'reset': False}.get(kw.get('error'), False)
            return request.render('aixo_desk.login_page', self._login_values(
                error=error, reset_done=kw.get('reset') == '1'))
        return self._do_login(kw)

    def _do_login(self, kw):
        login = clean_email(kw.get('login'))
        password = kw.get('password') or ''
        portal = (kw.get('portal') or 'employee').lower()
        key = f"{client_ip()}|{login}"
        values = self._login_values(login=login, portal=portal)

        if request.env['aixo.rate.limit'].is_locked('login', key):
            minutes = request.env['aixo.rate.limit'].minutes_left('login', key)
            values['error'] = _("Too many failed attempts. Try again in %s minutes.", minutes)
            return request.render('aixo_desk.login_page', values)
        if not login or not password:
            values['error'] = _("Enter your email and password.")
            return request.render('aixo_desk.login_page', values)

        credential = {'login': login, 'password': password, 'type': 'password'}
        try:
            auth_info = request.session.authenticate(request.env, credential)
        except AccessDenied:
            locked = request.env['aixo.rate.limit'].hit('login', key, LOGIN_MAX_FAILURES, lock=LOGIN_LOCK)
            values['error'] = (_("Too many failed attempts. Try again in 15 minutes.") if locked
                               else _("Wrong email or password."))
            return request.render('aixo_desk.login_page', values)

        user = request.env['res.users'].sudo().browse(auth_info['uid'])
        role = user.desk_role
        if not role or portal not in PORTAL_ROLES or role not in PORTAL_ROLES[portal]:
            request.session.logout(keep_db=True)
            values['error'] = _("This account doesn't have access to the %s portal.",
                                PORTAL_LABELS.get(portal, portal))
            return request.render('aixo_desk.login_page', values)
        if role == 'customer' and system_param('portal_enabled', 'True') != 'True':
            request.session.logout(keep_db=True)
            values['error'] = _("The customer portal is currently disabled.")
            return request.render('aixo_desk.login_page', values)

        request.env['aixo.rate.limit'].reset('login', key)
        request.session['aixo_keep'] = bool(kw.get('keep'))
        if user.desk_force_password_change:
            return request.redirect(PASSWORD_CHANGE_PATH)
        return request.redirect(safe_redirect(kw.get('redirect'), user))

    @http.route('/desk/logout', type='http', auth='public', website=True, sitemap=False)
    def logout(self, **kw):
        request.session.logout(keep_db=True)
        return request.redirect('/desk/login')

    # ---------------------------------------------------------- forced change

    @http.route(PASSWORD_CHANGE_PATH, type='http', auth='public', website=True, sitemap=False,
                methods=['GET', 'POST'])
    def password_change(self, **kw):
        user = request.env.user
        if user._is_public():
            return request.redirect('/desk/login?redirect=' + PASSWORD_CHANGE_PATH)
        values = {'error': False, 'forced': user.desk_force_password_change}
        if request.httprequest.method == 'POST':
            password, confirm = kw.get('password') or '', kw.get('confirm') or ''
            error = password_problem(password, confirm)
            if not error and self._same_as_current(user, password):
                error = _("Choose a password different from your current one.")
            if error:
                values['error'] = error
            else:
                self._set_password(user, password)
                return request.redirect(home_for(user))
        return request.render('aixo_desk.password_change_page', values)

    def _same_as_current(self, user, password):
        try:
            user.with_user(user)._check_credentials(
                {'type': 'password', 'password': password}, {'interactive': False})
            return True
        except AccessDenied:
            return False

    def _set_password(self, user, password):
        """Change the password, clear the forced flag and keep this session alive."""
        account = user.sudo()
        account._change_password(password)
        account.desk_force_password_change = False
        request.env.flush_all()
        request.env.registry.clear_cache()
        if request.session.uid == account.id:
            request.session.session_token = account._compute_session_token(request.session.sid)

    # ----------------------------------------------------------------- signup

    @http.route('/desk/signup', type='http', auth='public', website=True, sitemap=False,
                methods=['GET', 'POST'])
    def signup(self, **kw):
        if system_param('signup_enabled', 'True') != 'True':
            return request.render('aixo_desk.signup_disabled_page')
        values = {'error': False, 'done': False, 'form': {}}
        if request.httprequest.method == 'POST':
            form = {k: (kw.get(k) or '').strip() for k in ('first', 'last', 'email', 'company')}
            form['email'] = clean_email(form['email'])
            values['form'] = form
            error = self._signup_error(form, kw)
            if not error:
                try:
                    self._create_customer(form, kw['password'])
                    values.update(done=True, first=form['first'])
                except Exception:
                    _logger.exception("Aixo Desk sign-up failed")
                    error = _("We couldn't create your account. Please try again.")
            values['error'] = error
        return request.render('aixo_desk.signup_page', values)

    def _signup_error(self, form, kw):
        if request.env['aixo.rate.limit'].hit('signup', client_ip(), SIGNUP_PER_HOUR,
                                              window=timedelta(hours=1), lock=timedelta(hours=1)):
            return _("Too many sign-ups from this network. Try again later.")
        if not form['first']:
            return _("Enter your first name.")
        if not valid_email(form['email']):
            return _("Enter a valid work email.")
        problem = password_problem(kw.get('password'))
        if problem:
            return problem
        if not kw.get('terms'):
            return _("Please accept the terms to continue.")
        exists = request.env['res.users'].sudo().with_context(active_test=False).search_count(
            ['|', ('login', '=ilike', form['email']), ('email', '=ilike', form['email'])])
        if exists:
            return _("An account with this email already exists.")
        return None

    def _create_customer(self, form, password):
        env = request.env
        full_name = ' '.join(filter(None, (form['first'], form['last'])))
        values = {
            'name': full_name,
            'login': form['email'],
            'email': form['email'],
            'password': password,
            'group_ids': [(6, 0, [env.ref('aixo_desk.group_desk_customer').id])],
        }
        if form['company']:
            company = env['res.partner'].sudo().create({'name': form['company'], 'is_company': True})
            values['parent_id'] = company.id
        user = env['res.users'].sudo().with_context(no_reset_password=True).create(values)
        send_mail(
            user.email, _("Welcome to Aixo Desk"), 'aixo_desk.mail_welcome',
            {'first': form['first'], 'login_url': f"{base_url()}/desk/login?portal=customer"})
        return user

    # --------------------------------------------------------------- password reset

    @http.route('/desk/reset', type='http', auth='public', website=True, sitemap=False)
    def reset_page(self, **kw):
        return request.render('aixo_desk.reset_page', {})

    @http.route('/desk/api/otp/send', type='jsonrpc', auth='public', website=True)
    def otp_send(self, email=None, **kw):
        email = clean_email(email)
        if not valid_email(email):
            return _err(_("Enter a valid email address."))
        key = f"{client_ip()}|{email}"
        if request.env['aixo.rate.limit'].hit('otp_send', key, OTP_SENDS_PER_HOUR,
                                              window=timedelta(hours=1), lock=timedelta(hours=1)):
            return _err(_("Too many requests. Try again later."))
        user = request.env['res.users'].sudo().search(
            [('login', '=ilike', email), ('active', '=', True)], limit=1)
        if user and user.desk_role:
            code, _record = request.env['aixo.otp'].issue(user)
            if code:
                send_mail(user.email or user.login, _("Your Aixo Desk verification code"),
                                'aixo_desk.mail_otp', {'name': user.name, 'code': code})
        # The response never reveals whether the account exists or a mail was throttled.
        return _ok({'message': GENERIC_SENT, 'resend_after': 30})

    @http.route('/desk/api/otp/verify', type='jsonrpc', auth='public', website=True)
    def otp_verify(self, email=None, code=None, **kw):
        email = clean_email(email)
        digits = ''.join(ch for ch in (code or '') if ch.isdigit())
        if len(digits) != 6:
            return _err(_("Enter the 6-digit code."))
        if request.env['aixo.rate.limit'].hit('otp_verify', client_ip(), OTP_VERIFIES_PER_HOUR,
                                              window=timedelta(hours=1), lock=timedelta(hours=1)):
            return _err(_("Too many attempts. Try again later."))
        user = request.env['res.users'].sudo().search(
            [('login', '=ilike', email), ('active', '=', True)], limit=1)
        otp = request.env['aixo.otp'].verify(user, digits) if user else None
        if not otp:
            return _err(_("That code is invalid or has expired."))
        request.session[RESET_SESSION_KEY] = {'otp': otp.id, 'user': user.id}
        return _ok({})

    @http.route('/desk/api/otp/reset', type='jsonrpc', auth='public', website=True)
    def otp_reset(self, password=None, confirm=None, **kw):
        state = request.session.get(RESET_SESSION_KEY)
        if not state:
            return _err(_("Your reset session has expired. Start again."))
        problem = password_problem(password, confirm)
        if problem:
            return _err(problem)
        otp = request.env['aixo.otp'].sudo().browse(state['otp']).exists()
        user = request.env['res.users'].sudo().browse(state['user']).exists()
        if not (otp and user and otp.verified and not otp.used and otp.user_id == user
                and otp.expires_at > request.env.cr.now()):
            request.session.pop(RESET_SESSION_KEY, None)
            return _err(_("Your reset session has expired. Start again."))
        if self._same_as_current(user, password):
            return _err(_("Choose a password different from your current one."))
        otp.consume()
        user._change_password(password)
        user.desk_force_password_change = False
        request.session.pop(RESET_SESSION_KEY, None)
        # Changing the password invalidates every other session of this user,
        # because the session token is derived from the stored password hash.
        request.env['aixo.rate.limit'].reset('login', f"{client_ip()}|{clean_email(user.login)}")
        return _ok({'login_url': '/desk/login?reset=1'})

    # ------------------------------------------------------------------ helpers
