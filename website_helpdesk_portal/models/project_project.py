# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Project Manager',
        compute='_compute_employee_id',
        inverse='_inverse_employee_id',
        store=True,
        readonly=False,
    )
    team_id = fields.Many2one(
        'project.team',
        string='Team',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'project_project_hr_employee_rel',
        'project_id',
        'employee_id',
        string='Team Member',
    )

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            if not rec.employee_id and rec.user_id:
                emp = self.env['hr.employee'].search([
                    ('user_id', '=', rec.user_id.id),
                    '|', ('company_id', '=', rec.company_id.id), ('company_id', '=', False)
                ], limit=1) or self.env['hr.employee'].search([('user_id', '=', rec.user_id.id)], limit=1)
                rec.employee_id = emp
            elif not rec.user_id and not rec.employee_id:
                rec.employee_id = False

    def _inverse_employee_id(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.user_id:
                rec.user_id = rec.employee_id.user_id

    @api.onchange('team_id')
    def _onchange_team_id(self):
        if self.team_id:
            team_employees = self.team_id.member_ids.mapped('employee_id')
            self.employee_ids = [(6, 0, team_employees.ids)]
            if not self.employee_id and self.team_id.team_lead_id:
                lead_employee = self.env['hr.employee'].search(
                    [('user_id', '=', self.team_id.team_lead_id.id)], limit=1
                )
                if lead_employee:
                    self.employee_id = lead_employee
        else:
            self.employee_ids = [(5, 0, 0)]

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.user_id:
            self.user_id = self.employee_id.user_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('team_id') and 'employee_ids' not in vals:
                team = self.env['project.team'].browse(vals['team_id'])
                vals['employee_ids'] = [(6, 0, team.member_ids.mapped('employee_id').ids)]
            if vals.get('employee_id') and not vals.get('user_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                if emp.user_id:
                    vals['user_id'] = emp.user_id.id
            elif vals.get('user_id') and not vals.get('employee_id'):
                emp = self.env['hr.employee'].search([('user_id', '=', vals['user_id'])], limit=1)
                if emp:
                    vals['employee_id'] = emp.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('team_id') and 'employee_ids' not in vals:
            team = self.env['project.team'].browse(vals['team_id'])
            vals['employee_ids'] = [(6, 0, team.member_ids.mapped('employee_id').ids)]
        if vals.get('employee_id') and 'user_id' not in vals:
            emp = self.env['hr.employee'].browse(vals['employee_id'])
            if emp.user_id:
                vals['user_id'] = emp.user_id.id
        elif vals.get('user_id') and 'employee_id' not in vals:
            emp = self.env['hr.employee'].search([('user_id', '=', vals['user_id'])], limit=1)
            if emp:
                vals['employee_id'] = emp.id
        return super().write(vals)