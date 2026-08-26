# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _search_version_id(self, operator, value):
        if operator in ('in', 'not in', '=', '!=', 'any', 'any!'):
            from odoo.orm.domains import Domain
            return Domain('current_version_id', operator, value)
        return super()._search_version_id(operator, value)




    contract_ids = fields.One2many(
        'hr.version', 'employee_id',
        string='Employee Contracts')
    contract_id = fields.Many2one(
        'hr.version', string='Current Contract',
        domain="[('company_id', '=', company_id),('employee_id', '=', id)]",
        help='Current contract of the employee')
    contracts_count = fields.Integer(
        compute='_compute_contracts_count',
        string='Contract Count')
    contract_warning = fields.Boolean(
        string='Contract Warning',
        compute='_compute_contract_warning')
    first_contract_date = fields.Date(
        compute='_compute_first_contract_date')

    # ─────────────────────────────────────────────────────────────────────────

    calendar_mismatch = fields.Boolean(
        string='Calendar Mismatch',
        compute='_compute_calendar_mismatch',
        store=False,
        help='True when the employee\'s working schedule differs from their '
             'current contract\'s working schedule.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_first_contracts(self):
        """Return all non-cancelled contracts for this employee."""
        self.ensure_one()
        return self.sudo().contract_ids.filtered(
            lambda c: c.state != 'cancel')

    @api.depends('contract_ids.state', 'contract_ids.contract_date_start')
    def _compute_first_contract_date(self):
        for employee in self:
            contracts = employee._get_first_contracts()
            start_dates = [
                d for d in contracts.mapped('contract_date_start') if d
            ]
            employee.first_contract_date = min(start_dates) if start_dates else False

    @api.depends(
        'contract_id', 'contract_id.state', 'contract_id.kanban_state',
        'contract_ids',
    )
    def _compute_contract_warning(self):
        for employee in self:
            employee.contract_warning = (
                not employee.contract_id
                or employee.contract_id.kanban_state == 'blocked'
                or employee.contract_id.state not in ('open', 'probation')
            )

    def _compute_contracts_count(self):
        contract_groups = self.env['hr.version'].sudo()._read_group(
            domain=[
                ('employee_id', 'in', self.ids),
                ('state', '!=', 'cancel'),
            ],
            groupby=['employee_id'],
            aggregates=['__count'],
        )
        result = {employee.id: count for employee, count in contract_groups}
        for employee in self:
            employee.contracts_count = result.get(employee.id, 0)

    @api.depends(
        'contract_id',
        'contract_id.resource_calendar_id',
        'resource_calendar_id',
    )
    def _compute_calendar_mismatch(self):
        """Flag True when the employee's working schedule differs from the
        current contract's working schedule.  Mirrors the Odoo 14
        hr.contract.calendar_mismatch concept, adapted for hr.version."""
        for employee in self:
            if not employee.contract_id or not employee.contract_id.resource_calendar_id:
                employee.calendar_mismatch = False
            else:
                employee.calendar_mismatch = (
                    employee.resource_calendar_id
                    != employee.contract_id.resource_calendar_id
                )


    def _get_contracts(self, date_from, date_to,
                       states=None, kanban_state=False):
        """Return contracts for this employee set overlapping [date_from, date_to]."""
        if states is None:
            states = ['open']

        domain = [
            ('employee_id', 'in', self.ids),
            ('state', 'in', states),
            ('contract_date_start', '<=', date_to),
            '|',
            ('contract_date_end', '=', False),
            ('contract_date_end', '>=', date_from),
        ]

        if kanban_state:
            domain += [('kanban_state', 'in', kanban_state)]

        return self.env['hr.version'].search(domain)

    def _get_incoming_contracts(self, date_from, date_to):
        """Return draft contracts that are ready-to-go (kanban state 'done')."""
        return self._get_contracts(
            date_from, date_to,
            states=['draft'], kanban_state=['done'])

    @api.model
    def _get_all_contracts(self, date_from, date_to, states=None):
        """Return contracts for *all* employees overlapping [date_from, date_to]."""
        if states is None:
            states = ['open']
        return self.env['hr.version'].search([
            ('state', 'in', states),
            ('contract_date_start', '<=', date_to),
            '|',
            ('contract_date_end', '=', False),
            ('contract_date_end', '>=', date_from),
        ])

    # ─────────────────────────────────────────────────────────────────────────
    # WRITE OVERRIDE
    # ─────────────────────────────────────────────────────────────────────────

    def write(self, vals):
        res = super().write(vals)
        if vals.get('contract_id'):
            calendar_updates = {}
            for employee in self:
                calendar = employee.resource_calendar_id
                new_calendar = employee.contract_id.resource_calendar_id
                if calendar and new_calendar and calendar != new_calendar:
                    if hasattr(calendar, 'transfer_leaves_to'):
                        calendar.transfer_leaves_to(
                            new_calendar, employee.resource_id)
                    else:
                        _logger.warning(
                            "Cannot transfer leaves for employee %s (id=%s): "
                            "'transfer_leaves_to' is not available on %s. "
                            "Leave balances may need to be adjusted manually.",
                            employee.name, employee.id, calendar,
                        )
                    calendar_updates[employee.id] = new_calendar.id

            for employee in self:
                if employee.id in calendar_updates:
                    employee.with_context(skip_calendar_sync=True).write(
                        {'resource_calendar_id': calendar_updates[employee.id]}
                    )
        return res