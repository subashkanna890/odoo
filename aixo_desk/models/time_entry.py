from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AixoTimeEntry(models.Model):
    _name = 'aixo.time.entry'
    _description = 'Aixo Time Entry'
    _order = 'date desc, id desc'

    ticket_id = fields.Many2one('aixo.ticket', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Agent', required=True, index=True,
                              default=lambda self: self.env.user)
    name = fields.Char(string='Work description', required=True, default='Work on ticket')
    date = fields.Date(required=True, default=fields.Date.context_today)
    duration = fields.Float(string='Hours', help="Duration in hours.")
    timer_start = fields.Datetime(string='Timer started', copy=False)
    is_running = fields.Boolean(compute='_compute_is_running', store=True)

    _duration_check = models.Constraint('CHECK (duration >= 0)', 'Duration cannot be negative.')
    _one_running_timer = models.UniqueIndex(
        '(user_id) WHERE timer_start IS NOT NULL',
        'You already have a timer running. Pause it before starting another.')

    @api.depends('timer_start')
    def _compute_is_running(self):
        for entry in self:
            entry.is_running = bool(entry.timer_start)

    def action_start(self):
        for entry in self:
            others = self.search([('user_id', '=', entry.user_id.id), ('timer_start', '!=', False),
                                  ('id', '!=', entry.id)])
            others.action_pause()
            self.env.flush_all()  # the unique index is checked per statement, so pause must land first
            entry.timer_start = fields.Datetime.now()

    def action_pause(self):
        now = fields.Datetime.now()
        for entry in self.filtered('timer_start'):
            elapsed = (now - entry.timer_start).total_seconds() / 3600
            entry.write({'duration': entry.duration + elapsed, 'timer_start': False})

    @api.constrains('user_id')
    def _check_agent(self):
        for entry in self:
            if entry.user_id.share:
                raise ValidationError(_("Only employees can log time."))
