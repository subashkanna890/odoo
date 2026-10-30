# -*- coding: utf-8 -*-

def post_init_hook(env):
    """Ensure older conflicting login layouts and templates
    are inactive so aixodesk_login's clean split-card layout renders without conflicts."""
    conflicting_views = [
        'website.login_layout',
        'aixodesk.aixodesk_login_layout',
        'aixodesk.aixodesk_login_form',
        'aixodesk.portal_layout',
    ]
    for view_xmlid in conflicting_views:
        view = env.ref(view_xmlid, raise_if_not_found=False)
        if view and view.active:
            view.active = False
