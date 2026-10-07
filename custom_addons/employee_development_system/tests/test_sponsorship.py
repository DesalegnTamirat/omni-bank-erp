import base64
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'b2')
class TestEdsSponsorship(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Dawit Kebede',
        })
        # Admin or manager user
        cls.manager_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'L&D Manager Test',
            'login': 'ld_manager_test_unique_b2',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('employee_development_system.group_eds_manager').id,
            ])],
        })

    def _create_active_sponsorship(self, amount=100000.0, start_date=None, end_date=None, policy='pro_rata'):
        today = fields.Date.context_today(self.env.user)
        start = start_date or today
        end = end_date or (start + timedelta(days=730))
        sponsorship = self.env['eds.sponsorship'].create({
            'employee_id': self.employee.id,
            'program_name': 'ACCA Strategic Professional',
            'approved_amount': amount,
            'bond_duration_months': 24,
            'bond_start_date': start,
            'bond_end_date': end,
            'recovery_policy': policy,
            'bond_agreement': base64.b64encode(b'Sample bond agreement content for unit testing'),
            'bond_filename': 'agreement.pdf',
        })
        sponsorship.write({'state': 'active'})
        return sponsorship

    def test_b2_breach_reasons(self):
        """B2 & FREDS064: Test breach marking across all supported breach reasons."""
        reasons = ['resignation', 'breach', 'withdrawal', 'non_completion']
        for reason in reasons:
            sponsorship = self._create_active_sponsorship()
            sponsorship.breach_reason = reason
            sponsorship.with_user(self.manager_user).action_mark_breached()

            self.assertEqual(sponsorship.state, 'breached')
            self.assertEqual(sponsorship.breach_reason, reason)
            self.assertTrue(sponsorship.repayment_line_ids)
            last_line = sponsorship.repayment_line_ids[-1]
            self.assertEqual(last_line.amount, sponsorship.recovery_amount)

            payload = self.env['eds.payroll.payload'].search([
                ('employee_id', '=', self.employee.id),
                ('source_ref', 'ilike', f"%({reason})%"),
            ], order='id desc', limit=1)
            self.assertTrue(payload)
            self.assertEqual(payload.amount, sponsorship.recovery_amount)

    def test_b2_pro_rata_recovery_mid_bond(self):
        """B2: Test that pro-rata unamortised balance is computed BEFORE state change."""
        today = fields.Date.context_today(self.env.user)
        # Exactly 50% elapsed
        start_date = today - timedelta(days=365)
        end_date = today + timedelta(days=365)
        sponsorship = self._create_active_sponsorship(
            amount=100000.0, start_date=start_date, end_date=end_date, policy='pro_rata'
        )
        sponsorship.with_user(self.manager_user).action_mark_breached()

        self.assertEqual(sponsorship.state, 'breached')
        # Approximately 50,000 ETB
        self.assertAlmostEqual(sponsorship.recovery_amount, 50000.0, delta=500.0)
        self.assertAlmostEqual(sponsorship.outstanding_obligation, 50000.0, delta=500.0)

    def test_b2_full_recovery_under_policy_clause(self):
        """B2: Test full amount recovery when policy field specifies full amount."""
        today = fields.Date.context_today(self.env.user)
        start_date = today - timedelta(days=365)
        end_date = today + timedelta(days=365)
        sponsorship = self._create_active_sponsorship(
            amount=100000.0, start_date=start_date, end_date=end_date, policy='full'
        )
        sponsorship.with_user(self.manager_user).action_mark_breached()

        self.assertEqual(sponsorship.state, 'breached')
        self.assertEqual(sponsorship.recovery_amount, 100000.0)
        self.assertEqual(sponsorship.outstanding_obligation, 100000.0)

    def test_b2_fully_elapsed_bond_yields_zero_recovery(self):
        """B2: Test that a bond that has fully elapsed has 0 recovery obligation."""
        today = fields.Date.context_today(self.env.user)
        start_date = today - timedelta(days=800)
        end_date = today - timedelta(days=70)  # elapsed in past
        sponsorship = self._create_active_sponsorship(
            amount=100000.0, start_date=start_date, end_date=end_date, policy='pro_rata'
        )
        sponsorship.with_user(self.manager_user).action_mark_breached()

        self.assertEqual(sponsorship.state, 'breached')
        self.assertEqual(sponsorship.recovery_amount, 0.0)
        self.assertEqual(sponsorship.outstanding_obligation, 0.0)
        self.assertEqual(sponsorship.repayment_line_ids[-1].amount, 0.0)
