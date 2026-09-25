# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


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
        ])
        if not root_objectives:
            raise UserError('No Corporate-level (Tier1) Objectives found. Configure them first.')

        employees = root_objectives.mapped('employee_id')
        if len(employees) != 1:
            raise UserError(
                'Expected exactly one employee owning Corporate-level Objectives, '
                'found %d. Please check your Configuration.' % len(employees)
            )
        employee = employees[0]

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

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'corporate.scorecard',
            'view_mode': 'form',
            'res_id': scorecard.id,
        }