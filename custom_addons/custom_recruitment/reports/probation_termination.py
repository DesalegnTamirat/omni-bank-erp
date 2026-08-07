# -*- coding: utf-8 -*-
from odoo import api, models


class ReportProbationRevocation(models.AbstractModel):
    _name = 'report.custom_recruitment.report_probation_revocation'
    _description = 'Probation Termination Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["hr.version"].search([("id", "=", docids[0])])
        return {
            'doc_ids': docids,
            'doc_model': "hr.version",
            'docs': docs,
            'data': data,
        }
