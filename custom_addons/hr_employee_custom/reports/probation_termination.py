from datetime import datetime

from odoo import _, api, fields, models

class projection_detail_acting_probation_revocation(models.AbstractModel):
    _name = 'report.hr_employee_custom.report_probation_revocation'

    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        docs = self.env["hr.version"].search([("id", "=", docids[0])])
        return {
              'doc_ids': docids,
              'doc_model': "hr.version",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
