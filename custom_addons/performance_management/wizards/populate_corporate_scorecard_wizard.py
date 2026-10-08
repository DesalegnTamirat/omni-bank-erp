# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo import fields, models
from odoo.exceptions import UserError


def get_employee_hire_date(employee):
    """Retrieve the hire date or service start date of an employee."""
    if not employee:
        return False
    for field_name in ('service_hire_date', 'hire_date', 'service_start_date', 'first_contract_date', 'start_date'):
        if hasattr(employee, field_name) and getattr(employee, field_name):
            return getattr(employee, field_name)
    if hasattr(employee, 'contract_ids') and employee.contract_ids:
        contracts = employee.contract_ids.filtered('date_start').sorted('date_start')
        if contracts and contracts[0].date_start:
            return contracts[0].date_start
    if hasattr(employee, 'contract_id') and employee.contract_id and employee.contract_id.date_start:
        return employee.contract_id.date_start
    if hasattr(employee, 'version_id') and employee.version_id:
        v = employee.version_id
        for field_name in ('service_hire_date', 'service_start_date', 'start_date', 'probation_start_date'):
            if hasattr(v, field_name) and getattr(v, field_name):
                return getattr(v, field_name)
    if employee.create_date:
        return employee.create_date.date()
    return False


def is_eligible_for_period(employee, period_start, period_end):
    """
    Check if employee has worked at least 3 months by the appraisal period end date.
    Employees who have not completed 3 months of service by the period end are excluded.
    """
    hire_date = get_employee_hire_date(employee)
    if not hire_date:
        return True
    if period_end:
        if hire_date > period_end:
            return False
        min_service_date = hire_date + relativedelta(months=3)
        if min_service_date > period_end:
            return False
    return True


class PopulateCorporateScorecardWizard(models.TransientModel):
    _name = 'populate.corporate.scorecard.wizard'
    _description = 'Populate Corporate Scorecard Wizard'

    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year', string='Fiscal Year', required=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period', string='Appraisal Period', required=True,
    )

    def action_populate(self):
        self.ensure_one()

        fyl = self.fiscal_year_id.line_ids.filtered(
            lambda l: l.appraisal_period == self.appraisal_period_id
        )[:1]
        if not fyl:
            raise UserError(
                'No Fiscal Year Line found for the selected Fiscal Year and Appraisal Period.'
            )

        root_objectives = self.env['performance.objective'].search([
            ('parent_objective_id', '=', False),
            ('active', '=', True),
        ])
        if not root_objectives:
            raise UserError('No active Corporate-level (Tier 1) Objectives found. Configure them first.')

        # Verify active measures sum to 100%
        active_measures = root_objectives.mapped('measure_ids').filtered(lambda m: m.active)
        total_weight = sum(active_measures.mapped('weight'))
        if round(total_weight, 2) != 100.0:
            raise UserError(
                f"Corporate Objectives do not have 100% total weight (currently {round(total_weight, 2)}%). "
                "Please adjust the Corporate Measures so they total exactly 100% before populating."
            )

        employees = root_objectives.mapped('employee_id')
        if len(employees) != 1:
            raise UserError(
                'Expected exactly one employee owning Corporate-level Objectives, '
                'found %d. Please check your Configuration.' % len(employees)
            )
        employee = employees[0]

        # Check 3-month tenure rule
        if not is_eligible_for_period(employee, fyl.date_start, fyl.date_end):
            raise UserError(
                f"The executive '{employee.name}' does not meet the minimum 3 months service requirement "
                f"for the period ending {fyl.date_end}."
            )

        existing = self.env['corporate.scorecard'].search([
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
        ], limit=1)

        if existing:
            if existing.state != 'draft':
                raise UserError(
                    'A Corporate Scorecard already exists for this Fiscal Year and '
                    'Appraisal Period, and it is no longer in Draft (current status: '
                    '%s). It cannot be regenerated.' % dict(
                        existing._fields['state'].selection
                    ).get(existing.state, existing.state)
                )
            existing.unlink()

        scorecard = self.env['corporate.scorecard'].create({
            'name': 'Corporate Scorecard Plan %s %s' % (self.fiscal_year_id.name, self.appraisal_period_id.name),
            'fiscal_year_id': self.fiscal_year_id.id,
            'appraisal_period_id': self.appraisal_period_id.id,
            'employee_id': employee.id,
            'date_start': fyl.date_start,
            'date_end': fyl.date_end,
        })

        scorecard.action_populate_lines()

        if round(scorecard.total_weight, 2) != 100.0:
            scorecard.unlink()
            raise UserError(
                f"Corporate Scorecard generation restricted: Total weight is {round(scorecard.total_weight, 2)}% "
                "(must be exactly 100%). Please check Corporate Measures."
            )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'corporate.scorecard',
            'view_mode': 'form',
            'res_id': scorecard.id,
        }