import csv
import io
from datetime import timedelta

import xlsxwriter

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request

from .admin import admin_agents
from .api import avatar, desk_api
from .base import desk_page

PERIODS = (7, 30, 90)
CSAT_SCORE = {'good': 5.0, 'okay': 3.0, 'bad': 1.0}
FIELDS = ['partner_id', 'owner_id', 'state', 'create_date', 'closed_on', 'responded_on',
          'first_response_deadline', 'rating', 'is_overdue']
SLA_TARGET = 90


def duration_label(seconds):
    if seconds is None:
        return '—'
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def days_label(seconds):
    return '—' if seconds is None else f"{seconds / 86400:.1f} days"


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def window_tickets(start, end):
    """Tickets created or closed inside [start, end) as the (admin) caller can read them."""
    Ticket = request.env['aixo.ticket']
    return Ticket.search_fetch(
        ['|', '&', ('create_date', '>=', start), ('create_date', '<', end),
         '&', ('closed_on', '>=', start), ('closed_on', '<', end)], FIELDS)


def created_in(tickets, start, end):
    return tickets.filtered(lambda t: start <= t.create_date < end)


def closed_in(tickets, start, end):
    return tickets.filtered(lambda t: t.closed_on and start <= t.closed_on < end)


def first_reply_seconds(tickets):
    return mean((t.responded_on - t.create_date).total_seconds() for t in tickets if t.responded_on)


def sla_met(tickets, now):
    """Share (0-100) of tickets that were answered within the first response deadline."""
    due = tickets.filtered(lambda t: t.first_response_deadline and (t.responded_on or t.first_response_deadline < now))
    if not due:
        return None
    met = due.filtered(lambda t: t.responded_on and t.responded_on <= t.first_response_deadline)
    return round(len(met) * 100 / len(due))


def csat(tickets):
    value = mean(CSAT_SCORE[t.rating] for t in tickets if t.rating)
    return None if value is None else round(value, 1)


def trend(current, previous, kind, better='up'):
    """(text, good) for the KPI card, comparing with the previous period."""
    if current is None or previous is None:
        return _("No previous data"), None
    if kind == 'count':
        if previous == 0:
            return (_("New") if current else _("No change")), current > 0 if better == 'up' else None
        pct = round((current - previous) * 100 / previous)
        text = _("%(sign)s%(pct)s%% vs previous", sign='+' if pct >= 0 else '−', pct=abs(pct))
        delta = pct
    elif kind == 'seconds':
        minutes = round((current - previous) / 60)
        text = _("%(sign)s%(n)s min vs previous", sign='+' if minutes >= 0 else '−', n=abs(minutes))
        delta = minutes
    elif kind == 'points':
        points = round(current - previous)
        text = _("%(sign)s%(n)s pts vs previous", sign='+' if points >= 0 else '−', n=abs(points))
        delta = points
    else:  # float
        diff = round(current - previous, 1)
        text = _("Stable") if diff == 0 else _("%(sign)s%(n)s vs previous", sign='+' if diff > 0 else '−', n=abs(diff))
        delta = diff
    if delta == 0:
        return text, None
    return text, (delta > 0) == (better == 'up')


def report_data(tab, days):
    """The numbers behind both the screen and the exports."""
    if days not in PERIODS:
        raise UserError(_("Unknown period."))
    now = fields.Datetime.now()
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    tickets = window_tickets(prev_start, now)
    cur_created, prev_created = created_in(tickets, start, now), created_in(tickets, prev_start, start)
    cur_closed, prev_closed = closed_in(tickets, start, now), closed_in(tickets, prev_start, start)
    env = request.env
    if tab == 'emp':
        return _employee_report(env, tickets, cur_created, prev_created, cur_closed, prev_closed, start, now, prev_start)
    return _customer_report(env, tickets, cur_created, prev_created, cur_closed, prev_closed, start, now)


def _employee_report(env, tickets, cur_created, prev_created, cur_closed, prev_closed, start, now, prev_start):
    assigned = cur_created.filtered('owner_id')
    prev_assigned = prev_created.filtered('owner_id')
    fr, prev_fr = first_reply_seconds(assigned), first_reply_seconds(prev_assigned)
    sla, prev_sla = sla_met(assigned, now), sla_met(prev_assigned, start)
    cards = [
        {'label': _("Tickets assigned"), 'value': len(assigned), 'trend': trend(len(assigned), len(prev_assigned), 'count')},
        {'label': _("Tickets resolved"), 'value': len(cur_closed), 'trend': trend(len(cur_closed), len(prev_closed), 'count')},
        {'label': _("Avg. first reply"), 'value': duration_label(fr), 'trend': trend(fr, prev_fr, 'seconds', better='down')},
        {'label': _("SLA met"), 'value': '—' if sla is None else f"{sla}%", 'trend': trend(sla, prev_sla, 'points')},
    ]
    rows = []
    for agent in admin_agents().filtered('active'):
        mine = assigned.filtered(lambda t: t.owner_id == agent)
        done = cur_closed.filtered(lambda t: t.owner_id == agent)
        a_sla = sla_met(mine, now)
        rows.append({
            'agent': avatar(agent), 'team': agent.desk_team_ids[:1].name or '', 'assigned': len(mine), 'resolved': len(done),
            'first_reply': duration_label(first_reply_seconds(mine)), 'sla': a_sla, 'csat': csat(done),
        })
    rows.sort(key=lambda r: -r['assigned'])
    return {'tab': 'emp', 'cards': [_card(c) for c in cards], 'rows': rows, 'target': SLA_TARGET}


def _customer_report(env, tickets, cur_created, prev_created, cur_closed, prev_closed, start, now):
    res = [(t.closed_on - t.create_date).total_seconds() for t in cur_closed]
    prev_res = [(t.closed_on - t.create_date).total_seconds() for t in prev_closed]
    active = len(cur_created.mapped('partner_id'))
    prev_active = len(prev_created.mapped('partner_id'))
    avg_res, prev_avg_res = mean(res), mean(prev_res)
    score, prev_score = csat(cur_closed), csat(prev_closed)
    cards = [
        {'label': _("Active customers"), 'value': active, 'trend': trend(active, prev_active, 'count')},
        {'label': _("Tickets raised"), 'value': len(cur_created), 'trend': trend(len(cur_created), len(prev_created), 'count')},
        {'label': _("Avg. resolution"), 'value': days_label(avg_res), 'trend': trend(
            None if avg_res is None else avg_res / 86400, None if prev_avg_res is None else prev_avg_res / 86400, 'float', better='down')},
        {'label': _("Customer CSAT"), 'value': '—' if score is None else f"{score} / 5", 'trend': trend(score, prev_score, 'float')},
    ]
    rows = []
    for partner in cur_created.mapped('partner_id'):
        mine = cur_created.filtered(lambda t: t.partner_id == partner)
        closed = mine.filtered(lambda t: t.state == 'closed')
        plan = (partner.commercial_partner_id or partner).desk_plan or 'free'
        rows.append({
            'name': partner.name, 'company': partner.parent_id.name or '', 'tickets': len(mine),
            'open': len(mine) - len(closed),
            'resolution': days_label(mean((t.closed_on - t.create_date).total_seconds() for t in closed if t.closed_on)),
            'csat': csat(closed), 'plan': plan, 'plan_label': 'Paid' if plan == 'paid' else 'Free',
        })
    rows.sort(key=lambda r: -r['tickets'])
    return {'tab': 'cust', 'cards': [_card(c) for c in cards], 'rows': rows[:50]}


def _card(card):
    text, good = card['trend']
    return {'label': card['label'], 'value': card['value'], 'trend': text, 'good': good}


def table_for_export(data):
    if data['tab'] == 'emp':
        head = ['Employee', 'Team', 'Assigned', 'Resolved', 'First reply', 'SLA met %', 'CSAT']
        body = [[r['agent']['name'], r['team'], r['assigned'], r['resolved'], r['first_reply'],
                 '' if r['sla'] is None else r['sla'], '' if r['csat'] is None else r['csat']] for r in data['rows']]
    else:
        head = ['Customer', 'Company', 'Tickets', 'Open', 'Avg. resolution', 'CSAT', 'Plan']
        body = [[r['name'], r['company'], r['tickets'], r['open'], r['resolution'],
                 '' if r['csat'] is None else r['csat'], r['plan_label']] for r in data['rows']]
    summary = [[c['label'], c['value'], c['trend']] for c in data['cards']]
    return head, body, summary


def safe_cell(value):
    """Neutralise spreadsheet formula injection in text that came from users."""
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


class DeskReports(http.Controller):

    @http.route('/desk/api/admin/reports', type='jsonrpc', auth='public')
    @desk_api(roles=['admin'])
    def reports(self, tab='emp', days=7, **kw):
        return report_data('cust' if tab == 'cust' else 'emp', int(days))

    @http.route('/desk/admin/reports/export.<string:fmt>', type='http', auth='public', website=True, sitemap=False)
    @desk_page(roles=['admin'])
    def export(self, fmt, tab='emp', days='7', **kw):
        if fmt not in ('xlsx', 'csv') or not str(days).isdigit():
            raise request.not_found()
        try:
            data = report_data('cust' if tab == 'cust' else 'emp', int(days))
        except UserError:
            raise request.not_found()
        head, body, summary = table_for_export(data)
        name = f"aixo-{'employee' if data['tab'] == 'emp' else 'customer'}-report-{days}d"
        if fmt == 'csv':
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(['Metric', 'Value', 'Trend'])
            writer.writerows([[safe_cell(c) for c in row] for row in summary])
            writer.writerow([])
            writer.writerow(head)
            writer.writerows([[safe_cell(c) for c in row] for row in body])
            return request.make_response('﻿' + out.getvalue(), headers=[
                ('Content-Type', 'text/csv; charset=utf-8'),
                ('Content-Disposition', f'attachment; filename="{name}.csv"')])
        buffer = io.BytesIO()
        book = xlsxwriter.Workbook(buffer, {'in_memory': True, 'strings_to_formulas': False})
        sheet = book.add_worksheet('Report')
        bold = book.add_format({'bold': True, 'bg_color': '#EAF6D8'})
        for col, title in enumerate(['Metric', 'Value', 'Trend']):
            sheet.write(0, col, title, bold)
        for row, line in enumerate(summary, start=1):
            for col, cell in enumerate(line):
                sheet.write(row, col, cell)
        top = len(summary) + 2
        for col, title in enumerate(head):
            sheet.write(top, col, title, bold)
        for row, line in enumerate(body, start=top + 1):
            for col, cell in enumerate(line):
                sheet.write(row, col, cell)
        sheet.set_column(0, len(head), 22)
        book.close()
        return request.make_response(buffer.getvalue(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', f'attachment; filename="{name}.xlsx"')])
