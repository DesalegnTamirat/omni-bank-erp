from datetime import datetime

from odoo import _, api, fields, models

class projection_detail_acting_assignment(models.AbstractModel):
    _name = 'report.custom_recruitment.report_minute_template'

    @api.model
    def _get_report_values(self,docids,data=None):
        docs = self.env["job.vacancy"].search([("id","=",docids[0])])
        return {
              'doc_ids': docids,
              'doc_model': "job.vacancy",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
