# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CompetencyDataValidator(models.AbstractModel):
    """Data Quality Automation & Governance Validator for Competency Data."""
    _name = 'competency.data.validator'
    _description = 'Competency Data Quality & Governance Validator'

    @api.model
    def _cron_validate_competency_data_quality(self):
        """Daily cron: Audit active roles without approved competency mapping."""
        Job = self.env['hr.job']
        Mapping = self.env['competency.role.mapping']
        
        # 1. Active roles without approved competency mapping
        active_jobs = Job.search([('active', '=', True)])
        unmapped_jobs = []
        for job in active_jobs:
            has_mapping = Mapping.search_count([('job_position_id', '=', job.id), ('state', '=', 'approved')])
            if not has_mapping:
                unmapped_jobs.append(job.name)

        if unmapped_jobs:
            admin_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
            admins = admin_group.user_ids if admin_group else self.env['res.users']
            body = _(
                "<b>Competency Data Quality Audit Report</b><br/>"
                "• Active Roles Missing Approved Mapping (%s): %s"
            ) % (
                len(unmapped_jobs), ", ".join(unmapped_jobs[:10]) or "None"
            )
            for admin in admins:
                self.env['mail.thread'].message_notify(
                    partner_ids=admin.partner_id.ids,
                    subject=_("Data Quality Audit Alert: Competency Management"),
                    body=body
                )
