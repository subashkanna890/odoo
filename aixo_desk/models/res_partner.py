from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    desk_plan = fields.Selection([('free', 'Free'), ('paid', 'Paid')], string='Plan', default='free')
    desk_email2 = fields.Char(string='Secondary email')
    desk_mobile = fields.Char(string='Mobile')
    desk_linkedin = fields.Char(string='LinkedIn')
    desk_facebook = fields.Char(string='Facebook')
    desk_owner_id = fields.Many2one(
        'res.users', string='Contact owner', domain=[('share', '=', False)])
    desk_ticket_ids = fields.One2many('aixo.ticket', 'partner_id', string='Desk tickets')

    desk_ticket_count = fields.Integer(compute='_compute_desk_stats', string='All tickets')
    desk_open_ticket_count = fields.Integer(compute='_compute_desk_stats', string='Open tickets')
    desk_overdue_ticket_count = fields.Integer(compute='_compute_desk_stats', string='Overdue tickets')
    desk_happiness = fields.Integer(compute='_compute_desk_stats', string='Happiness %')
    desk_health = fields.Selection(
        [('healthy', 'Healthy'), ('at_risk', 'At risk')],
        compute='_compute_desk_stats', string='Customer health')
    desk_last_contact = fields.Datetime(compute='_compute_desk_stats', string='Last contact')

    @api.depends('desk_ticket_ids.state', 'desk_ticket_ids.rating',
                 'desk_ticket_ids.is_overdue', 'desk_ticket_ids.write_date')
    def _compute_desk_stats(self):
        # Statistics are aggregates over the partner's own tickets; the caller
        # already passed access control on the partner, so sudo is scoped to ids.
        tickets = self.env['aixo.ticket'].sudo().search_fetch(
            [('partner_id', 'in', self.ids)],
            ['partner_id', 'state', 'rating', 'is_overdue', 'write_date'])
        by_partner = {}
        for ticket in tickets:
            by_partner.setdefault(ticket.partner_id.id, []).append(ticket)
        score = {'good': 100, 'okay': 50, 'bad': 0}
        for partner in self:
            items = by_partner.get(partner.id, [])
            rated = [score[t.rating] for t in items if t.rating]
            partner.desk_ticket_count = len(items)
            partner.desk_open_ticket_count = len([t for t in items if t.state != 'closed'])
            partner.desk_overdue_ticket_count = len([t for t in items if t.is_overdue])
            partner.desk_happiness = round(sum(rated) / len(rated)) if rated else 0
            partner.desk_last_contact = max((t.write_date for t in items), default=False)
            at_risk = partner.desk_overdue_ticket_count > 0 or (rated and partner.desk_happiness < 70)
            partner.desk_health = 'at_risk' if at_risk else 'healthy'
