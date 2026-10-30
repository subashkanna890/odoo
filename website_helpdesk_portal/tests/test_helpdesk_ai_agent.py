# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from datetime import datetime, timedelta
from ..controllers.ai_agent import HelpdeskAiAgentService


class TestHelpdeskAiAgent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Setup test partners, employees, projects, tickets
        cls.customer_partner = cls.env['res.partner'].create({
            'name': 'Test Customer Alpha',
            'email': 'customer_alpha@example.com',
            'phone': '+1234567890',
        })
        cls.other_partner = cls.env['res.partner'].create({
            'name': 'Other Customer Beta',
            'email': 'customer_beta@example.com',
        })

        cls.test_employee = cls.env['hr.employee'].create({
            'name': 'Agent Sarah',
            'work_email': 'sarah@example.com',
        })

        cls.test_project = cls.env['project.project'].create({
            'name': 'Cloud Portal Migration',
            'employee_id': cls.test_employee.id,
        })

        # Create active tickets
        cls.ticket_open = cls.env['helpdesk.ticket'].create({
            'name': 'Login 2FA Error',
            'partner_id': cls.customer_partner.id,
            'ticket_project_id': cls.test_project.id,
            'assigned_employee_id': cls.test_employee.id,
            'stage': 'new',
            'priority': '2',
            'category': 'technical',
        })

        cls.ticket_overdue = cls.env['helpdesk.ticket'].create({
            'name': 'Database Timeout Crisis',
            'partner_id': cls.customer_partner.id,
            'ticket_project_id': cls.test_project.id,
            'assigned_employee_id': cls.test_employee.id,
            'stage': 'rotting',
            'priority': '3',
            'category': 'technical',
            'create_date': datetime.now() - timedelta(hours=50),
        })

        # Knowledge article
        cls.kb_article = cls.env['helpdesk.ai.knowledge'].create({
            'name': 'VPN & SSO Troubleshooting Guide',
            'document_type': 'faq',
            'access_scope': 'employee',
            'content': 'Step 1: Check your network adapter. Step 2: Clear cached credentials.',
            'is_indexed': True,
        })

    def test_01_customer_ticket_isolation(self):
        """Test that customer role can only see their own tickets."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='customer',
            current_partner=self.customer_partner
        )
        res = service.search_tickets()
        t_ids = [t['id'] for t in res['tickets']]
        self.assertIn(self.ticket_open.id, t_ids)
        self.assertIn(self.ticket_overdue.id, t_ids)

        # Other customer should not see customer alpha's tickets
        service_other = HelpdeskAiAgentService(
            env=self.env,
            role='customer',
            current_partner=self.other_partner
        )
        res_other = service_other.search_tickets()
        self.assertEqual(res_other['count'], 0)

    def test_02_overdue_tickets_detection(self):
        """Test overdue ticket filtering and calculations."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        res = service.search_tickets(overdue_only=True)
        overdue_ids = [t['id'] for t in res['tickets']]
        self.assertIn(self.ticket_overdue.id, overdue_ids)

    def test_03_ticket_details_and_screen_action(self):
        """Test retrieving ticket details triggers screen sync."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        res = service.get_ticket_details(str(self.ticket_open.id))
        self.assertTrue(res['found'])
        self.assertEqual(res['ticket']['name'], 'Login 2FA Error')
        self.assertEqual(res['ticket']['trigger_action']['type'], 'open_ticket')
        self.assertEqual(res['ticket']['trigger_action']['ticket_id'], self.ticket_open.id)

    def test_04_project_summary(self):
        """Test project summary generation."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='project_manager',
            current_emp=self.test_employee
        )
        res = service.get_project_summary(self.test_project.name)
        self.assertTrue(res['found'])
        self.assertGreaterEqual(res['total_tickets'], 2)
        self.assertGreaterEqual(res['overdue_tickets'], 1)

    def test_05_customer_search_authorization(self):
        """Test customer search is restricted to internal staff only."""
        customer_service = HelpdeskAiAgentService(
            env=self.env,
            role='customer',
            current_partner=self.customer_partner
        )
        res_cust = customer_service.search_customers('Alpha')
        self.assertIn('error', res_cust)

        employee_service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        res_emp = employee_service.search_customers('Alpha')
        self.assertGreaterEqual(res_emp['count'], 1)
        self.assertEqual(res_emp['customers'][0]['name'], 'Test Customer Alpha')

    def test_06_knowledge_scope_enforcement(self):
        """Test knowledge document access scope restrictions."""
        # Customer should NOT see employee-only doc
        customer_service = HelpdeskAiAgentService(
            env=self.env,
            role='customer',
            current_partner=self.customer_partner
        )
        res_cust = customer_service.search_helpdesk_documentation('VPN')
        titles_cust = [a['title'] for a in res_cust['articles']]
        self.assertNotIn('VPN & SSO Troubleshooting Guide', titles_cust)

        # Employee CAN see employee doc
        employee_service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        res_emp = employee_service.search_helpdesk_documentation('VPN')
        titles_emp = [a['title'] for a in res_emp['articles']]
        self.assertIn('VPN & SSO Troubleshooting Guide', titles_emp)

    def test_07_ticket_creation_draft_and_execution(self):
        """Test ticket creation preview card followed by execution."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        # 1. Draft preview
        draft = service.draft_ticket_creation(
            name='Payment Gateway Timeout',
            description='Transactions failing on Stripe webhook',
            category='billing',
            priority='2'
        )
        self.assertEqual(draft['status'], 'preview_ready')
        self.assertEqual(draft['preview']['name'], 'Payment Gateway Timeout')

        # 2. Execution
        created = service.create_ticket(
            name='Payment Gateway Timeout',
            description='Transactions failing on Stripe webhook',
            category='billing',
            priority='2'
        )
        self.assertTrue(created['success'])
        self.assertTrue(created['ticket_id'])
        self.assertIn('#', created['ticket_number'])

    def test_08_semantic_intent_execution(self):
        """Test natural language questions return structured live data responses."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        # Overdue tickets query
        reply, act, prev, sources = service.execute_semantic_intent("Which tickets are overdue?")
        self.assertIn('Overdue', reply)
        self.assertIn('Database Timeout Crisis', reply)

        # Project summary query
        reply_p, _, _, _ = service.execute_semantic_intent("Summarize my current projects")
        self.assertIn('Cloud Portal Migration', reply_p)

        # Capabilities query
        reply_c, _, _, _ = service.execute_semantic_intent("What can you do in this Helpdesk portal?")
        self.assertIn('Live Ticket Management', reply_c)

    def test_09_summarize_ticket(self):
        """Test ticket summarization with explicit ref and active_ticket_id context."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee,
            active_ticket_id=self.ticket_open.id
        )
        # Contextual summary without passing ticket_ref
        summary_ctx = service.summarize_ticket()
        self.assertTrue(summary_ctx.get('found'))
        self.assertEqual(summary_ctx.get('ticket', {}).get('id'), self.ticket_open.id)
        self.assertEqual(summary_ctx.get('ticket', {}).get('name'), 'Login 2FA Error')
        self.assertIn('Summary of Ticket', summary_ctx.get('summary', ''))

        # Explicit ref summary
        summary_ref = service.summarize_ticket(ticket_id_or_number=str(self.ticket_overdue.id))
        self.assertTrue(summary_ref.get('found'))
        self.assertEqual(summary_ref.get('ticket', {}).get('id'), self.ticket_overdue.id)
        self.assertEqual(summary_ref.get('ticket', {}).get('name'), 'Database Timeout Crisis')

    def test_10_draft_customer_reply(self):
        """Test drafting grounded customer response requiring human verification."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee,
            active_ticket_id=self.ticket_open.id
        )
        res = service.draft_customer_reply(instructions='Provide workaround for 2FA token sync')
        self.assertTrue(res.get('found'))
        draft_text = res.get('reply_draft', '')
        self.assertIn('Draft Customer Reply', draft_text)
        self.assertIn('Agent Verification Required', draft_text)
        self.assertIn('Test Customer Alpha', draft_text)

    def test_11_help_resolve_customer_issue(self):
        """Test issue resolution guidance with SOP and knowledge base links."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee,
            active_ticket_id=self.ticket_open.id
        )
        res = service.help_resolve_customer_issue(issue_text='VPN and network authentication login issue')
        self.assertTrue(res.get('found'))
        self.assertIn('Resolution Assistance', res.get('reply', ''))
        sources = res.get('sources', [])
        # Should link our VPN guide created in setUpClass
        self.assertTrue(any('VPN' in s.get('title', '') for s in sources))

    def test_12_find_similar_tickets(self):
        """Test finding similar resolved tickets."""
        # Create a resolved ticket
        ticket_solved = self.env['helpdesk.ticket'].create({
            'name': '2FA Login Device Token Desync',
            'partner_id': self.customer_partner.id,
            'ticket_project_id': self.test_project.id,
            'assigned_employee_id': self.test_employee.id,
            'stage': 'solved',
            'priority': '2',
            'category': 'technical',
            'resolution_notes': 'Resynced authenticator seed in IAM service',
        })
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee,
            active_ticket_id=self.ticket_open.id
        )
        res = service.find_similar_tickets()
        self.assertGreaterEqual(res.get('count', 0), 1)
        similar_ids = [t['id'] for t in res.get('tickets', [])]
        self.assertIn(ticket_solved.id, similar_ids)

    def test_13_analyze_unresolved_tickets(self):
        """Test analyzing unresolved tickets triage advice."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee
        )
        res = service.analyze_unresolved_tickets()
        self.assertGreaterEqual(res.get('total_open', 0), 2)
        self.assertGreaterEqual(res.get('overdue_count', 0), 1)
        self.assertIn('Analysis of Unresolved Helpdesk Tickets', res.get('analysis_text', ''))

    def test_14_zendesk_copilot_semantic_prompts(self):
        """Test execution of the 6 Zendesk Copilot suggested prompts."""
        service = HelpdeskAiAgentService(
            env=self.env,
            role='employee',
            current_emp=self.test_employee,
            active_ticket_id=self.ticket_open.id
        )
        # 1. Summarize a ticket
        rep1, act1, _, _ = service.execute_semantic_intent("Summarize a ticket")
        self.assertIn('Summary for Ticket', rep1)
        self.assertIn('Login 2FA Error', rep1)

        # 2. Draft a customer reply
        rep2, _, prev2, _ = service.execute_semantic_intent("Draft a customer reply")
        self.assertIn('Drafted Customer Reply', rep2)
        self.assertIsNotNone(prev2)

        # 3. Help me resolve a customer issue
        rep3, _, _, _ = service.execute_semantic_intent("Help me resolve a customer issue")
        self.assertIn('Troubleshooting and Resolution Guide', rep3)

        # 4. Search the knowledge base
        rep4, _, _, _ = service.execute_semantic_intent("Search the knowledge base")
        self.assertIn('Knowledge Base', rep4)

        # 5. Analyze unresolved tickets
        rep5, _, _, _ = service.execute_semantic_intent("Analyze unresolved tickets")
        self.assertIn('Unresolved Tickets Analysis', rep5)

        # 6. Find a ticket
        rep6, _, _, _ = service.execute_semantic_intent("Find a ticket")
        self.assertIn('Ticket Search', rep6)

