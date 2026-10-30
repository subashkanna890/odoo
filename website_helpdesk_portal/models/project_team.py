# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProjectTeam(models.Model):
    _name = 'project.team'
    _description = 'Project Team'
    _order = 'name'

    name = fields.Char(string='Team Name', required=True)
    team_lead_id = fields.Many2one('res.users', string='Team Lead')
    member_ids = fields.One2many('project.member', 'team_id', string='Team Members')
    project_ids = fields.One2many('project.project', 'team_id', string='Projects')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    member_count = fields.Integer(string='Members', compute='_compute_member_count')
    color = fields.Integer(string='Color')

    @api.depends('member_ids')
    def _compute_member_count(self):
        for team in self:
            team.member_count = len(team.member_ids)

    def write(self, vals):
        res = super().write(vals)
        if 'member_ids' in vals:
            for team in self:
                team_employees = team.member_ids.mapped('employee_id')
                for project in team.project_ids:
                    project.employee_ids = [(6, 0, team_employees.ids)]
        return res


class ProjectMember(models.Model):
    _name = 'project.member'
    _description = 'Project Member'
    _order = 'employee_id'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    team_id = fields.Many2one('project.team', string='Project Team', ondelete='cascade', required=True)
    role = fields.Selection([
        ('developer', 'Developer'),
        ('designer', 'Designer'),
        ('tester', 'Tester'),
        ('analyst', 'Business Analyst'),
        ('manager', 'Project Manager'),
        ('lead', 'Team Lead'),
        ('other', 'Other'),
    ], string='Role', default='developer')
    project_ids = fields.Many2many(
        'project.project',
        string='Assigned Projects',
        compute='_compute_project_ids',
        store=False,
    )
    user_id = fields.Many2one('res.users', string='Related User', related='employee_id.user_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    job_title = fields.Char(string='Job Title', related='employee_id.job_title', readonly=True)
    join_date = fields.Date(string='Join Date', default=fields.Date.today)
    active = fields.Boolean(default=True)

    @api.depends('team_id', 'team_id.project_ids')
    def _compute_project_ids(self):
        for member in self:
            member.project_ids = member.team_id.project_ids if member.team_id else False
