from datetime import datetime

from odoo import _, api, fields, models

class projection_increment_letter(models.AbstractModel):
    _name = 'report.cortex_hr_addons.report_increment_letter'

    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        docs = self.env["employee.increment"].search([("id","=",docids[0])])
        return {
              'doc_ids': docids,
              'doc_model': "employee.increment",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
