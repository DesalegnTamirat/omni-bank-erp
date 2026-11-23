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
        string='Default Measurement Gap Threshold (%)',
        default=75.0,
        required=True,
        help='Include an individual measurement below this threshold even when no course mapping exists. '
             'Mapped courses use their configured gap threshold.'
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
    ingestion_done = fields.Boolean(readonly=True)
    scanned_count = fields.Integer(string='Appraisals Scanned', readonly=True)
    created_count = fields.Integer(string='Needs Created', readonly=True)
    skipped_count = fields.Integer(string='Already Present', readonly=True)

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
        if self.ingestion_done:
            raise ValidationError(_("This ingestion has already been completed. Close this result and open a new pull to run again."))
        if self.cycle_id.state not in ('draft', 'collecting'):
            raise ValidationError(_("PMS gaps can only be pulled into a draft or collecting TNA cycle."))
        if 't3.appraisal' not in self.env:
            raise UserError(_("Performance Management (PMS) module is not installed."))

        domain = [
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

        appraisals = self.env['t3.appraisal'].sudo().search(
            domain + self.cycle_id._target_relation_domain())
        if not appraisals:
            self.ingestion_done = True
            self.scanned_count = 0
            self.result_log = _(
                "Scan complete. No PMS appraisals found for the selected period and states (%s)."
            ) % self.state_filter
            return self._return_view()

        TnaEntryModel = self.env['eds.tna.entry'].sudo()
        PmsCourseLine = self.env['eds.course.pms.line'].sudo()
        existing_keys = {
            (entry.employee_id.id, entry.pms_measure_id.id if entry.pms_measure_id
             else (entry.pms_kpi_reference or '').strip().lower())
            for entry in self.cycle_id.entry_ids
            if entry.source == 'pms' and entry.employee_id
        }

        success_count = 0
        skipped_count = 0

        for appraisal in appraisals:
            emp = appraisal.employee_id
            if not emp:
                continue

            appraised_lines = appraisal.line_ids.filtered(
                lambda l: l.appraised == 'yes' and (l.job_measure_id or l.appraisal_criteria)
            )

            work_unit = appraisal.operating_unit_id or self.env['eds.hr.compat'].get_employee_operating_unit(emp)
            job = appraisal.job_id or self.env['eds.hr.compat'].get_employee_job(emp)

            for line in appraised_lines:
                measure = line.job_measure_id
                measure_name = measure.name if measure else (line.appraisal_criteria or '').strip()
                if not measure and measure_name:
                    measure_domain = [('name', '=ilike', measure_name)]
                    if job:
                        measure_domain.append(('job_id', '=', job.id))
                    if work_unit:
                        measure_domain.append(('operating_unit_id', '=', work_unit.id))
                    measure = self.env['performance.job.measure'].sudo().search(
                        measure_domain, limit=1)
                mappings = PmsCourseLine.search([
                    ('job_measure_id', '=', measure.id),
                    ('course_id.status', 'in', ('active', 'draft')),
                ]) if measure else PmsCourseLine.browse()
                line_score = round(line.accomplishment_percent, 1)
                rating = (line.appraisal_rating or '').strip()
                unsatisfactory = rating.casefold() == 'unsatisfactory'
                applicable = mappings.filtered(
                    lambda mapping: unsatisfactory or line_score < mapping.min_threshold)
                if not unsatisfactory and line_score >= self.max_score_threshold and not applicable:
                    continue
                key = (emp.id, measure.id if measure else measure_name.lower())
                if key in existing_keys:
                    skipped_count += 1
                    continue
                existing_keys.add(key)

                # Match configured courses for this PMS measurement
                pms_courses = self.cycle_id._filter_cycle_courses(
                    applicable.mapped('course_id'))
                severity = 'critical' if line_score < 50.0 else ('high' if line_score < 65.0 else 'medium')

                recom_text = line.recommendations.strip() if line.recommendations else ""
                recom_part = _(" Recommendations: %s.") % recom_text if recom_text else ""

                prog_name = pms_courses[0].name if pms_courses else False

                justification = _(
                    "PMS Individual Measurement Gap from Appraisal '%s' (FY: %s, Period: %s). "
                    "Metric: %s (Accomplishment: %.1f%%, Target: %.1f).%s"
                ) % (
                    appraisal.name,
                    appraisal.fiscal_year_id.name if appraisal.fiscal_year_id else 'N/A',
                    appraisal.appraisal_period_id.name if appraisal.appraisal_period_id else 'N/A',
                    measure_name,
                    line_score,
                    line.target or 0.0,
                    recom_part
                )

                TnaEntryModel.create({
                    'cycle_id': self.cycle_id.id,
                    'request_level': 'individual',
                    'employee_id': emp.id,
                    'work_unit_id': work_unit.id if work_unit else False,
                    'department_id': appraisal.department_id.id if appraisal.department_id else (emp.department_id.id if emp.department_id else False),
                    'job_position_id': job.id if job else False,
                    'pms_measure_id': measure.id if measure else False,
                    'pms_measurement_name': measure_name,
                    'pms_kpi_reference': measure_name,
                    'pms_appraisal_score': line_score,
                    'pms_appraisal_rating': rating,
                    'pms_target_type': line.appraisal_type or (measure.target_type if measure else ''),
                    'pms_target_value': line.target or 0.0,
                    'pms_actual_value': line.uploaded_value or 0.0,
                    'course_id': pms_courses[0].id if pms_courses else False,
                    'suggested_course_ids': [(6, 0, pms_courses.ids)],
                    'proposed_program': prog_name,
                    'urgency': severity,
                    'gap_severity': severity,
                    'priority_score': max(1.0, round(100.0 - line_score, 1)),
                    'source': 'pms',
                    'delivery_mode': 'classroom',
                    'justification': justification,
                    'state': 'submitted',
                })
                success_count += 1

        summary = _(
            "PMS Performance Gap Ingestion Complete:\n"
            "- Appraisals Scanned: %d\n"
            "- Successfully Created TNA Entries (Measurement Gaps): %d\n"
            "- Skipped (Already Present): %d\n"
            "- Max Score Threshold Applied: %.1f%%"
        ) % (len(appraisals), success_count, skipped_count, self.max_score_threshold)

        self.write({
            'ingestion_done': True,
            'scanned_count': len(appraisals),
            'created_count': success_count,
            'skipped_count': skipped_count,
            'result_log': summary,
        })
        self.cycle_id.message_post(body=_(
            "Diagnostic Ingestion: %d PMS performance gap entries pulled into cycle '%s'."
        ) % (success_count, self.cycle_id.name))
        self.cycle_id._mark_course_demand_dirty()
        self.cycle_id._sync_course_demand()

        return self._return_view()

    def _return_view(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.pms.gap.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
