# -*- coding: utf-8 -*-
{
    'name': 'AixoDesk Login & Signup Portal',
    'version': '19.0.1.0.4',
    'summary': 'Indigo Aurora split-card login, sign-up, and mobile OTP verification for AixoDesk Helpdesk',
    'description': """AixoDesk Helpdesk Login & Signup Portal - Indigo Aurora Theme
- Split-card login layout (left: auth form, right: promo illustration & carousel)
- Modern Sign Up registration flow with First/Last name, email, country picker, mobile number
- Mobile 4-digit OTP verification with countdown timer, resend rate-limiting, and auto-authentication
- Seamless Bright ("Indigo Bright") and Dark ("Indigo Dark") modes
- Mode toggle button with 44px hit-target, rotating SVG icons, and localStorage persistence
- 3-slide auto-advancing feature carousel with responsive cross-fade on login
- High-contrast, accessible form styling with custom focus rings and button gradients
    """,
    'category': 'Helpdesk/Authentication',
    'author': 'Aixomind India Private Limited',
    'website': 'https://aixomind.com',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'auth_signup',
    ],
    'data': [
        'views/login_templates.xml',
        'views/signup_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'aixodesk_login/static/src/scss/login.scss',
            'aixodesk_login/static/src/js/login_theme.js',
            'aixodesk_login/static/src/scss/signup.scss',
            'aixodesk_login/static/src/js/signup.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
