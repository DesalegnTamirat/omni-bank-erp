from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslLoanReplacementWizard(models.TransientModel):
    _name = 'resl.loan.replacement.wizard'
    _description = 'Guarantor Replacement Wizard'

    loan_id = fields.Many2one(
        comodel_name='resl.loan', string='Loan', required=True
    )
    loan_employee_id = fields.Many2one(
        comodel_name='hr.employee', string='Borrower',
        related='loan_id.employee_id', readonly=True, store=False
    )
    # Single old guarantee (borrower flow)
    old_guarantee_id = fields.Many2one(
        'resl.loan.guarantee', string='Current Guarantor Line',
        domain="[('loan_id','=',loan_id)]",
    )
    # Multi old guarantees (HR flow)
    old_guarantee_ids = fields.Many2many(
        'resl.loan.guarantee', string='Current Guarantor Lines (HR)',
        domain="[('loan_id','=',loan_id)]",
    )
    guarantor_name = fields.Char(
        string='Current Guarantor', compute='_compute_guarantor_name'
    )
    new_guarantor_id = fields.Many2one(
        'hr.employee', string='New Guarantor', required=True
    )
    replacement_reason = fields.Text(string='Replacement Reason')
    manual_request = fields.Boolean(string='Manual Request', default=False)
    is_hr_action = fields.Boolean(string='HR Action', default=False)

    @api.depends('old_guarantee_id', 'old_guarantee_ids')
    def _compute_guarantor_name(self):
        for rec in self:
            names = []
            if rec.old_guarantee_id and rec.old_guarantee_id.guarantor_id:
                names.append(rec.old_guarantee_id.guarantor_id.name or '')
            for g in rec.old_guarantee_ids:
                if g.guarantor_id and g.guarantor_id.name:
                    names.append(g.guarantor_id.name)
            rec.guarantor_name = ', '.join(names) if names else ''

    def action_confirm(self):
        self.ensure_one()
        loan = self.loan_id
        new_emp = self.new_guarantor_id

        # Determine which old guarantee lines to replace
        if self.is_hr_action and self.old_guarantee_ids:
            old_lines = self.old_guarantee_ids
        elif self.old_guarantee_id:
            old_lines = self.old_guarantee_id
        else:
            # Fall back to all separated lines
            old_lines = loan.guarantor_line_ids.filtered(lambda l: l.state == 'separated')

        if not old_lines:
            raise ValidationError(_("No guarantor line selected for replacement."))

        ctx = dict(self.env.context or {})
        ctx.update({
            'default_is_hr_action': self.is_hr_action,
            'default_manual_request': self.manual_request,
        })

        for old_line in old_lines:
            loan.with_context(**ctx).nominate_replacement(old_line.id, new_emp.id)

        # Log the replacement(s)
        log_obj = self.env['resl.loan.replacement.log']
        for old_line in old_lines:
            try:
                log_obj.create({
                    'loan_id': loan.id,
                    'old_guarantor_id': old_line.guarantor_id.id,
                    'new_guarantor_id': new_emp.id,
                    'action_by': self.env.uid,
                    'is_hr_action': self.is_hr_action,
                    'reason': self.replacement_reason or '',
                })
            except Exception:
                _logger.exception("Failed to create replacement log entry")

        return {'type': 'ir.actions.act_window_close'}