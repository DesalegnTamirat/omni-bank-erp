from odoo import api, models


class HrEmployeePublic(models.Model):
    """The employee avatar widget searches hr.employee.public, not
    hr.employee, so the RESL guarantor bypass (resl_sudo_search) and the
    "hide current guarantors" filter (resl_exclude_loan_id) must exist here
    too.

    The candidate list for the guarantor fields is read straight from the
    hr_employee table (plain SQL): the ORM search on this model is narrowed
    to the logged-in user's own hierarchy by other modules / record rules,
    and that restriction must not apply when picking a guarantor.
    Only used when the field context carries resl_sudo_search."""
    _inherit = 'hr.employee.public'

    def _resl_exclude_ids(self):
        loan_id = self.env.context.get('resl_exclude_loan_id')
        if not loan_id:
            return []
        lines = self.env['resl.loan.guarantee'].sudo().search([
            ('loan_id', '=', loan_id),
            ('state', 'not in', ('replaced', 'rejected')),
        ])
        return lines.mapped('guarantor_id').ids

    @api.model
    def _resl_candidates(self, name, domain, operator, limit):
        """[(id, name)] of active employees, honouring only the simple
        domain terms the RESL views send: active, id != x, id not in [..]."""
        where = ['e.active IS TRUE']
        params = []
        excluded = set(self._resl_exclude_ids())
        for term in domain or []:
            if not isinstance(term, (list, tuple)) or len(term) != 3:
                continue
            field, op, value = term
            if field == 'id' and op == '!=' and value:
                excluded.add(int(value))
            elif field == 'id' and op == 'not in':
                excluded.update(int(v) for v in value)
        if excluded:
            where.append('e.id <> ALL(%s)')
            params.append(list(excluded))
        if name:
            where.append('e.name ILIKE %s')
            params.append('%' + name + '%')
        query = ('SELECT e.id, e.name FROM hr_employee e WHERE '
                 + ' AND '.join(where) + ' ORDER BY e.name LIMIT %s')
        params.append(limit or 8)
        self.env.cr.execute(query, params)
        return self.env.cr.fetchall()

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if self.env.context.get('resl_sudo_search'):
            return [(i, n) for i, n in self._resl_candidates(name, domain, operator, limit)]
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    @api.model
    def web_name_search(self, name, specification, domain=None, operator='ilike', limit=100):
        if self.env.context.get('resl_sudo_search'):
            return [
                {'id': i, 'display_name': n, '__formatted_display_name': n}
                for i, n in self._resl_candidates(name, domain, operator, limit)
            ]
        return super().web_name_search(
            name, specification, domain=domain, operator=operator, limit=limit
        )

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        """Same sudo bypass for the "Search More..." dialog of the new_guarantor_id
        field (it does not go through name_search / web_name_search).
        Without this override the core hr_employee_public_comp_rule record rule
        restricts results to the logged-in user and their direct reports only."""
        if self.env.context.get('resl_sudo_search'):
            # Honour the resl_exclude_loan_id exclusion and the id != x domain
            # term (borrower exclusion) before handing off to the superuser ORM.
            excluded = set(self._resl_exclude_ids())
            clean_domain = []
            for term in (domain or []):
                if not isinstance(term, (list, tuple)) or len(term) != 3:
                    clean_domain.append(term)
                    continue
                field, op, value = term
                if field == 'id' and op == '!=' and value:
                    excluded.add(int(value))
                elif field == 'id' and op == 'not in':
                    excluded.update(int(v) for v in value)
                else:
                    clean_domain.append(term)
            if excluded:
                clean_domain.append(('id', 'not in', list(excluded)))
            # Ensure only active employees are returned
            if not any(
                isinstance(t, (list, tuple)) and len(t) == 3 and t[0] == 'active'
                for t in clean_domain
            ):
                clean_domain.append(('active', '=', True))
            return super(HrEmployeePublic, self.sudo()).web_search_read(
                clean_domain, specification, offset=offset, limit=limit,
                order=order, count_limit=count_limit,
            )
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit,
            order=order, count_limit=count_limit,
        )