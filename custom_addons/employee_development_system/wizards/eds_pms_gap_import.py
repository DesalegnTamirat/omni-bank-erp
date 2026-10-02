# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class EdsPmsGapImport(models.TransientModel):
    """Direct PMS Performance Appraisal Gap Ingestion Wizard for TNA Cycles.

    Pulls low performance scores and developmental recommendations directly
    from confirmed/accepted Tier 3 Appraisals in the Performance Management
    module into TNA entries without manual data entry or CSV uploads.
    """
    _name = 'eds.pms.gap.import'
    _description = 'Pull Performance Appraisal Gaps from PMS'

    cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle', required=True)
    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year (Optional Filter)',
        help='Optionally limit PMS gap ingestion to appraisals within a specific fiscal year.'
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period (Optional Filter)',
        help='Optionally limit PMS gap ingestion to a specific appraisal period (e.g. Q1, Q2, Semi-Annual, Annual).'
    )
    max_score_threshold = fields.Float(
        string='Maximum Score Threshold (%)',
        default=75.0,
        required=True,
        help='Only pull appraisals where the overall performance score is strictly below this percentage (e.g. 75%).'
    )
    state_filter = fields.Selection([
        ('confirmed', 'Confirmed Appraisals Only'),
        ('all_evaluated', 'All Evaluated (Notified / Accepted / Confirmed)'),
    ], string='Appraisal State', default='all_evaluated', required=True)

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit (Optional Filter)',
        help='Optionally limit gap ingestion to employees in a specific operating unit.'
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department (Optional Filter)',
        help='Optionally limit gap ingestion to employees in a specific department.'
    )
    result_log = fields.Text(string='Ingestion Summary', readonly=True)

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id and self.department_id and self.department_id.operating_unit_id != self.operating_unit_id:
            self.department_id = False
        dept_domain = self.env['eds.hr.compat'].get_department_domain(self.operating_unit_id)
        return {'domain': {'department_id': dept_domain}}

    @api.onchange('department_id')
    def _onchange_department_id(self):
        if self.department_id and self.department_id.operating_unit_id and not self.operating_unit_id:
            self.operating_unit_id = self.department_id.operating_unit_id

    def action_pull_pms_gaps(self):
        """Query PMS appraisals below threshold and generate TNA entries."""
        self.ensure_one()
        if 't3.appraisal' not in self.env:
            raise UserError(_("Performance Management (PMS) module is not installed."))

        domain = [
            ('employee_score', '>', 0.0),
            ('employee_score', '<', self.max_score_threshold),
            ('employee_id.active', '=', True),
        ]
        if self.state_filter == 'confirmed':
            domain.append(('state', '=', 'confirmed'))
        else:
            domain.append(('state', 'in', ('notified', 'accepted', 'confirmed')))

        if self.fiscal_year_id:
            domain.append(('fiscal_year_id', '=', self.fiscal_year_id.id))
        if self.appraisal_period_id:
            domain.append(('appraisal_period_id', '=', self.appraisal_period_id.id))
        if self.operating_unit_id:
            domain.append(('operating_unit_id', '=', self.operating_unit_id.id))
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))

        appraisals = self.env['t3.appraisal'].sudo().search(domain)
        if not appraisals:
            self.result_log = _(
                "Scan complete. No PMS appraisals found matching the gap criteria (Score < %.1f%% in states: %s)."
            ) % (self.max_score_threshold, self.state_filter)
            return self._return_view()

        TnaEntryModel = self.env['eds.tna.entry'].sudo()
        existing_pms_emps = set(
            self.cycle_id.entry_ids.filtered(lambda e: e.source == 'pms' and e.employee_id).mapped('employee_id.id')
        )

        success_count = 0
        skipped_count = 0

        for appraisal in appraisals:
            emp = appraisal.employee_id
            if not emp:
                continue

            if emp.id in existing_pms_emps:
                skipped_count += 1
                continue
            existing_pms_emps.add(emp.id)

            # Analyze appraisal lines for lowest metric and recommendations
            appraised_lines = appraisal.line_ids.filtered(lambda l: l.appraised == 'yes')
            lowest_line = appraised_lines.sorted('accomplishment_percent')[:1] if appraised_lines else False

            recom_lines = appraised_lines.filtered(lambda l: l.recommendations)
            recom_texts = [l.recommendations.strip() for l in recom_lines if l.recommendations.strip()]
            recom_summary = " | ".join(recom_texts) if recom_texts else ""

            score = round(appraisal.employee_score, 1)
            severity = 'critical' if score < 50.0 else ('high' if score < 65.0 else 'medium')

            if lowest_line and lowest_line.job_measure_id:
                prog_name = _("Performance Improvement: %s") % lowest_line.job_measure_id.name
                metric_detail = _("Lowest Metric: %s (%.1f%% achieved).") % (
                    lowest_line.job_measure_id.name, lowest_line.accomplishment_percent
                )
            else:
                prog_name = _("Performance Enhancement Program")
                metric_detail = ""

            recom_part = _(" Recommendations: %s.") % recom_summary if recom_summary else ""

            justification = _(
                "PMS Appraisal Gap Diagnostic from Appraisal '%s' (FY: %s, Period: %s). "
                "Overall Score: %.1f%% (%s). %s%s"
            ) % (
                appraisal.name,
                appraisal.fiscal_year_id.name if appraisal.fiscal_year_id else 'N/A',
                appraisal.appraisal_period_id.name if appraisal.appraisal_period_id else 'N/A',
                score,
                appraisal.performance_rating or 'Below Target',
                metric_detail,
                recom_part
            )

            work_unit = appraisal.operating_unit_id or self.env['eds.hr.compat'].get_employee_operating_unit(emp)
            job = appraisal.job_id or self.env['eds.hr.compat'].get_employee_job(emp)

            TnaEntryModel.create({
                'cycle_id': self.cycle_id.id,
                'employee_id': emp.id,
                'work_unit_id': work_unit.id if work_unit else False,
                'department_id': appraisal.department_id.id if appraisal.department_id else (emp.department_id.id if emp.department_id else False),
                'job_position_id': job.id if job else False,
                'proposed_program': prog_name,
                'urgency': severity,
                'priority_score': max(1.0, round(100.0 - score, 1)),
                'source': 'pms',
                'delivery_mode': 'classroom',
                'justification': justification,
                'state': 'submitted',
            })
            success_count += 1

        summary = _(
            "PMS Performance Gap Ingestion Complete:\n"
            "- Appraisals Scanned: %d\n"
            "- Successfully Created TNA Entries: %d\n"
            "- Skipped (Already Present): %d\n"
            "- Max Score Threshold Applied: %.1f%%"
        ) % (len(appraisals), success_count, skipped_count, self.max_score_threshold)

        self.result_log = summary
        self.cycle_id.message_post(body=_(
            "Diagnostic Ingestion: %d PMS performance gap entries pulled into cycle '%s'."
        ) % (success_count, self.cycle_id.name))

        return self._return_view()

    def _return_view(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.pms.gap.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
