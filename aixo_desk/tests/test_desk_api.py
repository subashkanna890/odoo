import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestDeskApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        mk = lambda name, login, group, **kw: env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'email': login, 'password': 'Passw0rd!x',
            'group_ids': [(6, 0, [env.ref(group).id])], **kw})
        cls.admin = mk('A Admin', 'a_admin@example.com', 'aixo_desk.group_desk_admin')
        cls.agent = mk('Priya Agent', 'a_agent@example.com', 'aixo_desk.group_desk_agent')
        cls.other = mk('Arun Other', 'a_other@example.com', 'aixo_desk.group_desk_agent')
        cls.customer = mk('A Cust', 'a_cust@example.com', 'aixo_desk.group_desk_customer')
        cls.partner = env['res.partner'].create({'name': 'Lawrence Test', 'email': 'lawrence@example.org'})
        Ticket = env['aixo.ticket']
        cls.t1 = Ticket.create({'name': 'First ticket', 'partner_id': cls.partner.id, 'owner_id': cls.agent.id,
                                'description': '<p>I need this by Friday. It is urgent.</p>'})
        cls.t2 = Ticket.create({'name': 'Second ticket', 'partner_id': cls.partner.id, 'owner_id': cls.agent.id,
                                'priority': 'high'})
        cls.foreign = Ticket.create({'name': 'Not yours', 'partner_id': cls.partner.id, 'owner_id': cls.other.id})
        cls.unassigned = Ticket.create({'name': 'Nobody owns it', 'partner_id': cls.partner.id})

    # -------------------------------------------------------------------- helpers

    def rpc(self, route, **params):
        return self.make_jsonrpc_request(route, params)

    def signin(self, user):
        self.authenticate(user.login, 'Passw0rd!x')

    def good(self, route, **params):
        result = self.rpc(route, **params)
        self.assertTrue(result['ok'], result)
        return result['data']

    def bad(self, route, **params):
        result = self.rpc(route, **params)
        self.assertFalse(result['ok'], result)
        return result

    # ---------------------------------------------------------------------- pages

    def test_pages_render_for_agent(self):
        self.signin(self.agent)
        page = self.url_open('/desk')
        self.assertEqual(page.status_code, 200)
        self.assertIn('aixo_desk.TicketList', page.text)
        self.assertIn('aixo_desk.Topbar', page.text)
        self.assertIn('data-theme="blue"', page.text)
        detail = self.url_open(f'/desk/ticket/{self.t1.id}')
        self.assertIn('aixo_desk.TicketDetail', detail.text)
        self.assertTrue(self.url_open(f'/desk/ticket/{self.foreign.id}', allow_redirects=False).headers['Location'].endswith('/desk'))

    # ----------------------------------------------------------------------- list

    def test_list_counts_search_sort_and_scope(self):
        self.signin(self.agent)
        data = self.good('/desk/api/ticket/list')
        numbers = {t['number'] for t in data['tickets']}
        self.assertEqual(numbers, {self.t1.number, self.t2.number})
        self.assertEqual(data['counts']['all'], 2)
        self.assertEqual(data['counts']['my_open'], 2)
        self.assertEqual(data['counts']['closed'], 0)
        self.assertEqual(self.good('/desk/api/ticket/list', search='Second')['total'], 1)
        self.assertEqual(self.good('/desk/api/ticket/list', search=self.t1.number)['total'], 1)
        by_due = self.good('/desk/api/ticket/list', sort='due')
        self.assertEqual(by_due['total'], 2)
        self.t1.due_date = fields.Datetime.now() - timedelta(days=1)
        self.assertEqual(self.good('/desk/api/ticket/list', view='overdue')['total'], 1)

    def test_admin_sees_everything(self):
        self.signin(self.admin)
        data = self.good('/desk/api/ticket/list')
        self.assertGreaterEqual(data['total'], 4)
        unassigned = self.good('/desk/api/ticket/list', view='unassigned')
        self.assertIn(self.unassigned.id, [t['id'] for t in unassigned['tickets']])
        self.assertNotIn(self.t1.id, [t['id'] for t in unassigned['tickets']])

    def test_pagination(self):
        for n in range(55):
            self.env['aixo.ticket'].create({'name': f'Bulk {n}', 'partner_id': self.partner.id, 'owner_id': self.agent.id})
        self.signin(self.agent)
        first = self.good('/desk/api/ticket/list', page=1)
        second = self.good('/desk/api/ticket/list', page=2)
        self.assertEqual(len(first['tickets']), 50)
        self.assertEqual(len(second['tickets']), 7)
        self.assertFalse({t['id'] for t in first['tickets']} & {t['id'] for t in second['tickets']})

    # --------------------------------------------------------------------- access

    def test_anonymous_and_customer_are_refused(self):
        self.assertEqual(self.rpc('/desk/api/ticket/list')['code'], 'auth')
        self.signin(self.customer)
        self.assertEqual(self.rpc('/desk/api/ticket/list')['code'], 'forbidden')
        self.assertEqual(self.rpc('/desk/api/ticket/get', id=self.t1.id)['code'], 'forbidden')
        self.assertEqual(self.rpc('/desk/api/notifications/list')['code'], 'forbidden')

    def test_agent_cannot_touch_foreign_tickets(self):
        self.signin(self.agent)
        for route, extra in (('/desk/api/ticket/get', {}), ('/desk/api/ticket/reply', {'body': 'hi'}),
                             ('/desk/api/ticket/update', {'values': {'priority': 'low'}}),
                             ('/desk/api/timer/start', {}), ('/desk/api/ticket/close', {'summary': 'x'})):
            result = self.bad(route, id=self.foreign.id, **extra)
            self.assertIn(result['code'], ('forbidden', 'missing'), route)
        self.assertEqual(self.foreign.state, 'open')

    # --------------------------------------------------------------------- detail

    def test_detail_payload(self):
        self.signin(self.agent)
        data = self.good('/desk/api/ticket/get', id=self.t1.id)
        ticket = data['ticket']
        self.assertEqual(ticket['subject'], 'First ticket')
        self.assertEqual(data['contact']['name'], 'Lawrence Test')
        self.assertEqual(data['contact']['counts']['open'], 2, "counts only include tickets the agent can see")
        self.assertTrue(ticket['sla']['first_response_deadline'])
        self.assertEqual({t['id'] for t in data['switcher']}, {self.t1.id, self.t2.id})
        self.assertTrue(data['macros'])
        self.assertIn('Lawrence', data['macros'][0]['text'])
        self.assertIn('Priya Agent', data['macros'][0]['text'])

    def test_summary_is_local_and_finds_deadline(self):
        self.signin(self.agent)
        summary = self.good('/desk/api/ticket/summary', id=self.t1.id)
        self.assertEqual(summary['provider'], 'local')
        self.assertEqual(summary['deadline'].lower(), 'friday')
        self.assertEqual(summary['tone'], 'urgent')

    # --------------------------------------------------------------------- update

    def test_update_fields_and_whitelist(self):
        self.signin(self.agent)
        data = self.good('/desk/api/ticket/update', id=self.t1.id, values={'state': 'on_hold'})
        self.assertEqual(data['ticket']['state'], 'on_hold')
        self.assertTrue(self.t1.hold_since)
        self.good('/desk/api/ticket/update', id=self.t1.id, values={'priority': 'urgent'})
        self.assertEqual(self.t1.priority, 'urgent')
        self.good('/desk/api/ticket/update', id=self.t1.id, values={'due_date': '2030-01-15T10:30'})
        self.assertTrue(self.t1.due_date)
        self.assertEqual(self.bad('/desk/api/ticket/update', id=self.t1.id, values={'name': 'hacked'})['error'][:10], 'These fiel')
        self.assertIn('Close Ticket', self.bad('/desk/api/ticket/update', id=self.t1.id, values={'state': 'closed'})['error'])
        self.assertEqual(self.t1.name, 'First ticket')

    def test_changes_are_logged_in_history(self):
        self.signin(self.agent)
        self.good('/desk/api/ticket/update', id=self.t1.id, values={'priority': 'low'})
        history = self.good('/desk/api/ticket/get', id=self.t1.id)['history']
        self.assertTrue(any(c['field'] == 'Priority' for h in history for c in h['changes']))

    def test_assignment_notifies_new_owner(self):
        self.signin(self.admin)
        self.good('/desk/api/ticket/update', id=self.unassigned.id, values={'owner_id': self.other.id})
        notification = self.env['aixo.notification'].sudo().search(
            [('user_id', '=', self.other.id), ('type', '=', 'assign'), ('ticket_id', '=', self.unassigned.id)])
        self.assertEqual(len(notification), 1)
        self.good('/desk/api/ticket/update', id=self.unassigned.id, values={'owner_id': self.admin.id})
        self.assertFalse(self.env['aixo.notification'].sudo().search(
            [('user_id', '=', self.admin.id), ('ticket_id', '=', self.unassigned.id)]), "no self-notification")
        self.assertIn('employees', self.bad('/desk/api/ticket/update', id=self.unassigned.id,
                                            values={'owner_id': self.customer.id})['error'])

    def test_ticket_tags(self):
        self.signin(self.agent)
        tags = self.good('/desk/api/ticket/tag', id=self.t1.id, add='Zebra')['tags']
        self.assertEqual([t['name'] for t in tags], ['Zebra'])
        self.good('/desk/api/ticket/tag', id=self.t1.id, add='zebra')
        self.assertEqual(self.env['aixo.ticket.tag'].search_count([('name', '=ilike', 'zebra')]), 1, "no duplicates")
        self.assertEqual(len(self.t1.tag_ids), 1)
        tags = self.good('/desk/api/ticket/tag', id=self.t1.id, remove=tags[0]['id'])['tags']
        self.assertEqual(tags, [])
        self.assertTrue(self.bad('/desk/api/ticket/tag', id=self.t1.id, add='  ')['error'])

    # -------------------------------------------------------------------- replies

    def test_public_reply_sets_first_response_and_emails_contact(self):
        self.signin(self.agent)
        self.assertFalse(self.t1.responded_on)
        data = self.good('/desk/api/ticket/reply', id=self.t1.id, body='Hello <b>there</b>\nSecond line')
        self.assertFalse(data['message']['internal'])
        self.assertIn('&lt;b&gt;', data['message']['body'], "agent input is escaped")
        self.assertTrue(self.t1.responded_on)
        message = self.t1.message_ids.filtered(lambda m: m.message_type == 'comment')[0]
        self.assertIn(self.partner, message.partner_ids)
        self.assertEqual(message.subtype_id, self.env.ref('mail.mt_comment'))
        self.assertEqual(self.good('/desk/api/ticket/get', id=self.t1.id)['ticket']['replies'], 1)

    def test_reply_needs_text_and_contact_email(self):
        self.signin(self.agent)
        self.assertIn('first', self.bad('/desk/api/ticket/reply', id=self.t1.id, body='   ')['error'])
        self.partner.email = False
        self.assertIn('no email', self.bad('/desk/api/ticket/reply', id=self.t1.id, body='Hi')['error'])
        self.good('/desk/api/ticket/reply', id=self.t1.id, body='Internal only', internal=True)

    def test_internal_note_is_private_and_mentions_notify(self):
        self.signin(self.agent)
        data = self.good('/desk/api/ticket/reply', id=self.t1.id, body='Please check @Arun Other', internal=True)
        self.assertTrue(data['message']['internal'])
        message = self.t1.message_ids.filtered(lambda m: m.message_type == 'comment')[0]
        self.assertEqual(message.subtype_id, self.env.ref('mail.mt_note'))
        self.assertFalse(message.partner_ids)
        self.assertFalse(self.t1.responded_on, "a note is not a first response")
        mention = self.env['aixo.notification'].sudo().search([('user_id', '=', self.other.id), ('type', '=', 'mention')])
        self.assertEqual(len(mention), 1)
        self.assertEqual(self.good('/desk/api/ticket/get', id=self.t1.id)['ticket']['replies'], 0, "notes are not replies")

    def test_macro_usage_and_hold(self):
        self.signin(self.agent)
        macro = self.env.ref('aixo_desk.macro_request_info')
        self.good('/desk/api/ticket/reply', id=self.t1.id, body='Need more info', macro_id=macro.id)
        self.assertEqual(macro.usage_count, 1)
        self.assertEqual(self.t1.state, 'on_hold')

    # --------------------------------------------------------------- close/reopen

    def test_close_requires_resolution_and_reopen(self):
        self.signin(self.agent)
        self.assertIn('resolution', self.bad('/desk/api/ticket/close', id=self.t1.id, summary=' ')['error'])
        self.assertEqual(self.t1.state, 'open')
        self.good('/desk/api/timer/start', id=self.t1.id)
        data = self.good('/desk/api/ticket/close', id=self.t1.id, summary='Fixed the issue', notify=True)
        self.assertEqual(data['ticket']['state'], 'closed')
        self.assertIn('Fixed the issue', self.t1.resolution_summary)
        self.assertFalse(self.env['aixo.time.entry'].search([('ticket_id', '=', self.t1.id), ('timer_start', '!=', False)]),
                         "closing stops the timer")
        self.assertIn('Reopen', self.bad('/desk/api/timer/start', id=self.t1.id)['error'])
        self.good('/desk/api/ticket/reopen', id=self.t1.id)
        self.assertEqual(self.t1.state, 'open')

    # --------------------------------------------------------------------- timers

    def test_timer_lifecycle_one_running_per_agent(self):
        self.signin(self.agent)
        started = self.good('/desk/api/timer/start', id=self.t1.id)['timer']
        self.assertTrue(started['running'])
        self.good('/desk/api/timer/start', id=self.t2.id)
        self.env.invalidate_all()
        self.assertFalse(self.good('/desk/api/ticket/get', id=self.t1.id)['timer']['running'], "starting another pauses the first")
        paused = self.good('/desk/api/timer/pause', id=self.t2.id)
        self.assertFalse(paused['timer']['running'])
        self.assertEqual(self.env['aixo.time.entry'].search_count([('user_id', '=', self.agent.id), ('timer_start', '!=', False)]), 0)

    def test_time_entries_crud_and_ownership(self):
        self.signin(self.agent)
        data = self.good('/desk/api/time/save', id=self.t1.id, values={'name': 'Call', 'hours': 1.5, 'date': '2026-11-02'})
        entry = data['time_entries'][0]
        self.assertEqual((entry['hours'], entry['name']), (1.5, 'Call'))
        data = self.good('/desk/api/time/save', id=self.t1.id, entry_id=entry['id'], values={'name': 'Long call', 'hours': 2, 'date': '2026-11-02'})
        self.assertEqual(data['time_entries'][0]['hours'], 2)
        self.assertEqual(data['timer']['base_seconds'], 7200)
        self.assertTrue(self.bad('/desk/api/time/save', id=self.t1.id, values={'name': 'x', 'hours': 'abc'})['error'])
        self.assertTrue(self.bad('/desk/api/time/save', id=self.t1.id, values={'name': 'x', 'hours': -1})['error'])
        foreign = self.env['aixo.time.entry'].create({'ticket_id': self.t1.id, 'user_id': self.admin.id, 'duration': 1})
        self.bad('/desk/api/time/delete', id=self.t1.id, entry_id=foreign.id)
        self.assertTrue(foreign.exists())
        self.good('/desk/api/time/delete', id=self.t1.id, entry_id=entry['id'])
        self.assertFalse(self.env['aixo.time.entry'].search([('user_id', '=', self.agent.id), ('ticket_id', '=', self.t1.id)]))

    # ---------------------------------------------------------------- attachments

    def _csrf(self):
        page = self.url_open('/desk').text
        return re.search(r'csrf(?:&#34;|")\s*:\s*(?:&#34;|")([^&"]+)', page).group(1)

    def _upload(self, ticket, name, content, csrf=None):
        return self.url_open(f'/desk/ticket/{ticket.id}/attach', data={'csrf_token': csrf or self._csrf()},
                             files={'file': (name, content, 'text/plain')})

    def test_upload_download_and_policy(self):
        self.signin(self.agent)
        response = self._upload(self.t1, 'notes.txt', b'hello')
        self.assertEqual(response.status_code, 200, response.text)
        attachment = response.json()['data']['attachments'][0]
        self.assertEqual(attachment['name'], 'notes.txt')
        download = self.url_open(attachment['url'])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b'hello')
        self.assertEqual(self._upload(self.t1, 'bad.exe', b'MZ').status_code, 400)
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.attachment_max_mb', '1')
        self.assertEqual(self._upload(self.t1, 'big.txt', b'x' * (1024 * 1024 + 1)).status_code, 400)
        self.assertEqual(self._upload(self.foreign, 'a.txt', b'1').status_code, 400, "foreign ticket refused")
        self.assertEqual(self.url_open('/desk/ticket/%d/attach' % self.t1.id, data={'file': 'x'}).status_code, 400, "csrf required")
        data = self.good('/desk/api/ticket/get', id=self.t1.id)
        self.assertEqual([a['name'] for a in data['attachments']], ['notes.txt'])

    def test_attachment_download_is_access_controlled(self):
        self.signin(self.agent)
        attachment = self._upload(self.t1, 'secret.txt', b'secret').json()['data']['attachments'][0]
        self.signin(self.other)
        self.assertIn(self.url_open(attachment['url']).status_code, (403, 404))
        self.signin(self.customer)
        self.assertIn(self.url_open(attachment['url'], allow_redirects=False).status_code, (403, 404))
        self.opener.cookies.clear()
        self.assertEqual(self.url_open(attachment['url'], allow_redirects=False).status_code, 303)

    def test_attachments_on_reply_must_belong_to_the_ticket(self):
        self.signin(self.agent)
        mine = self._upload(self.t1, 'a.txt', b'1').json()['data']['attachments'][0]
        other = self._upload(self.t2, 'b.txt', b'2').json()['data']['attachments'][0]
        self.assertEqual(self.bad('/desk/api/ticket/reply', id=self.t1.id, body='x', attachment_ids=[other['id']])['error'], 'Invalid attachment.')
        data = self.good('/desk/api/ticket/reply', id=self.t1.id, body='see file', attachment_ids=[mine['id']])
        self.assertEqual(data['message']['attachments'][0]['name'], 'a.txt')

    # ---------------------------------------------------------------- notifications

    def test_notifications_flow(self):
        Notification = self.env['aixo.notification']
        a = Notification._notify(self.agent, 'assign', 'Assigned one', self.t1)
        m = Notification._notify(self.agent, 'mention', 'Mentioned', self.t1)
        Notification._notify(self.other, 'assign', 'Not for Priya', self.foreign)
        self.signin(self.agent)
        data = self.good('/desk/api/notifications/list')
        texts = {n['text'] for n in data['items']}
        self.assertTrue({'Assigned one', 'Mentioned'} <= texts)
        self.assertNotIn('Not for Priya', texts)
        self.assertEqual(data['unread'], len(data['items']))
        base_unread = data['unread']
        self.assertEqual({n['type'] for n in self.good('/desk/api/notifications/list', filter='mentions')['items']}, {'mention'})
        self.assertEqual(self.good('/desk/api/notifications/read', id=a.id)['unread'], base_unread - 1)
        self.assertEqual(len(self.good('/desk/api/notifications/list', filter='unread')['items']), base_unread - 1)
        self.assertTrue(self.good('/desk/api/notifications/flag', id=m.id)['flagged'])
        self.assertEqual(len(self.good('/desk/api/notifications/list', filter='flagged')['items']), 1)
        self.assertEqual(self.good('/desk/api/notifications/read')['unread'], 0)
        foreign = Notification.sudo().search([('user_id', '=', self.other.id), ('text', '=', 'Not for Priya')])
        self.bad('/desk/api/notifications/flag', id=foreign.id)
        self.assertFalse(foreign.flagged)

    def test_email_failure_retry_can_fix_recipient(self):
        failure = self.env['aixo.notification']._notify(
            self.agent, 'email_failure', 'Email to Lawrence failed', self.t1, failure_recipient='bad')
        self.signin(self.agent)
        data = self.good('/desk/api/notifications/list')
        self.assertEqual(len(data['failures']), 1)
        self.bad('/desk/api/notifications/retry', id=failure.id, email='not-an-email')
        self.good('/desk/api/notifications/retry', id=failure.id, email='fixed@example.org')
        self.assertEqual(self.partner.email, 'fixed@example.org')
        self.assertTrue(failure.is_read)

    def test_notification_is_pushed_on_the_bus(self):
        self.env['aixo.notification']._notify(self.agent, 'assign', 'Live one', self.t1)
        queued = self.env.cr.precommit.data.get('bus.bus.values', [])
        self.assertTrue(any('Live one' in v['message'] and 'aixo_desk/notification' in v['message'] for v in queued),
                        "the notification is queued on the bus for the user's partner")

    # ---------------------------------------------------------------- profile/prefs

    def test_profile_status_and_channels(self):
        self.signin(self.agent)
        self.assertEqual(self.good('/desk/api/profile/get')['availability'], 'online')
        data = self.good('/desk/api/profile/status', availability='away')
        self.assertEqual(data['availability'], 'away')
        self.assertEqual(self.agent.desk_availability, 'away')
        data = self.good('/desk/api/profile/status', channel='chat', state='offline')
        self.assertEqual(data['channels']['chat'], 'offline')
        self.bad('/desk/api/profile/status', availability='busy')
        self.bad('/desk/api/profile/status', channel='fax', state='online')

    def test_preferences_save_and_validate(self):
        self.signin(self.agent)
        prefs = self.good('/desk/api/prefs/save', values={'theme': 'red', 'appearance': 'night', 'font': 'poppins', 'size': 'xl', 'light_panel': False})
        self.assertEqual((prefs['theme'], prefs['appearance'], prefs['font'], prefs['size'], prefs['light_panel']), ('red', 'night', 'poppins', 'xl', False))
        self.assertEqual(self.agent.desk_theme, 'red')
        prefs = self.good('/desk/api/prefs/save', values={'toggles': {'acc0': True, 'bogus': True}})
        self.assertTrue(prefs['toggles']['acc0'])
        self.assertNotIn('bogus', prefs['toggles'])
        self.bad('/desk/api/prefs/save', values={'theme': 'pink'})
        page = self.url_open('/desk')
        self.assertIn('data-theme="red"', page.text)
        self.assertIn('data-appearance="night"', page.text)
        self.assertIn('data-font="poppins"', page.text)

    def test_customers_can_use_preferences_but_not_profile_routes(self):
        self.signin(self.customer)
        self.assertTrue(self.rpc('/desk/api/prefs/get')['ok'])
        self.assertEqual(self.rpc('/desk/api/profile/get')['code'], 'forbidden')
