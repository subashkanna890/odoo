import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


class CustomerCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        mk = lambda name, login, group, **kw: env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'email': login, 'password': 'Passw0rd!x',
            'group_ids': [(6, 0, [env.ref(group).id])], **kw})
        cls.company = env['res.partner'].create({'name': 'Cu Co', 'is_company': True, 'desk_plan': 'paid'})
        cls.other_company = env['res.partner'].create({'name': 'Other Co', 'is_company': True})
        cls.agent = mk('Cu Agent', 'cu_agent@example.com', 'aixo_desk.group_desk_agent')
        cls.me = mk('Mia Customer', 'cu_me@example.com', 'aixo_desk.group_desk_customer', parent_id=cls.company.id)
        cls.colleague = mk('Cal Colleague', 'cu_col@example.com', 'aixo_desk.group_desk_customer', parent_id=cls.company.id)
        cls.stranger = mk('Stan Stranger', 'cu_str@example.com', 'aixo_desk.group_desk_customer', parent_id=cls.other_company.id)
        Ticket = env['aixo.ticket']
        cls.t_open = Ticket.create({'name': 'My open', 'partner_id': cls.me.partner_id.id, 'owner_id': cls.agent.id,
                                    'description': '<p>Please help</p>'})
        cls.t_new = Ticket.create({'name': 'My unassigned', 'partner_id': cls.me.partner_id.id})
        cls.t_hold = Ticket.create({'name': 'My hold', 'partner_id': cls.me.partner_id.id, 'owner_id': cls.agent.id, 'state': 'on_hold'})
        cls.t_done = Ticket.create({'name': 'My done', 'partner_id': cls.me.partner_id.id, 'owner_id': cls.agent.id})
        cls.t_done.action_close('<p>Fixed it for you</p>')
        cls.t_col = Ticket.create({'name': 'Colleague ticket', 'partner_id': cls.colleague.partner_id.id})
        cls.t_str = Ticket.create({'name': 'Stranger ticket', 'partner_id': cls.stranger.partner_id.id})

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

    def csrf(self, path='/desk/my'):
        page = self.url_open(path).text
        return re.search(r'csrf(?:&#34;|")\s*:\s*(?:&#34;|")([^&"]+)', page).group(1)

    def csat_mails(self, ticket):
        return self.env['mail.mail'].sudo().search([('subject', 'ilike', f'Ticket #{ticket.number}'), ('email_to', '=', ticket.partner_id.email)])


@tagged('post_install', '-at_install')
class TestCustomerPortal(CustomerCase):

    def test_pages_by_role(self):
        self.signin(self.me)
        self.assertIn('aixo_desk.CustomerHome', self.url_open('/desk/my').text)
        self.assertIn('aixo_desk.CustomerTicket', self.url_open(f'/desk/my/ticket/{self.t_open.id}').text)
        self.assertIn('aixo_desk.CustomerProjects', self.url_open('/desk/my/projects').text)
        foreign = self.url_open(f'/desk/my/ticket/{self.t_str.id}', allow_redirects=False)
        self.assertTrue(foreign.headers['Location'].endswith('/desk/my'), "another company's ticket is not reachable")
        self.signin(self.agent)
        self.assertTrue(self.url_open('/desk/my', allow_redirects=False).headers['Location'].endswith('/desk'))
        self.opener.cookies.clear()
        self.assertEqual(self.url_open('/desk/my', allow_redirects=False).status_code, 303)

    def test_customer_cannot_reach_staff_pages_or_apis(self):
        self.signin(self.me)
        for path in ('/desk', '/desk/customers', '/desk/projects', '/desk/admin', '/desk/admin/reports'):
            self.assertTrue(self.url_open(path, allow_redirects=False).headers['Location'].endswith('/desk/my'), path)
        for route in ('ticket/list', 'customers/list', 'projects/list', 'notifications/list', 'admin/tickets', 'admin/reports'):
            self.assertEqual(self.rpc(f'/desk/api/{route}')['code'], 'forbidden', route)

    def test_home_lists_only_own_tickets_with_counts(self):
        self.signin(self.me)
        data = self.good('/desk/api/my/home')
        self.assertEqual({t['subject'] for t in data['tickets']}, {'My open', 'My unassigned', 'My hold', 'My done'})
        self.assertEqual(data['counts'], {'all': 4, 'open': 3, 'waiting': 1, 'resolved': 1})
        self.assertEqual((data['name'], data['company'], data['plan']), ('Mia Customer', 'Cu Co', 'paid'))
        self.assertEqual([v['label'] for v in data['views']], ['All my tickets', 'Open requests', 'Waiting for my reply', 'Resolved'])

    def test_views_search_and_status_labels(self):
        self.signin(self.me)
        rows = {t['subject']: t for t in self.good('/desk/api/my/home')['tickets']}
        self.assertEqual(rows['My open']['status'], 'In progress')
        self.assertEqual(rows['My unassigned']['status'], 'Open')
        self.assertEqual(rows['My unassigned']['agent'], 'Not yet assigned')
        self.assertEqual(rows['My hold']['status'], 'Waiting for you')
        self.assertEqual(rows['My done']['status'], 'Resolved')
        self.assertEqual(rows['My open']['agent'], 'Cu Agent', "the agent name is visible even though customers cannot read users")
        names = lambda **kw: {t['subject'] for t in self.good('/desk/api/my/home', **kw)['tickets']}
        self.assertEqual(names(view='waiting'), {'My hold'})
        self.assertEqual(names(view='resolved'), {'My done'})
        self.assertEqual(names(view='open'), {'My open', 'My unassigned', 'My hold'})
        self.assertEqual(names(search='unassigned'), {'My unassigned'})
        self.assertEqual(names(search='nothing-like-this'), set())

    def test_company_sharing_setting(self):
        self.signin(self.me)
        self.assertNotIn('Colleague ticket', {t['subject'] for t in self.good('/desk/api/my/home')['tickets']})
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.share_company_tickets', 'True')
        self.env.invalidate_all()
        subjects = {t['subject'] for t in self.good('/desk/api/my/home')['tickets']}
        self.assertIn('Colleague ticket', subjects)
        self.assertNotIn('Stranger ticket', subjects)

    def test_help_links(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.kb_url', 'https://kb.example.com')
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.support_email', 'help@example.com')
        self.signin(self.me)
        help_ = self.good('/desk/api/my/home')['help']
        self.assertEqual(help_['kb'], 'https://kb.example.com')
        self.assertEqual(help_['chat'], 'mailto:help@example.com')
        self.assertTrue(help_['chat_is_email'])

    def test_ticket_detail_hides_internal_content(self):
        self.t_open.message_post(body='<p>Public answer</p>', message_type='comment', subtype_xmlid='mail.mt_comment', author_id=self.agent.partner_id.id)
        self.t_open.message_post(body='<p>SECRET internal note</p>', message_type='comment', subtype_xmlid='mail.mt_note', author_id=self.agent.partner_id.id)
        self.t_open.write({'priority': 'urgent'})
        self.signin(self.me)
        data = self.good('/desk/api/my/ticket', id=self.t_open.id)
        bodies = ' '.join(m['body'] for m in data['messages'])
        self.assertIn('Public answer', bodies)
        self.assertNotIn('SECRET', bodies)
        self.assertEqual(len(data['messages']), 1, "tracking messages are not shown")
        self.assertEqual(data['messages'][0]['author']['name'], 'Cu Agent')
        self.assertFalse(data['messages'][0]['mine'])
        self.assertTrue(data['can_close'])
        self.assertIn('Please help', data['ticket']['description'])
        self.assertEqual(self.rpc('/desk/api/my/ticket', id=self.t_str.id)['code'], 'forbidden')

    def test_reply_posts_as_customer_and_notifies_agent(self):
        self.signin(self.me)
        data = self.good('/desk/api/my/reply', id=self.t_open.id, body='Thanks <b>a lot</b>')
        self.assertTrue(data['message']['mine'])
        self.assertIn('&lt;b&gt;', data['message']['body'], "input is escaped")
        message = self.t_open.message_ids.filtered(lambda m: m.message_type == 'comment')[0]
        self.assertEqual(message.author_id, self.me.partner_id)
        self.assertEqual(message.subtype_id, self.env.ref('mail.mt_comment'))
        note = self.env['aixo.notification'].sudo().search([('user_id', '=', self.agent.id), ('type', '=', 'reply'), ('ticket_id', '=', self.t_open.id)])
        self.assertEqual(len(note), 1)
        self.assertIn('Mia Customer', note.text)

    def test_reply_validation_and_isolation(self):
        self.signin(self.me)
        self.assertIn('first', self.bad('/desk/api/my/reply', id=self.t_open.id, body='  ')['error'])
        self.assertEqual(self.rpc('/desk/api/my/reply', id=self.t_str.id, body='hi')['code'], 'forbidden')
        self.assertFalse(self.t_str.message_ids.filtered(lambda m: m.message_type == 'comment'))

    def test_reply_resumes_a_waiting_ticket(self):
        self.signin(self.me)
        self.assertEqual(self.t_hold.state, 'on_hold')
        self.good('/desk/api/my/reply', id=self.t_hold.id, body='Here is the info')
        self.assertEqual(self.t_hold.state, 'open')
        self.assertFalse(self.t_hold.hold_since, "the SLA clock resumes")

    def test_reply_to_closed_ticket_reopens_within_window_only(self):
        self.signin(self.me)
        self.good('/desk/api/my/reply', id=self.t_done.id, body='Actually it is still broken')
        self.assertEqual(self.t_done.state, 'open')
        self.t_done.action_close('<p>again</p>')
        self.env.flush_all()
        self.env.cr.execute("UPDATE aixo_ticket SET closed_on = %s WHERE id = %s", (fields.Datetime.now() - timedelta(days=30), self.t_done.id))
        self.env.invalidate_all()
        error = self.bad('/desk/api/my/reply', id=self.t_done.id, body='Much later')['error']
        self.assertIn('raise a new request', error)
        self.assertEqual(self.t_done.state, 'closed')

    def test_close_reopen_and_window(self):
        self.signin(self.me)
        data = self.good('/desk/api/my/close', id=self.t_open.id)
        self.assertEqual(data['ticket']['status'], 'Resolved')
        self.assertIn('customer', self.t_open.resolution_summary)
        self.assertIn('already resolved', self.bad('/desk/api/my/close', id=self.t_open.id)['error'])
        self.good('/desk/api/my/reopen', id=self.t_open.id)
        self.assertEqual(self.t_open.state, 'open')
        self.good('/desk/api/my/close', id=self.t_open.id)
        self.env.cr.execute("UPDATE aixo_ticket SET closed_on = %s WHERE id = %s", (fields.Datetime.now() - timedelta(days=9), self.t_open.id))
        self.env.invalidate_all()
        self.assertIn('no longer be reopened', self.bad('/desk/api/my/reopen', id=self.t_open.id)['error'])
        self.assertFalse(self.good('/desk/api/my/ticket', id=self.t_open.id)['can_reopen'])

    def test_rating_from_the_portal(self):
        self.signin(self.me)
        self.assertIn('resolved', self.bad('/desk/api/my/rate', id=self.t_open.id, rating='good')['error'])
        self.assertIn('Choose', self.bad('/desk/api/my/rate', id=self.t_done.id, rating='great')['error'])
        self.good('/desk/api/my/rate', id=self.t_done.id, rating='okay', comment='Took a while')
        self.assertEqual((self.t_done.rating, self.t_done.rating_comment), ('okay', 'Took a while'))
        self.good('/desk/api/my/rate', id=self.t_done.id, rating='good')
        self.assertEqual(self.t_done.rating, 'good')
        self.assertEqual(self.t_done.partner_id.desk_happiness, 100, "ratings feed the happiness metric")

    def test_attachments(self):
        self.signin(self.me)
        token = self.csrf()
        upload = lambda ticket, name='a.txt', data=b'x': self.url_open(
            f'/desk/my/ticket/{ticket.id}/attach', data={'csrf_token': token}, files={'file': (name, data, 'text/plain')})
        response = upload(self.t_open)
        self.assertEqual(response.status_code, 200, response.text)
        attachment = response.json()['data']['attachments'][0]
        self.assertEqual(upload(self.t_open, 'bad.exe', b'MZ').status_code, 400)
        self.assertEqual(upload(self.t_str).status_code, 403)
        data = self.good('/desk/api/my/reply', id=self.t_open.id, body='See file', attachment_ids=[attachment['id']])
        self.assertEqual(data['message']['attachments'][0]['name'], 'a.txt')
        download = self.url_open(data['message']['attachments'][0]['url'])
        self.assertEqual((download.status_code, download.content), (200, b'x'))
        internal = self.env['ir.attachment'].create({'name': 'internal.txt', 'raw': b'secret', 'res_model': 'aixo.ticket', 'res_id': self.t_open.id})
        self.assertEqual(self.url_open(f'/desk/attachment/{internal.id}', allow_redirects=False).status_code, 404, "staff-only ticket files stay hidden")
        foreign = self.env['ir.attachment'].create({'name': 'f.txt', 'raw': b'1', 'res_model': 'aixo.ticket', 'res_id': self.t_hold.id})
        self.assertEqual(self.bad('/desk/api/my/reply', id=self.t_open.id, body='x', attachment_ids=[foreign.id])['error'], 'Invalid attachment.')

    def test_projects_are_own_company_and_read_only(self):
        mine = self.env['aixo.project'].create({'name': 'Cu Project', 'partner_id': self.company.id, 'state': 'in_progress'})
        self.env['aixo.project.task'].create([{'project_id': mine.id, 'name': 'T1', 'done': True}, {'project_id': mine.id, 'name': 'T2'}])
        self.env['aixo.project'].create({'name': 'Other Project', 'partner_id': self.other_company.id})
        self.signin(self.me)
        projects = self.good('/desk/api/my/projects')['projects']
        self.assertEqual([p['name'] for p in projects], ['Cu Project'])
        self.assertEqual((projects[0]['tasks_done'], projects[0]['tasks_total'], projects[0]['progress']), (1, 2, 50))
        for route, extra in (('projects/move', {'state': 'completed'}), ('projects/task', {'action': 'add', 'name': 'x'}), ('projects/star', {})):
            self.assertEqual(self.rpc(f'/desk/api/{route}', id=mine.id, **extra)['code'], 'forbidden', route)
        self.assertEqual(mine.state, 'in_progress')


@tagged('post_install', '-at_install')
class TestCsat(CustomerCase):

    def test_closing_queues_a_one_click_survey(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.csat_enabled', 'True')
        ticket = self.env['aixo.ticket'].create({'name': 'Survey me', 'partner_id': self.me.partner_id.id, 'owner_id': self.agent.id})
        self.assertFalse(self.csat_mails(ticket))
        ticket.action_close('<p>done</p>')
        mails = self.csat_mails(ticket)
        self.assertEqual(len(mails), 1)
        for score in ('good', 'okay', 'bad'):
            self.assertIn(f'/desk/csat/{ticket.access_token}/{score}', mails.body_html)

    def test_survey_respects_the_setting_and_rating(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.csat_enabled', 'False')
        off = self.env['aixo.ticket'].create({'name': 'No survey', 'partner_id': self.me.partner_id.id})
        off.action_close('<p>done</p>')
        self.assertFalse(self.csat_mails(off))
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.csat_enabled', 'True')
        rated = self.env['aixo.ticket'].create({'name': 'Already rated', 'partner_id': self.me.partner_id.id, 'rating': 'good'})
        rated.action_close('<p>done</p>')
        self.assertFalse(self.csat_mails(rated))

    def test_customer_closing_also_sends_the_survey(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.csat_enabled', 'True')
        self.signin(self.me)
        self.good('/desk/api/my/close', id=self.t_open.id)
        self.assertEqual(len(self.csat_mails(self.t_open)), 1)

    def test_public_link_records_the_rating(self):
        self.env['ir.config_parameter'].sudo().set_param('aixo_desk.csat_enabled', 'True')
        ticket = self.env['aixo.ticket'].create({'name': 'Rate me', 'partner_id': self.me.partner_id.id})
        ticket.action_close('<p>done</p>')
        page = self.url_open(f'/desk/csat/{ticket.access_token}/good')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Your rating', page.text)
        self.assertEqual(ticket.rating, 'good')
        again = self.url_open(f'/desk/csat/{ticket.access_token}/bad')
        self.assertIn('already rated', again.text)
        self.assertEqual(ticket.rating, 'good', "a second click on another link does not overwrite")

    def test_public_link_rejects_bad_input(self):
        ticket = self.env['aixo.ticket'].create({'name': 'Open one', 'partner_id': self.me.partner_id.id})
        self.assertEqual(self.url_open(f'/desk/csat/{ticket.access_token}/good').status_code, 200)
        self.assertFalse(ticket.rating, "an open ticket cannot be rated")
        self.assertEqual(self.url_open('/desk/csat/not-a-real-token/good').status_code, 404)
        ticket.action_close('<p>done</p>')
        self.assertEqual(self.url_open(f'/desk/csat/{ticket.access_token}/excellent').status_code, 404)
        self.assertFalse(ticket.rating)

    def test_changing_the_rating_needs_the_form(self):
        ticket = self.env['aixo.ticket'].create({'name': 'Change me', 'partner_id': self.me.partner_id.id})
        ticket.action_close('<p>done</p>')
        page = self.url_open(f'/desk/csat/{ticket.access_token}/okay')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        self.assertEqual(self.url_open(f'/desk/csat/{ticket.access_token}', data={'score': 'bad'}).status_code, 400, "csrf required")
        done = self.url_open(f'/desk/csat/{ticket.access_token}', data={'csrf_token': token, 'score': 'bad', 'comment': 'Slow'})
        self.assertEqual(done.status_code, 200)
        self.assertEqual((ticket.rating, ticket.rating_comment), ('bad', 'Slow'))

    def test_rating_is_visible_to_staff(self):
        ticket = self.env['aixo.ticket'].create({'name': 'Staff view', 'partner_id': self.me.partner_id.id, 'owner_id': self.agent.id})
        ticket.action_close('<p>done</p>')
        self.url_open(f'/desk/csat/{ticket.access_token}/good')
        self.signin(self.agent)
        self.assertEqual(self.good('/desk/api/ticket/get', id=ticket.id)['ticket']['rating'], 'good')
