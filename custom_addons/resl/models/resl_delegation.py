import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Table that stores "A delegates to B between start_date and end_date".
DELEGATION_TABLE = 'hr_employee_delegation'
# Candidate column names (the first one that exists in the table is used).
DELEGATOR_COLUMNS = ('employee_id', 'delegator_id', 'delegated_by_id', 'manager_id')
DELEGATE_COLUMNS = ('delegate_id', 'delegate_employee_id', 'delegated_to_id')
START_COLUMNS = ('start_date', 'date_start', 'date_from')
END_COLUMNS = ('end_date', 'date_end', 'date_to')

# RESL groups whose "see everything" record rules a delegate inherits.
_ALL_ACCESS_GROUPS = (
    'resl.group_resl_ho_approver', 'resl.group_resl_hr', 'resl.group_resl_hr_senior',
    'resl.group_resl_pomd', 'resl.group_resl_head_office',
)


class ResUsers(models.Model):
    _inherit = 'res.users'

    resl_effective_user_ids = fields.Many2many(
        'res.users', compute='_compute_resl_delegation_flags',
        string="RESL Effective Users (self + delegators)",
        help="The user themself plus every user who currently delegates "
             "their RESL role to this user (hr_employee_delegation, today "
             "between start_date and end_date). Used by the record rules.",
    )
    resl_deleg_all_access = fields.Boolean(
        compute='_compute_resl_delegation_flags',
        help="A current delegator holds a Head Office / HR role (sees all loans).",
    )
    resl_deleg_auditor = fields.Boolean(
        compute='_compute_resl_delegation_flags',
        help="A current delegator is an HR Auditor (read-only, all loans).",
    )
    resl_deleg_accountant = fields.Boolean(
        compute='_compute_resl_delegation_flags',
        help="A current delegator is an HR Accountant (all loans).",
    )

    # ── Delegation lookup ────────────────────────────────────────────────────

    @api.model
    def _resl_delegation_columns(self):
        """Resolve the real column names of hr_employee_delegation once."""
        cache = self.env.registry.__dict__.get('_resl_delegation_cols')
        if cache is not None:
            return cache
        cols = None
        try:
            self.env.cr.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s", (DELEGATION_TABLE,))
            existing = {r[0] for r in self.env.cr.fetchall()}

            def pick(cands):
                return next((c for c in cands if c in existing), None)

            delegator = pick(DELEGATOR_COLUMNS)
            delegate = pick(DELEGATE_COLUMNS)
            start = pick(START_COLUMNS)
            end = pick(END_COLUMNS)
            if delegator and delegate and start:
                # Is the delegate column an hr.employee id or a res.users id?
                self.env.cr.execute("""
                    SELECT ccu.table_name
                      FROM information_schema.table_constraints tc
                      JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                       AND tc.table_schema = kcu.table_schema
                      JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                       AND ccu.table_schema = tc.table_schema
                     WHERE tc.constraint_type = 'FOREIGN KEY'
                       AND tc.table_name = %s AND kcu.column_name = %s
                     LIMIT 1""", (DELEGATION_TABLE, delegate))
                row = self.env.cr.fetchone()
                delegate_is_user = bool(row and row[0] == 'res_users')
                self.env.cr.execute("""
                    SELECT ccu.table_name
                      FROM information_schema.table_constraints tc
                      JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                       AND tc.table_schema = kcu.table_schema
                      JOIN information_schema.constraint_column_usage ccu
                        ON ccu.constraint_name = tc.constraint_name
                       AND ccu.table_schema = tc.table_schema
                     WHERE tc.constraint_type = 'FOREIGN KEY'
                       AND tc.table_name = %s AND kcu.column_name = %s
                     LIMIT 1""", (DELEGATION_TABLE, delegator))
                row = self.env.cr.fetchone()
                delegator_is_user = bool(row and row[0] == 'res_users')
                cols = {
                    'delegator': delegator, 'delegate': delegate,
                    'start': start, 'end': end,
                    'delegator_is_user': delegator_is_user,
                    'delegate_is_user': delegate_is_user,
                    'active': 'active' in existing,
                }
        except Exception:
            _logger.exception("RESL: cannot inspect %s", DELEGATION_TABLE)
        # Never cache a failed / empty lookup: if the delegation table did not
        # exist yet when this first ran, caching {} would disable delegation
        # until the server is restarted.
        if cols:
            self.env.registry.__dict__['_resl_delegation_cols'] = cols
        return cols or {}

    def _resl_delegator_users(self):
        """Users whose role has been delegated to `self` TODAY (start_date <=
        today <= end_date; a blank end_date means open-ended)."""
        self.ensure_one()
        none = self.env['res.users']
        if not self.id:
            return none
        cols = self._resl_delegation_columns()
        if not cols:
            return none
        today = fields.Date.context_today(self)
        Employee = self.env['hr.employee'].sudo().with_context(active_test=False)
        if cols['delegate_is_user']:
            delegate_key = self.id
        else:
            emps = Employee.search([('user_id', '=', self.id)])
            if not emps:
                return none
            delegate_key = tuple(emps.ids)
        where = ['"%s" = %s' % (cols['delegate'], '%s' if cols['delegate_is_user'] else 'ANY(%s)')]
        params = [delegate_key if cols['delegate_is_user'] else list(delegate_key)]
        where.append('"%s" <= %%s' % cols['start'])
        params.append(today)
        if cols['end']:
            where.append('("%s" IS NULL OR "%s" >= %%s)' % (cols['end'], cols['end']))
            params.append(today)
        if cols['active']:
            where.append('COALESCE(active, TRUE)')
        self.env.cr.execute(
            'SELECT DISTINCT "%s" FROM %s WHERE %s' % (
                cols['delegator'], DELEGATION_TABLE, ' AND '.join(where)),
            params)
        ids = [r[0] for r in self.env.cr.fetchall() if r[0]]
        if not ids:
            return none
        if cols['delegator_is_user']:
            return self.sudo().browse(ids).exists() - self
        return Employee.browse(ids).mapped('user_id').sudo() - self

    def _resl_delegate_users(self):
        """Users `self` has delegated their role to TODAY (the reverse of
        _resl_delegator_users). Used to also notify the delegates."""
        self.ensure_one()
        none = self.env['res.users']
        if not self.id:
            return none
        cols = self._resl_delegation_columns()
        if not cols:
            return none
        today = fields.Date.context_today(self)
        Employee = self.env['hr.employee'].sudo().with_context(active_test=False)
        if cols['delegator_is_user']:
            keys = [self.id]
        else:
            keys = Employee.search([('user_id', '=', self.id)]).ids
            if not keys:
                return none
        where = ['"%s" = ANY(%%s)' % cols['delegator'], '"%s" <= %%s' % cols['start']]
        params = [keys, today]
        if cols['end']:
            where.append('("%s" IS NULL OR "%s" >= %%s)' % (cols['end'], cols['end']))
            params.append(today)
        if cols['active']:
            where.append('COALESCE(active, TRUE)')
        self.env.cr.execute(
            'SELECT DISTINCT "%s" FROM %s WHERE %s' % (
                cols['delegate'], DELEGATION_TABLE, ' AND '.join(where)),
            params)
        ids = [r[0] for r in self.env.cr.fetchall() if r[0]]
        if not ids:
            return none
        if cols['delegate_is_user']:
            return self.sudo().browse(ids).exists() - self
        return Employee.browse(ids).mapped('user_id').sudo() - self

    def _resl_notify_users(self):
        """`self` plus everyone `self` currently delegates to: all of them
        should receive the to-do for an approval / disbursement."""
        self.ensure_one()
        return self | self._resl_delegate_users()

    def _resl_effective_users(self):
        """`self` plus everyone who currently delegates to `self`."""
        self.ensure_one()
        return self | self._resl_delegator_users()

    def _resl_effective_user_ids(self):
        return self._resl_effective_users().ids

    def _resl_is_admin(self):
        """True for the RESL "Admin" role or an Odoo Administrator (own role
        or a delegated one): may approve / reject / disburse any loan
        regardless of per-loan routing."""
        self.ensure_one()
        return (self._resl_has_group('resl.group_resl_admin')
                or self._resl_has_group('base.group_system'))

    def _resl_has_group(self, group_xmlid):
        """has_group(), but a user also holds every group of the people who
        currently delegate to them."""
        self.ensure_one()
        if self.has_group(group_xmlid):
            return True
        return any(u.sudo().has_group(group_xmlid) for u in self._resl_delegator_users())

    def _compute_resl_delegation_flags(self):
        for user in self:
            effective = user._resl_effective_users() if user.id else user
            user.resl_effective_user_ids = effective
            delegators = effective - user
            user.resl_deleg_all_access = any(
                u.sudo().has_group(g) for u in delegators for g in _ALL_ACCESS_GROUPS)
            user.resl_deleg_auditor = any(
                u.sudo().has_group('resl.group_resl_hr_auditor') for u in delegators)
            user.resl_deleg_accountant = any(
                u.sudo().has_group('resl.group_resl_hr_accountant') for u in delegators)