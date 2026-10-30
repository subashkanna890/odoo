# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HelpdeskSupportTeamContact(models.Model):
    _name = 'helpdesk.support.team.contact'
    _description = 'Helpdesk Support Team Contact'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    team_id = fields.Many2one('helpdesk.team', string='Helpdesk Support Team', required=True, ondelete='cascade')
    mobile = fields.Char(string='Mobile')
    email = fields.Char(string='Email')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
