from datetime import timedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from .api import avatar, desk_api, fmt_dt, ticket_row
from .base import desk_page
from .tickets import render_page

STATES = [('planning', 'Planning'), ('in_progress', 'In Progress'), ('on_hold', 'On Hold'), ('completed', 'Completed')]
VIEWS = [('all', 'All Projects'), ('mine', 'My Projects'), ('active', 'Active Projects'),
         ('hold', 'On Hold Projects'), ('done', 'Completed Projects')]
SECTIONS = ('projects', 'milestones', 'timesheets', 'tasks')


def view_domain(view, uid):
    return {
        'all': [], 'mine': [('member_ids', 'in', [uid])],
        'active': [('state', 'in', ('planning', 'in_progress'))],
        'hold': [('state', '=', 'on_hold')], 'done': [('state', '=', 'completed')],
    }.get(view, [])


class DeskProjects(http.Controller):

    @http.route('/desk/projects', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def list_page(self, **kw):
        user = request.env.user
        return render_page('aixo_desk.ProjectList', {'is_admin': user.desk_role == 'admin',
                                                      'new': request.params.get('new') == '1'}, 'projects', 'Projects')

    @http.route('/desk/project/<int:project_id>', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['agent'])
    def detail_page(self, project_id, **kw):
        project = request.env['aixo.project'].browse(project_id).exists()
        if not project or not project.has_access('read'):
            return request.redirect('/desk/projects')
        return render_page('aixo_desk.ProjectDetail', {'id': project.id}, 'projects', project.name)

    # --------------------------------------------------------------------- helpers

    def _project(self, project_id, write=False):
        project = request.env['aixo.project'].browse(int(project_id)).exists()
        if not project:
            raise UserError(_("This project no longer exists."))
        project.check_access('write' if write else 'read')
        return project

    def _row(self, project):
        user = request.env.user
        pct = project.progress
        return {
            'id': project.id, 'code': project.code, 'name': project.name,
            'customer': project.partner_id.name or '', 'start': fmt_dt(datetime_of(project.date_start), False),
            'due': fmt_dt(datetime_of(project.date_due), False), 'overdue': project.is_overdue,
            'state': project.state, 'state_label': dict(STATES)[project.state],
            'tasks_done': project.task_done_count, 'tasks_total': project.task_count, 'pct': pct,
            'tickets': project.open_ticket_count, 'members': [avatar(m) for m in project.member_ids],
            'starred': user in project.starred_user_ids,
        }

    # ------------------------------------------------------------------------ list

    @http.route('/desk/api/projects/list', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_list(self, view='all', section='projects', **kw):
        env = request.env
        uid = env.uid
        admin = env.user.desk_role == 'admin'
        Project = env['aixo.project']
        today = fields.Date.context_today(env.user)
        all_projects = Project.search([])
        counts = {key: Project.search_count(view_domain(key, uid)) for key, _label in VIEWS}
        projects = Project.search(view_domain(view, uid), order='code desc')
        week_ago = fields.Datetime.now() - timedelta(days=7)
        entries = env['aixo.time.entry'].search([('create_date', '>=', week_ago)])
        data = {
            'view': view, 'section': section if section in SECTIONS else 'projects',
            'views': [{'key': k, 'label': v, 'count': counts[k]} for k, v in VIEWS],
            'states': [{'value': k, 'label': v} for k, v in STATES],
            'kpis': {
                'active': len(all_projects.filtered(lambda p: p.state in ('planning', 'in_progress'))),
                'open_tickets': env['aixo.ticket'].search_count([('project_id', '!=', False), ('state', '!=', 'closed')]),
                'due_week': len(all_projects.filtered(lambda p: p.state != 'completed' and p.date_due
                                                      and today <= p.date_due <= today + timedelta(days=7))),
                'hours_week': round(sum(entries.mapped('duration')), 1),
            },
            'projects': [self._row(p) for p in projects],
            'can_create': admin,
        }
        if admin:
            data['customers'] = [{'id': c.id, 'name': c.name} for c in env['res.partner'].search(
                [('is_company', '=', True)], limit=200)]
            data['agents'] = [avatar(u) for u in env['res.users'].sudo().search([('share', '=', False)])]
        if data['section'] == 'milestones':
            data['milestones'] = [{
                'id': m.id, 'name': m.name, 'project': m.project_id.name, 'code': m.project_id.code,
                'project_id': m.project_id.id, 'date': fmt_dt(datetime_of(m.date), False), 'reached': m.reached,
            } for m in env['aixo.project.milestone'].search([], order='date')]
        if data['section'] == 'tasks':
            data['tasks'] = [{
                'id': t.id, 'name': t.name, 'project': t.project_id.name, 'code': t.project_id.code,
                'project_id': t.project_id.id, 'done': t.done, 'assignee': t.user_id.name or '',
                'due': fmt_dt(datetime_of(t.date_due), False),
            } for t in env['aixo.project.task'].search([], order='done, project_id')]
        if data['section'] == 'timesheets':
            rows = env['aixo.time.entry'].search([('ticket_id.project_id', '!=', False)], limit=200)
            data['timesheets'] = [{
                'id': e.id, 'date': fmt_dt(datetime_of(e.date), False), 'agent': e.user_id.name, 'work': e.name,
                'ticket': f"#{e.ticket_id.number} {e.ticket_id.name}", 'ticket_id': e.ticket_id.id,
                'project': e.ticket_id.project_id.name, 'hours': round(e.duration, 2),
            } for e in rows]
        return data

    # ---------------------------------------------------------------------- changes

    @http.route('/desk/api/projects/move', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_move(self, id, state, **kw):
        if state not in dict(STATES):
            raise UserError(_("Unknown status."))
        project = self._project(id, write=True)
        project.state = state
        return {'project': self._row(project)}

    @http.route('/desk/api/projects/create', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def projects_create(self, values=None, **kw):
        values = values or {}
        name = (values.get('name') or '').strip()[:150]
        if not name:
            raise UserError(_("Enter a project name."))
        state = values.get('state') or 'planning'
        if state not in dict(STATES):
            raise UserError(_("Unknown status."))
        vals = {'name': name, 'state': state,
                'date_start': values.get('date_start') or False, 'date_due': values.get('date_due') or False,
                'partner_id': int(values['partner_id']) if values.get('partner_id') else False}
        members = [int(m) for m in values.get('member_ids') or []]
        if members:
            vals['member_ids'] = [(6, 0, request.env['res.users'].browse(members).filtered(lambda u: not u.share).ids)]
        if vals['date_start'] and vals['date_due'] and vals['date_due'] < vals['date_start']:
            raise UserError(_("The due date cannot be before the start date."))
        project = request.env['aixo.project'].create(vals)
        return {'project': self._row(project)}

    @http.route('/desk/api/projects/star', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_star(self, id, **kw):
        project = self._project(id, write=True)
        project.action_toggle_star()
        return {'starred': request.env.user in project.starred_user_ids}

    # ----------------------------------------------------------------------- detail

    @http.route('/desk/api/projects/get', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_get(self, id, **kw):
        project = self._project(id)
        env = request.env
        admin = env.user.desk_role == 'admin'
        tickets = env['aixo.ticket'].search([('project_id', '=', project.id)], order='id desc')
        data = {
            **self._row(project),
            'start_input': str(project.date_start or ''), 'due_input': str(project.date_due or ''),
            'partner_id': project.partner_id.id, 'hours': round(project.hours_logged, 2),
            'tasks': [{'id': t.id, 'name': t.name, 'done': t.done, 'assignee': t.user_id.name or '',
                       'due': fmt_dt(datetime_of(t.date_due), False)} for t in project.task_ids],
            'milestones': [{'id': m.id, 'name': m.name, 'date': fmt_dt(datetime_of(m.date), False),
                            'date_input': str(m.date or ''), 'reached': m.reached} for m in project.milestone_ids],
            'ticket_list': [ticket_row(t) for t in tickets],
            'states': [{'value': k, 'label': v} for k, v in STATES],
            'can_manage': admin,
            'agents': [avatar(u) for u in env['res.users'].sudo().search([('share', '=', False)])],
            'member_ids': project.member_ids.ids,
        }
        return data

    @http.route('/desk/api/projects/update', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_update(self, id, values=None, **kw):
        project = self._project(id, write=True)
        values = values or {}
        admin = request.env.user.desk_role == 'admin'
        vals = {}
        if 'state' in values:
            if values['state'] not in dict(STATES):
                raise UserError(_("Unknown status."))
            vals['state'] = values['state']
        if admin:
            if 'name' in values:
                name = (values['name'] or '').strip()[:150]
                if not name:
                    raise UserError(_("Enter a project name."))
                vals['name'] = name
            for key in ('date_start', 'date_due'):
                if key in values:
                    vals[key] = values[key] or False
            if 'member_ids' in values:
                users = request.env['res.users'].browse([int(i) for i in values['member_ids']]).filtered(lambda u: not u.share)
                vals['member_ids'] = [(6, 0, users.ids)]
        elif set(values) - {'state'}:
            raise AccessError(_("Only admins can change this."))
        start = vals.get('date_start', str(project.date_start or ''))
        due = vals.get('date_due', str(project.date_due or ''))
        if start and due and str(due) < str(start):
            raise UserError(_("The due date cannot be before the start date."))
        project.write(vals)
        return {'project': self._row(project)}

    @http.route('/desk/api/projects/task', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_task(self, id, action, task_id=None, name=None, **kw):
        project = self._project(id, write=True)
        Task = request.env['aixo.project.task']
        if action == 'add':
            title = (name or '').strip()[:200]
            if not title:
                raise UserError(_("Enter a task name."))
            Task.create({'project_id': project.id, 'name': title, 'user_id': request.env.uid})
        else:
            task = Task.browse(int(task_id)).exists()
            if task.project_id != project:
                raise UserError(_("Task not found."))
            if action == 'toggle':
                task.done = not task.done
            elif action == 'delete':
                task.unlink()
            else:
                raise UserError(_("Unknown action."))
        return {'project': self._row(project), 'tasks': [{
            'id': t.id, 'name': t.name, 'done': t.done, 'assignee': t.user_id.name or '',
            'due': fmt_dt(datetime_of(t.date_due), False)} for t in project.task_ids]}

    @http.route('/desk/api/projects/milestone', type='jsonrpc', auth='public')
    @desk_api(roles=['agent'])
    def projects_milestone(self, id, action, milestone_id=None, name=None, date=None, **kw):
        project = self._project(id, write=True)
        Milestone = request.env['aixo.project.milestone']
        if action == 'add':
            title = (name or '').strip()[:200]
            if not title:
                raise UserError(_("Enter a milestone name."))
            Milestone.create({'project_id': project.id, 'name': title, 'date': date or False})
        else:
            milestone = Milestone.browse(int(milestone_id)).exists()
            if milestone.project_id != project:
                raise UserError(_("Milestone not found."))
            if action == 'toggle':
                milestone.reached = not milestone.reached
            else:
                raise UserError(_("Unknown action."))
        return {'milestones': [{'id': m.id, 'name': m.name, 'date': fmt_dt(datetime_of(m.date), False),
                                'date_input': str(m.date or ''), 'reached': m.reached} for m in project.milestone_ids]}


def datetime_of(day):
    """Date -> naive datetime so the shared formatter can print it."""
    from datetime import datetime
    return datetime.combine(day, datetime.min.time()) if day else None
