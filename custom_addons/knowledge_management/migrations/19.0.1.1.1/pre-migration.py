"""Remove the unsafe LDAP configuration shipped by older KMS releases.

Only the module-owned XML ID is inspected. A connection whose password was
replaced by an administrator is left intact. The known bundled credential is
cleared, or the untouched seed is removed entirely.
"""

import hashlib


_SEED_PASSWORD_SHA256 = '127c3b8131dd676094f703aae1c92f9a46395b6c50c89a9d94bc086ae2673466'


def migrate(cr, version):
    cr.execute("""
        SELECT d.id, l.id, l.ldap_server, l.ldap_server_port,
               l.ldap_binddn, l.ldap_filter, l.ldap_base, l.ldap_password,
               l.sequence, l.create_user, l.ldap_tls
          FROM ir_model_data AS d
          JOIN res_company_ldap AS l ON l.id = d.res_id
         WHERE d.module = 'knowledge_management'
           AND d.name = 'bunna_ad_ldap_configuration'
           AND d.model = 'res.company.ldap'
    """)
    row = cr.fetchone()
    if not row:
        return

    xml_id, ldap_id, server, port, bind_dn, ldap_filter, base, password, sequence, create_user, tls = row
    if not password or hashlib.sha256(password.encode('utf-8')).hexdigest() != _SEED_PASSWORD_SHA256:
        # A different password means the connection has been configured by an
        # administrator. Never remove or reset that connection.
        return

    untouched_seed = (
        server == 'ldap.bunnabanksc.com'
        and port == 389
        and bind_dn == 'cn=odoo_kms_svc,ou=ServiceAccounts,dc=bunnabanksc,dc=com'
        and ldap_filter == '(&(objectCategory=person)(objectClass=user)(sAMAccountName=%s))'
        and base == 'ou=BankStaff,dc=bunnabanksc,dc=com'
        and sequence == 10 and create_user and tls
    )
    if untouched_seed:
        cr.execute('DELETE FROM ir_model_data WHERE id = %s', (xml_id,))
        cr.execute('DELETE FROM res_company_ldap WHERE id = %s', (ldap_id,))
    else:
        # Other settings were edited, but the original exposed credential is
        # still present. Preserve the connection and require a new password.
        cr.execute('UPDATE res_company_ldap SET ldap_password = NULL WHERE id = %s', (ldap_id,))
