from odoo import fields, models


class AixoTeam(models.Model):
    _name = 'aixo.team'
    _description = 'Aixo Team / Department'
    _order = 'name'

    name = fields.Char(required=True)
    department = fields.Char(help="Business unit, e.g. Support, Billing.")
    description = fields.Char()
    lead_id = fields.Many2one('res.users', string='Team lead',
                              domain=[('share', '=', False)])
    member_ids = fields.Many2many(
        'res.users', 'aixo_team_user_rel', 'team_id', 'user_id', string='Members',
        domain=[('share', '=', False)])
    email = fields.Char(string='Support address')
    active = fields.Boolean(default=True)
    open_ticket_count = fields.Integer(compute='_compute_open_ticket_count')

    def _compute_open_ticket_count(self):
        groups = self.env['aixo.ticket'].sudo()._read_group(
            [('team_id', 'in', self.ids), ('state', '!=', 'closed')],
            ['team_id'], ['__count'])
        counts = {team.id: count for team, count in groups}
        for team in self:
            team.open_ticket_count = counts.get(team.id, 0)
