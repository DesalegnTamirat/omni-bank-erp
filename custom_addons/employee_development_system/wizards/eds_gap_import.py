# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import csv
import io

class EdsCompetencyGapImport(models.TransientModel):
    """Bulk Competency Gap Assessment Importer for TNA Cycles."""
    _name = 'eds.competency.gap.import'
    _description = 'Bulk Competency Gap Importer'

    cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle', required=True)
    csv_file = fields.Binary(string='Competency Gap Sheet (CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Generate and download sample CSV template for Competency Gaps."""
        sample_csv = (
            "employee_badge,competency_name_or_code,required_level,current_level,gap_severity,notes\n"
            "EMP001,Credit Risk Assessment,3,1,critical,Branch loan portfolio assessment\n"
            "EMP002,AML & CFT Compliance,3,2,medium,Annual regulatory compliance audit\n"
            "EMP003,Customer Service Excellence,2,1,high,Branch service evaluation\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_competency_gaps(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select a Competency Gap CSV file to import."))

        try:
            data = base64.b64decode(self.csv_file)
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to parse CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []

        EmployeeModel = self.env['hr.employee']
        CompetencyModel = self.env['competency.competency']
        TnaEntryModel = self.env['eds.tna.entry']

        for line_no, row in enumerate(reader, start=2):
            badge = (row.get('employee_badge') or '').strip()
            comp_name = (row.get('competency_name_or_code') or '').strip()
            req_lvl = (row.get('required_level') or '2').strip()
            cur_lvl = (row.get('current_level') or '1').strip()
            severity = (row.get('gap_severity') or 'medium').strip().lower()
            notes = (row.get('notes') or '').strip()

            if not badge or not comp_name:
                errors.append(_("Row %d: Missing employee badge or competency.") % line_no)
                skipped_count += 1
                continue

            # Match employee
            emp = EmployeeModel.search([
                '|', '|',
                ('identification_id', '=', badge),
                ('barcode', '=', badge),
                ('name', '=ilike', badge)
            ], limit=1)

            if not emp:
                errors.append(_("Row %d: Employee '%s' not found.") % (line_no, badge))
                skipped_count += 1
                continue

            # Match competency
            comp = CompetencyModel.search([
                '|', ('name', '=ilike', comp_name), ('code', '=ilike', comp_name)
            ], limit=1)

            if not comp:
                # Create draft or fallback
                comp = CompetencyModel.search([('name', 'ilike', comp_name)], limit=1)

            # Calculate gap
            try:
                r_num = int(req_lvl) if req_lvl.isdigit() else 2
                c_num = int(cur_lvl) if cur_lvl.isdigit() else 1
                gap_diff = max(0, r_num - c_num)
            except Exception:
                gap_diff = 1

            valid_severity = severity if severity in ('critical', 'high', 'medium', 'low') else 'medium'

            # Avoid duplicates within same cycle
            existing = TnaEntryModel.search([
                ('cycle_id', '=', self.cycle_id.id),
                ('employee_id', '=', emp.id),
                ('competency_id', '=', comp.id if comp else False),
            ], limit=1)

            if existing:
                skipped_count += 1
                continue

            TnaEntryModel.create({
                'cycle_id': self.cycle_id.id,
                'employee_id': emp.id,
                'work_unit_id': getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id.id or False,
                'department_id': emp.department_id.id if emp.department_id else False,
                'job_position_id': emp.job_position.id if emp.job_position else False,
                'competency_id': comp.id if comp else False,
                'competency_gap_level_diff': gap_diff,
                'gap_severity': valid_severity,
                'source': 'competency_gap',
                'delivery_mode': 'classroom',
                'proposed_program': comp.name + _(" Competency Enhancement") if comp else (comp_name + " Training"),
                'justification': notes or _("External Competency Gap Assessment (Req: %s, Cur: %s, Gap: %d)") % (req_lvl, cur_lvl, gap_diff),
                'state': 'submitted',
            })
            success_count += 1

        summary = _("Import Complete:\n- Successfully Ingested: %d\n- Skipped / Duplicate: %d") % (success_count, skipped_count)
        if errors:
            summary += "\n\n" + _("Errors:") + "\n" + "\n".join(errors[:20])

        self.result_log = summary
        self.cycle_id.message_post(body=_("Competency Gap Batch Import: %d entries created.") % success_count)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.competency.gap.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class EdsPmsGapImport(models.TransientModel):
    """Bulk Performance Management (PMS) Gap Importer for TNA Cycles."""
    _name = 'eds.pms.gap.import'
    _description = 'Bulk PMS Appraisal Gap Importer'

    cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle', required=True)
    csv_file = fields.Binary(string='PMS Appraisal Gap Sheet (CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Generate and download sample CSV template for PMS Gaps."""
        sample_csv = (
            "employee_badge,kpi_or_objective,proposed_training,appraisal_score,gap_severity,notes\n"
            "EMP001,Non-Performing Loan Reduction,Advanced NPL Management & Remediation,58.5,critical,Underperforming branch portfolio\n"
            "EMP002,Digital Banking Adoption,Omnichannel Digital Onboarding & CX,64.0,high,Customer migration rate below target\n"
            "EMP003,Internal Audit Adherence,Operational Risk & Branch Compliance,70.0,medium,Minor procedural variances noted\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_pms_gaps(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select a PMS Gap CSV file to import."))

        try:
            data = base64.b64decode(self.csv_file)
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to parse CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []

        EmployeeModel = self.env['hr.employee']
        TnaEntryModel = self.env['eds.tna.entry']

        for line_no, row in enumerate(reader, start=2):
            badge = (row.get('employee_badge') or '').strip()
            kpi_ref = (row.get('kpi_or_objective') or '').strip()
            proposed = (row.get('proposed_training') or '').strip()
            score_str = (row.get('appraisal_score') or '0').strip()
            severity = (row.get('gap_severity') or 'medium').strip().lower()
            notes = (row.get('notes') or '').strip()

            if not badge or not proposed:
                errors.append(_("Row %d: Missing employee badge or proposed training.") % line_no)
                skipped_count += 1
                continue

            emp = EmployeeModel.search([
                '|', '|',
                ('identification_id', '=', badge),
                ('barcode', '=', badge),
                ('name', '=ilike', badge)
            ], limit=1)

            if not emp:
                errors.append(_("Row %d: Employee '%s' not found.") % (line_no, badge))
                skipped_count += 1
                continue

            try:
                score_val = float(score_str)
            except ValueError:
                score_val = 0.0

            valid_severity = severity if severity in ('critical', 'high', 'medium', 'low') else 'medium'

            existing = TnaEntryModel.search([
                ('cycle_id', '=', self.cycle_id.id),
                ('employee_id', '=', emp.id),
                ('proposed_program', '=ilike', proposed),
            ], limit=1)

            if existing:
                skipped_count += 1
                continue

            TnaEntryModel.create({
                'cycle_id': self.cycle_id.id,
                'employee_id': emp.id,
                'work_unit_id': getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id.id or False,
                'department_id': emp.department_id.id if emp.department_id else False,
                'job_position_id': emp.job_position.id if emp.job_position else False,
                'pms_kpi_reference': kpi_ref,
                'pms_appraisal_score': score_val,
                'gap_severity': valid_severity,
                'source': 'pms',
                'delivery_mode': 'classroom',
                'proposed_program': proposed,
                'justification': notes or _("PMS Performance Appraisal Gap: %s (Score: %.1f%%)") % (kpi_ref, score_val),
                'state': 'submitted',
            })
            success_count += 1

        summary = _("Import Complete:\n- Successfully Ingested: %d\n- Skipped / Duplicate: %d") % (success_count, skipped_count)
        if errors:
            summary += "\n\n" + _("Errors:") + "\n" + "\n".join(errors[:20])

        self.result_log = summary
        self.cycle_id.message_post(body=_("PMS Appraisal Gap Batch Import: %d entries created.") % success_count)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.pms.gap.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
