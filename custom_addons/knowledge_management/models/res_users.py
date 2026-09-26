# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """
    FR-SYS-001, FR-SYS-002: Security governance extensions for Active Directory / LDAP and TOTP MFA.
    Enforces mandatory Two-Factor Authentication (TOTP) for high-privilege roles:
    - KMS Managers
    - KMS Auditors
    - LMS Administrators
    """
    _inherit = 'res.users'

    is_privileged_kms_lms = fields.Boolean(
        string='Privileged KMS/LMS Role',
        compute='_compute_privileged_kms_lms',
        help='True if user holds administrative or auditor access in KMS or LMS.'
    )
    totp_mfa_enforced = fields.Boolean(
        string='Mandatory TOTP MFA Enforced',
        compute='_compute_privileged_kms_lms',
        help='Security policy mandates Two-Factor Authentication (TOTP) for this user.'
    )

    @api.depends('group_ids')
    def _compute_privileged_kms_lms(self):
        kms_mgr = self.env.ref('knowledge_management.group_kms_manager', raise_if_not_found=False)
        kms_aud = self.env.ref('knowledge_management.group_kms_auditor', raise_if_not_found=False)
        lms_adm = self.env.ref('learning_management.group_lms_admin', raise_if_not_found=False)
        privileged_ids = {g.id for g in (kms_mgr, kms_aud, lms_adm) if g}

        for user in self:
            user_groups = getattr(user, 'group_ids', False) or getattr(user, 'groups_id', False) or self.env['res.groups']
            has_priv = bool(set(user_groups.ids) & privileged_ids)
            user.is_privileged_kms_lms = has_priv
            user.totp_mfa_enforced = has_priv

    def check_totp_compliance(self):
        """
        FR-SYS-002: Verifies that privileged role holders have completed TOTP MFA enrollment.
        Returns a tuple: (is_compliant: bool, message: str)
        """
        self.ensure_one()
        if not self.totp_mfa_enforced:
            return True, "Standard user - TOTP optional"

        # Check if auth_totp is enabled on user (totp_secret exists and is not False)
        has_totp = bool(getattr(self, 'totp_secret', False))
        if not has_totp:
            msg = _("Security Policy Violation: User '%s' holds a privileged administrative role but has not enrolled in mandatory TOTP Two-Factor Authentication.") % self.login
            _logger.warning(msg)
            return False, msg
        return True, "TOTP Two-Factor Authentication active and verified"
