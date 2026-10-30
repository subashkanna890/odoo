# -*- coding: utf-8 -*-
import uuid
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    helpdesk_user_id = fields.Many2one(
        'res.users',
        string="Linked User Account",
        related='user_id',
        readonly=True
    )

    helpdesk_username = fields.Char(
        string="Helpdesk Username",
        compute='_compute_helpdesk_username',
        store=True,
        readonly=True,
        copy=False,
        index=True,
        help="Username used by the employee to log into the Helpdesk Employee Console (automatically matches work email)."
    )

    @api.depends('work_email')
    def _compute_helpdesk_username(self):
        for rec in self:
            rec.helpdesk_username = (rec.work_email or rec.private_email or '').strip()

    helpdesk_email = fields.Char(
        string="Login Email",
        compute='_compute_helpdesk_email',
        inverse='_inverse_helpdesk_email',
        store=False,
        help="Email used by the employee to log into the Helpdesk portal."
    )

    @api.depends('work_email', 'user_id.login', 'user_id.email')
    def _compute_helpdesk_email(self):
        for rec in self:
            rec.helpdesk_email = rec.work_email or (rec.user_id.email or rec.user_id.login if rec.user_id else '')

    def _inverse_helpdesk_email(self):
        for rec in self:
            if rec.helpdesk_email:
                clean_email = rec.helpdesk_email.strip()
                rec.work_email = clean_email

    # 1. Password Settings Fields
    helpdesk_password = fields.Char(
        string="Helpdesk Portal Password",
        copy=False,
        help="Direct password used for employee helpdesk portal authentication"
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

    helpdesk_two_factor = fields.Boolean(
        string="Two-Factor Authentication (2FA)",
        default=False,
        help="Enable enhanced security requiring authentication codes."
    )

    notes = fields.Text(
        string="About Me / Notes",
        help="Employee bio or about me description shown on the Helpdesk portal."
    )

    # 2. Login Active Sessions
    helpdesk_session_ids = fields.One2many(
        'helpdesk.employee.session',
        'employee_id',
        string="Active Login Sessions"
    )

    # 3. Log in Device Sessions
    helpdesk_device_ids = fields.One2many(
        'helpdesk.employee.device',
        'employee_id',
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
        try:
            self.env.cr.execute("""
                UPDATE hr_employee
                SET helpdesk_username = TRIM(COALESCE(work_email, private_email))
                WHERE ((work_email IS NOT NULL AND work_email != '') OR (private_email IS NOT NULL AND private_email != ''))
                  AND (helpdesk_username IS NULL OR helpdesk_username != TRIM(COALESCE(work_email, private_email)));
            """)
            self.env.cr.execute("""
                UPDATE hr_employee
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
            for emp in self:
                try:
                    self.env['helpdesk.employee.session'].sudo().search([
                        ('employee_id', '=', emp.id),
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
        """No-op: employee authentication is maintained directly in hr.employee"""
        return False

    def action_set_employee_password(self):
        """Set or update the employee password directly on hr.employee for Helpdesk portal."""
        self.ensure_one()
        new_pass = (self.helpdesk_new_password or self.helpdesk_password or '').strip()
        if not new_pass:
            raise UserError(_("Please enter a new password in the 'Set Password' field."))
        
        if len(new_pass) < 6:
            raise UserError(_("Password must be at least 6 characters long."))

        vals = {
            'helpdesk_password': new_pass,
            'helpdesk_new_password': new_pass,
            'helpdesk_password_updated': fields.Datetime.now(),
            'helpdesk_password_status': 'active',
        }
        self.write(vals)

        # Add chatter message
        login_label = self.helpdesk_username or self.work_email or self.name
        if hasattr(self, 'message_post'):
            self.message_post(
                body=_("Security Update: Helpdesk password configured for employee '%s' (%s) by %s.") % (
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
                'message': _("Password for employee '%s' has been saved. They can now log into the Helpdesk Employee Console.") % self.name,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_revoke_all_sessions(self):
        """Revoke all active sessions and log out unauthorized devices"""
        self.ensure_one()
        for session in self.helpdesk_session_ids:
            if not session.is_current:
                session.status = 'expired'
        for device in self.helpdesk_device_ids:
            if not device.is_trusted:
                device.status = 'logged_out'
        
        self.message_post(
            body=_("Security Alert: All other active sessions and untrusted devices were revoked by %s.") % self.env.user.name
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Sessions Revoked"),
                'message': _("All secondary active sessions have been terminated."),
                'type': 'warning',
                'sticky': False,
            }
        }

class HelpdeskEmployeeSession(models.Model):
    _name = 'helpdesk.employee.session'
    _description = 'Helpdesk Employee Active Login Session'
    _order = 'is_current desc, last_activity desc, id desc'

    employee_id = fields.Many2one('hr.employee', string="Employee", ondelete='cascade', required=True)
    session_token = fields.Char(string="Session ID", default=lambda self: 'SES-' + str(uuid.uuid4())[:8].upper(), required=True)
    ip_address = fields.Char(string="IP Address", default="127.0.0.1")
    login_date = fields.Datetime(string="Login Time", default=fields.Datetime.now)
    last_activity = fields.Datetime(string="Last Activity", default=fields.Datetime.now)
    logout_date = fields.Datetime(string="Logout Time")
    client_type = fields.Selection([
        ('console', 'Employee Helpdesk Console'),
        ('web', 'Customer/Staff Web Portal'),
        ('mobile', 'Mobile App (iOS/Android)'),
        ('api', 'REST API Integration'),
    ], string="Client Interface", default='console')
    status = fields.Selection([
        ('active', 'Active Now'),
        ('idle', 'Idle'),
        ('logged_out', 'Logged Out'),
        ('expired', 'Terminated'),
    ], string="Status", default='active')
    is_current = fields.Boolean(string="Current Session", default=False)
    location = fields.Char(string="Approx. Location", default="Employee Console Login")

    def action_terminate_session(self):
        for rec in self:
            rec.write({
                'status': 'expired',
                'is_current': False,
                'logout_date': fields.Datetime.now(),
            })


class HelpdeskEmployeeDevice(models.Model):
    _name = 'helpdesk.employee.device'
    _description = 'Helpdesk Employee Authorized Device'
    _order = 'last_active desc, id desc'

    employee_id = fields.Many2one('hr.employee', string="Employee", ondelete='cascade', required=True)
    device_name = fields.Char(string="Device Name", default="Web Browser", required=True)
    device_type = fields.Selection([
        ('desktop', 'Desktop / Laptop'),
        ('mobile', 'Smartphone'),
        ('tablet', 'Tablet'),
    ], string="Device Type", default='desktop')
    operating_system = fields.Char(string="Operating System", default="Windows")
    browser = fields.Char(string="Browser", default="Google Chrome")
    location = fields.Char(string="Approx. Location", default="Employee Console Login")
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
