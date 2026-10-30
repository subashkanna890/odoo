from datetime import datetime, timedelta

import pytz

from odoo import fields
from odoo.tests import tagged

from .common import DeskCase


def utc(tz_name, *args):
    """Naive UTC datetime for a local wall-clock time."""
    return pytz.timezone(tz_name).localize(datetime(*args)).astimezone(pytz.utc).replace(tzinfo=None)


@tagged('post_install', '-at_install')
class TestSla(DeskCase):

    def setUp(self):
        super().setUp()
        self.hours = self.env['aixo.business.hours'].create({
            'name': 'T hours', 'tz': 'Asia/Kolkata',
            'line_ids': [(0, 0, {'weekday': str(d), 'hour_from': 9, 'hour_to': 18}) for d in range(5)],
        })

    def test_within_a_working_day(self):
        start = utc('Asia/Kolkata', 2026, 11, 2, 10, 0)  # Monday 10:00 IST
        self.assertEqual(self.hours.add_work_hours(start, 4), utc('Asia/Kolkata', 2026, 11, 2, 14, 0))

    def test_rolls_over_end_of_day(self):
        start = utc('Asia/Kolkata', 2026, 11, 2, 16, 0)  # Monday 16:00, 2h left today
        self.assertEqual(self.hours.add_work_hours(start, 4), utc('Asia/Kolkata', 2026, 11, 3, 11, 0))

    def test_skips_weekend(self):
        start = utc('Asia/Kolkata', 2026, 11, 6, 17, 0)  # Friday 17:00
        self.assertEqual(self.hours.add_work_hours(start, 2), utc('Asia/Kolkata', 2026, 11, 9, 10, 0))

    def test_starts_next_morning_when_after_hours(self):
        start = utc('Asia/Kolkata', 2026, 11, 2, 20, 0)
        self.assertEqual(self.hours.add_work_hours(start, 1), utc('Asia/Kolkata', 2026, 11, 3, 10, 0))

    def test_holiday_is_skipped(self):
        self.env['aixo.holiday'].create({'name': 'T Holiday', 'date': '2026-11-03'})
        start = utc('Asia/Kolkata', 2026, 11, 2, 16, 0)
        self.assertEqual(self.hours.add_work_hours(start, 4), utc('Asia/Kolkata', 2026, 11, 4, 11, 0))

    def test_team_holiday_only_affects_its_team(self):
        team = self.env['aixo.team'].create({'name': 'T Team'})
        other = self.env['aixo.team'].create({'name': 'T Other'})
        self.env['aixo.holiday'].create({'name': 'T Team day', 'date': '2026-11-03', 'team_id': team.id})
        start = utc('Asia/Kolkata', 2026, 11, 2, 16, 0)
        self.assertEqual(self.hours.add_work_hours(start, 4, team), utc('Asia/Kolkata', 2026, 11, 4, 11, 0))
        self.assertEqual(self.hours.add_work_hours(start, 4, other), utc('Asia/Kolkata', 2026, 11, 3, 11, 0))

    def test_no_working_lines_falls_back_to_clock_hours(self):
        empty = self.env['aixo.business.hours'].create({'name': 'Empty', 'tz': 'UTC'})
        start = datetime(2026, 11, 2, 10, 0)
        self.assertEqual(empty.add_work_hours(start, 5), start + timedelta(hours=5))

    def test_ticket_gets_deadlines_from_priority(self):
        policy = self.env['aixo.sla.policy'].create({
            'name': 'T policy', 'sequence': -100, 'business_hours_id': self.hours.id,
            'line_ids': [(0, 0, {'priority': 'high', 'first_response_hours': 1, 'resolution_hours': 3}),
                         (0, 0, {'priority': 'low', 'first_response_hours': 5, 'resolution_hours': 8})],
        })
        high = self._ticket(self.cust_a.partner_id, priority='high', sla_policy_id=policy.id)
        low = self._ticket(self.cust_a.partner_id, priority='low', sla_policy_id=policy.id)
        self.assertTrue(high.first_response_deadline)
        self.assertLess(high.first_response_deadline, low.first_response_deadline)
        self.assertLess(high.resolution_deadline, low.resolution_deadline)
        self.assertEqual(high.due_date, high.resolution_deadline)

    def test_overdue_flag_and_cron(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        ticket.due_date = fields.Datetime.now() - timedelta(hours=1)
        self.assertTrue(ticket.is_overdue)
        ticket.resolution_deadline = fields.Datetime.now() - timedelta(minutes=5)
        self.env['aixo.ticket']._cron_update_sla()
        self.assertEqual(ticket.sla_status, 'breached')
        notified = self.env['aixo.notification'].sudo().search(
            [('user_id', '=', self.agent_a.id), ('type', '=', 'sla'), ('ticket_id', '=', ticket.id)])
        self.assertTrue(notified, "owner is notified of the breach")
        ticket.action_close('<p>done</p>')
        self.assertFalse(ticket.is_overdue, "closed tickets are never overdue")

    def test_at_risk_when_under_twenty_percent_left(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        now = fields.Datetime.now()
        self.env.cr.execute("UPDATE aixo_ticket SET create_date = %s WHERE id = %s",
                            (now - timedelta(hours=1), ticket.id))
        ticket.invalidate_recordset(['create_date'])
        ticket.first_response_deadline = False
        ticket.responded_on = now
        ticket.resolution_deadline = now + timedelta(minutes=5)
        self.assertEqual(ticket._sla_state(now), 'at_risk')
        ticket.resolution_deadline = now + timedelta(days=30)
        self.assertEqual(ticket._sla_state(now), 'on_time')

    def test_on_hold_pauses_sla(self):
        ticket = self._ticket(self.cust_a.partner_id, self.agent_a)
        deadline = ticket.resolution_deadline
        ticket.state = 'on_hold'
        ticket.hold_since = fields.Datetime.now() - timedelta(hours=2)
        ticket.state = 'open'
        self.assertGreaterEqual(ticket.resolution_deadline - deadline, timedelta(hours=1, minutes=59))
        self.assertFalse(ticket.hold_since)
