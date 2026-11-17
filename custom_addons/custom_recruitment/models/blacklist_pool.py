# -*- coding: utf-8 -*-
from odoo import api, models, fields, _


class BlacklistPool(models.Model):
    _name = "blacklist.pool"
    _description = "Blacklist Pool"
    _rec_name = "candidate"
    _order = "id desc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    # ── Core Blacklist Fields (Aligned with Inter-Bank Termination Records) ──
    candidate = fields.Char(string="Name", required=True, index=True)
    name_of_bank = fields.Char(string="Name of the Bank", required=True, index=True)
    reason = fields.Text(string="Reasons For Termination", required=True)
    date_of_termination = fields.Date(string="Date of Termination")
    national_id = fields.Char(string="National ID / NID", index=True)
    email = fields.Char(string="Email Address", index=True)
    phone = fields.Char(string="Phone Number", index=True)

    def action_open_import_wizard(self):
        return {
            'name': _('Import Blacklist Pool Excel/CSV'),
            'type': 'ir.actions.act_window',
            'res_model': 'blacklist.pool.import.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
