# -*- coding: utf-8 -*-
import logging
import re
import ldap
from ldap.filter import filter_format
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


def clean_ldap_text(val):
    """Sanitize string for LDAP and strip invalid characters."""
    if not val:
        return ""
    # Strip leading/trailing whitespaces and control characters
    s = str(val).strip()
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)


def clean_username_token(token):
    """Clean a name token for login/email username (alphanumeric only)."""
    if not token:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(token)).strip().lower()


class ActiveDirectoryService(models.AbstractModel):
    _name = 'ad.ldap.service'
    _description = 'Active Directory LDAP Provisioning Service'

    @api.model
    def _get_ad_config(self, company_id=None):
        """Retrieve AD connection parameters directly from res_company_ldap using SQL query."""
        company = company_id or self.env.company
        company_id_val = company.id if company else None

        row = None
        try:
            self.env.cr.execute("""
                SELECT ldap_server_port, ldap_server, ldap_binddn, ldap_password, ldap_filter, ldap_base, ldap_tls
                FROM res_company_ldap
                WHERE company = %s AND ldap_server IS NOT NULL
                LIMIT 1
            """, (company_id_val,))
            row = self.env.cr.dictfetchone()
        except Exception as e:
            _logger.warning("Could not query res_company_ldap for company %s: %s", company_id_val, e)

        if not row:
            try:
                self.env.cr.execute("""
                    SELECT ldap_server_port, ldap_server, ldap_binddn, ldap_password, ldap_filter, ldap_base, ldap_tls
                    FROM res_company_ldap
                    WHERE ldap_server IS NOT NULL
                    ORDER BY id ASC
                    LIMIT 1
                """)
                row = self.env.cr.dictfetchone()
            except Exception as e:
                _logger.warning("Could not query res_company_ldap: %s", e)

        row = row or {}
        server = (row.get('ldap_server') or '10.241.22.126').strip()
        port = int(row.get('ldap_server_port') or 389)
        bind_dn = (row.get('ldap_binddn') or 'administrator@domaintestbb.com').strip()
        password = row.get('ldap_password') or 'Bunna@1234'
        base_dn = (row.get('ldap_base') or 'DC=domaintestbb,DC=com').strip()
        use_tls = bool(row.get('ldap_tls'))

        # Derive UPN domain dynamically from base_dn (e.g. DC=domaintestbb,DC=com -> domaintestbb.com)
        derived_domain = ""
        if base_dn:
            parts = [p.split('=')[1] for p in base_dn.split(',') if p.strip().upper().startswith('DC=')]
            if parts:
                derived_domain = ".".join(parts).lower()
        if not derived_domain and '@' in bind_dn:
            derived_domain = bind_dn.split('@')[-1].lower()

        upn_domain = derived_domain or 'domaintestbb.com'
        # Derive mail_domain dynamically: from system parameter 'ad.mail_domain', company settings, or upn_domain
        custom_mail = self.env['ir.config_parameter'].sudo().get_param('ad.mail_domain', '').strip()
        mail_domain = custom_mail or 'bunnabanksc.com' or upn_domain
        # Target 'newusers' OU as requested, with support for custom ir.config_parameter
        custom_ou = self.env['ir.config_parameter'].sudo().get_param('ad.target_ou', '').strip()
        if custom_ou:
            target_ou = custom_ou
        else:
            target_ou = f"OU=newusers,{base_dn}" 

        return {
            'server': server,
            'port': port,
            'bind_dn': bind_dn,
            'password': password,
            'base_dn': base_dn,
            'use_tls': use_tls,
            'target_ou': target_ou,
            'upn_domain': upn_domain,
            'mail_domain': mail_domain,
            'default_password': password or 'Bunna@1234',
            'auto_provision': True,
        }

    @api.model
    def _get_ldap_connection(self, config=None):
        """Establish and bind LDAP connection to the Active Directory domain controller."""
        cfg = config or self._get_ad_config()
        uri = f"ldap://{cfg['server']}:{cfg['port']}"
        if cfg['port'] == 636 or cfg.get('use_ssl'):
            uri = f"ldaps://{cfg['server']}:{cfg['port']}"

        _logger.info("Connecting to Active Directory at %s", uri)
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)

        if cfg['use_tls'] and not uri.startswith('ldaps://'):
            try:
                conn.start_tls_s()
            except Exception as e:
                _logger.warning("Could not start TLS on %s: %s", uri, e)

        # Dynamically build bind candidates from database configuration (res_company_ldap)
        bind_candidates = []
        if cfg.get('bind_dn'):
            bind_candidates.append(cfg['bind_dn'].strip())

        raw_bind = cfg.get('bind_dn', '').strip()
        user_part = raw_bind.split('@')[0].split('\\')[-1].strip()

        # Dynamically derive domains and NetBIOS names from base_dn and bind_dn in database
        domains = set()
        if cfg.get('upn_domain'):
            domains.add(cfg['upn_domain'].lower())
        if '@' in raw_bind:
            domains.add(raw_bind.split('@')[-1].strip().lower())
        if cfg.get('base_dn'):
            dc_parts = [p.split('=')[1].strip() for p in cfg['base_dn'].split(',') if p.strip().upper().startswith('DC=')]
            if dc_parts:
                domains.add(".".join(dc_parts).lower())

        for dom in sorted(domains):
            if not dom:
                continue
            netbios = dom.split('.')[0].upper()
            for cand in [
                f"{user_part}@{dom}",
                f"{netbios}\\{user_part}",
            ]:
                if cand not in bind_candidates:
                    bind_candidates.append(cand)

        if user_part and user_part not in bind_candidates:
            bind_candidates.append(user_part)

        bound = False
        last_err = None
        for candidate_dn in bind_candidates:
            try:
                conn.simple_bind_s(candidate_dn, cfg['password'])
                _logger.info("Successfully bound to AD as %s", candidate_dn)
                bound = True
                break
            except ldap.INVALID_CREDENTIALS as cred_err:
                last_err = cred_err
                _logger.warning("Invalid credentials trying bind_dn %s: %s", candidate_dn, cred_err)
            except Exception as e:
                last_err = e
                _logger.warning("Error binding to AD with %s: %s", candidate_dn, e)

        if not bound:
            raise last_err or Exception("Failed to bind to Active Directory")

        return conn

    @api.model
    def generate_unique_username(self, full_name, conn=None, base_dn=None, current_emp_id=None):
        """
        Generate collision-free sAMAccountName and UPN:
        1. Base: first.father (e.g. amanuel.guben)
        2. Collision: first.father + grandfather[0] (e.g. amanuel.gubend for Derso)
        3. Secondary Collision: first.father + grandfather[0] + sequential number (e.g. amanuel.gubend2)
        """
        cfg = self._get_ad_config()
        base_dn = base_dn or cfg['base_dn']
        name_parts = [clean_username_token(p) for p in (full_name or '').split() if clean_username_token(p)]

        first = name_parts[0] if len(name_parts) >= 1 else "user"
        father = name_parts[1] if len(name_parts) >= 2 else ""
        grandfather = name_parts[2] if len(name_parts) >= 3 else ""

        if father:
            base_login = f"{first}.{father}"
        else:
            base_login = first

        # Check collision against AD if connection provided
        if not conn:
            return base_login

        def is_taken(login):
            flt = filter_format(
                "(|(sAMAccountName=%s)(userPrincipalName=%s@%s))",
                (login, login, cfg['upn_domain'])
            )
            try:
                res = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, flt, ['sAMAccountName', 'employeeID'])
                # IMPORTANT: Filter out referral tuples (None, [...]) returned by Active Directory
                entries = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                if not entries:
                    return False
                # If current employee is already associated with this account, it is not a collision
                if current_emp_id:
                    for dn, attrs in entries:
                        emp_ids = [x.decode('utf-8', errors='ignore') for x in attrs.get('employeeID', [])]
                        if str(current_emp_id) in emp_ids:
                            return False
                return True
            except Exception as err:
                _logger.warning("Error searching AD for login %s: %s", login, err)
                return False

        # 1. Try base: first.father
        if not is_taken(base_login):
            return base_login

        # 2. Collision: append 1st letter of grandfather name
        if grandfather:
            candidate = f"{base_login}{grandfather[0]}"
            if not is_taken(candidate):
                return candidate
            base_for_numbers = candidate
        else:
            base_for_numbers = base_login

        # 3. Secondary collision: append numeric index (2, 3, ...)
        idx = 2
        while True:
            candidate = f"{base_for_numbers}{idx}"
            if not is_taken(candidate):
                return candidate
            idx += 1
            if idx > 99:
                break

        return f"{base_login}{grandfather[:1] or ''}{idx}"

    @api.model
    def lookup_manager_dn(self, manager_employee, conn, base_dn):
        """Search AD for manager's DistinguishedName (DN) using email, sAMAccountName, or full name."""
        if not manager_employee:
            return None

        # Gather possible search identifiers
        candidates = []
        if getattr(manager_employee, 'work_email', None):
            candidates.append(manager_employee.work_email.strip())
        if getattr(manager_employee, 'ad_username', None):
            candidates.append(manager_employee.ad_username.strip())
        if getattr(manager_employee, 'name', None):
            full = manager_employee.name.strip()
            candidates.append(full)
            tokens = full.split()
            if len(tokens) >= 2:
                candidates.append(f"{tokens[0]} {tokens[1]}")  # e.g. "Eyob Shewangzaw"
                candidates.append(f"{tokens[0]}.{tokens[1]}")  # e.g. "eyob.shewangzaw"
            if len(tokens) >= 1:
                candidates.append(tokens[0])                   # e.g. "eyob" 

        for term in candidates:
            if not term:
                continue
            flt = filter_format(
                "(|(mail=%s)(userPrincipalName=%s)(sAMAccountName=%s)(displayName=%s)(cn=%s))",
                (term, term, term, term, term)
            )
            try:
                results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, flt, ['distinguishedName'])
                for dn, attrs in results:
                    if dn:
                        _logger.info("Resolved manager %s to AD DN: %s", manager_employee.name, dn)
                        return dn
            except Exception as e:
                _logger.debug("Failed manager search for '%s': %s", term, e)

        return None

    @api.model
    def provision_employee(self, employee, initial_password=None):
        """
        Create employee in Active Directory with all 15 mapped fields.
        Returns dict: {'success': bool, 'username': str, 'upn': str, 'dn': str, 'error': str}
        """
        cfg = self._get_ad_config(employee.company_id)
        if not cfg.get('auto_provision') and not self.env.context.get('force_ad_provision'):
            return {'success': False, 'error': 'AD Auto-provisioning is disabled in settings.'}

        # 1. Connect to Active Directory
        conn = None
        try:
            conn = self._get_ldap_connection(cfg)
        except Exception as conn_err:
            error_msg = f"Failed to connect to Active Directory DC ({cfg['server']}:{cfg['port']}): {conn_err}"
            _logger.error(error_msg)
            return {'success': False, 'error': error_msg}

        try:
            # 2. Extract and sanitize names
            raw_tokens = (employee.name or '').strip().split()
            first_name = raw_tokens[0] if len(raw_tokens) >= 1 else "Employee"
            father_name = raw_tokens[1] if len(raw_tokens) >= 2 else ""
            grandfather_name = raw_tokens[2] if len(raw_tokens) >= 3 else ""

            display_name = employee.name.strip()
            surname = grandfather_name or father_name or first_name

            emp_id_num = clean_ldap_text(
                getattr(employee, 'identification_id', '') or getattr(employee, 'id', '')
            )

            # Check if this employee ALREADY exists in Active Directory (by employeeID, ad_username, or email)
            existing_user = None
            search_terms = []
            if emp_id_num:
                search_terms.append(f"(employeeID={emp_id_num})")
            if getattr(employee, 'ad_username', None):
                search_terms.append(f"(sAMAccountName={employee.ad_username.strip()})")

            if search_terms:
                find_flt = f"(|{''.join(search_terms)})"
                try:
                    res = conn.search_s(
                        cfg['base_dn'], ldap.SCOPE_SUBTREE, find_flt,
                        ['sAMAccountName', 'userPrincipalName', 'distinguishedName', 'employeeID']
                    )
                    valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                    if valid:
                        existing_dn = valid[0][0]
                        existing_attrs = valid[0][1]
                        ex_login = existing_attrs.get('sAMAccountName', [b''])[0].decode('utf-8', errors='ignore')
                        ex_upn = existing_attrs.get('userPrincipalName', [b''])[0].decode('utf-8', errors='ignore')
                        existing_user = {
                            'dn': existing_dn,
                            'username': ex_login,
                            'upn': ex_upn or f"{ex_login}@{cfg['upn_domain']}",
                            'mail': f"{ex_login}@{cfg['mail_domain']}",
                        }
                except Exception as err:
                    _logger.warning("Error searching for existing employee in AD: %s", err)

            # 3. Generate collision-free username and UPN
            if existing_user:
                login = existing_user['username']
                upn = existing_user['upn']
                email = existing_user['mail']
                user_dn = existing_user['dn']
            else:
                login = self.generate_unique_username(employee.name, conn=conn, base_dn=cfg['base_dn'], current_emp_id=emp_id_num)
                upn = f"{login}@{cfg['upn_domain']}"
                email = f"{login}@{cfg['mail_domain']}"

            # 4. Resolve Job Title and Description
            job_title = clean_ldap_text(
                employee.job_title
                or (employee.job_id.name if getattr(employee, 'job_id', None) else "")
            )

            # 5. Resolve Department (Operating Unit) & Office (Department / District)
            op_unit_name = clean_ldap_text(
                employee.operating_unit_id.name if getattr(employee, 'operating_unit_id', None) else ""
            )
            dept_office_name = clean_ldap_text(
                employee.department_id.name if getattr(employee, 'department_id', None) else ""
            )

            # 6. Resolve Telephone
            telephone = clean_ldap_text(
                getattr(employee, 'mobile_phone', '')
                or getattr(employee, 'phone_num', '')
                or getattr(employee, 'work_phone', '')
            )

            # 7. Resolve Company & Employee ID & Tier
            company_name = clean_ldap_text(
                getattr(employee.company_id, 'name', '') or "bunnabanksc"
            )
            emp_tier = clean_ldap_text(
                getattr(employee.job_grade, 'grade_name', '') if getattr(employee, 'job_grade', None) else ""
            )

            # 8. Resolve Manager DistinguishedName
            manager_dn = None
            manager_obj = getattr(employee, 'parent_id', None) or getattr(employee, 'coach_id', None)
            if manager_obj:
                manager_dn = self.lookup_manager_dn(manager_obj, conn, cfg['base_dn'])

            # 9. Build Target DN with CN collision check
            target_ou = cfg['target_ou']
            if existing_user:
                cn_val = existing_user['dn'].split(',')[0].replace('CN=', '')
            else:
                def is_cn_taken(candidate_cn):
                    flt = filter_format("(cn=%s)", (candidate_cn,))
                    try:
                        # Search across entire domain to detect CN collision anywhere in AD
                        res = conn.search_s(cfg['base_dn'], ldap.SCOPE_SUBTREE, flt, ['cn', 'employeeID'])
                        valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                        if not valid:
                            return False
                        if emp_id_num:
                            for dn, attrs in valid:
                                emp_ids = [x.decode('utf-8', errors='ignore') for x in attrs.get('employeeID', [])]
                                if str(emp_id_num) in emp_ids:
                                    return False
                        return True
                    except Exception:
                        return False

                base_cn = f"{first_name} {father_name}".strip()
                if not is_cn_taken(base_cn):
                    cn_val = base_cn
                else:
                    # Collision on CN! Incorporate third name (grandfather name)
                    if grandfather_name:
                        cand_cn = f"{first_name} {father_name} {grandfather_name}"
                        if not is_cn_taken(cand_cn):
                            cn_val = cand_cn
                        else:
                            cand_cn_login = f"{first_name} {father_name} ({login})"
                            cn_val = cand_cn_login if not is_cn_taken(cand_cn_login) else f"{first_name} {father_name} {emp_id_num}"
                    else:
                        cand_cn_login = f"{first_name} {father_name} ({login})"
                        cn_val = cand_cn_login if not is_cn_taken(cand_cn_login) else f"{first_name} {father_name} {emp_id_num}"

                user_dn = f"CN={cn_val},{target_ou}"

            # 10. If existing user, perform an in-place update of AD attributes
            if existing_user:
                _logger.info("AD account already exists for %s at %s. Updating attributes.", employee.name, user_dn)
                mod_list = []
                updatable = [
                    ('displayName', [display_name.encode('utf-8')]),
                    ('department', [op_unit_name.encode('utf-8')]),
                    ('physicalDeliveryOfficeName', [dept_office_name.encode('utf-8')]),
                    ('telephoneNumber', [telephone.encode('utf-8')]),
                    ('company', [company_name.encode('utf-8')]),
                    ('employeeType', [emp_tier.encode('utf-8')]),
                    ('employeeID', [str(emp_id_num).encode('utf-8')]),
                ]
                if job_title:
                    updatable.extend([
                        ('title', [job_title.encode('utf-8')]),
                        ('description', [job_title.encode('utf-8')]),
                    ])
                if manager_dn:
                    updatable.append(('manager', [manager_dn.encode('utf-8')]))

                for attr_k, attr_v in updatable:
                    if attr_v and attr_v[0]:
                        mod_list.append((ldap.MOD_REPLACE, attr_k, [attr_v[0]]))

                if mod_list:
                    try:
                        conn.modify_s(user_dn, mod_list)
                    except Exception as mod_e:
                        _logger.warning("Could not modify AD user %s: %s", user_dn, mod_e)

                return {
                    'success': True,
                    'username': login,
                    'upn': upn,
                    'mail': email,
                    'dn': user_dn,
                    'error': None
                }

            # 11. Prepare AD Attributes for new user creation
            attrs = [
                ('objectClass', [b'top', b'person', b'organizationalPerson', b'user']),
                ('cn', [cn_val.encode('utf-8')]),
                ('givenName', [first_name.encode('utf-8')]),
                ('sn', [surname.encode('utf-8')]),
                ('displayName', [display_name.encode('utf-8')]),
                ('sAMAccountName', [login.encode('utf-8')]),
                ('userPrincipalName', [upn.encode('utf-8')]),
                ('mail', [email.encode('utf-8')]),
                ('userAccountControl', [b'544']),  # 544 = NORMAL_ACCOUNT (512) + DONT_REQ_PWD (32) -> ENABLED  # 514 = NORMAL_ACCOUNT + ACCOUNTDISABLE
                ('pwdLastSet', [b'0']),           # 0 = Must change password at next logon
            ]

            if job_title:
                attrs.append(('title', [job_title.encode('utf-8')]))
                attrs.append(('description', [job_title.encode('utf-8')]))

            if op_unit_name:
                attrs.append(('department', [op_unit_name.encode('utf-8')]))

            if dept_office_name:
                attrs.append(('physicalDeliveryOfficeName', [dept_office_name.encode('utf-8')]))

            if telephone:
                attrs.append(('telephoneNumber', [telephone.encode('utf-8')]))

            if company_name:
                attrs.append(('company', [company_name.encode('utf-8')]))

            if emp_id_num:
                attrs.append(('employeeID', [str(emp_id_num).encode('utf-8')]))

            if emp_tier:
                attrs.append(('empTier', [emp_tier.encode('utf-8')]))

            if manager_dn:
                attrs.append(('manager', [manager_dn.encode('utf-8')]))

            # 12. Create User in Active Directory
            _logger.info("Creating AD user with DN: %s, sAMAccountName: %s", user_dn, login)
            try:
                conn.add_s(user_dn, attrs)
            except ldap.NO_SUCH_ATTRIBUTE as nsa:
                _logger.warning("Active Directory schema missing attribute (%s), retrying with standard schema attributes...", nsa)
                attrs_filtered = [(k, v) for k, v in attrs if k != 'empTier']
                if emp_tier:
                    attrs_filtered.append(('employeeType', [emp_tier.encode('utf-8')]))
                conn.add_s(user_dn, attrs_filtered)

            # 13. Set initial password (if LDAPS/TLS or permitted)
            pwd = initial_password or cfg['default_password']
            if pwd:
                try:
                    unicode_pwd = f'"{pwd}"'.encode('utf-16-le')
                    conn.modify_s(user_dn, [(ldap.MOD_REPLACE, 'unicodePwd', [unicode_pwd])])
                    _logger.info("Set initial password and pwdLastSet=0 for %s", user_dn)
                except Exception as pwd_err:
                    _logger.warning("Could not set initial password on %s (LDAPS required): %s", user_dn, pwd_err)

            _logger.info("Successfully provisioned Active Directory user %s (%s)", display_name, upn)
            return {
                'success': True,
                'username': login,
                'upn': upn,
                'mail': email,
                'dn': user_dn,
                'error': None
            }

        except ldap.ALREADY_EXISTS:
            _logger.warning("Active Directory user '%s' already exists during add_s. Fetching existing user...", user_dn)
            try:
                chk_flt = filter_format("(|(cn=%s)(sAMAccountName=%s)(userPrincipalName=%s))", (cn_val, login, upn))
                res = conn.search_s(cfg['base_dn'], ldap.SCOPE_SUBTREE, chk_flt, ['sAMAccountName', 'userPrincipalName', 'distinguishedName'])
                valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                if valid:
                    rec_dn = valid[0][0]
                    rec_attrs = valid[0][1]
                    rec_login = rec_attrs.get('sAMAccountName', [b''])[0].decode('utf-8', errors='ignore')
                    rec_upn = rec_attrs.get('userPrincipalName', [b''])[0].decode('utf-8', errors='ignore')
                    return {
                        'success': True,
                        'username': rec_login or login,
                        'upn': rec_upn or upn,
                        'mail': f"{(rec_login or login)}@{cfg['mail_domain']}",
                        'dn': rec_dn,
                        'error': None
                    }
            except Exception:
                pass

            err = f"Active Directory user '{user_dn}' already exists."
            return {'success': False, 'error': err}
        except Exception as e:
            err = f"Active Directory provisioning error: {e}"
            _logger.error(err)
            return {'success': False, 'error': err}
        finally:
            if conn:
                try:
                    conn.unbind_s()
                except Exception:
                    pass


    @api.model
    def disable_employee(self, employee):
        """
        Disable user account in Active Directory by adding ACCOUNTDISABLE (0x0002) to userAccountControl.
        Returns dict: {'success': bool, 'error': str}
        """
        cfg = self._get_ad_config(employee.company_id)
        conn = None
        try:
            conn = self._get_ldap_connection(cfg)
        except Exception as conn_err:
            _logger.warning("Could not connect to AD to disable user %s: %s", employee.name, conn_err)
            return {'success': False, 'error': str(conn_err)}

        try:
            user_dn = employee.ad_dn
            if not user_dn:
                search_terms = []
                emp_id = clean_ldap_text(
                    getattr(employee, 'identification_id', '') or getattr(employee, 'id', '')
                )
                if emp_id:
                    search_terms.append(f"(employeeID={emp_id})")
                if getattr(employee, 'ad_username', None):
                    search_terms.append(f"(sAMAccountName={employee.ad_username.strip()})")
                if getattr(employee, 'name', None):
                    search_terms.append(f"(displayName={employee.name.strip()})")
                    search_terms.append(f"(cn={employee.name.strip()})")

                if search_terms:
                    flt = f"(|{''.join(search_terms)})"
                    res = conn.search_s(cfg['base_dn'], ldap.SCOPE_SUBTREE, flt, ['distinguishedName', 'userAccountControl'])
                    valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                    if valid:
                        user_dn = valid[0][0]

            if not user_dn:
                _logger.warning("No AD user found to disable for employee %s", employee.name)
                return {'success': False, 'error': f"AD account for {employee.name} not found"}

            res = conn.search_s(user_dn, ldap.SCOPE_BASE, '(objectClass=*)', ['userAccountControl', 'sAMAccountName'])
            valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
            if valid:
                uac_bytes = valid[0][1].get('userAccountControl', [b'512'])[0]
                try:
                    current_uac = int(uac_bytes.decode('utf-8'))
                except Exception:
                    current_uac = 512
                new_uac = str(current_uac | 0x0002)
            else:
                new_uac = '514'

            conn.modify_s(user_dn, [(ldap.MOD_REPLACE, 'userAccountControl', [new_uac.encode('utf-8')])])
            _logger.info("Active Directory account disabled for employee %s (%s, UAC=%s)", employee.name, user_dn, new_uac)
            employee.sudo().write({'ad_sync_date': fields.Datetime.now()})
            employee.message_post(body=_(
                "Active Directory account has been <b>DISABLED</b> automatically upon archiving:<br/>"
                "• <b>DN:</b> %s<br/>"
                "• <b>userAccountControl:</b> %s (ACCOUNTDISABLE flag set)"
            ) % (user_dn, new_uac))
            return {'success': True, 'error': None}
        except Exception as e:
            err = f"Failed to disable AD account for {employee.name}: {e}"
            _logger.warning(err)
            return {'success': False, 'error': err}
        finally:
            if conn:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    @api.model
    def enable_employee(self, employee):
        """
        Re-enable user account in Active Directory by removing ACCOUNTDISABLE (0x0002) flag.
        Returns dict: {'success': bool, 'error': str}
        """
        cfg = self._get_ad_config(employee.company_id)
        conn = None
        try:
            conn = self._get_ldap_connection(cfg)
        except Exception as conn_err:
            _logger.warning("Could not connect to AD to enable user %s: %s", employee.name, conn_err)
            return {'success': False, 'error': str(conn_err)}

        try:
            user_dn = employee.ad_dn
            if not user_dn:
                search_terms = []
                emp_id = clean_ldap_text(
                    getattr(employee, 'identification_id', '') or getattr(employee, 'id', '')
                )
                if emp_id:
                    search_terms.append(f"(employeeID={emp_id})")
                if getattr(employee, 'ad_username', None):
                    search_terms.append(f"(sAMAccountName={employee.ad_username.strip()})")
                if getattr(employee, 'name', None):
                    search_terms.append(f"(displayName={employee.name.strip()})")
                    search_terms.append(f"(cn={employee.name.strip()})")

                if search_terms:
                    flt = f"(|{''.join(search_terms)})"
                    res = conn.search_s(cfg['base_dn'], ldap.SCOPE_SUBTREE, flt, ['distinguishedName', 'userAccountControl'])
                    valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
                    if valid:
                        user_dn = valid[0][0]

            if not user_dn:
                _logger.warning("No AD user found to enable for employee %s", employee.name)
                return {'success': False, 'error': f"AD account for {employee.name} not found"}

            res = conn.search_s(user_dn, ldap.SCOPE_BASE, '(objectClass=*)', ['userAccountControl'])
            valid = [r for r in res if isinstance(r, tuple) and r[0] is not None]
            if valid:
                uac_bytes = valid[0][1].get('userAccountControl', [b'514'])[0]
                try:
                    current_uac = int(uac_bytes.decode('utf-8'))
                except Exception:
                    current_uac = 514
                new_uac = str((current_uac | 0x0020) & ~0x0002)
            else:
                new_uac = '512'

            try:
                conn.modify_s(user_dn, [(ldap.MOD_REPLACE, 'userAccountControl', [new_uac.encode('utf-8')])])
                _logger.info("Active Directory account re-enabled for %s (%s, UAC=%s)", employee.name, user_dn, new_uac)
                employee.sudo().write({'ad_sync_date': fields.Datetime.now()})
                employee.message_post(body=_(
                    "Active Directory account has been <b>RE-ENABLED / UNDISABLED</b> automatically upon unarchiving:<br/>"
                    "• <b>DN:</b> %s<br/>"
                    "• <b>userAccountControl:</b> %s"
                ) % (user_dn, new_uac))
                return {'success': True, 'error': None}
            except ldap.UNWILLING_TO_PERFORM as e:
                _logger.warning("Active Directory requires a password set before enabling account %s: %s", user_dn, e)
                employee.message_post(body=_(
                    "Active Directory notice: Account <b>%s</b> is unarchived and ready to be re-enabled once password is set."
                ) % user_dn)
                return {'success': False, 'error': 'Password required by domain policy before enabling.'}
        except Exception as e:
            err = f"Failed to enable AD account for {employee.name}: {e}"
            _logger.warning(err)
            return {'success': False, 'error': err}
        finally:
            if conn:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

