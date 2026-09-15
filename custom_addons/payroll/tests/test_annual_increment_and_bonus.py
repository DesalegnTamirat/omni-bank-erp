# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'payroll')
class TestAnnualIncrementAndBonus(TransactionCase):
    """
    Comprehensive Unit Test Suite for:
    1. Annual Salary Increment Engine (Effective July 1, 1.5x Multiplier, Retroactive Arrears, Dual Mode Disbursement).
    2. Annual Performance Bonus Engine (PMS Score Brackets, Score 91 -> 2.0x Multiplier, Ethiopian PIT Tax, GL & CBS Export).
    """

    def setUp(self):
        super().setUp()
        self.Employee = self.env['hr.employee']
        self.Contract = self.env['hr.version']
        self.Department = self.env['hr.department']
        self.IncrementCampaign = self.env['payroll.increment.campaign']
        self.BonusCampaign = self.env['payroll.bonus.campaign']

        ou = self.env['operating.unit'].search([], limit=1)
        if not ou:
            ou = self.env['operating.unit'].create({'name': 'Head Office', 'code': 'HO'})
        self.dept_it = self.Department.create({'name': 'Test Compensation IT Dept', 'operating_unit_id': ou.id})

        # Employee 1: Standard Tenured Staff (Basic 20,000 ETB, PMS 91)
        self.emp_tenured = self.Employee.create({
            'name': 'Abebe Bikila',
            'department_id': self.dept_it.id,
            'basic_salary': 20000.0,
            'joining_date': date(2022, 1, 1),
            'salary_account': '100011223344',
        })
        self.contract_tenured = self.Contract.search([('employee_id', '=', self.emp_tenured.id)], limit=1)
        if not self.contract_tenured:
            self.contract_tenured = self.Contract.create({
                'name': 'Contract - Abebe Bikila',
                'employee_id': self.emp_tenured.id,
                'wage': 20000.0,
                'base_salary': 20000.0,
                'pms_score': 91.0,
                'contract_date_start': date(2022, 1, 1),
                'state': 'open',
            })
        else:
            self.contract_tenured.write({
                'wage': 20000.0,
                'base_salary': 20000.0,
                'pms_score': 91.0,
                'contract_date_start': date(2022, 1, 1),
                'state': 'open',
            })

        # Employee 2: Top Performer Staff (Basic 40,000 ETB, PMS 160)
        self.emp_top = self.Employee.create({
            'name': 'Tadesse Gemechu',
            'department_id': self.dept_it.id,
            'basic_salary': 40000.0,
            'joining_date': date(2021, 6, 1),
            'salary_account': '100055667788',
        })
        self.contract_top = self.Contract.search([('employee_id', '=', self.emp_top.id)], limit=1)
        if not self.contract_top:
            self.contract_top = self.Contract.create({
                'name': 'Contract - Tadesse Gemechu',
                'employee_id': self.emp_top.id,
                'wage': 40000.0,
                'base_salary': 40000.0,
                'pms_score': 160.0,
                'contract_date_start': date(2021, 6, 1),
                'state': 'open',
            })
        else:
            self.contract_top.write({
                'wage': 40000.0,
                'base_salary': 40000.0,
                'pms_score': 160.0,
                'contract_date_start': date(2021, 6, 1),
                'state': 'open',
            })

        # Employee 3: Mid-Year Joiner (Joined 6 months prior to July 1, Basic 15,000 ETB, PMS 95)
        self.emp_joiner = self.Employee.create({
            'name': 'Marta Haile',
            'department_id': self.dept_it.id,
            'basic_salary': 15000.0,
            'joining_date': date(2025, 1, 1),
            'salary_account': '100099887766',
        })
        self.contract_joiner = self.Contract.search([('employee_id', '=', self.emp_joiner.id)], limit=1)
        if not self.contract_joiner:
            self.contract_joiner = self.Contract.create({
                'name': 'Contract - Marta Haile',
                'employee_id': self.emp_joiner.id,
                'wage': 15000.0,
                'base_salary': 15000.0,
                'pms_score': 95.0,
                'contract_date_start': date(2025, 1, 1),
                'state': 'open',
            })
        else:
            self.contract_joiner.write({
                'wage': 15000.0,
                'base_salary': 15000.0,
                'pms_score': 95.0,
                'contract_date_start': date(2025, 1, 1),
                'state': 'open',
            })

    def test_01_annual_increment_computation_and_back_arrears(self):
        """Test July 1 Annual Increment with 1.5x multiplier and 3 months retroactive back-increment arrears."""
        eff_date = date(2025, 7, 1)
        app_date = date(2025, 10, 1)  # 3 months elapsed after July 1

        campaign = self.IncrementCampaign.create({
            'title': 'FY 2025/2026 Annual Staff Salary Increment Test',
            'fiscal_year': '2025/2026',
            'effective_date': eff_date,
            'approval_date': app_date,
            'calculation_method': 'flat_multiplier',
            'base_multiplier': 1.5,
            'disbursement_mode': 'separate_batch',
            'department_ids': [(6, 0, [self.dept_it.id])],
        })

        # 1. Compute lines
        campaign.action_compute_increment_lines()
        self.assertEqual(campaign.state, 'computed')
        self.assertEqual(len(campaign.line_ids), 3)

        # 2. Check tenured employee calculation (Basic 20,000 -> 5% step is 1,000 -> 1.5x multiplier is 1,500)
        line_abebe = campaign.line_ids.filtered(lambda l: l.employee_id.id == self.emp_tenured.id)
        self.assertTrue(line_abebe.is_eligible)
        self.assertAlmostEqual(line_abebe.increment_amount, 1500.0, delta=0.01)
        self.assertAlmostEqual(line_abebe.new_basic, 21500.0, delta=0.01)
        self.assertEqual(line_abebe.retroactive_months, 3)
        # 3 months arrears = 1,500 * 3 = 4,500 ETB
        self.assertAlmostEqual(line_abebe.retroactive_arrears, 4500.0, delta=0.01)

        # 3. Verify workflow progression
        campaign.action_verify()
        self.assertEqual(campaign.state, 'verified')
        campaign.action_approve()
        self.assertEqual(campaign.state, 'approved')

        # 4. Apply Increment & generate separate CBS payment batch
        campaign.action_apply_and_disburse()
        self.assertEqual(campaign.state, 'applied')

        # Verify contract wage updated
        self.assertAlmostEqual(self.emp_tenured.basic_salary, 21500.0, delta=0.01)
        self.assertAlmostEqual(self.contract_tenured.wage, 21500.0, delta=0.01)

        # Verify Mode B Payment Batch created
        self.assertTrue(campaign.payment_batch_id)
        self.assertGreater(campaign.payment_batch_id.total_amount, 0.0)

    def test_02_annual_performance_bonus_pms_tier_and_tax(self):
        """Test PMS Performance Bonus with user's exact specification: PMS 91 -> 2.0 months basic salary."""
        campaign = self.BonusCampaign.create({
            'title': 'FY 2024/2025 Annual Performance Bonus Test',
            'fiscal_year': '2024/2025',
            'fy_start_date': date(2024, 7, 8),
            'fy_end_date': date(2025, 7, 7),
            'declaration_date': date(2025, 9, 15),
            'tier_above_150_months': 3.50,
            'tier_120_150_months': 2.75,
            'tier_100_120_months': 2.25,
            'tier_85_100_months': 2.00,
            'tier_75_85_months': 1.25,
            'tier_50_75_months': 0.50,
            'tier_below_50_months': 0.00,
            'department_ids': [(6, 0, [self.dept_it.id])],
        })

        # 1. Compute bonus schedules
        campaign.action_compute_bonus_lines()
        self.assertEqual(campaign.state, 'computed')

        # 2. Check Abebe (PMS 91 -> Tier 4: 85 - 100 -> 2.0 months)
        line_abebe = campaign.line_ids.filtered(lambda l: l.employee_id.id == self.emp_tenured.id)
        self.assertTrue(line_abebe.is_eligible)
        self.assertEqual(line_abebe.months_multiplier, 2.0)
        # Gross bonus = 20,000 * 2.0 = 40,000 ETB
        self.assertAlmostEqual(line_abebe.gross_bonus, 40000.0, delta=0.01)

        # Ethiopian PIT tax on 40,000 ETB (Over 10,900 bracket: 35% - 1500 = 14,000 - 1,500 = 12,500 ETB)
        self.assertAlmostEqual(line_abebe.tax_deduction, 12500.0, delta=0.01)
        # Net bonus = 40,000 - 12,500 = 27,500 ETB
        self.assertAlmostEqual(line_abebe.net_payable, 27500.0, delta=0.01)

        # 3. Check Tadesse (PMS 160 -> Tier 1: Above 150 -> 3.5 months)
        line_top = campaign.line_ids.filtered(lambda l: l.employee_id.id == self.emp_top.id)
        self.assertTrue(line_top.is_eligible)
        self.assertEqual(line_top.months_multiplier, 3.50)
        # Gross = 40,000 * 3.5 = 140,000 ETB
        self.assertAlmostEqual(line_top.gross_bonus, 140000.0, delta=0.01)

        # 4. Sign-off and Settlement
        campaign.action_verify()
        campaign.action_approve()
        campaign.action_post_and_disburse()

        self.assertEqual(campaign.state, 'paid')
        self.assertTrue(campaign.payment_batch_id)
        self.assertGreater(campaign.payment_batch_id.total_amount, 0.0)
