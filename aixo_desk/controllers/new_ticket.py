from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import html2plaintext, plaintext2html

from ..models.ticket import CHANNELS, CLASSIFICATIONS, PRIORITIES
from .api import avatar, check_attachment_policy, desk_api, err, ok, ticket_row
from .base import clean_email, desk_page, valid_email
from .tickets import render_page

CREATE_STATES = ('open', 'on_hold', 'escalated')


def contact_card(partner):
    """Contact summary shown beside the form: counts are scoped by the caller's ticket rules."""
    Ticket = request.env['aixo.ticket']
    tickets = Ticket.search([('partner_id', '=', partner.id)], order='id desc')
    rated = [t.rating for t in tickets if t.rating]
    score = {'good': 100, 'okay': 50, 'bad': 0}
    return {
        **avatar(partner), 'account': partner.parent_id.name or '', 'email': partner.email or '',
        'phone': partner.phone or '', 'open': len(tickets.filtered(lambda t: t.state != 'closed')),
        'closed': len(tickets.filtered(lambda t: t.state == 'closed')),
        'happy': round(sum(score[r] for r in rated) / len(rated)) if rated else None,
        'last': tickets[:1].name or '',
    }


class DeskNewTicket(http.Controller):

    @http.route('/desk/ticket/new', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['admin', 'customer'])
    def page(self, partner=None, **kw):
        props = {'csrf': request.csrf_token(), 'partner': int(partner) if (partner or '').isdigit() else 0}
        return render_page('aixo_desk.NewTicket', props, 'tickets', 'New ticket')

    @http.route('/desk/api/newticket/options', type='jsonrpc', auth='public')
    @desk_api(roles=['admin', 'customer'])
    def options(self, partner_id=None, **kw):
        env = request.env
        user = env.user
        customer = user.desk_role == 'customer'
        data = {
            'mode': 'customer' if customer else 'admin',
            'templates': [{
                'id': t.id, 'name': t.name, 'prefix': t.subject_prefix or '',
                'description': html2plaintext(t.description or '').strip(),
                'priority': t.priority or '', 'classification': t.classification or '',
            } for t in env['aixo.ticket.template'].search([])],
            'languages': [{'id': lang.id, 'name': lang.name} for lang in env['res.lang'].sudo().search([])],
            'priorities': [{'value': k, 'label': v} for k, v in PRIORITIES],
            'classifications': [{'value': k, 'label': v} for k, v in CLASSIFICATIONS],
            'channels': [{'value': k, 'label': v} for k, v in CHANNELS],
            'max_mb': int(env['ir.config_parameter'].sudo().get_param('aixo_desk.attachment_max_mb') or 40),
        }
        if customer:
            data['contact'] = contact_card(user.partner_id)
        else:
            data.update(
                products=[{'id': p.id, 'name': p.name} for p in env['aixo.product'].search([])],
                projects=[{'id': p.id, 'name': p.name} for p in env['aixo.project'].search([])],
                agents=[avatar(a) for a in env['res.users'].sudo().search([('share', '=', False)])],
                states=[{'value': 'open', 'label': 'Open'}, {'value': 'on_hold', 'label': 'On Hold'},
                        {'value': 'escalated', 'label': 'Escalated'}],
                me=user.id,
            )
            if partner_id:
                partner = env['res.partner'].browse(int(partner_id)).exists()
                data['contact'] = contact_card(partner) if partner else None
        return data

    @http.route('/desk/api/contact/search', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def contact_search(self, q='', **kw):
        term = (q or '').strip()[:60]
        if not term:
            return {'contacts': []}
        partners = request.env['res.partner'].search(
            [('is_company', '=', False), '|', ('name', 'ilike', term), ('email', 'ilike', term)], limit=8)
        return {'contacts': [contact_card(p) for p in partners]}

    @http.route('/desk/api/newticket/create', type='jsonrpc', auth='public')
    @desk_api(roles=['admin', 'customer'])
    def create(self, values=None, **kw):
        env = request.env
        user = env.user
        customer = user.desk_role == 'customer'
        values = values or {}
        subject = (values.get('subject') or '').strip()[:250]
        # Customers always raise tickets for themselves, on the web channel, with the basic fields only.
        partner = user.partner_id if customer else self._resolve_contact(values)
        if not subject:
            raise UserError(_("Enter a subject."))
        vals = {'name': subject, 'partner_id': partner.id, 'channel': 'web'}
        description = (values.get('description') or '').strip()
        if description:
            vals['description'] = plaintext2html(description)
        if values.get('priority'):
            vals['priority'] = self._choice(values['priority'], PRIORITIES, _("priority"))
        if values.get('classification'):
            vals['classification'] = self._choice(values['classification'], CLASSIFICATIONS, _("classification"))
        if values.get('lang_id'):
            vals['lang_id'] = env['res.lang'].sudo().browse(int(values['lang_id'])).exists().id
        if values.get('template_id'):
            template = env['aixo.ticket.template'].browse(int(values['template_id'])).exists()
            vals['template_id'] = template.id
        if not customer:
            vals.update(self._internal_values(values))
        ticket = env['aixo.ticket'].create(vals)
        self._claim_attachments(ticket, values.get('attachment_ids'))
        return {'ticket': ticket_row(ticket), 'contact': partner.name}

    def _choice(self, value, options, label):
        if value not in dict(options):
            raise UserError(_("Unknown %s.", label))
        return value

    def _resolve_contact(self, values):
        env = request.env
        if values.get('contact_id'):
            partner = env['res.partner'].browse(int(values['contact_id'])).exists()
            if not partner:
                raise UserError(_("Choose a contact."))
            return partner
        new = values.get('new_contact') or {}
        name = (new.get('name') or '').strip()[:120]
        if not name:
            raise UserError(_("Choose or enter a contact."))
        email = clean_email(new.get('email'))
        if email and not valid_email(email):
            raise UserError(_("Enter a valid email address."))
        # Admins create contacts from here; partner creation is not in the desk groups, so sudo is
        # limited to this one create of plain contact fields.
        partners = env['res.partner'].sudo()
        company = (new.get('account') or '').strip()[:120]
        parent = False
        if company:
            parent = (partners.search([('is_company', '=', True), ('name', '=ilike', company)], limit=1)
                      or partners.create({'name': company, 'is_company': True})).id
        return partners.create({'name': name, 'email': email or False, 'phone': (new.get('phone') or '').strip()[:40] or False,
                                'parent_id': parent})

    def _internal_values(self, values):
        env = request.env
        vals = {}
        state = values.get('status') or 'open'
        if state not in CREATE_STATES:
            raise UserError(_("Unknown status."))
        vals['state'] = state
        if values.get('channel'):
            vals['channel'] = self._choice(values['channel'], CHANNELS, _("channel"))
        if values.get('owner_id'):
            owner = env['res.users'].browse(int(values['owner_id'])).exists()
            if owner.share:
                raise UserError(_("Tickets can only be assigned to employees."))
            vals['owner_id'] = owner.id
        if values.get('product_id'):
            vals['product_id'] = env['aixo.product'].browse(int(values['product_id'])).exists().id
        if values.get('project_id'):
            project = env['aixo.project'].browse(int(values['project_id'])).exists()
            project.check_access('read')
            vals['project_id'] = project.id
        if values.get('due_date'):
            from .tickets import DeskTickets
            vals['due_date'] = DeskTickets()._parse_due(values['due_date'])
        return vals

    def _claim_attachments(self, ticket, ids):
        """Attach drafts uploaded before the ticket existed (only the user's own, unlinked ones)."""
        attachments = request.env['ir.attachment'].browse([int(i) for i in (ids or [])]).exists()
        for attachment in attachments:
            if (attachment.res_model != 'aixo.ticket' or attachment.res_id
                    or attachment.create_uid != request.env.user):
                raise UserError(_("Invalid attachment."))
        if attachments:
            attachments.write({'res_id': ticket.id})

    @http.route('/desk/ticket/attach-draft', type='http', auth='public', methods=['POST'], website=True)
    def attach_draft(self, **kw):
        user = request.env.user
        if user._is_public() or user.desk_role not in ('admin', 'customer'):
            return request.make_json_response(err(_("You don't have access to this."), 'forbidden'), status=403)
        try:
            uploaded = []
            for upload in request.httprequest.files.getlist('file'):
                data = upload.read()
                check_attachment_policy(upload.filename or 'file', len(data))
                attachment = request.env['ir.attachment'].create({
                    'name': upload.filename or 'file', 'raw': data, 'res_model': 'aixo.ticket', 'res_id': 0,
                    'mimetype': upload.mimetype or 'application/octet-stream'})
                uploaded.append({'id': attachment.id, 'name': attachment.name, 'size': attachment.file_size})
            return request.make_json_response(ok({'attachments': uploaded}))
        except UserError as exc:
            return request.make_json_response(err(str(exc.args[0])), status=400)
