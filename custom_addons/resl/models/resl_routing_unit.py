# -*- coding: utf-8 -*-
"""Configuration > District Setup / Branch Setup.

One record per district office (work_unit_type = 'district_office') and per
branch. Each record owns its approver / disbursor lines (resl.routing.rule
with `unit_id` set), chosen by job position, by employees, or both:

  District : Approver, Approver's Approver (Director's Approver),
             Disburser, Disburser's Disburser
  Branch   : Approver, Approver's Approver, Disburser, Disburser's Disburser

Lines made for a unit come before the general lines of the Approvers &
Disbursors configuration.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .resl_routing_rule import BRANCH_TYPES, DISTRICT_TYPES

_logger = logging.getLogger(__name__)

# tier -> [(role, source, allow_self_disburse, default job positions)]
UNIT_ROLES = {
    'district': [
        ('approver', 'district', False, ['District Director']),
        ('director_approver', 'branch', False, ['Branch Support and Compliance Officer']),
        ('disbursor', 'branch', False, ['Branch Sales and Relationship Officer']),
        ('disbursor_backup', 'branch', False, ['Branch Manager - I']),
    ],
    'branch': [
        ('approver', 'branch', False, ['Branch Manager - I']),
        ('manager_approver', 'district', False, ['District Director']),
        ('disbursor', 'branch', False, ['Branch Sales and Relationship Officer']),
        ('disbursor_backup', 'branch', False, ['Branch Manager - I']),
    ],
}


class ReslRoutingUnit(models.Model):
    _name = 'resl.routing.unit'
    _description = 'RESL Approvers & Disbursors of a District / Branch'
    _order = 'tier, name'

    operating_unit_id = fields.Many2one(
        'operating.unit', string="District / Branch", required=True, ondelete='cascade',
        index=True, domain="[('work_unit_type', 'in', ['district_office', 'regional_office'])]")
    name = fields.Char(related='operating_unit_id.name', store=True)
    tier = fields.Selection(
        [('district', 'District'), ('branch', 'Branch')],
        compute='_compute_tier', store=True)
    department_id = fields.Many2one(
        'hr.department', string="District department",
        help="The department of this district. The branch employees working under the "
             "district are the ones in this department (or its sub-departments), the same "
             "way the district's own staff are. Filled in from the district's staff; "
             "change it if it is wrong.")
    rule_ids = fields.One2many('resl.routing.rule', 'setup_id', string="Approvers & Disbursors")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unit_unique', 'unique(operating_unit_id)',
         'This district / branch already has a setup.'),
    ]

    @api.depends('operating_unit_id.work_unit_type')
    def _compute_tier(self):
        for rec in self:
            wut = rec.operating_unit_id.work_unit_type
            rec.tier = 'district' if wut in DISTRICT_TYPES else (
                'branch' if wut in BRANCH_TYPES else False)

    @api.constrains('operating_unit_id')
    def _check_unit_type(self):
        for rec in self:
            if rec.tier != 'district':
                raise ValidationError(_(
                    "Only districts are set up one by one. Branches are set once in "
                    "Configuration > Branch Setup."))

    def _guess_department(self):
        """Department most of the district office's own staff belong to."""
        Employee = self.env['hr.employee'].sudo()
        for rec in self:
            if rec.department_id:
                continue
            groups = Employee._read_group(
                [('default_operating_unit_id', '=', rec.operating_unit_id.id),
                 ('department_id', '!=', False)],
                groupby=['department_id'], aggregates=['__count'],
                order='__count desc', limit=1)
            if groups:
                rec.sudo().department_id = groups[0][0]

    def _make_rules(self):
        """Create the missing lines (4 roles) of each district and give the
        empty ones their default job positions."""
        Rule = self.env['resl.routing.rule'].sudo().with_context(resl_skip_refresh=True)
        self._guess_department()
        for rec in self:
            lines = rec.rule_ids.with_context(active_test=False)
            for role, source, self_disb, jobs in UNIT_ROLES.get(rec.tier, []):
                rule = lines.filtered(lambda r: r.role == role)[:1]
                if not rule:
                    rule = Rule.create({
                        'tier': rec.tier, 'role': role, 'source': source,
                        'mode': 'job' if jobs else 'employee',
                        'unit_id': rec.operating_unit_id.id, 'setup_id': rec.id,
                        'allow_self_disburse': self_disb, 'max_count': 1})
                rule._fill_default_jobs(jobs)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._make_rules()
        return recs

    def unlink(self):
        self.mapped('rule_ids').unlink()
        return super().unlink()

    @api.model
    def generate_missing(self):
        """One setup record for every district office (branches are set once,
        in Branch Setup)."""
        OU = self.env['operating.unit'].sudo()
        existing = self.sudo().with_context(active_test=False).search([]).mapped(
            'operating_unit_id').ids
        # every district gets its 4 lines (and the defaults on the empty ones)
        self.sudo().with_context(active_test=False).search([('tier', '=', 'district')])._make_rules()
        units = OU.search([
            ('work_unit_type', 'in', list(DISTRICT_TYPES)),
            ('id', 'not in', existing)])
        if units:
            self.sudo().with_context(resl_skip_refresh=True).create(
                [{'operating_unit_id': u.id} for u in units])
        self.env['resl.routing.rule']._create_default_rules()   # Branch / HO lines
        self.env['resl.routing.rule']._refresh_open_loans()
        return len(units)

    @api.model
    def action_generate_missing(self):
        count = self.generate_missing()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("Districts"), 'type': 'success', 'sticky': False,
                       'message': _("%s district(s) added.") % count},
        }

    @api.model
    def _generate_defaults_once(self):
        from odoo.tools import sql
        if not sql.table_exists(self.env.cr, 'resl_routing_unit'):
            return True
        self.generate_missing()
        return True

    @api.model
    def _cleanup_branch_units(self):
        """One time: branches are no longer set up one by one (Branch Setup is
        a single set of lines), so the per-branch records made by the previous
        version are removed."""
        ICP = self.env['ir.config_parameter'].sudo()
        from odoo.tools import sql
        if ICP.get_param('resl.unit_branch_cleaned') or not sql.table_exists(
                self.env.cr, 'resl_routing_unit'):
            return True
        old = self.sudo().with_context(active_test=False).search([('tier', '=', 'branch')])
        old.unlink()
        ICP.set_param('resl.unit_branch_cleaned', '1')
        return True