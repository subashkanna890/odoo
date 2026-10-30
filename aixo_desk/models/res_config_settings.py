from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aixo_company_name = fields.Char(string='Desk name', config_parameter='aixo_desk.company_name')
    aixo_support_email = fields.Char(string='Support email', config_parameter='aixo_desk.support_email')
    aixo_support_phone = fields.Char(string='Support phone', config_parameter='aixo_desk.support_phone')
    aixo_country = fields.Char(string='Country', config_parameter='aixo_desk.country')
    aixo_timezone = fields.Char(string='Time zone', config_parameter='aixo_desk.timezone')
    aixo_currency = fields.Char(string='Currency', config_parameter='aixo_desk.currency')
    aixo_date_format = fields.Char(string='Date format', config_parameter='aixo_desk.date_format')

    aixo_portal_enabled = fields.Boolean(
        string='Customer portal enabled', config_parameter='aixo_desk.portal_enabled')
    aixo_signup_enabled = fields.Boolean(
        string='Public sign-up enabled', config_parameter='aixo_desk.signup_enabled')
    aixo_share_company_tickets = fields.Boolean(
        string='Share tickets within company', config_parameter='aixo_desk.share_company_tickets')
    aixo_agents_see_team_queue = fields.Boolean(
        string='Agents also see unassigned team tickets',
        config_parameter='aixo_desk.agents_see_team_queue')
    aixo_attachment_max_mb = fields.Integer(
        string='Attachment max size (MB)', config_parameter='aixo_desk.attachment_max_mb')
    aixo_attachment_blocked = fields.Char(
        string='Blocked extensions', config_parameter='aixo_desk.attachment_blocked')
    aixo_csat_enabled = fields.Boolean(
        string='Send CSAT survey on close', config_parameter='aixo_desk.csat_enabled')
    aixo_reopen_days = fields.Integer(
        string='Reopen window (days)', config_parameter='aixo_desk.reopen_days')
    aixo_kb_url = fields.Char(string='Knowledge base URL', config_parameter='aixo_desk.kb_url')
    aixo_show_edition = fields.Boolean(
        string='Show edition block in profile', config_parameter='aixo_desk.show_edition')
    aixo_ai_provider = fields.Selection(
        [('local', 'Local summary (offline)'), ('openai', 'OpenAI compatible API')],
        string='AI provider', config_parameter='aixo_desk.ai_provider')
    aixo_ai_api_key = fields.Char(string='AI API key', config_parameter='aixo_desk.ai_api_key')
