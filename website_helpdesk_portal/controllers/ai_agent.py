# -*- coding: utf-8 -*-
"""
Helpdesk AI Agent Service (Maya AI Engine)
Production-grade Odoo 19 Helpdesk AI Agent with Gemini Tool Calling,
RAG retrieval, context memory, and secure live data operations.
"""

import re
import json
import logging
import base64
import os
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, date

from odoo import fields, _
from odoo.osv.expression import OR, AND

_logger = logging.getLogger(__name__)

# =====================================================================
# GEMINI FUNCTION CALLING TOOL DECLARATIONS (OpenAPI Schema)
# =====================================================================
GEMINI_TOOLS_DECLARATIONS = [
    {
        "name": "search_tickets",
        "description": "Search and list live Helpdesk tickets with filters for status/stage, priority, overdue criteria, due today, project, customer, or keywords.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords matching ticket title, subject, or description"},
                "stage": {"type": "string", "description": "Stage code: new, progress, on_hold, solved, cancelled, rotting, resolved"},
                "priority": {"type": "string", "description": "Priority: 0 (Low), 1 (Medium), 2 (High), 3 (Urgent)"},
                "category": {"type": "string", "description": "Category: billing, technical, refund, account, other, feature"},
                "project_name": {"type": "string", "description": "Filter by project name or ID"},
                "customer_name": {"type": "string", "description": "Filter by customer name or email"},
                "overdue_only": {"type": "boolean", "description": "Set true to filter strictly for overdue / rotting tickets"},
                "due_today_only": {"type": "boolean", "description": "Set true to filter strictly for tickets due today"},
                "assigned_to_me": {"type": "boolean", "description": "Set true to filter tickets assigned to current user/employee"},
                "limit": {"type": "integer", "description": "Maximum number of records to return (default 10)"}
            }
        }
    },
    {
        "name": "get_ticket_details",
        "description": "Retrieve complete details, status, history, and SLA metrics for a specific ticket by number (e.g. '#00003', 'HD-102', '3') or ID, and synchronize screen view.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or database ID (e.g. '#00003', '3', 'HD-102')"}
            },
            "required": ["ticket_id_or_number"]
        }
    },
    {
        "name": "get_my_projects",
        "description": "List all accessible projects for the current employee or project manager, including team name, tasks count, and active ticket metrics.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary_only": {"type": "boolean", "description": "Set true for compact summary"}
            }
        }
    },
    {
        "name": "get_project_summary",
        "description": "Get detailed summary, ticket statistics, overdue counts, and team members for a specific project.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name_or_id": {"type": "string", "description": "Name or ID of the project"}
            },
            "required": ["project_name_or_id"]
        }
    },
    {
        "name": "get_team_ticket_summary",
        "description": "Generate a comprehensive team breakdown of tickets by stage, priority, and assigned staff for a support team.",
        "parameters": {
            "type": "object",
            "properties": {
                "team_name_or_id": {"type": "string", "description": "Optional team name or ID"}
            }
        }
    },
    {
        "name": "search_customers",
        "description": "Search accessible customer records with contact details, company, and open tickets count (Internal staff / PM only).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Customer name, email, or phone search keywords"},
                "limit": {"type": "integer", "description": "Max customers to return (default 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_helpdesk_documentation",
        "description": "Search verified Helpdesk knowledge base, manuals, troubleshooting SOPs, FAQs, and resolved solutions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Technical topic, error message, or troubleshooting search keywords"},
                "category": {"type": "string", "description": "Document type: faq, manual, sop, resolved_ticket, project_doc"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "draft_ticket_creation",
        "description": "Draft a new support ticket and present an interactive preview card to the user for confirmation before creating.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Ticket subject or title"},
                "description": {"type": "string", "description": "Detailed explanation of the issue"},
                "category": {"type": "string", "description": "Category: billing, technical, refund, account, other, feature"},
                "priority": {"type": "string", "description": "Priority: 0 (Low), 1 (Medium), 2 (High), 3 (Urgent)"},
                "project_name": {"type": "string", "description": "Project name to associate with this ticket"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_helpdesk_ticket",
        "description": "Update permitted fields (stage, priority, or internal note) for an existing Helpdesk ticket after user request.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or ID"},
                "stage": {"type": "string", "description": "Target stage: new, progress, on_hold, solved, cancelled, rotting, resolved"},
                "priority": {"type": "string", "description": "Target priority: 0 (Low), 1 (Medium), 2 (High), 3 (Urgent)"},
                "internal_note": {"type": "string", "description": "Internal note or update message to log on chatter"}
            },
            "required": ["ticket_id_or_number"]
        }
    },
    {
        "name": "assign_helpdesk_ticket",
        "description": "Assign an existing Helpdesk ticket to a specific employee or support team staff member.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or ID"},
                "employee_name": {"type": "string", "description": "Name or email of the employee to assign to"}
            },
            "required": ["ticket_id_or_number", "employee_name"]
        }
    },
    {
        "name": "get_ticket_reports",
        "description": "Generate aggregated report metrics and tables (stage breakdown, priority breakdown, overdue trends).",
        "parameters": {
            "type": "object",
            "properties": {
                "report_type": {"type": "string", "description": "Type: stage_breakdown, priority_breakdown, overdue_analysis, team_workload"},
                "date_range": {"type": "string", "description": "Date range: all, today, this_week, this_month"}
            }
        }
    },
    {
        "name": "summarize_ticket",
        "description": "Generate a concise, factual summary of a ticket including customer issue, key conversation events, status, assignee, and recommended next steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or database ID (defaults to active ticket if omitted)"}
            }
        }
    },
    {
        "name": "draft_customer_reply",
        "description": "Draft a professional, context-grounded customer reply based on ticket history, customer query, and knowledge base. Displays draft for agent review before sending.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or ID"},
                "instructions": {"type": "string", "description": "Specific points or tone instructions to incorporate into the draft response"}
            }
        }
    },
    {
        "name": "help_resolve_customer_issue",
        "description": "Analyze a customer problem, search verified troubleshooting SOPs and past similar solved tickets, and provide clear step-by-step resolution advice.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or ID"},
                "issue_text": {"type": "string", "description": "Summary of customer issue or error message"}
            }
        }
    },
    {
        "name": "analyze_unresolved_tickets",
        "description": "Analyze all unresolved and open helpdesk tickets, breakdown by stage and priority, detect overdue/rotting tickets and unassigned bottlenecks, and provide triage guidance.",
        "parameters": {
            "type": "object",
            "properties": {
                "team_name_or_id": {"type": "string", "description": "Optional team name or ID"}
            }
        }
    },
    {
        "name": "find_similar_tickets",
        "description": "Search past resolved tickets with matching issue descriptions or categories to compare previous solutions and outcomes.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id_or_number": {"type": "string", "description": "Ticket number or ID"},
                "issue_text": {"type": "string", "description": "Keywords or problem statement"}
            }
        }
    }
]


class HelpdeskAiAgentService:
    """
    Core AI Agent Service powering Maya AI & Zendesk-Inspired Helpdesk Copilot.
    Handles Gemini LLM tool calling, semantic intent routing, live Odoo data operations,
    and multi-turn conversational context.
    """

    CLOSED_STAGES = ['resolved', 'solved', 'cancelled', 'cancel', 'closed', 'done']

    def __init__(self, env, role='customer', current_emp=False, current_partner=False, session_context=None, active_ticket_id=None):
        self.env = env
        self.role = role or 'customer'
        self.emp = current_emp
        self.partner = current_partner
        self.user = env.user
        self.session_context = session_context or {}
        self.active_ticket_id = active_ticket_id

        # Resolve display names and permissions
        if self.emp:
            self.user_name = self.emp.name
            self.user_email = self.emp.work_email or ''
        elif self.partner:
            self.user_name = self.partner.name
            self.user_email = self.partner.email or ''
        elif not self.user._is_public():
            self.user_name = self.user.name
            self.user_email = self.user.email or ''
        else:
            self.user_name = "Guest User"
            self.user_email = ""

        ICP = env['ir.config_parameter'].sudo()
        self.bot_name = ICP.get_param('website_helpdesk_portal.ai_bot_name', default='Maya') or 'Maya'

    # =========================================================================
    # PERMISSION & BASE DOMAIN HELPERS
    # =========================================================================
    def _get_ticket_base_domain(self):
        """Construct role-enforced domain so users never see unauthorized records."""
        if self.role == 'customer':
            if self.partner:
                return [('partner_id', '=', self.partner.id)]
            return [('id', '=', 0)]

        # Employee or Project Manager
        if not self.emp:
            if not self.user._is_public():
                return [('user_id', '=', self.user.id)]
            return [('id', '=', 0)]

        emp_id = self.emp.id
        user_id = self.emp.user_id.id if self.emp.user_id else 0

        if self.role == 'project_manager':
            # PM can see tickets in their managed projects OR assigned to them
            managed_projs = self.env['project.project'].sudo().search([('employee_id', '=', emp_id)])
            proj_ids = managed_projs.ids
            if proj_ids and user_id:
                return ['|', '|', ('ticket_project_id', 'in', proj_ids), ('assigned_employee_id', '=', emp_id), ('user_id', '=', user_id)]
            elif proj_ids:
                return ['|', ('ticket_project_id', 'in', proj_ids), ('assigned_employee_id', '=', emp_id)]

        if user_id:
            return ['|', ('assigned_employee_id', '=', emp_id), ('user_id', '=', user_id)]
        return [('assigned_employee_id', '=', emp_id)]

    def _resolve_ticket_record(self, ticket_id_or_number):
        """Find standard helpdesk.ticket record with fuzzy number, ref, or ID matching."""
        if not ticket_id_or_number and self.active_ticket_id:
            ticket_id_or_number = self.active_ticket_id
        if not ticket_id_or_number:
            return None

        val = str(ticket_id_or_number).strip()
        # Clean leading # or HD-
        clean_num = re.sub(r'^[#HD\-\s]+', '', val, flags=re.IGNORECASE).strip()

        domain = self._get_ticket_base_domain()
        Ticket = self.env['helpdesk.ticket'].sudo()

        # Try ID directly if digits
        if clean_num.isdigit():
            tid = int(clean_num)
            # 1. Search in user's permitted domain
            rec = Ticket.search(domain + [('id', '=', tid)], limit=1)
            if rec:
                return rec
            # 2. Match ticket_ref or ticket_number
            rec = Ticket.search(domain + [
                '|', '|',
                ('ticket_ref', '=', f"#{tid:05d}"),
                ('ticket_ref', '=', str(tid)),
                ('ticket_number', '=ilike', f"%{clean_num}%")
            ], limit=1)
            if rec:
                return rec

        # Try matching by ticket_ref, ticket_number, or subject
        rec = Ticket.search(domain + [
            '|', '|',
            ('ticket_ref', '=ilike', f"%{clean_num}%"),
            ('ticket_number', '=ilike', f"%{clean_num}%"),
            ('name', 'ilike', val)
        ], limit=1)
        if rec:
            return rec

        # For employee/PM, if not in assigned domain, check if accessible across company
        if self.role in ['employee', 'project_manager']:
            if clean_num.isdigit():
                rec = Ticket.search([
                    '|', '|',
                    ('id', '=', int(clean_num)),
                    ('ticket_ref', '=ilike', f"%{clean_num}%"),
                    ('ticket_number', '=ilike', f"%{clean_num}%")
                ], limit=1)
                if rec:
                    return rec

        return None

    def _format_ticket_dict(self, t):
        """Extract clean structured data with live SLA and elapsed times."""
        now_dt = fields.Datetime.now() if hasattr(fields, 'Datetime') else datetime.now()
        c_date = t.create_date or now_dt
        if isinstance(c_date, str):
            try:
                c_date = fields.Datetime.from_string(c_date)
            except Exception:
                try:
                    c_date = datetime.fromisoformat(c_date.replace(' ', 'T'))
                except Exception:
                    c_date = now_dt
        try:
            elapsed_seconds = max(0, (now_dt - c_date).total_seconds())
        except Exception:
            elapsed_seconds = 0

        stg = (t.stage or 'new').lower()
        is_overdue = bool(t.sla_failed or stg == 'rotting' or elapsed_seconds > (48 * 3600))
        is_due_today = bool(not is_overdue and (24 * 3600 <= elapsed_seconds <= 48 * 3600))

        code = t.ticket_number or t.ticket_ref or f"#{t.id:05d}"
        cust_name = t.partner_id.name if t.partner_id else (t.partner_name or 'Internal Customer')
        proj_name = t.ticket_project_id.name if t.ticket_project_id else '-'
        team_name = t.team_name or (t.team_id.name if t.team_id else '-')

        # Priority label
        prio_map = {'0': 'Low', '1': 'Medium', '2': 'High', '3': 'Urgent'}
        prio_str = prio_map.get(str(t.priority), 'Normal')

        # Status duration
        hrs = int(elapsed_seconds // 3600)
        mins = int((elapsed_seconds % 3600) // 60)
        dur_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

        return {
            'id': t.id,
            'number': code,
            'name': t.name or 'Untitled Ticket',
            'stage': stg,
            'stage_display': stg.replace('_', ' ').title(),
            'priority': prio_str,
            'priority_code': str(t.priority or '0'),
            'category': getattr(t, 'category', 'technical') or 'technical',
            'project': proj_name,
            'team': team_name,
            'customer': cust_name,
            'customer_email': t.partner_email or (t.partner_id.email if t.partner_id else ''),
            'assigned': t.assigned_employee_id.name if t.assigned_employee_id else (t.user_id.name if t.user_id else 'Unassigned'),
            'is_overdue': is_overdue,
            'is_due_today': is_due_today,
            'elapsed_seconds': elapsed_seconds,
            'elapsed_str': dur_str,
            'sla_status': 'Overdue' if is_overdue else ('Due Today' if is_due_today else 'On Track'),
            'created_on': fields.Datetime.to_string(t.create_date) if t.create_date else '-',
            'description': t.clean_description or (t.description or '')[:200]
        }

    # =========================================================================
    # TOOL IMPLEMENTATIONS (PHASE 3 & 4)
    # =========================================================================

    def search_tickets(self, query=None, stage=None, priority=None, category=None,
                       project_name=None, customer_name=None, overdue_only=False,
                       due_today_only=False, assigned_to_me=False, team_name=None, limit=10):
        """Search and list live tickets matching filters."""
        domain = self._get_ticket_base_domain()
        Ticket = self.env['helpdesk.ticket'].sudo()

        if query:
            q = str(query).strip()
            # If query looks like ticket number (#3, HD-102)
            num_match = re.search(r'#?0*(\d{1,6})', q)
            if num_match:
                n = num_match.group(1)
                domain = domain + [
                    '|', '|', '|',
                    ('ticket_number', '=ilike', f"%{n}%"),
                    ('ticket_ref', '=ilike', f"%{n}%"),
                    ('id', '=', int(n) if n.isdigit() else 0),
                    ('name', 'ilike', q)
                ]
            else:
                domain = domain + ['|', ('name', 'ilike', q), ('description', 'ilike', q)]

        if stage:
            st = str(stage).lower().strip()
            if st in ['open', 'pending']:
                domain = domain + [('stage', 'not in', self.CLOSED_STAGES)]
            elif st in ['closed', 'done']:
                domain = domain + [('stage', 'in', self.CLOSED_STAGES)]
            else:
                domain = domain + [('stage', '=', st)]

        if priority is not None:
            p_val = str(priority).strip().lower()
            p_map = {'urgent': '3', 'critical': '3', 'high': '2', 'medium': '1', 'low': '0'}
            p_code = p_map.get(p_val, p_val if p_val in ['0', '1', '2', '3'] else None)
            if p_code:
                domain = domain + [('priority', '=', p_code)]

        if category:
            domain = domain + [('category', '=', str(category).lower().strip())]

        if project_name and self.role != 'customer':
            domain = domain + [('ticket_project_id.name', 'ilike', str(project_name).strip())]

        if customer_name and self.role != 'customer':
            domain = domain + ['|', ('partner_id.name', 'ilike', str(customer_name).strip()), ('partner_name', 'ilike', str(customer_name).strip())]

        if team_name and self.role != 'customer':
            domain = domain + ['|', ('team_name', 'ilike', str(team_name).strip()), ('team_id.name', 'ilike', str(team_name).strip())]

        if assigned_to_me and self.emp:
            user_id = self.emp.user_id.id if self.emp.user_id else 0
            if user_id:
                domain = domain + ['|', ('assigned_employee_id', '=', self.emp.id), ('user_id', '=', user_id)]
            else:
                domain = domain + [('assigned_employee_id', '=', self.emp.id)]

        records = Ticket.search(domain, order='create_date desc, id desc', limit=max(1, min(limit or 10, 50)))
        results = [self._format_ticket_dict(t) for t in records]

        # Apply in-memory dynamic SLA filters
        if overdue_only:
            results = [r for r in results if r['is_overdue']]
        elif due_today_only:
            results = [r for r in results if r['is_due_today']]

        return {
            'count': len(results),
            'tickets': results
        }

    def get_ticket_details(self, ticket_id_or_number):
        """Retrieve complete live ticket record and generate screen sync action."""
        ticket = self._resolve_ticket_record(ticket_id_or_number)
        if not ticket:
            return {
                'found': False,
                'message': f"Ticket '{ticket_id_or_number}' could not be found or you do not have permission to view it."
            }

        data = self._format_ticket_dict(ticket)

        # Retrieve recent chatter messages / notes
        recent_msgs = []
        try:
            if hasattr(ticket, 'message_ids') and ticket.message_ids:
                for m in ticket.message_ids.filtered(lambda msg: msg.body and len(msg.body.strip()) > 3)[:4]:
                    clean_b = re.sub(r'<[^>]+>', ' ', m.body).strip()
                    if clean_b:
                        recent_msgs.append({
                            'author': m.author_id.name if m.author_id else 'System',
                            'date': fields.Datetime.to_string(m.date) if m.date else '',
                            'body': clean_b[:180]
                        })
        except Exception:
            pass

        data['recent_messages'] = recent_msgs
        data['trigger_action'] = {
            'type': 'open_ticket',
            'ticket_id': ticket.id,
            'ticket_code': data['number'],
            'ticket_name': data['name'],
            'ticket_project': data['project'],
            'ticket_priority': data['priority'],
            'ticket_desc': data['description'],
            'ticket_stage': data['stage'],
            'ticket_category': data['category']
        }
        return {
            'found': True,
            'ticket': data
        }

    def get_my_projects(self, summary_only=False):
        """Retrieve accessible projects with workload stats."""
        if self.role == 'customer':
            # Customers only see projects their tickets belong to
            tickets = self.env['helpdesk.ticket'].sudo().search([('partner_id', '=', self.partner.id if self.partner else 0)])
            projs = tickets.mapped('ticket_project_id')
        elif self.role == 'project_manager' and self.emp:
            projs = self.env['project.project'].sudo().search(['|', ('employee_id', '=', self.emp.id), ('employee_ids', 'in', [self.emp.id])])
        elif self.emp:
            projs = self.env['project.project'].sudo().search([('employee_ids', 'in', [self.emp.id])])
            if not projs:
                projs = self.env['project.project'].sudo().search([], limit=5)
        else:
            projs = self.env['project.project'].sudo().search([], limit=5)

        proj_list = []
        Ticket = self.env['helpdesk.ticket'].sudo()
        now_dt = fields.Datetime.now()

        for p in projs:
            p_tickets = Ticket.search([('ticket_project_id', '=', p.id)])
            open_count = sum(1 for t in p_tickets if getattr(t, 'stage', '') not in self.CLOSED_STAGES)
            overdue_count = sum(1 for t in p_tickets if getattr(t, 'stage', '') not in self.CLOSED_STAGES and (
                t.sla_failed or t.stage == 'rotting' or (now_dt - (t.create_date or now_dt)).total_seconds() > 48 * 3600
            ))
            task_count = len(p.task_ids) if 'task_ids' in p._fields else 0

            proj_list.append({
                'id': p.id,
                'name': p.name,
                'team': p.team_id.name if hasattr(p, 'team_id') and p.team_id else '-',
                'manager': p.employee_id.name if hasattr(p, 'employee_id') and p.employee_id else (p.user_id.name if p.user_id else '-'),
                'tasks_count': task_count,
                'total_tickets': len(p_tickets),
                'open_tickets': open_count,
                'overdue_tickets': overdue_count
            })

        return {
            'count': len(proj_list),
            'projects': proj_list
        }

    def get_project_summary(self, project_name_or_id):
        """Retrieve detailed metrics for a specific project."""
        p_val = str(project_name_or_id).strip()
        Project = self.env['project.project'].sudo()

        proj = None
        if p_val.isdigit():
            proj = Project.browse(int(p_val))
        if not proj or not proj.exists():
            proj = Project.search([('name', 'ilike', p_val)], limit=1)

        if not proj or not proj.exists():
            return {'found': False, 'message': f"Project '{project_name_or_id}' could not be found."}

        Ticket = self.env['helpdesk.ticket'].sudo()
        p_tickets = Ticket.search([('ticket_project_id', '=', proj.id)])
        now_dt = fields.Datetime.now()

        open_tkts = [t for t in p_tickets if getattr(t, 'stage', '') not in self.CLOSED_STAGES]
        overdue_tkts = [t for t in open_tkts if (
            t.sla_failed or t.stage == 'rotting' or (now_dt - (t.create_date or now_dt)).total_seconds() > 48 * 3600
        )]
        urgent_tkts = [t for t in open_tkts if str(t.priority) in ['2', '3']]

        team_members = []
        if hasattr(proj, 'employee_ids') and proj.employee_ids:
            team_members = [e.name for e in proj.employee_ids[:8]]

        sample_tickets = [self._format_ticket_dict(t) for t in open_tkts[:5]]

        return {
            'found': True,
            'id': proj.id,
            'name': proj.name,
            'team': proj.team_id.name if hasattr(proj, 'team_id') and proj.team_id else '-',
            'manager': proj.employee_id.name if hasattr(proj, 'employee_id') and proj.employee_id else (proj.user_id.name if proj.user_id else '-'),
            'total_tickets': len(p_tickets),
            'open_tickets': len(open_tkts),
            'overdue_tickets': len(overdue_tkts),
            'urgent_tickets': len(urgent_tkts),
            'team_members': team_members,
            'sample_open_tickets': sample_tickets
        }

    def get_team_ticket_summary(self, team_name_or_id=None):
        """Generate breakdown by stage, priority, and staff for team."""
        Ticket = self.env['helpdesk.ticket'].sudo()
        domain = [('stage', 'not in', self.CLOSED_STAGES)]

        if team_name_or_id and self.role != 'customer':
            domain = domain + ['|', ('team_name', 'ilike', str(team_name_or_id).strip()), ('team_id.name', 'ilike', str(team_name_or_id).strip())]
        elif self.role == 'customer':
            domain = domain + [('partner_id', '=', self.partner.id if self.partner else 0)]

        open_tickets = Ticket.search(domain)
        now_dt = fields.Datetime.now()

        # Breakdown by stage
        stages_count = {}
        for t in open_tickets:
            stg = t.stage or 'new'
            stages_count[stg] = stages_count.get(stg, 0) + 1

        # Breakdown by priority
        prio_map = {'0': 'Low', '1': 'Medium', '2': 'High', '3': 'Urgent'}
        prio_count = {'Low': 0, 'Medium': 0, 'High': 0, 'Urgent': 0}
        for t in open_tickets:
            p = prio_map.get(str(t.priority), 'Low')
            prio_count[p] = prio_count.get(p, 0) + 1

        # Workload by assignee
        assignee_count = {}
        for t in open_tickets:
            name = t.assigned_employee_id.name if t.assigned_employee_id else (t.user_id.name if t.user_id else 'Unassigned')
            assignee_count[name] = assignee_count.get(name, 0) + 1

        overdue_cnt = sum(1 for t in open_tickets if t.sla_failed or t.stage == 'rotting' or (now_dt - (t.create_date or now_dt)).total_seconds() > 48 * 3600)

        return {
            'total_open': len(open_tickets),
            'overdue_count': overdue_cnt,
            'stage_breakdown': stages_count,
            'priority_breakdown': prio_count,
            'workload_by_staff': assignee_count
        }

    def search_customers(self, query=None, limit=5):
        """Search customer partner records with ticket metrics."""
        if self.role == 'customer':
            return {'error': 'Unauthorized: Customers cannot search other customer records.'}

        Partner = self.env['res.partner'].sudo()
        domain = [('is_company', '=', False)]
        if query:
            q = str(query).strip()
            domain = domain + ['|', '|', ('name', 'ilike', q), ('email', 'ilike', q), ('phone', 'ilike', q)]

        partners = Partner.search(domain, limit=max(1, min(limit or 5, 20)))
        Ticket = self.env['helpdesk.ticket'].sudo()
        results = []

        for p in partners:
            c_tickets = Ticket.search([('partner_id', '=', p.id)])
            open_count = sum(1 for t in c_tickets if getattr(t, 'stage', '') not in self.CLOSED_STAGES)
            results.append({
                'id': p.id,
                'name': p.name,
                'email': p.email or '-',
                'phone': p.phone or '-',
                'company': p.parent_id.name if p.parent_id else '-',
                'total_tickets': len(c_tickets),
                'open_tickets': open_count
            })

        return {
            'count': len(results),
            'customers': results
        }

    def search_helpdesk_documentation(self, query=None, category=None, limit=3):
        """Search verified Knowledge Base documents with strict scope enforcement."""
        if not query:
            return {'count': 0, 'articles': []}

        q = str(query).strip()
        # Role scopes
        if self.role == 'customer':
            allowed_scopes = ['public']
        elif self.role == 'employee':
            allowed_scopes = ['public', 'employee']
        else:
            allowed_scopes = ['public', 'employee', 'project_manager']

        Knowledge = self.env['helpdesk.ai.knowledge'].sudo()
        domain = [('access_scope', 'in', allowed_scopes), ('is_indexed', '=', True)]

        if category:
            domain = domain + [('document_type', '=', str(category).strip())]

        words = [w.strip() for w in q.split() if len(w.strip()) > 2][:4]
        if words:
            word_domain = []
            for w in words:
                word_domain = OR([word_domain, [('name', 'ilike', w), ('content', 'ilike', w)]])
            domain = domain + word_domain

        records = Knowledge.search(domain, limit=limit or 3)
        articles = []
        for r in records:
            articles.append({
                'id': r.id,
                'title': r.name,
                'type': r.document_type,
                'url': r.source_url or '',
                'content': (r.content or '')[:900]
            })

        # Built-in verified Helpdesk Knowledge if no DB records found
        if not articles:
            articles = self._get_fallback_verified_kb(q)

        return {
            'count': len(articles),
            'articles': articles
        }

    def _get_fallback_verified_kb(self, query):
        """Verified procedural knowledge for common IT and Helpdesk troubleshooting."""
        q = (query or '').lower()
        verified = []

        if any(w in q for w in ['install', 'setup', 'environment', 'crash', 'python', 'docker', 'port']):
            verified.append({
                'id': 1001,
                'title': 'App Environment & Installation Troubleshooting Guide',
                'type': 'faq',
                'url': '/helpdesk/kb/installation-troubleshooting',
                'content': """### Installation & Application Setup Troubleshooting:
1. **Dependency Verification:** Ensure Python virtualenv is active and all pip requirements match `requirements.txt`.
2. **Port Conflict Resolution:** If service fails to bind to port 8069/5432, check running listeners using `netstat -ano | findstr <port>`.
3. **Database Connectivity:** Verify PostgreSQL service status (`pg_isready`). Check `db_host`, `db_user`, and `db_password` in your configuration.
4. **Clean Asset Recompile:** In case of frontend JS syntax errors or cached assets, restart service with `-u website_helpdesk_portal` to re-bundle assets."""
            })

        if any(w in q for w in ['sla', 'overdue', 'rotting', 'policy', 'time', 'delay', 'turnaround']):
            verified.append({
                'id': 1002,
                'title': 'Helpdesk SLA & Overdue Ticket Policy SOP',
                'type': 'sop',
                'url': '/helpdesk/kb/sla-policy',
                'content': """### Helpdesk SLA and Rotting Ticket Policies:
• **Rotting / Overdue Definition:** Any ticket exceeding 48 hours without resolution, or explicitly flagged with `sla_failed = True` or moved to stage `rotting`.
• **Response Timelines:**
  - Critical / Urgent (Priority 3): First response < 15 mins, resolution < 4 hours.
  - High (Priority 2): First response < 1 hour, resolution < 12 hours.
  - Medium (Priority 1): First response < 4 hours, resolution < 24 hours.
  - Low (Priority 0): First response < 8 hours, resolution < 48 hours.
• **Escalation Protocol:** Overdue tickets are automatically highlighted with urgent badges on the Employee and PM consoles for immediate triage."""
            })

        if any(w in q for w in ['triage', 'workflow', 'assign', 'stage', 'sop', 'procedure']):
            verified.append({
                'id': 1003,
                'title': 'Employee Ticket Lifecycle & Stage Transition SOP',
                'type': 'sop',
                'url': '/helpdesk/kb/stage-sop',
                'content': """### Standard Operating Procedure for Ticket Triage:
1. **Intake (New):** Review ticket subject, customer, and category. Assign to the relevant staff or team lead.
2. **In Progress:** Change stage to `progress` once active investigation begins. Status timer starts tracking real spent time.
3. **Testing / Solved:** Once fix is verified, move to `solved`. Send resolution summary to the requester.
4. **Resolved:** Ticket is archived upon customer confirmation or 72 hours of customer inactivity."""
            })

        return verified

    def draft_ticket_creation(self, name, description, category='technical', priority='0', project_name=None):
        """Prepare interactive preview card requiring user confirmation before database write."""
        name = (name or '').strip()
        description = (description or name).strip()
        prio_map = {'0': 'Low', '1': 'Medium', '2': 'High', '3': 'Urgent'}
        prio_label = prio_map.get(str(priority), 'Normal')

        proj_rec = None
        if project_name:
            proj_rec = self.env['project.project'].sudo().search([('name', 'ilike', project_name.strip())], limit=1)

        preview = {
            'name': name,
            'description': description,
            'category': category if category in ['billing', 'technical', 'refund', 'account', 'other', 'feature'] else 'technical',
            'priority': prio_label,
            'priority_code': str(priority or '0'),
            'project_name': proj_rec.name if proj_rec else (project_name or '-'),
            'project_id': proj_rec.id if proj_rec else None
        }
        return {
            'status': 'preview_ready',
            'preview': preview,
            'instructions': 'Please verify ticket details and click "Confirm & Create Ticket" to submit.'
        }

    def create_ticket(self, name, description=None, category='technical', priority='0', project_id=None, partner_id=None):
        """Authorized ticket creation executing full Odoo Helpdesk workflow."""
        name = (name or '').strip()
        if not name:
            return {'success': False, 'message': 'Ticket subject is required.'}

        desc = (description or name).strip()

        # Partner attribution
        ticket_partner = False
        if partner_id:
            ticket_partner = self.env['res.partner'].sudo().browse(int(partner_id))
        elif self.partner:
            ticket_partner = self.partner
        elif self.emp and self.emp.user_id and self.emp.user_id.partner_id:
            ticket_partner = self.emp.user_id.partner_id
        elif not self.user._is_public():
            ticket_partner = self.user.partner_id

        # Priority normalization
        p_val = str(priority).strip().lower()
        if p_val in ['3', 'urgent']:
            p_code = '3'
        elif p_val in ['2', 'high', 'critical']:
            p_code = '2'
        elif p_val in ['1', 'medium']:
            p_code = '1'
        else:
            p_code = '0'

        ticket_vals = {
            'name': name,
            'description': desc,
            'category': category if category in ['billing', 'technical', 'refund', 'account', 'other', 'feature'] else 'technical',
            'priority': p_code,
            'stage': 'new',
            'partner_id': ticket_partner.id if ticket_partner else False,
            'partner_phone': ticket_partner.phone if ticket_partner else '',
            'sla_duration': 'Just now',
            'history_trail': f"Opened via Maya AI Assistant ({self.role.replace('_', ' ').title()})"
        }

        # Project linking
        if project_id:
            ticket_vals['ticket_project_id'] = int(project_id)
        elif self.emp:
            # Assign to default project if available
            p = self.env['project.project'].sudo().search(['|', ('employee_id', '=', self.emp.id), ('employee_ids', 'in', [self.emp.id])], limit=1)
            if p:
                ticket_vals['ticket_project_id'] = p.id

        if self.emp:
            ticket_vals['assigned_employee_id'] = self.emp.id

        ticket = self.env['helpdesk.ticket'].sudo().create(ticket_vals)
        code = ticket.ticket_number or f"#{ticket.id:05d}"

        # Trigger screen action
        trigger_action = {
            'type': 'ticket_created',
            'ticket_id': ticket.id,
            'ticket_code': code,
            'ticket_name': ticket.name,
            'ticket_project': ticket.ticket_project_id.name if ticket.ticket_project_id else '-',
            'ticket_priority': 'Urgent' if p_code == '3' else ('High' if p_code == '2' else 'Normal'),
            'ticket_stage': 'new',
            'ticket_category': ticket.category or 'technical'
        }

        return {
            'success': True,
            'ticket_id': ticket.id,
            'ticket_number': code,
            'ticket_name': ticket.name,
            'trigger_action': trigger_action,
            'message': f"Ticket **{code}** (*{ticket.name}*) has been successfully created in the Helpdesk system!"
        }

    def update_helpdesk_ticket(self, ticket_id_or_number, stage=None, priority=None, internal_note=None):
        """Update permitted fields for an existing ticket."""
        if self.role == 'customer':
            return {'success': False, 'message': 'Permission denied: Customers cannot directly mutate ticket stages or priorities.'}

        ticket = self._resolve_ticket_record(ticket_id_or_number)
        if not ticket:
            return {'success': False, 'message': f"Ticket '{ticket_id_or_number}' not found or inaccessible."}

        vals = {}
        changes = []

        if priority is not None:
            p_val = str(priority).strip().lower()
            p_map = {'urgent': '3', 'critical': '3', 'high': '2', 'medium': '1', 'low': '0'}
            p_code = p_map.get(p_val, p_val if p_val in ['0', '1', '2', '3'] else '0')
            vals['priority'] = p_code
            changes.append(f"priority to **{p_val.title()}**")

        if stage is not None:
            st_val = str(stage).strip().lower()
            st_map = {'open': 'new', 'pending': 'on_hold', 'closed': 'cancelled', 'in_progress': 'progress'}
            target_st = st_map.get(st_val, st_val if st_val in ['new', 'progress', 'on_hold', 'solved', 'cancelled', 'rotting', 'resolved'] else 'new')
            vals['stage'] = target_st
            changes.append(f"status to **{target_st.replace('_', ' ').title()}**")

        if internal_note:
            note_text = str(internal_note).strip()
            if hasattr(ticket, 'message_post'):
                ticket.message_post(body=f"<b>Maya AI Note:</b> {note_text}", message_type='comment', subtype_xmlid='mail.mt_note')
            changes.append("logged internal note")

        if vals:
            ticket.write(vals)

        code = ticket.ticket_number or f"#{ticket.id:05d}"
        change_summary = ", ".join(changes) if changes else "no changes applied"

        return {
            'success': True,
            'ticket_id': ticket.id,
            'ticket_number': code,
            'message': f"Successfully updated ticket **{code}** ({change_summary})."
        }

    def assign_helpdesk_ticket(self, ticket_id_or_number, employee_name):
        """Assign ticket to specified staff employee."""
        if self.role == 'customer':
            return {'success': False, 'message': 'Permission denied: Only staff and managers can assign tickets.'}

        ticket = self._resolve_ticket_record(ticket_id_or_number)
        if not ticket:
            return {'success': False, 'message': f"Ticket '{ticket_id_or_number}' not found."}

        emp_query = str(employee_name).strip()
        Employee = self.env['hr.employee'].sudo()
        target_emp = Employee.search(['|', ('name', 'ilike', emp_query), ('work_email', 'ilike', emp_query)], limit=1)

        if not target_emp:
            return {'success': False, 'message': f"Employee '{employee_name}' could not be found in active employee directory."}

        vals = {
            'assigned_employee_id': target_emp.id,
            'assignment_status': 'assigned',
            'assigned_date': fields.Datetime.now()
        }
        if target_emp.user_id:
            vals['user_id'] = target_emp.user_id.id

        ticket.write(vals)
        code = ticket.ticket_number or f"#{ticket.id:05d}"

        if hasattr(ticket, 'message_post'):
            ticket.message_post(body=f"Ticket assigned to {target_emp.name} via Maya AI Assistant.", subtype_xmlid='mail.mt_note')

        return {
            'success': True,
            'ticket_id': ticket.id,
            'ticket_number': code,
            'assigned_employee': target_emp.name,
            'message': f"Ticket **{code}** has been successfully assigned to **{target_emp.name}**."
        }

    def get_ticket_reports(self, report_type='stage_breakdown', date_range='all'):
        """Calculate and format statistical reports."""
        Ticket = self.env['helpdesk.ticket'].sudo()
        domain = self._get_ticket_base_domain()
        now = fields.Datetime.now()

        if date_range == 'today':
            today_start = datetime.combine(date.today(), datetime.min.time())
            domain = domain + [('create_date', '>=', today_start)]
        elif date_range == 'this_week':
            week_start = datetime.combine(date.today() - timedelta(days=date.today().weekday()), datetime.min.time())
            domain = domain + [('create_date', '>=', week_start)]
        elif date_range == 'this_month':
            month_start = datetime.combine(date.today().replace(day=1), datetime.min.time())
            domain = domain + [('create_date', '>=', month_start)]

        tickets = Ticket.search(domain)
        total = len(tickets)
        open_tkts = [t for t in tickets if getattr(t, 'stage', '') not in self.CLOSED_STAGES]
        overdue_tkts = [t for t in open_tkts if t.sla_failed or t.stage == 'rotting' or (now - (t.create_date or now)).total_seconds() > 48 * 3600]

        # Stage distribution
        stages = {}
        for t in tickets:
            s = t.stage or 'new'
            stages[s] = stages.get(s, 0) + 1

        # Priority distribution
        prio_map = {'0': 'Low', '1': 'Medium', '2': 'High', '3': 'Urgent'}
        prios = {'Low': 0, 'Medium': 0, 'High': 0, 'Urgent': 0}
        for t in open_tkts:
            p = prio_map.get(str(t.priority), 'Low')
            prios[p] = prios.get(p, 0) + 1

        return {
            'report_type': report_type,
            'total_tickets': total,
            'open_tickets': len(open_tkts),
            'overdue_tickets': len(overdue_tkts),
            'resolved_tickets': total - len(open_tkts),
            'stage_distribution': stages,
            'priority_distribution': prios
        }

    def summarize_ticket(self, ticket_id_or_number=None):
        """
        Generate a concise, factual summary containing:
        - Customer issue
        - Main events and relevant conversation history
        - Current status and assignee
        - Actions already attempted
        - Outstanding questions
        - Recommended next steps
        Distinguishes public replies from internal notes and respects permissions.
        """
        target_num = ticket_id_or_number or self.active_ticket_id
        if not target_num:
            res = self.search_tickets(limit=5)
            open_tkts = [t for t in res['tickets'] if t['stage'] not in self.CLOSED_STAGES]
            if open_tkts:
                list_str = "\n".join([f"• **{t['number']}**: *{t['name']}* ({t['customer']})" for t in open_tkts])
                return {
                    'found': False,
                    'summary': f"Please specify which ticket you would like me to summarize (e.g. `Summarize ticket {open_tkts[0]['number']}`). Here are some of your current tickets:\n\n{list_str}"
                }
            return {
                'found': False,
                'summary': "Please specify a ticket number or ID to summarize (e.g. `Summarize ticket #00003`)."
            }

        rec = self._resolve_ticket_record(target_num)
        if not rec:
            return {
                'found': False,
                'summary': f"Ticket **{target_num}** was not found or you do not have permission to view its records."
            }

        t = self._format_ticket_dict(rec)

        messages_summary = []
        try:
            domain_msg = ['|', ('ticket_id', '=', rec.id), ('helpdesk_ticket_id', '=', rec.id)]
            if self.role == 'customer':
                domain_msg.append(('is_internal_note', '=', False))
            w_msgs = self.env['website.helpdesk.message'].sudo().search(domain_msg, order='create_date asc', limit=15)
            for m in w_msgs:
                if m.is_internal_note:
                    if self.role in ['employee', 'project_manager']:
                        messages_summary.append(f"*Internal Note ({m.sender_name}):* {m.body[:280]}")
                else:
                    sender_tag = f"Customer ({m.sender_name})" if m.author_type == 'customer' else f"Agent ({m.sender_name})"
                    messages_summary.append(f"*{sender_tag}:* {m.body[:280]}")
        except Exception as e:
            _logger.debug("Error reading website.helpdesk.message: %s", e)

        if not messages_summary:
            try:
                m_domain = [('res_id', '=', rec.id), ('model', 'in', ['helpdesk.ticket', 'website.helpdesk.ticket'])]
                mail_msgs = self.env['mail.message'].sudo().search(m_domain, order='date asc', limit=10)
                for mm in mail_msgs:
                    body_clean = re.sub(r'<[^>]+>', ' ', mm.body or '').strip()
                    if body_clean and len(body_clean) > 4:
                        author = mm.author_id.name if mm.author_id else 'System'
                        messages_summary.append(f"• *{author}:* {body_clean[:220]}")
            except Exception as e:
                _logger.debug("Error reading mail.message: %s", e)

        summary = f"### Summary of Ticket **{t['number']}** — *{t['name']}*\n\n"
        summary += f"• **Customer / Requester:** **{t['customer']}**\n"
        summary += f"• **Current Stage:** `{t['stage_display']}` | **Priority:** **{t['priority']}**\n"
        summary += f"• **Assigned Staff:** **{t['assigned']}** | **Project:** {t['project']}\n"
        summary += f"• **SLA Status:** **{t['sla_status']}** (Elapsed: {t['elapsed_str']})\n\n"

        summary += f"#### Customer Issue\n"
        desc_text = (t['description'] or 'No description provided by requester.').strip()
        summary += f"> {desc_text}\n\n"

        if messages_summary:
            summary += f"#### Key Events & Conversation ({len(messages_summary)} records)\n"
            for item in messages_summary[-5:]:
                summary += f"{item}\n"
            summary += "\n"

        summary += f"#### Recommended Next Steps\n"
        if t['is_overdue']:
            summary += f"1. **Immediate Escalation:** This ticket has exceeded SLA thresholds ({t['elapsed_str']}). Prioritize customer follow-up.\n"
        if t['stage'] in ['new', 'not_started']:
            summary += f"1. Acknowledge customer ticket and transition to `In Progress`.\n"
            summary += f"2. Assign to the relevant support specialist if unassigned.\n"
        elif t['stage'] in ['progress', 'in_progress']:
            summary += f"1. Confirm if troubleshooting steps resolved the reported issue.\n"
            summary += f"2. Draft a customer update or request additional logs if required.\n"
        elif t['stage'] in ['on_hold', 'waiting']:
            summary += f"1. Follow up on pending dependency or waiting customer information.\n"
        else:
            summary += f"1. Verify customer satisfaction and close ticket if no further assistance is needed.\n"

        summary += f"\n*Screen view synchronized to Ticket {t['number']}.*"

        return {
            'found': True,
            'summary': summary,
            'ticket': t,
            'trigger_action': t.get('trigger_action')
        }

    def draft_customer_reply(self, ticket_id_or_number=None, instructions=None, tone='professional'):
        """
        Draft a customer-facing reply grounded in the ticket history and approved knowledge.
        Requires explicit human review before sending.
        """
        target_num = ticket_id_or_number or self.active_ticket_id
        if not target_num:
            res = self.search_tickets(limit=5)
            open_tkts = [t for t in res['tickets'] if t['stage'] not in self.CLOSED_STAGES]
            if open_tkts:
                list_str = "\n".join([f"• **{t['number']}**: *{t['name']}*" for t in open_tkts])
                return {
                    'found': False,
                    'reply_draft': f"Which ticket would you like to draft a reply for? Please specify (e.g. `Draft reply for ticket {open_tkts[0]['number']}`).\n\n{list_str}"
                }
            return {
                'found': False,
                'reply_draft': "Please specify which ticket to draft a reply for (e.g. `Draft a reply for ticket #00003`)."
            }

        rec = self._resolve_ticket_record(target_num)
        if not rec:
            return {
                'found': False,
                'reply_draft': f"Ticket **{target_num}** was not found or access is restricted."
            }

        t = self._format_ticket_dict(rec)
        cust_first = (t['customer'].split()[0] if t['customer'] and t['customer'] != '-' else 'Customer')
        issue_brief = (t['name'] or 'your issue').strip()

        kb_matches = self.search_helpdesk_documentation(query=issue_brief, limit=1)
        kb_content = ""
        if kb_matches.get('articles'):
            kb_content = f"\n\nBased on our standard resolution procedure:\n• " + kb_matches['articles'][0]['content'][:200].replace('\n', ' ') + "..."

        greeting = f"Dear {cust_first},"
        body = f"Thank you for contacting Helpdesk Support regarding **{t['name']}** (Ticket {t['number']}).\n\n"
        if instructions:
            body += f"Regarding your query: {instructions.strip()}\n\n"
        else:
            body += f"We have reviewed your request and our technical team is currently investigating the issue. "
            if t['stage'] in ['progress', 'in_progress']:
                body += f"We have made active progress on your case and are verifying the resolution steps.{kb_content}\n\n"
            else:
                body += f"Your ticket is prioritized under our standard SLA guidelines.{kb_content}\n\n"

        body += "Could you please confirm if you are still experiencing this behavior, or if you have any additional error messages or screenshots to share?\n\n"
        body += f"Best regards,\n{self.user_name}\nHelpdesk Support Team"

        full_draft = f"### Draft Customer Reply for Ticket **{t['number']}**\n\n"
        full_draft += "> **Agent Verification Required:** AI-generated drafts must be reviewed and approved by you before being sent to the customer.\n\n"
        full_draft += "```text\n"
        full_draft += f"{greeting}\n\n{body}\n"
        full_draft += "```\n\n"
        full_draft += "*You can copy this draft directly into the ticket reply composer or ask me to adjust the tone (e.g. `Make it more concise`, `Add troubleshooting steps`).*"

        return {
            'found': True,
            'ticket': t,
            'reply_draft': full_draft,
            'raw_text': f"{greeting}\n\n{body}",
            'trigger_action': t.get('trigger_action')
        }

    def help_resolve_customer_issue(self, ticket_id_or_number=None, issue_text=None):
        """
        Analyze customer issue, search knowledge articles and similar solved tickets,
        and provide concrete step-by-step diagnostic and resolution guidance.
        """
        rec = None
        target_num = ticket_id_or_number or self.active_ticket_id
        if target_num:
            rec = self._resolve_ticket_record(target_num)

        if rec:
            t = self._format_ticket_dict(rec)
            query_str = f"{t['name']} {t['category']} {t['description'][:100]}"
            header_str = f"### Resolution Assistance for Ticket **{t['number']}** — *{t['name']}*\n\n"
            trigger = t.get('trigger_action')
        else:
            query_str = issue_text or "helpdesk troubleshooting"
            header_str = f"### Helpdesk Issue Resolution Assistance\n\n"
            trigger = None

        kb_res = self.search_helpdesk_documentation(query=query_str, limit=2)
        articles = kb_res.get('articles', [])

        similar_tkts = self.find_similar_tickets(ticket_id_or_number=target_num, issue_text=query_str, limit=3)

        reply = header_str
        if rec:
            reply += f"• **Reported Issue:** {t['description'][:200] or t['name']}\n"
            reply += f"• **Category:** `{t['category'].capitalize()}` | **Priority:** **{t['priority']}**\n\n"

        reply += "#### Recommended Diagnostic & Resolution Steps\n"
        if articles:
            reply += f"According to verified documentation (**{articles[0]['title']}**):\n\n"
            clean_art = articles[0]['content'][:500].replace('\n\n', '\n')
            reply += f"> {clean_art}\n\n"
        else:
            reply += "1. **Identify Root Cause:** Check if the issue relates to user credentials, network configuration, or permission constraints.\n"
            reply += "2. **Verify Error Logs:** Review system logs or reproduce in staging environment.\n"
            reply += "3. **Apply Workaround / Patch:** Clear session cache or re-authenticate.\n"
            reply += "4. **Customer Confirmation:** Prompt customer to verify after applying fix.\n\n"

        if similar_tkts.get('tickets'):
            reply += "#### Similar Solved Tickets in History\n"
            for st in similar_tkts['tickets']:
                reply += f"• **{st['number']}**: *{st['name']}* (Resolved in `{st['stage']}` — *{st['solution_summary']}*)\n"
            reply += "\n"

        sources = [{'title': a['title'], 'url': a['url'], 'type': a['type']} for a in articles]
        return {
            'found': True,
            'reply': reply,
            'sources': sources,
            'trigger_action': trigger
        }

    def find_similar_tickets(self, ticket_id_or_number=None, issue_text=None, limit=4):
        """Search past resolved tickets with matching issue descriptions or categories."""
        Ticket = self.env['helpdesk.ticket'].sudo()
        domain = [('stage', 'in', self.CLOSED_STAGES)]

        keywords = ""
        rec = None
        target_num = ticket_id_or_number or self.active_ticket_id
        if target_num:
            rec = self._resolve_ticket_record(target_num)
            if rec:
                keywords = rec.name or ''
                if rec.category:
                    domain.append(('category', '=', rec.category))

        if not keywords and issue_text:
            keywords = issue_text

        clean_words = [w for w in re.findall(r'\b[A-Za-z]{4,}\b', keywords) if w.lower() not in ['ticket', 'issue', 'problem', 'help', 'please', 'customer', 'solve']]

        sub_domains = []
        for w in clean_words[:3]:
            sub_domains.append(('name', 'ilike', w))

        final_domain = domain
        if sub_domains:
            final_domain = domain + [OR(sub_domains) if len(sub_domains) > 1 else sub_domains[0]]

        records = Ticket.search(final_domain, limit=limit)
        if not records and domain:
            records = Ticket.search(domain, limit=limit)

        results = []
        for r in records:
            if rec and r.id == rec.id:
                continue
            code = r.ticket_number or r.ticket_ref or f"#{r.id:05d}"
            sol_summary = "Issue resolved by support agent."
            if r.description:
                sol_summary = (r.description[:80] + '...') if len(r.description) > 80 else r.description
            results.append({
                'id': r.id,
                'number': code,
                'name': r.name,
                'category': getattr(r, 'category', 'general'),
                'stage': getattr(r, 'stage', 'resolved'),
                'solution_summary': sol_summary
            })

        return {'count': len(results), 'tickets': results}

    def analyze_unresolved_tickets(self, team_name_or_id=None):
        """
        Analyze all unresolved/open helpdesk tickets:
        - Breakdown by stage and priority
        - Overdue & rotting ticket alerts
        - Unassigned tickets needing triage
        - Actionable triage recommendations
        """
        Ticket = self.env['helpdesk.ticket'].sudo()
        domain = self._get_ticket_base_domain()
        domain = domain + [('stage', 'not in', self.CLOSED_STAGES)]

        open_tkts = Ticket.search(domain, order='priority desc, create_date asc')
        total_open = len(open_tkts)
        now = fields.Datetime.now()

        stages = {}
        overdue_list = []
        unassigned_list = []
        urgent_list = []

        for t in open_tkts:
            stg = (t.stage or 'new').lower()
            stages[stg] = stages.get(stg, 0) + 1

            code = t.ticket_number or t.ticket_ref or f"#{t.id:05d}"
            c_date = t.create_date or now
            if isinstance(c_date, str):
                try:
                    c_date = fields.Datetime.from_string(c_date)
                except Exception:
                    c_date = now
            try:
                elapsed_hrs = (now - c_date).total_seconds() / 3600.0
            except Exception:
                elapsed_hrs = 0.0

            if t.sla_failed or stg == 'rotting' or elapsed_hrs > 48.0:
                overdue_list.append({
                    'number': code,
                    'name': t.name,
                    'elapsed': f"{int(elapsed_hrs)}h ago",
                    'assigned': t.assigned_employee_id.name if t.assigned_employee_id else (t.user_id.name if t.user_id else 'Unassigned')
                })

            if not t.assigned_employee_id and not t.user_id:
                unassigned_list.append({
                    'number': code,
                    'name': t.name,
                    'prio': 'Urgent' if str(t.priority) == '3' else ('High' if str(t.priority) == '2' else 'Normal')
                })

            if str(t.priority) in ['2', '3']:
                urgent_list.append({
                    'number': code,
                    'name': t.name,
                    'prio': 'Urgent' if str(t.priority) == '3' else 'High'
                })

        reply = f"### Analysis of Unresolved Helpdesk Tickets\n\n"
        reply += f"Currently there are **{total_open} open tickets** in your queue.\n\n"

        reply += "**Current Stage Distribution:**\n"
        reply += "| Stage | Count | Status |\n| :--- | :--- | :--- |\n"
        stage_labels = {'new': 'New / Triage', 'progress': 'In Progress', 'on_hold': 'On Hold', 'rotting': 'Overdue / Rotting'}
        for s_code, cnt in stages.items():
            s_name = stage_labels.get(s_code, s_code.title())
            status_dot = "Attention" if s_code in ['rotting'] else ("Active" if s_code in ['progress'] else "Queue")
            reply += f"| {s_name} | **{cnt}** | {status_dot} |\n"

        if overdue_list:
            reply += f"\n**Critical Attention Required ({len(overdue_list)} Overdue Tickets):**\n"
            for ot in overdue_list[:5]:
                reply += f"• **{ot['number']}**: *{ot['name']}* ({ot['elapsed']} — Owner: {ot['assigned']})\n"

        if unassigned_list:
            reply += f"\n**Unassigned Tickets Needing Distribution ({len(unassigned_list)}):**\n"
            for ut in unassigned_list[:4]:
                reply += f"• **{ut['number']}**: *{ut['name']}* (Priority: **{ut['prio']}**)\n"

        reply += f"\n#### Actionable Triage Recommendations\n"
        if overdue_list:
            reply += f"1. **Clear SLA Bottlenecks:** Prioritize ticket **{overdue_list[0]['number']}** to prevent customer escalation.\n"
        if unassigned_list:
            reply += f"2. **Assign Triage Queue:** Assign **{unassigned_list[0]['number']}** to available team members.\n"
        reply += f"3. **Customer Follow-Ups:** Check tickets on hold to ensure customers have submitted required information.\n"

        return {
            'total_open': total_open,
            'overdue_count': len(overdue_list),
            'unassigned_count': len(unassigned_list),
            'analysis_text': reply
        }

    # =========================================================================
    # TOOL CALLING DISPATCHER
    # =========================================================================
    def execute_tool(self, tool_name, args):
        """Securely dispatch tool call with arguments validation."""
        tool_name = str(tool_name).strip()
        args = args or {}
        _logger.info("Executing Helpdesk AI Tool: %s with args: %s", tool_name, args)

        try:
            if tool_name == 'search_tickets':
                return self.search_tickets(
                    query=args.get('query'),
                    stage=args.get('stage'),
                    priority=args.get('priority'),
                    category=args.get('category'),
                    project_name=args.get('project_name'),
                    customer_name=args.get('customer_name'),
                    overdue_only=args.get('overdue_only', False),
                    due_today_only=args.get('due_today_only', False),
                    assigned_to_me=args.get('assigned_to_me', False),
                    team_name=args.get('team_name'),
                    limit=args.get('limit', 10)
                )
            elif tool_name == 'get_ticket_details':
                return self.get_ticket_details(args.get('ticket_id_or_number'))
            elif tool_name == 'summarize_ticket':
                return self.summarize_ticket(args.get('ticket_id_or_number'))
            elif tool_name == 'draft_customer_reply':
                return self.draft_customer_reply(
                    ticket_id_or_number=args.get('ticket_id_or_number'),
                    instructions=args.get('instructions')
                )
            elif tool_name == 'help_resolve_customer_issue':
                return self.help_resolve_customer_issue(
                    ticket_id_or_number=args.get('ticket_id_or_number'),
                    issue_text=args.get('issue_text')
                )
            elif tool_name == 'analyze_unresolved_tickets':
                return self.analyze_unresolved_tickets(args.get('team_name_or_id'))
            elif tool_name == 'find_similar_tickets':
                return self.find_similar_tickets(
                    ticket_id_or_number=args.get('ticket_id_or_number'),
                    issue_text=args.get('issue_text')
                )
            elif tool_name == 'get_my_projects':
                return self.get_my_projects(args.get('summary_only', False))
            elif tool_name == 'get_project_summary':
                return self.get_project_summary(args.get('project_name_or_id'))
            elif tool_name == 'get_team_ticket_summary':
                return self.get_team_ticket_summary(args.get('team_name_or_id'))
            elif tool_name == 'search_customers':
                return self.search_customers(args.get('query'), args.get('limit', 5))
            elif tool_name == 'search_helpdesk_documentation':
                return self.search_helpdesk_documentation(args.get('query'), args.get('category'), limit=3)
            elif tool_name == 'draft_ticket_creation':
                return self.draft_ticket_creation(
                    name=args.get('name'),
                    description=args.get('description'),
                    category=args.get('category', 'technical'),
                    priority=args.get('priority', '0'),
                    project_name=args.get('project_name')
                )
            elif tool_name == 'create_ticket':
                return self.create_ticket(
                    name=args.get('name'),
                    description=args.get('description'),
                    category=args.get('category', 'technical'),
                    priority=args.get('priority', '0'),
                    project_id=args.get('project_id'),
                    partner_id=args.get('partner_id')
                )
            elif tool_name == 'update_helpdesk_ticket':
                return self.update_helpdesk_ticket(
                    ticket_id_or_number=args.get('ticket_id_or_number'),
                    stage=args.get('stage'),
                    priority=args.get('priority'),
                    internal_note=args.get('internal_note')
                )
            elif tool_name == 'assign_helpdesk_ticket':
                return self.assign_helpdesk_ticket(
                    ticket_id_or_number=args.get('ticket_id_or_number'),
                    employee_name=args.get('employee_name')
                )
            elif tool_name == 'get_ticket_reports':
                return self.get_ticket_reports(
                    report_type=args.get('report_type', 'stage_breakdown'),
                    date_range=args.get('date_range', 'all')
                )
            else:
                return {'error': f"Unknown tool: '{tool_name}'"}
        except Exception as e:
            _logger.exception("Error executing AI tool %s: %s", tool_name, e)
            return {'error': f"Failed to execute operation: {str(e)}"}

    # =========================================================================
    # MULTI-TURN CONTEXT & CONVERSATIONAL PRONOUN RESOLVER (PHASE 5)
    # =========================================================================
    def _resolve_contextual_references(self, message, history):
        """
        Analyze conversation history to resolve pronouns like 'these', 'ones',
        'the first one', or follow-ups to a previously discussed ticket or project.
        """
        msg = message.lower()
        context = {
            'resolved_ticket_id': None,
            'referenced_tickets': [],
            'referenced_project': None,
            'is_followup': False
        }

        if not history or not isinstance(history, list):
            return context

        # Search backward for previously mentioned ticket IDs or numbers
        ticket_mentions = []
        project_mentions = []

        for turn in reversed(history[-6:]):
            text = (turn.get('content') or turn.get('text') or '')
            found_nums = re.findall(r'#?0*(\d{1,6})', text)
            for fn in found_nums:
                if fn not in ticket_mentions:
                    ticket_mentions.append(fn)

            proj_matches = re.findall(r'(?:project|in)\s+([A-Za-z0-9_\-\s]+?)(?:\.|\,|\n|$)', text, re.IGNORECASE)
            for pm in proj_matches:
                p_clean = pm.strip()
                if len(p_clean) > 2 and p_clean.lower() not in ['detail', 'tickets', 'overdue', 'summary']:
                    if p_clean not in project_mentions:
                        project_mentions.append(p_clean)

        context['referenced_tickets'] = ticket_mentions
        if ticket_mentions:
            context['resolved_ticket_id'] = ticket_mentions[0]
        elif self.active_ticket_id:
            context['resolved_ticket_id'] = str(self.active_ticket_id)
            context['referenced_tickets'].append(str(self.active_ticket_id))

        if project_mentions:
            context['referenced_project'] = project_mentions[0]

        # Pronoun check
        if any(w in msg for w in ['these', 'those', 'ones', 'them', 'first one', 'second one', 'last one', 'this ticket', 'why is it']) or self.active_ticket_id:
            context['is_followup'] = True

        return context

    # =========================================================================
    # GEMINI REST API CLIENT WITH TOOL CALLING LOOP (PHASE 7)
    # =========================================================================
    def call_gemini_with_tools(self, user_prompt, conversation_history=None):
        """
        Multi-turn Gemini tool calling engine executing function calling loop.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = (ICP.get_param('website_helpdesk_portal.gemini_api_key') or os.environ.get('GEMINI_API_KEY') or '').strip()
        configured_model = ICP.get_param('website_helpdesk_portal.gemini_model') or 'gemini-1.5-flash'

        # If key is empty, skip external API safely
        if not api_key:
            return False, "", None, None, None, []

        models_to_try = [configured_model]
        for m in ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']:
            if m not in models_to_try:
                models_to_try.append(m)

        # Build initial contents
        contents = []
        if conversation_history and isinstance(conversation_history, list):
            for turn in conversation_history[-6:]:
                role = turn.get('role', 'user')
                if role not in ['user', 'model']:
                    role = 'user' if role in ['employee', 'customer', 'human', 'pm'] else 'model'
                t_content = (turn.get('content') or turn.get('text') or '').strip()
                if t_content:
                    contents.append({
                        'role': role,
                        'parts': [{'text': t_content[:2000]}]
                    })

        system_instruction = f"""You are {self.bot_name}, the intelligent, accurate Helpdesk AI Agent inside Odoo Helpdesk Portal.
Current User: {self.user_name}
User Role: {self.role.replace('_', ' ').title()}

CRITICAL OPERATIONAL RULES:
1. Always use the provided tools to fetch live Odoo data instead of inventing or assuming facts.
2. For read queries (overdue tickets, status, project info, team breakdown, documentation), call the appropriate tool.
3. For creating tickets: Call 'draft_ticket_creation' so the user can verify details before creation.
4. Format responses in clean, structured GitHub Markdown with bold headers, bullet lists, or tables where appropriate.
5. If an operation succeeds or opens a ticket, state the ticket number clearly."""

        full_prompt = f"System Instruction:\n{system_instruction}\n\nUser Question:\n{user_prompt}"
        contents.append({
            'role': 'user',
            'parts': [{'text': full_prompt}]
        })

        executed_actions = None
        executed_preview = None
        collected_sources = []

        for model_name in models_to_try[:2]:
            current_contents = list(contents)
            tool_iterations = 0

            while tool_iterations < 4:
                payload = {
                    'contents': current_contents,
                    'tools': [{'functionDeclarations': GEMINI_TOOLS_DECLARATIONS}],
                    'generationConfig': {
                        'temperature': 0.2,
                        'maxOutputTokens': 1500
                    }
                }
                encoded_data = json.dumps(payload).encode('utf-8')
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

                req = urllib.request.Request(
                    url,
                    data=encoded_data,
                    headers={
                        'Content-Type': 'application/json',
                        'x-goog-api-key': api_key
                    },
                    method='POST'
                )

                try:
                    with urllib.request.urlopen(req, timeout=12.0) as resp:
                        if resp.status != 200:
                            break
                        res_json = json.loads(resp.read().decode('utf-8'))
                        candidates = res_json.get('candidates', [])
                        if not candidates or 'content' not in candidates[0]:
                            break

                        candidate_content = candidates[0]['content']
                        parts = candidate_content.get('parts', [])

                        # Check for functionCall
                        function_calls = [p.get('functionCall') for p in parts if 'functionCall' in p]

                        if function_calls:
                            fc = function_calls[0]
                            fname = fc.get('name')
                            fargs = fc.get('args') or {}
                            _logger.info("Gemini requested tool call: %s(%s)", fname, fargs)

                            # Execute tool in Odoo
                            tool_result = self.execute_tool(fname, fargs)

                            # Capture trigger_action, preview, or sources
                            if isinstance(tool_result, dict):
                                if tool_result.get('trigger_action'):
                                    executed_actions = tool_result['trigger_action']
                                if tool_result.get('preview'):
                                    executed_preview = tool_result['preview']
                                if tool_result.get('articles'):
                                    for a in tool_result['articles']:
                                        collected_sources.append({'title': a.get('title'), 'url': a.get('url'), 'type': a.get('type')})

                            # Append model's functionCall turn
                            current_contents.append({
                                'role': 'model',
                                'parts': [{'functionCall': {'name': fname, 'args': fargs}}]
                            })
                            # Append functionResponse turn
                            current_contents.append({
                                'role': 'function',
                                'parts': [{
                                    'functionResponse': {
                                        'name': fname,
                                        'response': {'result': tool_result}
                                    }
                                }]
                            })
                            tool_iterations += 1
                            continue

                        # Text response completed
                        text_parts = [p.get('text', '') for p in parts if 'text' in p]
                        final_text = "".join(text_parts).strip()
                        if final_text:
                            return True, final_text, model_name, executed_actions, executed_preview, collected_sources

                except Exception as e:
                    _logger.warning("Gemini API call error on %s: %s", model_name, e)
                    break

        return False, "", None, None, None, []

    # =========================================================================
    # EMBEDDED INTELLIGENT INTENT ROUTER (ZERO-FAILURE FALLBACK)
    # =========================================================================
    def execute_semantic_intent(self, raw_message, action_key='', history=None):
        """
        High-precision intent router executing live Odoo tools and generating
        rich markdown responses when Gemini is unavailable, offline, or unconfigured.
        """
        msg = (raw_message or '').lower().strip()
        key = (action_key or '').lower().strip()
        context = self._resolve_contextual_references(raw_message, history)

        # -------------------------------------------------------------
        # 1. ZENDESK-INSPIRED COPILOT SUGGESTED ACTIONS & INTENT ROUTERS
        # -------------------------------------------------------------
        # (A) Find a Ticket
        if key == 'find_ticket' or any(msg == p for p in ['find a ticket', 'find tickets', 'search tickets', 'search for a ticket']):
            res = self.search_tickets(limit=6)
            open_tkts = [t for t in res['tickets'] if t['stage'] not in self.CLOSED_STAGES]
            reply = "### Helpdesk Ticket Search\n\n"
            if open_tkts:
                reply += "Here are the most recent active tickets in your queue:\n\n"
                reply += "| Ticket # | Subject | Customer | Priority | Stage |\n| :--- | :--- | :--- | :--- | :--- |\n"
                for t in open_tkts[:5]:
                    reply += f"| **{t['number']}** | *{t['name']}* | {t['customer']} | **{t['priority']}** | `{t['stage_display']}` |\n"
                reply += "\n*You can type any ticket number (e.g. `Show ticket #00003`) or search keywords (e.g. `Find tickets about billing`).*"
            else:
                reply += "You have no open tickets currently. You can search by keywords or ticket numbers anytime!"
            return reply, {'type': 'switch_tab', 'tab': 'tickets'}, None, []

        # (B) Summarize a Ticket
        if key == 'summarize_ticket' or any(msg == p for p in ['summarize a ticket', 'summarize ticket', 'ticket summary']) or ('summarize' in msg and 'ticket' in msg):
            t_match = re.search(r'#?0*(\d{1,6})', raw_message)
            t_target = (t_match.group(1) if t_match else None) or context.get('resolved_ticket_id') or self.active_ticket_id
            sum_res = self.summarize_ticket(t_target)
            return sum_res['summary'], sum_res.get('trigger_action'), None, []

        # (C) Help Me Resolve a Customer Issue
        if key == 'resolve_issue' or any(msg == p for p in ['help me resolve a customer issue', 'help resolve customer issue', 'resolve customer issue', 'resolve issue']) or ('resolve' in msg and 'issue' in msg):
            t_match = re.search(r'#?0*(\d{1,6})', raw_message)
            t_target = (t_match.group(1) if t_match else None) or context.get('resolved_ticket_id') or self.active_ticket_id
            clean_issue = re.sub(r'^(?:help me\s+)?(?:resolve\s+)?(?:a\s+)?(?:customer\s+)?(?:issue|problem)\s*(?:about|on|for)?\s*', '', raw_message, flags=re.IGNORECASE).strip()
            res_data = self.help_resolve_customer_issue(t_target, issue_text=clean_issue or None)
            return res_data['reply'], res_data.get('trigger_action'), None, res_data.get('sources', [])

        # (D) Search Knowledge Base
        if key == 'search_kb' or any(msg == p for p in ['search the knowledge base', 'search knowledge base', 'search kb', 'knowledge base']):
            query_term = re.sub(r'^(?:search|find|show)\s+(?:the\s+)?(?:knowledge\s+base|kb|documentation|docs|guide)\s*(?:about|for|on)?\s*', '', msg).strip()
            if not query_term or query_term in ['search the knowledge base', 'search knowledge base', 'search kb']:
                query_term = 'troubleshooting'
            docs = self.search_helpdesk_documentation(query_term, limit=3)
            articles = docs['articles']
            sources = [{'title': a['title'], 'url': a['url'], 'type': a['type']} for a in articles]
            if not articles:
                reply = f"I could not locate specific articles matching '{query_term}'. You can search for topics such as *VPN setup*, *login errors*, *SLA policy*, or *printer configuration*."
            else:
                reply = f"### Knowledge Base Articles\n\n"
                for a in articles:
                    reply += f"#### {a['title']}\n{a['content'][:400]}...\n\n"
                reply += "*You can ask follow-up questions to get step-by-step guidance on any topic.*"
            return reply, None, None, sources

        # (E) Draft a Customer Reply
        if key == 'draft_reply' or any(msg == p for p in ['draft a customer reply', 'draft customer reply', 'draft reply', 'draft response']) or ('draft' in msg and 'reply' in msg):
            t_match = re.search(r'#?0*(\d{1,6})', raw_message)
            t_target = (t_match.group(1) if t_match else None) or context.get('resolved_ticket_id') or self.active_ticket_id
            instructions = re.sub(r'^(?:please\s+)?(?:can you\s+)?(?:draft\s+)?(?:a\s+)?(?:customer\s+)?(?:reply|response)\s*(?:for|to|about)?\s*(?:ticket\s+#?0*\d+)?\s*', '', raw_message, flags=re.IGNORECASE).strip()
            draft_res = self.draft_customer_reply(t_target, instructions=instructions or None)
            return draft_res['reply_draft'], draft_res.get('trigger_action'), None, []

        # (F) Analyze Unresolved Tickets
        if key == 'analyze_unresolved' or any(msg == p for p in ['analyze unresolved tickets', 'analyze unresolved', 'unresolved tickets', 'open tickets analysis']) or ('analyze' in msg and 'unresolved' in msg):
            ana_res = self.analyze_unresolved_tickets()
            return ana_res['analysis_text'], None, None, []

        # -------------------------------------------------------------
        # Quick Chip Direct Handlers
        # -------------------------------------------------------------
        if key == 'overdue_tickets' or any(w in msg for w in ['overdue', 'rotting', 'overdue tickets', 'overdue and rotting']):
            res = self.search_tickets(overdue_only=True, limit=12)
            tickets = res['tickets']
            if not tickets:
                reply = "**Great news!** There are currently **no overdue or rotting tickets** in your accessible workspace. All SLAs are currently on track!"
            else:
                reply = f"### Overdue & Rotting Tickets ({len(tickets)})\n\n"
                reply += "The following tickets have exceeded the SLA threshold or are currently in rotting status:\n\n"
                reply += "| Ticket # | Subject | Project | Priority | Status | Elapsed |\n"
                reply += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
                for t in tickets[:8]:
                    reply += f"| **{t['number']}** | *{t['name']}* | {t['project']} | **{t['priority']}** | `{t['stage_display']}` | {t['elapsed_str']} |\n"
                if len(tickets) > 8:
                    reply += f"\n*...and {len(tickets) - 8} additional overdue tickets in your console.*"
                reply += "\n\n*Tip: You can ask me to open any of these tickets (e.g. `Show ticket #00003`) to update its stage or triage it.*"

            return reply, {'type': 'switch_tab', 'tab': 'pending_tickets'}, None, []

        if key == 'project_summary' or any(w in msg for w in ['project summary', 'my projects summary', 'summarize my projects', 'my projects']):
            res = self.get_my_projects()
            projects = res['projects']
            if not projects:
                reply = "You do not currently have any active assigned projects in your profile."
            else:
                reply = f"### Projects Overview ({len(projects)} Accessible Projects)\n\n"
                reply += "| Project | Manager | Team | Open Tickets | Overdue |\n"
                reply += "| :--- | :--- | :--- | :--- | :--- |\n"
                for p in projects:
                    reply += f"| **{p['name']}** | {p['manager']} | {p['team']} | {p['open_tickets']} | **{p['overdue_tickets']}** |\n"
                reply += "\n*You can ask me for a deep dive on any project (e.g. `Show summary for Project X`).*"
            return reply, None, None, []

        if key == 'summarize_tickets' or any(w in msg for w in ['team ticket breakdown', 'team breakdown', 'ticket breakdown', 'summarize tickets']):
            res = self.get_team_ticket_summary()
            reply = f"### Helpdesk Ticket Breakdown\n\n"
            reply += f"• **Total Active / Open Tickets:** {res['total_open']}\n"
            reply += f"• **Overdue Attention Required:** **{res['overdue_count']}**\n\n"

            reply += "**Breakdown by Priority:**\n"
            reply += "| Priority | Count |\n| :--- | :--- |\n"
            for p, cnt in res['priority_breakdown'].items():
                reply += f"| **{p}** | {cnt} |\n"

            reply += "\n**Workload Distribution by Staff:**\n"
            reply += "| Assigned Staff | Open Tickets |\n| :--- | :--- |\n"
            for staff, cnt in list(res['workload_by_staff'].items())[:6]:
                reply += f"| {staff} | **{cnt}** |\n"

            return reply, None, None, []

        if key == 'search_kb' or any(w in msg for w in ['search project documentation', 'search documentation', 'search kb', 'knowledge base']):
            # If user just clicked the chip, give guidelines and prompt
            query_term = re.sub(r'^(?:search|find|show)\s+(?:project\s+)?(?:documentation|kb|knowledge|guide|about)\s*', '', msg).strip()
            if not query_term or query_term in ['search project documentation', 'search documentation']:
                query_term = 'troubleshooting'

            docs = self.search_helpdesk_documentation(query_term, limit=3)
            articles = docs['articles']
            sources = [{'title': a['title'], 'url': a['url'], 'type': a['type']} for a in articles]

            if not articles:
                reply = f"I could not locate specific documentation matching '{query_term}'. Please try searching for keywords like *installation*, *SLA*, *stage transition*, or *printer*."
            else:
                reply = f"### Documentation & Troubleshooting Knowledge\n\n"
                for a in articles:
                    reply += f"#### {a['title']}\n{a['content'][:450]}...\n\n"
                reply += "*You can ask me specific technical questions to guide you step-by-step.*"
            return reply, None, None, sources

        if key == 'my_tickets' or any(w in msg for w in ['my tickets', 'my open tickets', 'show my tickets', 'my pending tickets']):
            res = self.search_tickets(assigned_to_me=(self.role != 'customer'), limit=10)
            tickets = res['tickets']
            open_tkts = [t for t in tickets if t['stage'] not in self.CLOSED_STAGES]
            if not open_tkts:
                reply = "You currently have no open tickets assigned to you in the portal. Everything is up to date! "
            else:
                reply = f"### Your Open Tickets ({len(open_tkts)})\n\n"
                reply += "| Ticket # | Subject | Project | Priority | Stage |\n| :--- | :--- | :--- | :--- | :--- |\n"
                for t in open_tkts[:8]:
                    reply += f"| **{t['number']}** | *{t['name']}* | {t['project']} | {t['priority']} | `{t['stage_display']}` |\n"
                reply += f"\n*Click or type `#<number>` to view full details.*"
            return reply, {'type': 'switch_tab', 'tab': 'tickets'}, None, []

        # -------------------------------------------------------------
        # 2. SPECIFIC TICKET LOOKUP & SCREEN SYNCHRONIZATION
        # -------------------------------------------------------------
        ticket_match = re.search(r'#?0*(\d{1,6})', raw_message)
        is_lookup = ticket_match and (
            any(w in msg for w in ['open', 'show', 'view', 'display', 'go to', '#', 'detail', 'details', 'info', 'status', 'ticket'])
            and not any(w in msg for w in ['create', 'new ticket', 'assign', 'update', 'priority'])
        )

        if is_lookup:
            t_num = ticket_match.group(1)
            t_res = self.get_ticket_details(t_num)
            if t_res['found']:
                t = t_res['ticket']
                reply = f"### Ticket Details: **{t['number']}** — *{t['name']}*\n\n"
                reply += f"• **Stage / Status:** `{t['stage_display']}`\n"
                reply += f"• **Priority:** **{t['priority']}**\n"
                reply += f"• **Category:** `{t['category'].capitalize()}`\n"
                reply += f"• **Associated Project:** **{t['project']}**\n"
                reply += f"• **Customer / Requester:** **{t['customer']}**\n"
                reply += f"• **Assigned Staff:** {t['assigned']}\n"
                reply += f"• **SLA Status:** **{t['sla_status']}** (Elapsed: {t['elapsed_str']})\n\n"
                reply += f"**Description:**\n> {t['description'] or 'No description provided.'}\n\n"
                reply += f"✅ *I have synchronized your screen view to Ticket **{t['number']}**.*"
                return reply, t['trigger_action'], None, []

        # -------------------------------------------------------------
        # 3. EXPLAIN WHY A TICKET IS OVERDUE
        # -------------------------------------------------------------
        if any(w in msg for w in ['why is this ticket overdue', 'why is it overdue', 'explain why', 'why is it rotting']):
            target_num = context.get('resolved_ticket_id') or (ticket_match.group(1) if ticket_match else None)
            if target_num:
                t_res = self.get_ticket_details(target_num)
                if t_res['found']:
                    t = t_res['ticket']
                    reply = f"### ⏱SLA Analysis for Ticket **{t['number']}** (*{t['name']}*)\n\n"
                    if t['is_overdue']:
                        reply += f"• **Status:** **Overdue / Rotting** \n"
                        reply += f"• **Elapsed Time:** **{t['elapsed_str']}** since creation on {t['created_on']}.\n"
                        reply += f"• **Current Stage:** `{t['stage_display']}` (Assignment: {t['assigned']}).\n\n"
                        reply += f"**Reason:** Under company SLA policy, tickets in priority **{t['priority']}** must achieve first action and resolution within 24–48 hours. Because this ticket has been open for **{t['elapsed_str']}** without resolution, it has automatically transitioned into rotting / overdue status."
                    else:
                        reply += f"• **Status:** **On Track** ✅\n"
                        reply += f"• **Elapsed Time:** {t['elapsed_str']}.\n"
                        reply += f"• This ticket has not breached the 48-hour SLA threshold."
                    return reply, t.get('trigger_action'), None, []

        # -------------------------------------------------------------
        # 4. PRONOUN FOLLOW-UP: "Which of these have high priority?", "Overdue ones"
        # -------------------------------------------------------------
        if context.get('is_followup'):
            if any(w in msg for w in ['high priority', 'urgent', 'critical']):
                res = self.search_tickets(priority='2', limit=8)
                tickets = res['tickets']
                if not tickets:
                    reply = "None of the referenced active tickets have High or Urgent priority."
                else:
                    reply = f"From our records, here are the **High/Urgent Priority tickets**:\n\n"
                    for t in tickets:
                        reply += f"• **{t['number']}**: *{t['name']}* (**{t['priority']}** — Stage: `{t['stage_display']}`)\n"
                return reply, None, None, []

            if any(w in msg for w in ['overdue', 'rotting']):
                res = self.search_tickets(overdue_only=True, limit=8)
                tickets = res['tickets']
                if not tickets:
                    reply = "None of the referenced tickets are overdue."
                else:
                    reply = f"Here are the **overdue tickets**:\n\n"
                    for t in tickets:
                        reply += f"• **{t['number']}**: *{t['name']}* (Elapsed: {t['elapsed_str']})\n"
                return reply, None, None, []

            if any(w in msg for w in ['assigned', 'who is working', 'employees']):
                res = self.search_tickets(limit=8)
                reply = "Here are the assigned staff members for these tickets:\n\n"
                for t in res['tickets']:
                    reply += f"• **{t['number']}**: Assigned to **{t['assigned']}** (Project: {t['project']})\n"
                return reply, None, None, []

        # -------------------------------------------------------------
        # 5. TICKETS DUE TODAY
        # -------------------------------------------------------------
        if any(w in msg for w in ['due today', 'tickets due today', 'deadline today']):
            res = self.search_tickets(due_today_only=True, limit=10)
            tickets = res['tickets']
            if not tickets:
                reply = "There are currently **no tickets due today**. All daily deadlines are met!"
            else:
                reply = f"### Tickets Due Today ({len(tickets)})\n\n"
                for t in tickets:
                    reply += f"• **{t['number']}**: *{t['name']}* (Priority: **{t['priority']}**, Stage: `{t['stage_display']}`)\n"
            return reply, None, None, []

        # -------------------------------------------------------------
        # 6. TICKET CREATION DRAFT & CONFIRMATION
        # -------------------------------------------------------------
        if any(w in msg for w in ['create a ticket', 'create project ticket', 'raise a ticket', 'log a ticket', 'file a ticket', 'new ticket']):
            # Extract subject
            title = ""
            desc = ""
            clean_title = re.sub(r'^(?:please\s+)?(?:can you\s+)?(?:create|raise|log|file|make)\s+(?:a\s+)?(?:project\s+)?ticket\s+(?:for|about|on|regarding)?\s*', '', raw_message, flags=re.IGNORECASE).strip()

            if clean_title:
                if 'description:' in clean_title.lower():
                    parts = re.split(r'description:', clean_title, flags=re.IGNORECASE)
                    title = parts[0].strip()
                    desc = parts[1].strip() if len(parts) > 1 else title
                else:
                    title = clean_title[:70]
                    desc = clean_title
            else:
                title = "New Helpdesk Support Request"
                desc = "Created via Maya AI Assistant"

            prio = '2' if any(w in msg for w in ['urgent', 'critical', 'high']) else '0'
            cat = 'technical' if any(w in msg for w in ['bug', 'crash', 'error', 'technical', 'login']) else 'billing'

            draft = self.draft_ticket_creation(title, desc, category=cat, priority=prio)
            reply = f"I've drafted a support ticket based on your description:\n\n• **Title:** *{title}*\n• **Category:** `{cat.title()}`\n• **Priority:** **{'High' if prio == '2' else 'Normal'}**\n\nPlease review the details in the card below and click **Confirm & Create Ticket** to submit:"
            return reply, None, draft['preview'], []

        # -------------------------------------------------------------
        # 7. UPDATE TICKET PRIORITY OR STAGE
        # -------------------------------------------------------------
        if any(w in msg for w in ['update priority', 'change priority', 'set priority', 'move to stage', 'mark ticket']):
            t_num = ticket_match.group(1) if ticket_match else context.get('resolved_ticket_id')
            if t_num:
                target_prio = None
                target_stage = None
                if 'urgent' in msg or 'critical' in msg:
                    target_prio = 'urgent'
                elif 'high' in msg:
                    target_prio = 'high'
                elif 'medium' in msg:
                    target_prio = 'medium'
                elif 'low' in msg:
                    target_prio = 'low'

                if any(w in msg for w in ['progress', 'in progress']):
                    target_stage = 'progress'
                elif any(w in msg for w in ['solved', 'resolve', 'resolved']):
                    target_stage = 'solved'
                elif any(w in msg for w in ['hold', 'on hold', 'pause']):
                    target_stage = 'on_hold'

                up_res = self.update_helpdesk_ticket(t_num, stage=target_stage, priority=target_prio)
                return up_res['message'], None, None, []

        # -------------------------------------------------------------
        # 8. ASSIGN TICKET TO EMPLOYEE
        # -------------------------------------------------------------
        if any(w in msg for w in ['assign ticket', 'assign this ticket', 'assign to']):
            t_num = ticket_match.group(1) if ticket_match else context.get('resolved_ticket_id')
            emp_match = re.search(r'assign\s+(?:ticket\s+#?0*\d+\s+)?to\s+([A-Za-z\s]+?)(?:\.|$)', raw_message, re.IGNORECASE)
            emp_target = emp_match.group(1).strip() if emp_match else None
            if t_num and emp_target:
                as_res = self.assign_helpdesk_ticket(t_num, emp_target)
                return as_res['message'], None, None, []

        # -------------------------------------------------------------
        # 9. DOCUMENTATION / TROUBLESHOOTING SEARCH
        # -------------------------------------------------------------
        if any(w in msg for w in ['troubleshoot', 'guide', 'install', 'documentation', 'manual', 'how to', 'error', 'crash']):
            docs = self.search_helpdesk_documentation(raw_message, limit=3)
            articles = docs['articles']
            sources = [{'title': a['title'], 'url': a['url'], 'type': a['type']} for a in articles]
            if articles:
                reply = f"Here is the verified documentation regarding your technical question:\n\n"
                for a in articles:
                    reply += f"### {a['title']}\n{a['content']}\n\n"
                return reply, None, None, sources

        # -------------------------------------------------------------
        # 10. GREETINGS & CAPABILITIES
        # -------------------------------------------------------------
        if any(w in msg for w in ['hello', 'hi', 'hey', 'greetings', 'good morning', 'good afternoon']):
            reply = f"Hello {self.user_name}! I am **{self.bot_name}**, your intelligent Helpdesk AI Assistant.\n\nHow can I help you today? You can ask me to:\n• **Check overdue tickets** (`Which tickets are overdue?`)\n• **Inspect any ticket** (`Show ticket #00003`)\n• **Summarize your projects** (`Summarize my current projects`)\n• **Generate team ticket breakdowns**\n• **Search technical guides & SOPs**\n• **Draft and create tickets**"
            return reply, None, None, []

        if any(w in msg for w in ['what can you do', 'who are you', 'help me', 'commands', 'capabilities']):
            reply = f"""### What I Can Do as Your Helpdesk AI Companion ({self.bot_name})

• **Live Ticket Management:** Search, view live SLA metrics, inspect overdue tickets, and track elapsed durations.
• **Instant Screen Synchronization:** Saying `Show ticket #00003` synchronizes your browser view directly to that ticket.
• **Project & Team Summaries:** Check project workload, open tickets, and employee assignments.
• **Verified Technical Documentation:** Retrieve step-by-step troubleshooting SOPs and manuals.
• **Consequential Actions:** Draft new tickets with confirmation preview cards, update priorities, and assign tickets."""
            return reply, None, None, []

        # -------------------------------------------------------------
        # 11. GENERAL SEARCH FALLBACK
        # -------------------------------------------------------------
        t_search = self.search_tickets(query=raw_message, limit=5)
        if t_search['count'] > 0:
            reply = f"I found **{t_search['count']} matching tickets** for your query:\n\n"
            for t in t_search['tickets']:
                reply += f"• **{t['number']}**: *{t['name']}* (Project: {t['project']}, Priority: **{t['priority']}**, Stage: `{t['stage_display']}`)\n"
            reply += "\n*You can ask me to open any of these tickets to view details.*"
            return reply, None, None, []

        # Default conversational assistance
        reply = f"I've received your query: \"{raw_message}\". As {self.bot_name}, I'm connected to your live Helpdesk database. You can ask me to open any ticket (`Show ticket #00003`), check overdue tickets, summarize projects, or search troubleshooting documentation."
        return reply, None, None, []

    # =========================================================================
    # MASTER QUERY PROCESSOR
    # =========================================================================
    def process_query(self, message='', action_key='', history=None, active_ticket_id=None):
        """
        Main pipeline handling conversation turns:
        1. Attempts Gemini Tool Calling if configured and reachable.
        2. Seamlessly falls back to Embedded Semantic Router if Gemini is unavailable.
        3. Returns clean structured response for the frontend.
        """
        if active_ticket_id:
            self.active_ticket_id = active_ticket_id
        raw_msg = (message or '').strip()
        key = (action_key or '').strip()

        # Try Gemini API with Tool Calling first
        success, ai_reply, model_used, trigger_act, preview, sources = self.call_gemini_with_tools(
            user_prompt=raw_msg or f"[Action Triggered: {key}]",
            conversation_history=history
        )

        if success and ai_reply:
            return {
                'success': True,
                'status': 'success',
                'reply_text': ai_reply,
                'trigger_action': trigger_act,
                'ticket_preview': preview,
                'sources': sources,
                'model': model_used or 'gemini-1.5-flash'
            }

        # Zero-failure Fallback to Semantic Intent Engine
        reply_text, trigger_act, preview, sources = self.execute_semantic_intent(
            raw_message=raw_msg,
            action_key=key,
            history=history
        )

        return {
            'success': True,
            'status': 'success',
            'reply_text': reply_text,
            'trigger_action': trigger_act,
            'ticket_preview': preview,
            'sources': sources,
            'model': 'maya-semantic-engine'
        }
