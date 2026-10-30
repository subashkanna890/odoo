import hmac
import secrets
from datetime import timedelta

from odoo import api, fields, models

OTP_TTL = timedelta(minutes=10)
OTP_RESEND_AFTER = timedelta(seconds=30)
OTP_MAX_ATTEMPTS = 5


class AixoOtp(models.Model):
    _name = 'aixo.otp'
    _description = 'Aixo Password Reset Code'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    code_hash = fields.Char(required=True)
    expires_at = fields.Datetime(required=True)
    attempts = fields.Integer(default=0)
    last_sent = fields.Datetime(required=True, default=fields.Datetime.now)
    used = fields.Boolean(default=False)
    verified = fields.Boolean(default=False)

    def _hash(self, user, code):
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret') or ''
        message = f"{user.id}:{code}".encode()
        return hmac.new(secret.encode(), message, 'sha256').hexdigest()

    @api.model
    def issue(self, user):
        """Create a fresh 6-digit code for ``user``.

        Returns ``(code, record)`` or ``(None, record)`` when a code was sent less
        than 30 seconds ago. Callers must respond identically either way so the
        endpoint cannot be used to probe which accounts exist.
        """
        now = fields.Datetime.now()
        otp_model = self.sudo()
        last = otp_model.search([('user_id', '=', user.id)], limit=1)
        if last and now - last.last_sent < OTP_RESEND_AFTER:
            return None, last
        otp_model.search([('user_id', '=', user.id), ('used', '=', False)]).write({'used': True})
        code = f"{secrets.randbelow(10 ** 6):06d}"
        record = otp_model.create({
            'user_id': user.id,
            'code_hash': self._hash(user, code),
            'expires_at': now + OTP_TTL,
            'last_sent': now,
        })
        return code, record

    @api.model
    def verify(self, user, code):
        """Check ``code``. Returns the matching record on success, else ``None``.

        A wrong code consumes one of the five attempts; after that, or after the
        10 minute expiry, the code is dead and a new one must be requested.
        """
        now = fields.Datetime.now()
        record = self.sudo().search(
            [('user_id', '=', user.id), ('used', '=', False)], limit=1)
        if not record or record.expires_at < now or record.attempts >= OTP_MAX_ATTEMPTS:
            return None
        if hmac.compare_digest(record.code_hash, self._hash(user, code or '')):
            record.verified = True
            return record
        record.attempts += 1
        return None

    def consume(self):
        self.write({'used': True})

    @api.autovacuum
    def _gc_otp(self):
        limit = fields.Datetime.now() - timedelta(days=1)
        self.sudo().search([('create_date', '<', limit)]).unlink()
