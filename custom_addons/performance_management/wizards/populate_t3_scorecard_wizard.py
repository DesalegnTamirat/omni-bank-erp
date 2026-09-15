# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class PopulateT3ScorecardWizard(models.TransientModel):
    _name = 'populate.t3.scorecard.wizard'
    _description = 'Populate Tier 3 Scorecard Wizard'

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

        job_objectives = self.env['performance.job.objective'].search([])
        if not job_objectives:
            raise UserError('No Job Position KPIs found. Configure them first.')

        unit_job_pairs = set(
            (obj.operating_unit_id.id, obj.job_id.id) for obj in job_objectives
        )

        Employee = self.env['hr.employee']
        employees = Employee.browse()
        for unit_id, job_id in unit_job_pairs:
            employees |= Employee.search([
                ('default_operating_unit_id', '=', unit_id),
                ('job_position', '=', job_id),
            ])

        if not employees:
            raise UserError(
                'No employees found matching the configured Work Unit + Job '
                'Position combinations. Check employee assignments.'
            )

        planning_name = 'Corporate Scorecard %s %s' % (self.fiscal_year_id.name, self.appraisal_period_id.name)

        existing = self.env['t3.scorecard'].search([
            ('employee_id', 'in', employees.ids),
            ('planning_name', '=', planning_name),
        ])
        draft_existing = existing.filtered(lambda r: r.state == 'draft')
        locked_existing = existing - draft_existing

        if draft_existing:
            draft_existing.unlink()

        locked_employee_ids = set(locked_existing.mapped('employee_id').ids)

        vals_list = []
        for emp in employees:
            if emp.id in locked_employee_ids:
                continue
            vals_list.append({
                'employee_id': emp.id,
                'planning_name': planning_name,
                'appraisal_period_id': self.appraisal_period_id.id,
                'start_date': fyl.date_start,
                'end_date': fyl.date_end,
                'company_id': emp.company_id.id if emp.company_id else False,
                'operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                'manager_id': emp.coach_id.id if emp.coach_id else False,
                'job_id': emp.job_position.id if emp.job_position else False,
            })

        if not vals_list:
            raise UserError('No new Tier3 Scorecards were created — they may already exist.')

        new_scorecards = self.env['t3.scorecard'].create(vals_list)
        new_scorecards.action_populate_lines()

        return {
            'name': 'Populated Tier3 Scorecards',
            'type': 'ir.actions.act_window',
            'res_model': 't3.scorecard',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_scorecards.ids)],
        }