from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    desk_job_title = fields.Char(string='Job title')
    desk_office_phone = fields.Char(string='Office phone')
    desk_extension = fields.Char(string='Extension')
    desk_availability = fields.Selection(
        [('online', 'Online'), ('away', 'Away'), ('offline', 'Offline')],
        string='Availability', default='online')
    desk_channel_status = fields.Json(
        string='Channel statuses',
        help="Per channel availability, e.g. {'email': 'online', 'chat': 'away'}.")
    desk_team_ids = fields.Many2many(
        'aixo.team', 'aixo_team_user_rel', 'user_id', 'team_id', string='Departments')
    desk_channel_ids = fields.Many2many('aixo.channel', string='Channel expertise')
    desk_skill_ids = fields.Many2many('aixo.skill', string='Skills')
    desk_lang_ids = fields.Many2many('res.lang', string='Languages spoken')
    desk_hours_id = fields.Many2one('aixo.business.hours', string='Working hours')
    desk_assign_seq = fields.Integer(
        string='Auto-assign order', copy=False,
        help="Monotonic marker of the last automatic assignment (lowest is next in round robin).")
    desk_force_password_change = fields.Boolean(string='Must change password', copy=False)

    # Per user look and feel (applied through CSS variables on the website)
    desk_appearance = fields.Selection(
        [('light', 'Light'), ('night', 'Night'), ('auto', 'Auto')], default='light')
    desk_light_panel = fields.Boolean(string='Make left panel light', default=True)
    desk_theme = fields.Selection(
        [('red', 'Red'), ('green', 'Green'), ('blue', 'Blue'),
         ('yellow', 'Yellow'), ('orange', 'Orange')], default='blue')
    desk_font = fields.Selection(
        [('inter', 'Inter'), ('roboto', 'Roboto'), ('lato', 'Lato'),
         ('open_sans', 'Open Sans'), ('poppins', 'Poppins')], default='inter')
    desk_font_size = fields.Selection(
        [('xs', 'Extra small'), ('s', 'Small'), ('m', 'Medium'),
         ('l', 'Large'), ('xl', 'Extra large')], default='m')
    desk_prefs = fields.Json(
        string='Desk preferences',
        help="Ticket and detail view toggles, saved per user.")
    desk_starred_boards = fields.Char(string='Starred dashboards')

    desk_role = fields.Selection(
        [('admin', 'Admin'), ('agent', 'Employee'), ('customer', 'Customer')],
        compute='_compute_desk_role', string='Desk role')
    desk_share_company = fields.Boolean(compute='_compute_desk_settings')
    desk_team_queue = fields.Boolean(compute='_compute_desk_settings')

    @api.depends_context('uid')
    @api.depends('group_ids')
    def _compute_desk_role(self):
        admin = self.env.ref('aixo_desk.group_desk_admin')
        agent = self.env.ref('aixo_desk.group_desk_agent')
        customer = self.env.ref('aixo_desk.group_desk_customer')
        for user in self:
            groups = user.all_group_ids
            if admin in groups:
                user.desk_role = 'admin'
            elif agent in groups:
                user.desk_role = 'agent'
            elif customer in groups:
                user.desk_role = 'customer'
            else:
                user.desk_role = False

    def _compute_desk_settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        share = icp.get_param('aixo_desk.share_company_tickets', 'False') == 'True'
        queue = icp.get_param('aixo_desk.agents_see_team_queue', 'False') == 'True'
        for user in self:
            user.desk_share_company = share
            user.desk_team_queue = queue

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + [
            'desk_job_title', 'desk_office_phone', 'desk_extension',
            'desk_availability', 'desk_channel_status', 'desk_appearance',
            'desk_light_panel', 'desk_theme', 'desk_font', 'desk_font_size',
            'desk_prefs', 'desk_starred_boards',
        ]
