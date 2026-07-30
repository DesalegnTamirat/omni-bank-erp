# -*- coding: utf-8 -*-
# Part of custom HR Contract module for Odoo 19.

from odoo import models


class HrContractType(models.Model):
    """Extend Contract Type (base model is already defined in the hr module)."""
    _inherit = 'hr.contract.type'
