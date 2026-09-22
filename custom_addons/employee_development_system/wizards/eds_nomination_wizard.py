# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsNominationWizard(models.TransientModel):
    """\"Nominate for Session\" wizard (, ...030).

    The officer picks a session, the eligible employees and - for TNA-based
    nominations - the source training needs. One nomination per employee is created
    and submitted directly into the approval chain. Employees whose approved TNA
    need is provided are nominated TNA-based; the rest fall back to ad-hoc and
    therefore require a justification + L&D approval .
    """
    _name = 'eds.nomination.wizard'
    _description = 'Nominate Employees for a Session'

    session_id = fields.Many2one(
        'eds.session', string='Session', required=True,
        domain="[('status', 'in', ('scheduled', 'ongoing', 'rescheduled'))]")
    course_name = fields.Char(string='Program', related='session_id.program_name', readonly=True)
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        help='Employees to nominate for this session.')
    nomination_type = fields.Selection([
        ('tna_based', 'TNA-Based'),
        ('ad_hoc', 'Ad-Hoc (Justified Exception)'),
    ], string='Nomination Type', default='tna_based', required=True)
    tna_entry_ids = fields.Many2many(
        'eds.tna.entry', string='Source TNA Needs',
        domain="[('state', 'in', ('approved', 'converted')), "
               "('delivery_mode', 'in', ('classroom', 'blended'))]",
        help='Approved training needs to link. The wizard links each employee to their '
             'own need automatically .')
    justification = fields.Text(
        string='Justification',
        help='Mandatory when nominating ad-hoc . Applied to ad-hoc nominations.')

    @api.onchange('session_id')
    def _onchange_session_id(self):
        self.employee_ids = False

    @api.onchange('nomination_type')
    def _onchange_nomination_type(self):
        if self.nomination_type == 'tna_based':
            self.justification = False

    def action_create_nominations(self):
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_('Select at least one employee to nominate.'))
        # Pre-validate: employees without a matching approved TNA need become ad-hoc
        # nominations, which always require a justification .
        missing_entry = any(not self._find_entry_for(emp) for emp in self.employee_ids)
        if (self.nomination_type == 'ad_hoc' or missing_entry) and not self.justification:
            raise UserError(_('Ad-hoc nominations require a mandatory justification '
                              '. Some employees have no matching approved '
                              'training need, so a justification is required.'))
        # Skip employees who already have a nomination for this session (unique constraint
        # on session_id + employee_id, ) instead of failing mid-loop.
        existing = self.env['eds.nomination'].search(
            [('session_id', '=', self.session_id.id),
             ('employee_id', 'in', self.employee_ids.ids),
             ('state', 'not in', ('withdrawn', 'rejected', 'declined'))])
        eligible = self.employee_ids - existing.mapped('employee_id')
        if not eligible:
            raise UserError(_('All selected employees already have a nomination for this '
                              'session .'))
        if len(eligible) != len(self.employee_ids):
            self.session_id.message_post(
                body=_('%d employee(s) skipped - they already have a nomination for this '
                      'session .') % (len(self.employee_ids) - len(eligible)))
        created = self.env['eds.nomination']
        for employee in eligible:
            entry = self._find_entry_for(employee)
            nomination_type = self.nomination_type
            if nomination_type == 'tna_based' and not entry:
                # No matching approved need for this employee -> documented ad-hoc exception.
                nomination_type = 'ad_hoc'
            nomination = self.env['eds.nomination'].create({
                'session_id': self.session_id.id,
                'employee_id': employee.id,
                'nomination_type': nomination_type,
                'tna_entry_id': entry.id if entry else False,
                'justification': self.justification if nomination_type == 'ad_hoc' else False,
            })
            nomination.action_submit()
            created |= nomination
        return {
            'name': _('Nominations'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.nomination',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
            'target': 'current',
        }

    def _find_entry_for(self, employee):
        """The approved TNA need of this employee (per session program if possible)."""
        if not self.tna_entry_ids:
            return self.env['eds.tna.entry']
        matching = self.tna_entry_ids.filtered(
            lambda e: e.employee_id == employee
            and (not self.session_id.course_id
                 or not e.proposed_program
                 or e.proposed_program == self.session_id.course_id.name))
        return matching[:1] if matching else self.env['eds.tna.entry']
