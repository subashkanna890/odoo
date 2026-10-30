from datetime import timedelta

from odoo import _, http
from odoo.http import request

from .base import clean_email, client_ip, send_mail, system_param, valid_email

DEMO_PER_HOUR = 5
FIELD_LIMITS = {'name': 120, 'email': 160, 'company': 160, 'team_size': 20, 'message': 2000}


class DeskPublic(http.Controller):

    @http.route('/aixo-desk/demo', type='http', auth='public', website=True, sitemap=False,
                methods=['GET', 'POST'])
    def demo_page(self, **kw):
        values = {'form': {}, 'error': False, 'done': False, 'name': ''}
        if request.httprequest.method == 'POST':
            form = self._clean(kw)
            error = self._create_request(form, honeypot=kw.get('website_url'))
            values.update(form=form, error=error, done=not error, name=form['name'].split(' ')[0])
        return request.render('aixo_desk.demo_page', values)

    @http.route('/desk/api/demo-request', type='jsonrpc', auth='public', website=True)
    def demo_request(self, **kw):
        form = self._clean(kw)
        error = self._create_request(form, honeypot=kw.get('website_url'))
        if error:
            return {'ok': False, 'error': error}
        return {'ok': True, 'data': {'name': form['name'].split(' ')[0]}}

    def _clean(self, raw):
        form = {key: str(raw.get(key) or '').strip()[:limit] for key, limit in FIELD_LIMITS.items()}
        form['email'] = clean_email(form['email'])
        return form

    def _create_request(self, form, honeypot=None):
        """Validate, store and announce a demo request. Returns an error message or None."""
        if honeypot:
            return None  # bots fill the hidden field; pretend success without storing anything
        if not form['name']:
            return _("Enter your name.")
        if not valid_email(form['email']):
            return _("Enter a valid work email.")
        if request.env['aixo.rate.limit'].hit('demo', client_ip(), DEMO_PER_HOUR,
                                              window=timedelta(hours=1), lock=timedelta(hours=1)):
            return _("Too many requests from this network. Please try again later.")
        request.env['aixo.demo.request'].sudo().create({
            'name': form['name'], 'email': form['email'], 'company': form['company'],
            'team_size': form['team_size'], 'message': form['message'],
        })
        sales = system_param('support_email') or request.env.company.email
        if sales:
            send_mail(sales, _("New Aixo Desk demo request: %s", form['company'] or form['name']),
                      'aixo_desk.mail_demo_notify', form, reply_to=form['email'])
        return None
