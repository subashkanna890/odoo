import json
import re
from datetime import datetime

import pytz

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import html_escape, plaintext2html

from ..services import ai_provider
from .api import (
    PRIORITY_RANK, STATE_LABELS, avatar, check_attachment_policy, desk_api, err, fmt_dt, iso, local, ok,
    ticket_row, user_tz,
)
from .base import desk_page, system_param

VIEWS = {
    'all': ('All Tickets', lambda uid: []),
    'my_open': ('My Open Tickets', lambda uid: [('owner_id', '=', uid), ('state', '!=', 'closed')]),
    'unassigned': ('Unassigned Tickets', lambda uid: [('owner_id', '=', False), ('state', '!=', 'closed')]),
    'overdue': ('Overdue Tickets', lambda uid: [('is_overdue', '=', True)]),
    'closed': ('Closed Tickets', lambda uid: [('state', '=', 'closed')]),
    'team': ('Team Queue', lambda uid: [('team_id', 'in', request.env.user.desk_team_ids.ids), ('state', '!=', 'closed')]),
    'project': ('Project Tickets', lambda uid: [('project_id', '!=', False)]),
}
SORTS = {
    'created': 'id desc',
    'due': 'due_date asc nulls last, id desc',
    'subject': 'name asc, id desc',
    'status': 'state asc, id desc',
}
PAGE_SIZE = 50
EDITABLE_FIELDS = {'owner_id', 'state', 'project_id', 'due_date', 'priority'}
CHANNEL_ICON = {'web', 'email', 'phone', 'chat', 'whatsapp'}


def shell_props(active):
    """Props for the top bar present on every desk page."""
    user = request.env.user
    return {
        'user': {
            **avatar(user), 'email': user.email or user.login, 'role': user.desk_role,
            'title': user.desk_job_title or '', 'availability': user.desk_availability,
        },
        'active': active,
        'csrf': request.csrf_token(),
        'show_edition': system_param('show_edition') == 'True',
    }


def render_page(component, props, active, title):
    user = request.env.user
    return request.render('aixo_desk.desk_page', {
        'component': component,
        'props': json.dumps(props),
        'shell': json.dumps(shell_props(active)),
        'page_title': title,
        'prefs': {
            'theme': user.desk_theme or 'blue', 'appearance': user.desk_appearance or 'light',
            'font': user.desk_font or 'inter', 'size': user.desk_font_size or 'm',
            'light_panel': '1' if user.desk_light_panel else '0',
        },
    })


class DeskTickets(http.Controller):

    # ------------------------------------------------------------------- pages

    @http.route('/desk', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def tickets_page(self, **kw):
        return render_page('aixo_desk.TicketList', {'csrf': request.csrf_token()}, 'tickets', 'Tickets')

    @http.route('/desk/ticket/<int:ticket_id>', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def ticket_page(self, ticket_id, **kw):
        ticket = request.env['aixo.ticket'].browse(ticket_id).exists()
        if not ticket or not ticket.has_access('read'):
            return request.redirect('/desk')
        return render_page('aixo_desk.TicketDetail', {'id': ticket.id, 'csrf': request.csrf_token()},
                           'tickets', f"#{ticket.number} {ticket.name}")

    # --------------------------------------------------------------------- list

    def _ticket(self, ticket_id):
        ticket = request.env['aixo.ticket'].browse(int(ticket_id)).exists()
        if not ticket:
            raise UserError(_("This ticket no longer exists."))
        ticket.check_access('read')
        return ticket

    @http.route('/desk/api/ticket/list', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_list(self, view='all', search='', sort='created', page=1, tag_id=None, **kw):
        Ticket = request.env['aixo.ticket']
        uid = request.env.uid
        if view not in VIEWS:
            view = 'all'
        domain = list(VIEWS[view][1](uid))
        if tag_id:
            domain.append(('tag_ids', 'in', [int(tag_id)]))
        term = (search or '').strip()[:100]
        if term:
            domain += ['|', '|', ('name', 'ilike', term), ('number', 'ilike', term),
                       ('partner_id.name', 'ilike', term)]
        page = max(int(page or 1), 1)
        order = SORTS.get(sort, SORTS['created'])
        total = Ticket.search_count(domain)
        tickets = Ticket.search(domain, order=order, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        counts = {key: Ticket.search_count(fn(uid)) for key, (_label, fn) in VIEWS.items()}
        return {
            'view': view, 'title': VIEWS[view][0], 'total': total, 'page': page, 'page_size': PAGE_SIZE,
            'counts': counts, 'tickets': [ticket_row(t) for t in tickets],
            'tags': [{'id': t.id, 'name': t.name} for t in request.env['aixo.ticket.tag'].search([])],
            'agents': [avatar(a) for a in request.env['res.users'].sudo().search([('share', '=', False)])],
        }

    # ------------------------------------------------------------------- detail

    @http.route('/desk/api/ticket/get', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_get(self, id, **kw):
        return self._detail(self._ticket(id))

    def _detail(self, ticket):
        env = request.env
        user = env.user
        note = env.ref('mail.mt_note')
        Message = env['mail.message']
        messages = ticket.message_ids.filtered(
            lambda m: m.message_type in ('comment', 'email', 'email_outgoing')).sorted('id')
        # Tracking values are readable by system users only; the ticket was access-checked above.
        history = ticket.sudo().message_ids.filtered(lambda m: m.tracking_value_ids).sorted('id', reverse=True)
        Ticket = env['aixo.ticket']
        partner = ticket.partner_id
        contact_counts = {
            'open': Ticket.search_count([('partner_id', '=', partner.id), ('state', 'in', ('open', 'escalated'))]),
            'on_hold': Ticket.search_count([('partner_id', '=', partner.id), ('state', '=', 'on_hold')]),
            'closed': Ticket.search_count([('partner_id', '=', partner.id), ('state', '=', 'closed')]),
        }
        related = Ticket.search([('partner_id', '=', partner.id), ('id', '!=', ticket.id)], limit=10)
        switcher = Ticket.search([], order='id desc', limit=30)
        entries = env['aixo.time.entry'].search([('ticket_id', '=', ticket.id)])
        attachments = env['ir.attachment'].search([
            '|', '&', ('res_model', '=', 'aixo.ticket'), ('res_id', '=', ticket.id),
            '&', ('res_model', '=', 'mail.message'), ('res_id', 'in', messages.ids)])
        agents = env['res.users'].sudo().search([('share', '=', False), ('active', '=', True)])
        return {
            'ticket': {
                **ticket_row(ticket),
                'description': ticket.description or '',
                'email': ticket.email, 'phone': ticket.phone,
                'closed': ticket.state == 'closed',
                'due_input': local(ticket.due_date).strftime('%Y-%m-%dT%H:%M') if ticket.due_date else '',
                'project': {'id': ticket.project_id.id, 'name': ticket.project_id.name} if ticket.project_id else None,
                'team': ticket.team_id.name or '',
                'product': ticket.product_id.name or '',
                'classification': ticket.classification or '',
                'tags': [{'id': t.id, 'name': t.name} for t in ticket.tag_ids],
                'resolution': ticket.resolution_summary or '',
                'rating': ticket.rating,
                'sla': {
                    'first_response_deadline': iso(ticket.first_response_deadline),
                    'resolution_deadline': iso(ticket.resolution_deadline),
                    'responded_on': iso(ticket.responded_on),
                    'status': ticket.sla_status, 'paused': bool(ticket.hold_since),
                },
            },
            'contact': {**avatar(partner), 'email': partner.email, 'phone': partner.phone,
                        'account': partner.commercial_partner_id.name if partner.parent_id else '',
                        'counts': contact_counts},
            'messages': [self._message(m, note) for m in messages],
            'history': [self._history(m) for m in history],
            'time_entries': [{
                'id': e.id, 'name': e.name, 'date': fmt_dt(datetime.combine(e.date, datetime.min.time()), False),
                'date_input': str(e.date), 'hours': round(e.duration, 2), 'running': e.is_running,
                'agent': e.user_id.name, 'mine': e.user_id == user,
            } for e in entries],
            'timer': self._timer(ticket),
            'attachments': [self._attachment(a) for a in attachments],
            'related': [ticket_row(t) for t in related],
            'tasks': [{'id': t.id, 'name': t.name, 'done': t.done}
                      for t in (ticket.project_id.task_ids if ticket.project_id else [])],
            'switcher': [ticket_row(t) for t in switcher],
            'agents': [avatar(a) for a in agents],
            'projects': [{'id': p.id, 'name': p.name} for p in env['aixo.project'].search([])],
            'all_tags': [{'id': t.id, 'name': t.name} for t in env['aixo.ticket.tag'].search([])],
            'macros': self._macros(ticket),
            'me': avatar(user),
            'states': [{'value': k, 'label': v} for k, v in STATE_LABELS.items()],
        }

    def _message(self, message, note):
        author = message.author_id
        return {
            'id': message.id,
            'internal': message.subtype_id == note,
            'author': avatar(author) if author else {'id': 0, 'name': message.email_from or _("Unknown"), 'initials': '?', 'bg': '#EEF3EA', 'fg': '#62756B'},
            'date': fmt_dt(message.date),
            'iso': iso(message.date),
            'body': message.body or '',
            'attachments': [self._attachment(a) for a in message.attachment_ids],
        }

    def _history(self, message):
        return {
            'id': message.id,
            'author': message.author_id.name or _("System"),
            'date': fmt_dt(message.date),
            'changes': [{
                'field': t.field_id.field_description,
                'old': t.old_value_char or t.old_value_datetime and fmt_dt(t.old_value_datetime) or '',
                'new': t.new_value_char or t.new_value_datetime and fmt_dt(t.new_value_datetime) or '',
            } for t in message.tracking_value_ids],
        }

    def _attachment(self, attachment):
        return {
            'id': attachment.id, 'name': attachment.name, 'size': attachment.file_size,
            'url': f'/desk/attachment/{attachment.id}', 'date': fmt_dt(attachment.create_date, False),
            'by': attachment.create_uid.name,
        }

    def _macros(self, ticket):
        agent = request.env.user.name
        contact = ticket.partner_id.name.split(' ')[0] if ticket.partner_id.name else ''
        return [{
            'id': m.id, 'name': m.name, 'suggest': m.suggest, 'set_state': m.set_state or '',
            'text': m.body.replace('{contact}', contact).replace('{agent}', agent),
        } for m in request.env['aixo.macro'].search([])]

    @http.route('/desk/api/ticket/summary', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_summary(self, id, **kw):
        ticket = self._ticket(id)
        note = request.env.ref('mail.mt_note')
        bodies = ticket.message_ids.filtered(
            lambda m: m.message_type in ('comment', 'email') and m.subtype_id != note).sorted('id').mapped('body')
        return ai_provider.summarize(request.env, ticket, bodies)

    # ------------------------------------------------------------------- update

    @http.route('/desk/api/ticket/update', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_update(self, id, values=None, **kw):
        ticket = self._ticket(id)
        values = values or {}
        unknown = set(values) - EDITABLE_FIELDS
        if unknown:
            raise UserError(_("These fields cannot be edited: %s", ', '.join(sorted(unknown))))
        vals = {}
        if 'owner_id' in values:
            owner = request.env['res.users'].browse(int(values['owner_id'])) if values['owner_id'] else None
            if owner:
                ticket._check_can_assign(owner)
            vals['owner_id'] = owner.id if owner else False
        if 'state' in values:
            if values['state'] not in STATE_LABELS or values['state'] == 'closed':
                raise UserError(_("Use Close Ticket to close a ticket."))
            vals['state'] = values['state']
        if 'priority' in values:
            if values['priority'] not in PRIORITY_RANK:
                raise UserError(_("Unknown priority."))
            vals['priority'] = values['priority']
        if 'project_id' in values:
            project = request.env['aixo.project'].browse(int(values['project_id'])) if values['project_id'] else None
            if project:
                project.check_access('read')
            vals['project_id'] = project.id if project else False
        if 'due_date' in values:
            vals['due_date'] = self._parse_due(values['due_date'])
        ticket.write(vals)
        return {'ticket': ticket_row(ticket), 'due_input': local(ticket.due_date).strftime('%Y-%m-%dT%H:%M') if ticket.due_date else ''}

    def _parse_due(self, value):
        if not value:
            return False
        try:
            naive = datetime.strptime(value[:16], '%Y-%m-%dT%H:%M')
        except ValueError:
            raise UserError(_("Invalid due date."))
        return user_tz().localize(naive).astimezone(pytz.utc).replace(tzinfo=None)

    @http.route('/desk/api/ticket/tag', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_tag(self, id, add=None, remove=None, **kw):
        ticket = self._ticket(id)
        Tag = request.env['aixo.ticket.tag']
        if add:
            name = str(add).strip()[:50]
            if not name:
                raise UserError(_("Enter a tag name."))
            tag = Tag.search([('name', '=ilike', name)], limit=1) or Tag.create({'name': name})
            ticket.tag_ids = [(4, tag.id)]
        if remove:
            ticket.tag_ids = [(3, int(remove))]
        return {'tags': [{'id': t.id, 'name': t.name} for t in ticket.tag_ids]}

    # ------------------------------------------------------------------ replies

    @http.route('/desk/api/ticket/reply', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_reply(self, id, body='', internal=False, attachment_ids=None, macro_id=None, **kw):
        ticket = self._ticket(id)
        text = (body or '').strip()
        if not text:
            raise UserError(_("Write a message first."))
        attachments = self._own_attachments(ticket, attachment_ids)
        html = plaintext2html(text)
        if internal:
            message = ticket.message_post(
                body=html, message_type='comment', subtype_xmlid='mail.mt_note',
                attachment_ids=attachments.ids)
            self._notify_mentions(ticket, text)
        else:
            if not ticket.partner_id.email:
                raise UserError(_("%s has no email address. Add one before replying.", ticket.partner_id.name))
            message = ticket.message_post(
                body=html, message_type='comment', subtype_xmlid='mail.mt_comment',
                partner_ids=[ticket.partner_id.id], attachment_ids=attachments.ids,
                email_layout_xmlid='mail.mail_notification_light')
            ticket.action_mark_responded()
        if macro_id:
            macro = request.env['aixo.macro'].browse(int(macro_id)).exists()
            if macro:
                macro.sudo().usage_count += 1
                if macro.set_state == 'on_hold':
                    ticket.state = 'on_hold'
        note = request.env.ref('mail.mt_note')
        return {'message': self._message(message, note), 'ticket': ticket_row(ticket)}

    def _own_attachments(self, ticket, ids):
        attachments = request.env['ir.attachment'].browse([int(i) for i in (ids or [])]).exists()
        for attachment in attachments:
            if attachment.res_model != 'aixo.ticket' or attachment.res_id != ticket.id:
                raise UserError(_("Invalid attachment."))
        return attachments

    def _notify_mentions(self, ticket, text):
        """@mentions in internal notes notify the named employee."""
        wanted = {m.lower() for m in re.findall(r'@([\w]+(?: [\w]+)?)', text)}
        if not wanted:
            return
        Users = request.env['res.users'].sudo()
        for user in Users.search([('share', '=', False), ('active', '=', True)]):
            full = user.name.lower()
            first = full.split(' ')[0]
            if user != request.env.user and (full in wanted or any(w == first or w.startswith(full) for w in wanted)):
                request.env['aixo.notification']._notify(
                    user, 'mention',
                    _("%(who)s mentioned you in a comment on #%(number)s “%(name)s”",
                      who=request.env.user.name, number=ticket.number, name=ticket.name),
                    ticket)

    # -------------------------------------------------------------- close/reopen

    @http.route('/desk/api/ticket/close', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_close(self, id, summary='', notify=False, **kw):
        ticket = self._ticket(id)
        text = (summary or '').strip()
        if not text:
            raise UserError(_("A resolution summary is required to close a ticket."))
        request.env['aixo.time.entry'].search(
            [('ticket_id', '=', ticket.id), ('timer_start', '!=', False)]).action_pause()
        html = plaintext2html(text)
        ticket.action_close(html, bool(notify))
        if notify and ticket.partner_id.email:
            ticket.message_post(
                body=html, message_type='comment', subtype_xmlid='mail.mt_comment',
                partner_ids=[ticket.partner_id.id], email_layout_xmlid='mail.mail_notification_light')
        return {'ticket': ticket_row(ticket), 'resolution': ticket.resolution_summary}

    @http.route('/desk/api/ticket/reopen', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def ticket_reopen(self, id, **kw):
        ticket = self._ticket(id)
        ticket.action_reopen()
        return {'ticket': ticket_row(ticket)}

    # --------------------------------------------------------------------- time

    def _timer(self, ticket):
        entries = request.env['aixo.time.entry'].search(
            [('ticket_id', '=', ticket.id), ('user_id', '=', request.env.uid)])
        running = entries.filtered('timer_start')[:1]
        return {
            'running': bool(running),
            'started': iso(running.timer_start) if running else None,
            'base_seconds': int(round(sum(entries.mapped('duration')) * 3600)),
        }

    @http.route('/desk/api/timer/start', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def timer_start(self, id, **kw):
        ticket = self._ticket(id)
        if ticket.state == 'closed':
            raise UserError(_("Reopen the ticket to track time."))
        entry = request.env['aixo.time.entry'].create({'ticket_id': ticket.id, 'name': _("Timer")})
        entry.action_start()
        return {'timer': self._timer(ticket)}

    @http.route('/desk/api/timer/pause', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def timer_pause(self, id, **kw):
        ticket = self._ticket(id)
        request.env['aixo.time.entry'].search(
            [('ticket_id', '=', ticket.id), ('user_id', '=', request.env.uid), ('timer_start', '!=', False)]).action_pause()
        return {'timer': self._timer(ticket), 'time_entries': self._detail(ticket)['time_entries']}

    def _entry_values(self, values):
        try:
            hours = float(values.get('hours'))
        except (TypeError, ValueError):
            raise UserError(_("Enter the time spent in hours."))
        if hours < 0 or hours > 24 * 31:
            raise UserError(_("That duration is not valid."))
        name = (values.get('name') or '').strip()[:200] or _("Work on ticket")
        try:
            day = fields.Date.to_date(values.get('date')) or fields.Date.context_today(request.env.user)
        except ValueError:
            raise UserError(_("Invalid date."))
        return {'name': name, 'duration': hours, 'date': day}

    @http.route('/desk/api/time/save', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def time_save(self, id, entry_id=None, values=None, **kw):
        ticket = self._ticket(id)
        vals = self._entry_values(values or {})
        Entry = request.env['aixo.time.entry']
        if entry_id:
            entry = Entry.browse(int(entry_id))
            if entry.ticket_id != ticket or entry.user_id != request.env.user:
                raise UserError(_("You can only change your own entries."))
            entry.write(vals)
        else:
            Entry.create({'ticket_id': ticket.id, **vals})
        return {'time_entries': self._detail(ticket)['time_entries'], 'timer': self._timer(ticket)}

    @http.route('/desk/api/time/delete', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def time_delete(self, id, entry_id, **kw):
        ticket = self._ticket(id)
        entry = request.env['aixo.time.entry'].browse(int(entry_id))
        if entry.ticket_id != ticket or entry.user_id != request.env.user:
            raise UserError(_("You can only delete your own entries."))
        entry.unlink()
        return {'time_entries': self._detail(ticket)['time_entries'], 'timer': self._timer(ticket)}

    # -------------------------------------------------------------- attachments

    @http.route('/desk/ticket/<int:ticket_id>/attach', type='http', auth='public', methods=['POST'], website=True)
    def attach(self, ticket_id, **kw):
        user = request.env.user
        if user._is_public() or user.desk_role not in ('agent', 'admin'):
            return self._json_response(err(_("You don't have access to this."), 'forbidden'), 403)
        try:
            ticket = self._ticket(ticket_id)
            uploaded = []
            for upload in request.httprequest.files.getlist('file'):
                data = upload.read()
                check_attachment_policy(upload.filename or 'file', len(data))
                attachment = request.env['ir.attachment'].create({
                    'name': upload.filename or 'file', 'raw': data, 'res_model': 'aixo.ticket',
                    'res_id': ticket.id, 'mimetype': upload.mimetype or 'application/octet-stream',
                })
                uploaded.append(self._attachment(attachment))
            return self._json_response(ok({'attachments': uploaded}))
        except UserError as exc:
            return self._json_response(err(str(exc.args[0])), 400)
        except Exception as exc:  # AccessError and friends
            if exc.__class__.__name__ == 'AccessError':
                return self._json_response(err(_("You don't have access to this."), 'forbidden'), 403)
            raise

    def _json_response(self, payload, status=200):
        return request.make_json_response(payload, status=status)

    @http.route('/desk/attachment/<int:attachment_id>', type='http', auth='public', website=True)
    def download(self, attachment_id, **kw):
        user = request.env.user
        if user._is_public():
            return request.redirect('/desk/login')
        # Looked up with sudo so the ticket (not the attachment ACL) decides access, as for agents.
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if not attachment:
            raise request.not_found()
        ticket = self._attachment_ticket(attachment)
        if not ticket or not ticket.has_access('read'):
            raise request.not_found()
        if user.desk_role == 'customer' and not self._customer_may_download(attachment, user):
            raise request.not_found()
        stream = request.env['ir.binary']._get_stream_from(attachment.sudo(), 'raw')
        return stream.get_response(as_attachment=True)

    def _customer_may_download(self, attachment, user):
        """Customers get their own uploads and files on public messages, never internal ones."""
        if attachment.description == f'portal-upload:{user.id}':
            return True
        if attachment.res_model == 'mail.message':
            message = request.env['mail.message'].sudo().browse(attachment.res_id)
            return message.subtype_id != request.env.ref('mail.mt_note')
        # Files linked to a message through the many2many field live on the ticket.
        messages = request.env['mail.message'].sudo().search([('attachment_ids', 'in', attachment.id)])
        return bool(messages) and all(m.subtype_id != request.env.ref('mail.mt_note') for m in messages)

    def _attachment_ticket(self, attachment):
        Ticket = request.env['aixo.ticket']
        if attachment.res_model == 'aixo.ticket':
            return Ticket.browse(attachment.res_id).exists()
        if attachment.res_model == 'mail.message':
            message = request.env['mail.message'].sudo().browse(attachment.res_id).exists()
            if message and message.model == 'aixo.ticket':
                return Ticket.browse(message.res_id).exists()
        return Ticket
