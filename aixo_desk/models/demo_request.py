from odoo import api, fields, models


class AixoDemoRequest(models.Model):
    _name = 'aixo.demo.request'
    _description = 'Aixo Desk Demo Request'
    _order = 'id desc'

    name = fields.Char(required=True)
    email = fields.Char(string='Work email', required=True)
    company = fields.Char()
    team_size = fields.Char()
    message = fields.Text()
    lead_ref = fields.Char(string='CRM lead', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for request in requests:
            request._create_crm_lead()
        return requests

    def _create_crm_lead(self):
        """Convert to a lead only when CRM is installed."""
        if 'crm.lead' not in self.env:
            return
        self.ensure_one()
        lead = self.env['crm.lead'].sudo().create({
            'name': f"Aixo Desk demo: {self.company or self.name}",
            'contact_name': self.name,
            'email_from': self.email,
            'partner_name': self.company,
            'description': f"Team size: {self.team_size or '-'}\n\n{self.message or ''}",
        })
        self.lead_ref = f"crm.lead,{lead.id}"
