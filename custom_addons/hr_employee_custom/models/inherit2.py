from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import datetime

class Job(models.Model):
    _inherit = "hr.job"
    e_mail_id = fields.Char(string="E Mail", store=False)
    recruitment_reference = fields.Char(string="Recruitment Reference")


class HolidaysRequest(models.Model):
    _inherit = "hr.leave"
    job_grade = fields.Char(string="Job Grade", required=False)

class HrContract(models.Model):
    _inherit = 'hr.version'

    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('forwarded', 'Forwarded'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Approval Status", default="draft")
    over_hour = fields.Float(compute='_compute_hour_wage', string='Hour Wage')

    @api.depends('wage')
    def _compute_hour_wage(self):
        for record in self:
            if record.wage:
                record.over_hour = record.wage / 176
            else:
                record.over_hour = 0.0


    # over_hour = fields.Float("Hour_Wage", store=True)
    # over_hour = fields.Monetary('Hour Wage')

    # def hour_wage(self):
    #      self.over_hour = self.wage/176;
    
class Job(models.Model):
    _inherit = 'hr.job'

    state = fields.Selection([
        ('recruit', 'Recruitment in Progress'),
        ('open', 'Not Recruiting')
    ], string='Status', readonly=True, required=True, tracking=True, copy=False, default='open',
        help="Set whether the recruitment process is open or closed for this job position.")



# class MyStockReturnReques(models.Model):
#     _inherit = 'stock.return.request.line'
#
#     asset_name = fields.Many2one('account.asset', string="Asset Name", domain="[('location','=',parent.return_from)]")
#
#     @api.depends('parent.return_from')
#     def _compute_asset_name_domain(self):
#         for line in self:
#             line.asset_name_domain = [('location','=',line.parent.return_from)]

# class Hr(models.Model):
#     _inherit = 'hr.employee'
#
#     job_category = fields.Char(string="Job Category")
    # , compute="_compute_job_category")

    # @api.depends('job_position')
    # def _compute_job_category(self):
    #     val = self.env["hr.job"].search([("name", "=", self.job_position)])
    #     print("**********val", val)
    #     self.job_category = val.employee_category
    #     return self.job_category
