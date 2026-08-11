# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import timedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Disciplinary History Smart Fields
    active_disciplinary_action = fields.Boolean(
        string='Has Active Disciplinary Action',
        default=False,
        help='Indicates whether employee has an active/enforced disciplinary warning or pending case',
        tracking=True
    )
    disciplinary_warning_count = fields.Integer(
        string='Total Disciplinary Warnings',
        default=0,
        readonly=True,
        tracking=True
    )
    last_disciplinary_date = fields.Date(
        string='Last Disciplinary Action Date',
        readonly=True,
        tracking=True
    )
    is_suspended = fields.Boolean(
        string='Currently Suspended',
        default=False,
        readonly=True,
        tracking=True
    )
    suspension_type = fields.Selection([
        ('with_pay', 'Suspension With Pay'),
        ('without_pay', 'Suspension Without Pay'),
    ], string='Active Suspension Type', readonly=True)

    discipline_case_ids = fields.One2many(
        'discipline.case',
        'employee_id',
        string='Disciplinary Cases History'
    )
    discipline_case_count = fields.Integer(
        string='Disciplinary Cases Count',
        compute='_compute_discipline_case_count'
    )

    @api.depends('discipline_case_ids')
    def _compute_discipline_case_count(self):
        for emp in self:
            emp.discipline_case_count = len(emp.discipline_case_ids)

    # Recruitment & Promotion Eligibility Integration Method
    def check_discipline_eligibility(self):
        """
        Check if employee is eligible for promotion, transfer, or internal recruitment.
        Returns tuple: (is_eligible: bool, reason: str)
        """
        self.ensure_one()
        if self.is_suspended:
            return (False, _('Employee is currently under active disciplinary suspension (%s).') % self.suspension_type)
        
        # Check active cases in enforced state within last 12 months
        cutoff_date = fields.Date.context_today(self) - timedelta(days=365)
        active_cases = self.discipline_case_ids.filtered(
            lambda c: c.state == 'enforced' and c.final_decision_date and c.final_decision_date >= cutoff_date
        )
        if active_cases:
            case_names = ", ".join(active_cases.mapped('name'))
            return (False, _('Ineligible for promotion/recruitment due to active disciplinary record within 12 months (Cases: %s).') % case_names)
        
        return (True, _('Employee is eligible.'))

    def action_view_discipline_cases(self):
        self.ensure_one()
        return {
            'name': _('Disciplinary Cases History'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id}
        }
