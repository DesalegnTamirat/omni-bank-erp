# -*- coding: utf-8 -*-
from markupsafe import Markup, escape
from odoo import api, fields, models, _


class CompetencyDataValidator(models.Model):
    """Data Quality Automation & Governance Validator for Competency Data."""
    _name = 'competency.data.validator'
    _description = 'Competency Data Quality & Governance Validator'
    _auto = False  # No DB table created — keeps it lightweight

    @api.model
    def _cron_validate_competency_data_quality(self):
        """Audit active roles without approved competency mapping in 1 query."""
        Job = self.env['hr.job']
        Mapping = self.env['competency.role.mapping']
        
        active_jobs = Job.search([('active', '=', True)])
        mapped_job_ids = set(Mapping.search([('state', '=', 'approved')]).mapped('job_position_id.id'))
        unmapped_jobs = active_jobs.filtered(lambda j: j.id not in mapped_job_ids).mapped('name')

        if unmapped_jobs:
            admin_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
            admins = getattr(admin_group, 'users', getattr(admin_group, 'user_ids', self.env['res.users'])) if admin_group else self.env['res.users']
            body = Markup(_(
                "<b>Competency Data Quality Audit Report</b><br/>"
                "• Active Roles Missing Approved Mapping (%s): %s"
            )) % (
                len(unmapped_jobs), escape(", ".join(unmapped_jobs[:10]) or "None")
            )
            partner_ids = admins.mapped('partner_id').ids
            if partner_ids:
                try:
                    self.env['mail.thread'].message_notify(
                        partner_ids=partner_ids,
                        subject=_("Data Quality Audit Alert: Competency Management"),
                        body=body
                    )
                except Exception:
                    pass
