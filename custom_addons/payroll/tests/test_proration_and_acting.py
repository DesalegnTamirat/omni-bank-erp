# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'payroll')
class TestProrationAndActing(TransactionCase):
    """Unit test suite for multi-segment proration and acting allowance duration tracking."""

    def setUp(self):
        super(TestProrationAndActing, self).setUp()
        self.Payslip = self.env['hr.payslip']
        self.Employee = self.env['hr.employee']
        self.Period = self.env['hr.payroll.period']
        self.Job = self.env['hr.job']
        self.Acting = self.env['hr.acting.assignment']
        self.Structure = self.env['hr.payroll.structure']

        self.struct = self.Structure.search([('code', '=', 'ETH_BANK_STD')], limit=1)

        self.period = self.Period.create({
            'name': 'September 2026',
            'code': 'PERIOD/2026/09/PROR',
            'date_start': date(2026, 9, 1),
            'date_end': date(2026, 9, 30),
            'cutoff_date': date(2026, 9, 20),
            'state': 'open',
        })

    def test_01_mid_month_joiner_proration(self):
        """Test mid-month joiner hired on 16th of 30-day month (15 days worked = 50% basic)."""
        joiner = self.Employee.create({
            'name': 'Marta Tadesse',
            'basic_salary': 30000.0,
            'joining_date': date(2026, 9, 16),
        })

        payslip = self.Payslip.create({
            'employee_id': joiner.id,
            'period_id': self.period.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })

        payslip.compute_sheet()

        # Prorated factor: 15 / 30 = 0.5
        # Prorated basic: 30,000 * 0.5 = 15,000.0 ETB
        self.assertAlmostEqual(payslip.basic_wage, 15000.0, places=2)
        # Pension 7% of 15,000 = 1,050.0 ETB
        self.assertAlmostEqual(payslip.pension_ee, 1050.0, places=2)

    def test_02_acting_allowance_lifecycle_rules(self):
        """FR-PAY-028: Test acting allowance Month 1 (0%), Months 2-6 (100%), Month 7+ (0%)."""
        manager_job = self.Job.create({'name': 'Branch Operations Manager'})
        staff = self.Employee.create({
            'name': 'Dawit Lemma',
            'basic_salary': 20000.0,
        })

        # Scenario A: Month 1 (Start date: 2026-09-01 evaluated on 2026-09-30) -> Month 1 Buffer
        acting_m1 = self.Acting.create({
            'employee_id': staff.id,
            'acting_job_id': manager_job.id,
            'start_date': date(2026, 9, 1),
            'fixed_allowance_amount': 5000.0,
            'state': 'approved',
        })
        payout_m1 = acting_m1.get_monthly_payout_amount(for_date=date(2026, 9, 30))
        self.assertEqual(payout_m1, 0.0, "Month 1 acting assignment must receive 0 payment buffer.")

        # Scenario B: Month 3 (Start date: 2026-07-01 evaluated on 2026-09-30) -> Month 3 Active
        acting_m3 = self.Acting.create({
            'employee_id': staff.id,
            'acting_job_id': manager_job.id,
            'start_date': date(2026, 7, 1),
            'fixed_allowance_amount': 5000.0,
            'state': 'approved',
        })
        payout_m3 = acting_m3.get_monthly_payout_amount(for_date=date(2026, 9, 30))
        self.assertEqual(payout_m3, 5000.0, "Month 3 acting assignment must receive full allowance.")

        # Scenario C: Month 8 (Start date: 2026-02-01 evaluated on 2026-09-30) -> Month 8 Capped
        acting_m8 = self.Acting.create({
            'employee_id': staff.id,
            'acting_job_id': manager_job.id,
            'start_date': date(2026, 2, 1),
            'fixed_allowance_amount': 5000.0,
            'state': 'approved',
        })
        payout_m8 = acting_m8.get_monthly_payout_amount(for_date=date(2026, 9, 30))
        self.assertEqual(payout_m8, 0.0, "Month 7+ acting assignment must be stopped from payment.")
