# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HelpdeskCustomProfile(models.Model):
    _name = 'helpdesk.custom.profile'
    _description = 'Helpdesk Custom Profile'

    name = fields.Char(string='Brand Name', required=True, default='Helpdesk Portal')
    logo = fields.Binary(string='Brand Logo', attachment=True)
    color = fields.Selection([
        ('theme_blue_gradient', 'Theme 1 — Royal Blue Ocean Gradient (#1D4ED8 / #2563EB / #38BDF8)'),
        ('theme_papernotes_ocean', 'Theme 2 — Papernotes Ocean Blue (#3B82F6 / #06B6D4)'),
        ('theme_new_romantics', 'Theme 3 — Blue Sapphire Gradient (#1D4ED8 / #2563EB)'),
        ('theme_dantene_purple', 'Theme 4 — Dantene Purple Romance (#8B5CF6 / #EC4899)'),
        ('theme_childer_mint', 'Theme 5 — Childer Mint Fresh (#06B6D4 / #10B981)'),
        ('theme_hellobaby_sunset', 'Theme 6 — Hello Baby Sunset Coral (#F97316 / #FB7185)'),
        ('theme_wildeast_amber', 'Theme 7 — The Wildeast Amber (#F59E0B / #F43F5E)'),
        ('theme_vogue_royal', 'Theme 8 — Vogue Royal Violet (#7C3AED / #6366F1)'),
        # Legacy mappings for backward compatibility
        ('gradient_blue_purple', 'Legacy — Royal Sapphire (Blue/Purple)'),
        ('gradient_emerald_teal', 'Legacy — Emerald Mint (Teal)'),
        ('gradient_sunset_amber', 'Legacy — Sunset Coral (Amber)'),
        ('gradient_ocean_cyan', 'Legacy — Deep Ocean Azure'),
        ('gradient_midnight_gold', 'Legacy — Midnight Gold'),
    ], string='Color Design', default='theme_blue_gradient', required=True)
    font_family = fields.Selection([
        ('plus_jakarta', '01 Plus Jakarta Sans (Modern Clean UI)'),
        ('inter', '02 Inter (Professional Sans)'),
        ('new_romantics', '03 New Romantics (Serif Font)'),
        ('dantene', 'Dantene (Elegant Calligraphy Script)'),
        ('childer', 'Childer (Bold Rounded Handwritten)'),
        ('hello_baby', 'Hello Baby (Playful Friendly Lettering)'),
        ('papernotes', 'Papernotes (Casual Rounded Handwritten)'),
        ('the_wildeast', 'The Wildeast (Textured Brush Lettering)'),
        ('vogue', 'Vogue (Luxury Editorial Serif)'),
        # Legacy mappings for backward compatibility
        ('poppins', 'Legacy — Poppins'),
        ('outfit', 'Legacy — Outfit'),
        ('playfair', 'Legacy — Playfair Display'),
        ('roboto', 'Legacy — Roboto'),
    ], string='Text Font Style', default='plus_jakarta', required=True)
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._sync_profile_to_system()
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            rec._sync_profile_to_system()
        return res

    def _sync_profile_to_system(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('website_helpdesk_portal.active_profile_id', str(self.id))
        if self.name:
            ICP.set_param('website_helpdesk_portal.brand_name', self.name)
        if self.color:
            ICP.set_param('website_helpdesk_portal.brand_gradient', self.color)
        if self.font_family:
            ICP.set_param('website_helpdesk_portal.brand_font', self.font_family)
