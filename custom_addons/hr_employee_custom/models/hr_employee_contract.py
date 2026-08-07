# -*- coding: utf-8 -*-
# Employee model — contract-related fields and methods (Odoo 19)

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ─────────────────────────────────────────────────────────────────────────
    # CONTRACT FIELDS
    # ─────────────────────────────────────────────────────────────────────────
    contract_ids = fields.One2many(
        'hr.contract', 'employee_id',
        string='Employee Contracts')
    contract_id = fields.Many2one(
        'hr.contract', string='Current Contract',
        domain="[('company_id', '=', company_id)]",
        help='Current contract of the employee')
    contracts_count = fields.Integer(
        compute='_compute_contracts_count',
        string='Contract Count')
    contract_warning = fields.Boolean(
        string='Contract Warning', store=True,
        compute='_compute_contract_warning')
    first_contract_date = fields.Date(
        compute='_compute_first_contract_date')
    calendar_mismatch = fields.Boolean(
        related='contract_id.calendar_mismatch')

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_first_contracts(self):
        """Return all non-cancelled contracts for this employee.

        Uses sudo() so that the computed field (_compute_first_contract_date)
        can access contracts regardless of the calling user's record rules.
        """
        self.ensure_one()
        return self.sudo().contract_ids.filtered(
            lambda c: c.state != 'cancel')

    @api.depends('contract_ids.state', 'contract_ids.date_start')
    def _compute_first_contract_date(self):
        for employee in self:
            contracts = employee._get_first_contracts()
            if contracts:
                employee.first_contract_date = min(
                    contracts.mapped('date_start'))
            else:
                employee.first_contract_date = False

    # FIX: added 'contract_ids' to depends so that creating a first contract
    # (which leaves contract_id unset) still triggers a recompute of the warning.
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

    # FIX: read_group is removed in Odoo 19; use _read_group instead.
    # FIX: count only non-cancelled contracts so the number is consistent
    # with _get_first_contracts() and the general notion of "valid contracts".
    def _compute_contracts_count(self):
        contract_groups = self.env['hr.contract'].sudo()._read_group(
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

    # ─────────────────────────────────────────────────────────────────────────
    # CONTRACT QUERY HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_contracts(self, date_from, date_to,
                       states=None, kanban_state=False):
        """Return contracts for this employee set overlapping [date_from, date_to].

        :param date_from:    start of the period (date)
        :param date_to:      end of the period (date)
        :param states:       list of contract states to include (default: ['open'])
        :param kanban_state: list of kanban states to filter on, e.g. ['done'],
                             or False to skip the kanban filter
        """
        if states is None:
            states = ['open']

        # In Odoo 19, search() accepts a plain domain list; adjacent tuples are
        # implicitly AND-ed by the framework. The '|' operator applies only to
        # the two leaves that immediately follow it.
        domain = [
            ('employee_id', 'in', self.ids),
            ('state', 'in', states),
            ('date_start', '<=', date_to),
            '|',
            ('date_end', '=', False),
            ('date_end', '>=', date_from),
        ]

        if kanban_state:
            domain += [('kanban_state', 'in', kanban_state)]

        return self.env['hr.contract'].search(domain)

    def _get_incoming_contracts(self, date_from, date_to):
        """Return draft contracts that are ready-to-go (kanban state 'done')."""
        return self._get_contracts(
            date_from, date_to,
            states=['draft'], kanban_state=['done'])

    @api.model
    def _get_all_contracts(self, date_from, date_to, states=None):
        """Return contracts for *all* employees overlapping [date_from, date_to].

        Searches directly on hr.contract to avoid a full employee table scan.
        """
        if states is None:
            states = ['open']
        return self.env['hr.contract'].search([
            ('state', 'in', states),
            ('date_start', '<=', date_to),
            '|',
            ('date_end', '=', False),
            ('date_end', '>=', date_from),
        ])

    # ─────────────────────────────────────────────────────────────────────────
    # WRITE OVERRIDE
    # ─────────────────────────────────────────────────────────────────────────

    def write(self, vals):
        res = super().write(vals)
        if vals.get('contract_id'):
            # FIX: collect calendar updates and apply them in a single batched
            # write via super() to avoid re-entering this write() override and
            # causing infinite recursion.
            calendar_updates = {}  # employee_id -> new resource_calendar_id
            for employee in self:
                calendar = employee.resource_calendar_id
                new_calendar = employee.contract_id.resource_calendar_id
                if calendar and new_calendar and calendar != new_calendar:
                    # FIX: log a warning instead of silently skipping when the
                    # transfer method is absent (missing module / version mismatch).
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

            # Apply resource_calendar_id changes via super() to bypass this
            # override and prevent recursive write() calls.
            for employee in self:
                if employee.id in calendar_updates:
                    super(HrEmployee, employee).write(
                        {'resource_calendar_id': calendar_updates[employee.id]}
                    )
        return res
