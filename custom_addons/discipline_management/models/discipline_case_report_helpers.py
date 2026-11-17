# -*- coding: utf-8 -*-
import base64
import os
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineCaseReportHelpers(models.Model):
    _inherit = 'discipline.case'

    def action_print_warning_letter(self):
        """Print the formal Disciplinary Sanction / Decision Notice Letter."""
        self.ensure_one()
        if self.is_exonerated_case:
            raise UserError(_("Cannot Print Warning Letter: This case has been Exonerated with no disciplinary penalty. Please print the 'Clearance Certificate' instead."))
        return self.env.ref('discipline_management.action_report_disciplinary_warning_letter').report_action(self)

    def action_print_exoneration_certificate(self):
        """Print the official Exoneration & Clearance Certificate."""
        self.ensure_one()
        if not self.is_exonerated_case:
            raise UserError(_("Cannot Print Clearance Certificate: This case resulted in an active disciplinary penalty. Please print the 'Disciplinary Decision Notice' instead."))
        return self.env.ref('discipline_management.action_report_exoneration_certificate').report_action(self)

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def get_formatted_employee_name(self):
        """Returns formatted full recipient employee name with salutation."""
        self.ensure_one()
        emp = self.sudo().employee_id
        emp_name = emp.name if emp else _('Employee')
        salutation = self.get_salutation_label()
        return f"{salutation} {emp_name}"

    def get_salutation_title_and_first_name(self):
        """Returns formal salutation and first name for letter opening."""
        self.ensure_one()
        emp = self.sudo().employee_id
        emp_name = emp.name if emp else _('Employee')
        salutation = self.get_salutation_label()
        first_name = emp_name.split()[0] if emp_name else _('Employee')
        return f"{salutation} {first_name}"

    def get_sanction_display_text(self):
        """Returns clean human-readable sanction and financial penalty description."""
        self.ensure_one()
        sanction_name = dict(self._fields['punishment_type'].selection).get(
            self.punishment_type, str(self.punishment_type or '')
        )
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(f"{self.penalty_percentage}% monthly basic salary deduction")
        if self.fine_days > 0.0:
            penalty_details.append(f"{int(self.fine_days)} day(s) salary fine")

        if penalty_details:
            return f"{sanction_name} with {' and '.join(penalty_details)}"
        return sanction_name

    def get_signatory_name(self):
        """Returns the formal signatory name based on action track and appeal lifecycle."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            return decided_appeals[0].reviewer_id.name or self.approver_id.name or self.env.user.name
        if self.case_action_track == 'direct_enforce':
            return self.initiator_id.name or self.reported_by_id.name or self.approver_id.name or self.env.user.name
        return self.approver_id.name or self.env.user.name

    def get_signatory_title(self):
        """Returns formal signatory job / authority title based on action track and appeal lifecycle."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            reviewer = last_app.reviewer_id
            if last_app.appeal_target_authority == 'ceo' or (reviewer and reviewer.has_group('discipline_management.group_discipline_ceo')):
                return _("Chief Executive Officer (CEO)")
            elif last_app.appeal_target_authority == 'chief' or (reviewer and (reviewer.has_group('discipline_management.group_discipline_cpco') or reviewer.has_group('discipline_management.group_discipline_chief'))):
                return _("Chief People & Culture Officer (CPCO)")
            elif last_app.appeal_target_authority == 'directorate' or (reviewer and reviewer.has_group('discipline_management.group_discipline_director')):
                return _("Director, Respective Directorate")
            elif last_app.appeal_target_authority == 'secretary' or (reviewer and reviewer.has_group('discipline_management.group_discipline_pomd')):
                return _("POMD / Disciplinary Authority")
            return _("Designated Appeal Authority")

        if self.case_action_track == 'direct_enforce':
            return _("Line Manager / Direct Coach")
        if self.approver_id and hasattr(self.approver_id, 'has_group') and self.approver_id.has_group('discipline_management.group_discipline_ceo'):
            return _("Chief Executive Officer")
        return _("Chief People & Culture Officer / Authorized Executive")

    def get_decision_authority_narrative(self):
        """Returns formal narrative of the deciding authority for the official notice body."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            rev_name = last_app.reviewer_id.name or _("the Appeal Authority")
            title = self.get_signatory_title()
            if last_app.decision_outcome == 'penalty_reduced':
                return _("following executive appeal review by %s (%s), the Bank has resolved to reduce and enforce a revised measure of") % (rev_name, title)
            elif last_app.decision_outcome == 'upheld':
                return _("following executive appeal review by %s (%s), the Bank has upheld the disciplinary finding and enforced a measure of") % (rev_name, title)
            return _("following executive appeal review by %s (%s), the Bank has resolved to enforce a measure of") % (rev_name, title)

        if self.case_action_track == 'direct_enforce':
            return _("your reporting coach / line management has enforced a")
        return _("the Disciplinary Authority has resolved to enforce a")

    def is_appeal_final_and_exhausted(self):
        """Returns True if all appeal levels are concluded or appeal window is definitively closed."""
        self.ensure_one()
        if any(a.appeal_level == 'third' and a.state == 'decided' for a in self.appeal_ids):
            return True
        if self.initiator_type in ('chief', 'committee') and any(a.state == 'decided' for a in self.appeal_ids):
            return True
        if self.initiator_type == 'director' and any(a.appeal_level == 'second' and a.state == 'decided' for a in self.appeal_ids):
            return True
        if not self.is_appeal_window_open and any(a.state == 'decided' for a in self.appeal_ids):
            return True
        return False

    def get_payroll_month_display(self):
        """Returns clean formatted payroll month name (e.g. 'October 2026' or 'October')."""
        self.ensure_one()
        if not self.payroll_month:
            return ''
        month_dict = dict(self._fields['payroll_month'].selection) if 'payroll_month' in self._fields else {}
        month_name = month_dict.get(self.payroll_month, str(self.payroll_month))
        year = self.final_decision_date.year if self.final_decision_date else (self.incident_date.year if self.incident_date else fields.Date.today().year)
        return f"{month_name} {year}"

    def get_signatory_company(self):
        return _("Bunna Bank S.C.")

    def get_discipline_letter_cc_lines(self):
        """Returns formatted CC distribution lines for the official letter."""
        self.ensure_one()
        lines = [
            _("People Operations Management Directorate (POMD) - Personnel File"),
        ]
        if self.department_id:
            lines.append(f"{self.department_id.name} / Respective Directorate")
        else:
            lines.append(_("Respective Directorate / Branch Management"))
        lines.append(_("Internal Audit Directorate"))
        emp = self.sudo().employee_id
        if emp:
            lines.append(f"{emp.name} (Subject Employee)")
        return lines

    @api.model
    def get_discipline_analytics_payload(self, date_from=None, date_to=None):
        """Public API method returning aggregated disciplinary statistics for external HR Analytics integration."""
        domain = []
        if date_from:
            domain.append(('incident_date', '>=', date_from))
        if date_to:
            domain.append(('incident_date', '<=', date_to))

        cases = self.search(domain)
        by_state, by_severity, by_department, by_punishment = {}, {}, {}, {}

        for c in cases:
            st = c.state or 'unknown'
            by_state[st] = by_state.get(st, 0) + 1
            sev = c.severity_level or 'unclassified'
            by_severity[sev] = by_severity.get(sev, 0) + 1
            dept = c.department_id.name if c.department_id else 'Unassigned'
            by_department[dept] = by_department.get(dept, 0) + 1
            pish = c.punishment_type or 'none'
            by_punishment[pish] = by_punishment.get(pish, 0) + 1

        return {
            'total_cases': len(cases),
            'cases_by_state': by_state,
            'cases_by_severity': by_severity,
            'cases_by_department': by_department,
            'cases_by_punishment': by_punishment,
        }


class ReportSuspensionLetter(models.AbstractModel):
    _name = 'report.discipline_management.report_suspension_letter_template'
    _description = 'Official Suspension Letter Report'
    _table = 'report_disc_susp_letter'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.suspension'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.suspension',
            'docs': docs,
        }


class ReportDisciplinaryWarningLetter(models.AbstractModel):
    _name = 'report.discipline_management.report_disciplinary_warning_letter_template'
    _description = 'Disciplinary Warning Letter Report'
    _table = 'report_disc_warn_letter'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.case'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.case',
            'docs': docs,
        }


class ReportExonerationCertificate(models.AbstractModel):
    _name = 'report.discipline_management.report_exoneration_certificate_template'
    _description = 'Official Exoneration Certificate Report'
    _table = 'report_disc_exon_cert'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.case'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.case',
            'docs': docs,
        }


class ReportCommitteeResolution(models.AbstractModel):
    _name = 'report.discipline_management.report_committee_resolution_template'
    _description = 'Disciplinary Committee Hearing Minutes & Resolution Report'
    _table = 'report_disc_comm_res'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.committee.meeting'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.committee.meeting',
            'docs': docs,
        }

