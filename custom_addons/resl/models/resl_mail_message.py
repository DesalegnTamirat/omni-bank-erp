# -*- coding: utf-8 -*-
"""Prevent requesters (and regular guarantors) from deleting chatter messages
and activities on resl.loan records.

Only Odoo system administrators, RESL HR officers and RESL managers can delete
loan-related mail messages.  Requesters, guarantors and other viewers receive a
clear error when they try.
"""
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MailMessageReslProtect(models.Model):
    _inherit = 'mail.message'

    def unlink(self):
        for msg in self:
            if msg.model == 'resl.loan' and msg.res_id:
                user = self.env.user
                try:
                    allowed = (
                        user.has_group('base.group_system')
                        or user._resl_has_group('resl.group_resl_hr')
                        or user._resl_has_group('resl.group_resl_manager')
                        or user._resl_has_group('resl.group_resl_admin')
                    )
                except Exception:
                    allowed = user.has_group('base.group_system')
                if not allowed:
                    raise UserError(_(
                        "You are not allowed to delete loan records or activity logs.\n\n"
                        "Loan agreement logs are legally binding records and cannot be "
                        "removed by requesters or guarantors."
                    ))
        return super().unlink()


class MailActivityReslProtect(models.Model):
    _inherit = 'mail.activity'

    def unlink(self):
        for act in self:
            if act.res_model == 'resl.loan' and act.res_id:
                user = self.env.user
                try:
                    allowed = (
                        user.has_group('base.group_system')
                        or user._resl_has_group('resl.group_resl_hr')
                        or user._resl_has_group('resl.group_resl_manager')
                        or user._resl_has_group('resl.group_resl_admin')
                        # The user whose activity it is may mark it done (the
                        # activity system calls unlink internally when done)
                        or act.user_id.id == user.id
                    )
                except Exception:
                    allowed = user.has_group('base.group_system')
                if not allowed:
                    raise UserError(_(
                        "You are not allowed to delete loan activity logs."
                    ))
        return super().unlink()
