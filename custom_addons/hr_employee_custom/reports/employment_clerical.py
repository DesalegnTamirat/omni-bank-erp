from datetime import datetime

from odoo import _, api, fields, models


class employment_clerical(models.AbstractModel):
    _name = 'report.hr_employee_custom.report_employment_clerical'
    


    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        # docs = self.env["hr.applicant"].search([])
        docs = self.env["hr.applicant"].search([("id","=",docids[0])])
        
        # print("my_data", type(data["line_date"]),docs[0]["depreciation_line_ids"][0]["line_date"])
        return {
              'doc_ids': docids,
              'doc_model': "hr.applicant",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }

    # @api.model
    # def _get_report_values(self,docids,data=None):
        # print("reports=======================================")
        # #docs = self.env[model.model].search([])
        # # docs = self.env["account.asset"].search([])
        # docs = self.env["hr.applicant"].search([("name","!="," ")])
        # print("docs==========================",docs)
        # # print("my_data", type(data["line_date"]),docs[0]["depreciation_line_ids"][0]["line_date"])
        # return {
              # 'doc_ids': docids,
              # 'doc_model': "hr.applicant",
              # 'docs': docs[-1],
              # 'data': data,
              # # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        # }
