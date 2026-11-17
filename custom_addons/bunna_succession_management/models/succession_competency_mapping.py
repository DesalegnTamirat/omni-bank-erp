# -*- coding: utf-8 -*-
from odoo import models, api

class CompetencyRoleMappingLineSuccession(models.Model):
    """Extend competency.role.mapping.line to allow seamless read access for Succession Management users."""
    _inherit = 'competency.role.mapping.line'

    def _is_succession_user(self):
        user = self.env.user
        return (
            self.env.su or
            user.has_group('bunna_succession_management.group_succession_ppdd') or
            user.has_group('bunna_succession_management.group_succession_spmc') or
            user.has_group('bunna_succession_management.group_succession_admin') or
            user.has_group('competency_management.group_competency_admin')
        )

    def _check_access(self, operation: str):
        if operation == 'read' and self._is_succession_user():
            return None
        return super()._check_access(operation)

    def check_access(self, operation: str) -> None:
        if operation == 'read' and self._is_succession_user():
            return None
        return super().check_access(operation)

    def check_access_rule(self, operation):
        if operation == 'read' and self._is_succession_user():
            return None
        return super().check_access_rule(operation)

    def _filter_access_rules_python(self, operation='read'):
        if operation == 'read' and self._is_succession_user():
            return self
        return super()._filter_access_rules_python(operation=operation)

    def _filtered_access(self, operation='read'):
        if operation == 'read' and self._is_succession_user():
            return self
        return super()._filtered_access(operation=operation)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self._is_succession_user():
            bypass_access = True
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def web_read(self, specification):
        if self._is_succession_user():
            self = self.sudo()
        return super().web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        if self._is_succession_user():
            self = self.sudo()
        return super().read(fields=fields, load=load)


class CompetencyRoleMappingSuccession(models.Model):
    """Extend competency.role.mapping to allow seamless read access for Succession Management users."""
    _inherit = 'competency.role.mapping'

    def _is_succession_user(self):
        user = self.env.user
        return (
            self.env.su or
            user.has_group('bunna_succession_management.group_succession_ppdd') or
            user.has_group('bunna_succession_management.group_succession_spmc') or
            user.has_group('bunna_succession_management.group_succession_admin') or
            user.has_group('competency_management.group_competency_admin')
        )

    def _check_access(self, operation: str):
        if operation == 'read' and self._is_succession_user():
            return None
        return super()._check_access(operation)

    def check_access(self, operation: str) -> None:
        if operation == 'read' and self._is_succession_user():
            return None
        return super().check_access(operation)

    def check_access_rule(self, operation):
        if operation == 'read' and self._is_succession_user():
            return None
        return super().check_access_rule(operation)

    def _filter_access_rules_python(self, operation='read'):
        if operation == 'read' and self._is_succession_user():
            return self
        return super()._filter_access_rules_python(operation=operation)

    def _filtered_access(self, operation='read'):
        if operation == 'read' and self._is_succession_user():
            return self
        return super()._filtered_access(operation=operation)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if self._is_succession_user():
            bypass_access = True
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def web_read(self, specification):
        if self._is_succession_user():
            self = self.sudo()
        return super().web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        if self._is_succession_user():
            self = self.sudo()
        return super().read(fields=fields, load=load)
