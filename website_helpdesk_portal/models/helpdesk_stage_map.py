# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HelpdeskStageMap(models.Model):
    _name = 'helpdesk.stage.map'
    _description = 'Helpdesk Stage Map'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Selection([
        ('my_own', 'My Own Tickets'),
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('hold', 'Hold'),
        ('resolved', 'Resolved'),
        ('canceled', 'Canceled'),
        ('waiting_for_reply', 'Waiting For Reply'),
        ('waiting', 'Waiting'),
    ], string='Code', default='not_started', compute='_compute_code', store=True, readonly=False)

    stage_ids = fields.Many2many(
        'helpdesk.stage',
        'helpdesk_stage_map_stage_rel',
        'stage_map_id',
        'stage_id',
        string='Stage Key',
        help='Map standard Helpdesk stages that correspond to this stage map'
    )

    team_ids = fields.Many2many(
        'helpdesk.team',
        'helpdesk_stage_map_team_rel',
        'stage_map_id',
        'team_id',
        string='Helpdesk Teams'
    )

    fold = fields.Boolean(
        string='Folded',
        default=False,
        help='Whether this stage is folded/closed in overview and kanban views'
    )

    active = fields.Boolean(string='Active', default=True)
    color = fields.Integer(string='Color', default=0)

    @api.depends('name')
    def _compute_code(self):
        for rec in self:
            if not rec.code:
                n = (rec.name or '').lower()
                if 'my' in n or 'own' in n:
                    rec.code = 'my_own'
                elif 'not' in n or 'start' in n:
                    rec.code = 'not_started'
                elif 'progress' in n or 'work' in n:
                    rec.code = 'in_progress'
                elif 'wait' in n or 'reply' in n:
                    rec.code = 'waiting_for_reply'
                elif 'hold' in n or 'pend' in n:
                    rec.code = 'hold'
                elif 'solve' in n or 'resolve' in n or 'done' in n:
                    rec.code = 'resolved'
                elif 'cancel' in n:
                    rec.code = 'canceled'
                else:
                    rec.code = 'not_started'


class HelpdeskStage(models.Model):
    _inherit = 'helpdesk.stage'

    to_track_stage_ids = fields.Many2many(
        'helpdesk.stage',
        'helpdesk_stage_to_track_rel',
        'stage_id',
        'to_track_stage_id',
        string='To Track Stage',
        help='Stages to track from this stage',
    )
    back_track_stage_ids = fields.Many2many(
        'helpdesk.stage',
        'helpdesk_stage_back_track_rel',
        'stage_id',
        'back_track_stage_id',
        string='Back Track Stages',
        help='Stages to which tickets in this stage can be backtracked',
    )
    allow_reopen = fields.Boolean(
        string='Re Open',
        default=False,
        help='Show the Re Open button for tickets in this stage.',
    )
    is_completed = fields.Boolean(
        string='Is Completed',
        default=False,
        help='Mark this stage as a completed stage. Tickets in this stage are filtered and available for selection in the Existing Tickets field.',
    )

    def get_allowed_target_stages(self):
        """Returns recordset of allowed next stages based on To Track and Back Track rules"""
        self.ensure_one()
        return self.to_track_stage_ids | self.back_track_stage_ids

    def is_transition_allowed(self, target_stage):
        """Check if transition from self to target_stage is permitted"""
        self.ensure_one()
        if not target_stage or self.id == target_stage.id:
            return True
        allowed = self.get_allowed_target_stages()
        if not allowed:
            return False
        return target_stage.id in allowed.ids

    @api.onchange('is_completed')
    def _onchange_is_completed(self):
        """Display notification dialog when attempting to mark more than one stage as completed."""
        if self.is_completed:
            current_id = self._origin.id or (self.id if isinstance(self.id, int) else False)
            domain = [('is_completed', '=', True)]
            if current_id:
                domain.append(('id', '!=', current_id))
            other = self.search(domain, limit=1)
            if other:
                self.is_completed = False
                return {
                    'warning': {
                        'title': _("Stage Completed Notification"),
                        'message': _(
                            "Only one stage can have 'Is Completed' enabled at a time.\n\n"
                            "Stage '%(stage_name)s' is already marked as completed.\n\n"
                            "Please uncheck 'Is Completed' on '%(stage_name)s' first before selecting another stage.",
                            stage_name=other.name
                        ),
                        'type': 'notification',
                    }
                }

    @api.constrains('is_completed')
    def _check_single_is_completed(self):
        """Ensure only one stage has is_completed=True in database."""
        completed_stages = self.search([('is_completed', '=', True)])
        if len(completed_stages) > 1:
            names = ", ".join(f"'{s.name}'" for s in completed_stages)
            raise UserError(_(
                "Only one stage can have 'Is Completed' enabled at a time.\n\n"
                "Multiple stages are currently marked as completed: %(names)s.\n"
                "Please ensure only one stage has 'Is Completed' enabled.",
                names=names
            ))

    def write(self, vals):
        if vals.get('is_completed'):
            for rec in self:
                other = self.search([
                    ('is_completed', '=', True),
                    ('id', '!=', rec.id)
                ], limit=1)
                if other:
                    raise UserError(_(
                        "Only one stage can have 'Is Completed' enabled at a time.\n\n"
                        "Stage '%(other_name)s' is already marked as completed.\n"
                        "Please uncheck 'Is Completed' on '%(other_name)s' before marking '%(current_name)s'.",
                        other_name=other.name,
                        current_name=rec.name
                    ))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_completed'):
                other = self.search([('is_completed', '=', True)], limit=1)
                if other:
                    raise UserError(_(
                        "Only one stage can have 'Is Completed' enabled at a time.\n\n"
                        "Stage '%(other_name)s' is already marked as completed.\n"
                        "Please uncheck 'Is Completed' on '%(other_name)s' before creating another completed stage.",
                        other_name=other.name
                    ))
        return super().create(vals_list)

    def action_open_completed_wizard(self, other_stage=None):
        """Open notification wizard dialog to switch completed stage."""
        self.ensure_one()
        other = other_stage or self.search([('is_completed', '=', True), ('id', '!=', self.id)], limit=1)
        return {
            'name': _("Stage Completed Notification"),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.stage.completed.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_stage_id': self.id,
                'default_current_completed_stage_id': other.id if other else False,
                'default_message': _(
                    "Only one stage can have 'Is Completed' enabled at a time.\n\n"
                    "Stage '%(other_name)s' is currently marked as completed.\n\n"
                    "Would you like to replace it and set '%(target_name)s' as the completed stage?",
                    other_name=other.name if other else 'Another Stage',
                    target_name=self.name
                ),
            }
        }


class HelpdeskStageCompletedWizard(models.TransientModel):
    _name = 'helpdesk.stage.completed.wizard'
    _description = 'Stage Completed Notification Wizard'

    stage_id = fields.Many2one('helpdesk.stage', string='Stage to Complete', readonly=True)
    current_completed_stage_id = fields.Many2one('helpdesk.stage', string='Currently Completed Stage', readonly=True)
    message = fields.Text(string='Notification', readonly=True)

    def action_switch_completed(self):
        """Switch completed status from previous stage to the target stage."""
        self.ensure_one()
        if self.current_completed_stage_id:
            self.current_completed_stage_id.sudo().write({'is_completed': False})
        if self.stage_id:
            self.stage_id.sudo().write({'is_completed': True})
        return {'type': 'ir.actions.act_window_close'}


