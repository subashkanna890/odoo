# -*- coding: utf-8 -*-
import json
import logging
import os
import re
import secrets
import time
from odoo import http, _
from odoo.http import request
from odoo.addons.web.controllers.home import ensure_db

_logger = logging.getLogger(__name__)

COUNTRY_LIST = [
    {'code': 'IN', 'name': 'India', 'dial': '+91', 'flag': '🇮🇳'},
    {'code': 'US', 'name': 'United States', 'dial': '+1', 'flag': '🇺🇸'},
    {'code': 'GB', 'name': 'United Kingdom', 'dial': '+44', 'flag': '🇬🇧'},
    {'code': 'AE', 'name': 'United Arab Emirates', 'dial': '+971', 'flag': '🇦🇪'},
    {'code': 'SG', 'name': 'Singapore', 'dial': '+65', 'flag': '🇸🇬'},
    {'code': 'AU', 'name': 'Australia', 'dial': '+61', 'flag': '🇦🇺'},
    {'code': 'CA', 'name': 'Canada', 'dial': '+1', 'flag': '🇨🇦'},
    {'code': 'DE', 'name': 'Germany', 'dial': '+49', 'flag': '🇩🇪'},
    {'code': 'FR', 'name': 'France', 'dial': '+33', 'flag': '🇫🇷'},
    {'code': 'SA', 'name': 'Saudi Arabia', 'dial': '+966', 'flag': '🇸🇦'},
    {'code': 'MY', 'name': 'Malaysia', 'dial': '+60', 'flag': '🇲🇾'},
]


def _extract_data(kw):
    data = {}
    try:
        raw = request.get_json_data()
        if isinstance(raw, dict):
            if 'params' in raw and isinstance(raw['params'], dict):
                data.update(raw['params'])
            else:
                data.update(raw)
    except Exception:
        pass
    if isinstance(kw, dict):
        data.update(kw)
    return data


class AixoDeskSignup(http.Controller):

    @http.route(['/assets/<path:filename>'], type='http', auth='public', website=True, sitemap=False)
    def aixodesk_assets_serve(self, filename, **kw):
        """Serve static assets directly from /assets/ path."""
        base_dir = os.path.dirname(os.path.dirname(__file__))
        file_path = os.path.join(base_dir, 'static', 'src', 'img', filename)
        if not os.path.isfile(file_path):
            alt_dir = os.path.join(os.path.dirname(base_dir), 'aixodesk', 'static', 'src', 'img', filename)
            if os.path.isfile(alt_dir):
                file_path = alt_dir
        if os.path.isfile(file_path):
            with open(file_path, 'rb') as f:
                content = f.read()
            mimetype = 'image/svg+xml' if filename.endswith('.svg') else 'application/octet-stream'
            return request.make_response(content, [
                ('Content-Type', mimetype),
                ('Cache-Control', 'public, max-age=3600'),
            ])
        return request.not_found()

    @http.route(['/signup', '/web/signup'], type='http', auth='public', website=True, sitemap=True)
    def aixodesk_signup(self, **kw):
        """Dedicated Sign Up & Mobile OTP page for AixoDesk Helpdesk."""
        ensure_db()
        if request.session.uid and not request.env.user._is_public():
            if request.env.user._is_internal():
                return request.redirect('/odoo')
            return request.redirect('/my')

        # Retrieve any existing signup session
        signup_data = request.session.get('aixo_signup_data') or {}
        has_pending_otp = bool(signup_data and request.session.get('aixo_signup_otp'))

        return request.render('aixodesk_login.signup_page', {
            'countries': COUNTRY_LIST,
            'default_country': COUNTRY_LIST[0],
            'signup_data': signup_data,
            'has_pending_otp': has_pending_otp,
            'resend_in': max(0, int(request.session.get('aixo_signup_resend_after', 0) - time.time())),
        })

    @http.route('/aixodesk/api/send_otp', type='json', auth='public', website=True, methods=['POST'], csrf=False)
    def send_otp(self, **kw):
        """Validate registration form fields and initiate 4-digit mobile OTP delivery."""
        ensure_db()
        data = _extract_data(kw)
        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        country_code = (data.get('country_code') or '+91').strip()
        mobile = (data.get('mobile') or '').strip()
        terms = bool(data.get('terms'))

        # Validation
        if not first_name:
            return {'success': False, 'error': 'First name is required.'}
        if not last_name:
            return {'success': False, 'error': 'Last name is required.'}
        if not email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            return {'success': False, 'error': 'Please enter a valid email address.'}
        clean_mobile = re.sub(r'\D', '', mobile)
        if not clean_mobile or len(clean_mobile) < 7:
            return {'success': False, 'error': 'Please enter a valid mobile number.'}
        if not terms:
            return {'success': False, 'error': 'You must agree to the Terms of Service and Privacy Policy.'}

        # Check existing user
        User = request.env['res.users'].sudo()
        if User.search_count([('login', '=', email)]) > 0:
            return {'success': False, 'error': 'An account with this email address already exists. Please sign in.'}

        # Generate 4-digit numeric OTP
        otp = f"{secrets.randbelow(9000) + 1000}"
        full_phone = f"{country_code} {clean_mobile}"

        # Persist in session
        now = time.time()
        request.session['aixo_signup_data'] = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'country_code': country_code,
            'mobile': clean_mobile,
            'full_phone': full_phone,
        }
        request.session['aixo_signup_otp'] = otp
        request.session['aixo_signup_otp_expires'] = now + 300  # 5 minutes
        request.session['aixo_signup_resend_after'] = now + 30  # 30 seconds

        _logger.info("=== [AIXODESK SIGNUP OTP] Initiated for %s: %s ===", full_phone, otp)

        # Dispatch via SMS gateway if configured
        sms_sent = False
        try:
            if 'sms.sms' in request.env:
                sms_body = f"Your AixoDesk verification code is: {otp}. Valid for 5 minutes."
                sms_rec = request.env['sms.sms'].sudo().create({
                    'number': f"{country_code}{clean_mobile}",
                    'body': sms_body,
                })
                sms_rec.send()
                sms_sent = True
        except Exception as e:
            _logger.warning("Could not dispatch via Odoo sms.sms: %s", e)

        return {
            'success': True,
            'message': f'Verification code sent to {full_phone}',
            'phone': full_phone,
            'resend_in': 30,
            'sms_sent': sms_sent,
        }

    @http.route('/aixodesk/api/resend_otp', type='json', auth='public', website=True, methods=['POST'], csrf=False)
    def resend_otp(self, **kw):
        """Resend a new 4-digit verification code with 30-second rate limiting."""
        ensure_db()
        signup_data = request.session.get('aixo_signup_data')
        if not signup_data:
            return {'success': False, 'error': 'Session expired. Please return to sign up and re-enter your details.'}

        now = time.time()
        resend_after = request.session.get('aixo_signup_resend_after', 0)
        if now < resend_after:
            wait_sec = max(1, int(resend_after - now))
            return {'success': False, 'error': f'Please wait {wait_sec}s before requesting a new code.'}

        # Generate new 4-digit OTP
        otp = f"{secrets.randbelow(9000) + 1000}"
        request.session['aixo_signup_otp'] = otp
        request.session['aixo_signup_otp_expires'] = now + 300
        request.session['aixo_signup_resend_after'] = now + 30

        full_phone = signup_data.get('full_phone') or f"{signup_data.get('country_code')} {signup_data.get('mobile')}"
        _logger.info("=== [AIXODESK SIGNUP OTP RESEND] Initiated for %s: %s ===", full_phone, otp)

        try:
            if 'sms.sms' in request.env:
                sms_body = f"Your new AixoDesk verification code is: {otp}. Valid for 5 minutes."
                request.env['sms.sms'].sudo().create({
                    'number': f"{signup_data.get('country_code')}{signup_data.get('mobile')}",
                    'body': sms_body,
                }).send()
        except Exception as e:
            _logger.warning("Could not dispatch resend via sms.sms: %s", e)

        return {
            'success': True,
            'message': f'A new verification code has been sent to {full_phone}.',
            'phone': full_phone,
            'resend_in': 30,
        }

    @http.route('/aixodesk/api/verify_otp', type='json', auth='public', website=True, methods=['POST'], csrf=False)
    def verify_otp(self, **kw):
        """Verify the 4-digit OTP code and create the user account."""
        ensure_db()
        data = _extract_data(kw)
        submitted_otp = str(data.get('otp') or '').strip()

        stored_otp = request.session.get('aixo_signup_otp')
        otp_expires = request.session.get('aixo_signup_otp_expires', 0)
        signup_data = request.session.get('aixo_signup_data')

        if not signup_data or not stored_otp:
            return {'success': False, 'error': 'Verification session expired. Please return to sign up and submit again.'}

        if time.time() > otp_expires:
            return {'success': False, 'error': 'Verification code has expired. Please click Resend code.'}

        if submitted_otp != stored_otp:
            return {'success': False, 'error': 'Invalid 4-digit verification code. Please check and try again.'}

        # Validated successfully! Create user in Odoo
        email = signup_data['email']
        full_name = f"{signup_data['first_name']} {signup_data['last_name']}".strip()
        phone = signup_data.get('full_phone') or f"{signup_data['country_code']} {signup_data['mobile']}"

        User = request.env['res.users'].sudo()
        if User.search_count([('login', '=', email)]) > 0:
            return {'success': False, 'error': 'An account with this email already exists. Please sign in.'}

        temp_password = secrets.token_urlsafe(16)
        try:
            portal_group = request.env.ref('base.group_portal')
            new_user = User.with_context(no_reset_password=True).create({
                'name': full_name,
                'login': email,
                'email': email,
                'phone': phone,
                'mobile': phone,
                'password': temp_password,
                'groups_id': [(6, 0, [portal_group.id])],
            })

            # Clean up verification session keys
            request.session.pop('aixo_signup_otp', None)
            request.session.pop('aixo_signup_data', None)
            request.session.pop('aixo_signup_otp_expires', None)
            request.session.pop('aixo_signup_resend_after', None)

            # Auto-authenticate user
            try:
                request.session.authenticate(request.env.cr.dbname, email, temp_password)
                redirect_url = '/my'
            except Exception as auth_err:
                _logger.warning("Session auto-auth fallback: %s", auth_err)
                redirect_url = f"/web/login?account_created=1&login={email}"

            return {
                'success': True,
                'message': 'Account verified and created successfully! Welcome to AixoDesk.',
                'redirect': redirect_url,
            }
        except Exception as e:
            _logger.exception("Failed to create user account: %s", e)
            return {'success': False, 'error': f'Failed to create account: {str(e)}'}
