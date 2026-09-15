# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from datetime import date
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'payroll')
class TestPayrollCalculations(TransactionCase):
    """Unit test suite for Ethiopian statutory tax brackets and pension calculations."""

    def setUp(self):
        super(TestPayrollCalculations, self).setUp()
        self.Structure = self.env['hr.payroll.structure']
        self.Payslip = self.env['hr.payslip']
        self.Employee = self.env['hr.employee']
        self.Period = self.env['hr.payroll.period']

        # Retrieve standard Ethiopian banking salary structure
        self.struct = self.Structure.search([('code', '=', 'ETH_BANK_STD')], limit=1)

        # Create test company and employee
        self.employee = self.Employee.create({
            'name': 'Abebe Bikila',
            'basic_salary': 15000.0,
            'salary_account': '100012345678',
            'tin': '0012345678',
        })

        # Create test period
        self.period = self.Period.create({
            'name': 'September 2026',
            'code': 'PERIOD/2026/09',
            'date_start': date(2026, 9, 1),
            'date_end': date(2026, 9, 30),
            'cutoff_date': date(2026, 9, 20),
            'state': 'open',
        })

    def test_01_statutory_tax_and_pension_calculation(self):
        """Test calculation of basic wage, pension (7% EE / 11% ER), and Ethiopian progressive tax."""
        payslip = self.Payslip.create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })

        payslip.compute_sheet()

        # Basic wage check
        self.assertEqual(payslip.basic_wage, 15000.0)
        
        # Pension 7% Employee: 15,000 * 0.07 = 1,050.0 ETB
        self.assertAlmostEqual(payslip.pension_ee, 1050.0, places=2)
        
        # Pension 11% Employer: 15,000 * 0.11 = 1,650.0 ETB
        self.assertAlmostEqual(payslip.pension_er, 1650.0, places=2)

        # Taxable income = 15,000 ETB (Above 10,900 bracket)
        # Tax = (15,000 * 0.35) - 1500 = 5,250 - 1500 = 3,750.0 ETB
        self.assertAlmostEqual(payslip.income_tax, 3750.0, places=2)

        # Net = Gross (15,000) - Tax (3,750) - Pension EE (1,050) = 10,200.0 ETB
        self.assertAlmostEqual(payslip.net_wage, 10200.0, places=2)

    def test_02_low_income_zero_tax_bracket(self):
        """Test low income below 600 ETB threshold (0% tax)."""
        low_earner = self.Employee.create({
            'name': 'Chala Kebede',
            'basic_salary': 500.0,
        })
        payslip = self.Payslip.create({
            'employee_id': low_earner.id,
            'period_id': self.period.id,
            'struct_id': self.struct.id,
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 30),
        })
        payslip.compute_sheet()
        self.assertEqual(payslip.income_tax, 0.0)
