# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta

class WebsiteHelpdeskTicket(models.Model):
    _name = 'website.helpdesk.ticket'
    _description = 'Helpdesk Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Subject / Title', required=True, tracking=True)
    ticket_number = fields.Char(string='Ticket Number', default='New', copy=False, readonly=True, index=True)
    
    partner_id = fields.Many2one('res.partner', string='Customer', default=lambda self: self.env.user.partner_id)
    partner_email = fields.Char(related='partner_id.email', string='Customer Email', readonly=True)
    partner_name = fields.Char(related='partner_id.name', string='Customer Name', readonly=True)

    user_id = fields.Many2one('res.users', string='Assigned Employee', tracking=True)
    ticket_project_id = fields.Many2one('project.project', string='Project', tracking=True)
    assigned_employee_id = fields.Many2one('hr.employee', string='Assigned Employee Staff', tracking=True)
    assignment_status = fields.Selection([
        ('pending', 'Pending Assignment'),
        ('assigned', 'Assigned'),
    ], string='Assignment Status', default='pending', tracking=True, index=True)
    assigned_date = fields.Datetime(
        string='Assigned Date',
        help='Exact time and date when the ticket was assigned to an employee',
        tracking=True,
        copy=False,
    )
    helpdesk_ticket_id = fields.Many2one('helpdesk.ticket', string='Odoo Helpdesk Ticket', ondelete='set null')
    existing_ticket_id = fields.Many2one('website.helpdesk.ticket', string='Existing Ticket', ondelete='set null', help='Completed ticket related to this ticket')
    existing_ticket_ids = fields.Many2many(
        'website.helpdesk.ticket',
        'website_helpdesk_ticket_existing_rel',
        'ticket_id',
        'existing_ticket_id',
        string='Existing Tickets',
        help='Completed tickets related to this ticket',
    )
    stage_id = fields.Many2one('helpdesk.stage', string='Helpdesk Stage', compute='_compute_stage_id')

    @api.depends('helpdesk_ticket_id', 'stage')
    def _compute_stage_id(self):
        for rec in self:
            rec.stage_id = rec.helpdesk_ticket_id.stage_id if (rec.helpdesk_ticket_id and 'stage_id' in rec.helpdesk_ticket_id._fields) else False
    
    stage = fields.Selection([
        ('new', 'New'),
        ('progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('solved', 'Solved'),
        ('cancelled', 'Cancelled'),
        ('rotting', 'Rotting'),
        ('resolved', 'Resolved'),
    ], string='Status', default='new', tracking=True)

    due_date_text = fields.Char(string='Due Date Text', default='', help="e.g. In 2 days, In 9 days")
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

    @api.depends('partner_id', 'partner_name')
    def _compute_customer_name_display(self):
        for rec in self:
            rec.customer_name_display = rec.partner_id.name or rec.partner_name or (rec.partner_email if hasattr(rec, 'partner_email') else False) or 'Customer'

    stage_update_date = fields.Datetime(string='Stage Updated Date', default=fields.Datetime.now, tracking=True)
    sla_duration = fields.Char(string='SLA Duration', default='45m')
    
    # Custom Widget Field: status with time of stage
    rotting_statusbar_duration = fields.Char(
        string='Status with Duration',
        compute='_compute_rotting_statusbar_duration',
        store=False,
        help='Displays the stage accompanied by the dynamic elapsed time duration'
    )
    sla_status_text = fields.Char(compute='_compute_rotting_statusbar_duration', string='SLA Badge Text', readonly=True)

    category = fields.Selection([
        ('billing', 'Billing & Payments'),
        ('technical', 'Technical & App Crash'),
        ('refund', 'Refund & Returns'),
        ('account', 'Account & Access'),
        ('other', 'General Inquiry'),
        ('feature', 'Feature Request'),
    ], string='Category', default='billing')

    priority = fields.Selection([
        ('0', 'Low priority'),
        ('1', 'Medium priority'),
        ('2', 'High priority'),
        ('3', 'Urgent'),
    ], string='Priority', default='0')

    in_progress_duration = fields.Integer(string='In Progress Duration (Seconds)', default=0, copy=False)
    progress_start_date = fields.Datetime(string='Progress Start Date', copy=False)
    status_time_seconds = fields.Integer(string='Status Time (Seconds)', compute='_compute_status_time_data')
    status_time_str = fields.Char(string='Status Time Text', compute='_compute_status_time_data')

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
                # Stopped stage: preserve accumulated in-progress duration
                sec = rec.in_progress_duration or 0
            else:
                # Stage 'new' or open: status time MUST NOT run and MUST be 0
                sec = 0

            rec.status_time_seconds = sec
            hrs = sec // 3600
            mins = (sec % 3600) // 60
            secs = sec % 60
            rec.status_time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

    history_trail = fields.Text(
        string='History Flow', 
        default='Opened by customer â†’ awaiting assignment',
        help='Progressive milestone path shown on ticket card'
    )

    description = fields.Html(string='Description')
    clean_description = fields.Char(string='Clean Description', compute='_compute_clean_description', store=False)

    @api.depends('description')
    def _compute_clean_description(self):
        import re
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
    message_line_ids = fields.One2many('website.helpdesk.message', 'ticket_id', string='Chat Messages')

    # Fields matching user uploaded screenshot
    team_name = fields.Char(string='Helpdesk Team')
    partner_phone = fields.Char(string='Phone')
    email_cc = fields.Char(string='Email cc')
    tag_names = fields.Char(string='Tags')

    # Employee Performance & Overview Fields
    open_hours = fields.Float(string='Open Hours', compute='_compute_open_hours', store=False)
    sla_failed = fields.Boolean(string='SLA Failed', default=False, tracking=True)
    customer_rating = fields.Float(string='Customer Rating', default=0.0)
    closed_date = fields.Datetime(string='Closed Date', tracking=True)

    @api.depends('create_date', 'closed_date', 'stage')
    def _compute_open_hours(self):
        now = fields.Datetime.now()
        for rec in self:
            start = rec.create_date or now
            end = rec.closed_date if rec.stage == 'resolved' and rec.closed_date else now
            diff = end - start
            rec.open_hours = round(max(0.0, diff.total_seconds() / 3600.0), 2)

    @api.model
    def get_employee_overview_stats(self, user_id=None):
        domain = []
        if user_id:
            domain.append(('user_id', '=', user_id))
        
        all_tickets = self.sudo().search(domain)
        open_tickets = all_tickets.filtered(lambda t: t.stage not in ['resolved', 'solved', 'cancelled'])
        open_high = open_tickets.filtered(lambda t: t.priority in ['1', '2'])
        open_urgent = open_tickets.filtered(lambda t: t.priority in ['2', '3'])

        cnt_open = len(open_tickets)
        cnt_high = len(open_high)
        cnt_urgent = len(open_urgent)

        def format_hours(tickets, default_str="00:00"):
            if tickets:
                avg = sum(tickets.mapped('open_hours')) / len(tickets)
                h = int(avg)
                m = int((avg - h) * 60)
                return f"{h:02d}:{m:02d}"
            return default_str

        avg_total = format_hours(open_tickets, "00:00")
        avg_high = format_hours(open_high, "00:00")
        avg_urgent = format_hours(open_urgent, "00:00")

        failed_total = len(all_tickets.filtered(lambda t: t.sla_failed))
        failed_high = len(open_high.filtered(lambda t: t.sla_failed))
        failed_urgent = len(open_urgent.filtered(lambda t: t.sla_failed))

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        closed_today_tickets = all_tickets.filtered(lambda t: t.stage in ['resolved', 'solved'] and ((t.closed_date and t.closed_date >= today_start) or (t.write_date and t.write_date >= today_start)))
        closed_today = len(closed_today_tickets)

        closed_today_passed = len(closed_today_tickets.filtered(lambda t: not t.sla_failed))
        today_sla_rate = f"{(closed_today_passed / closed_today * 100):.1f} %" if closed_today > 0 else "100.0 %"

        today_ratings = [t.customer_rating for t in closed_today_tickets if t.customer_rating > 0]
        today_rating = f"{(sum(today_ratings) / len(today_ratings)):.1f} / 5" if today_ratings else "5.0 / 5"

        seven_days_ago = today_start - timedelta(days=7)
        last_7_tickets = all_tickets.filtered(lambda t: t.stage in ['resolved', 'solved'] and ((t.closed_date and t.closed_date >= seven_days_ago) or (t.write_date and t.write_date >= seven_days_ago)))
        last_7_closed = len(last_7_tickets)
        last_7_passed = len(last_7_tickets.filtered(lambda t: not t.sla_failed))
        last_7_sla_rate = f"{(last_7_passed / last_7_closed * 100):.1f} %" if last_7_closed > 0 else "100.0 %"

        last_7_ratings = [t.customer_rating for t in last_7_tickets if t.customer_rating > 0]
        last_7_rating = f"{(sum(last_7_ratings) / len(last_7_ratings)):.1f} / 5" if last_7_ratings else "5.0 / 5"

        return {
            'my_tickets': {
                'open_total': cnt_open,
                'open_high': cnt_high,
                'open_urgent': cnt_urgent,
                'avg_hours_total': avg_total,
                'avg_hours_high': avg_high,
                'avg_hours_urgent': avg_urgent,
                'failed_total': failed_total,
                'failed_high': failed_high,
                'failed_urgent': failed_urgent,
            },
            'my_performance': {
                'today_closed': closed_today,
                'today_sla_rate': today_sla_rate,
                'today_rating': today_rating,
                'last_7_closed': last_7_closed,
                'last_7_sla_rate': last_7_sla_rate,
                'last_7_rating': last_7_rating,
                'target_closed': 5,
                'target_sla_rate': "95%",
                'target_rating': "4.8 / 5",
            }
        }

    @api.model
    def get_next_ticket_number(self):
        last_ticket = self.search([], order='id desc', limit=1)
        if last_ticket and last_ticket.ticket_number:
            import re
            m = re.findall(r'\d+', last_ticket.ticket_number)
            if m:
                try:
                    num = int(m[-1])
                    return f"#{num + 1:05d}"
                except Exception:
                    pass
        last_id = last_ticket.id if last_ticket else 5
        return f"#{last_id + 1:05d}"

    def init(self):
        super().init()
        try:
            self.env.cr.execute("""
                ALTER TABLE website_helpdesk_ticket ADD COLUMN IF NOT EXISTS ticket_project_id integer;
                ALTER TABLE website_helpdesk_ticket ADD COLUMN IF NOT EXISTS assigned_employee_id integer;
                ALTER TABLE website_helpdesk_ticket ADD COLUMN IF NOT EXISTS helpdesk_ticket_id integer;
                ALTER TABLE website_helpdesk_ticket ADD COLUMN IF NOT EXISTS assignment_status varchar;
                ALTER TABLE website_helpdesk_ticket ADD COLUMN IF NOT EXISTS assigned_date timestamp;
                UPDATE website_helpdesk_ticket SET assignment_status = CASE WHEN assigned_employee_id IS NOT NULL THEN 'assigned' ELSE 'pending' END WHERE assignment_status IS NULL;
            """)
        except Exception:
            pass

    def _sync_to_odoo_helpdesk(self):
        if self.env.context.get('skip_helpdesk_sync') or 'helpdesk.ticket' not in self.env:
            return

        hd_model = self.env['helpdesk.ticket'].sudo()
        for rec in self:
            try:
                target = False
                try:
                    target = rec.helpdesk_ticket_id
                except Exception:
                    target = False
                if not target or not target.exists():
                    target = hd_model.search([
                        ('partner_id', '=', rec.partner_id.id if rec.partner_id else False),
                        ('name', '=', rec.name)
                    ], limit=1)
                    if not target and rec.ticket_number:
                        target = hd_model.search([('ticket_ref', '=', rec.ticket_number)], limit=1)

                default_team = self.env['helpdesk.team'].sudo().search([], limit=1)
                stg = False
                if hasattr(hd_model, '_map_website_stage_to_stage_id'):
                    stg = hd_model._map_website_stage_to_stage_id(rec.stage, default_team)

                vals = {
                    'name': rec.name,
                    'partner_id': rec.partner_id.id if rec.partner_id else False,
                    'user_id': rec.user_id.id if rec.user_id else False,
                    'priority': rec.priority if rec.priority in ['0', '1', '2', '3'] else '0',
                    'description': rec.description or '',
                }
                if hasattr(hd_model, 'assignment_status'):
                    vals['assignment_status'] = rec.assignment_status or ('assigned' if rec.assigned_employee_id else 'pending')
                if stg:
                    vals['stage_id'] = stg.id
                if default_team and not (target and target.team_id):
                    vals['team_id'] = default_team.id
                if hasattr(rec, 'ticket_project_id') and rec.ticket_project_id and hasattr(hd_model, 'ticket_project_id'):
                    vals['ticket_project_id'] = rec.ticket_project_id.id
                elif hasattr(hd_model, 'ticket_project_id') and hasattr(target, 'ticket_project_id') and target and not getattr(rec, 'ticket_project_id', False):
                    vals['ticket_project_id'] = False
                if hasattr(rec, 'assigned_employee_id') and rec.assigned_employee_id and hasattr(hd_model, 'assigned_employee_id'):
                    vals['assigned_employee_id'] = rec.assigned_employee_id.id
                    emp_user = rec.assigned_employee_id.user_id or self.env['res.users'].sudo().search([('name', '=ilike', rec.assigned_employee_id.name)], limit=1)
                    if emp_user:
                        vals['user_id'] = emp_user.id
                elif hasattr(hd_model, 'assigned_employee_id') and not getattr(rec, 'assigned_employee_id', False):
                    vals['assigned_employee_id'] = False
                    vals['user_id'] = False
                if hasattr(rec, 'existing_ticket_ids') and rec.existing_ticket_ids and hasattr(hd_model, 'existing_ticket_ids'):
                    hd_exist = [t.helpdesk_ticket_id.id for t in rec.existing_ticket_ids if t.helpdesk_ticket_id]
                    if hd_exist:
                        vals['existing_ticket_ids'] = [(6, 0, hd_exist)]
                if hasattr(rec, 'existing_ticket_id') and hasattr(hd_model, 'existing_ticket_id'):
                    if rec.existing_ticket_id and rec.existing_ticket_id.helpdesk_ticket_id:
                        vals['existing_ticket_id'] = rec.existing_ticket_id.helpdesk_ticket_id.id
                    elif not rec.existing_ticket_id:
                        vals['existing_ticket_id'] = False

                if target and target.exists():
                    changed_vals = {}
                    if (target.name or '') != (vals.get('name') or ''):
                        changed_vals['name'] = vals['name']
                    if (target.partner_id.id if target.partner_id else False) != vals.get('partner_id'):
                        changed_vals['partner_id'] = vals['partner_id']
                    if (target.user_id.id if target.user_id else False) != vals.get('user_id'):
                        changed_vals['user_id'] = vals['user_id']
                    if str(target.priority or '0') != str(vals.get('priority', '0')):
                        changed_vals['priority'] = vals['priority']
                    if (target.description or '') != (vals.get('description') or ''):
                        changed_vals['description'] = vals['description']
                    if 'stage_id' in vals and (target.stage_id.id if target.stage_id else False) != vals['stage_id']:
                        changed_vals['stage_id'] = vals['stage_id']
                    if 'team_id' in vals and (target.team_id.id if target.team_id else False) != vals['team_id']:
                        changed_vals['team_id'] = vals['team_id']
                    if 'ticket_project_id' in vals and hasattr(target, 'ticket_project_id') and (target.ticket_project_id.id if target.ticket_project_id else False) != vals['ticket_project_id']:
                        changed_vals['ticket_project_id'] = vals['ticket_project_id']
                    if 'assigned_employee_id' in vals and hasattr(target, 'assigned_employee_id') and (target.assigned_employee_id.id if target.assigned_employee_id else False) != vals['assigned_employee_id']:
                        changed_vals['assigned_employee_id'] = vals['assigned_employee_id']
                    if 'assignment_status' in vals and hasattr(target, 'assignment_status') and getattr(target, 'assignment_status', False) != vals['assignment_status']:
                        changed_vals['assignment_status'] = vals['assignment_status']
                    if 'existing_ticket_ids' in vals and hasattr(target, 'existing_ticket_ids'):
                        changed_vals['existing_ticket_ids'] = vals['existing_ticket_ids']
                    if 'existing_ticket_id' in vals and hasattr(target, 'existing_ticket_id') and (target.existing_ticket_id.id if target.existing_ticket_id else False) != vals['existing_ticket_id']:
                        changed_vals['existing_ticket_id'] = vals['existing_ticket_id']
                    if hasattr(target, 'assigned_date') and rec.assigned_date and target.assigned_date != rec.assigned_date:
                        changed_vals['assigned_date'] = rec.assigned_date

                    if changed_vals:
                        target.with_context(skip_helpdesk_sync=True).write(changed_vals)
                    if not rec.helpdesk_ticket_id or rec.helpdesk_ticket_id.id != target.id:
                        super(WebsiteHelpdeskTicket, rec.with_context(skip_helpdesk_sync=True)).write({'helpdesk_ticket_id': target.id})
                else:
                    new_hd = hd_model.with_context(skip_helpdesk_sync=True).create(vals)
                    super(WebsiteHelpdeskTicket, rec.with_context(skip_helpdesk_sync=True)).write({'helpdesk_ticket_id': new_hd.id})
            except Exception as e:
                pass

    def _apply_auto_assignment(self, vals):
        ICP = self.env['ir.config_parameter'].sudo()
        mode = ICP.get_param('website_helpdesk_portal.assignment_mode', default='manual')
        if mode != 'auto':
            return
        rule_ticket_count = ICP.get_param('website_helpdesk_portal.auto_rule_ticket_count', default='True') == 'True'
        rule_assigned_date = ICP.get_param('website_helpdesk_portal.auto_rule_assigned_date', default='True') == 'True'
        
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
        
        def candidate_sort_key(emp):
            cnt = self.search_count([
                ('assigned_employee_id', '=', emp.id),
                ('stage', 'not in', ['resolved', 'solved', 'cancelled'])
            ]) if rule_ticket_count else 0
            
            if rule_assigned_date:
                last_ticket = self.search([
                    ('assigned_employee_id', '=', emp.id),
                    ('assigned_date', '!=', False)
                ], order='assigned_date desc', limit=1)
                t_dt = last_ticket.assigned_date or datetime.min
            else:
                t_dt = datetime.min
            return (cnt, t_dt)

        chosen_emp = min(candidates, key=candidate_sort_key)
            
        now = fields.Datetime.now()
        vals['assigned_employee_id'] = chosen_emp.id
        vals['assignment_status'] = 'assigned'
        vals['assigned_date'] = now
        emp_user = chosen_emp.user_id or self.env['res.users'].sudo().search([('name', '=ilike', chosen_emp.name)], limit=1)
        if emp_user:
            vals['user_id'] = emp_user.id

    @api.model_create_multi
    def create(self, vals_list):
        category_field = self._fields.get('category')
        valid_cats = set(dict(category_field.selection).keys()) if (category_field and hasattr(category_field, 'selection') and category_field.selection) else {'billing', 'technical', 'refund', 'account', 'other', 'feature'}
        for vals in vals_list:
            if 'category' in vals and vals['category'] not in valid_cats:
                vals['category'] = 'technical' if vals['category'] in ['other', 'feature'] else 'billing'

            if vals.get('ticket_number', 'New') == 'New':
                seq = self.env['ir.sequence'].next_by_code('website.helpdesk.ticket') or ''
                if not seq:
                    last_id = self.search([], order='id desc', limit=1).id or 5
                    seq = f"#{last_id + 1:05d}"
                vals['ticket_number'] = seq
            
            if not vals.get('stage_update_date'):
                vals['stage_update_date'] = fields.Datetime.now()

            # Automatic assignment check if unassigned
            if not vals.get('assigned_employee_id'):
                self._apply_auto_assignment(vals)

            # Strict Ticket Assignment Workflow:
            if not vals.get('assigned_employee_id'):
                vals['assigned_employee_id'] = False
                vals['user_id'] = False
                vals['assignment_status'] = 'pending'
                if not vals.get('history_trail'):
                    vals['history_trail'] = "Opened by customer → Pending Assignment"
            else:
                vals['assignment_status'] = 'assigned'
                if not vals.get('assigned_date'):
                    vals['assigned_date'] = fields.Datetime.now()
                if not vals.get('user_id'):
                    emp = self.env['hr.employee'].browse(vals['assigned_employee_id'])
                    if emp.exists():
                        emp_user = emp.user_id or self.env['res.users'].sudo().search([('name', '=ilike', emp.name)], limit=1)
                        if emp_user:
                            vals['user_id'] = emp_user.id
                if not vals.get('history_trail'):
                    agent_name = "Staff"
                    if vals.get('user_id'):
                        user = self.env['res.users'].browse(vals['user_id'])
                        agent_name = user.name.split()[0] if user.name else "Staff"
                    vals['history_trail'] = f"Opened by customer → assigned to {agent_name} → awaiting response"

        records = super().create(vals_list)
        records._sync_to_odoo_helpdesk()
        return records

    def write(self, vals):
        if 'category' in vals:
            category_field = self._fields.get('category')
            valid_cats = set(dict(category_field.selection).keys()) if (category_field and hasattr(category_field, 'selection') and category_field.selection) else {'billing', 'technical', 'refund', 'account', 'other', 'feature'}
            if vals['category'] not in valid_cats:
                vals['category'] = 'technical' if vals['category'] in ['other', 'feature'] else 'billing'

        if 'assigned_employee_id' in vals:
            if vals['assigned_employee_id']:
                vals['assignment_status'] = 'assigned'
                vals['assigned_date'] = vals.get('assigned_date') or fields.Datetime.now()
                if 'user_id' not in vals:
                    emp = self.env['hr.employee'].browse(vals['assigned_employee_id'])
                    if emp.exists():
                        emp_user = emp.user_id or self.env['res.users'].sudo().search([('name', '=ilike', emp.name)], limit=1)
                        vals['user_id'] = emp_user.id if emp_user else False
                
                emp = self.env['hr.employee'].browse(vals['assigned_employee_id'])
                emp_name = emp.name if emp.exists() else 'Staff'
                now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                for rec in self:
                    rec.message_post(
                        body=f"Assigned to {emp_name} on {now_str}",
                        subtype_xmlid='mail.mt_note'
                    )
                    rec.add_history_milestone(f"Assigned to {emp_name}")
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
                        # Exiting in progress: accumulate elapsed progress seconds
                        start_dt = rec.progress_start_date or rec.stage_update_date
                        if start_dt:
                            elapsed = max(0, int((now - start_dt).total_seconds()))
                            vals['in_progress_duration'] = (rec.in_progress_duration or 0) + elapsed
                        vals['progress_start_date'] = False
                    elif new_stage in ['progress', 'in_progress'] and old_stage not in ['progress', 'in_progress']:
                        # Entering in progress: set progress_start_date
                        vals['progress_start_date'] = now
                    elif new_stage in ['new', 'open']:
                        # Reset back to new: reset in_progress_duration and progress_start_date
                        vals['in_progress_duration'] = 0
                        vals['progress_start_date'] = False

            stage_changing = any(rec.stage != new_stage for rec in self)
            if stage_changing:
                if 'stage_update_date' not in vals:
                    vals['stage_update_date'] = fields.Datetime.now()
                if new_stage == 'resolved' and not vals.get('closed_date'):
                    vals['closed_date'] = fields.Datetime.now()
                elif new_stage != 'resolved' and 'closed_date' not in vals:
                    vals['closed_date'] = False

        res = super().write(vals)
        if not self.env.context.get('skip_helpdesk_sync'):
            sync_fields = {'name', 'partner_id', 'user_id', 'priority', 'description', 'stage', 'ticket_project_id', 'assigned_employee_id', 'assignment_status', 'existing_ticket_id'}
            if any(f in vals for f in sync_fields):
                self._sync_to_odoo_helpdesk()
        return res

    def unlink(self):
        for rec in self:
            if rec.helpdesk_ticket_id and rec.helpdesk_ticket_id.exists():
                try:
                    rec.helpdesk_ticket_id.with_context(skip_helpdesk_sync=True).unlink()
                except Exception:
                    pass
        return super().unlink()

    @api.depends('stage', 'stage_update_date', 'sla_duration')
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
            
            if rec.stage == 'rotting':
                rec.rotting_statusbar_duration = f"Rotting - {duration_str or '3h 20m'}"
            elif rec.stage == 'progress':
                rec.rotting_statusbar_duration = f"In progress - {duration_str or '45m'}"
            elif rec.stage in ['solved', 'resolved']:
                rec.rotting_statusbar_duration = "Solved"
            elif rec.stage == 'new':
                rec.rotting_statusbar_duration = f"New - {duration_str or 'Just now'}"
            elif rec.stage == 'on_hold':
                rec.rotting_statusbar_duration = f"On Hold - {duration_str or 'Paused'}"
            elif rec.stage == 'cancelled':
                rec.rotting_statusbar_duration = "Cancelled"
            else:
                rec.rotting_statusbar_duration = rec.stage or 'Open'
            rec.sla_status_text = rec.rotting_statusbar_duration

    def action_set_progress(self):
        now = fields.Datetime.now()
        for rec in self:
            agent_name = rec.user_id.name.split()[0] if rec.user_id else "Agent"
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
            agent_name = rec.user_id.name.split()[0] if rec.user_id else "Agent"
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
            rec.with_context(skip_helpdesk_sync=True).write({'history_trail': new_trail})


class WebsiteHelpdeskMessage(models.Model):
    _name = 'website.helpdesk.message'
    _description = 'Helpdesk Chat Message'
    _order = 'create_date asc, id asc'

    ticket_id = fields.Many2one('website.helpdesk.ticket', string='Ticket', ondelete='cascade', required=False)
    helpdesk_ticket_id = fields.Many2one('helpdesk.ticket', string='Helpdesk Ticket', ondelete='cascade', index=True)
    author_type = fields.Selection([
        ('customer', 'Customer'),
        ('employee', 'Employee'),
    ], string='Author Type', default='customer', required=True)

    sender_name = fields.Char(string='Sender Name', required=True)
    body = fields.Text(string='Message Content', required=True)
    is_internal_note = fields.Boolean(string='Internal Staff Note', default=False)
    timestamp_str = fields.Char(string='Time', compute='_compute_time_str', store=False)

    @api.depends('create_date')
    def _compute_time_str(self):
        for rec in self:
            if rec.create_date:
                rec.timestamp_str = rec.create_date.strftime('%I:%M %p')
            else:
                rec.timestamp_str = ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('helpdesk_ticket_id') and vals.get('ticket_id'):
                try:
                    wt = self.env['website.helpdesk.ticket'].sudo().browse(vals['ticket_id'])
                    if wt.exists() and wt.helpdesk_ticket_id:
                        vals['helpdesk_ticket_id'] = wt.helpdesk_ticket_id.id
                except Exception:
                    pass
        records = super().create(vals_list)
        for rec in records:
            target_hd = rec.helpdesk_ticket_id or (rec.ticket_id.helpdesk_ticket_id if rec.ticket_id else False)
            if target_hd and rec.body:
                try:
                    target_hd.sudo().message_post(
                        body=f"[{rec.sender_name}]: {rec.body}",
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception:
                    pass
        return records

    def is_message_read_by_receiver(self):
        for rec in self:
            try:
                t_id = rec.helpdesk_ticket_id.id if rec.helpdesk_ticket_id else (rec.ticket_id.id if rec.ticket_id else 0)
                if not t_id:
                    return False
                role = 'emp' if rec.author_type == 'customer' else 'cust'
                key = f'helpdesk_ticket_{t_id}_{role}_last_read'
                val = int(rec.env['ir.config_parameter'].sudo().get_param(key, default='0') or 0)
                if rec.id <= val:
                    return True
                other_type = '!=' if rec.author_type == 'customer' else '='
                domain = [('id', '>', rec.id), ('author_type', other_type, 'customer')]
                if rec.helpdesk_ticket_id:
                    domain.append(('helpdesk_ticket_id', '=', rec.helpdesk_ticket_id.id))
                elif rec.ticket_id:
                    domain.append(('ticket_id', '=', rec.ticket_id.id))
                if rec.search_count(domain) > 0:
                    return True
            except Exception:
                pass
            return False
        return False
                