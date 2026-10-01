# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsTnaExcludeWizard(models.TransientModel):
    _name = 'eds.tna.exclude.wizard'
    _description = 'Exclude Training Need Wizard'

    entry_id = fields.Many2one('eds.tna.entry', string='Training Need', required=True, readonly=True)
    employee_id = fields.Many2one('hr.employee', related='entry_id.employee_id', readonly=True)
    proposed_program = fields.Char(related='entry_id.proposed_program', readonly=True)
    exclusion_type = fields.Selection([
        ('duplicate', 'Duplicate Request (Already Submitted / Active)'),
        ('process', 'Process Issue (Requires Operational / Workflow Change, Not Training)'),
        ('system', 'System / Technical Issue (IT Bug / System Configuration, Not Training)'),
        ('structural', 'Structural Issue (Staffing Shortage / Policy, Not Training)'),
        ('other', 'Other Discretionary / Out of Scope'),
    ], string='Exclusion Category', required=True, default='duplicate')
    excluded_reason = fields.Text(
        string='Exclusion Justification', required=True)

    def action_confirm_exclusion(self):
        self.ensure_one()
        if not self.excluded_reason or not self.excluded_reason.strip():
            raise UserError(_('Please provide a valid exclusion justification.'))
        self.entry_id.write({
            'state': 'excluded',
            'exclusion_type': self.exclusion_type,
            'excluded_reason': self.excluded_reason.strip(),
        })
        category_label = dict(self._fields['exclusion_type'].selection).get(self.exclusion_type)
        self.entry_id.message_post(
            body=_("Training need excluded from TNA.<br/><b>Category:</b> %s<br/><b>Reason:</b> %s") % (
                category_label, self.excluded_reason.strip()))
        return {'type': 'ir.actions.act_window_close'}
