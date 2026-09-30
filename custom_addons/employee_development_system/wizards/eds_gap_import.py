# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError


class EdsCompetencyGapImport(models.TransientModel):
    """Direct Competency Gap Ingestion Wizard for TNA Cycles.

    Pulls assessed gaps from finalized (closed) Competency Assessment Cycles
    in the Competency Management module directly into TNA entries without CSV uploads.
    """
    _name = 'eds.competency.gap.import'
    _description = 'Pull Competency Gaps from Closed Assessment Cycle'

    cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle', required=True)
    competency_cycle_id = fields.Many2one(
        'competency.assessment.cycle',
        string='Closed Competency Assessment Cycle',
        required=True,
        domain="[('state', '=', 'closed')]",
        help='Only finalized and closed competency assessment cycles can be ingested into TNA.'
    )
    min_gap = fields.Integer(
        string='Minimum Gap Threshold',
        default=1,
        required=True,
        help='Only pull gaps where Required Level minus Current Rating is at least this value.'
    )
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

    def action_pull_competency_gaps(self):
        """Query assessment lines from the selected closed cycle and generate TNA entries."""
        self.ensure_one()
        if not self.competency_cycle_id:
            raise ValidationError(_("Please select a closed Competency Assessment Cycle."))
        if self.competency_cycle_id.state != 'closed':
            raise ValidationError(_("Only closed competency cycles can be ingested into TNA."))

        domain = [
            ('cycle_id', '=', self.competency_cycle_id.id),
            ('gap', '>=', self.min_gap),
            ('active', '=', True),
            ('tna_measure', '=', 'below'),
            ('employee_id.active', '=', True),
        ]
        if self.operating_unit_id:
            domain.append(('operating_unit_id', '=', self.operating_unit_id.id))
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))

        assessment_lines = self.env['competency.assessment.line'].sudo().search(domain)
        if not assessment_lines:
            self.result_log = _(
                "Scan complete for closed cycle '%s'. No assessment lines found matching the gap criteria (min gap >= %d)."
            ) % (self.competency_cycle_id.name, self.min_gap)
            return self._return_view()

        TnaEntryModel = self.env['eds.tna.entry'].sudo()
        existing_keys = set(
            self.cycle_id.entry_ids.filtered(lambda e: e.employee_id and e.competency_id).mapped(
                lambda e: (e.employee_id.id, e.competency_id.id)
            )
        )

        success_count = 0
        skipped_count = 0

        for line in assessment_lines:
            if not line.employee_id or not line.competency_id:
                continue
            key = (line.employee_id.id, line.competency_id.id)
            if key in existing_keys:
                skipped_count += 1
                continue
            existing_keys.add(key)

            gap_val = line.gap or (int(line.required_level or 2) - int(line.current_level or 1))
            if gap_val < self.min_gap:
                continue

            severity = 'critical' if gap_val >= 3 else ('high' if gap_val == 2 else 'medium')
            emp = line.employee_id
            work_unit = line.operating_unit_id or self.env['eds.hr.compat'].get_employee_operating_unit(emp)
            job = line.job_id or self.env['eds.hr.compat'].get_employee_job(emp)

            TnaEntryModel.create({
                'cycle_id': self.cycle_id.id,
                'employee_id': emp.id,
                'work_unit_id': work_unit.id if work_unit else False,
                'department_id': line.department_id.id if line.department_id else (emp.department_id.id if emp.department_id else False),
                'job_position_id': job.id if job else False,
                'competency_id': line.competency_id.id,
                'competency_gap_level_diff': gap_val,
                'gap_severity': severity,
                'urgency': severity,
                'source': 'competency_gap',
                'delivery_mode': 'classroom',
                'proposed_program': _("%s Mastery Program") % line.competency_id.name,
                'justification': _(
                    "Competency Gap diagnostic from Closed Assessment Cycle '%s'. Required Level: %s, Current Level: %s (Gap: %d)."
                ) % (self.competency_cycle_id.name, line.required_level or '2', line.current_level or '1', gap_val),
                'state': 'submitted',
            })
            success_count += 1

        summary = _(
            "Competency Gap Ingestion Complete:\n"
            "- Source Closed Cycle: %s\n"
            "- Successfully Created TNA Entries: %d\n"
            "- Skipped (Already Present): %d\n"
            "- Minimum Gap Threshold Applied: %d"
        ) % (self.competency_cycle_id.name, success_count, skipped_count, self.min_gap)

        self.result_log = summary
        self.cycle_id.message_post(body=_(
            "Diagnostic Ingestion: %d competency gap entries pulled from closed cycle '%s'."
        ) % (success_count, self.competency_cycle_id.name))

        return self._return_view()

    def _return_view(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.competency.gap.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
