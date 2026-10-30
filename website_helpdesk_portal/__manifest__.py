# -*- coding: utf-8 -*-
{
    'name': 'AIXODESK — Helpdesk & Customer Management for Odoo 19',
    'version': '19.0.1.0.35',
    'category': 'Services/Helpdesk',
    'summary': 'One connected workspace for customers, support teams and administrators.',
    'description': """
AIXODESK — Helpdesk & Customer Management for Odoo 19
=====================================================
One connected workspace for customers, support teams and administrators.
Manage customer requests, ticket conversations, team assignments, projects and service performance through a unified support workflow.

Key Features & Portals:
-----------------------
* Three Dedicated Portals:
  - Customer Portal: Raise requests in under a minute, track live status, responsive chatter, search Knowledge Base, rate service.
  - Employee Portal: Agent workspace with queue triage, canned responses, internal notes, SLA timers, and stage transitions.
  - Admin Portal: Team management, intelligent routing (Manual / Round-robin / Least-loaded), SLA policy matrix, and executive reporting.

* 6-Stage Ticket Progression Lifecycle:
  1. Capture the request (portal form & email inbound creation)
  2. Find the right team & automated agent assignment
  3. Start the response & measure first-response SLA
  4. Wait for customer (automatic SLA pause & resume)
  5. Move ownership & transfer audit log
  6. Record outcome & customer service satisfaction rating

* Operations & SLA Intelligence:
  - Priority-based SLA policies with business calendars
  - Real-time in-app and email event notifications
  - Company-wide and agent-level analytics dashboard
  - Service reports, backlog tracking, and satisfaction metrics
    """,
    'author': 'AixoDesk Team / Aixomind',
    'website': 'https://aixodesk.com',
    'images': [
        'static/description/screenshots/customer-portal-tickets.png',
        'static/description/screenshots/employee-ticket-queue.png',
        'static/description/screenshots/admin-ticket-assignment.png',
        'static/description/screenshots/analytics-dashboard.png',
        'static/description/screenshots/ticket-conversation.png',
        'static/description/screenshots/projects-overview.png',
        'static/description/screenshots/customer-directory.png',
        'static/description/screenshots/admin-service-reports.png',
    ],
    'depends': ['base', 'web', 'website', 'portal', 'mail', 'hr', 'project', 'helpdesk'],
    'data': [
        'security/ir.model.access.csv',
        'data/helpdesk_stage_map_data.xml',
        'data/helpdesk_demo_data.xml',
        'data/helpdesk_ai_knowledge_data.xml',
        'views/helpdesk_stage_map_views.xml',
        'views/helpdesk_ticket_views.xml',
        'views/helpdesk_ticket_project_views.xml',
        'views/helpdesk_zoho_desk_templates.xml',
        'views/helpdesk_portal_templates.xml',
        'views/helpdesk_admin_templates.xml',
        'views/hr_employee_views.xml',
        'views/res_partner_views.xml',
        'views/project_team_views.xml',
        'views/project_project_views.xml',
        'views/helpdesk_custom_profile_views.xml',
        'views/res_config_settings_views.xml',
        'views/helpdesk_support_team_contact_views.xml',
        'views/helpdesk_ai_knowledge_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_helpdesk_portal/static/src/css/helpdesk_portal.css',
            'website_helpdesk_portal/static/src/js/helpdesk_ai_assistant.js',
        ],
        'web.assets_backend': [
            'website_helpdesk_portal/static/src/css/helpdesk_backend.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
