# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError
from ..models.t2_appraisal import detect_period_type, get_target_for_period


class PopulateCorporateAppraisalWizard(models.TransientModel):
    _name = 'populate.corporate.appraisal.wizard'
    _description = 'Populate Corporate Appraisal Wizard'

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

        scorecard = self.env['corporate.scorecard'].search([
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
        ], limit=1)

        if not scorecard:
            scorecard = self.env['corporate.scorecard'].search([
                ('fiscal_year_id', '=', self.fiscal_year_id.id),
            ], limit=1)

        if not scorecard:
            raise UserError(
                'No Corporate Scorecard found for the selected Fiscal Year and Appraisal Period.'
            )

        if scorecard.state not in ('accepted', 'confirmed', 'appraisal_started'):
            raise UserError(
                'Only accepted Corporate Scorecards can be populated into Appraisal. '
                'The current status of this scorecard is "%s".' % dict(
                    scorecard._fields['state'].selection
                ).get(scorecard.state, scorecard.state)
            )

        existing = self.env['corporate.appraisal'].search([
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
        ], limit=1)

        if existing:
            if existing.state != 'draft':
                raise UserError(
                    'A Corporate Appraisal already exists for this Fiscal Year and '
                    'Appraisal Period, and it is no longer in Draft (current status: %s).' % dict(
                        existing._fields['state'].selection
                    ).get(existing.state, existing.state)
                )
            existing.unlink()

        # Update scorecard state to appraisal_started so it won't be deleted on subsequent scorecard populate runs
        scorecard.write({'state': 'appraisal_started'})

        appraisal = self.env['corporate.appraisal'].create({
            'name': 'Corporate Appraisal %s %s' % (self.fiscal_year_id.name, self.appraisal_period_id.name),
            'scorecard_id': scorecard.id,
            'fiscal_year_id': self.fiscal_year_id.id,
            'appraisal_period_id': self.appraisal_period_id.id,
            'company_id': scorecard.company_id.id,
            'employee_id': scorecard.employee_id.id,
            'operating_unit_id': self.env['performance.objective'].search(
                [('employee_id', '=', scorecard.employee_id.id)], limit=1
            ).employee_operating_unit_id.id or False,
            'job_id': scorecard.employee_id.job_id.id if scorecard.employee_id.job_id else False,
            'start_date': fyl.date_start,
            'end_date': fyl.date_end,
            'appraisal_date': fields.Date.context_today(self),
            'manager_id': False,
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
                'weight': sc_line.weight,
                'planned_weight': sc_line.weight,
                'target': target_val,
                'appraisal_criteria': sc_line.target_description or '',
                'maximum_score': sc_line.weight,
                'appraised': 'yes',
                'uploaded_value': 0.0,
            })

        if lines_vals:
            self.env['corporate.appraisal.line'].create(lines_vals)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'corporate.appraisal',
            'view_mode': 'form',
            'res_id': appraisal.id,
        }