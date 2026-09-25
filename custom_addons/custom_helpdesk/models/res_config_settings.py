# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo import fields, models
import ast



class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    helpdesk_mgmt_portal_select_team = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_select_team",
        readonly=False,
    )
    helpdesk_mgmt_portal_team_id_required = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_team_id_required",
        readonly=False,
    )
    helpdesk_mgmt_portal_select_category = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_select_category",
        readonly=False,
    )
    helpdesk_mgmt_portal_category_id_required = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_category_id_required",
        readonly=False,
    )
    helpdesk_mgmt_duplicate_tracking = fields.Boolean(
        related="company_id.helpdesk_mgmt_duplicate_tracking", readonly=False
    )
    helpdesk_mgmt_duplicate_ticket_stage_id = fields.Many2one(
        related="company_id.helpdesk_mgmt_duplicate_ticket_stage_id", readonly=False
    )
    helpdesk_mgmt_ticket_auto_assign = fields.Boolean(
        related="company_id.helpdesk_mgmt_ticket_auto_assign",
        readonly=False,
    )

# --- From helpdesk_mgmt_activity ---
# Copyright (C) 2024 Cetmix OÜ
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).




class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    helpdesk_available_model_ids = fields.Many2many(
        comodel_name="ir.model",
        domain="[('transient', '=', False)]",
        string="Available Models",
        help="Available models for set source record in helpdesk ticket",
    )

    def set_values(self):
        super().set_values()
        ICPSudo = self.env["ir.config_parameter"].sudo()
        ICPSudo.set_param(
            "helpdesk_mgmt_activity.helpdesk_available_model_ids",
            str(self.helpdesk_available_model_ids.ids),
        )
        return

    @api.model
    def get_values(self):
        res = super().get_values()
        ICPSudo = self.env["ir.config_parameter"].sudo()
        helpdesk_available_model_ids = ICPSudo.get_param(
            "helpdesk_mgmt_activity.helpdesk_available_model_ids", False
        )
        if helpdesk_available_model_ids:
            res.update(
                helpdesk_available_model_ids=ast.literal_eval(
                    helpdesk_available_model_ids
                )
            )
        return res

# --- From helpdesk_type ---


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    helpdesk_mgmt_portal_type = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_type",
        readonly=False,
    )
    helpdesk_mgmt_portal_type_id_required = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_type_id_required",
        readonly=False,
    )
