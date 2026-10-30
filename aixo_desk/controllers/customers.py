from datetime import timedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import html2plaintext

from .api import avatar, desk_api, fmt_dt, human_ago, ticket_row
from .base import clean_email, desk_page, valid_email
from .tickets import render_page

VIEWS = [('all', 'All Contacts'), ('mine', 'My Contacts'), ('paid', 'Paid Customers'),
         ('open', 'With Open Tickets'), ('recent', 'Recently Active')]
EDITABLE = {'email', 'desk_email2', 'phone', 'desk_mobile', 'lang', 'city', 'desk_linkedin', 'desk_facebook',
            'account', 'desk_plan', 'desk_owner_id'}
ADMIN_ONLY = {'account', 'desk_plan', 'desk_owner_id'}
FIELD_LABEL = {
    'email': 'Email', 'desk_email2': 'Secondary email', 'phone': 'Phone', 'desk_mobile': 'Mobile', 'lang': 'Language',
    'city': 'City', 'desk_linkedin': 'LinkedIn', 'desk_facebook': 'Facebook', 'account': 'Account',
    'desk_plan': 'Plan', 'desk_owner_id': 'Contact owner',
}
RATING_SCORE = {'good': 100, 'okay': 50, 'bad': 0}


def customer_domain():
    """Partners the current user may see as customers.

    Agents get exactly the contacts of tickets they can read (the search below runs
    under the ticket record rules); admins also get portal customers who have not
    raised a ticket yet.
    """
    env = request.env
    on_tickets = env['aixo.ticket']._read_group([], ['partner_id'])
    partner_ids = [partner.id for (partner,) in on_tickets]
    domain = [('is_company', '=', False), ('id', 'in', partner_ids)]
    if env.user.desk_role == 'admin':
        group = env.ref('aixo_desk.group_desk_customer')
        domain = [('is_company', '=', False), '|', ('id', 'in', partner_ids),
                  ('user_ids.group_ids', 'in', [group.id])]
    return domain


def scoped_stats(partners):
    """Per partner counts from the tickets the caller can see (never wider than their rules)."""
    stats = {p.id: {'all': 0, 'open': 0, 'on_hold': 0, 'closed': 0, 'overdue': 0, 'scores': [], 'last': False}
             for p in partners}
    tickets = request.env['aixo.ticket'].search_fetch(
        [('partner_id', 'in', partners.ids)], ['partner_id', 'state', 'rating', 'is_overdue', 'write_date'])
    for t in tickets:
        s = stats[t.partner_id.id]
        s['all'] += 1
        s['open'] += t.state in ('open', 'escalated')
        s['on_hold'] += t.state == 'on_hold'
        s['closed'] += t.state == 'closed'
        s['overdue'] += bool(t.is_overdue)
        if t.rating:
            s['scores'].append(RATING_SCORE[t.rating])
        s['last'] = max(s['last'] or t.write_date, t.write_date)
    for s in stats.values():
        s['happy'] = round(sum(s['scores']) / len(s['scores'])) if s['scores'] else None
        s['health'] = 'at_risk' if (s['overdue'] or (s['happy'] is not None and s['happy'] < 70)) else 'healthy'
    return stats


def plan_of(partner):
    return (partner.commercial_partner_id or partner).desk_plan or 'free'


class DeskCustomers(http.Controller):

    # -------------------------------------------------------------------- pages

    @http.route('/desk/customers', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def list_page(self, **kw):
        return render_page('aixo_desk.CustomerList', {}, 'customers', 'Customers')

    @http.route('/desk/customer/<int:partner_id>', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def detail_page(self, partner_id, **kw):
        found = request.env['res.partner'].search(customer_domain() + [('id', '=', partner_id)], limit=1)
        if not found:
            return request.redirect('/desk/customers')
        return render_page('aixo_desk.CustomerDetail', {'id': partner_id, 'is_admin': request.env.user.desk_role == 'admin'},
                           'customers', found.name)

    # --------------------------------------------------------------------- list

    def _row(self, partner, stat):
        owner = partner.desk_owner_id
        return {
            'id': partner.id, 'name': partner.name, 'initials': avatar(partner)['initials'],
            'account': partner.parent_id.name or '', 'email': partner.email or '',
            'phone': partner.phone or '', 'plan': plan_of(partner), 'paid': plan_of(partner) == 'paid',
            'open': stat['open'] + stat['on_hold'], 'overdue': stat['overdue'], 'happy': stat['happy'],
            'owner': avatar(owner) if owner else None, 'owner_id': owner.id,
            'last': human_ago(stat['last']), 'last_days': (fields.Datetime.now() - stat['last']).days if stat['last'] else 999,
        }

    @http.route('/desk/api/customers/list', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def customers_list(self, view='all', letter='ALL', search='', **kw):
        domain = customer_domain()
        term = (search or '').strip()[:80]
        if term:
            domain += ['|', '|', ('name', 'ilike', term), ('email', 'ilike', term), ('parent_id.name', 'ilike', term)]
        partners = request.env['res.partner'].search(domain, order='name', limit=500)
        stats = scoped_stats(partners)
        uid = request.env.uid
        rows = [self._row(p, stats[p.id]) for p in partners]
        filters = {
            'all': lambda r: True,
            'mine': lambda r: r['owner_id'] == uid,
            'paid': lambda r: r['paid'],
            'open': lambda r: r['open'] > 0,
            'recent': lambda r: r['last_days'] <= 1,
        }
        counts = {key: len([r for r in rows if fn(r)]) for key, fn in filters.items()}
        shown = [r for r in rows if filters.get(view, filters['all'])(r)]
        letters = sorted({r['name'][:1].upper() for r in shown if r['name']})
        if letter and letter != 'ALL':
            shown = [r for r in shown if r['name'][:1].upper() == letter]
        return {'view': view, 'views': [{'key': k, 'label': v, 'count': counts[k]} for k, v in VIEWS],
                'customers': shown, 'letters': letters, 'total': len(shown)}

    # ------------------------------------------------------------------- detail

    def _partner(self, partner_id):
        partner = request.env['res.partner'].search(customer_domain() + [('id', '=', int(partner_id))], limit=1)
        if not partner:
            raise AccessError(_("This customer is not available to you."))
        return partner

    @http.route('/desk/api/customers/get', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def customers_get(self, id, **kw):
        partner = self._partner(id)
        stat = scoped_stats(partner)[partner.id]
        tickets = request.env['aixo.ticket'].search([('partner_id', '=', partner.id)], order='id desc')
        lang_options = request.env['res.lang'].sudo().search([])
        admin = request.env.user.desk_role == 'admin'
        company = partner.parent_id
        return {
            'id': partner.id, 'name': partner.name, 'initials': avatar(partner)['initials'],
            'props': {
                'email': partner.email or '', 'desk_email2': partner.desk_email2 or '', 'phone': partner.phone or '',
                'desk_mobile': partner.desk_mobile or '', 'lang': partner.lang or '', 'account': company.name or '',
                'city': partner.city or '', 'desk_linkedin': partner.desk_linkedin or '',
                'desk_facebook': partner.desk_facebook or '', 'desk_plan': plan_of(partner),
                'desk_owner_id': partner.desk_owner_id.id,
            },
            'languages': [{'code': lang.code, 'name': lang.name} for lang in lang_options],
            'owners': [avatar(u) for u in request.env['res.users'].sudo().search([('share', '=', False)])] if admin else [],
            'paid': plan_of(partner) == 'paid',
            'tags': [{'id': t.id, 'name': t.name} for t in partner.category_id],
            'stats': {'all': stat['all'], 'open': stat['open'], 'on_hold': stat['on_hold'], 'closed': stat['closed'],
                      'overdue': stat['overdue'], 'happy': stat['happy'], 'health': stat['health'],
                      'health_score': self._health_score(stat), 'last': human_ago(stat['last'])},
            'tickets': [{**ticket_row(t), 'created_long': fmt_dt(t.create_date, False)} for t in tickets],
            'activity': self._activity(tickets),
            'interactions': self._interactions(tickets),
            'history': self._history(partner),
            'can_edit_admin': admin,
            'can_create_ticket': admin,
        }

    def _health_score(self, stat):
        score = 100 - 12 * stat['overdue']
        if stat['happy'] is not None:
            score = round((score + stat['happy']) / 2)
        return max(0, min(100, score))

    def _activity(self, tickets):
        events = [{'when': fmt_dt(t.create_date), 'sort': t.create_date, 'text': _("Ticket #%(n)s “%(s)s” was raised", n=t.number, s=t.name), 'ticket': t.id}
                  for t in tickets[:15]]
        for t in tickets.filtered(lambda t: t.state == 'closed')[:10]:
            events.append({'when': fmt_dt(t.closed_on), 'sort': t.closed_on or t.write_date,
                           'text': _("Ticket #%(n)s was closed", n=t.number), 'ticket': t.id})
        events.sort(key=lambda e: e['sort'], reverse=True)
        return [{k: v for k, v in e.items() if k != 'sort'} for e in events[:20]]

    def _interactions(self, tickets):
        note = request.env.ref('mail.mt_note')
        messages = tickets.message_ids.filtered(
            lambda m: m.message_type in ('comment', 'email', 'email_outgoing') and m.subtype_id != note)
        return [{'id': m.id, 'when': fmt_dt(m.date), 'who': m.author_id.name or '', 'ticket': m.res_id,
                 'text': html2plaintext(m.body or '').strip()[:220]} for m in messages.sorted('id', reverse=True)[:20]]

    def _history(self, partner):
        # Change notes are written by the update route below on this very partner.
        note = request.env.ref('mail.mt_note')
        messages = partner.sudo().message_ids.filtered(lambda m: m.subtype_id == note and m.message_type == 'comment')
        return [{'id': m.id, 'when': fmt_dt(m.date), 'who': m.author_id.name or '',
                 'text': html2plaintext(m.body or '').strip()} for m in messages.sorted('id', reverse=True)[:30]]

    @http.route('/desk/api/customers/update', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def customers_update(self, id, values=None, **kw):
        partner = self._partner(id)
        values = values or {}
        admin = request.env.user.desk_role == 'admin'
        unknown = set(values) - EDITABLE
        if unknown:
            raise UserError(_("These fields cannot be edited: %s", ', '.join(sorted(unknown))))
        if set(values) & ADMIN_ONLY and not admin:
            raise AccessError(_("Only admins can change this."))
        vals, changes = {}, []
        for key in sorted(values, key=lambda k: k != 'account'):
            raw = values[key]
            value = (str(raw).strip() if raw not in (None, False) else '')[:200]
            old = self._current(partner, key)
            if key in ('email', 'desk_email2'):
                value = clean_email(value)
                if value and not valid_email(value):
                    raise UserError(_("Enter a valid email address."))
            if key == 'lang' and value and value not in request.env['res.lang'].sudo().search([]).mapped('code'):
                raise UserError(_("Unknown language."))
            if key == 'desk_plan':
                if value not in ('free', 'paid'):
                    raise UserError(_("Unknown plan."))
                self._set_plan(partner, value)
            elif key == 'desk_owner_id':
                owner = request.env['res.users'].sudo().browse(int(raw or 0))
                vals[key] = owner.id if owner and not owner.share else False
                value = owner.name if vals[key] else ''
            elif key == 'account':
                self._set_account(partner, value)
            else:
                vals[key] = value or False
            if str(old or '') != str(value or ''):
                changes.append((FIELD_LABEL[key], old, value))
        # Agents cannot edit partners in general; the whitelist above plus the visibility
        # check in _partner() is what makes this sudo write safe.
        if vals:
            partner.sudo().write(vals)
        for label, old, new in changes:
            partner.sudo().message_post(
                body=_("%(label)s changed from “%(old)s” to “%(new)s”", label=label, old=old or '—', new=new or '—'),
                message_type='comment', subtype_xmlid='mail.mt_note', author_id=request.env.user.partner_id.id)
        return {'ok': True, 'name': partner.name}

    def _current(self, partner, key):
        if key == 'account':
            return partner.parent_id.name
        if key == 'desk_plan':
            return plan_of(partner)
        if key == 'desk_owner_id':
            return partner.desk_owner_id.name
        return partner[key]

    def _set_plan(self, partner, plan):
        (partner.commercial_partner_id or partner).sudo().desk_plan = plan

    def _set_account(self, partner, name):
        partners = request.env['res.partner'].sudo()
        if not name:
            partner.sudo().parent_id = False
            return
        company = (partners.search([('is_company', '=', True), ('name', '=ilike', name)], limit=1)
                   or partners.create({'name': name, 'is_company': True}))
        partner.sudo().parent_id = company.id

    @http.route('/desk/api/customers/tag', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def customers_tag(self, id, add=None, remove=None, **kw):
        partner = self._partner(id).sudo()  # tag changes only; visibility was checked above
        Category = request.env['res.partner.category'].sudo()
        if add:
            name = str(add).strip()[:50]
            if not name:
                raise UserError(_("Enter a tag name."))
            tag = Category.search([('name', '=ilike', name)], limit=1) or Category.create({'name': name})
            partner.category_id = [(4, tag.id)]
        if remove:
            partner.category_id = [(3, int(remove))]
        return {'tags': [{'id': t.id, 'name': t.name} for t in partner.category_id]}
