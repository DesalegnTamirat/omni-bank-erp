from datetime import datetime

from odoo import _, api, fields, models

class projection_offer_letter(models.AbstractModel):
    _name = 'report.cortex_hr_addons.report_offer_letter'

    @api.model
    def _get_report_values(self,docids,data=None):
        #docs = self.env[model.model].search([])
        # docs = self.env["account.asset"].search([])

        docs = self.env["hr.applicant"].search([("id","=",docids[0])])
        return {
              'doc_ids': docids,
              'doc_model': "hr.applicant",
              'docs': docs,
              'data': data,
              # 'compare_date':datetime.strptime(data["line_date"],"%Y-%m-%d").date(),
        }
        
    @api.model
    def get_data_from_employee_grade(self, record_id):
        # Fetch data from related_model_1
        # Return the data as a dictionary
        return {
            'base_salary': base_salary,
            # 'field_2': value_2,
            # Add more fields as needed
        }
