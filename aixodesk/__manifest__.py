# -*- coding: utf-8 -*-
{
    'name': 'AixoDesk',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Support, simplified. - Modern Reference-Matched Login & Portal Experience',
    'description': """
AixoDesk Helpdesk Portal
========================
- Premium, reference-matched login & signup experience
- Minimalist SaaS aesthetic with original branding
- Custom SVG decorative business artwork and ambient sunlight lighting
- Password visibility toggle & client-side validation
- Seamless integration with Odoo native authentication, signup, and password recovery
    """,
    'author': 'AixoDesk Team',
    'website': 'https://aixodesk.com',
    'license': 'LGPL-3',
    'images': [
        'static/description/screenshots/customer-portal-tickets.png',
        'static/description/screenshots/employee-ticket-queue.png',
        'static/description/screenshots/admin-ticket-assignment.png',
        'static/description/screenshots/analytics-dashboard.png',
    ],
    'depends': [
        'base',
        'web',
        'portal',
        'website',
        'auth_signup',
    ],
    'data': [
        'views/login_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'aixodesk/static/src/css/login.css',
            'aixodesk/static/src/js/login.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
