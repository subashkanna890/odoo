from datetime import timedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import plaintext2html

from .api import avatar, check_attachment_policy, desk_api, err, fmt_dt, human_ago, iso, ok
from .base import desk_page, system_param
from .tickets import render_page

VIEWS = [('all', 'All my tickets'), ('open', 'Open requests'), ('waiting', 'Waiting for my reply'), ('resolved', 'Resolved')]
VIEW_DOMAIN = {
    'all': [], 'open': [('state', '!=', 'closed')], 'waiting': [('state', '=', 'on_hold')],
    'resolved': [('state', '=', 'closed')],
}
RATINGS = ('good', 'okay', 'bad')
RATING_LABEL = {'good': 'Good', 'okay': 'Okay', 'bad': 'Bad'}


def customer_status(ticket):
    """(label, css class) as the customer sees it; the owner name is read with sudo on purpose."""
    if ticket.state == 'closed':
        return 'Resolved', 'is-closed'
    if ticket.state == 'on_hold':
        return 'Waiting for you', 'is-hold'
    return ('In progress', 'is-progress') if ticket.sudo().owner_id else ('Open', 'is-open')


def customer_row(ticket):
    label, css = customer_status(ticket)
    owner = ticket.sudo().owner_id
    return {
        'id': ticket.id, 'number': ticket.number, 'subject': ticket.name, 'channel': ticket.channel,
        'created': human_ago(ticket.create_date) if (fields.Datetime.now() - ticket.create_date).days < 1 else fmt_dt(ticket.create_date, False),
        'updated': human_ago(ticket.write_date),
        'agent': owner.name if owner else _("Not yet assigned"),
        'agent_avatar': avatar(owner) if owner else None,
        'status': label, 'status_class': css, 'closed': ticket.state == 'closed',
    }


def reopen_days():
    return int(system_param('reopen_days', '7') or 7)


class DeskCustomer(http.Controller):

    # -------------------------------------------------------------------- pages

    @http.route('/desk/my', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['customer'])
    def home_page(self, **kw):
        return render_page('aixo_desk.CustomerHome', {}, 'requests', 'My requests')

    @http.route('/desk/my/ticket/<int:ticket_id>', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['customer'])
    def ticket_page(self, ticket_id, **kw):
        ticket = request.env['aixo.ticket'].browse(ticket_id).exists()
        if not ticket or not ticket.has_access('read'):
            return request.redirect('/desk/my')
        return render_page('aixo_desk.CustomerTicket', {'id': ticket.id, 'csrf': request.csrf_token()},
                           'requests', f"#{ticket.number} {ticket.name}")

    @http.route('/desk/my/projects', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['customer'])
    def projects_page(self, **kw):
        return render_page('aixo_desk.CustomerProjects', {}, 'projects', 'Projects')

    # --------------------------------------------------------------------- home

    def _help_links(self):
        support = system_param('support_email')
        chat = False
        if 'im_livechat.channel' in request.env:
            channel = request.env['im_livechat.channel'].sudo().search([], limit=1)
            if channel:
                chat = f"/im_livechat/support/{channel.id}"
        return {
            'kb': system_param('kb_url') or '',
            'chat': chat or (f"mailto:{support}" if support else ''),
            'chat_is_email': not chat,
        }

    @http.route('/desk/api/my/home', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def home(self, view='all', search='', **kw):
        user = request.env.user
        Ticket = request.env['aixo.ticket']
        domain = list(VIEW_DOMAIN.get(view, []))
        term = (search or '').strip()[:100]
        if term:
            domain += ['|', ('name', 'ilike', term), ('number', 'ilike', term)]
        tickets = Ticket.search(domain, order='write_date desc, id desc', limit=100)
        partner = user.partner_id
        plan = (partner.commercial_partner_id or partner).desk_plan or 'free'
        counts = {key: Ticket.search_count(dom) for key, dom in VIEW_DOMAIN.items()}
        return {
            'name': user.name, 'company': partner.parent_id.name or '', 'plan': plan,
            'plan_label': 'Paid' if plan == 'paid' else 'Free',
            'views': [{'key': k, 'label': v, 'count': counts[k]} for k, v in VIEWS], 'view': view,
            'counts': counts, 'tickets': [customer_row(t) for t in tickets], 'help': self._help_links(),
            'projects': request.env['aixo.project'].search_count([]),
        }

    # ------------------------------------------------------------------- detail

    def _ticket(self, ticket_id):
        ticket = request.env['aixo.ticket'].browse(int(ticket_id)).exists()
        if not ticket:
            raise UserError(_("This request no longer exists."))
        ticket.check_access('read')
        return ticket

    def _message(self, message):
        author = message.author_id
        mine = author == request.env.user.partner_id
        return {
            'id': message.id, 'mine': mine, 'author': avatar(author) if author else {'name': '', 'initials': '?', 'bg': '#EEF3EA', 'fg': '#62756B'},
            'date': fmt_dt(message.date), 'body': message.body or '',
            'attachments': [{'id': a.id, 'name': a.name, 'url': f'/desk/attachment/{a.id}'} for a in message.attachment_ids],
        }

    def _can_reopen(self, ticket):
        return ticket.state == 'closed' and bool(ticket.closed_on) and \
            fields.Datetime.now() - ticket.closed_on <= timedelta(days=reopen_days())

    @http.route('/desk/api/my/ticket', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def ticket(self, id, **kw):
        ticket = self._ticket(id)
        label, css = customer_status(ticket)
        note = request.env.ref('mail.mt_note')
        # Messages are read with sudo only after the ticket passed the customer's record rule,
        # and internal notes and tracking messages are filtered out explicitly.
        messages = ticket.sudo().message_ids.filtered(
            lambda m: m.message_type in ('comment', 'email', 'email_outgoing') and m.subtype_id != note).sorted('id')
        row = customer_row(ticket)
        return {
            'ticket': {**row, 'description': ticket.description or '', 'priority': ticket.priority,
                       'resolution': ticket.resolution_summary if ticket.state == 'closed' else '',
                       'rating': ticket.rating or '', 'rating_comment': ticket.rating_comment or '',
                       'waiting': ticket.state == 'on_hold'},
            'messages': [self._message(m) for m in messages],
            'requester': avatar(ticket.partner_id),
            'can_reply': True, 'can_close': ticket.state != 'closed', 'can_reopen': self._can_reopen(ticket),
            'reopen_days': reopen_days(), 'csat': system_param('csat_enabled') == 'True',
            'max_mb': int(system_param('attachment_max_mb') or 40),
        }

    def _own_attachments(self, ticket, ids):
        attachments = request.env['ir.attachment'].sudo().browse([int(i) for i in (ids or [])]).exists()
        for attachment in attachments:
            if (attachment.res_model != 'aixo.ticket' or attachment.res_id != ticket.id
                    or attachment.description != f'portal-upload:{request.env.uid}'):
                raise UserError(_("Invalid attachment."))
        return attachments

    @http.route('/desk/api/my/reply', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def reply(self, id, body='', attachment_ids=None, **kw):
        ticket = self._ticket(id)
        text = (body or '').strip()
        if not text:
            raise UserError(_("Write a message first."))
        if ticket.state == 'closed':
            if not self._can_reopen(ticket):
                raise UserError(_("This request was closed more than %s days ago. Please raise a new request.", reopen_days()))
        attachments = self._own_attachments(ticket, attachment_ids)
        # The customer already passed the ticket record rule; the message is posted as them (author fixed),
        # with sudo only because portal users cannot write chatter on internal models.
        message = ticket.sudo().message_post(
            body=plaintext2html(text), message_type='comment', subtype_xmlid='mail.mt_comment',
            author_id=request.env.user.partner_id.id, attachment_ids=attachments.ids)
        # message_post only keeps attachments it created itself, so link the validated ones explicitly
        if attachments:
            message.sudo().attachment_ids = [(4, a.id) for a in attachments]
        if ticket.state in ('closed', 'on_hold'):
            ticket.sudo().write({'state': 'open'})
        if ticket.sudo().owner_id:
            request.env['aixo.notification']._notify(
                ticket.sudo().owner_id, 'reply',
                _("%(who)s replied to #%(number)s “%(name)s”", who=ticket.partner_id.name, number=ticket.number, name=ticket.name),
                ticket.sudo())
        return {'message': self._message(message), 'ticket': customer_row(ticket)}

    @http.route('/desk/api/my/close', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def close(self, id, **kw):
        ticket = self._ticket(id)
        if ticket.state == 'closed':
            raise UserError(_("This request is already resolved."))
        # Customers cannot write the resolution; a system note records who closed it.
        ticket.sudo().write({'state': 'closed', 'resolution_summary': _("<p>Marked as resolved by the customer.</p>")})
        return {'ticket': customer_row(ticket), 'can_reopen': self._can_reopen(ticket), 'csat': system_param('csat_enabled') == 'True'}

    @http.route('/desk/api/my/reopen', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def reopen(self, id, **kw):
        ticket = self._ticket(id)
        if not self._can_reopen(ticket):
            raise UserError(_("This request can no longer be reopened. Please raise a new request."))
        ticket.sudo().write({'state': 'open', 'rating': False, 'rating_comment': False})
        return {'ticket': customer_row(ticket)}

    @http.route('/desk/api/my/rate', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def rate(self, id, rating, comment='', **kw):
        ticket = self._ticket(id)
        if ticket.state != 'closed':
            raise UserError(_("You can rate a request once it is resolved."))
        if rating not in RATINGS:
            raise UserError(_("Choose Good, Okay or Bad."))
        ticket.sudo().write({'rating': rating, 'rating_comment': (comment or '').strip()[:500] or False})
        return {'rating': rating}

    # -------------------------------------------------------------- attachments

    @http.route('/desk/my/ticket/<int:ticket_id>/attach', type='http', auth='public', methods=['POST'], website=True)
    def attach(self, ticket_id, **kw):
        user = request.env.user
        if user._is_public() or user.desk_role != 'customer':
            return request.make_json_response(err(_("You don't have access to this."), 'forbidden'), status=403)
        try:
            ticket = self._ticket(ticket_id)
            uploaded = []
            for upload in request.httprequest.files.getlist('file'):
                data = upload.read()
                check_attachment_policy(upload.filename or 'file', len(data))
                attachment = request.env['ir.attachment'].sudo().create({
                    'name': upload.filename or 'file', 'raw': data, 'res_model': 'aixo.ticket', 'res_id': ticket.id,
                    'description': f'portal-upload:{user.id}',
                    'mimetype': upload.mimetype or 'application/octet-stream'})
                uploaded.append({'id': attachment.id, 'name': attachment.name, 'size': attachment.file_size})
            return request.make_json_response(ok({'attachments': uploaded}))
        except AccessError:  # a subclass of UserError, so it must come first
            return request.make_json_response(err(_("You don't have access to this."), 'forbidden'), status=403)
        except UserError as exc:
            return request.make_json_response(err(str(exc.args[0])), status=400)

    # ----------------------------------------------------------------- projects

    @http.route('/desk/api/my/projects', type='jsonrpc', auth='public')
    @desk_api(roles=['customer'])
    def projects(self, **kw):
        projects = request.env['aixo.project'].search([], order='code desc')
        return {'projects': [{
            'id': p.id, 'code': p.code, 'name': p.name, 'state': p.state, 'state_label': dict(p._fields['state'].selection)[p.state],
            'due': fmt_dt(fields.Datetime.to_datetime(p.date_due), False) if p.date_due else '',
            'progress': p.progress, 'tasks_done': p.task_done_count, 'tasks_total': p.task_count,
            'tasks': [{'id': t.id, 'name': t.name, 'done': t.done} for t in p.task_ids],
            'milestones': [{'id': m.id, 'name': m.name, 'reached': m.reached,
                            'date': fmt_dt(fields.Datetime.to_datetime(m.date), False) if m.date else ''} for m in p.milestone_ids],
        } for p in projects]}


class DeskCsat(http.Controller):
    """One-click satisfaction links from the closing email. The access token is the credential."""

    def _ticket(self, token):
        if not token:
            return request.env['aixo.ticket']
        return request.env['aixo.ticket'].sudo().search([('access_token', '=', token)], limit=1)

    def _page(self, ticket, **values):
        return request.render('aixo_desk.csat_page', {
            'ticket': ticket, 'labels': RATING_LABEL, 'token': ticket.access_token, **values})

    @http.route('/desk/csat/<string:token>/<string:score>', type='http', auth='public', website=True, sitemap=False)
    def rate_link(self, token, score, **kw):
        ticket = self._ticket(token)
        if not ticket or score not in RATINGS:
            raise request.not_found()
        if ticket.state != 'closed':
            return self._page(ticket, status='open')
        if not ticket.rating:
            ticket.rating = score
            return self._page(ticket, status='thanks', score=score)
        return self._page(ticket, status='already', score=ticket.rating)

    @http.route('/desk/csat/<string:token>', type='http', auth='public', website=True, sitemap=False, methods=['POST'])
    def rate_change(self, token, score=None, comment='', **kw):
        ticket = self._ticket(token)
        if not ticket or ticket.state != 'closed':
            raise request.not_found()
        if score in RATINGS:
            ticket.rating = score
        ticket.rating_comment = (comment or '').strip()[:500] or ticket.rating_comment
        return self._page(ticket, status='thanks', score=ticket.rating)
