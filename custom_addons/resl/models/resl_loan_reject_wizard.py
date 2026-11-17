from odoo import fields, models, _
from odoo.exceptions import ValidationError


class ReslLoanRejectWizard(models.TransientModel):
    """Justification dialog shown when an approver rejects a request.

    The comment is MANDATORY for everybody on the approval side (approver,
    HR Auditor, HR Accountant, disbursement officer such as the Branch
    Accountant). Guarantors are not asked: they can reject without a comment
    (resl.loan.guarantee.action_reject).
    """
    _name = 'resl.loan.reject.wizard'
    _description = 'Loan Rejection Justification'

    loan_id = fields.Many2one('resl.loan', string='Loan', required=True, readonly=True)
    reject_kind = fields.Selection([
        ('manager', 'Approver rejection'),
        ('after_approval', 'Rejection after approval'),
    ], string='Rejection Type', required=True, readonly=True)
    reason = fields.Text(
        string='Comment / Justification', required=True,
        help="Why is this request rejected? Required.",
    )

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise ValidationError(_(
                "A comment (justification) is required to reject a request."
            ))
        loan = self.loan_id
        if self.reject_kind == 'after_approval':
            loan._do_reject_after_approval(reason)
        else:
            loan._do_manager_reject(reason)
        return {'type': 'ir.actions.act_window_close'}
