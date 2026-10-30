from datetime import timedelta

from odoo import api, fields, models


class AixoRateLimit(models.Model):
    """Failure counters used to throttle login, OTP and sign-up endpoints.

    Kept in the database (not in memory) so limits hold across workers.
    """
    _name = 'aixo.rate.limit'
    _description = 'Aixo Desk Rate Limit'

    kind = fields.Char(required=True, index=True)
    key = fields.Char(required=True, index=True)
    count = fields.Integer(default=0)
    window_start = fields.Datetime(required=True, default=fields.Datetime.now)
    locked_until = fields.Datetime()

    _kind_key_uniq = models.Constraint('unique (kind, key)', 'One counter per kind and key.')

    @api.model
    def _get(self, kind, key):
        return self.sudo().search([('kind', '=', kind), ('key', '=', key)], limit=1)

    @api.model
    def is_locked(self, kind, key):
        record = self._get(kind, key)
        return bool(record and record.locked_until and record.locked_until > fields.Datetime.now())

    @api.model
    def hit(self, kind, key, limit, window=timedelta(minutes=15), lock=timedelta(minutes=15)):
        """Count one event. Returns True when the caller is (now) over the limit.

        More than ``limit`` events inside ``window`` lock the key for ``lock``.
        """
        now = fields.Datetime.now()
        record = self._get(kind, key)
        if not record:
            record = self.sudo().create({'kind': kind, 'key': key, 'count': 1, 'window_start': now})
        else:
            if record.locked_until and record.locked_until > now:
                return True
            if now - record.window_start > window:
                record.write({'count': 1, 'window_start': now, 'locked_until': False})
            else:
                record.count += 1
        if record.count >= limit:
            record.locked_until = now + lock
            return True
        return False

    @api.model
    def reset(self, kind, key):
        self._get(kind, key).unlink()

    @api.model
    def minutes_left(self, kind, key):
        record = self._get(kind, key)
        if not (record and record.locked_until):
            return 0
        return max(1, int((record.locked_until - fields.Datetime.now()).total_seconds() // 60) + 1)

    @api.autovacuum
    def _gc_rate_limits(self):
        limit = fields.Datetime.now() - timedelta(days=2)
        self.sudo().search([('write_date', '<', limit)]).unlink()
