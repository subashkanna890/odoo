from odoo import api, fields, models


class AixoProject(models.Model):
    _name = 'aixo.project'
    _description = 'Aixo Project'
    _inherit = ['mail.thread']
    _order = 'code desc'

    code = fields.Char(readonly=True, copy=False, default='New', index=True)
    name = fields.Char(required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer', tracking=True)
    date_start = fields.Date(string='Start')
    date_due = fields.Date(string='Due', tracking=True)
    state = fields.Selection(
        [('planning', 'Planning'), ('in_progress', 'In Progress'),
         ('on_hold', 'On Hold'), ('completed', 'Completed')],
        default='planning', required=True, tracking=True, index=True)
    member_ids = fields.Many2many(
        'res.users', 'aixo_project_user_rel', 'project_id', 'user_id', string='Members',
        domain=[('share', '=', False)])
    starred_user_ids = fields.Many2many(
        'res.users', 'aixo_project_star_rel', 'project_id', 'user_id', string='Starred by')
    task_ids = fields.One2many('aixo.project.task', 'project_id', string='Tasks')
    milestone_ids = fields.One2many('aixo.project.milestone', 'project_id', string='Milestones')
    ticket_ids = fields.One2many('aixo.ticket', 'project_id', string='Tickets')
    task_count = fields.Integer(compute='_compute_progress')
    task_done_count = fields.Integer(compute='_compute_progress')
    progress = fields.Integer(compute='_compute_progress', string='Progress %')
    open_ticket_count = fields.Integer(compute='_compute_open_ticket_count')
    hours_logged = fields.Float(compute='_compute_hours_logged')
    is_overdue = fields.Boolean(compute='_compute_is_overdue')
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code('aixo.project') or 'New'
        return super().create(vals_list)

    @api.depends('task_ids.done')
    def _compute_progress(self):
        for project in self:
            total = len(project.task_ids)
            done = len(project.task_ids.filtered('done'))
            project.task_count = total
            project.task_done_count = done
            project.progress = round(done * 100 / total) if total else 0

    def _compute_open_ticket_count(self):
        groups = self.env['aixo.ticket'].sudo()._read_group(
            [('project_id', 'in', self.ids), ('state', '!=', 'closed')],
            ['project_id'], ['__count'])
        counts = {project.id: count for project, count in groups}
        for project in self:
            project.open_ticket_count = counts.get(project.id, 0)

    def _compute_hours_logged(self):
        groups = self.env['aixo.time.entry'].sudo()._read_group(
            [('ticket_id.project_id', 'in', self.ids)],
            ['ticket_id.project_id'], ['duration:sum'])
        totals = {project.id: total for project, total in groups}
        for project in self:
            project.hours_logged = totals.get(project.id, 0.0)

    @api.depends('date_due', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for project in self:
            project.is_overdue = bool(
                project.date_due and project.date_due < today and project.state != 'completed')

    def action_toggle_star(self):
        self.ensure_one()
        self.starred_user_ids = [(3 if self.env.user in self.starred_user_ids else 4, self.env.uid)]


class AixoProjectTask(models.Model):
    _name = 'aixo.project.task'
    _description = 'Aixo Project Task'
    _order = 'done, sequence, id'

    name = fields.Char(required=True)
    project_id = fields.Many2one('aixo.project', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Assignee', domain=[('share', '=', False)])
    date_due = fields.Date()
    done = fields.Boolean()
    sequence = fields.Integer(default=10)


class AixoProjectMilestone(models.Model):
    _name = 'aixo.project.milestone'
    _description = 'Aixo Project Milestone'
    _order = 'date, id'

    name = fields.Char(required=True)
    project_id = fields.Many2one('aixo.project', required=True, ondelete='cascade', index=True)
    date = fields.Date()
    reached = fields.Boolean()
