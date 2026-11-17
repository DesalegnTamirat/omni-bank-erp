# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import ValidationError


class ReslConfigSettings(models.TransientModel):
    """Configuration > Settings: rules an administrator can change."""
    _inherit = 'res.config.settings'

    resl_max_guarantors = fields.Integer(
        string="Number of guarantors",
        config_parameter='resl.max_guarantors', default=2,
        help="The most guarantors one loan request can have (default 2). A single "
             "guarantor is still enough when his / her salary covers the borrower; "
             "more are asked for only while the salaries selected so far do not.")

    def set_values(self):
        for rec in self:
            if rec.resl_max_guarantors < 1:
                raise ValidationError(_("Number of guarantors must be at least 1."))
        return super().set_values()
