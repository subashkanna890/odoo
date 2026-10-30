from odoo.tests import tagged

from .common import DeskCase


@tagged('post_install', '-at_install')
class TestAssignmentAndNumbering(DeskCase):

    def _team(self, *members):
        return self.env['aixo.team'].create(
            {'name': 'T Team', 'member_ids': [(6, 0, [m.id for m in members])]})

    def test_sequence_numbers_increment(self):
        first = self._ticket(self.cust_a.partner_id)
        second = self._ticket(self.cust_a.partner_id)
        self.assertEqual(int(second.number), int(first.number) + 1)
        self.assertEqual(first.display_name, f"#{first.number} Test ticket")

    def test_project_code_sequence(self):
        project = self.env['aixo.project'].create({'name': 'T Project'})
        self.assertRegex(project.code, r'^PRJ-\d{3}$')

    def test_round_robin_alternates(self):
        team = self._team(self.agent_a, self.agent_b)
        self.env['aixo.assignment.rule'].create(
            {'name': 'T rr', 'team_id': team.id, 'mode': 'round_robin', 'sequence': -10})
        owners = [self._ticket(self.cust_a.partner_id, team_id=team.id).owner_id for _i in range(4)]
        self.assertEqual(owners[0], owners[2])
        self.assertEqual(owners[1], owners[3])
        self.assertNotEqual(owners[0], owners[1])

    def test_load_balanced_picks_least_busy(self):
        team = self._team(self.agent_a, self.agent_b)
        for _i in range(3):
            self._ticket(self.cust_a.partner_id, self.agent_a)
        self.env['aixo.assignment.rule'].create(
            {'name': 'T lb', 'team_id': team.id, 'mode': 'load_balanced', 'sequence': -10})
        ticket = self._ticket(self.cust_a.partner_id, team_id=team.id)
        self.assertEqual(ticket.owner_id, self.agent_b)

    def test_offline_agents_are_skipped(self):
        team = self._team(self.agent_a, self.agent_b)
        self.agent_a.desk_availability = 'offline'
        self.env['aixo.assignment.rule'].create(
            {'name': 'T rr', 'team_id': team.id, 'mode': 'round_robin', 'sequence': -10})
        for _i in range(3):
            self.assertEqual(self._ticket(self.cust_a.partner_id, team_id=team.id).owner_id, self.agent_b)

    def test_skill_matching(self):
        team = self._team(self.agent_a, self.agent_b)
        skill = self.env['aixo.skill'].create({'name': 'T-billing'})
        self.agent_b.desk_skill_ids = skill
        tag = self.env['aixo.ticket.tag'].create({'name': 'T-billing'})
        self.env['aixo.assignment.rule'].create(
            {'name': 'T skills', 'team_id': team.id, 'mode': 'round_robin', 'match_skills': True, 'sequence': -10})
        for _i in range(3):
            ticket = self._ticket(self.cust_a.partner_id, team_id=team.id, tag_ids=[(6, 0, [tag.id])])
            self.assertEqual(ticket.owner_id, self.agent_b)

    def test_manual_mode_and_explicit_owner_are_respected(self):
        team = self._team(self.agent_a, self.agent_b)
        self.env['aixo.assignment.rule'].create(
            {'name': 'T manual', 'team_id': team.id, 'mode': 'none', 'sequence': -10})
        self.assertFalse(self._ticket(self.cust_a.partner_id, team_id=team.id).owner_id)
        self.env['aixo.assignment.rule'].create(
            {'name': 'T rr', 'team_id': team.id, 'mode': 'round_robin', 'sequence': -20})
        explicit = self._ticket(self.cust_a.partner_id, self.agent_b, team_id=team.id)
        self.assertEqual(explicit.owner_id, self.agent_b)

    def test_ticket_without_team_is_not_auto_assigned(self):
        team = self._team(self.agent_a)
        self.env['aixo.assignment.rule'].create(
            {'name': 'T rr', 'team_id': team.id, 'mode': 'round_robin', 'sequence': -10})
        self.assertFalse(self._ticket(self.cust_a.partner_id).owner_id)

    def test_template_defaults_applied(self):
        template = self.env.ref('aixo_desk.template_bug')
        ticket = self._ticket(self.cust_a.partner_id, template_id=template.id)
        self.assertEqual(ticket.priority, 'high')
        self.assertEqual(ticket.classification, 'problem')

    def test_partner_statistics(self):
        partner = self.cust_a.partner_id
        good = self._ticket(partner)
        good.action_close('<p>ok</p>')
        good.rating = 'good'
        bad = self._ticket(partner)
        bad.action_close('<p>ok</p>')
        bad.rating = 'bad'
        self._ticket(partner)
        partner.invalidate_recordset()
        self.assertEqual(partner.desk_ticket_count, 3)
        self.assertEqual(partner.desk_open_ticket_count, 1)
        self.assertEqual(partner.desk_happiness, 50)
        self.assertEqual(partner.desk_health, 'at_risk')

    def test_timer_one_running_per_agent(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        Entry = self.env['aixo.time.entry']
        entry = Entry.create({'ticket_id': ticket.id, 'user_id': self.agent_a.id})
        entry.action_start()
        self.assertTrue(entry.is_running)
        second = Entry.create({'ticket_id': ticket.id, 'user_id': self.agent_a.id})
        second.action_start()
        self.assertTrue(second.is_running)
        self.assertFalse(entry.is_running, "starting a second timer pauses the first one")
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.env.cr.execute("UPDATE aixo_time_entry SET timer_start = now() WHERE id = %s", (entry.id,))
        second.action_pause()
        self.assertFalse(second.is_running)
