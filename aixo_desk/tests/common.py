from odoo.tests.common import TransactionCase


class DeskCase(TransactionCase):
    """Builds its own users so tests do not depend on demo data."""

    @classmethod
    def _make_user(cls, name, login, group_xmlid, **extra):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': name,
            'login': login,
            'email': login,
            'group_ids': [(6, 0, [cls.env.ref(group_xmlid).id])],
            **extra,
        })

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = cls._make_user('T Admin', 't_admin@example.com', 'aixo_desk.group_desk_admin')
        cls.agent_a = cls._make_user('T Agent A', 't_agent_a@example.com', 'aixo_desk.group_desk_agent')
        cls.agent_b = cls._make_user('T Agent B', 't_agent_b@example.com', 'aixo_desk.group_desk_agent')
        cls.company_a = cls.env['res.partner'].create({'name': 'T Company A', 'is_company': True})
        cls.company_b = cls.env['res.partner'].create({'name': 'T Company B', 'is_company': True})
        cls.cust_a = cls._make_user('T Cust A', 't_cust_a@example.com', 'aixo_desk.group_desk_customer',
                                    parent_id=cls.company_a.id)
        cls.cust_b = cls._make_user('T Cust B', 't_cust_b@example.com', 'aixo_desk.group_desk_customer',
                                    parent_id=cls.company_b.id)
        cls.colleague_a = cls.env['res.partner'].create(
            {'name': 'T Colleague A', 'email': 't_col_a@example.com', 'parent_id': cls.company_a.id})

    def _ticket(self, partner, owner=None, **vals):
        return self.env['aixo.ticket'].create({
            'name': vals.pop('name', 'Test ticket'),
            'partner_id': partner.id,
            'owner_id': owner.id if owner else False,
            **vals,
        })
