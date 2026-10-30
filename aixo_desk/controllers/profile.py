from odoo import _
from odoo.exceptions import UserError
from odoo.http import Controller, request, route

from .api import avatar, desk_api, fmt_dt, iso

THEMES = ('red', 'green', 'blue', 'yellow', 'orange')
APPEARANCES = ('light', 'night', 'auto')
FONTS = ('inter', 'roboto', 'lato', 'open_sans', 'poppins')
SIZES = ('xs', 's', 'm', 'l', 'xl')
CHANNELS = ('email', 'chat', 'phone')
CHANNEL_STATES = ('online', 'away', 'offline')
NOTIFICATION_FILTERS = {
    'all': [],
    'unread': [('is_read', '=', False)],
    'mentions': [('type', '=', 'mention')],
    'assignments': [('type', '=', 'assign')],
    'flagged': [('flagged', '=', True)],
}
# Preference toggles shown in the drawer: key -> default
PREF_DEFAULTS = {
    'tdp0': False, 'tdp1': True, 'tdp2': True,
    'dvp0': True, 'dvp1': True, 'dvp2': True,
    'acc0': False, 'acc1': False, 'acc2': False,
    'ess0': True, 'ess1': True,
}


def notification_dict(n):
    return {
        'id': n.id, 'type': n.type, 'text': n.text, 'ticket_id': n.ticket_id.id,
        'is_read': n.is_read, 'flagged': n.flagged, 'when': fmt_dt(n.create_date),
        'failure_recipient': n.failure_recipient or '',
    }


class DeskProfile(Controller):

    # ------------------------------------------------------------ notifications

    @route('/desk/api/notifications/list', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def notifications_list(self, filter='all', **kw):
        Notification = request.env['aixo.notification']
        domain = list(NOTIFICATION_FILTERS.get(filter, []))
        failures = Notification.search([('type', '=', 'email_failure')], limit=50)
        items = Notification.search(domain + [('type', '!=', 'email_failure')], limit=100)
        return {
            'items': [notification_dict(n) for n in items],
            'failures': [notification_dict(n) for n in failures],
            'unread': Notification.search_count([('is_read', '=', False)]),
        }

    @route('/desk/api/notifications/unread', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def notifications_unread(self, **kw):
        return {'unread': request.env['aixo.notification'].search_count([('is_read', '=', False)])}

    def _own(self, notification_id):
        notification = request.env['aixo.notification'].browse(int(notification_id)).exists()
        if not notification:
            raise UserError(_("This notification no longer exists."))
        return notification

    @route('/desk/api/notifications/read', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def notifications_read(self, id=None, **kw):
        if id:
            self._own(id).action_mark_read()
        else:
            request.env['aixo.notification'].search([('is_read', '=', False)]).action_mark_read()
        return {'unread': request.env['aixo.notification'].search_count([('is_read', '=', False)])}

    @route('/desk/api/notifications/flag', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def notifications_flag(self, id, **kw):
        notification = self._own(id)
        notification.action_toggle_flag()
        return {'flagged': notification.flagged}

    @route('/desk/api/notifications/retry', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def notifications_retry(self, id, email=None, **kw):
        """Retry sending the failed mails of the ticket, optionally after fixing the recipient."""
        notification = self._own(id)
        if notification.type != 'email_failure' or not notification.ticket_id:
            raise UserError(_("Nothing to retry."))
        ticket = notification.ticket_id
        if email:
            address = email.strip()
            if '@' not in address:
                raise UserError(_("Enter a valid email address."))
            # Agents cannot edit contacts in general; fixing the recipient of a ticket
            # they can modify is the one case allowed, so sudo is limited to that field.
            ticket.check_access('write')
            ticket.partner_id.sudo().write({'email': address})
        mails = request.env['mail.mail'].sudo().search([
            ('model', '=', 'aixo.ticket'), ('res_id', '=', ticket.id), ('state', 'in', ('exception', 'cancel'))])
        mails.write({'state': 'outgoing'})
        mails.send(raise_exception=False)
        sent = len(mails.filtered(lambda m: m.exists() and m.state == 'sent')) or len(mails) - len(mails.exists())
        notification.action_mark_read()
        return {'retried': len(mails), 'sent': sent}

    # ------------------------------------------------------------------ profile

    def _profile(self, user):
        status = user.desk_channel_status or {}
        return {
            **avatar(user), 'email': user.email or user.login, 'title': user.desk_job_title or '',
            'role': user.desk_role, 'availability': user.desk_availability,
            'channels': {c: status.get(c, 'online') for c in CHANNELS},
            'office_phone': user.desk_office_phone or '', 'extension': user.desk_extension or '',
            'hours': user.desk_hours_id.name or '',
        }

    @route('/desk/api/profile/get', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def profile_get(self, **kw):
        return self._profile(request.env.user)

    @route('/desk/api/profile/status', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def profile_status(self, availability=None, channel=None, state=None, **kw):
        # A user may always edit their own presence; sudo is limited to their own row.
        user = request.env.user.sudo()
        if availability:
            if availability not in ('online', 'away', 'offline'):
                raise UserError(_("Unknown status."))
            user.desk_availability = availability
        if channel:
            if channel not in CHANNELS or state not in CHANNEL_STATES:
                raise UserError(_("Unknown channel status."))
            status = dict(user.desk_channel_status or {})
            status[channel] = state
            user.desk_channel_status = status
        return self._profile(user)

    # -------------------------------------------------------------- preferences

    def _prefs(self, user):
        saved = user.desk_prefs or {}
        return {
            'appearance': user.desk_appearance, 'light_panel': user.desk_light_panel,
            'theme': user.desk_theme, 'font': user.desk_font, 'size': user.desk_font_size,
            'toggles': {key: saved.get(key, default) for key, default in PREF_DEFAULTS.items()},
        }

    @route('/desk/api/prefs/get', type='jsonrpc', auth='public')
    @desk_api(roles=['agent', 'customer'])
    def prefs_get(self, **kw):
        return self._prefs(request.env.user)

    @route('/desk/api/prefs/save', type='jsonrpc', auth='public')
    @desk_api(roles=['agent', 'customer'])
    def prefs_save(self, values=None, **kw):
        values = values or {}
        user = request.env.user.sudo()  # own row only
        vals = {}
        choices = {'appearance': ('desk_appearance', APPEARANCES), 'theme': ('desk_theme', THEMES),
                   'font': ('desk_font', FONTS), 'size': ('desk_font_size', SIZES)}
        for key, (field, allowed) in choices.items():
            if key in values:
                if values[key] not in allowed:
                    raise UserError(_("Invalid value for %s.", key))
                vals[field] = values[key]
        if 'light_panel' in values:
            vals['desk_light_panel'] = bool(values['light_panel'])
        if 'toggles' in values:
            current = dict(user.desk_prefs or {})
            for key, value in (values['toggles'] or {}).items():
                if key in PREF_DEFAULTS:
                    current[key] = bool(value)
            vals['desk_prefs'] = current
        user.write(vals)
        return self._prefs(user)
