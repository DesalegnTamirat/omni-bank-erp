# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class HrEmployeeEds(models.Model):
    """hr.employee extension: EDS training history, certificates, sponsorship smart buttons."""
    _inherit = 'hr.employee'

    eds_tna_entry_ids = fields.One2many('eds.tna.entry', 'employee_id', string='TNA Needs')
    eds_tna_entry_count = fields.Integer(string='Training Needs (TNA)', compute='_compute_eds_tna_counts')
    eds_certificate_ids = fields.One2many('eds.certificate', 'employee_id', string='Certificates')
    eds_certificate_count = fields.Integer(string='Certificates Count', compute='_compute_eds_tna_counts')
    eds_sponsorship_ids = fields.One2many('eds.sponsorship', 'employee_id', string='Sponsorships')
    eds_sponsorship_count = fields.Integer(string='Sponsorships Count', compute='_compute_eds_tna_counts')
    # COMMENTED OUT PER USER JOURNEY: IDP and Self-Development omitted from 14 Use Cases
    # eds_idp_ids = fields.One2many('eds.individual.development.plan', 'employee_id', string='IDPs')
    # eds_idp_count = fields.Integer(string='IDPs Count', compute='_compute_eds_tna_counts')
    # eds_self_dev_ids = fields.One2many('eds.self.development.activity', 'employee_id', string='Self Development Activities')
    # eds_self_dev_count = fields.Integer(string='Self-Development Count', compute='_compute_eds_tna_counts')

    @api.depends('eds_tna_entry_ids', 'eds_certificate_ids', 'eds_sponsorship_ids')
    def _compute_eds_tna_counts(self):
        for rec in self:
            rec.eds_tna_entry_count = len(rec.eds_tna_entry_ids)
            rec.eds_certificate_count = len(rec.eds_certificate_ids.filtered(lambda c: c.state == 'issued'))
            rec.eds_sponsorship_count = len(rec.eds_sponsorship_ids)

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
            'name': _('Sponsorships & Bonds'),
            'res_model': 'eds.sponsorship',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_idps(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Individual Development Plans'),
            'res_model': 'eds.individual.development.plan',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_self_dev(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Self-Development Activities'),
            'res_model': 'eds.self.development.activity',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }
