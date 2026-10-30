from odoo import api, fields, models


class AixoAssignmentRule(models.Model):
    _name = 'aixo.assignment.rule'
    _description = 'Aixo Assignment Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    team_id = fields.Many2one('aixo.team', string='Team', required=True)
    mode = fields.Selection(
        [('none', 'Manual (no automatic assignment)'),
         ('round_robin', 'Round robin'),
         ('load_balanced', 'Load balanced')],
        default='round_robin', required=True)
    match_skills = fields.Boolean(
        string='Match skills', help="Only agents having every skill tagged on the ticket's product.")
    active = fields.Boolean(default=True)

    @api.model
    def _find_rule(self, ticket):
        if not ticket.team_id:
            return self.browse()
        return self.sudo().search(
            [('mode', '!=', 'none'), ('team_id', '=', ticket.team_id.id)], limit=1)

    def _candidates(self, ticket):
        self.ensure_one()
        members = self.team_id.member_ids.filtered(
            lambda u: u.active and u.desk_availability != 'offline')
        if self.match_skills and ticket.tag_ids:
            skills = self.env['aixo.skill'].search([('name', 'in', ticket.tag_ids.mapped('name'))])
            if skills:
                members = members.filtered(lambda u: skills <= u.desk_skill_ids)
        return members

    def _pick_user(self, ticket):
        """Return the agent who should get ``ticket`` or an empty recordset."""
        self.ensure_one()
        members = self._candidates(ticket)
        if not members:
            return self.env['res.users']
        if self.mode == 'round_robin':
            chosen = members.sorted(lambda u: (u.desk_assign_seq, u.id))[0]
        else:
            groups = self.env['aixo.ticket'].sudo()._read_group(
                [('owner_id', 'in', members.ids), ('state', '!=', 'closed')],
                ['owner_id'], ['__count'])
            load = {user.id: count for user, count in groups}
            chosen = members.sorted(lambda u: (load.get(u.id, 0), u.id))[0]
        chosen.sudo().desk_assign_seq = max(members.mapped('desk_assign_seq')) + 1
        return chosen
