from datetime import datetime

from odoo import _, api, fields, models

class projection_non_mangeriald_same_location_voucher(models.AbstractModel):
    _name = 'report.cortex_hr_addons.report_non_managerial_same_location'

    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        docs = self.env["hr.applicant"].search([])
        # print("my_data", type(data["line_date"]),docs[0]["depreciation_line_ids"][0]["line_date"])
        return {
              'doc_ids': docids,
              'doc_model': "hr.applicant",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
