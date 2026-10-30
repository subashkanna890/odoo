# -*- coding: utf-8 -*-
import logging
import uuid
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    helpdesk_user_id = fields.Many2one(
        'res.users',
        string="Linked User Account",
        compute='_compute_helpdesk_user_id',
        readonly=True,
        help="Linked portal or internal user account for this contact."
    )

    helpdesk_username = fields.Char(
        string="Helpdesk Username",
        compute='_compute_helpdesk_username',
        store=True,
        readonly=True,
        copy=False,
        index=True,
        help="Username used by the customer to log into the Customer Helpdesk Portal (automatically matches contact email)."
    )

    @api.depends('email')
    def _compute_helpdesk_username(self):
        for rec in self:
            rec.helpdesk_username = (rec.email or '').strip()

    helpdesk_password = fields.Char(
        string="Helpdesk Portal Password",
        copy=False,
        help="Direct password used for customer helpdesk portal authentication."
    )
    helpdesk_new_password = fields.Char(
        string="Set New Password",
        help="Type a new password here and click 'Set Password' to apply it to the linked user."
    )
    helpdesk_password_updated = fields.Datetime(
        string="Password Last Changed",
        default=fields.Datetime.now,
        readonly=True
    )
    helpdesk_password_status = fields.Selection([
        ('active', 'Active & Protected'),
        ('expired', 'Needs Reset'),
        ('temporary', 'Temporary Password'),
    ], string="Security Status", default='active')

    notes = fields.Text(
        string="About Me / Bio",
        help="Contact introduction, bio, or support notes shown on the Helpdesk portal."
    )

    helpdesk_session_ids = fields.One2many(
        'helpdesk.customer.session',
        'partner_id',
        string="Active Login Sessions"
    )

    helpdesk_device_ids = fields.One2many(
        'helpdesk.customer.device',
        'partner_id',
        string="Registered Device Sessions"
    )

    helpdesk_active_session_count = fields.Integer(
        string="Active Sessions",
        compute='_compute_helpdesk_security_stats'
    )
    helpdesk_device_count = fields.Integer(
        string="Registered Devices",
        compute='_compute_helpdesk_security_stats'
    )

    @api.depends('user_ids')
    def _compute_helpdesk_user_id(self):
        for rec in self:
            rec.helpdesk_user_id = rec.user_ids[0] if rec.user_ids else False

    @api.depends('helpdesk_session_ids.status', 'helpdesk_device_ids.status')
    def _compute_helpdesk_security_stats(self):
        for rec in self:
            try:
                rec.helpdesk_active_session_count = len(rec.helpdesk_session_ids.filtered(lambda s: s.status == 'active'))
                rec.helpdesk_device_count = len(rec.helpdesk_device_ids.filtered(lambda d: d.status == 'logged_in'))
            except Exception:
                rec.helpdesk_active_session_count = 0
                rec.helpdesk_device_count = 0

    def _auto_init(self):
        res = super()._auto_init()
        # Automatically populate helpdesk_username table value with contact's email value
        try:
            self.env.cr.execute("""
                UPDATE res_partner
                SET helpdesk_username = TRIM(email)
                WHERE email IS NOT NULL AND email != ''
                  AND (helpdesk_username IS NULL OR helpdesk_username != TRIM(email));
            """)
            self.env.cr.execute("""
                UPDATE res_partner
                SET helpdesk_new_password = helpdesk_password
                WHERE helpdesk_password IS NOT NULL AND helpdesk_password != ''
                  AND (helpdesk_new_password IS NULL OR helpdesk_new_password = '');
            """)
        except Exception:
            pass
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.pop('helpdesk_username', None)
            new_p = vals.get('helpdesk_new_password') or vals.get('helpdesk_password')
            if new_p:
                clean_p = str(new_p).strip()
                vals['helpdesk_password'] = clean_p
                vals['helpdesk_new_password'] = clean_p
                vals['helpdesk_password_updated'] = fields.Datetime.now()
                vals['helpdesk_password_status'] = 'active'
        return super().create(vals_list)

    def write(self, vals):
        vals.pop('helpdesk_username', None)
        new_p = vals.get('helpdesk_new_password') or vals.get('helpdesk_password')
        if new_p:
            clean_p = str(new_p).strip()
            vals['helpdesk_password'] = clean_p
            vals['helpdesk_new_password'] = clean_p
            vals['helpdesk_password_updated'] = fields.Datetime.now()
            vals['helpdesk_password_status'] = 'active'
        res = super().write(vals)
        if 'active' in vals and not vals['active']:
            for partner in self:
                try:
                    self.env['helpdesk.customer.session'].sudo().search([
                        ('partner_id', '=', partner.id),
                        ('status', '=', 'active')
                    ]).write({
                        'status': 'logged_out',
                        'is_current': False,
                        'logout_date': fields.Datetime.now()
                    })
                except Exception:
                    pass
        return res

    def _sync_helpdesk_portal_user(self, email, new_pass):
        """No-op: customer authentication is maintained directly in res.partner"""
        return False

    def action_set_employee_password(self):
        """Set or update the customer password directly on res.partner for Helpdesk portal."""
        self.ensure_one()
        new_pass = (self.helpdesk_new_password or self.helpdesk_password or '').strip()
        if not new_pass:
            raise UserError(_("Please enter a password in the 'Set Password' field."))

        if len(new_pass) < 6:
            raise UserError(_("Password must be at least 6 characters long."))

        vals = {
            'helpdesk_password': new_pass,
            'helpdesk_new_password': new_pass,
            'helpdesk_password_updated': fields.Datetime.now(),
            'helpdesk_password_status': 'active',
        }
        self.write(vals)

        login_label = self.helpdesk_username or self.email or self.name
        if hasattr(self, 'message_post'):
            self.message_post(
                body=_("Security Update: Helpdesk portal password configured for '%s' (%s) by %s.") % (
                    self.name,
                    login_label,
                    self.env.user.name,
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Password Set Successfully"),
                'message': _("Password for '%s' has been saved. The customer can now log into the Helpdesk portal.") % self.name,
                'type': 'success',
                'sticky': False,
            }
        }

    action_set_partner_password = action_set_employee_password


class HelpdeskCustomerSession(models.Model):
    _name = 'helpdesk.customer.session'
    _description = 'Helpdesk Customer Active Login Session'
    _order = 'is_current desc, login_date desc, id desc'

    partner_id = fields.Many2one('res.partner', string="Customer / Contact", ondelete='cascade', required=True)
    session_token = fields.Char(string="Session ID", default=lambda self: 'SES-' + str(uuid.uuid4())[:8].upper(), required=True)
    ip_address = fields.Char(string="IP Address", default="127.0.0.1")
    login_date = fields.Datetime(string="Login Time", default=fields.Datetime.now)
    last_activity = fields.Datetime(string="Last Active", default=fields.Datetime.now)
    logout_date = fields.Datetime(string="Logout Time")
    client_type = fields.Selection([
        ('web', 'Customer Web Portal'),
        ('mobile', 'Mobile Portal'),
        ('api', 'REST API Integration'),
    ], string="Client Interface", default='web')
    status = fields.Selection([
        ('active', 'Active Now'),
        ('idle', 'Idle'),
        ('logged_out', 'Logged Out'),
        ('expired', 'Terminated'),
    ], string="Status", default='active')
    is_current = fields.Boolean(string="Current Session", default=False)
    location = fields.Char(string="Approx. Location", default="Web Customer Portal")

    def action_terminate_session(self):
        for rec in self:
            rec.write({
                'status': 'expired',
                'is_current': False,
                'logout_date': fields.Datetime.now(),
            })


class HelpdeskCustomerDevice(models.Model):
    _name = 'helpdesk.customer.device'
    _description = 'Helpdesk Customer Authorized Device'
    _order = 'last_active desc, id desc'

    partner_id = fields.Many2one('res.partner', string="Customer / Contact", ondelete='cascade', required=True)
    device_name = fields.Char(string="Device Name", default="Web Browser", required=True)
    device_type = fields.Selection([
        ('desktop', 'Desktop / Laptop'),
        ('mobile', 'Smartphone'),
        ('tablet', 'Tablet'),
    ], string="Device Type", default='desktop')
    operating_system = fields.Char(string="Operating System", default="Windows")
    browser = fields.Char(string="Browser", default="Google Chrome")
    location = fields.Char(string="Location", default="Web Portal Login")
    ip_address = fields.Char(string="IP Address", default="127.0.0.1")
    first_login = fields.Datetime(string="First Logged In", default=fields.Datetime.now)
    last_active = fields.Datetime(string="Last Active", default=fields.Datetime.now)
    is_trusted = fields.Boolean(string="Trusted Device", default=True)
    status = fields.Selection([
        ('logged_in', 'Logged In'),
        ('logged_out', 'Signed Out'),
    ], string="Status", default='logged_in')

    def action_logout_device(self):
        for rec in self:
            rec.write({
                'status': 'logged_out',
                'last_active': fields.Datetime.now(),
            })
