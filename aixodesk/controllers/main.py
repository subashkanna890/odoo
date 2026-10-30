# -*- coding: utf-8 -*-
import json
import logging
import werkzeug.urls
from odoo import http, _
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.web.controllers.home import ensure_db

_logger = logging.getLogger(__name__)


class AixoDeskLogin(AuthSignupHome):

    def _get_google_oauth_info(self):
        """
        Check if Google OAuth is configured and enabled in auth.oauth.provider.
        Returns (google_auth_link, is_configured).
        """
        try:
            if 'auth.oauth.provider' in request.env:
                providers = request.env['auth.oauth.provider'].sudo().search([('enabled', '=', True)])
                for provider in providers:
                    p_name = (provider.name or '').lower()
                    p_endpoint = (provider.auth_endpoint or '').lower()
                    if 'google' in p_name or 'google' in p_endpoint:
                        if provider.client_id and provider.auth_endpoint:
                            return_url = request.httprequest.url_root + 'auth_oauth/signin'
                            redirect = request.params.get('redirect') or 'web'
                            if not redirect.startswith(('//', 'http://', 'https://')):
                                redirect = '%s%s' % (request.httprequest.url_root, redirect[1:] if redirect[0] == '/' else redirect)
                            state = dict(
                                d=request.session.db,
                                p=provider.id,
                                r=werkzeug.urls.url_quote_plus(redirect),
                            )
                            params = dict(
                                response_type='token',
                                client_id=provider.client_id,
                                redirect_uri=return_url,
                                scope=provider.scope or 'openid profile email',
                                state=json.dumps(state),
                            )
                            auth_link = "%s?%s" % (provider.auth_endpoint, werkzeug.urls.url_encode(params))
                            return auth_link, True
        except Exception as e:
            _logger.warning("Error checking Google OAuth provider: %s", e)
        return '#', False

    @http.route()
    def web_login(self, *args, **kw):
        ensure_db()
        response = super().web_login(*args, **kw)
        if request.httprequest.method == 'POST' and request.session.uid:
            redirect_param = request.params.get('redirect')
            if not redirect_param or redirect_param in ['/web', '/web/', '/odoo', '/odoo/']:
                return request.redirect('/helpdesk/employee')
        if hasattr(response, 'is_qweb') and response.is_qweb:
            google_link, is_configured = self._get_google_oauth_info()
            response.qcontext['google_auth_link'] = google_link
            response.qcontext['google_oauth_configured'] = is_configured
            response.qcontext['aixodesk_portal'] = True
        return response

    @http.route(['/aixodesk', '/aixodesk/login', '/aixodesk/desk'], type='http', auth='public', website=True, sitemap=True)
    def aixodesk_login_entry(self, **kw):
        """Dedicated portal entrance route for AixoDesk Helpdesk."""
        if request.session.uid:
            return request.redirect('/helpdesk/employee')
        return request.redirect_query('/web/login', query=request.params)
