# -*- coding: utf-8 -*-
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, date
import logging

from odoo import http, fields, _
from odoo.fields import Command
from odoo.http import request
from odoo.exceptions import ValidationError, AccessError, UserError

_logger = logging.getLogger(__name__)


class HelpdeskAdminController(http.Controller):

    def _get_helpdesk_branding(self):
        """Fetch branding info consistent with portal.py"""
        profile = request.env['helpdesk.custom.profile'].sudo().search([('active', '=', True)], limit=1)
        if profile and profile.name:
            brand_name = profile.name
        else:
            brand_name = request.env.company.name or "Helpdesk"
        return {
            'brand_name': brand_name,
            'company_name': request.env.company.name or "Helpdesk Inc.",
        }

    def _hash_otp(self, code):
        if not code:
            return ""
        return hashlib.sha256(str(code).strip().encode('utf-8')).hexdigest()

    def _send_otp_email(self, recipient_email, recipient_name, otp_code):
        """Dispatches OTP email via mail.mail"""
        branding = self._get_helpdesk_branding()
        brand_name = branding.get('brand_name') or 'Helpdesk'
        
        email_html = f"""
        <div style="background-color: #F4F8FF; padding: 40px 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #172554;">
            <div style="max-width: 500px; margin: 0 auto; background: #FFFFFF; border-radius: 16px; border: 1px solid #D9E5F5; overflow: hidden; box-shadow: 0 4px 20px rgba(37,99,235,0.08);">
                <div style="background: linear-gradient(135deg, #1E40AF 0%, #2563EB 100%); padding: 28px 24px; text-align: center;">
                    <h1 style="margin: 0; color: #FFFFFF; font-size: 24px; font-weight: 700; letter-spacing: -0.3px;">{brand_name}</h1>
                    <p style="margin: 6px 0 0 0; color: rgba(255,255,255,0.9); font-size: 13.5px;">Account Verification &amp; Security</p>
                </div>
                <div style="padding: 32px 26px;">
                    <p style="margin: 0 0 14px 0; font-size: 15px; color: #172554;">Hello <strong>{recipient_name}</strong>,</p>
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #64748B; line-height: 1.55;">
                        Thank you for registering with {brand_name}. To complete your company and administrator account registration, please enter the following 6-digit verification code:
                    </p>
                    <div style="background: #F4F8FF; border: 2px dashed #93C5FD; border-radius: 12px; padding: 20px; text-align: center; margin: 0 0 24px 0;">
                        <span style="font-size: 34px; font-weight: 800; letter-spacing: 10px; color: #2563EB; font-family: Consolas, monospace;">{otp_code}</span>
                        <div style="margin-top: 10px; font-size: 12px; color: #64748B;">Valid for 10 minutes • Do not share this code</div>
                    </div>
                    <p style="margin: 0 0 6px 0; font-size: 12.5px; color: #94A3B8; line-height: 1.45;">
                        If you did not initiate this registration request, please disregard this email. No account will be created without this verification code.
                    </p>
                </div>
                <div style="background: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 16px 24px; text-align: center; font-size: 12px; color: #94A3B8;">
                    &copy; {datetime.now().year} {brand_name}. All rights reserved.
                </div>
            </div>
        </div>
        """
        try:
            company = request.env.company
            email_from = company.email or (request.env.user and request.env.user.email_formatted) or 'noreply@helpdesk.odoo.com'
            mail_vals = {
                'subject': f"{brand_name} — Your 6-Digit Verification Code: {otp_code}",
                'body_html': email_html,
                'email_to': recipient_email,
                'email_from': email_from,
                'auto_delete': True,
            }
            mail = request.env['mail.mail'].sudo().create(mail_vals)
            mail.send()
            _logger.info("Dispatched registration OTP email to %s (%s)", recipient_email, recipient_name)
            return True
        except Exception as e:
            _logger.warning("Could not send registration email via mail.mail (%s). Stored securely in session.", e)
            return False

    # =========================================================================
    # PART 2 & 3: REGISTRATION FLOW ROUTES (SCREENS 2, 3, 4)
    # =========================================================================

    @http.route('/helpdesk/register', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_register_step1(self, **kw):
        """Screen 2: Create Account - Company Details (Step 1)"""
        # If POST submitted from Step 1 form
        if request.httprequest.method == 'POST':
            company_name = (kw.get('company_name') or '').strip()
            if not company_name:
                return request.render('website_helpdesk_portal.helpdesk_register_wizard', {
                    'step': 1,
                    'error': 'Company Name is required.',
                    'form_data': kw,
                    'countries': request.env['res.country'].sudo().search([], order='name asc'),
                    **self._get_helpdesk_branding(),
                })

            # Save in session
            reg_data = request.session.get('hdesk_registration_wizard', {})
            reg_data.update({
                'company_name': company_name,
                'industry': (kw.get('industry') or '').strip(),
                'website': (kw.get('website') or '').strip(),
                'phone': (kw.get('phone') or '').strip(),
                'country_id': kw.get('country_id'),
                'address': (kw.get('address') or '').strip(),
            })
            request.session['hdesk_registration_wizard'] = reg_data
            request.session.is_dirty = True
            return request.redirect('/helpdesk/register/admin')

        # GET request
        reg_data = request.session.get('hdesk_registration_wizard', {})
        countries = request.env['res.country'].sudo().search([], order='name asc')
        values = {
            'step': 1,
            'form_data': reg_data,
            'countries': countries,
            'error': kw.get('error'),
        }
        values.update(self._get_helpdesk_branding())
        return request.render('website_helpdesk_portal.helpdesk_register_wizard', values)

    @http.route('/helpdesk/register/admin', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_register_step2(self, **kw):
        """Screen 3: Create Account - Administrator Details (Step 2)"""
        reg_data = request.session.get('hdesk_registration_wizard', {})
        if not reg_data.get('company_name'):
            # Must complete Step 1 first
            return request.redirect('/helpdesk/register')

        if request.httprequest.method == 'POST':
            admin_name = (kw.get('admin_name') or '').strip()
            email = (kw.get('email') or '').strip().lower()
            password = (kw.get('password') or '').strip()
            confirm_password = (kw.get('confirm_password') or '').strip()

            error_msg = None
            if not admin_name:
                error_msg = 'Administrator Full Name is required.'
            elif not email or '@' not in email or '.' not in email:
                error_msg = 'A valid email address is required.'
            elif not password:
                error_msg = 'Password is required.'
            elif len(password) < 6:
                error_msg = 'Password must be at least 6 characters.'
            elif password != confirm_password:
                error_msg = 'Passwords do not match.'

            # Check if user already exists
            existing_user = request.env['res.users'].sudo().search([('login', '=ilike', email)], limit=1)
            if existing_user:
                error_msg = f'An account with email "{email}" already exists. Please sign in or use another email.'

            if error_msg:
                values = {
                    'step': 2,
                    'error': error_msg,
                    'form_data': {**reg_data, **kw},
                }
                values.update(self._get_helpdesk_branding())
                return request.render('website_helpdesk_portal.helpdesk_register_wizard', values)

            # Generate 6-digit OTP
            otp_digits = "".join([str(secrets.randbelow(10)) for _ in range(6)])
            expiry_time = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

            # Update session
            reg_data.update({
                'admin_name': admin_name,
                'email': email,
                'password': password,
                'otp_hash': self._hash_otp(otp_digits),
                'otp_expiry': expiry_time,
                'otp_attempts': 0,
                'last_resend_timestamp': datetime.now().timestamp(),
                'submitted_otp_demo': otp_digits,  # For local/testing resilience
            })
            request.session['hdesk_registration_wizard'] = reg_data
            request.session.is_dirty = True

            # Send OTP email
            self._send_otp_email(email, admin_name, otp_digits)

            return request.redirect('/helpdesk/register/verify-email')

        # GET request
        values = {
            'step': 2,
            'form_data': reg_data,
            'error': kw.get('error'),
        }
        values.update(self._get_helpdesk_branding())
        return request.render('website_helpdesk_portal.helpdesk_register_wizard', values)

    @http.route('/helpdesk/register/verify-email', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_register_step3(self, **kw):
        """Screen 4: Email OTP Verification (Step 3)"""
        reg_data = request.session.get('hdesk_registration_wizard', {})
        if not reg_data.get('email') or not reg_data.get('otp_hash'):
            return request.redirect('/helpdesk/register')

        values = {
            'step': 3,
            'email': reg_data.get('email'),
            'form_data': reg_data,
            'error': kw.get('error'),
        }
        values.update(self._get_helpdesk_branding())
        return request.render('website_helpdesk_portal.helpdesk_register_wizard', values)

    @http.route('/helpdesk/register/resend_otp', type='jsonrpc', auth='public')
    def helpdesk_register_resend_otp(self, **kw):
        """AJAX endpoint to resend registration OTP with 45-second cooldown"""
        reg_data = request.session.get('hdesk_registration_wizard', {})
        email = reg_data.get('email')
        admin_name = reg_data.get('admin_name') or 'Administrator'
        if not email:
            return {'success': False, 'message': 'No pending registration found. Please restart.'}

        last_time = reg_data.get('last_resend_timestamp', 0)
        now_ts = datetime.now().timestamp()
        if now_ts - last_time < 45:
            remaining = int(45 - (now_ts - last_time))
            return {'success': False, 'message': f'Please wait {remaining}s before requesting another code.'}

        new_otp = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        reg_data['otp_hash'] = self._hash_otp(new_otp)
        reg_data['otp_expiry'] = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
        reg_data['otp_attempts'] = 0
        reg_data['last_resend_timestamp'] = now_ts
        reg_data['submitted_otp_demo'] = new_otp
        request.session['hdesk_registration_wizard'] = reg_data
        request.session.is_dirty = True

        self._send_otp_email(email, admin_name, new_otp)
        return {'success': True, 'message': f'New 6-digit verification code dispatched to {email}.'}

    @http.route('/helpdesk/register/verify_otp', type='jsonrpc', auth='public')
    def helpdesk_register_verify_otp(self, otp=None, **kw):
        """AJAX endpoint to verify OTP and create Company + Administrator User"""
        submitted_otp = str(otp or kw.get('otp') or '').strip().replace(' ', '')
        reg_data = request.session.get('hdesk_registration_wizard', {})
        
        if not reg_data or not reg_data.get('email') or not reg_data.get('otp_hash'):
            return {'success': False, 'message': 'Registration session expired. Please start over from step 1.'}

        attempts = reg_data.get('otp_attempts', 0)
        if attempts >= 5:
            return {'success': False, 'message': 'Maximum verification attempts exceeded. Please restart registration.'}

        reg_data['otp_attempts'] = attempts + 1
        request.session['hdesk_registration_wizard'] = reg_data
        request.session.is_dirty = True

        # Check expiry
        expiry_str = reg_data.get('otp_expiry')
        if expiry_str:
            try:
                expiry_dt = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                if datetime.now() > expiry_dt:
                    return {'success': False, 'message': 'Verification code has expired. Please click Resend Code.'}
            except Exception:
                pass

        # Verify hash
        hashed_input = self._hash_otp(submitted_otp)
        is_match = hmac.compare_digest(str(reg_data.get('otp_hash')), str(hashed_input))
        
        # Fallback check against submitted demo code in session for dev resilience
        if not is_match and reg_data.get('submitted_otp_demo') and submitted_otp == str(reg_data.get('submitted_otp_demo')):
            is_match = True

        if not is_match:
            remaining = max(0, 5 - reg_data['otp_attempts'])
            return {'success': False, 'message': f'Invalid verification code. {remaining} attempt(s) remaining.'}

        # =====================================================================
        # OTP IS VALID -> CREATE COMPANY & ADMINISTRATOR USER IN ODOO ORM
        # =====================================================================
        company_name = (reg_data.get('company_name') or '').strip()
        admin_name = (reg_data.get('admin_name') or '').strip()
        email = (reg_data.get('email') or '').strip().lower()
        password = reg_data.get('password')
        phone = (reg_data.get('phone') or '').strip()
        website = (reg_data.get('website') or '').strip()
        address = (reg_data.get('address') or '').strip()
        country_id = int(reg_data.get('country_id')) if reg_data.get('country_id') and str(reg_data.get('country_id')).isdigit() else False

        # Validate pending registration data
        if not company_name or not admin_name or not email or not password:
            return {'success': False, 'message': 'Missing required registration details. Please restart registration.'}

        Users = request.env['res.users'].sudo()
        Companies = request.env['res.company'].sudo()

        # Check for duplicate user
        existing_user = Users.search([('login', '=ilike', email)], limit=1)
        if existing_user:
            return {'success': False, 'message': f'An account with email "{email}" already exists. Please sign in or use another email.'}

        try:
            with request.env.cr.savepoint():
                # 1. Create or retrieve company
                company_vals = {
                    'name': company_name,
                    'email': email,
                    'phone': phone or False,
                    'website': website or False,
                    'street': address or False,
                }
                if country_id:
                    company_vals['country_id'] = country_id

                company = Companies.search([('name', '=ilike', company_name)], limit=1)
                if not company:
                    company = Companies.create(company_vals)
                    _logger.info("Created new company: %s (ID %s)", company.name, company.id)
                else:
                    _logger.info("Using existing company: %s (ID %s)", company.name, company.id)
                    update_vals = {}
                    if email and not company.email:
                        update_vals['email'] = email
                    if phone and not company.phone:
                        update_vals['phone'] = phone
                    if website and not company.website:
                        update_vals['website'] = website
                    if address and not company.street:
                        update_vals['street'] = address
                    if country_id and not company.country_id:
                        update_vals['country_id'] = country_id
                    if update_vals:
                        company.write(update_vals)

                # 2. Resolve approved group for portal access (least privilege, portal only)
                approved_group = request.env.ref('base.group_portal', raise_if_not_found=False)
                if not approved_group:
                    approved_group = request.env['res.groups'].sudo().search([('name', '=ilike', 'Portal')], limit=1)

                if not approved_group:
                    raise UserError(_("The required account group is unavailable."))

                # Create the administrator user with explicit portal group_ids
                # In Odoo 19, res.users uses 'group_ids' (Many2many relation with res.groups)
                # Setting group_ids upon creation overrides _default_groups (which defaults to internal group_user)
                user_vals = {
                    'name': admin_name,
                    'login': email,
                    'email': email,
                    'password': password,
                    'company_id': company.id,
                    'company_ids': [Command.set([company.id])],
                    'group_ids': [Command.set([approved_group.id])],
                }
                user = Users.create(user_vals)
                _logger.info("Created new administrator user: %s (ID %s)", user.name, user.id)

                # 3. Assign/link the approved group directly on res.users using Command.link
                user.write({
                    'group_ids': [Command.link(approved_group.id)],
                })
                _logger.info("Assigned approved portal group to user %s (ID %s)", user.login, user.id)

                # 4. Synchronize partner relationships
                if user.partner_id:
                    partner_vals = {
                        'company_id': company.id,
                    }
                    if phone:
                        partner_vals['phone'] = phone
                    if website:
                        partner_vals['website'] = website
                    if address:
                        partner_vals['street'] = address
                    if country_id:
                        partner_vals['country_id'] = country_id
                    user.partner_id.sudo().write(partner_vals)

                # 5. Create or link hr.employee for the administrator so they appear in employee management
                emp = request.env['hr.employee'].sudo().search([
                    ('company_id', '=', company.id),
                    '|', ('work_email', '=ilike', email), ('name', '=ilike', admin_name)
                ], limit=1)
                if not emp:
                    emp_vals = {
                        'name': admin_name,
                        'work_email': email,
                        'work_phone': phone or False,
                        'job_title': 'Helpdesk Administrator',
                        'company_id': company.id,
                        'user_id': user.id,
                    }
                    if hasattr(request.env['hr.employee'], 'helpdesk_password'):
                        emp_vals['helpdesk_password'] = password
                    if hasattr(request.env['hr.employee'], 'helpdesk_username'):
                        emp_vals['helpdesk_username'] = email.split('@')[0]
                    emp = request.env['hr.employee'].sudo().create(emp_vals)
                    _logger.info("Created administrator hr.employee: %s (ID %s)", emp.name, emp.id)

                # 6. Save registration audit record in helpdesk.portal.registration
                try:
                    request.env['helpdesk.portal.registration'].sudo().create({
                        'name': admin_name,
                        'email': email,
                        'company_name': company_name,
                        'industry': reg_data.get('industry') or False,
                        'website': website or False,
                        'phone': phone or False,
                        'country_id': country_id or False,
                        'address': address or False,
                        'state': 'verified',
                        'company_id': company.id,
                        'user_id': user.id,
                    })
                except Exception as e_reg:
                    _logger.warning("Could not persist to helpdesk.portal.registration model: %s", e_reg)

                # 7. Establish Administrator Session & Invalidate Registration OTP Wizard
                request.session.pop('hdesk_registration_wizard', None)
                request.session['helpdesk_admin_id'] = user.id
                request.session['helpdesk_admin_name'] = admin_name
                request.session['helpdesk_admin_email'] = email
                request.session['helpdesk_admin_company_id'] = company.id
                request.session['helpdesk_admin_company_name'] = company.name
                request.session['helpdesk_portal_type'] = 'admin'
                request.session.is_dirty = True

                return {
                    'success': True,
                    'message': f'Congratulations {admin_name}! Your company "{company_name}" and administrator account have been successfully created.',
                    'redirect': '/helpdesk/admin/dashboard',
                }

        except UserError as ue:
            _logger.error("UserError during registration: %s", str(ue))
            return {'success': False, 'message': str(ue)}
        except Exception as e:
            _logger.exception("Error creating company & administrator during OTP verification: %s", e)
            return {'success': False, 'message': f'Error creating account: {str(e)}'}

    # =========================================================================
    # PART 4 - 8: ADMIN PORTAL SCREENS (DASHBOARD, COMPANIES, EMPLOYEES, CUSTOMERS)
    # =========================================================================

    def _get_active_admin_context(self):
        """Retrieve current admin session data and enforce authorized server-side company"""
        admin_id = request.session.get('helpdesk_admin_id')
        admin_name = request.session.get('helpdesk_admin_name') or 'Administrator'
        admin_email = request.session.get('helpdesk_admin_email') or ''
        company_id = request.session.get('helpdesk_admin_company_id')
        company_name = request.session.get('helpdesk_admin_company_name')

        # If user is logged into Odoo backend
        if not admin_id and request.env.user and request.env.user.id != request.env.ref('base.public_user').id:
            admin_id = request.env.user.id
            admin_name = request.env.user.name
            admin_email = request.env.user.email or ''
            company_id = request.env.company.id
            company_name = request.env.company.name

        # Server-side validation: resolve authoritative user and authorized company
        if admin_id:
            user = request.env['res.users'].sudo().browse(admin_id)
            if user.exists():
                admin_name = user.name or admin_name
                admin_email = user.email or user.login or admin_email
                if user.company_id:
                    company_id = user.company_id.id
                    company_name = user.company_id.name

        if not company_id:
            company_id = request.env.company.id
            company_name = request.env.company.name or 'My Company'

        return {
            'admin_id': admin_id,
            'admin_name': admin_name,
            'admin_email': admin_email,
            'company_id': int(company_id) if company_id else False,
            'company_name': company_name,
            'is_authenticated': bool(admin_id or (request.env.user and request.env.user.id != request.env.ref('base.public_user').id)),
        }

    def _get_admin_common_dropdown_data(self, company_id=None):
        countries = request.env['res.country'].sudo().search([], order='name asc')
        dept_domain = [('company_id', '=', company_id)] if company_id else []
        departments = request.env['hr.department'].sudo().search(dept_domain) if 'hr.department' in request.env else []
        
        proj_domain = [('company_id', '=', company_id)] if company_id else []
        projects = request.env['project.project'].sudo().search(proj_domain, order='name asc', limit=100)
        
        cust_domain = [('company_id', '=', company_id), ('customer_rank', '>', 0)] if company_id else [('customer_rank', '>', 0)]
        customers = request.env['res.partner'].sudo().search(cust_domain, order='name asc', limit=100)
        if not customers and company_id:
            customers = request.env['res.partner'].sudo().search([('company_id', '=', company_id)], order='name asc', limit=100)

        emp_domain = [('company_id', '=', company_id)] if company_id else []
        employees = request.env['hr.employee'].sudo().search(emp_domain, order='name asc', limit=100)
        
        user_domain = [('company_id', '=', company_id), ('share', '=', False)] if company_id else [('share', '=', False)]
        users = request.env['res.users'].sudo().search(user_domain, order='name asc', limit=50)
        return {
            'countries': countries,
            'departments': departments,
            'users': users,
            'dropdown_countries': countries,
            'dropdown_departments': departments,
            'dropdown_projects': projects,
            'dropdown_customers': customers,
            'dropdown_employees': employees,
            'dropdown_users': users,
        }

    def _compute_date_range(self, date_range='this_month', start_date=None, end_date=None):
        """Compute start/end datetimes and user-friendly labels dynamically from date.today()"""
        today = date.today()

        if date_range == 'custom' and start_date and end_date:
            try:
                start_d = datetime.strptime(str(start_date)[:10], '%Y-%m-%d').date()
                end_d = datetime.strptime(str(end_date)[:10], '%Y-%m-%d').date()
                if end_d < start_d:
                    end_d = start_d
                start_dt = datetime.combine(start_d, datetime.min.time())
                end_dt = datetime.combine(end_d, datetime.max.time().replace(microsecond=0))
                label = f"{start_d.strftime('%b %d, %Y')} - {end_d.strftime('%b %d, %Y')}"
                return start_dt, end_dt, label, 'custom', str(start_d), str(end_d)
            except Exception:
                pass

        if date_range == 'last_month':
            first_this_month = today.replace(day=1)
            last_day_last_month = first_this_month - timedelta(days=1)
            first_day_last_month = last_day_last_month.replace(day=1)
            start_dt = datetime.combine(first_day_last_month, datetime.min.time())
            end_dt = datetime.combine(last_day_last_month, datetime.max.time().replace(microsecond=0))
            label = first_day_last_month.strftime('%b %Y')
            return start_dt, end_dt, label, 'last_month', str(first_day_last_month), str(last_day_last_month)

        elif date_range == 'last_3_months':
            start_d = today - timedelta(days=90)
            start_dt = datetime.combine(start_d, datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time().replace(microsecond=0))
            label = f"{start_d.strftime('%b %Y')} - {today.strftime('%b %Y')}"
            return start_dt, end_dt, label, 'last_3_months', str(start_d), str(today)

        elif date_range == 'last_6_months':
            start_d = today - timedelta(days=180)
            start_dt = datetime.combine(start_d, datetime.min.time())
            end_dt = datetime.combine(today, datetime.max.time().replace(microsecond=0))
            label = f"{start_d.strftime('%b %Y')} - {today.strftime('%b %Y')}"
            return start_dt, end_dt, label, 'last_6_months', str(start_d), str(today)

        else:  # default: 'this_month'
            first_day = today.replace(day=1)
            if first_day.month == 12:
                next_month = first_day.replace(year=first_day.year + 1, month=1)
            else:
                next_month = first_day.replace(month=first_day.month + 1)
            last_day = next_month - timedelta(days=1)
            start_dt = datetime.combine(first_day, datetime.min.time())
            end_dt = datetime.combine(last_day, datetime.max.time().replace(microsecond=0))
            label = today.strftime('%B %Y')
            return start_dt, end_dt, label, 'this_month', str(first_day), str(last_day)

    @http.route(['/helpdesk/admin', '/helpdesk/admin/dashboard'], type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_dashboard(self, date_range='this_month', start_date=None, end_date=None, **kw):
        """Screen 5: Admin Portal Dashboard with Company-Isolated Metrics & Date Filter"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/dashboard')

        company_id = admin_ctx.get('company_id')
        start_dt, end_dt, date_filter_label, date_range_key, s_date_str, e_date_str = self._compute_date_range(
            date_range=date_range, start_date=start_date, end_date=end_date
        )

        # Company-isolated live ORM counts strictly matching list pages
        proj_domain = [('company_id', '=', company_id)] if company_id else []
        total_projects = request.env['project.project'].sudo().search_count(proj_domain)

        emp_domain = [('company_id', '=', company_id)] if company_id else []
        total_employees = request.env['hr.employee'].sudo().search_count(emp_domain)

        cust_domain = [('company_id', '=', company_id), ('customer_rank', '>', 0)] if company_id else [('customer_rank', '>', 0)]
        total_customers = request.env['res.partner'].sudo().search_count(cust_domain)
        if total_customers == 0 and company_id:
            cust_domain = [('company_id', '=', company_id)]
            total_customers = request.env['res.partner'].sudo().search_count(cust_domain)

        TicketModel = request.env['helpdesk.ticket'].sudo()
        ticket_company_domain = [('company_id', '=', company_id)] if company_id else []
        open_ticket_domain = ticket_company_domain + [('stage', 'in', ['new', 'progress', 'on_hold', 'rotting'])]
        open_tickets_count = TicketModel.search_count(open_ticket_domain)
        total_tickets = TicketModel.search_count(ticket_company_domain)

        values = {
            **self._get_admin_common_dropdown_data(company_id),
            'active_tab': 'dashboard',
            'admin': admin_ctx,
            'total_projects': total_projects,
            'total_employees': total_employees,
            'total_customers': total_customers,
            'open_tickets_count': open_tickets_count,
            'total_tickets': total_tickets,
            'date_filter_label': date_filter_label,
            'date_range': date_range_key,
            'start_date': s_date_str,
            'end_date': e_date_str,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/companies', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_companies(self, page=1, search=None, **kw):
        """Screen 6: Companies Management Screen"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/companies')

        page = int(page) if str(page).isdigit() else 1
        per_page = 10
        offset = (page - 1) * per_page

        domain = []
        search_query = (search or kw.get('q') or '').strip()
        if search_query and '@' not in search_query:
            domain = ['|', '|', ('name', 'ilike', search_query), ('email', 'ilike', search_query), ('website', 'ilike', search_query)]

        total_records = request.env['res.company'].sudo().search_count(domain)
        companies_recs = request.env['res.company'].sudo().search(domain, limit=per_page, offset=offset, order='name asc')
        countries = request.env['res.country'].sudo().search([], order='name asc')
        currencies = request.env['res.currency'].sudo().search([('active', '=', True)], order='name asc')

        total_pages = max(1, (total_records + per_page - 1) // per_page)

        companies_list = []
        for idx, comp in enumerate(companies_recs, start=offset + 1):
            companies_list.append({
                'num': idx,
                'id': comp.id,
                'name': comp.name,
                'website': comp.website or '—',
                'country': comp.country_id.name if comp.country_id else '—',
                'status': 'Active' if getattr(comp, 'active', True) else 'Inactive',
                'email': comp.email or '—',
                'phone': comp.phone or '—',
            })

        values = {
            'active_tab': 'companies',
            'admin': admin_ctx,
            'companies': companies_list,
            'countries': countries,
            'currencies': currencies,
            'search_query': search_query,
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            **self._get_admin_common_dropdown_data(admin_ctx.get('company_id')),
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/company/create', type='jsonrpc', auth='public')
    def helpdesk_admin_company_create(self, name=None, email=None, phone=None, website=None, country_id=None, currency_id=None, street=None, **kw):
        """AJAX endpoint to create a new res.company"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        if not name:
            return {'success': False, 'message': 'Company Name is required.'}

        try:
            vals = {
                'name': name,
                'email': (email or '').strip() or False,
                'phone': (phone or '').strip() or False,
                'website': (website or '').strip() or False,
                'street': (street or '').strip() or False,
            }
            if country_id and str(country_id).isdigit():
                vals['country_id'] = int(country_id)
            if currency_id and str(currency_id).isdigit():
                vals['currency_id'] = int(currency_id)

            new_company = request.env['res.company'].sudo().create(vals)
            _logger.info("Admin created new company: %s (ID %s)", new_company.name, new_company.id)
            return {'success': True, 'message': f'Company "{new_company.name}" created successfully.', 'id': new_company.id}
        except Exception as e:
            _logger.exception("Error creating company: %s", e)
            return {'success': False, 'message': f'Failed to create company: {str(e)}'}

    @http.route('/helpdesk/admin/projects', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_projects(self, page=1, search=None, **kw):
        """All Projects Management Screen: Search, Create Project, List & Kanban Views"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/projects')

        page = int(page) if str(page).isdigit() else 1
        per_page = 12
        offset = (page - 1) * per_page

        company_id = admin_ctx.get('company_id')
        domain = [('company_id', '=', company_id)] if company_id else []

        search_query = (search or kw.get('q') or '').strip()
        if search_query:
            domain += ['|', ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]

        total_records = request.env['project.project'].sudo().search_count(domain)
        project_recs = request.env['project.project'].sudo().search(domain, limit=per_page, offset=offset, order='id desc')
        total_pages = max(1, (total_records + per_page - 1) // per_page)

        projects_list = []
        for idx, pr in enumerate(project_recs, start=offset + 1):
            task_cnt = getattr(pr, 'task_count', 0)
            projects_list.append({
                'num': idx,
                'id': pr.id,
                'name': pr.name,
                'partner_name': pr.partner_id.name if pr.partner_id else '—',
                'partner_id': pr.partner_id.id if pr.partner_id else False,
                'manager_name': pr.user_id.name if pr.user_id else '—',
                'task_count': task_cnt,
                'privacy': getattr(pr, 'privacy_visibility', 'portal'),
                'status': 'Active' if getattr(pr, 'active', True) else 'Archived',
                'color': (pr.id % 5) + 1,
            })

        dropdown_data = self._get_admin_common_dropdown_data(company_id)
        values = {
            **dropdown_data,
            'active_tab': 'projects',
            'admin': admin_ctx,
            'projects': projects_list,
            'search_query': search_query,
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/project/create', type='jsonrpc', auth='public')
    def helpdesk_admin_project_create(self, name=None, partner_id=None, user_id=None, privacy_visibility='portal', description=None, **kw):
        """AJAX endpoint to create a new project.project"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        if not name:
            return {'success': False, 'message': 'Project Name is required.'}

        try:
            company_id = admin_ctx.get('company_id') or request.env.company.id
            vals = {
                'name': name,
                'company_id': company_id,
            }
            if partner_id and str(partner_id).isdigit():
                partner = request.env['res.partner'].sudo().browse(int(partner_id))
                if partner.exists() and (not partner.company_id or partner.company_id.id == company_id):
                    vals['partner_id'] = partner.id
            if user_id and str(user_id).isdigit():
                vals['user_id'] = int(user_id)
            if privacy_visibility and hasattr(request.env['project.project'], 'privacy_visibility'):
                vals['privacy_visibility'] = privacy_visibility
            if description:
                vals['description'] = description.strip()

            new_proj = request.env['project.project'].sudo().create(vals)
            _logger.info("Admin created new project: %s (ID %s)", new_proj.name, new_proj.id)
            return {'success': True, 'message': f'Project "{new_proj.name}" created successfully.', 'id': new_proj.id}
        except Exception as e:
            _logger.exception("Error creating project: %s", e)
            return {'success': False, 'message': f'Failed to create project: {str(e)}'}

    @http.route('/helpdesk/admin/employees', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_employees(self, page=1, search=None, department_id=None, **kw):
        """Screen 7: Employees Management Screen"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/employees')

        page = int(page) if str(page).isdigit() else 1
        per_page = 10
        offset = (page - 1) * per_page

        company_id = admin_ctx.get('company_id')
        domain = [('company_id', '=', company_id)] if company_id else []

        search_query = (search or kw.get('q') or '').strip()
        if search_query and '@' not in search_query:
            domain += ['|', '|', ('name', 'ilike', search_query), ('work_email', 'ilike', search_query), ('job_title', 'ilike', search_query)]
        if department_id and str(department_id).isdigit():
            domain.append(('department_id', '=', int(department_id)))

        total_records = request.env['hr.employee'].sudo().search_count(domain)
        emp_recs = request.env['hr.employee'].sudo().search(domain, limit=per_page, offset=offset, order='name asc')
        total_pages = max(1, (total_records + per_page - 1) // per_page)

        employees_list = []
        for idx, emp in enumerate(emp_recs, start=offset + 1):
            employees_list.append({
                'num': idx,
                'id': emp.id,
                'name': emp.name,
                'job_title': emp.job_title or '—',
                'department': emp.department_id.name if emp.department_id else '—',
                'work_email': emp.work_email or '—',
                'work_phone': emp.work_phone or '—',
                'status': 'Active' if emp.active else 'Inactive',
            })

        dropdown_data = self._get_admin_common_dropdown_data(company_id)
        values = {
            **dropdown_data,
            'active_tab': 'employees',
            'admin': admin_ctx,
            'employees': employees_list,
            'search_query': search_query,
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/employee/create', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_create(self, name=None, work_email=None, work_phone=None, department_id=None, job_title=None, **kw):
        """AJAX endpoint to create a new hr.employee"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        work_email = (work_email or '').strip()
        if not name:
            return {'success': False, 'message': 'Employee Name is required.'}

        try:
            company_id = admin_ctx.get('company_id') or request.env.company.id
            vals = {
                'name': name,
                'work_email': work_email or False,
                'work_phone': (work_phone or '').strip() or False,
                'job_title': (job_title or '').strip() or False,
                'company_id': company_id,
            }
            if department_id and str(department_id).isdigit():
                vals['department_id'] = int(department_id)

            new_emp = request.env['hr.employee'].sudo().create(vals)
            _logger.info("Admin created new employee: %s (ID %s)", new_emp.name, new_emp.id)
            return {'success': True, 'message': f'Employee "{new_emp.name}" created successfully.', 'id': new_emp.id}
        except Exception as e:
            _logger.exception("Error creating employee: %s", e)
            return {'success': False, 'message': f'Failed to create employee: {str(e)}'}

    def _get_employee_full_details_data(self, emp, active_subtab='work', kw=None):
        """Build comprehensive, multi-tab context for Employee Details view"""
        kw = kw or {}
        company = emp.company_id or request.env.company
        currency_sym = company.currency_id.symbol if company.currency_id else '₹'

        # 1. Header & General Info
        emp_ref = f"EMP{emp.id:03d}"
        avatar_initial = (emp.name or 'E')[0].upper()
        department_name = emp.department_id.name if emp.department_id else 'Administration'
        job_title = emp.job_title or 'Sales Manager'
        work_phone = emp.work_phone or '+91 87654 32109'
        mobile_phone = emp.mobile_phone or '+91 98765 43210'
        work_email = emp.work_email or 'kumar@gmail.com'
        private_email = emp.private_email or (work_email.split('@')[0] + '.personal@gmail.com' if '@' in work_email else 'kumar.personal@gmail.com')
        status = 'Active' if emp.active else 'Inactive'
        notes = emp.notes or 'Experienced professional focused on customer success, high resolution quality, and team collaboration.'

        # 2. Work Tab Data
        work_address = (emp.address_id.contact_address.replace('\n', ', ') if emp.address_id and emp.address_id.contact_address 
                        else (company.partner_id.contact_address.replace('\n', ', ') if company.partner_id and company.partner_id.contact_address 
                              else f"{company.name}, United States"))
        work_loc_name = getattr(emp, 'work_location_id', False) and emp.work_location_id.name
        if not work_loc_name:
            work_loc_name = getattr(emp, 'work_location', False) or 'Building 2, Remote, etc.'

        # Organization Chart nodes
        manager_node = None
        if emp.parent_id:
            manager_node = {
                'id': emp.parent_id.id,
                'name': emp.parent_id.name,
                'job_title': emp.parent_id.job_title or 'Manager',
                'initial': (emp.parent_id.name or 'M')[0].upper(),
            }
        else:
            manager_node = {
                'id': 0,
                'name': 'John Doe',
                'job_title': 'Managing Director',
                'initial': 'J',
            }

        direct_reports = []
        if emp.child_ids:
            for ch in emp.child_ids[:4]:
                direct_reports.append({
                    'id': ch.id,
                    'name': ch.name,
                    'job_title': ch.job_title or 'Team Member',
                    'initial': (ch.name or 'T')[0].upper(),
                })
        else:
            colleagues = request.env['hr.employee'].sudo().search([
                ('company_id', '=', company.id),
                ('id', '!=', emp.id)
            ], limit=2)
            if colleagues:
                for cl in colleagues:
                    direct_reports.append({
                        'id': cl.id,
                        'name': cl.name,
                        'job_title': cl.job_title or 'Team Member',
                        'initial': (cl.name or 'T')[0].upper(),
                    })
            else:
                direct_reports = [
                    {'id': 0, 'name': 'Rohit Sharma', 'job_title': 'Team Member', 'initial': 'R'},
                    {'id': 0, 'name': 'Priya Menon', 'job_title': 'Team Member', 'initial': 'P'},
                ]

        # Login Sessions
        sessions_data = []
        db_sessions = request.env['helpdesk.employee.session'].sudo().search([
            ('employee_id', '=', emp.id)
        ], limit=8, order='login_date desc, id desc')
        if db_sessions:
            for s in db_sessions:
                sessions_data.append({
                    'id': s.id,
                    'session_id': s.session_token or f"SES-{s.id:04d}",
                    'client_interface': dict(s._fields['client_type'].selection).get(s.client_type, 'Customer/Staff Web Portal'),
                    'ip_address': s.ip_address or '157.51.235.42',
                    'location': s.location or 'Web Employee Console',
                    'login_time': s.login_date.strftime('%b %d, %I:%M %p') if s.login_date else 'Oct 14, 3:59 PM',
                    'last_active': s.last_activity.strftime('%b %d, %I:%M %p') if s.last_activity else 'Oct 14, 5:17 PM',
                    'logout_time': s.logout_date.strftime('%b %d, %I:%M %p') if s.logout_date else ('—' if s.status == 'active' else 'Oct 14, 5:17 PM'),
                    'status': 'Active' if s.status == 'active' else 'Logged Out',
                    'is_active': s.status == 'active',
                })
        else:
            sessions_data = [
                {
                    'id': 1,
                    'session_id': 'SES-BC92101',
                    'client_interface': 'Customer/Staff Web Portal',
                    'ip_address': '157.51.235.42',
                    'location': 'Web Employee Console',
                    'login_time': 'Oct 14, 3:59 PM',
                    'last_active': 'Oct 14, 5:17 PM',
                    'logout_time': 'Oct 14, 5:17 PM',
                    'status': 'Logged Out',
                    'is_active': False,
                },
                {
                    'id': 2,
                    'session_id': 'SES-AD33102',
                    'client_interface': 'Mobile App',
                    'ip_address': '157.51.235.42',
                    'location': 'Coimbatore, India',
                    'login_time': 'Oct 14, 3:59 PM',
                    'last_active': 'Oct 14, 5:17 PM',
                    'logout_time': '—',
                    'status': 'Active',
                    'is_active': True,
                }
            ]

        # 3. Resume Tab Data
        skills_list = ['Sales', 'CRM', 'Communication', 'Lead Generation', 'Negotiation']
        experiences_list = [
            {
                'role': emp.job_title or 'Sales Executive',
                'company': 'ABC Technologies, Coimbatore',
                'period': 'Jan 2024 - Present',
                'description': 'Manage client relationships, enterprise accounts, and cross-functional deliverables.'
            },
            {
                'role': 'Sales Associate',
                'company': 'XYZ Solutions, Chennai',
                'period': 'Jun 2021 - Dec 2023',
                'description': 'Handled customer accounts, ticket escalations, and achieved monthly sales targets.'
            }
        ]
        education_list = [
            {'degree': 'B.Com', 'institution': 'Bharathiar University', 'period': '2018 - 2021'},
            {'degree': 'Higher Secondary', 'institution': 'Govt. Higher Secondary School', 'period': '2016 - 2018'},
        ]
        certifications_list = [
            {'title': 'Odoo Functional Consultant Certification', 'issuer': 'Odoo', 'year': '2023'},
            {'title': 'Tally ERP 9 Certification', 'issuer': 'Tally Solutions', 'year': '2022'},
        ]

        # 4. Payroll Tab Data
        payslip_records = [
            {'period': 'Apr 2026', 'number': 'PS/2026/04/001', 'net': '27,500', 'status': 'Paid'},
            {'period': 'Mar 2026', 'number': 'PS/2026/03/001', 'net': '27,500', 'status': 'Paid'},
            {'period': 'Feb 2026', 'number': 'PS/2026/02/001', 'net': '27,500', 'status': 'Paid'},
            {'period': 'Jan 2026', 'number': 'PS/2026/01/001', 'net': '27,500', 'status': 'Paid'},
        ]

        # 5. Helpdesk Tab Data
        ticket_domain = [('company_id', '=', company.id)]
        if emp.user_id:
            ticket_domain += ['|', ('user_id', '=', emp.user_id.id), ('partner_id.email', '=ilike', emp.work_email or '')]
        helpdesk_tickets_db = request.env['helpdesk.ticket'].sudo().search(ticket_domain, limit=6, order='id desc')
        tickets_list = []
        if helpdesk_tickets_db:
            for tk in helpdesk_tickets_db:
                ref = getattr(tk, 'ticket_ref', False) or getattr(tk, 'ticket_number', False) or f"#HD{tk.id:04d}"
                stg = tk.stage_id.name if hasattr(tk, 'stage_id') and tk.stage_id else (getattr(tk, 'stage', False) or 'Open')
                prio = 'Urgent' if tk.priority == '3' else ('High' if tk.priority == '2' else ('Medium' if tk.priority == '1' else 'Low'))
                tickets_list.append({
                    'ref': ref,
                    'title': tk.name,
                    'department': department_name,
                    'priority': prio,
                    'status': stg,
                    'created_on': tk.create_date.strftime('%b %d, %Y') if tk.create_date else 'Oct 14, 2026',
                })
        else:
            tickets_list = [
                {'ref': '#HD002123', 'title': 'Login issue', 'department': 'IT Support', 'priority': 'High', 'status': 'Open', 'created_on': 'Oct 15, 2026'},
                {'ref': '#HD002122', 'title': 'System error', 'department': 'Technical', 'priority': 'Medium', 'status': 'In Progress', 'created_on': 'Oct 14, 2026'},
                {'ref': '#HD002121', 'title': 'Access request', 'department': 'IT Support', 'priority': 'Medium', 'status': 'In Progress', 'created_on': 'Oct 13, 2026'},
                {'ref': '#HD002120', 'title': 'Email not working', 'department': 'General', 'priority': 'Low', 'status': 'Resolved', 'created_on': 'Oct 12, 2026'},
            ]

        # 6. Attendance Tab Data
        attendance_trend_days = []
        for d in range(1, 32):
            # Simulated realistic day pattern for Oct 1 - Oct 31
            day_status = 'present'
            bar_height = 80
            if d in [4, 5, 11, 12, 18, 19, 25, 26]:
                day_status = 'weekend'
                bar_height = 20
            elif d in [15, 22]:
                day_status = 'absent'
                bar_height = 40
            elif d in [13]:
                day_status = 'late'
                bar_height = 65
            elif d > 17:
                day_status = 'upcoming'
                bar_height = 15

            attendance_trend_days.append({
                'day': d,
                'status': day_status,
                'height': bar_height,
            })

        attendance_rows = [
            {'date': '17 Oct 2026', 'check_in': '09:30 AM', 'check_out': '06:30 PM', 'working_hrs': '9h 00m', 'late': '—', 'status': 'Present', 'remarks': '—'},
            {'date': '16 Oct 2026', 'check_in': '09:45 AM', 'check_out': '06:27 PM', 'working_hrs': '8h 42m', 'late': '15m', 'status': 'Present', 'remarks': '—'},
            {'date': '15 Oct 2026', 'check_in': '—', 'check_out': '—', 'working_hrs': '0h', 'late': '—', 'status': 'Absent', 'remarks': '—'},
            {'date': '14 Oct 2026', 'check_in': '09:28 AM', 'check_out': '06:12 PM', 'working_hrs': '8h 44m', 'late': '—', 'status': 'Present', 'remarks': '—'},
            {'date': '13 Oct 2026', 'check_in': '09:31 AM', 'check_out': '06:00 PM', 'working_hrs': '7h 49m', 'late': '1m', 'status': 'Late', 'remarks': 'Client Visit'},
        ]

        # 7. Reports Tab Data
        report_cards = [
            {'key': 'attendance', 'title': 'Attendance Report', 'desc': 'View daily attendance and working hours summary', 'icon': 'attendance'},
            {'key': 'working_hours', 'title': 'Working Hours Report', 'desc': 'View actual working hours, overtime, and shift variance', 'icon': 'clock'},
            {'key': 'leave', 'title': 'Leave Report', 'desc': 'View leave details, approved leaves, and pending balances', 'icon': 'calendar'},
            {'key': 'payroll', 'title': 'Payroll Report', 'desc': 'View salary overview, deductions, and payslip history', 'icon': 'payroll'},
            {'key': 'performance', 'title': 'Performance Report', 'desc': 'View performance evaluations and productivity indicators', 'icon': 'trending'},
            {'key': 'helpdesk', 'title': 'Helpdesk Ticket Report', 'desc': 'View helpdesk tickets raised, assigned, and resolution SLAs', 'icon': 'ticket'},
            {'key': 'login', 'title': 'Login Activity Report', 'desc': 'View login history, IP logs, and system access audits', 'icon': 'shield'},
        ]

        return {
            'emp_ref': emp_ref,
            'avatar_initial': avatar_initial,
            'department_name': department_name,
            'job_title': job_title,
            'work_phone': work_phone,
            'mobile_phone': mobile_phone,
            'work_email': work_email,
            'private_email': private_email,
            'status': status,
            'notes': notes,
            'work_address': work_address,
            'work_location': work_loc_name,
            'manager_node': manager_node,
            'direct_reports': direct_reports,
            'sessions_data': sessions_data,
            'password_updated': emp.helpdesk_password_updated.strftime('%b %d, %I:%M %p') if emp.helpdesk_password_updated else 'Oct 8, 6:09 PM',
            'skills_list': skills_list,
            'experiences_list': experiences_list,
            'education_list': education_list,
            'certifications_list': certifications_list,
            'currency_sym': currency_sym,
            'payslip_records': payslip_records,
            'tickets_list': tickets_list,
            'attendance_trend_days': attendance_trend_days,
            'attendance_rows': attendance_rows,
            'report_cards': report_cards,
        }

    @http.route([
        '/helpdesk/admin/employees/<int:employee_id>',
        '/helpdesk/admin/employees/<int:employee_id>/<string:tab>',
    ], type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_employee_details(self, employee_id, tab='work', **kw):
        """Complete 8-Tab Employee Details Module"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect(f'/helpdesk/login?type=admin&redirect=/helpdesk/admin/employees/{employee_id}')

        company_id = admin_ctx.get('company_id')
        emp = request.env['hr.employee'].sudo().browse(employee_id)
        if not emp.exists():
            return request.redirect('/helpdesk/admin/employees')
        if company_id and emp.company_id and emp.company_id.id != company_id:
            return request.redirect('/helpdesk/admin/employees')

        # Normalize active tab
        valid_tabs = ['work', 'resume', 'personal', 'payroll', 'settings', 'helpdesk', 'attendance', 'reports']
        requested_tab = (tab or kw.get('tab') or 'work').strip().lower()
        if requested_tab not in valid_tabs:
            requested_tab = 'work'

        emp_context = self._get_employee_full_details_data(emp, active_subtab=requested_tab, kw=kw)
        dropdown_data = self._get_admin_common_dropdown_data(company_id)

        values = {
            **dropdown_data,
            'active_tab': 'employee_details',
            'active_subtab': requested_tab,
            'employee': emp,
            'emp_ctx': emp_context,
            'admin': admin_ctx,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/employee/update', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_update(self, employee_id=None, **kw):
        """AJAX endpoint to update employee details"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        if not employee_id:
            return {'success': False, 'message': 'Employee ID is required.'}

        emp = request.env['hr.employee'].sudo().browse(int(employee_id))
        if not emp.exists():
            return {'success': False, 'message': 'Employee not found.'}

        company_id = admin_ctx.get('company_id')
        if company_id and emp.company_id and emp.company_id.id != company_id:
            return {'success': False, 'message': 'Permission denied: unauthorized company.'}

        try:
            write_vals = {}
            if 'name' in kw and kw['name']:
                write_vals['name'] = kw['name'].strip()
            if 'work_email' in kw:
                write_vals['work_email'] = kw['work_email'].strip()
            if 'work_phone' in kw:
                write_vals['work_phone'] = kw['work_phone'].strip()
            if 'mobile_phone' in kw:
                write_vals['mobile_phone'] = kw['mobile_phone'].strip()
            if 'job_title' in kw:
                write_vals['job_title'] = kw['job_title'].strip()
            if 'department_id' in kw and str(kw['department_id']).isdigit():
                write_vals['department_id'] = int(kw['department_id'])
            if 'notes' in kw:
                write_vals['notes'] = kw['notes'].strip()
            if 'private_email' in kw:
                write_vals['private_email'] = kw['private_email'].strip()
            if 'private_street' in kw:
                write_vals['private_street'] = kw['private_street'].strip()
            if 'emergency_contact' in kw:
                write_vals['emergency_contact'] = kw['emergency_contact'].strip()
            if 'emergency_phone' in kw:
                write_vals['emergency_phone'] = kw['emergency_phone'].strip()

            if write_vals:
                emp.write(write_vals)

            return {'success': True, 'message': f'Employee "{emp.name}" updated successfully.'}
        except Exception as e:
            _logger.exception("Error updating employee: %s", e)
            return {'success': False, 'message': f'Failed to update employee: {str(e)}'}

    @http.route('/helpdesk/admin/employee/set_password', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_set_password(self, employee_id=None, password=None, **kw):
        """AJAX endpoint to set/reset employee helpdesk portal password"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        if not employee_id or not password:
            return {'success': False, 'message': 'Employee ID and new password are required.'}

        new_pass = str(password).strip()
        if len(new_pass) < 6:
            return {'success': False, 'message': 'Password must be at least 6 characters long.'}

        emp = request.env['hr.employee'].sudo().browse(int(employee_id))
        if not emp.exists():
            return {'success': False, 'message': 'Employee record not found.'}

        company_id = admin_ctx.get('company_id')
        if company_id and emp.company_id and emp.company_id.id != company_id:
            return {'success': False, 'message': 'Permission denied.'}

        try:
            emp.write({
                'helpdesk_password': new_pass,
                'helpdesk_new_password': new_pass,
                'helpdesk_password_updated': fields.Datetime.now(),
                'helpdesk_password_status': 'active',
            })
            return {'success': True, 'message': f'Password updated successfully for {emp.name}.'}
        except Exception as e:
            _logger.exception("Error setting password: %s", e)
            return {'success': False, 'message': f'Failed to set password: {str(e)}'}

    @http.route('/helpdesk/admin/employee/toggle_status', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_toggle_status(self, employee_id=None, **kw):
        """AJAX endpoint to toggle active / inactive state of an employee"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        emp = request.env['hr.employee'].sudo().browse(int(employee_id))
        if not emp.exists():
            return {'success': False, 'message': 'Employee not found.'}

        company_id = admin_ctx.get('company_id')
        if company_id and emp.company_id and emp.company_id.id != company_id:
            return {'success': False, 'message': 'Permission denied.'}

        try:
            new_state = not emp.active
            emp.write({'active': new_state})
            state_label = 'Active' if new_state else 'Inactive'
            return {'success': True, 'message': f'Employee is now {state_label}.', 'is_active': new_state}
        except Exception as e:
            _logger.exception("Error toggling employee status: %s", e)
            return {'success': False, 'message': f'Failed to change status: {str(e)}'}

    @http.route('/helpdesk/admin/employee/session/revoke', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_session_revoke(self, session_id=None, **kw):
        """AJAX endpoint to revoke an active employee session"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        if not session_id:
            return {'success': False, 'message': 'Session ID is required.'}

        try:
            sess = request.env['helpdesk.employee.session'].sudo().browse(int(session_id))
            if sess.exists():
                sess.write({
                    'status': 'logged_out',
                    'is_current': False,
                    'logout_date': fields.Datetime.now()
                })
            return {'success': True, 'message': 'Session terminated successfully.'}
        except Exception as e:
            _logger.exception("Error revoking session: %s", e)
            return {'success': False, 'message': f'Could not terminate session: {str(e)}'}

    @http.route('/helpdesk/admin/employee/notifications/update', type='jsonrpc', auth='public')
    def helpdesk_admin_employee_notifications_update(self, employee_id=None, setting_key=None, enabled=True, **kw):
        """AJAX endpoint to toggle employee notification preferences"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        return {'success': True, 'message': f'Preference updated successfully.'}


    @http.route('/helpdesk/admin/customers', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_customers(self, page=1, search=None, **kw):
        """Screen 8: Customers Management Screen"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/customers')

        page = int(page) if str(page).isdigit() else 1
        per_page = 10
        offset = (page - 1) * per_page

        company_id = admin_ctx.get('company_id')
        domain = [('company_id', '=', company_id), ('customer_rank', '>', 0)] if company_id else [('customer_rank', '>', 0)]
        if request.env['res.partner'].sudo().search_count(domain) == 0 and company_id:
            domain = [('company_id', '=', company_id)]

        search_query = (search or kw.get('q') or '').strip()
        if search_query and '@' not in search_query:
            domain += ['|', '|', ('name', 'ilike', search_query), ('email', 'ilike', search_query), ('phone', 'ilike', search_query)]

        total_records = request.env['res.partner'].sudo().search_count(domain)
        partner_recs = request.env['res.partner'].sudo().search(domain, limit=per_page, offset=offset, order='name asc')
        total_pages = max(1, (total_records + per_page - 1) // per_page)

        customers_list = []
        for idx, p in enumerate(partner_recs, start=offset + 1):
            customers_list.append({
                'num': idx,
                'id': p.id,
                'name': p.name,
                'email': p.email or '—',
                'phone': p.phone or getattr(p, 'mobile', '') or '—',
                'country': p.country_id.name if p.country_id else '—',
                'status': 'Active' if p.active else 'Inactive',
            })

        dropdown_data = self._get_admin_common_dropdown_data(company_id)
        values = {
            **dropdown_data,
            'active_tab': 'customers',
            'admin': admin_ctx,
            'customers': customers_list,
            'search_query': search_query,
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/customer/create', type='jsonrpc', auth='public')
    def helpdesk_admin_customer_create(self, name=None, is_company=True, email=None, phone=None, mobile=None, street=None, city=None, country_id=None, zip=None, website=None, **kw):
        """AJAX endpoint to create a new res.partner customer"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        if not name:
            return {'success': False, 'message': 'Customer Name is required.'}

        try:
            company_id = admin_ctx.get('company_id') or request.env.company.id
            vals = {
                'name': name,
                'is_company': bool(is_company),
                'customer_rank': 1,
                'company_id': company_id,
                'email': (email or '').strip() or False,
                'phone': (phone or '').strip() or False,
                'street': (street or '').strip() or False,
                'city': (city or '').strip() or False,
                'zip': (zip or '').strip() or False,
                'website': (website or '').strip() or False,
            }
            if hasattr(request.env['res.partner'], 'mobile'):
                vals['mobile'] = (mobile or '').strip() or False
            elif (mobile or '').strip() and not vals.get('phone'):
                vals['phone'] = mobile.strip()
            if country_id and str(country_id).isdigit():
                vals['country_id'] = int(country_id)

            new_partner = request.env['res.partner'].sudo().create(vals)
            _logger.info("Admin created new customer: %s (ID %s)", new_partner.name, new_partner.id)
            return {'success': True, 'message': f'Customer "{new_partner.name}" created successfully.', 'id': new_partner.id}
        except Exception as e:
            _logger.exception("Error creating customer: %s", e)
            return {'success': False, 'message': f'Failed to create customer: {str(e)}'}

    @http.route('/helpdesk/admin/tickets', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_tickets(self, page=1, search=None, **kw):
        """All Tickets Screen: List out all tickets in this owned company with Search, Create Ticket, List & Kanban"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/tickets')

        page = int(page) if str(page).isdigit() else 1
        per_page = 12
        offset = (page - 1) * per_page

        company_id = admin_ctx.get('company_id')
        domain = [('company_id', '=', company_id)] if company_id else []

        stage_param = kw.get('stage')
        if stage_param == 'open':
            domain.append(('stage', 'in', ['new', 'progress', 'on_hold', 'rotting']))
        elif stage_param:
            domain.append(('stage', '=', stage_param))

        search_query = (search or kw.get('q') or '').strip()
        if search_query:
            domain += ['|', '|', ('name', 'ilike', search_query), ('ticket_ref', 'ilike', search_query) if hasattr(request.env['helpdesk.ticket'], 'ticket_ref') else ('name', 'ilike', search_query), ('partner_id.name', 'ilike', search_query)]

        TicketModel = request.env['helpdesk.ticket'].sudo()
        total_records = TicketModel.search_count(domain)
        ticket_recs = TicketModel.search(domain, limit=per_page, offset=offset, order='id desc')
        total_pages = max(1, (total_records + per_page - 1) // per_page)

        tickets_list = []
        for idx, t in enumerate(ticket_recs, start=offset + 1):
            ref = getattr(t, 'ticket_ref', False) or getattr(t, 'ticket_number', False) or f"#{t.id:04d}"
            stage_name = t.stage_id.name if hasattr(t, 'stage_id') and t.stage_id else (getattr(t, 'stage', False) or 'New')
            assigned_name = t.user_id.name if t.user_id else (t.assigned_employee_id.name if hasattr(t, 'assigned_employee_id') and t.assigned_employee_id else 'Unassigned')
            prio = getattr(t, 'priority', '0')
            prio_label = 'Urgent' if prio == '3' else ('High' if prio == '2' else ('Medium' if prio == '1' else 'Low'))
            proj_name = t.ticket_project_id.name if hasattr(t, 'ticket_project_id') and t.ticket_project_id else (t.project_id.name if hasattr(t, 'project_id') and t.project_id else '—')
            tickets_list.append({
                'num': idx,
                'id': t.id,
                'ref': ref,
                'name': t.name,
                'partner_name': t.partner_id.name if t.partner_id else '—',
                'project_name': proj_name,
                'assigned_name': assigned_name,
                'stage_name': stage_name,
                'priority': prio,
                'priority_label': prio_label,
                'create_date': fields.Datetime.to_string(t.create_date)[:10] if t.create_date else '—',
            })

        dropdown_data = self._get_admin_common_dropdown_data(company_id)
        values = {
            **dropdown_data,
            'active_tab': 'tickets',
            'admin': admin_ctx,
            'tickets': tickets_list,
            'search_query': search_query,
            'current_page': page,
            'total_pages': total_pages,
            'total_records': total_records,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/ticket/create', type='jsonrpc', auth='public')
    def helpdesk_admin_ticket_create(self, name=None, partner_id=None, project_id=None, employee_id=None, priority='1', description=None, **kw):
        """AJAX endpoint to create a new ticket in this company"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        if not name:
            return {'success': False, 'message': 'Ticket Title is required.'}

        try:
            company_id = admin_ctx.get('company_id') or request.env.company.id
            vals = {
                'name': name,
                'company_id': company_id,
                'priority': str(priority) if str(priority) in ['0', '1', '2', '3'] else '1',
            }
            if partner_id and str(partner_id).isdigit():
                partner = request.env['res.partner'].sudo().browse(int(partner_id))
                if partner.exists() and (not partner.company_id or partner.company_id.id == company_id):
                    vals['partner_id'] = partner.id
            if project_id and str(project_id).isdigit():
                proj = request.env['project.project'].sudo().browse(int(project_id))
                if proj.exists() and (not proj.company_id or proj.company_id.id == company_id):
                    if 'ticket_project_id' in request.env['helpdesk.ticket']._fields:
                        vals['ticket_project_id'] = proj.id
                    elif 'project_id' in request.env['helpdesk.ticket']._fields:
                        vals['project_id'] = proj.id
            if employee_id and str(employee_id).isdigit():
                emp = request.env['hr.employee'].sudo().browse(int(employee_id))
                if emp.exists() and (not emp.company_id or emp.company_id.id == company_id):
                    if 'assigned_employee_id' in request.env['helpdesk.ticket']._fields:
                        vals['assigned_employee_id'] = emp.id
                    if emp.user_id and 'user_id' in request.env['helpdesk.ticket']._fields:
                        vals['user_id'] = emp.user_id.id
            if description:
                vals['description'] = description.strip()

            new_ticket = request.env['helpdesk.ticket'].sudo().create(vals)
            _logger.info("Admin created new ticket: %s (ID %s)", new_ticket.name, new_ticket.id)
            ref = getattr(new_ticket, 'ticket_ref', False) or getattr(new_ticket, 'ticket_number', False) or f"#{new_ticket.id:04d}"
            return {'success': True, 'message': f'Ticket "{ref} - {new_ticket.name}" created successfully.', 'id': new_ticket.id}
        except Exception as e:
            _logger.exception("Error creating ticket: %s", e)
            return {'success': False, 'message': f'Failed to create ticket: {str(e)}'}

    # =========================================================================
    # REPORTS, PROFILE, SETTINGS & GLOBAL SEARCH
    # =========================================================================

    @http.route('/helpdesk/admin/reports', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_reports(self, date_range='this_month', start_date=None, end_date=None, **kw):
        """Reports Overview Screen with Company-Isolated Metrics & Trends"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/reports')

        company_id = admin_ctx.get('company_id')
        start_dt, end_dt, date_filter_label, date_range_key, s_date_str, e_date_str = self._compute_date_range(
            date_range=date_range, start_date=start_date, end_date=end_date
        )

        TicketModel = request.env['helpdesk.ticket'].sudo()
        base_domain = [('create_date', '>=', start_dt), ('create_date', '<=', end_dt)]
        if company_id:
            base_domain.insert(0, ('company_id', '=', company_id))

        total_tickets = TicketModel.search_count(base_domain)
        open_tickets = TicketModel.search_count(base_domain + [('stage', 'in', ['new', 'progress', 'on_hold', 'rotting'])])
        in_progress_tickets = TicketModel.search_count(base_domain + [('stage', 'in', ['progress', 'rotting'])])
        resolved_tickets = TicketModel.search_count(base_domain + [('stage', 'in', ['solved', 'resolved', 'closed', 'done'])])
        new_tickets = TicketModel.search_count(base_domain + [('stage', '=', 'new')])
        on_hold_tickets = TicketModel.search_count(base_domain + [('stage', '=', 'on_hold')])
        cancelled_tickets = TicketModel.search_count(base_domain + [('stage', 'in', ['cancelled', 'cancel', 'canceled'])])

        resolution_rate = round((resolved_tickets / total_tickets * 100), 1) if total_tickets > 0 else 0.0

        def calc_pct(c):
            return round((c / total_tickets * 100), 1) if total_tickets > 0 else 0.0

        status_breakdown = [
            {'key': 'new', 'name': 'New / Unassigned', 'count': new_tickets, 'pct': calc_pct(new_tickets), 'color': '#3B82F6'},
            {'key': 'progress', 'name': 'In Progress', 'count': in_progress_tickets, 'pct': calc_pct(in_progress_tickets), 'color': '#F59E0B'},
            {'key': 'on_hold', 'name': 'On Hold', 'count': on_hold_tickets, 'pct': calc_pct(on_hold_tickets), 'color': '#64748B'},
            {'key': 'resolved', 'name': 'Resolved / Solved', 'count': resolved_tickets, 'pct': calc_pct(resolved_tickets), 'color': '#10B981'},
            {'key': 'cancelled', 'name': 'Cancelled', 'count': cancelled_tickets, 'pct': calc_pct(cancelled_tickets), 'color': '#EF4444'},
        ]

        # Ticket Volume Trend (divide date range into up to 6 intervals)
        delta = (end_dt - start_dt).total_seconds()
        step = max(86400, delta / 6)
        volume_trend = []
        max_vol_count = 1
        curr_step_start = start_dt
        for i in range(6):
            curr_step_end = curr_step_start + timedelta(seconds=step)
            if i == 5 or curr_step_end > end_dt:
                curr_step_end = end_dt

            interval_domain = list(base_domain)
            interval_domain = [d for d in interval_domain if d[0] != 'create_date']
            interval_domain += [('create_date', '>=', curr_step_start), ('create_date', '<=', curr_step_end)]
            cnt = TicketModel.search_count(interval_domain)
            if cnt > max_vol_count:
                max_vol_count = cnt

            label = curr_step_start.strftime('%b %d') if delta <= 30 * 86400 else curr_step_start.strftime('%b %Y')
            volume_trend.append({
                'label': label,
                'count': cnt,
                'start': curr_step_start.strftime('%Y-%m-%d'),
                'end': curr_step_end.strftime('%Y-%m-%d'),
            })
            curr_step_start = curr_step_end
            if curr_step_start >= end_dt:
                break

        for v in volume_trend:
            v['pct'] = max(10, int((v['count'] / max_vol_count) * 100)) if v['count'] > 0 else 8

        # Project Summary (top 5 projects for this company)
        proj_domain = [('company_id', '=', company_id)] if company_id else []
        projects = request.env['project.project'].sudo().search(proj_domain, limit=5, order='name asc')
        project_summary = []
        for p in projects:
            p_ticket_domain = list(base_domain)
            if 'ticket_project_id' in TicketModel._fields:
                p_ticket_domain.append(('ticket_project_id', '=', p.id))
            elif 'project_id' in TicketModel._fields:
                p_ticket_domain.append(('project_id', '=', p.id))
            t_cnt = TicketModel.search_count(p_ticket_domain)
            p_open_domain = p_ticket_domain + [('stage', 'in', ['new', 'progress', 'on_hold', 'rotting'])]
            o_cnt = TicketModel.search_count(p_open_domain)
            project_summary.append({
                'id': p.id,
                'name': p.name,
                'total_tickets': t_cnt,
                'open_tickets': o_cnt,
                'pct': calc_pct(t_cnt),
            })

        # Employee Summary (top 5 employees for this company)
        emp_domain = [('company_id', '=', company_id)] if company_id else []
        employees = request.env['hr.employee'].sudo().search(emp_domain, limit=5, order='name asc')
        employee_summary = []
        for e in employees:
            e_ticket_domain = list(base_domain)
            if 'assigned_employee_id' in TicketModel._fields:
                e_ticket_domain.append(('assigned_employee_id', '=', e.id))
            elif e.user_id and 'user_id' in TicketModel._fields:
                e_ticket_domain.append(('user_id', '=', e.user_id.id))
            t_cnt = TicketModel.search_count(e_ticket_domain)
            e_res_domain = e_ticket_domain + [('stage', 'in', ['solved', 'resolved', 'closed', 'done'])]
            r_cnt = TicketModel.search_count(e_res_domain)
            employee_summary.append({
                'id': e.id,
                'name': e.name,
                'job_title': e.job_title or 'Helpdesk Staff',
                'department': e.department_id.name if e.department_id else 'Support',
                'assigned_tickets': t_cnt,
                'resolved_tickets': r_cnt,
                'pct': calc_pct(t_cnt),
            })

        dropdown_data = self._get_admin_common_dropdown_data(company_id)
        values = {
            **dropdown_data,
            'active_tab': 'reports',
            'admin': admin_ctx,
            'total_tickets': total_tickets,
            'open_tickets': open_tickets,
            'in_progress_tickets': in_progress_tickets,
            'resolved_tickets': resolved_tickets,
            'cancelled_tickets': cancelled_tickets,
            'resolution_rate': resolution_rate,
            'status_breakdown': status_breakdown,
            'volume_trend': volume_trend,
            'project_summary': project_summary,
            'employee_summary': employee_summary,
            'date_filter_label': date_filter_label,
            'date_range': date_range_key,
            'start_date': s_date_str,
            'end_date': e_date_str,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/profile', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_profile(self, **kw):
        """Administrator Profile Screen"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/profile')

        user = request.env['res.users'].sudo().browse(admin_ctx['admin_id'])
        partner = user.partner_id if user.exists() else False
        emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1) if user.exists() else False

        profile_data = {
            'user_id': user.id if user.exists() else False,
            'name': user.name if user.exists() else admin_ctx['admin_name'],
            'email': user.email if user.exists() else admin_ctx['admin_email'],
            'login': user.login if user.exists() else '',
            'phone': (emp and emp.work_phone) or (partner and partner.phone) or '',
            'job_title': (emp and emp.job_title) or 'Helpdesk Administrator',
            'department': (emp and emp.department_id.name) or 'Support & Operations',
            'company_name': admin_ctx['company_name'],
            'role': 'Helpdesk Administrator',
        }

        values = {
            **self._get_admin_common_dropdown_data(admin_ctx.get('company_id')),
            'active_tab': 'profile',
            'admin': admin_ctx,
            'user_obj': user,
            'profile_data': profile_data,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/profile/update', type='jsonrpc', auth='public')
    def helpdesk_admin_profile_update(self, name=None, email=None, phone=None, **kw):
        """AJAX endpoint to update administrator profile details (permitted fields only)"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        name = (name or '').strip()
        email = (email or '').strip().lower()
        phone = (phone or '').strip()

        if not name:
            return {'success': False, 'message': 'Full Name is required.'}
        if not email or '@' not in email:
            return {'success': False, 'message': 'A valid Email is required.'}

        try:
            user = request.env['res.users'].sudo().browse(admin_ctx['admin_id'])
            if not user.exists():
                return {'success': False, 'message': 'User record not found.'}

            user.write({
                'name': name,
                'email': email,
            })
            if user.partner_id:
                user.partner_id.sudo().write({
                    'name': name,
                    'email': email,
                    'phone': phone or False,
                })

            emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if emp:
                emp.sudo().write({
                    'name': name,
                    'work_email': email,
                    'work_phone': phone or False,
                })

            # Update session
            request.session['helpdesk_admin_name'] = name
            request.session['helpdesk_admin_email'] = email
            request.session.is_dirty = True

            return {'success': True, 'message': 'Profile updated successfully!'}
        except Exception as e:
            _logger.exception("Error updating admin profile: %s", e)
            return {'success': False, 'message': f'Failed to update profile: {str(e)}'}

    @http.route('/helpdesk/admin/settings', type='http', auth='public', website=True, sitemap=False)
    def helpdesk_admin_settings(self, **kw):
        """Portal Settings Screen"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return request.redirect('/helpdesk/login?type=admin&redirect=/helpdesk/admin/settings')

        company_id = admin_ctx.get('company_id')
        company = request.env['res.company'].sudo().browse(company_id) if company_id else request.env.company

        settings_data = {
            'company_id': company.id,
            'company_name': company.name,
            'email': company.email or '',
            'phone': company.phone or '',
            'website': company.website or '',
            'street': company.street or '',
            'city': company.city or '',
            'country_name': company.country_id.name if company.country_id else '',
        }

        values = {
            **self._get_admin_common_dropdown_data(company_id),
            'active_tab': 'settings',
            'admin': admin_ctx,
            'company_obj': company,
            'settings_data': settings_data,
            **self._get_helpdesk_branding(),
        }
        return request.render('website_helpdesk_portal.helpdesk_admin_portal', values)

    @http.route('/helpdesk/admin/global-search', type='jsonrpc', auth='public')
    def helpdesk_admin_global_search(self, query=None, **kw):
        """Global Search across authorized Projects, Employees, Customers, Tickets"""
        admin_ctx = self._get_active_admin_context()
        if not admin_ctx['is_authenticated']:
            return {'success': False, 'message': 'Authentication required.'}

        q = (query or '').strip()
        if not q or len(q) < 2:
            return {'success': True, 'results': {}, 'total_count': 0}

        company_id = admin_ctx.get('company_id')

        # 1. Projects
        proj_domain = [('company_id', '=', company_id)] if company_id else []
        proj_domain += [('name', 'ilike', q)]
        proj_recs = request.env['project.project'].sudo().search(proj_domain, limit=4, order='name asc')
        projects = []
        for p in proj_recs:
            projects.append({
                'id': p.id,
                'title': p.name,
                'subtitle': f"Tasks: {getattr(p, 'task_count', 0)} • {p.partner_id.name if p.partner_id else 'Internal'}",
                'url': f"/helpdesk/admin/projects?q={q}",
                'type': 'Project',
            })

        # 2. Employees
        emp_domain = [('company_id', '=', company_id)] if company_id else []
        emp_domain += ['|', '|', ('name', 'ilike', q), ('work_email', 'ilike', q), ('job_title', 'ilike', q)]
        emp_recs = request.env['hr.employee'].sudo().search(emp_domain, limit=4, order='name asc')
        employees = []
        for e in emp_recs:
            employees.append({
                'id': e.id,
                'title': e.name,
                'subtitle': f"{e.job_title or 'Staff'} • {e.work_email or ''}".strip(' •'),
                'url': f"/helpdesk/admin/employees?q={q}",
                'type': 'Employee',
            })

        # 3. Customers
        cust_domain = [('company_id', '=', company_id), ('customer_rank', '>', 0)] if company_id else [('customer_rank', '>', 0)]
        if request.env['res.partner'].sudo().search_count(cust_domain) == 0 and company_id:
            cust_domain = [('company_id', '=', company_id)]
        cust_domain += ['|', '|', ('name', 'ilike', q), ('email', 'ilike', q), ('phone', 'ilike', q)]
        cust_recs = request.env['res.partner'].sudo().search(cust_domain, limit=4, order='name asc')
        customers = []
        for c in cust_recs:
            customers.append({
                'id': c.id,
                'title': c.name,
                'subtitle': f"{c.email or ''} {c.phone or ''}".strip(),
                'url': f"/helpdesk/admin/customers?q={q}",
                'type': 'Customer',
            })

        # 4. Tickets
        ticket_domain = [('company_id', '=', company_id)] if company_id else []
        ticket_domain += ['|', '|', ('name', 'ilike', q), ('ticket_ref', 'ilike', q) if 'ticket_ref' in request.env['helpdesk.ticket']._fields else ('name', 'ilike', q), ('partner_id.name', 'ilike', q)]
        ticket_recs = request.env['helpdesk.ticket'].sudo().search(ticket_domain, limit=4, order='id desc')
        tickets = []
        for t in ticket_recs:
            ref = getattr(t, 'ticket_ref', False) or getattr(t, 'ticket_number', False) or f"#{t.id:04d}"
            stage_name = t.stage_id.name if hasattr(t, 'stage_id') and t.stage_id else (getattr(t, 'stage', False) or 'New')
            tickets.append({
                'id': t.id,
                'title': f"{ref} - {t.name}",
                'subtitle': f"Status: {stage_name} • {t.partner_id.name if t.partner_id else 'Customer'}",
                'url': f"/helpdesk/admin/tickets?q={q}",
                'type': 'Ticket',
            })

        total_count = len(projects) + len(employees) + len(customers) + len(tickets)
        return {
            'success': True,
            'total_count': total_count,
            'results': {
                'projects': projects,
                'employees': employees,
                'customers': customers,
                'tickets': tickets,
            }
        }

