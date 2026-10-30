import secrets

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request

from .api import avatar, desk_api, fmt_dt, ok, ticket_row
from .base import base_url, clean_email, desk_page, password_problem, send_mail, valid_email
from .tickets import render_page

ADMIN_VIEWS = [('all', 'All Tickets'), ('unassigned', 'Unassigned'), ('overdue', 'Overdue'),
               ('high', 'High Priority'), ('escalated', 'Escalated')]
VIEW_DOMAIN = {
    'all': [], 'unassigned': [('owner_id', '=', False), ('state', '!=', 'closed')],
    'overdue': [('is_overdue', '=', True)], 'high': [('priority', 'in', ('high', 'urgent')), ('state', '!=', 'closed')],
    'escalated': [('state', '=', 'escalated')],
}
MAX_BULK = 200
PAGE_SIZE = 50
ROLES = [('agent', 'Agent'), ('lead', 'Team lead'), ('admin', 'Admin')]


def admin_agents():
    """Employees (agents and admins) except the system user."""
    env = request.env
    groups = env.ref('aixo_desk.group_desk_agent') | env.ref('aixo_desk.group_desk_admin')
    return env['res.users'].sudo().with_context(active_test=False).search([
        ('share', '=', False), ('group_ids', 'in', groups.ids), ('id', '!=', env.ref('base.user_root').id)])


class DeskAdmin(http.Controller):

    # ------------------------------------------------------------------- pages

    @http.route('/desk/admin', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['admin'])
    def home_page(self, **kw):
        return render_page('aixo_desk.AdminHome', {}, 'tickets', 'Admin')

    @http.route('/desk/admin/people', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['admin'])
    def people_page(self, **kw):
        return render_page('aixo_desk.AdminPeople', {'add': request.params.get('add', ''),
                                                      'tab': request.params.get('tab', 'employees')},
                           'employees', 'Employees')

    @http.route('/desk/admin/reports', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['admin'])
    def reports_page(self, **kw):
        return render_page('aixo_desk.AdminReports', {}, 'reports', 'Reports')

    # ------------------------------------------------------------------ tickets

    @http.route('/desk/api/admin/tickets', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def tickets(self, view='all', search='', page=1, **kw):
        env = request.env
        Ticket = env['aixo.ticket']
        view = view if view in VIEW_DOMAIN else 'all'
        domain = list(VIEW_DOMAIN[view])
        term = (search or '').strip()[:100]
        if term:
            domain += ['|', '|', ('name', 'ilike', term), ('number', 'ilike', term), ('partner_id.name', 'ilike', term)]
        page = max(int(page or 1), 1)
        tickets = Ticket.search(domain, order='id desc', limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        agents = admin_agents().filtered('active')
        load = {a.id: 0 for a in agents}
        for owner, count in Ticket._read_group([('state', '!=', 'closed'), ('owner_id', 'in', agents.ids)],
                                               ['owner_id'], ['__count']):
            load[owner.id] = count
        return {
            'view': view, 'views': [{'key': k, 'label': v, 'count': Ticket.search_count(VIEW_DOMAIN[k])}
                                    for k, v in ADMIN_VIEWS],
            'tickets': [ticket_row(t) for t in tickets], 'total': Ticket.search_count(domain),
            'page': page, 'page_size': PAGE_SIZE,
            'agents': [avatar(a) for a in agents],
            'workload': [{**avatar(a), 'open': load[a.id]} for a in agents],
        }

    @http.route('/desk/api/admin/assign', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def assign(self, ids=None, owner_id=None, **kw):
        ids = [int(i) for i in (ids or [])][:MAX_BULK + 1]
        if not ids:
            raise UserError(_("Select at least one ticket."))
        if len(ids) > MAX_BULK:
            raise UserError(_("You can assign up to %s tickets at once.", MAX_BULK))
        tickets = request.env['aixo.ticket'].browse(ids).exists()
        if not tickets:
            raise UserError(_("These tickets no longer exist."))
        owner = request.env['res.users'].sudo().browse(int(owner_id)) if owner_id else None
        if owner:
            if owner not in admin_agents().filtered('active'):
                raise UserError(_("Tickets can only be assigned to active employees."))
            tickets._check_can_assign(owner)
        tickets.write({'owner_id': owner.id if owner else False})
        if owner and owner != request.env.user and owner.email:
            send_mail(owner.email, _("%s ticket(s) assigned to you", len(tickets)), 'aixo_desk.mail_assign', {
                'name': owner.name, 'count': len(tickets), 'tickets': [(t.number, t.name) for t in tickets[:10]],
                'url': f"{base_url()}/desk"})
        if owner:
            message = (_("%(n)s tickets assigned to %(who)s", n=len(tickets), who=owner.name) if len(tickets) > 1
                       else _("Ticket #%(n)s assigned to %(who)s", n=tickets.number, who=owner.name))
        else:
            message = _("Ticket #%s unassigned", tickets[0].number) if len(tickets) == 1 else _("%s tickets unassigned", len(tickets))
        return {'message': message, 'tickets': [ticket_row(t) for t in tickets]}

    # ------------------------------------------------------------------- people

    def _employee_row(self, user, load, lead_ids):
        role = 'admin' if request.env.ref('aixo_desk.group_desk_admin') in user.group_ids else (
            'lead' if user.id in lead_ids else 'agent')
        team = user.desk_team_ids[:1]
        return {
            'id': user.id, 'name': user.name, 'email': user.login, 'phone': user.desk_office_phone or '',
            'role': role, 'role_label': dict(ROLES)[role], 'team': team.name or '', 'team_id': team.id,
            'department': team.department or '', 'assigned': load.get(user.id, 0),
            'status': 'Inactive' if not user.active else ('Active' if user.login_date else 'Invited'),
            'active': user.active, 'avatar': avatar(user),
        }

    def _customer_row(self, user):
        company = user.partner_id.parent_id
        plan = (user.partner_id.commercial_partner_id or user.partner_id).desk_plan or 'free'
        return {
            'id': user.id, 'name': user.name, 'email': user.login, 'company': company.name or '',
            'plan': plan, 'plan_label': dict(user.partner_id._fields['desk_plan'].selection)[plan],
            'portal': 'Enabled' if user.active else 'Disabled',
            'status': 'Inactive' if not user.active else ('Active' if user.login_date else 'Invited'),
            'active': user.active, 'avatar': avatar(user),
        }

    def _team_row(self, team):
        return {
            'id': team.id, 'name': team.name, 'department': team.department or '', 'lead': team.lead_id.name or '',
            'lead_id': team.lead_id.id, 'description': team.description or '',
            'members': [avatar(m) for m in team.member_ids], 'member_ids': team.member_ids.ids,
            'open': team.open_ticket_count,
        }

    @http.route('/desk/api/admin/people', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def people(self, search='', **kw):
        env = request.env
        Ticket = env['aixo.ticket']
        load = {owner.id: count for owner, count in
                Ticket._read_group([('state', '!=', 'closed'), ('owner_id', '!=', False)], ['owner_id'], ['__count'])}
        teams = env['aixo.team'].with_context(active_test=False).search([])
        lead_ids = set(teams.lead_id.ids)
        q = (search or '').strip().lower()

        def match(*values):
            return not q or q in ' '.join(v or '' for v in values).lower()

        employees = [self._employee_row(u, load, lead_ids) for u in admin_agents()]
        customer_group = env.ref('aixo_desk.group_desk_customer')
        customers = [self._customer_row(u) for u in env['res.users'].sudo().with_context(active_test=False).search(
            [('group_ids', 'in', customer_group.id)], order='name')]
        team_rows = [self._team_row(t) for t in teams]
        return {
            'employees': [e for e in employees if match(e['name'], e['email'], e['team'], e['role_label'])],
            'customers': [c for c in customers if match(c['name'], c['email'], c['company'])],
            'teams': [t for t in team_rows if match(t['name'], t['department'], t['lead'])],
            'counts': {'employees': len(employees), 'customers': len(customers), 'teams': len(team_rows)},
            'options': {
                'teams': [{'id': t.id, 'name': t.name, 'department': t.department or ''} for t in teams],
                'departments': sorted({t.department for t in teams if t.department} | {'Support', 'Implementation', 'Billing'}),
                'roles': [{'value': k, 'label': v} for k, v in ROLES],
                'employees': [{'id': e['id'], 'name': e['name']} for e in employees if e['active']],
            },
            'me': env.uid,
        }

    def _clean_login(self, values):
        email = clean_email(values.get('email'))
        if not valid_email(email):
            raise UserError(_("Enter a valid login email."))
        if request.env['res.users'].sudo().with_context(active_test=False).search_count(
                ['|', ('login', '=ilike', email), ('email', '=ilike', email)]):
            raise UserError(_("A user with this email already exists."))
        problem = password_problem(values.get('password'))
        if problem:
            raise UserError(problem)
        return email

    def _name(self, values, label=None):
        name = (values.get('name') or '').strip()[:120]
        if not name:
            raise UserError(label or _("Enter a name."))
        return name

    @http.route('/desk/api/admin/employee/create', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def employee_create(self, values=None, **kw):
        values = values or {}
        name = self._name(values)
        email = self._clean_login(values)
        role = values.get('role') or 'agent'
        if role not in dict(ROLES):
            raise UserError(_("Unknown role."))
        env = request.env
        team = env['aixo.team'].browse(int(values['team_id'])).exists() if values.get('team_id') else env['aixo.team']
        if role == 'lead' and not team:
            raise UserError(_("Choose a team for the team lead."))
        group = env.ref('aixo_desk.group_desk_admin' if role == 'admin' else 'aixo_desk.group_desk_agent')
        # Creating users is a system-level operation; the desk admin role check above is the gate.
        user = env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': name, 'login': email, 'email': email, 'password': values['password'],
            'group_ids': [(6, 0, group.ids)], 'desk_office_phone': (values.get('phone') or '').strip()[:40] or False,
            'desk_force_password_change': bool(values.get('force_change')),
            'desk_team_ids': [(6, 0, team.ids)],
        })
        if role == 'lead':
            team.sudo().lead_id = user
        if values.get('send_login'):
            self._send_login(user, values['password'])
        return {'id': user.id, 'message': (_("%(name)s was added. Login details sent to %(email)s.", name=name, email=email)
                                           if values.get('send_login') else _("%s was added.", name))}

    @http.route('/desk/api/admin/customer/create', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def customer_create(self, values=None, **kw):
        values = values or {}
        name = self._name(values)
        email = self._clean_login(values)
        plan = values.get('plan') or 'free'
        if plan not in ('free', 'paid'):
            raise UserError(_("Unknown plan."))
        env = request.env
        company = False
        company_name = (values.get('company') or '').strip()[:120]
        partners = env['res.partner'].sudo()
        if company_name:
            company = partners.search([('is_company', '=', True), ('name', '=ilike', company_name)], limit=1) \
                or partners.create({'name': company_name, 'is_company': True})
            company.desk_plan = plan
        user = env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': name, 'login': email, 'email': email, 'password': values['password'],
            'phone': (values.get('phone') or '').strip()[:40] or False,
            'group_ids': [(6, 0, env.ref('aixo_desk.group_desk_customer').ids)],
            'parent_id': company.id if company else False,
        })
        if not company:
            user.partner_id.desk_plan = plan
        if values.get('send_login', True):
            self._send_login(user, values['password'])
        return {'id': user.id, 'message': _("%s can now log in to the customer portal.", name)}

    @http.route('/desk/api/admin/team/save', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def team_save(self, values=None, team_id=None, **kw):
        values = values or {}
        name = self._name(values, _("Enter a team name."))
        env = request.env
        members = env['res.users'].browse([int(m) for m in values.get('member_ids') or []]).filtered(lambda u: not u.share)
        lead = env['res.users'].browse(int(values['lead_id'])) if values.get('lead_id') else env['res.users']
        if lead and lead.share:
            raise UserError(_("The team lead must be an employee."))
        vals = {'name': name, 'department': (values.get('department') or '').strip()[:60] or False,
                'description': (values.get('description') or '').strip()[:200] or False,
                'lead_id': lead.id or False, 'member_ids': [(6, 0, (members | lead).ids)]}
        team = env['aixo.team'].browse(int(team_id)).exists() if team_id else env['aixo.team']
        if team:
            team.write(vals)
        else:
            team = env['aixo.team'].create(vals)
        return {'id': team.id, 'message': _("Team “%s” saved.", team.name)}

    @http.route('/desk/api/admin/employee/update', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def employee_update(self, id, values=None, **kw):
        values = values or {}
        env = request.env
        user = admin_agents().filtered(lambda u: u.id == int(id))
        if not user:
            raise UserError(_("Employee not found."))
        vals = {}
        if 'name' in values:
            vals['name'] = self._name(values)
        if 'phone' in values:
            vals['desk_office_phone'] = (values['phone'] or '').strip()[:40] or False
        role = values.get('role')
        if role:
            if role not in dict(ROLES):
                raise UserError(_("Unknown role."))
            if user == env.user and role != 'admin':
                raise UserError(_("You cannot remove your own admin access."))
            admin_group = env.ref('aixo_desk.group_desk_admin')
            if role != 'admin' and admin_group in user.group_ids and self._admin_count() <= 1:
                raise UserError(_("At least one admin is required."))
            group = admin_group if role == 'admin' else env.ref('aixo_desk.group_desk_agent')
            vals['group_ids'] = [(6, 0, group.ids)]
        if 'team_id' in values:
            team = env['aixo.team'].browse(int(values['team_id'] or 0)).exists()
            vals['desk_team_ids'] = [(6, 0, team.ids)]
            if role == 'lead':
                if not team:
                    raise UserError(_("Choose a team for the team lead."))
                team.sudo().lead_id = user
        user.write(vals)
        return {'message': _("%s was updated.", user.name)}

    def _admin_count(self):
        group = request.env.ref('aixo_desk.group_desk_admin')
        return len(admin_agents().filtered(lambda u: u.active and group in u.group_ids))

    @http.route('/desk/api/admin/user/toggle', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def user_toggle(self, id, **kw):
        """Deactivate or reactivate an employee or customer login."""
        env = request.env
        user = env['res.users'].sudo().with_context(active_test=False).browse(int(id)).exists()
        customer_group = env.ref('aixo_desk.group_desk_customer')
        if not user or not (user in admin_agents() or customer_group in user.group_ids):
            raise UserError(_("User not found."))
        if user == env.user:
            raise UserError(_("You cannot deactivate your own account."))
        if user.active and env.ref('aixo_desk.group_desk_admin') in user.group_ids and self._admin_count() <= 1:
            raise UserError(_("At least one admin is required."))
        user.active = not user.active
        return {'active': user.active,
                'message': _("%(name)s was reactivated.", name=user.name) if user.active else _("%(name)s was deactivated.", name=user.name)}

    @http.route('/desk/api/admin/user/invite', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def user_invite(self, id, **kw):
        """Resend the invitation: a login link plus a pointer to the password reset."""
        user = request.env['res.users'].sudo().browse(int(id)).exists()
        if not user or not user.active or user.login_date:
            raise UserError(_("This person has already logged in or cannot be invited."))
        self._send_login(user, None)
        return {'message': _("Invitation sent to %s.", user.email or user.login)}

    def _send_login(self, user, password):
        role = user.desk_role
        path = {'admin': '/desk/login?portal=admin', 'agent': '/desk/login?portal=employee'}.get(role, '/desk/login?portal=customer')
        send_mail(user.email or user.login, _("Your Aixo Desk login"), 'aixo_desk.mail_login', {
            'name': user.name, 'login': user.login, 'password': password, 'login_url': base_url() + path,
            'reset_url': base_url() + '/desk/reset', 'force': user.desk_force_password_change})

    @http.route('/desk/api/admin/generate-password', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def generate_password(self, **kw):
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
        return {'password': ''.join(secrets.choice(alphabet) for _i in range(10)) + '#7'}
