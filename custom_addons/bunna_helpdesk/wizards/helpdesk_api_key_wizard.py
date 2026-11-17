# -*- coding: utf-8 -*-
import binascii
import datetime
import os

from odoo import api, fields, models
from odoo.addons.base.models.res_users import (
    API_KEY_SIZE,
    INDEX_SIZE,
    KEY_CRYPT_CONTEXT,
)


class HelpdeskApiKeyWizard(models.TransientModel):
    _name = "helpdesk.api.key.wizard"
    _description = "Generate Helpdesk API Key Wizard"

    @api.model
    def _default_user(self):
        user = self.env.user
        if not user or not user.active or user.id == 1:
            admin = self.env.ref("base.user_admin", raise_if_not_found=False)
            return admin or user
        return user

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User / Identity",
        required=True,
        default=_default_user,
        domain=[("active", "=", True), ("share", "=", False)],
        help="The tickets created with this key will be associated with this user's context and privileges.",
    )
    name = fields.Char(
        string="Key Description / Client Name",
        required=True,
        default="External System Integration Key",
        help="Identifies the client or external application using this API key (e.g. Mobile App, CBS, CRM, Website).",
    )
    expiration_days = fields.Integer(
        string="Validity (Days)",
        default=365,
        help="Number of days the API key remains valid. Set to 0 for a permanent key with no expiration.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("generated", "Generated"),
        ],
        default="draft",
        string="Status",
    )
    generated_key = fields.Char(
        string="Generated API Key",
        readonly=True,
        help="Copy this API key now. For security, it will not be displayed in plaintext again.",
    )
    endpoint_url = fields.Char(
        string="Ticket Creation Endpoint",
        readonly=True,
    )
    curl_command = fields.Text(
        string="Example cURL Command",
        readonly=True,
    )

    def action_generate_key(self):
        self.ensure_one()
        raw_key = binascii.hexlify(os.urandom(API_KEY_SIZE)).decode()
        hashed_key = KEY_CRYPT_CONTEXT.hash(raw_key)
        index = raw_key[:INDEX_SIZE]

        expiration_date = None
        if self.expiration_days and self.expiration_days > 0:
            expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=self.expiration_days)

        self.env.cr.execute(
            """
            INSERT INTO res_users_apikeys (name, user_id, scope, expiration_date, key, index)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            [self.name, self.user_id.id, None, expiration_date, hashed_key, index],
        )

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "http://localhost:8069").rstrip("/")
        endpoint = f"{base_url}/api/v1/helpdesk/ticket/create"

        curl_example = (
            f'curl -X POST "{endpoint}" \\\n'
            f'  -H "Authorization: Bearer {raw_key}" \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f'  -d \'{{\n'
            f'    "subject": "ATM Card Retained at Bole Branch",\n'
            f'    "description": "Customer ATM card was retained by machine ATM-002.",\n'
            f'    "priority": "2",\n'
            f'    "case_type": "complaint",\n'
            f'    "customer": {{\n'
            f'      "name": "Abebe Kebede",\n'
            f'      "phone": "+251911234567",\n'
            f'      "account_number": "100012345678"\n'
            f'    }}\n'
            f'  }}\''
        )

        self.write({
            "generated_key": raw_key,
            "endpoint_url": endpoint,
            "curl_command": curl_example,
            "state": "generated",
        })

        return {
            "type": "ir.actions.act_window",
            "name": "Generated API Key",
            "res_model": "helpdesk.api.key.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
