from odoo import api, fields, models, _


class ReslLoanReplacementLog(models.Model):
    _name = "resl.loan.replacement.log"
    _description = "Loan Guarantor Replacement Log"
    _rec_name = "loan_id"
    _order = "create_date desc"

    loan_id = fields.Many2one(
        "resl.loan", string="Loan", required=True, ondelete="cascade"
    )
    old_guarantor_id = fields.Many2one(
        "hr.employee", string="Old Guarantor", required=True
    )
    new_guarantor_id = fields.Many2one(
        "hr.employee", string="New Guarantor", required=True
    )
    action_by = fields.Many2one(
        "res.users", string="Action By", required=True,
        default=lambda self: self.env.uid
    )
    is_hr_action = fields.Boolean(string="Performed by HR")
    reason = fields.Text(string="Replacement Reason")
    create_date = fields.Datetime(string="Created On", readonly=True)
