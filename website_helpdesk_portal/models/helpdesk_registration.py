# -*- coding: utf-8 -*-
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class HelpdeskPortalRegistration(models.Model):
    _name = 'helpdesk.portal.registration'
    _description = 'Helpdesk Portal Pending Account Registration & OTP'
    _order = 'create_date desc'

    name = fields.Char(string='Administrator Name', required=True)
    email = fields.Char(string='Administrator Email', required=True, index=True)
    company_name = fields.Char(string='Company Name', required=True)
    industry = fields.Char(string='Industry')
    website = fields.Char(string='Website')
    phone = fields.Char(string='Phone')
    country_id = fields.Many2one('res.country', string='Country')
    address = fields.Text(string='Address')
    
    password_hash = fields.Char(string='Password Hash', copy=False)
    otp_hash = fields.Char(string='OTP Hash', copy=False)
    otp_expiry = fields.Datetime(string='OTP Expiry', copy=False)
    otp_attempts = fields.Integer(string='Verification Attempts', default=0)
    resend_count = fields.Integer(string='Resend Count', default=0)
    last_resend_time = fields.Datetime(string='Last Resend Timestamp')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Verification'),
        ('verified', 'Verified & Created'),
        ('expired', 'Expired'),
        ('failed', 'Verification Failed'),
    ], string='Status', default='pending', index=True)

    company_id = fields.Many2one('res.company', string='Created Company', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Created Administrator User', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Created Contact Partner', ondelete='set null')

    @api.model
    def hash_secret(self, secret_text):
        if not secret_text:
            return False
        return hashlib.sha256(str(secret_text).strip().encode('utf-8')).hexdigest()

    def generate_otp(self):
        """Generate a cryptographically secure 6-digit OTP code and set expiry."""
        self.ensure_one()
        otp_digits = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        self.write({
            'otp_hash': self.hash_secret(otp_digits),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=10),
            'otp_attempts': 0,
            'last_resend_time': fields.Datetime.now(),
            'state': 'pending',
        })
        return otp_digits

    def verify_otp(self, submitted_otp):
        """Verify the submitted 6-digit OTP."""
        self.ensure_one()
        if self.state == 'verified':
            return False, _('This registration has already been verified and completed.')
        if self.otp_attempts >= 5:
            self.write({'state': 'failed'})
            return False, _('Maximum verification attempts exceeded. Please restart the registration.')
        if not self.otp_expiry or fields.Datetime.now() > self.otp_expiry:
            self.write({'state': 'expired'})
            return False, _('The verification code has expired. Please request a new one.')

        # Increment attempts counter
        self.write({'otp_attempts': self.otp_attempts + 1})

        submitted_hash = self.hash_secret(submitted_otp)
        if not hmac.compare_digest(str(self.otp_hash or ''), str(submitted_hash or '')):
            remaining = max(0, 5 - self.otp_attempts)
            return False, _('Invalid verification code. %s attempts remaining.') % remaining

        return True, _('Verification successful.')
