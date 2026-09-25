# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError
from ..models.t2_appraisal import detect_period_type, get_target_for_period


class PopulateT2AppraisalWizard(models.TransientModel):
    _name = 'populate.t2.appraisal.wizard'
    _description = 'Populate Tier 2 Appraisal Wizard'

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

        scorecards = self.env['t2.scorecard'].search([
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
            ('start_date', '=', fyl.date_start),
            ('state', 'in', ('accepted', 'confirmed', 'appraisal_started')),
        ])

        if not scorecards:
            scorecards = self.env['t2.scorecard'].search([
                ('appraisal_period_id', '=', self.appraisal_period_id.id),
                ('state', 'in', ('accepted', 'confirmed', 'appraisal_started')),
            ])

        if not scorecards:
            scorecards = self.env['t2.scorecard'].search([
                ('fiscal_year_id', '=', self.fiscal_year_id.id),
                ('state', 'in', ('accepted', 'confirmed', 'appraisal_started')),
            ])

        if not scorecards:
            raise UserError(
                'No accepted Tier 2 Scorecards found for the selected Fiscal Year and Appraisal Period.'
            )

        created_appraisals = self.env['t2.appraisal']

        for scorecard in scorecards:
            existing = self.env['t2.appraisal'].search([
                ('scorecard_id', '=', scorecard.id),
            ], limit=1)

            if existing:
                if existing.state != 'draft':
                    continue
                existing.unlink()

            scorecard.write({'state': 'appraisal_started'})

            unit_name = scorecard.operating_unit_id.name if scorecard.operating_unit_id else scorecard.employee_id.name
            appraisal_name = '%s Appraisal %s %s' % (
                unit_name, self.fiscal_year_id.name, self.appraisal_period_id.name
            )

            appraisal = self.env['t2.appraisal'].create({
                'name': appraisal_name,
                'scorecard_id': scorecard.id,
                'planning_name': scorecard.planning_name,
                'fiscal_year_id': self.fiscal_year_id.id,
                'appraisal_period_id': self.appraisal_period_id.id,
                'company_id': scorecard.company_id.id if scorecard.company_id else False,
                'employee_id': scorecard.employee_id.id,
                'operating_unit_id': scorecard.operating_unit_id.id if scorecard.operating_unit_id else False,
                'department_id': scorecard.department_id.id if scorecard.department_id else False,
                'job_id': scorecard.job_id.id if scorecard.job_id else False,
                'start_date': fyl.date_start,
                'end_date': fyl.date_end,
                'appraisal_date': fields.Date.context_today(self),
                'manager_id': scorecard.manager_id.id if scorecard.manager_id else False,
                'state': 'draft',
            })

            period_type = detect_period_type(
                period_rec=self.appraisal_period_id or scorecard.appraisal_period_id,
                start_date=fyl.date_start,
                end_date=fyl.date_end,
                fiscal_year=self.fiscal_year_id,
            )

            lines_vals = []
            for sc_line in scorecard.line_ids:
                target_val = get_target_for_period(sc_line, period_type)

                lines_vals.append({
                    'appraisal_id': appraisal.id,
                    'perspective_id': sc_line.perspective_id.id if sc_line.perspective_id else False,
                    'objective_id': sc_line.objective_id.id if sc_line.objective_id else False,
                    'measure_id': sc_line.measure_id.id if sc_line.measure_id else False,
                    'planned_weight': sc_line.weight,
                    'weight': sc_line.weight,
                    'target': target_val,
                    'appraisal_criteria': sc_line.target_description or '',
                    'maximum_score': sc_line.weight,
                    'appraised': 'yes',
                    'uploaded_value': 0.0,
                })

            if lines_vals:
                self.env['t2.appraisal.line'].create(lines_vals)

            created_appraisals |= appraisal

        if not created_appraisals:
            raise UserError('No new Tier 2 Appraisals were created — they may already be locked/processed.')

        return {
            'name': 'Populated Tier 2 Appraisals',
            'type': 'ir.actions.act_window',
            'res_model': 't2.appraisal',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', created_appraisals.ids)],
        }
