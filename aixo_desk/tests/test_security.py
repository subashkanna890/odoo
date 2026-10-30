from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import DeskCase


@tagged('post_install', '-at_install')
class TestSecurity(DeskCase):

    def _set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, value)
        # Non-stored computed user flags are cached per environment; a real
        # request starts with an empty cache, a test has to drop it explicitly.
        self.env.invalidate_all()

    def test_roles_resolve(self):
        self.assertEqual(self.admin_user.desk_role, 'admin')
        self.assertEqual(self.agent_a.desk_role, 'agent')
        self.assertEqual(self.cust_a.desk_role, 'customer')
        self.assertTrue(self.cust_a.share, "customers are portal users")
        self.assertFalse(self.agent_a.share, "agents are internal users")

    def test_agent_sees_only_assigned(self):
        mine = self._ticket(self.cust_a.partner_id, self.agent_a)
        other = self._ticket(self.cust_a.partner_id, self.agent_b)
        unassigned = self._ticket(self.cust_a.partner_id)
        visible = self.env['aixo.ticket'].with_user(self.agent_a).search(
            [('id', 'in', (mine | other | unassigned).ids)])
        self.assertEqual(visible, mine)
        with self.assertRaises(AccessError):
            other.with_user(self.agent_a).read(['name'])

    def test_agent_team_queue_setting(self):
        team = self.env['aixo.team'].create({'name': 'T Team', 'member_ids': [(6, 0, [self.agent_a.id])]})
        queued = self._ticket(self.cust_a.partner_id, team_id=team.id)
        Ticket = self.env['aixo.ticket']
        self.assertNotIn(queued, Ticket.with_user(self.agent_a).search([]))
        self._set_param('aixo_desk.agents_see_team_queue', 'True')
        self.assertIn(queued, Ticket.with_user(self.agent_a).search([]))
        self.assertNotIn(queued, Ticket.with_user(self.agent_b).search([]), "non-members still blocked")

    def test_admin_sees_all(self):
        tickets = self._ticket(self.cust_a.partner_id, self.agent_a) | self._ticket(self.cust_b.partner_id)
        found = self.env['aixo.ticket'].with_user(self.admin_user).search([('id', 'in', tickets.ids)])
        self.assertEqual(found, tickets)

    def test_customer_sees_only_own(self):
        own = self._ticket(self.cust_a.partner_id)
        foreign = self._ticket(self.cust_b.partner_id)
        Ticket = self.env['aixo.ticket'].with_user(self.cust_a)
        self.assertEqual(Ticket.search([('id', 'in', (own | foreign).ids)]), own)
        with self.assertRaises(AccessError):
            foreign.with_user(self.cust_a).read(['name'])

    def test_customer_company_sharing_setting(self):
        colleague_ticket = self._ticket(self.colleague_a)
        Ticket = self.env['aixo.ticket'].with_user(self.cust_a)
        self.assertNotIn(colleague_ticket, Ticket.search([]))
        self._set_param('aixo_desk.share_company_tickets', 'True')
        self.assertIn(colleague_ticket, Ticket.search([]))
        foreign = self._ticket(self.cust_b.partner_id)
        self.assertNotIn(foreign, Ticket.search([]), "sharing never crosses companies")

    def test_customer_cannot_delete_ticket(self):
        own = self._ticket(self.cust_a.partner_id)
        with self.assertRaises(AccessError):
            own.with_user(self.cust_a).unlink()

    def test_customer_cannot_touch_config(self):
        for model in ('aixo.team', 'aixo.sla.policy', 'aixo.assignment.rule', 'aixo.otp',
                      'aixo.demo.request', 'aixo.macro', 'aixo.notification', 'aixo.time.entry'):
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(self.cust_a).search([])

    def test_agent_cannot_write_config_or_read_otp(self):
        with self.assertRaises(AccessError):
            self.env['aixo.team'].with_user(self.agent_a).create({'name': 'Nope'})
        with self.assertRaises(AccessError):
            self.env['aixo.otp'].with_user(self.agent_a).search([])

    def test_time_entries_are_personal(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        entry = self.env['aixo.time.entry'].create(
            {'ticket_id': ticket.id, 'user_id': self.agent_b.id, 'duration': 1})
        Entry = self.env['aixo.time.entry'].with_user(self.agent_a)
        self.assertNotIn(entry, Entry.search([]))
        self.assertIn(entry, self.env['aixo.time.entry'].with_user(self.admin_user).search([]))

    def test_notifications_are_personal(self):
        notif = self.env['aixo.notification']._notify(self.agent_b, 'assign', 'x')
        self.assertFalse(self.env['aixo.notification'].with_user(self.agent_a).search([('id', '=', notif.id)]))
        self.assertFalse(self.env['aixo.notification'].with_user(self.admin_user).search([('id', '=', notif.id)]),
                         "even admins only see their own notifications")

    def test_projects_scoped(self):
        project = self.env['aixo.project'].create({
            'name': 'T Project', 'partner_id': self.company_a.id, 'member_ids': [(6, 0, [self.agent_a.id])]})
        Project = self.env['aixo.project']
        self.assertIn(project, Project.with_user(self.agent_a).search([]))
        self.assertNotIn(project, Project.with_user(self.agent_b).search([]))
        self.assertIn(project, Project.with_user(self.cust_a).search([]))
        self.assertNotIn(project, Project.with_user(self.cust_b).search([]))
        with self.assertRaises(AccessError):
            project.with_user(self.cust_a).write({'name': 'hack'})

    def test_closing_requires_resolution(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        with self.assertRaises(ValidationError):
            ticket.write({'state': 'closed'})
        ticket.action_close('<p>Fixed it.</p>')
        self.assertEqual(ticket.state, 'closed')
        self.assertTrue(ticket.closed_on)
        ticket.action_reopen()
        self.assertFalse(ticket.closed_on)
