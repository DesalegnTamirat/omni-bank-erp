# -*- coding: utf-8 -*-
"""Select an approved EDS decision and download its approval minute."""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


# The same state policy is used by the dropdown domains and by the download guard.
APPROVAL_SOURCES = {
    'annual_plan': {
        'field': 'annual_plan_id', 'model': 'eds.annual.plan',
        'states': ('published',),
    },
    'unscheduled_request': {
        'field': 'unscheduled_request_id', 'model': 'eds.unscheduled.request',
        'states': ('approved',),
    },
    'vendor_selection': {
        'field': 'vendor_selection_id', 'model': 'eds.course.vendor.selection',
        'states': ('awarded',),
    },
    'hotel_selection': {
        'field': 'hotel_selection_id', 'model': 'eds.hotel.selection',
        'states': ('awarded',),
    },
    'sponsorship': {
        'field': 'sponsorship_id', 'model': 'eds.sponsorship',
        # Approval remains valid after the bond advances through its lifecycle.
        'states': ('approved', 'active', 'completed', 'breached'),
    },
    'tna_consolidation': {
        'field': 'tna_consolidation_id', 'model': 'eds.tna.consolidation',
        'states': ('approved', 'locked'),
    },
    'rfp': {
        'field': 'rfp_id', 'model': 'eds.rfp',
        'states': ('awarded',),
    },
}


def _record_company(record):
    """Find the owning company even for sourcing records without company_id."""
    if 'company_id' in record._fields and record.company_id:
        return record.company_id
    source_fields = (
        ('unscheduled_request_id', 'annual_plan_id')
        if 'source_type' in record._fields and record.source_type == 'unscheduled'
        else ('annual_plan_id', 'unscheduled_request_id')
    )
    for field_name in source_fields:
        if field_name in record._fields and record[field_name]:
            linked = record[field_name]
            if 'company_id' in linked._fields and linked.company_id:
                return linked.company_id
    if 'plan_line_id' in record._fields and record.plan_line_id:
        return record.plan_line_id.plan_id.company_id
    if 'employee_id' in record._fields and record.employee_id:
        return record.employee_id.company_id
    return record.env['res.company']


class EdsApprovalMinuteWizard(models.TransientModel):
    _name = 'eds.approval.minute.wizard'
    _description = 'Download EDS Approval Minute'

    approval_type = fields.Selection([
        ('annual_plan', 'Approved Annual L&D Plan'),
        ('unscheduled_request', 'Approved Unscheduled Training Request'),
        ('vendor_selection', 'Awarded Training Provider'),
        ('hotel_selection', 'Awarded Hotel / Venue'),
        ('sponsorship', 'Approved Sponsorship'),
        ('tna_consolidation', 'Approved TNA Consolidation'),
        ('rfp', 'Awarded Request for Proposal'),
    ], string='Approval Type', required=True)

    annual_plan_id = fields.Many2one(
        'eds.annual.plan', string='Approved Annual L&D Plan',
        domain="[('state', '=', 'published')]")
    unscheduled_request_id = fields.Many2one(
        'eds.unscheduled.request', string='Approved Unscheduled Request',
        domain="[('state', '=', 'approved')]")
    vendor_selection_id = fields.Many2one(
        'eds.course.vendor.selection', string='Awarded Training Provider',
        domain="[('state', '=', 'awarded')]")
    hotel_selection_id = fields.Many2one(
        'eds.hotel.selection', string='Awarded Hotel / Venue',
        domain="[('state', '=', 'awarded')]")
    sponsorship_id = fields.Many2one(
        'eds.sponsorship', string='Approved Sponsorship',
        domain="[('state', 'in', ('approved', 'active', 'completed', 'breached'))]")
    tna_consolidation_id = fields.Many2one(
        'eds.tna.consolidation', string='Approved TNA Consolidation',
        domain="[('state', 'in', ('approved', 'locked'))]")
    rfp_id = fields.Many2one(
        'eds.rfp', string='Awarded Request for Proposal',
        domain="[('state', '=', 'awarded')]")

    @api.onchange('approval_type')
    def _onchange_approval_type(self):
        for wizard in self:
            for config in APPROVAL_SOURCES.values():
                wizard[config['field']] = False

    def _get_approved_record(self):
        """Recheck state and access when a PDF is downloaded or rendered."""
        self.ensure_one()
        config = APPROVAL_SOURCES.get(self.approval_type)
        if not config:
            raise UserError(_('Choose the type of approved record first.'))

        selected = [(key, self[item['field']])
                    for key, item in APPROVAL_SOURCES.items()
                    if self[item['field']]]
        if len(selected) != 1 or selected[0][0] != self.approval_type:
            raise UserError(_('Select one approved record in the chosen category.'))

        record = selected[0][1].exists()
        if not record:
            raise UserError(_('The selected record no longer exists.'))
        # Domains improve the UI, but cannot replace a server-side authorization check.
        record.check_access('read')
        company = _record_company(record)
        if company and company not in self.env.companies:
            raise AccessError(_('You cannot print an approval minute for another company.'))
        if record.state not in config['states']:
            raise UserError(_('This record is not in an approved or awarded status.'))
        return record

    def _record_company(self, record):
        """Expose the selected record's company to the PDF template."""
        self.ensure_one()
        return _record_company(record)

    def action_download(self):
        self.ensure_one()
        self._get_approved_record()
        return self.env.ref(
            'employee_development_system.action_report_eds_meeting_minutes'
        ).report_action(self)
