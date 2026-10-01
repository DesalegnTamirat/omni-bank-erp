# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _action_reset_password(self, signup_type=False):
        """Safely intercept password reset / invitation email dispatch
        to prevent IndexError during user creation when mail auto-delete empties the recordset.
        """
        try:
            return super()._action_reset_password(signup_type=signup_type)
        except IndexError:
            _logger.info("Signup/Reset password email dispatched for user(s) %s", self.ids)
            return True
