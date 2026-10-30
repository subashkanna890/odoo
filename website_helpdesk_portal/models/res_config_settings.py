# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ============================================================
    # 1. Custom Profile (searchabletext: "custom profile")
    # ============================================================
    helpdesk_profile_id = fields.Many2one(
        'helpdesk.custom.profile',
        string="Custom Profile",
    )
    helpdesk_custom_logo = fields.Binary(
        string="Logo",
        related='helpdesk_profile_id.logo',
        readonly=False,
    )
    helpdesk_brand_name = fields.Char(
        string="Brand Name",
        related='helpdesk_profile_id.name',
        readonly=False,
    )
    helpdesk_brand_gradient = fields.Selection(
        string="Color",
        related='helpdesk_profile_id.color',
        readonly=False,
    )
    helpdesk_brand_font = fields.Selection(
        string="Font Style",
        related='helpdesk_profile_id.font_family',
        readonly=False,
    )

    # ============================================================
    # 2. API Bot Chat (searchabletext: "api bot chat")
    # ============================================================
    helpdesk_enable_ai_bot = fields.Boolean(
        string="Enable API AI Bot Chat",
        config_parameter='website_helpdesk_portal.enable_ai_bot',
        default=True,
    )
    helpdesk_ai_bot_name = fields.Char(
        string="AI Bot Name",
        config_parameter='website_helpdesk_portal.ai_bot_name',
        default='Maya',
        help="4-letter unique AI assistant name (e.g. Maya, Aria, Zara)"
    )
    helpdesk_ai_bot_subtitle = fields.Char(
        string="AI Bot Subtitle",
        config_parameter='website_helpdesk_portal.ai_bot_subtitle',
        default='Your Intelligent AI Companion • Online',
    )
    helpdesk_ai_bot_welcome_msg = fields.Char(
        string="Welcome Message",
        config_parameter='website_helpdesk_portal.ai_bot_welcome_msg',
        default="Hi! I'm Maya, your intelligent AI companion. How can I help you today?",
    )
    helpdesk_ai_bot_avatar_style = fields.Selection([
        ('sparkle_gem', 'Sparkle Crystal Gem (Modern Gradient)'),
        ('neural_crest', 'Neural Crest (Glowing Pulse)'),
        ('cyber_female', 'Cyber Assistant (Stylized Avatar)'),
        ('hologram_core', 'Hologram Core (Futuristic Sphere)'),
    ], string="AI Bot Avatar Style", config_parameter='website_helpdesk_portal.ai_bot_avatar_style', default='sparkle_gem')
    helpdesk_ai_bot_custom_avatar = fields.Binary(
        string="Custom Bot Icon / Logo",
        attachment=True,
    )
    helpdesk_gemini_api_key = fields.Char(
        string="Gemini API Key",
        config_parameter='website_helpdesk_portal.gemini_api_key',
        default='',
    )
    helpdesk_gemini_model = fields.Selection([
        ('gemini-1.5-flash', 'Gemini 1.5 Flash (Fast & Recommended)'),
        ('gemini-2.0-flash', 'Gemini 2.0 Flash (Next-Gen Ultra Fast)'),
        ('gemini-1.5-pro', 'Gemini 1.5 Pro (Advanced Reasoning)'),
        ('gemini-3.5-flash', 'Gemini 1.5 Flash (Default)'),
        ('gemini-flash-latest', 'Gemini Flash Latest'),
        ('gemini-3.8-flash', 'Gemini 2.0 Flash'),
        ('gemini-pro-latest', 'Gemini Pro Latest'),
    ], string="Gemini Model", config_parameter='website_helpdesk_portal.gemini_model', default='gemini-1.5-flash')

    # ============================================================
    # 3. Assigned To (searchabletext: "assigned to")
    # ============================================================
    helpdesk_assignment_mode = fields.Selection([
        ('manual', 'Default (Manual by Project Manager)'),
        ('auto', 'Automatic (Without Project Manager)'),
    ], string="Assignment Mode", config_parameter='website_helpdesk_portal.assignment_mode', default='manual')

    helpdesk_assign_manual = fields.Boolean(
        string="Default",
        compute="_compute_assign_booleans",
        inverse="_inverse_assign_manual",
    )
    helpdesk_assign_auto = fields.Boolean(
        string="Automatic",
        compute="_compute_assign_booleans",
        inverse="_inverse_assign_auto",
    )

    helpdesk_auto_rule_ticket_count = fields.Boolean(
        string="Ticket Count : (lowest ticket count of employee)",
        default=True,
    )
    helpdesk_auto_rule_assigned_date = fields.Boolean(
        string="Assigned Date : (oldest assigned ticket of employee)",
        default=True,
    )

    @api.depends('helpdesk_assignment_mode')
    def _compute_assign_booleans(self):
        for rec in self:
            rec.helpdesk_assign_manual = (rec.helpdesk_assignment_mode != 'auto')
            rec.helpdesk_assign_auto = (rec.helpdesk_assignment_mode == 'auto')

    def _inverse_assign_manual(self):
        for rec in self:
            if rec.helpdesk_assign_manual:
                rec.helpdesk_assignment_mode = 'manual'
            else:
                rec.helpdesk_assignment_mode = 'auto'

    def _inverse_assign_auto(self):
        for rec in self:
            if rec.helpdesk_assign_auto:
                rec.helpdesk_assignment_mode = 'auto'
            else:
                rec.helpdesk_assignment_mode = 'manual'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        profile_id = False
        profile_id_param = ICP.get_param('website_helpdesk_portal.active_profile_id')
        if profile_id_param:
            try:
                prof = self.env['helpdesk.custom.profile'].browse(int(profile_id_param))
                if prof.exists():
                    profile_id = prof.id
            except Exception:
                pass
        if not profile_id:
            prof = self.env['helpdesk.custom.profile'].search([], limit=1)
            if not prof:
                prof = self.env['helpdesk.custom.profile'].sudo().create({
                    'name': 'Helpdesk Portal',
                    'color': 'theme_dantene_purple',
                    'font_family': 'dantene',
                })
            profile_id = prof.id
            ICP.set_param('website_helpdesk_portal.active_profile_id', str(profile_id))

        if 'helpdesk_profile_id' in fields_list:
            res['helpdesk_profile_id'] = profile_id
        if 'helpdesk_ai_bot_name' in fields_list:
            res['helpdesk_ai_bot_name'] = ICP.get_param('website_helpdesk_portal.ai_bot_name', default='Maya')
        if 'helpdesk_ai_bot_subtitle' in fields_list:
            res['helpdesk_ai_bot_subtitle'] = ICP.get_param('website_helpdesk_portal.ai_bot_subtitle', default='Your Intelligent AI Companion • Online')
        if 'helpdesk_ai_bot_welcome_msg' in fields_list:
            res['helpdesk_ai_bot_welcome_msg'] = ICP.get_param('website_helpdesk_portal.ai_bot_welcome_msg', default="Hi! I'm Maya, your intelligent AI companion. How can I help you today?")
        if 'helpdesk_ai_bot_avatar_style' in fields_list:
            res['helpdesk_ai_bot_avatar_style'] = ICP.get_param('website_helpdesk_portal.ai_bot_avatar_style', default='sparkle_gem')
        if 'helpdesk_gemini_api_key' in fields_list:
            res['helpdesk_gemini_api_key'] = ICP.get_param('website_helpdesk_portal.gemini_api_key', default='')
        if 'helpdesk_gemini_model' in fields_list:
            model_val = ICP.get_param('website_helpdesk_portal.gemini_model', default='gemini-1.5-flash')
            if model_val in ['gemini-3.5-flash', 'gemini-flash-latest']:
                model_val = 'gemini-1.5-flash'
                ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-1.5-flash')
            elif model_val == 'gemini-3.8-flash':
                model_val = 'gemini-2.0-flash'
                ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-2.0-flash')
            elif model_val == 'gemini-pro-latest':
                model_val = 'gemini-1.5-pro'
                ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-1.5-pro')
            res['helpdesk_gemini_model'] = model_val
        if 'helpdesk_auto_rule_ticket_count' in fields_list:
            res['helpdesk_auto_rule_ticket_count'] = ICP.get_param('website_helpdesk_portal.auto_rule_ticket_count', default='True') == 'True'
        if 'helpdesk_auto_rule_assigned_date' in fields_list:
            res['helpdesk_auto_rule_assigned_date'] = ICP.get_param('website_helpdesk_portal.auto_rule_assigned_date', default='True') == 'True'
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        if self.helpdesk_profile_id:
            ICP.set_param('website_helpdesk_portal.active_profile_id', str(self.helpdesk_profile_id.id))
            if self.helpdesk_brand_name:
                ICP.set_param('website_helpdesk_portal.brand_name', self.helpdesk_brand_name)
            if self.helpdesk_brand_gradient:
                ICP.set_param('website_helpdesk_portal.brand_gradient', self.helpdesk_brand_gradient)
            if self.helpdesk_brand_font:
                ICP.set_param('website_helpdesk_portal.brand_font', self.helpdesk_brand_font)
        ICP.set_param('website_helpdesk_portal.enable_ai_bot', 'True' if self.helpdesk_enable_ai_bot else 'False')
        ICP.set_param('website_helpdesk_portal.ai_bot_name', self.helpdesk_ai_bot_name or 'Maya')
        ICP.set_param('website_helpdesk_portal.ai_bot_subtitle', self.helpdesk_ai_bot_subtitle or 'Your Intelligent AI Companion • Online')
        ICP.set_param('website_helpdesk_portal.ai_bot_welcome_msg', self.helpdesk_ai_bot_welcome_msg or "Hi! I'm Maya, your intelligent AI companion. How can I help you today?")
        ICP.set_param('website_helpdesk_portal.ai_bot_avatar_style', self.helpdesk_ai_bot_avatar_style or 'sparkle_gem')
        if self.helpdesk_ai_bot_custom_avatar:
            ICP.set_param('website_helpdesk_portal.ai_bot_custom_avatar', self.helpdesk_ai_bot_custom_avatar.decode('utf-8') if isinstance(self.helpdesk_ai_bot_custom_avatar, bytes) else str(self.helpdesk_ai_bot_custom_avatar))
        ICP.set_param('website_helpdesk_portal.gemini_api_key', self.helpdesk_gemini_api_key or '')
        ICP.set_param('website_helpdesk_portal.gemini_model', self.helpdesk_gemini_model or 'gemini-1.5-flash')
        ICP.set_param('website_helpdesk_portal.assignment_mode', self.helpdesk_assignment_mode or 'manual')
        ICP.set_param('website_helpdesk_portal.auto_rule_ticket_count', 'True' if self.helpdesk_auto_rule_ticket_count else 'False')
        ICP.set_param('website_helpdesk_portal.auto_rule_assigned_date', 'True' if self.helpdesk_auto_rule_assigned_date else 'False')

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        profile_id_param = ICP.get_param('website_helpdesk_portal.active_profile_id')
        if profile_id_param:
            try:
                prof = self.env['helpdesk.custom.profile'].browse(int(profile_id_param))
                if prof.exists():
                    res['helpdesk_profile_id'] = prof.id
            except Exception:
                pass
        res['helpdesk_enable_ai_bot'] = ICP.get_param('website_helpdesk_portal.enable_ai_bot', default='True') == 'True'
        res['helpdesk_ai_bot_name'] = ICP.get_param('website_helpdesk_portal.ai_bot_name', default='Maya')
        res['helpdesk_ai_bot_subtitle'] = ICP.get_param('website_helpdesk_portal.ai_bot_subtitle', default='Your Intelligent AI Companion • Online')
        res['helpdesk_ai_bot_welcome_msg'] = ICP.get_param('website_helpdesk_portal.ai_bot_welcome_msg', default="Hi! I'm Maya, your intelligent AI companion. How can I help you today?")
        res['helpdesk_ai_bot_avatar_style'] = ICP.get_param('website_helpdesk_portal.ai_bot_avatar_style', default='sparkle_gem')
        custom_av = ICP.get_param('website_helpdesk_portal.ai_bot_custom_avatar', default=False)
        if custom_av:
            res['helpdesk_ai_bot_custom_avatar'] = custom_av.encode('utf-8') if isinstance(custom_av, str) else custom_av
        res['helpdesk_gemini_api_key'] = ICP.get_param('website_helpdesk_portal.gemini_api_key', default='')
        model_val = ICP.get_param('website_helpdesk_portal.gemini_model', default='gemini-1.5-flash')
        if model_val in ['gemini-3.5-flash', 'gemini-flash-latest']:
            model_val = 'gemini-1.5-flash'
            ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-1.5-flash')
        elif model_val == 'gemini-3.8-flash':
            model_val = 'gemini-2.0-flash'
            ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-2.0-flash')
        elif model_val == 'gemini-pro-latest':
            model_val = 'gemini-1.5-pro'
            ICP.set_param('website_helpdesk_portal.gemini_model', 'gemini-1.5-pro')
        res['helpdesk_gemini_model'] = model_val
        res['helpdesk_assignment_mode'] = ICP.get_param('website_helpdesk_portal.assignment_mode', default='manual')
        res['helpdesk_auto_rule_ticket_count'] = ICP.get_param('website_helpdesk_portal.auto_rule_ticket_count', default='True') == 'True'
        res['helpdesk_auto_rule_assigned_date'] = ICP.get_param('website_helpdesk_portal.auto_rule_assigned_date', default='True') == 'True'
        return res
