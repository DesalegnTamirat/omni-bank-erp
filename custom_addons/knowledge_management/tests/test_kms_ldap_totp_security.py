# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestKmsLdapTotpSecurity(TransactionCase):
    """
    FR-SYS-001, FR-SYS-002: Security governance tests for Active Directory / LDAP and TOTP MFA.
    Verifies:
    1. Bunna Bank Active Directory / LDAP configuration record is populated.
    2. Privileged administrative roles have mandatory TOTP MFA enforced.
    3. Regular employees do not have mandatory TOTP MFA enforced.
    4. Compliance check method correctly validates TOTP readiness.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CompanyLdap = cls.env['res.company.ldap']
        cls.ResUsers = cls.env['res.users']

        cls.user_admin_mgr = cls.ResUsers.search([('login', '=', 'admin')], limit=1) or cls.env.ref('base.user_admin')
        # Assign KMS Manager group to test user
        grp_mgr = cls.env.ref('knowledge_management.group_kms_manager')
        cls.user_admin_mgr.write({'group_ids': [(4, grp_mgr.id)]})

        cls.user_regular = cls.env.ref('base.user_root')

    def test_01_bunna_ldap_configuration_record_exists(self):
        """FR-SYS-001: Active Directory LDAP configuration record is present with proper security parameters."""
        ldap_rec = self.CompanyLdap.search([('ldap_server', '=', 'ldap.bunnabanksc.com')], limit=1)
        self.assertTrue(ldap_rec, "Bunna Bank AD/LDAP record should exist in res.company.ldap")
        self.assertEqual(ldap_rec.ldap_server_port, 389)
        self.assertTrue(ldap_rec.create_user, "LDAP user auto-provisioning must be enabled")
        self.assertTrue(ldap_rec.ldap_tls, "TLS encryption must be enabled for LDAP")
        self.assertIn("sAMAccountName", ldap_rec.ldap_filter)
        self.assertIn("ou=BankStaff", ldap_rec.ldap_base)

    def test_02_privileged_role_enforces_totp_mfa(self):
        """FR-SYS-002: KMS Manager role triggers mandatory TOTP MFA enforcement flag."""
        self.assertTrue(self.user_admin_mgr.is_privileged_kms_lms)
        self.assertTrue(self.user_admin_mgr.totp_mfa_enforced)

    def test_03_standard_user_totp_not_enforced(self):
        """FR-SYS-002: Regular users without privileged groups are not subjected to mandatory TOTP."""
        # Ensure root/standard user without mgr group is not enforced
        grp_mgr = self.env.ref('knowledge_management.group_kms_manager')
        grp_aud = self.env.ref('knowledge_management.group_kms_auditor')
        self.user_regular.write({'group_ids': [(3, grp_mgr.id), (3, grp_aud.id)]})
        self.assertFalse(self.user_regular.totp_mfa_enforced)

    def test_04_check_totp_compliance_method(self):
        """FR-SYS-002: check_totp_compliance returns proper compliance tuple."""
        compliant, msg = self.user_regular.check_totp_compliance()
        self.assertTrue(compliant)
        self.assertIn("optional", msg.lower())

        # For privileged user without totp_secret configured, check_totp_compliance returns False with advisory
        self.user_admin_mgr.write({'totp_secret': False})
        compliant_mgr, msg_mgr = self.user_admin_mgr.check_totp_compliance()
        self.assertFalse(compliant_mgr)
        self.assertIn("not enrolled", msg_mgr.lower())
