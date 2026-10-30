import logging
import re
from datetime import datetime, timedelta
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    ticket_project_id = fields.Many2one(
        "project.project",
        string="Project",
    )

    ticket_project_team_id = fields.Many2one(
        "project.team",
        string="Team",
        compute="_compute_ticket_project_fields",
        store=True,
        readonly=False,
    )

    ticket_employee_ids = fields.Many2many(
        "hr.employee",
        string="Team Member",
        compute="_compute_ticket_project_fields",
        store=True,
        readonly=False,
    )

    assigned_employee_id = fields.Many2one(
        "hr.employee",
        string="Assigned Employee",
    )

    assignment_status = fields.Selection([
        ('pending', 'Pending Assignment'),
        ('assigned', 'Assigned'),
    ], string='Assignment Status', default='pending', tracking=True, index=True)

    assigned_date = fields.Datetime(
        string="Assigned Date",
        help="Exact time and date when the ticket was assigned to an employee",
        tracking=True,
        copy=False,
    )

    user_id = fields.Many2one(
        "res.users",
        string="Assigned to",
        compute="_compute_user_id_from_assigned_employee",
        store=True,
        readonly=False,
    )

    website_ticket_id = fields.Many2one(
        "website.helpdesk.ticket",
        string="Website Portal Ticket",
        ondelete="set null",
    )

    existing_ticket_id = fields.Many2one(
        'helpdesk.ticket',
        string='Existing Ticket',
        ondelete='set null',
        help='Completed ticket related to this ticket',
    )
    existing_ticket_ids = fields.Many2many(
        'helpdesk.ticket',
        'helpdesk_ticket_existing_rel',
        'ticket_id',
        'existing_ticket_id',
        string='Existing Tickets',
        help='Completed tickets related to this ticket',
    )

    # Portal compatibility fields & Single Source of Truth
    ticket_number = fields.Char(
        string='Ticket Number',
        compute='_compute_ticket_number',
        store=True,
        index=True
    )

    stage = fields.Selection([
        ('new', 'New'),
        ('progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('solved', 'Solved'),
        ('cancelled', 'Cancelled'),
        ('rotting', 'Rotting'),
        ('resolved', 'Resolved'),
    ], string='Status', compute='_compute_website_stage', inverse='_inverse_website_stage', store=True, tracking=True)

    stage_code = fields.Char(string='Stage Code', compute='_compute_stage_code')

    category = fields.Selection([
        ('billing', 'Billing & Payments'),
        ('technical', 'Technical & App Crash'),
        ('refund', 'Refund & Returns'),
        ('account', 'Account & Access'),
        ('other', 'General Inquiry'),
        ('feature', 'Feature Request'),
    ], string='Category', default='billing')

    due_date_text = fields.Char(string='Due Date Text', default='')
    satisfaction_rating = fields.Selection([
        ('check', 'Checkmark'),
        ('smile', 'Positive'),
        ('frown', 'Negative'),
        ('clock', 'Clock'),
    ], string='Satisfaction Icon', default='clock')
    is_urgent_alert = fields.Boolean(string='Urgent Alert (!)', default=False)
    agent_status_dot = fields.Selection([
        ('green', 'Active (Green)'),
        ('red', 'Busy/Critical (Red)'),
        ('gray', 'Offline (Gray)'),
    ], string='Agent Status Dot', default='gray')
    customer_name_display = fields.Char(string='Customer Display Name', compute='_compute_customer_name_display', store=True)

    stage_update_date = fields.Datetime(string='Stage Updated Date', default=fields.Datetime.now, tracking=True)
    sla_duration = fields.Char(string='SLA Duration', default='45m')

    rotting_statusbar_duration = fields.Char(
        string='Status with Duration',
        compute='_compute_rotting_statusbar_duration',
        store=False,
        help='Displays the stage accompanied by the dynamic elapsed time duration'
    )
    sla_status_text = fields.Char(compute='_compute_rotting_statusbar_duration', string='SLA Badge Text', readonly=True)

    in_progress_duration = fields.Integer(string='In Progress Duration (Seconds)', default=0, copy=False)
    progress_start_date = fields.Datetime(string='Progress Start Date', copy=False)
    status_time_seconds = fields.Integer(string='Status Time (Seconds)', compute='_compute_status_time_data')
    status_time_str = fields.Char(string='Status Time Text', compute='_compute_status_time_data')

    history_trail = fields.Text(
        string='History Flow',
        default='Opened by customer → awaiting assignment',
        help='Progressive milestone path shown on ticket card'
    )

    clean_description = fields.Char(string='Clean Description', compute='_compute_clean_description', store=False)

    team_name = fields.Char(string='Helpdesk Team Name', compute='_compute_team_name', store=True)
    tag_names = fields.Char(string='Tags Display', compute='_compute_tag_names', store=True)

    sla_failed = fields.Boolean(string='SLA Failed', compute='_compute_sla_failed', store=True)
    customer_rating = fields.Float(string='Customer Rating', default=0.0)
    closed_date = fields.Datetime(string='Closed Date', compute='_compute_closed_date', inverse='_inverse_closed_date', store=True)

    message_line_ids = fields.One2many('website.helpdesk.message', 'helpdesk_ticket_id', string='Chat Messages')

    @api.depends('ticket_ref')
    def _compute_ticket_number(self):
        for rec in self:
            rec.ticket_number = rec.ticket_ref or (f"#{rec.id:05d}" if rec.id else 'New')

    @api.depends('stage_id', 'stage_id.name')
    def _compute_website_stage(self):
        for rec in self:
            rec.stage = rec._map_stage_id_to_website_stage(rec.stage_id)

    def _inverse_website_stage(self):
        for rec in self:
            if rec.stage:
                stage_rec = rec._map_website_stage_to_stage_id(rec.stage, rec.team_id)
                if stage_rec:
                    rec.stage_id = stage_rec.id

    @api.depends('stage', 'stage_id')
    def _compute_stage_code(self):
        for rec in self:
            rec.stage_code = rec.stage or 'new'

    @api.depends('partner_id', 'partner_id.name', 'partner_name')
    def _compute_customer_name_display(self):
        for rec in self:
            rec.customer_name_display = rec.partner_id.name or rec.partner_name or (rec.partner_email if hasattr(rec, 'partner_email') else False) or 'Customer'

    @api.depends('description')
    def _compute_clean_description(self):
        for rec in self:
            if not rec.description:
                rec.clean_description = ''
                continue
            text = re.sub(r'<[^>]+>', '\n', str(rec.description))
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            unique_lines = []
            for line in lines:
                if line not in unique_lines:
                    unique_lines.append(line)
            rec.clean_description = ' '.join(unique_lines)

    @api.depends('team_id', 'team_id.name', 'ticket_project_team_id', 'ticket_project_team_id.name')
    def _compute_team_name(self):
        for rec in self:
            rec.team_name = rec.team_id.name if rec.team_id else (rec.ticket_project_team_id.name if rec.ticket_project_team_id else '')

    @api.depends('tag_ids', 'tag_ids.name')
    def _compute_tag_names(self):
        for rec in self:
            rec.tag_names = ', '.join(rec.tag_ids.mapped('name')) if rec.tag_ids else ''

    @api.depends('sla_fail')
    def _compute_sla_failed(self):
        for rec in self:
            rec.sla_failed = bool(getattr(rec, 'sla_fail', False))

    @api.depends('close_date')
    def _compute_closed_date(self):
        for rec in self:
            rec.closed_date = rec.close_date

    def _inverse_closed_date(self):
        for rec in self:
            rec.close_date = rec.closed_date

    @api.depends('stage', 'in_progress_duration', 'progress_start_date', 'stage_update_date')
    def _compute_status_time_data(self):
        now = fields.Datetime.now()
        for rec in self:
            stg = (rec.stage or 'new').lower()
            sec = 0
            if stg in ['progress', 'in_progress']:
                base_dur = rec.in_progress_duration or 0
                start_dt = rec.progress_start_date or rec.stage_update_date
                if start_dt:
                    diff = now - start_dt
                    sec = base_dur + max(0, int(diff.total_seconds()))
                else:
                    sec = base_dur
            elif stg in ['on_hold', 'rotting', 'resolved', 'cancelled']:
                sec = rec.in_progress_duration or 0
            else:
                sec = 0

            rec.status_time_seconds = sec
            hrs = sec // 3600
            mins = (sec % 3600) // 60
            secs = sec % 60
            rec.status_time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

    @api.depends('stage', 'stage_id', 'stage_update_date', 'sla_duration')
    def _compute_rotting_statusbar_duration(self):
        for rec in self:
            duration_str = rec.sla_duration
            if not duration_str and rec.stage_update_date:
                diff = datetime.now() - rec.stage_update_date
                minutes = int(diff.total_seconds() // 60)
                if minutes < 60:
                    duration_str = f"{minutes}m"
                else:
                    hours = minutes // 60
                    rem_min = minutes % 60
                    duration_str = f"{hours}h {rem_min}m"

            stg = rec.stage or 'new'
            if stg == 'rotting':
                rec.rotting_statusbar_duration = f"Rotting - {duration_str or '3h 20m'}"
            elif stg == 'progress':
                rec.rotting_statusbar_duration = f"In progress - {duration_str or '45m'}"
            elif stg in ['solved', 'resolved']:
                rec.rotting_statusbar_duration = "Solved"
            elif stg == 'new':
                rec.rotting_statusbar_duration = f"New - {duration_str or 'Just now'}"
            elif stg == 'on_hold':
                rec.rotting_statusbar_duration = f"On Hold - {duration_str or 'Paused'}"
            elif stg == 'cancelled':
                rec.rotting_statusbar_duration = "Cancelled"
            else:
                rec.rotting_statusbar_duration = rec.stage_id.name if rec.stage_id else (rec.stage or 'Open')
            rec.sla_status_text = rec.rotting_statusbar_duration

    def action_set_progress(self):
        now = fields.Datetime.now()
        for rec in self:
            agent_name = rec.user_id.name.split()[0] if rec.user_id else (rec.assigned_employee_id.name.split()[0] if rec.assigned_employee_id else "Agent")
            current_trail = rec.history_trail or ''
            new_trail = f"{current_trail} → in progress by {agent_name}" if current_trail else f"In progress by {agent_name}"
            rec.write({
                'stage': 'progress',
                'sla_duration': '45m',
                'stage_update_date': now,
                'progress_start_date': now,
                'history_trail': new_trail,
            })

    def action_set_resolved(self):
        now = fields.Datetime.now()
        for rec in self:
            agent_name = rec.user_id.name.split()[0] if rec.user_id else (rec.assigned_employee_id.name.split()[0] if rec.assigned_employee_id else "Agent")
            current_trail = rec.history_trail or ''
            new_trail = f"{current_trail} → resolved by {agent_name}" if current_trail else f"Resolved by {agent_name}"
            rec.write({
                'stage': 'resolved',
                'stage_update_date': now,
                'closed_date': now,
                'history_trail': new_trail,
            })

    def action_set_rotting(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.write({
                'stage': 'rotting',
                'sla_duration': '3h 20m',
                'stage_update_date': now,
            })

    def add_history_milestone(self, milestone_text):
        if not milestone_text:
            return
        clean_text = str(milestone_text).strip()
        for rec in self:
            current_trail = rec.history_trail or ''
            new_trail = f"{current_trail} → {clean_text}" if current_trail else clean_text
            rec.write({'history_trail': new_trail})

    @api.model
    def get_employee_overview_stats(self, user_id=None):
        domain = []
        if user_id:
            domain.append(('user_id', '=', user_id))

        all_tickets = self.sudo().search(domain)
        open_tickets = all_tickets.filtered(lambda t: (t.stage or 'new') not in ['resolved', 'solved', 'cancelled'])
        open_high = open_tickets.filtered(lambda t: str(t.priority) in ['1', '2'])
        open_urgent = open_tickets.filtered(lambda t: str(t.priority) in ['2', '3'])

        cnt_open = len(open_tickets)
        cnt_high = len(open_high)
        cnt_urgent = len(open_urgent)

        def format_hours(tickets, default_str="00:00"):
            if tickets:
                avg_hrs = sum(t.open_hours for t in tickets) / len(tickets)
                h = int(avg_hrs)
                m = int((avg_hrs - h) * 60)
                return f"{h:02d}:{m:02d}"
            return default_str

        return {
            'open_tickets_count': cnt_open,
            'high_priority_count': cnt_high,
            'urgent_priority_count': cnt_urgent,
            'average_response_time': format_hours(open_tickets, "00:00"),
            'average_resolution_time': format_hours(all_tickets.filtered(lambda t: (t.stage or '') in ['resolved', 'solved']), "00:00"),
            'sla_failed_count': len(all_tickets.filtered(lambda t: t.sla_failed)),
            'customer_rating_average': round(sum(t.customer_rating for t in all_tickets) / len(all_tickets), 1) if all_tickets else 0.0,
        }

    @api.depends("ticket_project_id", "ticket_project_id.team_id", "ticket_project_id.employee_ids")
    def _compute_ticket_project_fields(self):
        for rec in self:
            if rec.ticket_project_id:
                rec.ticket_project_team_id = rec.ticket_project_id.team_id or False
                rec.ticket_employee_ids = rec.ticket_project_id.employee_ids or [(5, 0, 0)]
            else:
                rec.ticket_project_team_id = False
                rec.ticket_employee_ids = [(5, 0, 0)]

    def _get_user_from_employee(self, employee):
        if not employee:
            return False
        if employee.user_id:
            return employee.user_id
        if getattr(employee, 'work_email', False):
            user = self.env['res.users'].sudo().search([('email', '=ilike', employee.work_email)], limit=1)
            if user:
                return user
        if getattr(employee, 'name', False):
            user = self.env['res.users'].sudo().search([('name', '=ilike', employee.name)], limit=1)
            if user:
                return user
        return False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'user_id' in fields_list:
            res['user_id'] = False
        if 'assigned_employee_id' in fields_list:
            res['assigned_employee_id'] = False
        return res

    @api.depends("assigned_employee_id")
    def _compute_user_id_from_assigned_employee(self):
        for rec in self:
            if rec.assigned_employee_id:
                user = rec._get_user_from_employee(rec.assigned_employee_id)
                rec.user_id = user or False
            else:
                rec.user_id = False

    def _map_stage_id_to_website_stage(self, stage_id):
        if not stage_id:
            return 'new'
        sname = (stage_id.name or '').lower()
        if 'cancel' in sname:
            return 'cancelled'
        if any(k in sname for k in ['solve', 'resolve', 'done', 'close']):
            return 'resolved'
        if any(k in sname for k in ['hold', 'wait', 'pend']):
            return 'on_hold'
        if any(k in sname for k in ['progress', 'work', 'develop']):
            return 'progress'
        return 'new'

    @api.model
    def _map_website_stage_to_stage_id(self, stage_code, team_id=False):
        stage_model = self.env['helpdesk.stage'].sudo()
        team_domain = [('team_ids', 'in', [team_id.id])] if team_id else []

        name_map = {
            'new': ['new', 'not started', 'open'],
            'progress': ['in progress', 'progress', 'working', 'development'],
            'on_hold': ['hold', 'on hold', 'pending', 'waiting'],
            'solved': ['solved', 'resolved', 'done', 'closed'],
            'resolved': ['resolved', 'solved', 'done', 'closed'],
            'cancelled': ['cancelled', 'canceled', 'cancel'],
        }
        targets = name_map.get(stage_code, ['new'])
        for target in targets:
            stage = stage_model.search(team_domain + [('name', 'ilike', target)], limit=1)
            if stage:
                return stage
        for target in targets:
            stage = stage_model.search([('name', 'ilike', target)], limit=1)
            if stage:
                return stage
        return stage_model.search([], order='sequence asc, id asc', limit=1)

    def _apply_auto_assignment(self, vals):
        ICP = self.env['ir.config_parameter'].sudo()
        mode = ICP.get_param('website_helpdesk_portal.assignment_mode', default='manual')
        if mode != 'auto':
            return
        rule = ICP.get_param('website_helpdesk_portal.auto_assign_rule', default='ticket_count')

        candidates = self.env['hr.employee']
        proj_id = vals.get('ticket_project_id')
        if proj_id:
            proj = self.env['project.project'].browse(proj_id)
            if proj.exists() and proj.employee_ids:
                candidates = proj.employee_ids
            elif proj.exists() and proj.team_id and proj.team_id.employee_ids:
                candidates = proj.team_id.employee_ids
        if not candidates:
            candidates = self.env['hr.employee'].search([('user_id', '!=', False)], limit=20)

        if not candidates:
            return

        chosen_emp = None
        if rule == 'ticket_count':
            best_count = float('inf')
            for emp in candidates:
                cnt = self.search_count([
                    ('assigned_employee_id', '=', emp.id),
                    ('stage_id.fold', '=', False),
                ])
                if cnt < best_count:
                    best_count = cnt
                    chosen_emp = emp
        elif rule == 'assigned_date':
            oldest_dt = None
            for emp in candidates:
                last_ticket = self.search([
                    ('assigned_employee_id', '=', emp.id),
                    ('assigned_date', '!=', False),
                ], order='assigned_date desc', limit=1)
                t_dt = last_ticket.assigned_date if last_ticket else datetime.min
                if oldest_dt is None or t_dt < oldest_dt:
                    oldest_dt = t_dt
                    chosen_emp = emp

        if not chosen_emp:
            chosen_emp = candidates[0]

        now = fields.Datetime.now()
        vals['assigned_employee_id'] = chosen_emp.id
        vals['assignment_status'] = 'assigned'
        vals['assigned_date'] = now
        user = self._get_user_from_employee(chosen_emp)
        if user:
            vals['user_id'] = user.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ticket_project_id'):
                proj = self.env['project.project'].browse(vals['ticket_project_id'])
                if proj.exists():
                    if not vals.get('ticket_project_team_id') and proj.team_id:
                        vals['ticket_project_team_id'] = proj.team_id.id
                    if not vals.get('ticket_employee_ids') and proj.employee_ids:
                        vals['ticket_employee_ids'] = [(6, 0, proj.employee_ids.ids)]

            if not vals.get('assigned_employee_id'):
                self._apply_auto_assignment(vals)

            if vals.get('assigned_employee_id'):
                emp = self.env['hr.employee'].browse(vals['assigned_employee_id'])
                if emp.exists():
                    user = self._get_user_from_employee(emp)
                    if user:
                        vals['user_id'] = user.id
                vals['assignment_status'] = 'assigned'
                if not vals.get('assigned_date'):
                    vals['assigned_date'] = fields.Datetime.now()
            else:
                vals['assigned_employee_id'] = False
                vals['user_id'] = False
                vals['assignment_status'] = 'pending'

            if vals.get('stage') and not vals.get('stage_id'):
                st = self._map_website_stage_to_stage_id(vals['stage'], vals.get('team_id'))
                if st:
                    vals['stage_id'] = st.id

        records = super().create(vals_list)
        return records

    def write(self, vals):
        if 'ticket_project_id' in vals:
            if vals['ticket_project_id']:
                proj = self.env['project.project'].browse(vals['ticket_project_id'])
                if proj.exists():
                    if 'ticket_project_team_id' not in vals and proj.team_id:
                        vals['ticket_project_team_id'] = proj.team_id.id
                    if 'ticket_employee_ids' not in vals and proj.employee_ids:
                        vals['ticket_employee_ids'] = [(6, 0, proj.employee_ids.ids)]
            else:
                if 'ticket_project_team_id' not in vals:
                    vals['ticket_project_team_id'] = False
                if 'ticket_employee_ids' not in vals:
                    vals['ticket_employee_ids'] = [(5, 0, 0)]
                if 'assigned_employee_id' not in vals:
                    vals['assigned_employee_id'] = False
                if 'user_id' not in vals:
                    vals['user_id'] = False

        if 'assigned_employee_id' in vals:
            if vals['assigned_employee_id']:
                emp = self.env['hr.employee'].browse(vals['assigned_employee_id'])
                if emp.exists():
                    user = self._get_user_from_employee(emp)
                    vals['user_id'] = user.id if user else False
                vals['assignment_status'] = 'assigned'
                vals['assigned_date'] = vals.get('assigned_date') or fields.Datetime.now()

                emp_name = emp.name if emp.exists() else 'Staff'
                now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for rec in self:
                    rec.message_post(
                        body=f"Assigned to {emp_name} on {now_str}",
                        subtype_xmlid='mail.mt_note'
                    )
            else:
                vals['assigned_employee_id'] = False
                vals['user_id'] = False
                vals['assignment_status'] = 'pending'

        if 'stage' in vals:
            new_stage = (vals['stage'] or 'new').lower()
            now = fields.Datetime.now()
            for rec in self:
                old_stage = (rec.stage or 'new').lower()
                if old_stage != new_stage:
                    if old_stage in ['progress', 'in_progress'] and new_stage not in ['progress', 'in_progress']:
                        start_dt = rec.progress_start_date or rec.stage_update_date
                        if start_dt:
                            elapsed = max(0, int((now - start_dt).total_seconds()))
                            vals['in_progress_duration'] = (rec.in_progress_duration or 0) + elapsed
                        vals['progress_start_date'] = False
                    elif new_stage in ['progress', 'in_progress'] and old_stage not in ['progress', 'in_progress']:
                        vals['progress_start_date'] = now
                    elif new_stage in ['new', 'open']:
                        vals['in_progress_duration'] = 0
                        vals['progress_start_date'] = False

            if 'stage_update_date' not in vals:
                vals['stage_update_date'] = fields.Datetime.now()
            if new_stage == 'resolved' and not vals.get('close_date'):
                vals['close_date'] = fields.Datetime.now()

        res = super().write(vals)
        return res

    def unlink(self):
        return super().unlink()

    @api.onchange("partner_id")
    def _onchange_partner_id_project(self):
        self.ticket_project_id = False
        self.ticket_project_team_id = False
        self.ticket_employee_ids = [(5, 0, 0)]
        self.assigned_employee_id = False
        self.user_id = False

        if not self.partner_id:
            return {
                "domain": {
                    "ticket_project_id": [("id", "=", False)],
                }
            }

        return {
            "domain": {
                "ticket_project_id": [
                    ("partner_id", "=", self.partner_id.id),
                ],
            }
        }

    @api.onchange("ticket_project_id")
    def _onchange_ticket_project_id(self):
        self.ticket_project_team_id = False
        self.ticket_employee_ids = [(5, 0, 0)]
        self.assigned_employee_id = False
        self.user_id = False

        if not self.ticket_project_id:
            return {
                "domain": {
                    "assigned_employee_id": [("id", "=", False)],
                }
            }

        project = self.ticket_project_id
        self.ticket_project_team_id = project.team_id
        self.ticket_employee_ids = [(6, 0, project.employee_ids.ids)]

        return {
            "domain": {
                "assigned_employee_id": [
                    ("id", "in", project.employee_ids.ids),
                ],
            }
        }

    @api.onchange("assigned_employee_id")
    def _onchange_assigned_employee_id(self):
        if self.assigned_employee_id:
            user = self._get_user_from_employee(self.assigned_employee_id)
            self.user_id = user or False
        else:
            self.user_id = False