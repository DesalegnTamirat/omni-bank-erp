# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class PopulateT2ScorecardWizard(models.TransientModel):
    _name = 'populate.t2.scorecard.wizard'
    _description = 'Populate Tier 2 Scorecard Wizard'

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

        # Everyone who owns at least one non-root (cascaded) Objective —
        # i.e. everyone except the CEO.
        objectives = self.env['performance.objective'].search([
            ('parent_objective_id', '!=', False),
        ])
        employees = objectives.mapped('employee_id')
        if not employees:
            raise UserError('No cascaded Objectives found. Configure Tier2 Objectives first.')

        planning_name = 'Corporate Scorecard %s %s' % (self.fiscal_year_id.name, self.appraisal_period_id.name)

        existing = self.env['t2.scorecard'].search([
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
                'operating_unit_id': self.env['performance.objective'].search(
                    [('employee_id', '=', emp.id)], limit=1
                ).employee_operating_unit_id.id or False,
                'manager_id': emp.coach_id.id if emp.coach_id else False,
                'job_id': emp.job_id.id if emp.job_id else False,
            })

        if not vals_list:
            raise UserError('No new Tier2 Scorecards were created — they may already exist.')

        new_scorecards = self.env['t2.scorecard'].create(vals_list)
        new_scorecards.action_populate_lines()

        return {
            'name': 'Populated Tier2 Scorecards',
            'type': 'ir.actions.act_window',
            'res_model': 't2.scorecard',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_scorecards.ids)],
        }