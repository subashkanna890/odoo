from odoo import api, fields, models


class AixoNotification(models.Model):
    _name = 'aixo.notification'
    _description = 'Aixo Desk Notification'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    type = fields.Selection(
        [('assign', 'Assignment'), ('mention', 'Mention'), ('sla', 'SLA'),
         ('reply', 'Reply'), ('email_failure', 'Email failure')],
        required=True)
    text = fields.Char(required=True)
    ticket_id = fields.Many2one('aixo.ticket', ondelete='cascade', index=True)
    is_read = fields.Boolean(default=False, index=True)
    flagged = fields.Boolean(default=False)
    failure_recipient = fields.Char(help="Address the failed email was sent to.")

    @api.model
    def _notify(self, users, notif_type, text, ticket=None, **extra):
        """Create a notification per user and push it live on the bus.

        Creation is sudo on purpose: system events notify other people, and the
        record rule only lets each user read their own notifications.
        """
        created = self.sudo().browse()
        for user in users:
            notification = self.sudo().create({
                'user_id': user.id,
                'type': notif_type,
                'text': text,
                'ticket_id': ticket.id if ticket else False,
                **extra,
            })
            user.partner_id._bus_send('aixo_desk/notification', notification._to_payload())
            created |= notification
        return created

    def _to_payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'type': self.type,
            'text': self.text,
            'ticket_id': self.ticket_id.id,
            'is_read': self.is_read,
            'flagged': self.flagged,
            'create_date': fields.Datetime.to_string(self.create_date),
        }

    def action_mark_read(self):
        self.write({'is_read': True})

    def action_toggle_flag(self):
        for notification in self:
            notification.flagged = not notification.flagged
