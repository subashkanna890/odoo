from odoo import api, fields, models


class AixoSlaPolicy(models.Model):
    _name = 'aixo.sla.policy'
    _description = 'Aixo SLA Policy'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    business_hours_id = fields.Many2one('aixo.business.hours', string='Business hours')
    plan = fields.Selection(
        [('free', 'Free'), ('paid', 'Paid')], string='Customer plan',
        help="Restrict the policy to customers on this plan. Empty applies to everyone.")
    line_ids = fields.One2many('aixo.sla.policy.line', 'policy_id', string='Targets')

    def _target_for(self, priority):
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.priority == priority)[:1]

    @api.model
    def _find_policy(self, partner=None):
        plan = partner.desk_plan if partner else False
        policies = self.search([])
        specific = policies.filtered(lambda p: p.plan and p.plan == plan)
        return (specific or policies.filtered(lambda p: not p.plan))[:1]


class AixoSlaPolicyLine(models.Model):
    _name = 'aixo.sla.policy.line'
    _description = 'Aixo SLA Policy Target'
    _order = 'policy_id, priority'

    policy_id = fields.Many2one('aixo.sla.policy', required=True, ondelete='cascade')
    priority = fields.Selection(
        [('urgent', 'Urgent'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
        required=True)
    first_response_hours = fields.Float(required=True, default=4.0)
    resolution_hours = fields.Float(required=True, default=24.0)

    _priority_uniq = models.Constraint(
        'unique (policy_id, priority)', 'Only one target per priority in a policy.')
    _hours_check = models.Constraint(
        'CHECK (first_response_hours > 0 AND resolution_hours > 0)',
        'SLA hours must be positive.')
