# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class HrSalaryRule(models.Model):
    """
    Enterprise Salary Calculation Rule Model.
    
    Executes flexible mathematical formulas, condition evaluations, and dynamic Python code
    within an isolated safe environment. Provides deep access to payslip segments, contract terms,
    attendance metrics, disciplinary deductions, and accumulated category totals.
    """
    _name = 'hr.salary.rule'
    _description = 'Enterprise Salary Calculation Rule'
    _order = 'sequence, id'

    name = fields.Char(string='Rule Name', required=True, translate=True)
    code = fields.Char(string='Rule Code', required=True, index=True, help="Formula variable name, e.g. BASIC, GROSS, NET, TAX.")
    sequence = fields.Integer(string='Sequence', default=50, help="Execution order index. Rules are computed sequentially from lowest to highest sequence.")
    category_id = fields.Many2one(
        'hr.salary.rule.category',
        string='Category',
        required=True,
        index=True
    )
    structure_id = fields.Many2one(
        'hr.payroll.structure',
        string='Salary Structure',
        required=True,
        ondelete='cascade',
        index=True
    )
    active = fields.Boolean(string='Active', default=True)
    appears_on_payslip = fields.Boolean(
        string='Appears on Official Payslip',
        default=True,
        help="When enabled, this line item will render on the employee-facing payslip document and reports."
    )

    # Condition Configuration
    condition_select = fields.Selection([
        ('none', 'Always Satisfied (No Condition)'),
        ('range', 'Numeric Range Condition'),
        ('python', 'Python Expression Condition'),
    ], string='Condition Type', default='none', required=True)

    condition_range = fields.Char(string='Range Target Expression', default='contract.wage', help="Expression to evaluate against min/max limits.")
    condition_range_min = fields.Float(string='Minimum Range Limit', default=0.0)
    condition_range_max = fields.Float(string='Maximum Range Limit', default=0.0)
    condition_python = fields.Text(
        string='Python Condition Code',
        default='result = True',
        help="Custom Python boolean expression. Example: 'result = rules.GROSS.total > 1000'"
    )

    # Computation Configuration
    amount_select = fields.Selection([
        ('fix', 'Fixed Constant Amount'),
        ('percentage', 'Percentage Calculation'),
        ('code', 'Python Code Computation'),
    ], string='Amount Calculation Type', default='code', required=True)

    amount_fix = fields.Float(string='Fixed Amount (ETB)', digits=(16, 2), default=0.0)
    amount_percentage = fields.Float(string='Percentage (%)', digits=(16, 4), default=0.0)
    amount_percentage_base = fields.Char(
        string='Percentage Base Expression',
        default='categories.BASIC',
        help="Expression providing the base value on which the percentage is calculated."
    )
    amount_python_compute = fields.Text(
        string='Python Calculation Script',
        default='result = 0.0',
        help="Available local variables:\n"
             "- payslip: browse record of current hr.payslip\n"
             "- employee: browse record of current hr.employee\n"
             "- contract: active contract/version record\n"
             "- rules: object storing computed rule totals (e.g. rules.BASIC.total)\n"
             "- categories: object storing category totals (e.g. categories.GROSS)\n"
             "- inputs: dictionary of manual/imported payslip inputs\n"
             "- segments: list of active mid-month time slices (hr.payslip.segment)"
    )

    note = fields.Text(string='Internal Policy & Regulatory Reference')

    def _satisfies_condition(self, localdict):
        """
        Evaluate whether this rule should execute for the current payslip context.
        """
        self.ensure_one()
        if self.condition_select == 'none':
            return True
        elif self.condition_select == 'range':
            try:
                val = safe_eval(self.condition_range, localdict)
                return self.condition_range_min <= val <= self.condition_range_max
            except Exception as e:
                _logger.warning("Error evaluating range condition for rule %s: %s", self.code, str(e))
                return False
        elif self.condition_select == 'python':
            try:
                safe_eval(self.condition_python, localdict, mode='exec')
                return bool(localdict.get('result', False))
            except Exception as e:
                _logger.warning("Error evaluating python condition for rule %s: %s", self.code, str(e))
                return False
        return False

    def _compute_rule(self, localdict):
        """
        Compute line item amount, quantity, and rate for this rule.
        Returns a tuple of (amount, quantity, rate).
        """
        self.ensure_one()
        if self.amount_select == 'fix':
            return self.amount_fix, 1.0, 100.0
        elif self.amount_select == 'percentage':
            try:
                base_amount = float(safe_eval(self.amount_percentage_base, localdict))
                amount = (base_amount * self.amount_percentage) / 100.0
                return amount, 1.0, self.amount_percentage
            except Exception as e:
                _logger.error("Error evaluating percentage base for rule %s: %s", self.code, str(e))
                return 0.0, 1.0, 0.0
        elif self.amount_select == 'code':
            try:
                safe_eval(self.amount_python_compute, localdict, mode='exec')
                computed_amount = float(localdict.get('result', 0.0))
                qty = float(localdict.get('result_qty', 1.0))
                rate = float(localdict.get('result_rate', 100.0))
                return computed_amount, qty, rate
            except Exception as e:
                _logger.error("Error executing python compute script for rule %s: %s", self.code, str(e))
                raise UserError(_("Calculation error in salary rule [%s] %s: %s") % (self.code, self.name, str(e)))
        return 0.0, 1.0, 100.0
