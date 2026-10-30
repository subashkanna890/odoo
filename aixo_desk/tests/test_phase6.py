import re

from odoo.tests import HttpCase, tagged


class Phase6Case(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        mk = lambda name, login, group, **kw: env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'email': login, 'password': 'Passw0rd!x',
            'group_ids': [(6, 0, [env.ref(group).id])], **kw})
        cls.admin = mk('P6 Admin', 'p6_admin@example.com', 'aixo_desk.group_desk_admin')
        cls.agent = mk('P6 Agent', 'p6_agent@example.com', 'aixo_desk.group_desk_agent')
        cls.other = mk('P6 Other', 'p6_other@example.com', 'aixo_desk.group_desk_agent')
        cls.company = env['res.partner'].create({'name': 'P6 Company', 'is_company': True})
        cls.customer = mk('P6 Customer', 'p6_cust@example.com', 'aixo_desk.group_desk_customer', parent_id=cls.company.id)
        cls.contact_a = env['res.partner'].create({'name': 'Zed Mine', 'email': 'zed@example.org', 'parent_id': cls.company.id})
        cls.contact_b = env['res.partner'].create({'name': 'Yara Theirs', 'email': 'yara@example.org'})
        cls.contact_c = env['res.partner'].create({'name': 'Quiet Portal', 'email': 'quiet@example.org'})
        Ticket = env['aixo.ticket']
        cls.t_mine = Ticket.create({'name': 'Mine', 'partner_id': cls.contact_a.id, 'owner_id': cls.agent.id})
        cls.t_mine2 = Ticket.create({'name': 'Mine too', 'partner_id': cls.contact_a.id, 'owner_id': cls.agent.id})
        cls.t_theirs = Ticket.create({'name': 'Theirs', 'partner_id': cls.contact_b.id, 'owner_id': cls.other.id})
        cls.t_hidden = Ticket.create({'name': 'Hidden from agent', 'partner_id': cls.contact_a.id, 'owner_id': cls.other.id})
        cls.project = env['aixo.project'].create({
            'name': 'P6 Project', 'partner_id': cls.company.id, 'state': 'in_progress',
            'member_ids': [(6, 0, [cls.agent.id])]})
        cls.project_other = env['aixo.project'].create({
            'name': 'P6 Other project', 'state': 'planning', 'member_ids': [(6, 0, [cls.other.id])]})

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

    def csrf(self, path='/desk'):
        page = self.url_open(path).text
        return re.search(r'csrf(?:&#34;|")\s*:\s*(?:&#34;|")([^&"]+)', page).group(1)


@tagged('post_install', '-at_install')
class TestNewTicket(Phase6Case):

    def test_page_access_by_role(self):
        self.signin(self.admin)
        page = self.url_open('/desk/ticket/new')
        self.assertIn('aixo_desk.NewTicket', page.text)
        self.signin(self.agent)
        redirect = self.url_open('/desk/ticket/new', allow_redirects=False)
        self.assertEqual(redirect.status_code, 303)
        self.assertTrue(redirect.headers['Location'].endswith('/desk'), "employees have no New ticket")
        self.signin(self.customer)
        self.assertEqual(self.url_open('/desk/ticket/new', allow_redirects=False).status_code, 200)

    def test_options_differ_by_mode(self):
        self.signin(self.admin)
        admin = self.good('/desk/api/newticket/options')
        self.assertEqual(admin['mode'], 'admin')
        self.assertTrue({'products', 'projects', 'agents', 'states'} <= set(admin))
        self.assertTrue(any(t['name'] == 'Bug report' for t in admin['templates']))
        self.assertIn('Steps to reproduce', next(t for t in admin['templates'] if t['name'] == 'Bug report')['description'])
        self.signin(self.customer)
        customer = self.good('/desk/api/newticket/options')
        self.assertEqual(customer['mode'], 'customer')
        self.assertFalse({'products', 'projects', 'agents', 'states'} & set(customer), "internal fields are hidden")
        self.assertEqual(customer['contact']['name'], 'P6 Customer')

    def test_admin_creates_ticket_for_existing_contact(self):
        self.signin(self.admin)
        data = self.good('/desk/api/newticket/create', values={
            'contact_id': self.contact_a.id, 'subject': 'Printer broken', 'description': 'It <b>smokes</b>',
            'status': 'on_hold', 'owner_id': self.agent.id, 'priority': 'urgent', 'channel': 'phone',
            'classification': 'problem', 'project_id': self.project.id, 'due_date': '2030-05-01T09:00'})
        ticket = self.env['aixo.ticket'].browse(data['ticket']['id'])
        self.assertEqual((ticket.name, ticket.partner_id, ticket.state, ticket.owner_id, ticket.priority, ticket.channel),
                         ('Printer broken', self.contact_a, 'on_hold', self.agent, 'urgent', 'phone'))
        self.assertIn('&lt;b&gt;', ticket.description, "description is escaped")
        self.assertEqual(ticket.project_id, self.project)
        self.assertTrue(ticket.first_response_deadline, "SLA deadlines are computed")
        self.assertEqual(data['contact'], 'Zed Mine')

    def test_admin_creates_new_contact_and_company(self):
        self.signin(self.admin)
        data = self.good('/desk/api/newticket/create', values={
            'new_contact': {'name': 'Brand New', 'email': 'NEW@Example.org', 'phone': '123', 'account': 'Fresh Co'},
            'subject': 'Hello'})
        ticket = self.env['aixo.ticket'].browse(data['ticket']['id'])
        self.assertEqual(ticket.partner_id.name, 'Brand New')
        self.assertEqual(ticket.partner_id.email, 'new@example.org')
        self.assertEqual(ticket.partner_id.parent_id.name, 'Fresh Co')
        self.good('/desk/api/newticket/create', values={'new_contact': {'name': 'Second', 'account': 'fresh co'}, 'subject': 'Again'})
        self.assertEqual(self.env['res.partner'].search_count([('name', '=ilike', 'Fresh Co')]), 1, "companies are reused")

    def test_required_fields_and_validation(self):
        self.signin(self.admin)
        self.assertIn('subject', self.bad('/desk/api/newticket/create', values={'contact_id': self.contact_a.id, 'subject': '  '})['error'])
        self.assertIn('contact', self.bad('/desk/api/newticket/create', values={'subject': 'x'})['error'])
        self.assertIn('valid email', self.bad('/desk/api/newticket/create', values={'new_contact': {'name': 'A', 'email': 'bad'}, 'subject': 'x'})['error'])
        self.assertIn('status', self.bad('/desk/api/newticket/create', values={'contact_id': self.contact_a.id, 'subject': 'x', 'status': 'closed'})['error'])
        self.assertIn('priority', self.bad('/desk/api/newticket/create', values={'contact_id': self.contact_a.id, 'subject': 'x', 'priority': 'nope'})['error'])
        self.assertIn('employees', self.bad('/desk/api/newticket/create', values={
            'contact_id': self.contact_a.id, 'subject': 'x', 'owner_id': self.customer.id})['error'])

    def test_template_default_is_applied_on_create(self):
        self.signin(self.admin)
        template = self.env.ref('aixo_desk.template_bug')
        data = self.good('/desk/api/newticket/create', values={
            'contact_id': self.contact_a.id, 'subject': 'Bug: login', 'template_id': template.id})
        ticket = self.env['aixo.ticket'].browse(data['ticket']['id'])
        self.assertEqual(ticket.priority, 'high')
        self.assertEqual(ticket.template_id, template)

    def test_contact_search_is_admin_only(self):
        self.signin(self.admin)
        found = self.good('/desk/api/contact/search', q='zed')['contacts']
        self.assertEqual([c['name'] for c in found], ['Zed Mine'])
        self.assertEqual(found[0]['open'], 3)
        self.assertEqual(self.good('/desk/api/contact/search', q='')['contacts'], [])
        self.signin(self.agent)
        self.assertEqual(self.rpc('/desk/api/contact/search', q='zed')['code'], 'forbidden')
        self.signin(self.customer)
        self.assertEqual(self.rpc('/desk/api/contact/search', q='zed')['code'], 'forbidden')

    def test_draft_attachments_are_claimed_by_the_new_ticket(self):
        self.signin(self.admin)
        token = self.csrf('/desk/ticket/new')
        upload = self.url_open('/desk/ticket/attach-draft', data={'csrf_token': token}, files={'file': ('a.txt', b'data', 'text/plain')})
        self.assertEqual(upload.status_code, 200, upload.text)
        attachment = upload.json()['data']['attachments'][0]
        data = self.good('/desk/api/newticket/create', values={
            'contact_id': self.contact_a.id, 'subject': 'With file', 'attachment_ids': [attachment['id']]})
        record = self.env['ir.attachment'].browse(attachment['id'])
        self.assertEqual((record.res_model, record.res_id), ('aixo.ticket', data['ticket']['id']))
        self.assertEqual(self.url_open('/desk/ticket/attach-draft', data={'csrf_token': token}, files={'file': ('x.exe', b'MZ', 'text/plain')}).status_code, 400)
        again = self.bad('/desk/api/newticket/create', values={
            'contact_id': self.contact_a.id, 'subject': 'Steal', 'attachment_ids': [attachment['id']]})
        self.assertEqual(again['error'], 'Invalid attachment.', "an already attached file cannot be reused")

    def test_customer_raises_own_ticket_only(self):
        self.signin(self.customer)
        data = self.good('/desk/api/newticket/create', values={
            'subject': 'Need help', 'description': 'Please', 'priority': 'high',
            'contact_id': self.contact_b.id, 'owner_id': self.admin.id, 'status': 'escalated',
            'channel': 'phone', 'project_id': self.project.id})
        ticket = self.env['aixo.ticket'].browse(data['ticket']['id'])
        self.assertEqual(ticket.partner_id, self.customer.partner_id, "contact is forced to themselves")
        self.assertEqual((ticket.state, ticket.channel), ('open', 'web'), "internal fields are ignored")
        self.assertFalse(ticket.project_id)
        self.assertNotEqual(ticket.owner_id, self.admin)
        self.assertTrue(ticket.first_response_deadline, "portal users still get SLA deadlines")
        self.assertEqual(ticket.priority, 'high')

    def test_customer_cannot_use_staff_routes(self):
        self.signin(self.customer)
        self.assertEqual(self.rpc('/desk/api/customers/list')['code'], 'forbidden')
        self.assertEqual(self.rpc('/desk/api/projects/list')['code'], 'forbidden')


@tagged('post_install', '-at_install')
class TestCustomers(Phase6Case):

    def test_pages(self):
        self.signin(self.agent)
        self.assertIn('aixo_desk.CustomerList', self.url_open('/desk/customers').text)
        self.assertIn('aixo_desk.CustomerDetail', self.url_open(f'/desk/customer/{self.contact_a.id}').text)
        redirect = self.url_open(f'/desk/customer/{self.contact_b.id}', allow_redirects=False)
        self.assertTrue(redirect.headers['Location'].endswith('/desk/customers'), "not linked to this agent's tickets")
        self.signin(self.customer)
        self.assertTrue(self.url_open('/desk/customers', allow_redirects=False).headers['Location'].endswith('/desk/my'))

    def test_agent_sees_only_contacts_on_their_tickets(self):
        self.signin(self.agent)
        names = {c['name'] for c in self.good('/desk/api/customers/list')['customers']}
        self.assertIn('Zed Mine', names)
        self.assertNotIn('Yara Theirs', names)
        self.assertNotIn('Quiet Portal', names)

    def test_admin_sees_all_customers_including_portal_users(self):
        self.signin(self.admin)
        names = {c['name'] for c in self.good('/desk/api/customers/list')['customers']}
        self.assertTrue({'Zed Mine', 'Yara Theirs', 'P6 Customer'} <= names)
        self.assertNotIn('Quiet Portal', names, "a plain contact without tickets or login is not a customer")

    def test_list_stats_are_scoped_to_visible_tickets(self):
        self.signin(self.agent)
        zed = next(c for c in self.good('/desk/api/customers/list')['customers'] if c['name'] == 'Zed Mine')
        self.assertEqual(zed['open'], 2, "the agent's 2 tickets, not the hidden third one")
        self.signin(self.admin)
        zed = next(c for c in self.good('/desk/api/customers/list')['customers'] if c['name'] == 'Zed Mine')
        self.assertEqual(zed['open'], 3)

    def test_views_letters_and_search(self):
        self.contact_a.desk_owner_id = self.agent
        self.signin(self.agent)
        data = self.good('/desk/api/customers/list')
        counts = {v['key']: v['count'] for v in data['views']}
        self.assertEqual(counts['all'], 1)
        self.assertEqual(counts['mine'], 1)
        self.assertEqual(counts['open'], 1)
        self.assertEqual(counts['recent'], 1)
        self.assertEqual(self.good('/desk/api/customers/list', view='paid')['total'], 0)
        self.assertEqual(self.good('/desk/api/customers/list', letter='Z')['total'], 1)
        letter = self.good('/desk/api/customers/list', letter='Q')
        self.assertEqual(letter['total'], 0)
        self.assertEqual(self.good('/desk/api/customers/list', search='zed')['total'], 1)
        self.assertEqual(self.good('/desk/api/customers/list', search='nobody-here')['total'], 0)
        self.assertEqual(data['letters'], ['Z'])
        self.company.desk_plan = 'paid'
        self.assertEqual(self.good('/desk/api/customers/list', view='paid')['total'], 1, "plan comes from the company")

    def test_detail_payload_and_access(self):
        self.signin(self.agent)
        data = self.good('/desk/api/customers/get', id=self.contact_a.id)
        self.assertEqual(data['name'], 'Zed Mine')
        self.assertEqual(data['stats']['all'], 2)
        self.assertEqual({t['subject'] for t in data['tickets']}, {'Mine', 'Mine too'})
        self.assertEqual(data['props']['account'], 'P6 Company')
        self.assertFalse(data['can_create_ticket'], "employees cannot raise tickets")
        self.assertEqual(self.rpc('/desk/api/customers/get', id=self.contact_b.id)['code'], 'forbidden')
        self.signin(self.admin)
        self.assertTrue(self.good('/desk/api/customers/get', id=self.contact_a.id)['can_create_ticket'])

    def test_inline_edit_logs_history_and_validates(self):
        self.signin(self.agent)
        self.good('/desk/api/customers/update', id=self.contact_a.id, values={'phone': '+91 1111', 'city': 'Chennai', 'email': 'ZED@Example.org'})
        self.assertEqual((self.contact_a.phone, self.contact_a.city, self.contact_a.email), ('+91 1111', 'Chennai', 'zed@example.org'))
        history = self.good('/desk/api/customers/get', id=self.contact_a.id)['history']
        self.assertTrue(any('Phone changed' in h['text'] and '+91 1111' in h['text'] for h in history))
        self.assertIn('valid email', self.bad('/desk/api/customers/update', id=self.contact_a.id, values={'email': 'nope'})['error'])
        self.assertIn('cannot be edited', self.bad('/desk/api/customers/update', id=self.contact_a.id, values={'name': 'Hack'})['error'])
        self.assertEqual(self.contact_a.name, 'Zed Mine')
        self.assertEqual(self.rpc('/desk/api/customers/update', id=self.contact_b.id, values={'city': 'X'})['code'], 'forbidden')
        self.assertIn('Unknown language', self.bad('/desk/api/customers/update', id=self.contact_a.id, values={'lang': 'xx_XX'})['error'])

    def test_admin_only_fields(self):
        self.signin(self.agent)
        for values in ({'desk_plan': 'paid'}, {'account': 'New Corp'}, {'desk_owner_id': self.agent.id}):
            self.assertEqual(self.rpc('/desk/api/customers/update', id=self.contact_a.id, values=values)['code'], 'forbidden', values)
        self.signin(self.admin)
        self.good('/desk/api/customers/update', id=self.contact_a.id, values={'desk_plan': 'paid', 'desk_owner_id': self.agent.id, 'account': 'New Corp'})
        self.assertEqual(self.contact_a.parent_id.name, 'New Corp')
        self.assertEqual(self.contact_a.commercial_partner_id.desk_plan, 'paid')
        self.assertEqual(self.contact_a.desk_owner_id, self.agent)
        self.assertIn('plan', self.bad('/desk/api/customers/update', id=self.contact_a.id, values={'desk_plan': 'gold'})['error'].lower())

    def test_customer_tags(self):
        self.signin(self.agent)
        tags = self.good('/desk/api/customers/tag', id=self.contact_a.id, add='VIP-p6')['tags']
        self.assertEqual([t['name'] for t in tags], ['VIP-p6'])
        self.good('/desk/api/customers/tag', id=self.contact_a.id, add='vip-P6')
        self.assertEqual(self.env['res.partner.category'].search_count([('name', '=ilike', 'vip-p6')]), 1)
        self.assertEqual(self.good('/desk/api/customers/tag', id=self.contact_a.id, remove=tags[0]['id'])['tags'], [])
        self.assertEqual(self.rpc('/desk/api/customers/tag', id=self.contact_b.id, add='x')['code'], 'forbidden')


@tagged('post_install', '-at_install')
class TestProjects(Phase6Case):

    def test_pages(self):
        self.signin(self.agent)
        self.assertIn('aixo_desk.ProjectList', self.url_open('/desk/projects').text)
        self.assertIn('aixo_desk.ProjectDetail', self.url_open(f'/desk/project/{self.project.id}').text)
        redirect = self.url_open(f'/desk/project/{self.project_other.id}', allow_redirects=False)
        self.assertTrue(redirect.headers['Location'].endswith('/desk/projects'))

    def test_list_scope_views_and_kpis(self):
        self.signin(self.agent)
        data = self.good('/desk/api/projects/list')
        self.assertEqual({p['name'] for p in data['projects']}, {'P6 Project'}, "only projects the agent belongs to")
        counts = {v['key']: v['count'] for v in data['views']}
        self.assertEqual((counts['all'], counts['mine'], counts['active'], counts['hold'], counts['done']), (1, 1, 1, 0, 0))
        self.assertEqual(data['kpis']['active'], 1)
        self.assertEqual(self.good('/desk/api/projects/list', view='hold')['projects'], [])
        self.signin(self.admin)
        names = {p['name'] for p in self.good('/desk/api/projects/list')['projects']}
        self.assertTrue({'P6 Project', 'P6 Other project'} <= names)
        self.assertTrue(self.good('/desk/api/projects/list')['can_create'])

    def test_project_row_progress_and_members(self):
        self.env['aixo.project.task'].create([{'project_id': self.project.id, 'name': 'a', 'done': True},
                                              {'project_id': self.project.id, 'name': 'b'}])
        self.env['aixo.ticket'].create({'name': 'Linked', 'partner_id': self.contact_a.id, 'owner_id': self.agent.id, 'project_id': self.project.id})
        self.signin(self.agent)
        row = self.good('/desk/api/projects/list')['projects'][0]
        self.assertEqual((row['tasks_done'], row['tasks_total'], row['pct']), (1, 2, 50))
        self.assertEqual(row['tickets'], 1)
        self.assertEqual([m['name'] for m in row['members']], ['P6 Agent'])
        self.assertEqual(self.good('/desk/api/projects/list')['kpis']['open_tickets'], 1)

    def test_board_move_changes_status(self):
        self.signin(self.agent)
        data = self.good('/desk/api/projects/move', id=self.project.id, state='on_hold')
        self.assertEqual(data['project']['state'], 'on_hold')
        self.assertEqual(self.project.state, 'on_hold')
        self.assertIn('status', self.bad('/desk/api/projects/move', id=self.project.id, state='weird')['error'].lower())
        self.assertEqual(self.rpc('/desk/api/projects/move', id=self.project_other.id, state='completed')['code'], 'forbidden')
        self.assertEqual(self.project_other.state, 'planning')

    def test_create_is_admin_only_and_validated(self):
        self.signin(self.agent)
        self.assertEqual(self.rpc('/desk/api/projects/create', values={'name': 'x'})['code'], 'forbidden')
        self.signin(self.admin)
        self.assertIn('name', self.bad('/desk/api/projects/create', values={'name': ' '})['error'])
        self.assertIn('due date', self.bad('/desk/api/projects/create', values={'name': 'x', 'date_start': '2026-05-02', 'date_due': '2026-05-01'})['error'])
        data = self.good('/desk/api/projects/create', values={
            'name': 'Fresh', 'partner_id': self.company.id, 'date_start': '2026-05-01', 'date_due': '2026-06-01',
            'member_ids': [self.agent.id, self.customer.id]})
        project = self.env['aixo.project'].browse(data['project']['id'])
        self.assertRegex(project.code, r'^PRJ-\d+$')
        self.assertEqual(project.member_ids, self.agent, "customers cannot be members")

    def test_detail_tasks_milestones_and_star(self):
        self.signin(self.agent)
        self.assertEqual(self.good('/desk/api/projects/get', id=self.project.id)['name'], 'P6 Project')
        tasks = self.good('/desk/api/projects/task', id=self.project.id, action='add', name='Write tests')['tasks']
        self.assertEqual(tasks[0]['name'], 'Write tests')
        self.assertIn('task name', self.bad('/desk/api/projects/task', id=self.project.id, action='add', name=' ')['error'])
        done = self.good('/desk/api/projects/task', id=self.project.id, action='toggle', task_id=tasks[0]['id'])
        self.assertEqual(done['project']['pct'], 100)
        self.good('/desk/api/projects/task', id=self.project.id, action='delete', task_id=tasks[0]['id'])
        self.assertFalse(self.project.task_ids)
        foreign_task = self.env['aixo.project.task'].create({'project_id': self.project_other.id, 'name': 'not mine'})
        self.bad('/desk/api/projects/task', id=self.project.id, action='toggle', task_id=foreign_task.id)
        self.assertFalse(foreign_task.done)
        milestones = self.good('/desk/api/projects/milestone', id=self.project.id, action='add', name='Go live', date='2030-01-01')['milestones']
        self.assertEqual(milestones[0]['name'], 'Go live')
        milestones = self.good('/desk/api/projects/milestone', id=self.project.id, action='toggle', milestone_id=milestones[0]['id'])['milestones']
        self.assertTrue(milestones[0]['reached'])
        self.assertTrue(self.good('/desk/api/projects/star', id=self.project.id)['starred'])
        self.assertFalse(self.good('/desk/api/projects/star', id=self.project.id)['starred'])
        self.assertEqual(self.rpc('/desk/api/projects/task', id=self.project_other.id, action='add', name='x')['code'], 'forbidden')

    def test_update_permissions(self):
        self.signin(self.agent)
        self.good('/desk/api/projects/update', id=self.project.id, values={'state': 'completed'})
        self.assertEqual(self.rpc('/desk/api/projects/update', id=self.project.id, values={'name': 'Renamed'})['code'], 'forbidden')
        self.signin(self.admin)
        self.good('/desk/api/projects/update', id=self.project.id, values={'name': 'Renamed', 'date_start': '2026-01-01', 'date_due': '2026-02-01', 'member_ids': [self.agent.id, self.other.id]})
        self.assertEqual(self.project.name, 'Renamed')
        self.assertEqual(len(self.project.member_ids), 2)
        self.assertIn('due date', self.bad('/desk/api/projects/update', id=self.project.id, values={'date_due': '2025-01-01'})['error'])

    def test_other_sections(self):
        self.env['aixo.project.milestone'].create({'project_id': self.project.id, 'name': 'M1', 'date': '2030-01-01'})
        self.env['aixo.project.task'].create({'project_id': self.project.id, 'name': 'T1'})
        self.signin(self.agent)
        self.assertEqual([m['name'] for m in self.good('/desk/api/projects/list', section='milestones')['milestones']], ['M1'])
        self.assertEqual([t['name'] for t in self.good('/desk/api/projects/list', section='tasks')['tasks']], ['T1'])
        self.assertIn('timesheets', self.good('/desk/api/projects/list', section='timesheets'))
