# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.osv import expression


_EDS_SELECTOR_DOMAIN_FIELDS = frozenset({
    'id', 'company_id', 'department_id',
    'default_operating_unit_id', 'operating_unit_id',
    'job_id', 'job_position', 'parent_id', 'coach_id',
    'name', 'display_name', 'work_phone', 'work_email', 'user_id',
})
_EDS_SELECTOR_NAME_OPERATORS = frozenset({'ilike', '=ilike', 'like', '=like', '='})
_EDS_SELECTOR_READ_FIELDS = frozenset({
    'id', 'name', 'display_name', 'work_phone', 'work_email',
    'department_id', 'job_id', 'job_position', 'parent_id', 'coach_id',
    'default_operating_unit_id', 'operating_unit_id', 'company_id',
    'active', 'avatar_128', 'image_128', 'user_id',
    'address_id', 'work_location_id', 'work_location_name',
    'employee_type', 'resource_calendar_id', '__last_update',
    'write_date', 'create_date',
})


def _safe_eds_selector_domain_term(term):
    if isinstance(term, str):
        return term in ('&', '|', '!')
    if not isinstance(term, (list, tuple)) or len(term) != 3:
        return False
    field_name, operator, value = term
    if field_name == 'active':
        return operator in ('=', '!=') and type(value) in (bool, int)
    if field_name not in _EDS_SELECTOR_DOMAIN_FIELDS:
        return False
    if operator in _EDS_SELECTOR_NAME_OPERATORS:
        return isinstance(value, str) or value is False
    if operator in ('=', '!='):
        return type(value) in (bool, int) or value is False
    if operator in ('in', 'not in'):
        return (isinstance(value, (list, tuple, set)) and len(value) <= 10000
                and all(type(item) is int and item >= 0 for item in value))
    return False


class HrEmployeeEds(models.Model):
    """hr.employee extension: EDS training history, certificates, sponsorship smart buttons and offboarding bond clearance."""
    _inherit = 'hr.employee'

    eds_tna_entry_ids = fields.One2many('eds.tna.entry', 'employee_id', string='TNA Needs')
    eds_tna_entry_count = fields.Integer(string='Training Needs (TNA)', compute='_compute_eds_tna_counts')
    eds_certificate_ids = fields.One2many('eds.certificate', 'employee_id', string='Certificates')
    eds_certificate_count = fields.Integer(string='Certificates Count', compute='_compute_eds_tna_counts')
    eds_training_record_ids = fields.One2many(
        'eds.report.transcript', 'employee_id', string='EDS Training History', readonly=True)
    eds_training_record_count = fields.Integer(
        string='Training Records', compute='_compute_eds_training_record_count')
    eds_sponsorship_ids = fields.One2many('eds.sponsorship', 'employee_id', string='Sponsorships & Bonds')
    eds_sponsorship_count = fields.Integer(string='Sponsorships Count', compute='_compute_eds_tna_counts')
    
    # Active Bond and Service Obligation Tracking for Offboarding Clearance
    active_sponsorship_count = fields.Integer(string='Active Service Bonds', compute='_compute_eds_bonds')
    total_unamortized_bond_amount = fields.Monetary(
        string='Unamortized Bond Obligation',
        currency_field='currency_id',
        compute='_compute_eds_bonds',
        help='Total outstanding unamortized service bond obligation across all active sponsorships.'
    )
    has_active_bond_obligation = fields.Boolean(
        string='Has Active Bond Obligation',
        compute='_compute_eds_bonds',
        help='True if employee currently has active service bonds with unamortized financial obligations.'
    )

    @api.depends('eds_tna_entry_ids', 'eds_certificate_ids', 'eds_sponsorship_ids')
    def _compute_eds_tna_counts(self):
        for rec in self:
            rec.eds_tna_entry_count = len(rec.eds_tna_entry_ids)
            rec.eds_certificate_count = len(rec.eds_certificate_ids.filtered(lambda c: c.state == 'issued'))
            rec.eds_sponsorship_count = len(rec.eds_sponsorship_ids)

    def _compute_eds_training_record_count(self):
        Transcript = self.env['eds.report.transcript'].sudo()
        for rec in self:
            rec.eds_training_record_count = Transcript.search_count([('employee_id', '=', rec.id)])

    @api.depends('eds_sponsorship_ids.state', 'eds_sponsorship_ids.outstanding_obligation')
    def _compute_eds_bonds(self):
        for rec in self:
            active_bonds = rec.eds_sponsorship_ids.filtered(lambda s: s.state in ('active', 'breached'))
            rec.active_sponsorship_count = len(active_bonds)
            rec.total_unamortized_bond_amount = sum(active_bonds.mapped('outstanding_obligation'))
            rec.has_active_bond_obligation = rec.active_sponsorship_count > 0 and rec.total_unamortized_bond_amount > 0.0

    def action_view_eds_tna_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Training Needs (TNA)'),
            'res_model': 'eds.tna.entry',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Issued Certificates'),
            'res_model': 'eds.certificate',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_training_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('EDS Training History'),
            'res_model': 'eds.report.transcript',
            'view_mode': 'list',
            'domain': [('employee_id', '=', self.id)],
        }

    def action_view_eds_sponsorships(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sponsorships & Service Bonds'),
            'res_model': 'eds.sponsorship',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }

    def _is_eds_scoped_context(self):
        ctx = self.env.context
        if (ctx.get('eds_employee_select')
                or ctx.get('eds_self_service')
                or ctx.get('eds_work_unit_request')
                or str(ctx.get('active_model') or '').startswith('eds.')):
            return True

        params = ctx.get('params') or {}
        params_model = str(params.get('model') or '')
        params_active_model = str(params.get('active_model') or '')

        if params_model.startswith('eds.') or params_active_model.startswith('eds.'):
            return True

        try:
            from odoo.http import request
            if request and hasattr(request, 'params'):
                req_model = str(request.params.get('model') or '')
                if req_model.startswith('eds.'):
                    return True
        except Exception:
            pass

        return False

    def _check_access(self, operation: str):
        if operation == 'read' and (self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee')):
            return None
        return super()._check_access(operation)

    def check_access(self, operation: str) -> None:
        if operation == 'read' and (self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee')):
            return None
        return super().check_access(operation)

    def check_access_rule(self, operation):
        if operation == 'read' and (self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee')):
            return None
        return super().check_access_rule(operation)

    def _filter_access_rules_python(self, operation='read'):
        if operation == 'read' and (self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee')):
            return self
        return super()._filter_access_rules_python(operation=operation)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not bypass_access and (self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee')):
            bypass_access = True
        return super()._search(
            domain, offset=offset, limit=limit, order=order,
            active_test=active_test, bypass_access=bypass_access,
        )

    def read(self, fields=None, load='_classic_read'):
        if self.env.su:
            return super().read(fields=fields, load=load)
        if self._is_eds_scoped_context() or self.env.user.has_group('employee_development_system.group_eds_employee'):
            requested = set(fields or [])
            if not requested or requested.issubset(_EDS_SELECTOR_READ_FIELDS):
                return super(HrEmployeeEds, self.sudo()).read(fields=fields, load=load)
            safe_fields = [f for f in requested if f in _EDS_SELECTOR_READ_FIELDS]
            if safe_fields:
                return super(HrEmployeeEds, self.sudo()).read(fields=safe_fields, load=load)
        return super().read(fields=fields, load=load)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100, **kwargs):
        """Resolve names in EDS selectors without changing ordinary HR lookup.

        The context flag is only a selector opt-in for EDS staff. It never
        grants employee profile read access; ordinary searches and reads keep
        the Employee Master access rules.
        """
        if not (self._is_eds_scoped_context()
                or self.env.user.has_group(
                    'employee_development_system.group_eds_employee')):
            return super().name_search(
                name=name, domain=domain, operator=operator, limit=limit, **kwargs)
        requested_domain = list(domain or [])
        if requested_domain:
            try:
                requested_domain = expression.normalize_domain(requested_domain)
            except (TypeError, ValueError):
                return super().name_search(
                    name=name, domain=domain, operator=operator, limit=limit, **kwargs)
        safe_domain = all(_safe_eds_selector_domain_term(term)
                          for term in requested_domain)
        if not safe_domain or operator not in _EDS_SELECTOR_NAME_OPERATORS:
            # Never sudo a caller-supplied filter on private HR fields.
            return super().name_search(
                name=name, domain=domain, operator=operator, limit=limit, **kwargs)
        has_id_in = any(
            isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == 'id' and term[1] == 'in'
            for term in requested_domain
        )
        managed_domain = (
            [] if (has_id_in or self.env.user.has_group('employee_development_system.group_eds_officer'))
            else self.env['eds.hr.compat'].get_managed_employee_read_domain())
        employee_domain = expression.AND([
            [('active', '=', True)], requested_domain, managed_domain,
            [('name', operator, name)] if name else [],
        ])
        employees = self.sudo().search(employee_domain, limit=min(limit or 100, 100))
        return [(employee.id, employee.name or '') for employee in employees]

    def web_read(self, specification):
        """Allow UI relational fields to read safe selector fields under eds_employee_select."""
        if self.env.su:
            return super().web_read(specification)
        if (self._is_eds_scoped_context()
                or self.env.user.has_group(
                    'employee_development_system.group_eds_employee')):
            requested_fields = set(specification or {})
            if requested_fields.issubset(_EDS_SELECTOR_READ_FIELDS):
                return self.sudo().web_read(specification)
            safe_spec = {k: v for k, v in (specification or {}).items() if k in _EDS_SELECTOR_READ_FIELDS}
            if safe_spec:
                return self.sudo().web_read(safe_spec)
        return super().web_read(specification)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        """Allow UI SelectCreateDialog to search and list safe directory records under eds_employee_select."""
        if self.env.su:
            return super().web_search_read(
                domain=domain, specification=specification, offset=offset,
                limit=limit, order=order, count_limit=count_limit)
        if not (self._is_eds_scoped_context()
                or self.env.user.has_group(
                    'employee_development_system.group_eds_employee')):
            return super().web_search_read(
                domain=domain, specification=specification, offset=offset,
                limit=limit, order=order, count_limit=count_limit)
        clean_domain = list(domain or [])
        if clean_domain:
            try:
                clean_domain = expression.normalize_domain(clean_domain)
            except (TypeError, ValueError):
                return super().web_search_read(
                    domain=domain, specification=specification, offset=offset,
                    limit=limit, order=order, count_limit=count_limit)
        if not all(_safe_eds_selector_domain_term(term) for term in clean_domain):
            return super().web_search_read(
                domain=domain, specification=specification, offset=offset,
                limit=limit, order=order, count_limit=count_limit)
        has_id_in = any(
            isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == 'id' and term[1] == 'in'
            for term in clean_domain
        )
        managed_domain = (
            [] if (has_id_in or self.env.user.has_group('employee_development_system.group_eds_officer'))
            else self.env['eds.hr.compat'].get_managed_employee_read_domain())
        full_domain = expression.AND([[('active', '=', True)], clean_domain, managed_domain])
        requested_fields = set(specification or {})
        if requested_fields.issubset(_EDS_SELECTOR_READ_FIELDS):
            return self.sudo().web_search_read(
                domain=full_domain, specification=specification, offset=offset,
                limit=limit, order=order, count_limit=count_limit)
        safe_spec = {k: v for k, v in (specification or {}).items() if k in _EDS_SELECTOR_READ_FIELDS}
        if not safe_spec:
            safe_spec = {'id': {}, 'display_name': {}}
        return self.sudo().web_search_read(
            domain=full_domain, specification=safe_spec, offset=offset,
            limit=limit, order=order, count_limit=count_limit)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        """Allow search_read for safe selector fields under eds_employee_select."""
        if self.env.su:
            return super().search_read(
                domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        if not (self._is_eds_scoped_context()
                and self.env.user.has_group(
                    'employee_development_system.group_eds_employee')):
            return super().search_read(
                domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        clean_domain = list(domain or [])
        if clean_domain:
            try:
                clean_domain = expression.normalize_domain(clean_domain)
            except (TypeError, ValueError):
                return super().search_read(
                    domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        if not all(_safe_eds_selector_domain_term(term) for term in clean_domain):
            return super().search_read(
                domain=domain, fields=fields, offset=offset, limit=limit, order=order)
        has_id_in = any(
            isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == 'id' and term[1] == 'in'
            for term in clean_domain
        )
        managed_domain = (
            [] if (has_id_in or self.env.user.has_group('employee_development_system.group_eds_officer'))
            else self.env['eds.hr.compat'].get_managed_employee_read_domain())
        full_domain = expression.AND([[('active', '=', True)], clean_domain, managed_domain])
        requested_fields = set(fields or [])
        if requested_fields and requested_fields.issubset(_EDS_SELECTOR_READ_FIELDS):
            return self.sudo().search_read(
                domain=full_domain, fields=fields, offset=offset, limit=limit, order=order)
        safe_fields = [f for f in (fields or []) if f in _EDS_SELECTOR_READ_FIELDS]
        if not safe_fields:
            safe_fields = ['id', 'display_name']
        return self.sudo().search_read(
            domain=full_domain, fields=safe_fields, offset=offset, limit=limit, order=order)
