# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class HrEmployeeEds(models.Model):
    """hr.employee extension: EDS training history, certificates, sponsorship smart buttons and offboarding bond clearance."""
    _inherit = 'hr.employee'

    eds_tna_entry_ids = fields.One2many('eds.tna.entry', 'employee_id', string='TNA Needs')
    eds_tna_entry_count = fields.Integer(string='Training Needs (TNA)', compute='_compute_eds_tna_counts')
    eds_certificate_ids = fields.One2many('eds.certificate', 'employee_id', string='Certificates')
    eds_certificate_count = fields.Integer(string='Certificates Count', compute='_compute_eds_tna_counts')
    eds_sponsorship_ids = fields.One2many('eds.sponsorship', 'employee_id', string='Sponsorships & Bonds')
    eds_sponsorship_count = fields.Integer(string='Sponsorships Count', compute='_compute_eds_tna_counts')
    
    # Active Bond and Service Obligation Tracking for Offboarding Clearance
    active_sponsorship_count = fields.Integer(string='Active Service Bonds', compute='_compute_eds_bonds')
    total_unamortized_bond_amount = fields.Monetary(
        string='Unamortized Bond Obligation',
        currency_field='currency_id',
        compute='_compute_eds_bonds',
        help='Total outstanding unamortized service bond obligation across all active sponsorships.'
    )
    has_active_bond_obligation = fields.Boolean(
        string='Has Active Bond Obligation',
        compute='_compute_eds_bonds',
        help='True if employee currently has active service bonds with unamortized financial obligations.'
    )

    @api.depends('eds_tna_entry_ids', 'eds_certificate_ids', 'eds_sponsorship_ids')
    def _compute_eds_tna_counts(self):
        for rec in self:
            rec.eds_tna_entry_count = len(rec.eds_tna_entry_ids)
            rec.eds_certificate_count = len(rec.eds_certificate_ids.filtered(lambda c: c.state == 'issued'))
            rec.eds_sponsorship_count = len(rec.eds_sponsorship_ids)

    @api.depends('eds_sponsorship_ids.state', 'eds_sponsorship_ids.outstanding_obligation')
    def _compute_eds_bonds(self):
        for rec in self:
            active_bonds = rec.eds_sponsorship_ids.filtered(lambda s: s.state in ('active', 'breached'))
            rec.active_sponsorship_count = len(active_bonds)
            rec.total_unamortized_bond_amount = sum(active_bonds.mapped('outstanding_obligation'))
            rec.has_active_bond_obligation = rec.active_sponsorship_count > 0 and rec.total_unamortized_bond_amount > 0.0

    def action_view_eds_tna_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Training Needs (TNA)'),
            'res_model': 'eds.tna.entry',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Issued Certificates'),
            'res_model': 'eds.certificate',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_sponsorships(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sponsorships & Service Bonds'),
            'res_model': 'eds.sponsorship',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

