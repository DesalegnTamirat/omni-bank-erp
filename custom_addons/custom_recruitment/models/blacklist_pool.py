# -*- coding: utf-8 -*-
from odoo import api, models, fields, _

class BlacklistPool(models.Model):
    _name = "blacklist.pool"
    _description = "Blacklist Pool"
    _rec_name = "candidate"
    
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    candidate = fields.Char(string="Candidate Name", required=True)
    gender = fields.Selection([('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
                              string="Gender", default="Male")
    national_id = fields.Char(string="National ID / NID")
    email = fields.Char(string="Email Address")
    phone = fields.Char(string="Phone Number")
    reason = fields.Text(string="Reason for Blacklisting")
    blacklisted_date = fields.Date(string="Date Blacklisted", default=fields.Date.today)

    def action_open_import_wizard(self):
        return {
            'name': _('Import Blacklist Pool Excel/CSV'),
            'type': 'ir.actions.act_window',
            'res_model': 'blacklist.pool.import.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
