from odoo import _, api, fields, models

class projection_detail_acting_assignment(models.AbstractModel):
    _name = 'report.cortex_hr_addons.report_acting_termination'

    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        docs = self.env["supplementary.role"].search([])
        return {
              'doc_ids': docids,
              'doc_model': "supplementary.role",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
