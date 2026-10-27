from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPerformanceUserGroupAssignment(TransactionCase):
    def test_internal_user_role_on_create_and_group_change(self):
        internal_group = self.env.ref('base.group_user')
        performance_group = self.env.ref('performance_management.group_performance_user')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Performance role regression user',
            'login': 'performance-role-regression@example.test',
            'group_ids': [Command.set(internal_group.ids)],
        })

        self.assertIn(performance_group.id, user.group_ids.ids)

        user.write({'group_ids': [Command.set(internal_group.ids)]})

        self.assertIn(performance_group.id, user.group_ids.ids)
