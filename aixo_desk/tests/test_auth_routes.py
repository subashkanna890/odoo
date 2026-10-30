import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAuthRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        mk = lambda name, login, group, **kw: env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'email': login, 'password': 'Passw0rd!x',
            'group_ids': [(6, 0, [env.ref(group).id])], **kw})
        cls.admin = mk('R Admin', 'r_admin@example.com', 'aixo_desk.group_desk_admin')
        cls.agent = mk('R Agent', 'r_agent@example.com', 'aixo_desk.group_desk_agent')
        cls.customer = mk('R Cust', 'r_cust@example.com', 'aixo_desk.group_desk_customer')
        cls.forced = mk('R Forced', 'r_forced@example.com', 'aixo_desk.group_desk_agent',
                        desk_force_password_change=True)
        cls.plain_portal = mk('R Plain', 'r_plain@example.com', 'base.group_portal')

    # -------------------------------------------------------------------- helpers

    def _csrf(self, path='/desk/login'):
        page = self.url_open(path)
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertTrue(match, "csrf token present in form")
        return match.group(1)

    def _login(self, login, password='Passw0rd!x', portal='employee', **extra):
        data = {'csrf_token': self._csrf(), 'login': login, 'password': password, 'portal': portal, **extra}
        return self.url_open('/desk/login', data=data, allow_redirects=False)

    def _fresh_session(self):
        self.opener.cookies.clear()

    # ---------------------------------------------------------------------- login

    def test_login_page_renders_all_portals(self):
        page = self.url_open('/desk/login')
        self.assertEqual(page.status_code, 200)
        for label in ('Admin', 'Employee', 'Customer', 'Forgot password?', 'Keep me logged in'):
            self.assertIn(label, page.text)
        self.assertIn('/desk/signup', page.text)

    def test_role_redirects(self):
        for login, portal, target in (
            ('r_admin@example.com', 'admin', '/desk/admin'),
            ('r_agent@example.com', 'employee', '/desk'),
            ('r_cust@example.com', 'customer', '/desk/my'),
            ('r_admin@example.com', 'employee', '/desk/admin'),
        ):
            self._fresh_session()
            response = self._login(login, portal=portal)
            self.assertEqual(response.status_code, 303, login)
            self.assertEqual(response.headers['Location'].replace(self.base_url(), ''), target, login)

    def test_portal_selector_does_not_grant_access(self):
        cases = (
            ('r_agent@example.com', 'admin', 'Admin'),
            ('r_cust@example.com', 'employee', 'Employee'),
            ('r_agent@example.com', 'customer', 'Customer'),
        )
        for login, portal, label in cases:
            self._fresh_session()
            response = self._login(login, portal=portal)
            self.assertEqual(response.status_code, 200, login)
            self.assertIn(f"This account doesn&#39;t have access to the {label} portal.", response.text.replace("'", '&#39;'))
            self.assertEqual(self.url_open('/desk', allow_redirects=False).status_code, 303,
                             "session was dropped, /desk still needs login")

    def test_account_without_desk_role_is_refused(self):
        response = self._login('r_plain@example.com', portal='customer')
        self.assertEqual(response.status_code, 200)
        self.assertIn('have access', response.text)

    def test_wrong_password_and_lockout(self):
        for attempt in range(4):
            response = self._login('r_agent@example.com', password='nope')
            self.assertIn('Wrong email or password', response.text, attempt)
        response = self._login('r_agent@example.com', password='nope')
        self.assertIn('Too many failed attempts', response.text)
        # even the right password is refused while locked
        response = self._login('r_agent@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Too many failed attempts', response.text)
        # lock expires
        self.env['aixo.rate.limit'].sudo().search([('kind', '=', 'login')]).locked_until = \
            fields.Datetime.now() - timedelta(minutes=1)
        self._fresh_session()
        self.assertEqual(self._login('r_agent@example.com').status_code, 303)

    def test_csrf_required_on_login(self):
        response = self.url_open('/desk/login', data={'login': 'r_agent@example.com', 'password': 'Passw0rd!x'})
        self.assertEqual(response.status_code, 400)

    def test_logged_in_user_is_redirected_from_login(self):
        self._login('r_cust@example.com', portal='customer')
        response = self.url_open('/desk/login', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith('/desk/my'))

    def test_open_redirect_is_blocked(self):
        for target in ('https://evil.example.com', '//evil.example.com', '/web'):
            self._fresh_session()
            response = self._login('r_agent@example.com', redirect=target)
            self.assertTrue(response.headers['Location'].endswith('/desk'), target)
        self._fresh_session()
        response = self._login('r_agent@example.com', redirect='/desk/customers')
        self.assertTrue(response.headers['Location'].endswith('/desk/customers'))

    # ------------------------------------------------------------- route guards

    def test_pages_redirect_to_login_when_anonymous(self):
        for path in ('/desk', '/desk/admin', '/desk/my'):
            response = self.url_open(path, allow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertIn('/desk/login', response.headers['Location'])

    def test_wrong_role_is_sent_home(self):
        self._login('r_agent@example.com')
        self.assertTrue(self.url_open('/desk/admin', allow_redirects=False).headers['Location'].endswith('/desk'))
        self.assertTrue(self.url_open('/desk/my', allow_redirects=False).headers['Location'].endswith('/desk'))
        self.assertEqual(self.url_open('/desk', allow_redirects=False).status_code, 200)
        self._fresh_session()
        self._login('r_cust@example.com', portal='customer')
        self.assertTrue(self.url_open('/desk', allow_redirects=False).headers['Location'].endswith('/desk/my'))
        self.assertTrue(self.url_open('/desk/admin', allow_redirects=False).headers['Location'].endswith('/desk/my'))

    def test_forced_password_change(self):
        response = self._login('r_forced@example.com')
        self.assertTrue(response.headers['Location'].endswith('/desk/password/change'))
        guarded = self.url_open('/desk', allow_redirects=False)
        self.assertTrue(guarded.headers['Location'].endswith('/desk/password/change'))
        token = self._csrf('/desk/password/change')
        post = lambda pw, confirm: self.url_open('/desk/password/change', allow_redirects=False, data={
            'csrf_token': token, 'password': pw, 'confirm': confirm})
        self.assertIn('at least 8', post('short', 'short').text)
        self.assertIn('do not match', post('Newpass123', 'Newpass124').text)
        self.assertIn('different from your current', post('Passw0rd!x', 'Passw0rd!x').text)
        done = post('Newpass123', 'Newpass123')
        self.assertEqual(done.status_code, 303)
        self.assertFalse(self.forced.desk_force_password_change)
        self.assertEqual(self.url_open('/desk', allow_redirects=False).status_code, 200,
                         "session survives the password change")
        self._fresh_session()
        self.assertEqual(self._login('r_forced@example.com', password='Newpass123').status_code, 303)

    # -------------------------------------------------------------------- signup

    def _signup(self, **overrides):
        data = {'csrf_token': self._csrf('/desk/signup'), 'first': 'Meera', 'last': 'Nair',
                'email': 'meera@example.org', 'company': 'Nair Foods', 'password': 'Sup3rsecret', 'terms': '1'}
        data.update(overrides)
        return self.url_open('/desk/signup', data=data)

    def test_signup_creates_company_and_portal_customer(self):
        response = self._signup()
        self.assertIn('Welcome aboard, Meera', response.text)
        user = self.env['res.users'].search([('login', '=', 'meera@example.org')])
        self.assertEqual(user.desk_role, 'customer')
        self.assertTrue(user.share)
        self.assertEqual(user.partner_id.parent_id.name, 'Nair Foods')
        self._fresh_session()
        self.assertEqual(self._login('meera@example.org', 'Sup3rsecret', 'customer').status_code, 303)

    def test_signup_without_company(self):
        self._signup(email='solo@example.org', company='')
        user = self.env['res.users'].search([('login', '=', 'solo@example.org')])
        self.assertTrue(user)
        self.assertFalse(user.partner_id.parent_id)

    def test_signup_duplicate_email(self):
        self.assertIn('An account with this email already exists.', self._signup(email='R_AGENT@example.com').text)
        self._signup(email='dup@example.org')
        self.assertIn('already exists', self._signup(email='dup@example.org').text)

    def test_signup_validation(self):
        self.assertIn('first name', self._signup(first='').text)
        self.assertIn('valid work email', self._signup(email='nope').text)
        self.assertIn('at least 8', self._signup(password='short').text)
        self.assertIn('accept the terms', self._signup(terms='').text)
        self.assertFalse(self.env['res.users'].search([('login', '=', 'meera@example.org')]))

    def test_signup_can_be_disabled(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.signup_enabled', 'False')
        page = self.url_open('/desk/signup')
        self.assertIn('Sign-up is closed', page.text)
        self.assertNotIn('/desk/signup', self.url_open('/desk/login').text.replace('action="/desk/signup"', ''))

    # ------------------------------------------------------------ password reset

    def _rpc(self, route, params):
        return self.make_jsonrpc_request(route, params)

    def _issue_code(self, email='r_agent@example.com'):
        with patch('odoo.addons.aixo_desk.models.otp.secrets.randbelow', return_value=123456):
            result = self._rpc('/desk/api/otp/send', {'email': email})
        self.assertTrue(result['ok'])
        return result

    def test_otp_send_never_reveals_account_existence(self):
        known = self._issue_code('r_agent@example.com')
        unknown = self._issue_code('nobody@example.org')
        self.assertEqual(known, unknown)
        self.assertEqual(self.env['aixo.otp'].search_count([('user_id', '=', self.agent.id)]), 1)
        self.assertFalse(self.env['aixo.otp'].search([('user_id.login', '=', 'nobody@example.org')]))
        invalid = self._rpc('/desk/api/otp/send', {'email': 'not-an-email'})
        self.assertFalse(invalid['ok'])

    def test_otp_mail_contains_code_and_full_reset_flow(self):
        self._issue_code()
        otp = self.env['aixo.otp'].search([('user_id', '=', self.agent.id)])
        code = self._known_code(otp)
        bad = self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': '12'})
        self.assertFalse(bad['ok'])
        wrong = '000000' if code != '000000' else '111111'
        self.assertFalse(self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': wrong})['ok'])
        self.assertEqual(otp.attempts, 1)
        # cannot jump to step 3 without verifying
        self.assertFalse(self._rpc('/desk/api/otp/reset', {'password': 'Brandnew123', 'confirm': 'Brandnew123'})['ok'])
        self.assertTrue(self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': code})['ok'])
        self.assertFalse(self._rpc('/desk/api/otp/reset', {'password': 'short', 'confirm': 'short'})['ok'])
        self.assertFalse(self._rpc('/desk/api/otp/reset', {'password': 'Brandnew123', 'confirm': 'Other12345'})['ok'])
        same = self._rpc('/desk/api/otp/reset', {'password': 'Passw0rd!x', 'confirm': 'Passw0rd!x'})
        self.assertFalse(same['ok'])
        self.assertIn('different', same['error'])
        done = self._rpc('/desk/api/otp/reset', {'password': 'Brandnew123', 'confirm': 'Brandnew123'})
        self.assertTrue(done['ok'])
        self.assertTrue(otp.used)
        self.assertFalse(self._rpc('/desk/api/otp/reset', {'password': 'Another1234', 'confirm': 'Another1234'})['ok'],
                         "code and session are single use")
        self._fresh_session()
        self.assertEqual(self._login('r_agent@example.com', 'Brandnew123').status_code, 303)
        self._fresh_session()
        self.assertEqual(self._login('r_agent@example.com', 'Passw0rd!x').status_code, 200, "old password is dead")

    def _known_code(self, otp):
        self.assertEqual(self.env['aixo.otp']._hash(otp.user_id, '123456'), otp.code_hash)
        return '123456'

    def test_reset_invalidates_other_sessions(self):
        other = self.env['res.users'].browse(self.agent.id)
        old_token = other.sudo()._compute_session_token('sid')
        self._issue_code()
        otp = self.env['aixo.otp'].search([('user_id', '=', self.agent.id)])
        code = self._known_code(otp)
        self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': code})
        self._rpc('/desk/api/otp/reset', {'password': 'Brandnew123', 'confirm': 'Brandnew123'})
        self.env.invalidate_all()
        self.assertNotEqual(old_token, self.agent.sudo()._compute_session_token('sid'),
                            "session tokens depend on the password hash, so old sessions stop working")

    def test_otp_attempts_lock_after_five_wrong_codes(self):
        self._issue_code()
        otp = self.env['aixo.otp'].search([('user_id', '=', self.agent.id)])
        code = self._known_code(otp)
        wrong = '000000' if code != '000000' else '111111'
        for _i in range(5):
            self.assertFalse(self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': wrong})['ok'])
        self.assertFalse(self._rpc('/desk/api/otp/verify', {'email': 'r_agent@example.com', 'code': code})['ok'])

    def test_otp_resend_is_throttled_silently(self):
        self._issue_code()
        self._issue_code()
        self.assertEqual(self.env['aixo.otp'].search_count([('user_id', '=', self.agent.id)]), 1,
                         "a second request inside 30s does not create another code")

    def test_reset_page_and_assets_render(self):
        page = self.url_open('/desk/reset')
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-ax-reset', page.text)
        self.assertEqual(len(re.findall(r'data-ax-otp', page.text)), 6)
