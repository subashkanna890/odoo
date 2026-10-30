from odoo import fields, models


class AixoChannel(models.Model):
    _name = 'aixo.channel'
    _description = 'Aixo Desk Channel'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)

    _code_uniq = models.Constraint('unique (code)', 'The channel code must be unique.')


class AixoSkill(models.Model):
    _name = 'aixo.skill'
    _description = 'Aixo Desk Skill'
    _order = 'name'

    name = fields.Char(required=True, translate=True)

    _name_uniq = models.Constraint('unique (name)', 'This skill already exists.')


class AixoTicketTag(models.Model):
    _name = 'aixo.ticket.tag'
    _description = 'Aixo Ticket Tag'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()

    _name_uniq = models.Constraint('unique (name)', 'This tag already exists.')


class AixoProduct(models.Model):
    _name = 'aixo.product'
    _description = 'Aixo Desk Product'
    _order = 'name'

    name = fields.Char(required=True)
    team_id = fields.Many2one('aixo.team', string='Department')
    active = fields.Boolean(default=True)
    ticket_count = fields.Integer(compute='_compute_ticket_count')

    def _compute_ticket_count(self):
        groups = self.env['aixo.ticket'].sudo()._read_group(
            [('product_id', 'in', self.ids)], ['product_id'], ['__count'])
        counts = {product.id: count for product, count in groups}
        for product in self:
            product.ticket_count = counts.get(product.id, 0)


class AixoTicketTemplate(models.Model):
    _name = 'aixo.ticket.template'
    _description = 'Aixo Ticket Template'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    subject_prefix = fields.Char()
    description = fields.Html()
    priority = fields.Selection(
        [('urgent', 'Urgent'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
        default='medium')
    classification = fields.Selection(
        [('question', 'Question'), ('problem', 'Problem'),
         ('feature', 'Feature request'), ('others', 'Others')])
    team_id = fields.Many2one('aixo.team', string='Department')
    active = fields.Boolean(default=True)


class AixoMacro(models.Model):
    _name = 'aixo.macro'
    _description = 'Aixo Canned Reply'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    body = fields.Text(required=True, translate=True,
                       help="Reply text. {contact} and {agent} are replaced when inserted.")
    sequence = fields.Integer(default=10)
    suggest = fields.Boolean(string='Show as AI suggestion chip', default=True)
    set_state = fields.Selection(
        [('open', 'Open'), ('on_hold', 'On Hold'), ('closed', 'Closed')],
        string='Then set status')
    usage_count = fields.Integer(readonly=True)
    active = fields.Boolean(default=True)
