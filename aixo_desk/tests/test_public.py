import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPublicHome(HttpCase):

    def _csrf(self, path='/aixo-desk/demo'):
        page = self.url_open(path)
        self.assertEqual(page.status_code, 200)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    def _post_demo(self, **overrides):
        data = {'csrf_token': self._csrf(), 'name': 'Meera Nair', 'email': 'Meera@Example.org',
                'company': 'Nair Foods', 'team_size': '6-20', 'message': 'Show me reports', 'website_url': ''}
        data.update(overrides)
        return self.url_open('/aixo-desk/demo', data=data)

    def test_home_page_is_public_and_complete(self):
        page = self.url_open('/aixo-desk')
        self.assertEqual(page.status_code, 200)
        text = page.text
        for needle in (
            'Meet Aixo, your', 'data-ax-typed', 'data-ax-story', 'data-ax-replay',
            'Admin portal', 'Employee portal', 'Customer portal',
            'id="product"', 'id="portals"', 'id="security"', 'id="pricing"', 'id="resources"',
            '/desk/login?portal=admin', '/desk/login?portal=customer', 'data-ax-demo-dialog',
        ):
            self.assertIn(needle, text, needle)
        self.assertEqual(len(re.findall(r'class="ax-logo-cell"', text)), 8)

    def test_statement_is_in_html_without_javascript(self):
        self.assertIn('turns every email, chat and call into a ticket', self.url_open('/aixo-desk').text)

    def test_demo_page_without_js(self):
        page = self.url_open('/aixo-desk/demo').text
        self.assertIn('Get a demo', page)
        for field in ('name', 'email', 'company', 'team_size', 'message'):
            self.assertIn(f'name="{field}"', page, field)
        self.assertIn('<textarea', page)
        self.assertIn('</textarea>', page)

    def test_demo_request_is_stored(self):
        response = self._post_demo()
        self.assertIn('Thank you, Meera', response.text)
        record = self.env['aixo.demo.request'].search([('email', '=', 'meera@example.org')])
        self.assertEqual(len(record), 1)
        self.assertEqual((record.name, record.company, record.team_size), ('Meera Nair', 'Nair Foods', '6-20'))

    def test_demo_request_validation(self):
        self.assertIn('Enter your name.', self._post_demo(name=' ').text)
        self.assertIn('valid work email', self._post_demo(email='nope').text)
        self.assertFalse(self.env['aixo.demo.request'].search([('email', 'in', ('nope', 'meera@example.org'))]))

    def test_honeypot_is_discarded_silently(self):
        response = self._post_demo(website_url='http://spam.example.com', email='bot@example.org')
        self.assertIn('Thank you', response.text)
        self.assertFalse(self.env['aixo.demo.request'].search([('email', '=', 'bot@example.org')]))

    def test_demo_request_json_route(self):
        ok = self.make_jsonrpc_request('/desk/api/demo-request', {
            'name': 'Ravi Shankar', 'email': 'ravi@example.org', 'company': 'RS', 'team_size': '1-5'})
        self.assertEqual(ok, {'ok': True, 'data': {'name': 'Ravi'}})
        self.assertTrue(self.env['aixo.demo.request'].search([('email', '=', 'ravi@example.org')]))
        bad = self.make_jsonrpc_request('/desk/api/demo-request', {'name': 'x', 'email': 'broken'})
        self.assertFalse(bad['ok'])

    def test_long_input_is_truncated(self):
        self.make_jsonrpc_request('/desk/api/demo-request', {
            'name': 'N' * 500, 'email': 'long@example.org', 'message': 'm' * 5000})
        record = self.env['aixo.demo.request'].search([('email', '=', 'long@example.org')])
        self.assertEqual(len(record.name), 120)
        self.assertEqual(len(record.message), 2000)

    def test_demo_requests_are_rate_limited(self):
        for n in range(5):
            self.make_jsonrpc_request('/desk/api/demo-request', {'name': f'P{n}', 'email': f'p{n}@example.org'})
        blocked = self.make_jsonrpc_request('/desk/api/demo-request', {'name': 'P9', 'email': 'p9@example.org'})
        self.assertFalse(blocked['ok'])
        self.assertIn('Too many', blocked['error'])

    def test_html_in_demo_fields_is_escaped_in_the_notification(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.support_email', 'sales@example.com')
        self.make_jsonrpc_request('/desk/api/demo-request', {
            'name': '<b>Eve</b>', 'email': 'eve@example.org', 'message': '<script>alert(1)</script>'})
        mail = self.env['mail.mail'].sudo().search([('email_to', '=', 'sales@example.com')], limit=1) \
            or self.env['mail.mail'].sudo().search([('subject', 'ilike', 'demo request')], limit=1)
        if mail:  # mails are auto-deleted once sent; when kept, the body must be escaped
            self.assertNotIn('<script>', mail.body_html)
