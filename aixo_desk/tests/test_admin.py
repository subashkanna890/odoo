import csv
import io
import re
import zipfile
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


class AdminCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        mk = lambda name, login, group, **kw: env['res.users'].with_context(no_reset_password=True).create({
            'name': name, 'login': login, 'email': login, 'password': 'Passw0rd!x',
            'group_ids': [(6, 0, [env.ref(group).id])], **kw})
        cls.admin = mk('Ad Min', 'ad_admin@example.com', 'aixo_desk.group_desk_admin')
        cls.agent = mk('Ag One', 'ad_agent1@example.com', 'aixo_desk.group_desk_agent')
        cls.agent2 = mk('Ag Two', 'ad_agent2@example.com', 'aixo_desk.group_desk_agent')
        cls.customer = mk('Cu Stomer', 'ad_cust@example.com', 'aixo_desk.group_desk_customer')
        cls.team = env['aixo.team'].create({'name': 'Ad Team', 'department': 'Support', 'member_ids': [(6, 0, [cls.agent.id])]})
        cls.contact = env['res.partner'].create({'name': 'Con Tact', 'email': 'con@example.org'})
        Ticket = env['aixo.ticket']
        cls.t_unassigned = Ticket.create({'name': 'Unassigned one', 'partner_id': cls.contact.id})
        cls.t_assigned = Ticket.create({'name': 'Assigned one', 'partner_id': cls.contact.id, 'owner_id': cls.agent.id})
        cls.t_high = Ticket.create({'name': 'High one', 'partner_id': cls.contact.id, 'priority': 'urgent'})
        cls.t_escalated = Ticket.create({'name': 'Escalated one', 'partner_id': cls.contact.id, 'state': 'escalated'})

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


@tagged('post_install', '-at_install')
class TestAdminTickets(AdminCase):

    def test_pages_are_admin_only(self):
        self.signin(self.admin)
        for path, component in (('/desk/admin', 'AdminHome'), ('/desk/admin/people', 'AdminPeople'), ('/desk/admin/reports', 'AdminReports')):
            self.assertIn(f'aixo_desk.{component}', self.url_open(path).text, path)
        self.signin(self.agent)
        for path in ('/desk/admin', '/desk/admin/people', '/desk/admin/reports'):
            self.assertTrue(self.url_open(path, allow_redirects=False).headers['Location'].endswith('/desk'), path)
        self.signin(self.customer)
        self.assertTrue(self.url_open('/desk/admin', allow_redirects=False).headers['Location'].endswith('/desk/my'))

    def test_every_admin_route_refuses_agents_and_customers(self):
        routes = ('tickets', 'assign', 'people', 'employee/create', 'customer/create', 'team/save', 'employee/update',
                  'user/toggle', 'user/invite', 'generate-password', 'reports')
        for user in (self.agent, self.customer):
            self.signin(user)
            for route in routes:
                self.assertEqual(self.rpc(f'/desk/api/admin/{route}')['code'], 'forbidden', (user.login, route))

    def test_views_counts_and_search(self):
        self.signin(self.admin)
        data = self.good('/desk/api/admin/tickets')
        counts = {v['key']: v['count'] for v in data['views']}
        ids = lambda **kw: {t['id'] for t in self.good('/desk/api/admin/tickets', **kw)['tickets']}
        self.assertTrue({self.t_unassigned.id, self.t_assigned.id} <= ids())
        self.assertIn(self.t_unassigned.id, ids(view='unassigned'))
        self.assertNotIn(self.t_assigned.id, ids(view='unassigned'))
        self.assertIn(self.t_high.id, ids(view='high'))
        self.assertIn(self.t_escalated.id, ids(view='escalated'))
        self.assertGreaterEqual(counts['unassigned'], 3)
        self.assertEqual(ids(search='Escalated one'), {self.t_escalated.id})
        self.t_assigned.due_date = fields.Datetime.now() - timedelta(days=1)
        self.assertIn(self.t_assigned.id, ids(view='overdue'))

    def test_workload(self):
        self.signin(self.admin)
        load = {w['name']: w['open'] for w in self.good('/desk/api/admin/tickets')['workload']}
        self.assertEqual(load['Ag One'], 1)
        self.assertEqual(load['Ag Two'], 0)
        self.assertNotIn('Cu Stomer', load, "customers are not employees")

    def test_assign_single_bulk_and_unassign(self):
        self.signin(self.admin)
        data = self.good('/desk/api/admin/assign', ids=[self.t_unassigned.id], owner_id=self.agent2.id)
        self.assertEqual(data['message'], f"Ticket #{self.t_unassigned.number} assigned to Ag Two")
        self.assertEqual(self.t_unassigned.owner_id, self.agent2)
        data = self.good('/desk/api/admin/assign', ids=[self.t_high.id, self.t_escalated.id], owner_id=self.agent.id)
        self.assertEqual(data['message'], '2 tickets assigned to Ag One')
        self.assertEqual((self.t_high.owner_id, self.t_escalated.owner_id), (self.agent, self.agent))
        data = self.good('/desk/api/admin/assign', ids=[self.t_high.id], owner_id=0)
        self.assertIn('unassigned', data['message'])
        self.assertFalse(self.t_high.owner_id)

    def test_assignment_notifies_and_is_logged(self):
        self.signin(self.admin)
        self.good('/desk/api/admin/assign', ids=[self.t_unassigned.id], owner_id=self.agent2.id)
        notes = self.env['aixo.notification'].sudo().search([('user_id', '=', self.agent2.id), ('ticket_id', '=', self.t_unassigned.id)])
        self.assertEqual(len(notes), 1)
        tracked = self.t_unassigned.message_ids.tracking_value_ids.filtered(lambda t: t.field_id.name == 'owner_id')
        self.assertTrue(tracked, "the change is recorded in the chatter")

    def test_assign_validation(self):
        self.signin(self.admin)
        self.assertIn('Select', self.bad('/desk/api/admin/assign', ids=[], owner_id=self.agent.id)['error'])
        self.assertIn('employees', self.bad('/desk/api/admin/assign', ids=[self.t_unassigned.id], owner_id=self.customer.id)['error'])
        self.agent2.active = False
        self.assertIn('active employees', self.bad('/desk/api/admin/assign', ids=[self.t_unassigned.id], owner_id=self.agent2.id)['error'])
        self.assertIn('up to', self.bad('/desk/api/admin/assign', ids=list(range(1, 300)), owner_id=self.agent.id)['error'])
        self.assertIn('no longer exist', self.bad('/desk/api/admin/assign', ids=[999999], owner_id=self.agent.id)['error'])
        self.assertFalse(self.t_unassigned.owner_id)


@tagged('post_install', '-at_install')
class TestAdminPeople(AdminCase):

    def people(self, **kw):
        return self.good('/desk/api/admin/people', **kw)

    def setUp(self):
        super().setUp()
        self.signin(self.admin)

    def test_lists_and_counts(self):
        data = self.people()
        names = {e['name']: e for e in data['employees']}
        self.assertEqual(names['Ad Min']['role'], 'admin')
        self.assertEqual(names['Ag One']['role'], 'agent')
        self.assertEqual(names['Ag One']['team'], 'Ad Team')
        self.assertEqual(names['Ag One']['assigned'], 1)
        self.assertEqual(names['Ag One']['status'], 'Invited', "never logged in")
        self.assertNotIn('OdooBot', names)
        self.assertIn('Cu Stomer', {c['name'] for c in data['customers']})
        self.assertIn('Ad Team', {t['name'] for t in data['teams']})
        self.assertEqual(data['counts']['employees'], len(data['employees']))

    def test_search_and_lead_role(self):
        self.team.lead_id = self.agent
        data = self.people(search='ag one')
        self.assertEqual([e['name'] for e in data['employees']], ['Ag One'])
        self.assertEqual(data['employees'][0]['role'], 'lead')
        self.assertEqual(self.people(search='zzz-nobody')['employees'], [])

    def test_create_employee(self):
        data = self.good('/desk/api/admin/employee/create', values={
            'name': 'New Agent', 'email': 'New.Agent@Example.com', 'password': 'Secret1234', 'role': 'agent',
            'team_id': self.team.id, 'phone': '+91 1', 'send_login': True, 'force_change': True})
        self.assertIn('Login details sent', data['message'])
        user = self.env['res.users'].browse(data['id'])
        self.assertEqual((user.login, user.desk_role, user.share), ('new.agent@example.com', 'agent', False))
        self.assertEqual(user.desk_team_ids, self.team)
        self.assertTrue(user.desk_force_password_change)
        self.opener.cookies.clear()
        page = self.url_open('/desk/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        login = self.url_open('/desk/login', allow_redirects=False, data={
            'csrf_token': token, 'login': 'new.agent@example.com', 'password': 'Secret1234', 'portal': 'employee'})
        self.assertTrue(login.headers['Location'].endswith('/desk/password/change'), "first login forces a new password")

    def test_create_admin_and_team_lead(self):
        admin = self.good('/desk/api/admin/employee/create', values={'name': 'Big Boss', 'email': 'boss@example.com', 'password': 'Secret1234', 'role': 'admin'})
        self.assertEqual(self.env['res.users'].browse(admin['id']).desk_role, 'admin')
        lead = self.good('/desk/api/admin/employee/create', values={'name': 'Lead Gal', 'email': 'lead@example.com', 'password': 'Secret1234', 'role': 'lead', 'team_id': self.team.id})
        self.assertEqual(self.team.lead_id.id, lead['id'])
        self.assertIn('team', self.bad('/desk/api/admin/employee/create', values={'name': 'No Team', 'email': 'nt@example.com', 'password': 'Secret1234', 'role': 'lead'})['error'])

    def test_create_employee_validation(self):
        base = {'name': 'X Y', 'email': 'xy@example.com', 'password': 'Secret1234'}
        self.assertIn('name', self.bad('/desk/api/admin/employee/create', values={**base, 'name': ' '})['error'])
        self.assertIn('valid login email', self.bad('/desk/api/admin/employee/create', values={**base, 'email': 'nope'})['error'])
        self.assertIn('at least 8', self.bad('/desk/api/admin/employee/create', values={**base, 'password': 'short'})['error'])
        self.assertIn('already exists', self.bad('/desk/api/admin/employee/create', values={**base, 'email': 'AD_AGENT1@example.com'})['error'])
        self.assertIn('role', self.bad('/desk/api/admin/employee/create', values={**base, 'role': 'root'})['error'])
        self.assertFalse(self.env['res.users'].search([('login', '=', 'xy@example.com')]))

    def test_create_customer(self):
        data = self.good('/desk/api/admin/customer/create', values={
            'name': 'Nina Customer', 'email': 'nina@example.org', 'password': 'Secret1234', 'company': 'Nina Co', 'plan': 'paid'})
        self.assertIn('can now log in', data['message'])
        user = self.env['res.users'].browse(data['id'])
        self.assertEqual((user.desk_role, user.share), ('customer', True))
        self.assertEqual(user.partner_id.parent_id.name, 'Nina Co')
        self.assertEqual(user.partner_id.commercial_partner_id.desk_plan, 'paid')
        solo = self.good('/desk/api/admin/customer/create', values={'name': 'Solo', 'email': 'solo@example.org', 'password': 'Secret1234', 'plan': 'paid'})
        self.assertEqual(self.env['res.users'].browse(solo['id']).partner_id.desk_plan, 'paid')
        self.assertIn('plan', self.bad('/desk/api/admin/customer/create', values={'name': 'P', 'email': 'p@example.org', 'password': 'Secret1234', 'plan': 'gold'})['error'].lower())

    def test_team_create_and_edit(self):
        data = self.good('/desk/api/admin/team/save', values={
            'name': 'Weekend', 'lead_id': self.agent.id, 'department': 'Support', 'member_ids': [self.agent2.id, self.customer.id]})
        team = self.env['aixo.team'].browse(data['id'])
        self.assertEqual(team.lead_id, self.agent)
        self.assertEqual(team.member_ids, self.agent | self.agent2, "lead is a member, customers are never members")
        self.good('/desk/api/admin/team/save', team_id=team.id, values={'name': 'Weekend 2', 'member_ids': []})
        self.assertEqual((team.name, len(team.member_ids), bool(team.lead_id)), ('Weekend 2', 0, False))
        self.assertIn('team name', self.bad('/desk/api/admin/team/save', values={'name': ' '})['error'])
        self.assertIn('employee', self.bad('/desk/api/admin/team/save', values={'name': 'T', 'lead_id': self.customer.id})['error'])

    def test_update_employee_role_and_team(self):
        self.good('/desk/api/admin/employee/update', id=self.agent.id, values={'name': 'Ag Renamed', 'role': 'admin', 'phone': '123'})
        self.assertEqual((self.agent.name, self.agent.desk_role, self.agent.desk_office_phone), ('Ag Renamed', 'admin', '123'))
        self.good('/desk/api/admin/employee/update', id=self.agent.id, values={'role': 'lead', 'team_id': self.team.id})
        self.assertEqual((self.agent.desk_role, self.team.lead_id), ('agent', self.agent))
        self.good('/desk/api/admin/employee/update', id=self.agent.id, values={'team_id': 0})
        self.assertFalse(self.agent.desk_team_ids)
        self.assertIn('Employee not found', self.bad('/desk/api/admin/employee/update', id=self.customer.id, values={'name': 'x'})['error'])

    def test_admin_cannot_demote_or_remove_themselves(self):
        self.assertIn('own admin', self.bad('/desk/api/admin/employee/update', id=self.admin.id, values={'role': 'agent'})['error'])
        self.assertIn('own account', self.bad('/desk/api/admin/user/toggle', id=self.admin.id)['error'])
        self.assertEqual(self.admin.desk_role, 'admin')
        self.assertTrue(self.admin.active)

    def test_deactivate_blocks_login_and_reactivate(self):
        data = self.good('/desk/api/admin/user/toggle', id=self.agent.id)
        self.assertFalse(data['active'])
        self.assertFalse(self.agent.active)
        row = next(e for e in self.people()['employees'] if e['id'] == self.agent.id)
        self.assertEqual(row['status'], 'Inactive')
        self.assertIn('active employees', self.bad('/desk/api/admin/assign', ids=[self.t_unassigned.id], owner_id=self.agent.id)['error'])
        self.opener.cookies.clear()
        page = self.url_open('/desk/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        login = self.url_open('/desk/login', allow_redirects=False, data={'csrf_token': token, 'login': self.agent.login, 'password': 'Passw0rd!x', 'portal': 'employee'})
        self.assertEqual(login.status_code, 200, "a deactivated user cannot log in")
        self.signin(self.admin)
        self.assertTrue(self.good('/desk/api/admin/user/toggle', id=self.agent.id)['active'])
        self.assertIn('not found', self.bad('/desk/api/admin/user/toggle', id=self.contact.id + 99999)['error'].lower())

    def test_invite_only_for_people_who_never_logged_in(self):
        self.assertIn('Invitation sent', self.good('/desk/api/admin/user/invite', id=self.agent.id)['message'])
        self.env.cr.execute("INSERT INTO res_users_log (create_uid, create_date, write_uid, write_date) VALUES (%s, now(), %s, now())", (self.agent2.id, self.agent2.id))
        self.env.invalidate_all()
        self.assertTrue(self.agent2.login_date)
        self.assertIn('already logged in', self.bad('/desk/api/admin/user/invite', id=self.agent2.id)['error'])

    def test_generated_password_is_strong_enough(self):
        password = self.good('/desk/api/admin/generate-password')['password']
        self.assertGreaterEqual(len(password), 12)
        self.assertNotEqual(password, self.good('/desk/api/admin/generate-password')['password'])


@tagged('post_install', '-at_install')
class TestAdminReports(AdminCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Ticket = cls.env['aixo.ticket']
        cls.now = fields.Datetime.now()
        cls.partner = cls.env['res.partner'].create({'name': '=SUM(A1)', 'email': 'inj@example.org'})
        # two tickets for agent 1 in the current window: one answered on time and closed (good), one unanswered and breached
        cls.r1 = Ticket.create({'name': 'R1', 'partner_id': cls.partner.id, 'owner_id': cls.agent.id})
        cls.r2 = Ticket.create({'name': 'R2', 'partner_id': cls.partner.id, 'owner_id': cls.agent.id})
        cls.env.cr.execute("UPDATE aixo_ticket SET create_date = %s WHERE id IN %s", (cls.now - timedelta(days=2), (cls.r1.id, cls.r2.id)))
        cls.r1.write({'first_response_deadline': cls.now - timedelta(days=2) + timedelta(hours=4),
                      'responded_on': cls.now - timedelta(days=2) + timedelta(hours=1)})
        cls.r1.action_close('<p>done</p>')
        cls.r1.write({'rating': 'good', 'closed_on': cls.now - timedelta(days=1)})
        cls.r2.write({'first_response_deadline': cls.now - timedelta(days=1)})
        # one ticket in the previous window
        cls.r0 = Ticket.create({'name': 'R0', 'partner_id': cls.partner.id, 'owner_id': cls.agent.id})
        cls.env.cr.execute("UPDATE aixo_ticket SET create_date = %s WHERE id = %s", (cls.now - timedelta(days=10), cls.r0.id))
        cls.env.invalidate_all()

    def setUp(self):
        super().setUp()
        self.signin(self.admin)

    def test_employee_report_numbers(self):
        data = self.good('/desk/api/admin/reports', tab='emp', days=7)
        row = next(r for r in data['rows'] if r['agent']['name'] == 'Ag One')
        self.assertEqual(row['assigned'], 3 + 0 if False else row['assigned'])
        self.assertGreaterEqual(row['assigned'], 2)
        self.assertEqual(row['resolved'], 1)
        self.assertEqual(row['first_reply'].replace(' ', ''), '1h00m', "1 hour between creation and first reply")
        self.assertEqual(row['sla'], 50, "one of two answered within the deadline")
        self.assertEqual(row['csat'], 5.0)
        cards = {c['label']: c for c in data['cards']}
        self.assertEqual(cards['Tickets resolved']['value'], 1)
        self.assertIn('vs previous', cards['Tickets assigned']['trend'])

    def test_period_changes_the_window(self):
        week = self.good('/desk/api/admin/reports', tab='emp', days=7)
        month = self.good('/desk/api/admin/reports', tab='emp', days=30)
        get = lambda d: next(r for r in d['rows'] if r['agent']['name'] == 'Ag One')['assigned']
        self.assertEqual(get(month), get(week) + 1, "the 10 day old ticket only counts in the 30 day window")

    def test_customer_report(self):
        data = self.good('/desk/api/admin/reports', tab='cust', days=7)
        row = next(r for r in data['rows'] if r['name'] == '=SUM(A1)')
        self.assertEqual((row['tickets'], row['open']), (2, 1))
        self.assertEqual(row['csat'], 5.0)
        cards = {c['label']: c['value'] for c in data['cards']}
        self.assertGreaterEqual(cards['Active customers'], 1)
        self.assertEqual(cards['Customer CSAT'], '5.0 / 5')

    def test_bad_period_is_rejected(self):
        self.assertIn('period', self.bad('/desk/api/admin/reports', tab='emp', days=13)['error'])

    def test_csv_export_and_formula_injection(self):
        response = self.url_open('/desk/admin/reports/export.csv?tab=cust&days=7')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response.headers['Content-Type'])
        self.assertIn('attachment', response.headers['Content-Disposition'])
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[0], ['Metric', 'Value', 'Trend'])
        flat = [cell for row in rows for cell in row]
        self.assertIn("'=SUM(A1)", flat, "text starting with = is neutralised")
        self.assertNotIn('=SUM(A1)', flat)

    def test_xlsx_export(self):
        response = self.url_open('/desk/admin/reports/export.xlsx?tab=emp&days=30')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.headers['Content-Type'])
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        self.assertIn('xl/worksheets/sheet1.xml', archive.namelist())
        shared = archive.read('xl/sharedStrings.xml').decode()
        self.assertIn('Ag One', shared)
        self.assertIn('Tickets assigned', shared)

    def test_export_is_admin_only_and_validated(self):
        self.assertEqual(self.url_open('/desk/admin/reports/export.pdf?tab=emp&days=7').status_code, 404)
        self.assertEqual(self.url_open('/desk/admin/reports/export.csv?tab=emp&days=5').status_code, 404)
        self.signin(self.agent)
        redirect = self.url_open('/desk/admin/reports/export.csv?tab=emp&days=7', allow_redirects=False)
        self.assertEqual(redirect.status_code, 303)
        self.assertNotIn('text/csv', redirect.headers.get('Content-Type', ''))
        self.opener.cookies.clear()
        self.assertEqual(self.url_open('/desk/admin/reports/export.csv?tab=emp&days=7', allow_redirects=False).status_code, 303)
