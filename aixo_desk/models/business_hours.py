from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

WEEKDAYS = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
    ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
]


class AixoBusinessHours(models.Model):
    _name = 'aixo.business.hours'
    _description = 'Aixo Business Hours'

    name = fields.Char(required=True, default='Business hours')
    tz = fields.Selection(
        lambda self: [(tz, tz) for tz in sorted(pytz.all_timezones)],
        string='Time zone', required=True, default='Asia/Kolkata')
    line_ids = fields.One2many('aixo.business.hours.line', 'hours_id', string='Working days')
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    def _day_windows(self, day, tzinfo):
        """Return [(start, end)] aware datetimes (UTC) worked on local date ``day``."""
        self.ensure_one()
        windows = []
        for line in self.line_ids.filtered(lambda l: int(l.weekday) == day.weekday()):
            start = datetime.combine(day, datetime.min.time()) + timedelta(hours=line.hour_from)
            end = datetime.combine(day, datetime.min.time()) + timedelta(hours=line.hour_to)
            windows.append((tzinfo.localize(start).astimezone(pytz.utc),
                            tzinfo.localize(end).astimezone(pytz.utc)))
        return sorted(windows)

    def _holiday_dates(self, team=None):
        domain = ['|', ('team_id', '=', False)]
        domain.append(('team_id', '=', team.id if team else False))
        return set(self.env['aixo.holiday'].sudo().search(domain).mapped('date'))

    def add_work_hours(self, start, hours, team=None):
        """Naive UTC ``start`` + ``hours`` of working time, skipping holidays.

        Returns a naive UTC datetime. With no working lines the hours are plain
        clock hours so a misconfigured calendar never blocks ticket creation.
        """
        self.ensure_one()
        if not self.line_ids:
            return start + timedelta(hours=hours)
        tzinfo = pytz.timezone(self.tz)
        holidays = self._holiday_dates(team)
        cursor = pytz.utc.localize(start)
        remaining = timedelta(hours=hours)
        day = cursor.astimezone(tzinfo).date()
        for _i in range(366):
            if day not in holidays:
                for w_start, w_end in self._day_windows(day, tzinfo):
                    if w_end <= cursor:
                        continue
                    begin = max(w_start, cursor)
                    available = w_end - begin
                    if available >= remaining:
                        return (begin + remaining).replace(tzinfo=None)
                    remaining -= available
            day += timedelta(days=1)
        return (cursor + remaining).replace(tzinfo=None)

    @api.model
    def get_default(self):
        return self.search([('is_default', '=', True)], limit=1) or self.search([], limit=1)


class AixoBusinessHoursLine(models.Model):
    _name = 'aixo.business.hours.line'
    _description = 'Aixo Business Hours Line'
    _order = 'hours_id, weekday, hour_from'

    hours_id = fields.Many2one('aixo.business.hours', required=True, ondelete='cascade')
    weekday = fields.Selection(WEEKDAYS, required=True)
    hour_from = fields.Float(required=True, default=9.0)
    hour_to = fields.Float(required=True, default=18.0)

    _hours_check = models.Constraint(
        'CHECK (hour_from >= 0 AND hour_to <= 24 AND hour_from < hour_to)',
        'Working hours must be inside a day and end after they start.')


class AixoHoliday(models.Model):
    _name = 'aixo.holiday'
    _description = 'Aixo Holiday'
    _order = 'date'

    name = fields.Char(required=True)
    date = fields.Date(required=True)
    team_id = fields.Many2one('aixo.team', string='Applies to',
                              help="Leave empty to apply to all departments.")
