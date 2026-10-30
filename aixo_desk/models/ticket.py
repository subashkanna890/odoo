import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PRIORITIES = [('urgent', 'Urgent'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')]
STATES = [('open', 'Open'), ('on_hold', 'On Hold'), ('escalated', 'Escalated'), ('closed', 'Closed')]
CHANNELS = [('email', 'Email'), ('phone', 'Phone'), ('web', 'Web'), ('chat', 'Chat'), ('whatsapp', 'WhatsApp')]
CLASSIFICATIONS = [('question', 'Question'), ('problem', 'Problem'),
                   ('feature', 'Feature request'), ('others', 'Others')]
CUSTOMER_STATE_LABELS = {
    'open': 'Open', 'escalated': 'Open', 'on_hold': 'Waiting for your reply', 'closed': 'Resolved',
}
AT_RISK_FRACTION = 0.2


class AixoTicket(models.Model):
    _name = 'aixo.ticket'
    _description = 'Aixo Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    number = fields.Char(readonly=True, copy=False, index=True, default='New')
    name = fields.Char(string='Subject', required=True, tracking=True)
    description = fields.Html(sanitize_style=True)
    partner_id = fields.Many2one('res.partner', string='Contact', required=True,
                                 tracking=True, index=True, ondelete='restrict')
    account_id = fields.Many2one('res.partner', string='Account',
                                 related='partner_id.commercial_partner_id', store=True)
    email = fields.Char(compute='_compute_contact_details', store=True, readonly=False)
    phone = fields.Char(compute='_compute_contact_details', store=True, readonly=False)

    state = fields.Selection(STATES, default='open', required=True, tracking=True, index=True)
    priority = fields.Selection(PRIORITIES, default='medium', tracking=True)
    channel = fields.Selection(CHANNELS, default='web', tracking=True)
    lang_id = fields.Many2one('res.lang', string='Language')
    classification = fields.Selection(CLASSIFICATIONS)

    owner_id = fields.Many2one('res.users', string='Ticket owner', tracking=True, index=True,
                               domain=[('share', '=', False)])
    team_id = fields.Many2one('aixo.team', string='Team / department', tracking=True, index=True)
    product_id = fields.Many2one('aixo.product', string='Product')
    project_id = fields.Many2one('aixo.project', string='Project', tracking=True, index=True)
    due_date = fields.Datetime(tracking=True, index=True)
    tag_ids = fields.Many2many('aixo.ticket.tag', string='Tags')
    template_id = fields.Many2one('aixo.ticket.template', string='Template')

    # SLA
    sla_policy_id = fields.Many2one('aixo.sla.policy', string='SLA policy')
    first_response_deadline = fields.Datetime(copy=False)
    resolution_deadline = fields.Datetime(copy=False)
    responded_on = fields.Datetime(copy=False)
    hold_since = fields.Datetime(copy=False)
    sla_status = fields.Selection(
        [('on_time', 'On time'), ('at_risk', 'At risk'), ('breached', 'Breached')],
        default='on_time', copy=False, index=True)
    is_overdue = fields.Boolean(compute='_compute_is_overdue', store=True, index=True)

    # Closing
    closed_on = fields.Datetime(copy=False)
    resolution_summary = fields.Html(copy=False)
    notify_resolution = fields.Boolean(string='Notify customer and add to knowledge base', copy=False)
    rating = fields.Selection([('good', 'Good'), ('okay', 'Okay'), ('bad', 'Bad')], copy=False)
    rating_comment = fields.Text(copy=False)
    access_token = fields.Char(copy=False, index=True)

    time_entry_ids = fields.One2many('aixo.time.entry', 'ticket_id', string='Time entries')
    hours_logged = fields.Float(compute='_compute_hours_logged')
    reply_count = fields.Integer(compute='_compute_reply_count')
    customer_state_label = fields.Char(compute='_compute_customer_state_label')

    _access_token_uniq = models.Constraint(
        'unique (access_token)', 'The ticket access token must be unique.')
    _state_owner_idx = models.Index('(state, owner_id)')

    # ------------------------------------------------------------------ computes

    @api.depends('partner_id')
    def _compute_contact_details(self):
        for ticket in self:
            ticket.email = ticket.partner_id.email
            ticket.phone = ticket.partner_id.phone or ticket.partner_id.desk_mobile

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for ticket in self:
            ticket.is_overdue = bool(
                ticket.due_date and ticket.due_date < now and ticket.state != 'closed')

    @api.depends('time_entry_ids.duration')
    def _compute_hours_logged(self):
        groups = self.env['aixo.time.entry']._read_group(
            [('ticket_id', 'in', self.ids)], ['ticket_id'], ['duration:sum'])
        totals = {ticket.id: total for ticket, total in groups}
        for ticket in self:
            ticket.hours_logged = totals.get(ticket.id, 0.0)

    def _compute_reply_count(self):
        # Public replies only: internal notes are not "replies" for customers.
        note = self.env.ref('mail.mt_note')
        groups = self.env['mail.message'].sudo()._read_group(
            [('model', '=', 'aixo.ticket'), ('res_id', 'in', self.ids),
             ('message_type', 'in', ('email', 'comment', 'email_outgoing')),
             ('subtype_id', '!=', note.id)],
            ['res_id'], ['__count'])
        counts = dict(groups)
        for ticket in self:
            ticket.reply_count = counts.get(ticket.id, 0)

    @api.depends('state')
    def _compute_customer_state_label(self):
        for ticket in self:
            ticket.customer_state_label = CUSTOMER_STATE_LABELS[ticket.state]

    @api.depends('number', 'name')
    def _compute_display_name(self):
        for ticket in self:
            ticket.display_name = f"#{ticket.number} {ticket.name}" if ticket.number else ticket.name

    # ----------------------------------------------------------------- lifecycle

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if vals.get('number', 'New') == 'New':
                vals['number'] = sequence.next_by_code('aixo.ticket') or 'New'
            vals.setdefault('access_token', secrets.token_urlsafe(24))
            self._apply_template_defaults(vals)
        tickets = super().create(vals_list)
        for ticket in tickets:
            ticket._compute_sla_deadlines()
            if not ticket.owner_id:
                ticket._auto_assign()
            ticket._notify_assignment()
        return tickets

    @api.model
    def _apply_template_defaults(self, vals):
        template = self.env['aixo.ticket.template'].browse(vals.get('template_id'))
        if not template:
            return
        if template.priority:
            vals.setdefault('priority', template.priority)
        if template.classification:
            vals.setdefault('classification', template.classification)
        if template.team_id:
            vals.setdefault('team_id', template.team_id.id)
        if template.description:
            vals.setdefault('description', template.description)

    def write(self, vals):
        previous = {t.id: t.owner_id for t in self} if 'owner_id' in vals else {}
        closing = self.filtered(lambda t: t.state != 'closed') if vals.get('state') == 'closed' else self.browse()
        res = self._write_with_rules(vals)
        for ticket in self:
            if previous and ticket.owner_id != previous[ticket.id]:
                ticket._notify_assignment()
        for ticket in closing:
            ticket._send_csat()
        return res

    def _write_with_rules(self, vals):
        now = fields.Datetime.now()
        if 'state' in vals:
            new_state = vals['state']
            for ticket in self:
                if new_state == 'closed' and ticket.state != 'closed':
                    summary = vals.get('resolution_summary', ticket.resolution_summary)
                    if not summary or not summary.strip():
                        raise ValidationError(_("A resolution summary is required to close a ticket."))
                if new_state == 'on_hold' and ticket.state != 'on_hold':
                    ticket.hold_since = now
                elif ticket.state == 'on_hold' and new_state != 'on_hold':
                    ticket._resume_sla(now)
            if new_state == 'closed':
                vals.setdefault('closed_on', now)
            else:
                vals.setdefault('closed_on', False)
        if {'priority', 'team_id', 'partner_id'} & set(vals) and 'sla_policy_id' not in vals:
            res = super().write(vals)
            self._compute_sla_deadlines()
            return res
        return super().write(vals)

    # ------------------------------------------------------------------------ SLA

    def _compute_sla_deadlines(self):
        for ticket in self:
            # SLA configuration is internal; portal users creating a ticket must still get deadlines.
            policy = ticket.sla_policy_id.sudo() or self.env['aixo.sla.policy'].sudo()._find_policy(ticket.partner_id)
            target = policy._target_for(ticket.priority) if policy else False
            if not target:
                continue
            hours = policy.business_hours_id or self.env['aixo.business.hours'].sudo().get_default()
            start = ticket.create_date or fields.Datetime.now()
            values = {'sla_policy_id': policy.id}
            if not ticket.responded_on:
                values['first_response_deadline'] = hours.add_work_hours(
                    start, target.first_response_hours, ticket.team_id) if hours else \
                    start + timedelta(hours=target.first_response_hours)
            values['resolution_deadline'] = hours.add_work_hours(
                start, target.resolution_hours, ticket.team_id) if hours else \
                start + timedelta(hours=target.resolution_hours)
            if not ticket.due_date:
                values['due_date'] = values['resolution_deadline']
            ticket.write(values)

    def _resume_sla(self, now):
        """Shift deadlines by the time the ticket spent On Hold (SLA paused)."""
        self.ensure_one()
        if not self.hold_since:
            return
        paused = now - self.hold_since
        values = {'hold_since': False}
        if self.resolution_deadline:
            values['resolution_deadline'] = self.resolution_deadline + paused
        if self.first_response_deadline and not self.responded_on:
            values['first_response_deadline'] = self.first_response_deadline + paused
        if self.due_date:
            values['due_date'] = self.due_date + paused
        super().write(values)

    def _sla_state(self, now=None):
        """Return on_time / at_risk / breached for an open ticket."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        if self.state == 'closed' or self.hold_since:
            return self.sla_status
        deadlines = []
        if not self.responded_on and self.first_response_deadline:
            deadlines.append(self.first_response_deadline)
        if self.resolution_deadline:
            deadlines.append(self.resolution_deadline)
        if not deadlines:
            return 'on_time'
        deadline = min(deadlines)
        if deadline < now:
            return 'breached'
        total = deadline - (self.create_date or now)
        if total.total_seconds() > 0 and (deadline - now) < total * AT_RISK_FRACTION:
            return 'at_risk'
        return 'on_time'

    @api.model
    def _cron_update_sla(self):
        """Refresh SLA status and overdue flags; notify on transitions."""
        now = fields.Datetime.now()
        tickets = self.search([('state', '!=', 'closed')])
        tickets._compute_is_overdue()
        for ticket in tickets:
            new_status = ticket._sla_state(now)
            if new_status != ticket.sla_status:
                ticket.sla_status = new_status
                if new_status in ('at_risk', 'breached') and ticket.owner_id:
                    self.env['aixo.notification']._notify(
                        ticket.owner_id, 'sla',
                        _("SLA %(status)s: ticket #%(number)s “%(name)s”",
                          status=dict(self._fields['sla_status'].selection)[new_status].lower(),
                          number=ticket.number, name=ticket.name),
                        ticket)

    # ------------------------------------------------------------------ assignment

    def _auto_assign(self):
        for ticket in self:
            rule = self.env['aixo.assignment.rule']._find_rule(ticket)
            if rule:
                owner = rule._pick_user(ticket)
                if owner:
                    ticket.owner_id = owner

    # ---------------------------------------------------------------- state actions

    def action_close(self, summary, notify=False):
        self.ensure_one()
        self.write({'state': 'closed', 'resolution_summary': summary, 'notify_resolution': notify})

    def action_reopen(self):
        self.write({'state': 'open'})

    def action_mark_responded(self):
        for ticket in self.filtered(lambda t: not t.responded_on):
            ticket.responded_on = fields.Datetime.now()

    def _send_csat(self):
        """Queue the one-click satisfaction email when a ticket is closed (setting-controlled)."""
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('aixo_desk.csat_enabled') != 'True' or not self.partner_id.email or self.rating:
            return
        base = (icp.get_param('web.base.url') or '').rstrip('/')
        links = [(label, f"{base}/desk/csat/{self.access_token}/{score}")
                 for score, label in (('good', _("Good")), ('okay', _("Okay")), ('bad', _("Bad")))]
        body = self.env['ir.qweb']._render('aixo_desk.mail_csat', {
            'name': self.partner_id.name, 'number': self.number, 'subject': self.name, 'links': links,
            'company_name': icp.get_param('aixo_desk.company_name') or 'Aixo Desk'})
        self.env['mail.mail'].sudo().create({
            'subject': _("How did we do? Ticket #%s", self.number), 'body_html': body,
            'email_to': self.partner_id.email,
            'email_from': icp.get_param('aixo_desk.support_email') or self.env.company.email_formatted,
            'auto_delete': True,
        })

    def _notify_assignment(self):
        """Tell the new owner about the assignment (not when they assigned it to themselves)."""
        self.ensure_one()
        if self.owner_id and self.owner_id != self.env.user:
            self.env['aixo.notification']._notify(
                self.owner_id, 'assign',
                _("Ticket #%(number)s “%(name)s” from %(contact)s was assigned to you",
                  number=self.number, name=self.name, contact=self.partner_id.name),
                self)

    def _check_can_assign(self, user):
        if user and user.share:
            raise UserError(_("Tickets can only be assigned to employees."))
