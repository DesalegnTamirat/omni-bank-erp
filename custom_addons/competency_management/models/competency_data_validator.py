# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CompetencyDataValidator(models.AbstractModel):
    """Data Quality Automation & Governance Validator for Competency Data (FR-DQ-COM-001..003)."""
    _name = 'competency.data.validator'
    _description = 'Competency Data Quality & Governance Validator'

    @api.model
    def _cron_validate_competency_data_quality(self):
        """Daily cron: Audit framework integrity, unmapped roles, non-approved framework references, and mandatory IDP compliance."""
        Job = self.env['hr.job']
        Mapping = self.env['competency.role.mapping']
        MappingLine = self.env['competency.role.mapping.line']
        AssessmentLine = self.env['competency.assessment.line']
        IDP = self.env['competency.idp']
        
        # 1. Active roles without approved competency mapping
        active_jobs = Job.search([('active', '=', True)])
        unmapped_jobs = []
        for job in active_jobs:
            has_mapping = Mapping.search_count([('job_position_id', '=', job.id), ('state', '=', 'approved')])
            if not has_mapping:
                unmapped_jobs.append(job.name)
                
        # 2. Mandatory IDPs remaining unapproved > 14 days
        today = fields.Date.context_today(self)
        pending_idps = IDP.search([('mandatory', '=', True), ('state', 'in', ['draft', 'submitted'])])
        overdue_idps = []
        for idp in pending_idps:
            if idp.create_date:
                days = (today - idp.create_date.date()).days
                if days >= 14:
                    overdue_idps.append(idp.name)

        # 3. Lines referencing competencies with no approved framework
        unapproved_mapping_lines = MappingLine.search([('competency_id.approved_framework_ids', '=', False)])
        unapproved_assessment_lines = AssessmentLine.search([('competency_id.approved_framework_ids', '=', False)])

        if unmapped_jobs or overdue_idps or unapproved_mapping_lines or unapproved_assessment_lines:
            admin_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
            admins = admin_group.user_ids if admin_group else self.env['res.users']
            body = _(
                "<b>Competency Data Quality Audit Report</b><br/>"
                "• Active Roles Missing Approved Mapping (%s): %s<br/>"
                "• Overdue Mandatory IDPs (>14 days unapproved) (%s): %s<br/>"
                "• Role Mapping Lines with Non-Approved Competencies: %s<br/>"
                "• Assessment Lines with Non-Approved Competencies: %s"
            ) % (
                len(unmapped_jobs), ", ".join(unmapped_jobs[:10]) or "None",
                len(overdue_idps), ", ".join(overdue_idps[:10]) or "None",
                len(unapproved_mapping_lines),
                len(unapproved_assessment_lines)
            )
            for admin in admins:
                self.env['mail.thread'].message_notify(
                    partner_ids=admin.partner_id.ids,
                    subject=_("Data Quality Audit Alert: Competency Framework"),
                    body=body
                )
