# -*- coding: utf-8 -*-
import base64
import logging
import io
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

try:
    import docx
except ImportError:
    docx = None

try:
    import pypdf
except ImportError:
    pypdf = None


class HelpdeskAiKnowledge(models.Model):
    _name = 'helpdesk.ai.knowledge'
    _description = 'Helpdesk AI Knowledge Base Document'
    _order = 'sequence, write_date desc, id desc'

    name = fields.Char(string='Document Title', required=True, index=True)
    document_type = fields.Selection([
        ('faq', 'FAQ / Troubleshooting Guide'),
        ('manual', 'Product / Technical Manual'),
        ('sop', 'Internal SOP / Policy'),
        ('resolved_ticket', 'Resolved Ticket Solution Summary'),
        ('project_doc', 'Project Documentation'),
        ('general', 'General Knowledge / Article'),
    ], string='Document Type', default='faq', required=True)

    access_scope = fields.Selection([
        ('public', 'Public (Customer & Employee)'),
        ('employee', 'Internal (Employee & Agent Only)'),
        ('project_manager', 'Restricted (Project Manager Only)'),
    ], string='Access Scope', default='employee', required=True, index=True,
       help='Security level restricting which assistant role is authorized to retrieve this document.')

    content = fields.Text(string='Plain Text / Markdown Content', help='Cleaned, normalized searchable text.')
    
    file_attachment = fields.Binary(string='Upload Document File (PDF / DOCX / TXT / MD)')
    file_name = fields.Char(string='File Name')
    file_mimetype = fields.Char(string='File MIME Type')

    source_url = fields.Char(string='Reference Link / URL')
    ticket_id = fields.Many2one('website.helpdesk.ticket', string='Related Ticket', ondelete='set null')
    project_id = fields.Many2one('project.project', string='Related Project', ondelete='set null')
    
    is_indexed = fields.Boolean(string='Is Indexed', default=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.file_attachment and not rec.content:
                rec._extract_text_from_attachment()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'file_attachment' in vals:
            for rec in self:
                rec._extract_text_from_attachment()
        return res

    def _extract_text_from_attachment(self):
        """Extract text from PDF, DOCX, TXT, or MD attachments safely."""
        self.ensure_one()
        if not self.file_attachment:
            return
        
        extracted_text = ""
        try:
            raw_bytes = base64.b64decode(self.file_attachment)
            fname = (self.file_name or '').lower()

            if fname.endswith('.pdf') and pypdf:
                reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
                pages_text = []
                for p in reader.pages[:40]:  # Cap at 40 pages for speed & safety
                    t = p.extract_text() or ''
                    if t.strip():
                        pages_text.append(t.strip())
                extracted_text = "\n\n".join(pages_text)

            elif (fname.endswith('.docx') or fname.endswith('.doc')) and docx:
                doc = docx.Document(io.BytesIO(raw_bytes))
                paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                extracted_text = "\n\n".join(paragraphs)

            elif fname.endswith('.txt') or fname.endswith('.md') or fname.endswith('.html'):
                extracted_text = raw_bytes.decode('utf-8', errors='ignore')

        except Exception as e:
            _logger.warning("Failed to extract text from attachment for AI Knowledge %s: %s", self.id, e)

        if extracted_text.strip():
            self.content = extracted_text.strip()
            self.is_indexed = True


class HelpdeskAiConversation(models.Model):
    _name = 'helpdesk.ai.conversation'
    _description = 'Helpdesk AI Assistant Conversation'
    _order = 'write_date desc, id desc'

    conversation_token = fields.Char(string='Conversation ID', required=True, index=True, copy=False)
    title = fields.Char(string='Title / Subject', default='New Conversation')
    
    role = fields.Selection([
        ('customer', 'Customer'),
        ('employee', 'Employee / Agent'),
        ('project_manager', 'Project Manager'),
    ], string='Role', required=True, default='employee')

    partner_id = fields.Many2one('res.partner', string='Customer Owner', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee Owner', ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Odoo User', ondelete='cascade', index=True)

    message_ids = fields.One2many('helpdesk.ai.message', 'conversation_id', string='Messages')
    active = fields.Boolean(string='Active', default=True)


class HelpdeskAiMessage(models.Model):
    _name = 'helpdesk.ai.message'
    _description = 'Helpdesk AI Assistant Message'
    _order = 'create_date asc, id asc'

    conversation_id = fields.Many2one('helpdesk.ai.conversation', string='Conversation', required=True, ondelete='cascade', index=True)
    sender = fields.Selection([
        ('user', 'User'),
        ('assistant', 'Helpdesk AI Assistant'),
        ('system', 'System Context'),
    ], string='Sender', required=True, default='user')

    content = fields.Text(string='Message Content', required=True)
    model_used = fields.Char(string='Model Used')
    sources = fields.Text(string='Citations & Sources JSON')
    actions = fields.Text(string='Actions JSON')
