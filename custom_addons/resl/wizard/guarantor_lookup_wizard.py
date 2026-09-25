from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslGuarantorLookup(models.TransientModel):
    _name = 'resl.guarantor.lookup'
    _description = 'Guarantor Employee Lookup Wizard'

    loan_id = fields.Many2one('resl.loan', string='Loan')
    query = fields.Char(string='Search Query')
    line_ids = fields.One2many(
        'resl.guarantor.lookup.line', 'wizard_id', string='Results'
    )

    def action_search(self):
        self.ensure_one()
        query = (self.query or '').strip()
        domain = [('active', '=', True)]
        if query:
            domain += ['|', ('name', 'ilike', query), ('job_title', 'ilike', query)]
        employees = self.env['hr.employee'].sudo().search(domain, limit=50)
        # Exclude the borrower
        if self.loan_id and self.loan_id.employee_id:
            employees = employees.filtered(lambda e: e.id != self.loan_id.employee_id.id)
        # Remove stale lines
        self.line_ids.unlink()
        lines = []
        for emp in employees:
            lines.append({
                'wizard_id': self.id,
                'employee_id': emp.id,
                'name': emp.name,
                'job_title': emp.job_title or '',
            })
        self.env['resl.guarantor.lookup.line'].create(lines)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resl.guarantor.lookup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_clear(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.query = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resl.guarantor.lookup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ReslGuarantorLookupLine(models.TransientModel):
    _name = 'resl.guarantor.lookup.line'
    _description = 'Guarantor Lookup Result Line'

    wizard_id = fields.Many2one('resl.guarantor.lookup', string='Wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    name = fields.Char(string='Employee Name', readonly=True)
    job_title = fields.Char(string='Job Title', readonly=True)

    def action_select(self):
        """Add selected employee as a guarantor on the linked loan."""
        self.ensure_one()
        wizard = self.wizard_id
        if not wizard or not wizard.loan_id or not self.employee_id:
            raise ValidationError(_("Wizard or loan context is missing."))
        loan = wizard.loan_id
        # Create guarantee line in draft state
        self.env['resl.loan.guarantee'].with_context(
            resl_allow_guarantee_create=True
        ).create({
            'loan_id': loan.id,
            'guarantor_id': self.employee_id.id,
            'state': 'draft',
        })
        return {'type': 'ir.actions.act_window_close'}
