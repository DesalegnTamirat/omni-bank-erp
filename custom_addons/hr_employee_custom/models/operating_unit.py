# -*- coding: utf-8 -*-
from email.policy import default

from odoo.exceptions import UserError
from odoo import api, fields, models, _


class OperatingUnit(models.Model):
    _name = "operating.unit"
    _description = "Operating Unit"
    _order = 'sol_id'
    name = fields.Char(required=True)
    # code = fields.Char(string="Code")
    code = fields.Many2one(
        comodel_name='hr.report.code',
        string='Report Code',
    )
    manager_id = fields.Many2one('hr.employee',string ="Manager")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    # partner_id = fields.Many2one("res.partner", "Company", readonly=True,default=lambda self: self.env.company)
    user_ids = fields.Many2many(
        "res.users",
        "operating_unit_users_rel",
        "operating_unit_id",
        "user_id",
        "Users Allowed",
    )

    ## added for operating unit
    job_position_ids = fields.One2many(
        comodel_name='operating.unit.job.position',
        inverse_name='operating_unit_id',
        string='Job Positions',
    )
    sol_id = fields.Integer(
        string='Sol ID',
        required=True,
        help='Numeric Sol identifier for this operating unit.',
    )

    # ── Classification ────────────────────────────────────────────────────
    work_unit_type = fields.Selection(
        selection=[
            ('branch', 'Branch'),
            ('sub_branch', 'Sub-Branch'),
            ('head_office', 'Head Office'),
            ('regional_office', 'Regional Office'),
            ('district_office', 'District Office'),
            ('service_center', 'Service Center'),
            ('other', 'Other'),
        ],
        string='Work Unit Type',
        required=True,
    )
    is_ifb = fields.Boolean(
        string='Is IFB',
        default=False,
        help='Indicates whether this branch operates under Interest-Free Banking (IFB).',
    )
    location_type = fields.Selection(
        selection=[
            ('city_branch', 'City Branch'),
            ('outline', 'Outline Branch'),
        ],
        string='Location Type',
        help='Operating unit location classification (City Branch or Outline Branch).',
    )

    @api.onchange('work_unit_type')
    def _onchange_work_unit_type(self):
        if self.work_unit_type != 'branch':
            self.is_ifb = False

    parent_unit = fields.Many2one(
        comodel_name='operating.unit',
        string='Parent Unit',
        ondelete='set null',
        domain="[('id', '!=', id)]",
        help='Leave empty if this is a top-level unit.',
    )

    branch_grade = fields.Char(
        string='Branch Grade',
    )
    latitude=fields.Float(string="Latitude")
    longitude = fields.Float(string="Longitude")
    district = fields.Char(string="District")
    region = fields.Char(string="Region")
    department = fields.Many2one('hr.department', string='Department')

    @api.onchange('parent_unit')
    def _onchange_parent_unit_sync_department(self):
        if self.parent_unit and getattr(self.parent_unit, 'department', False) and not self.department:
            self.department = self.parent_unit.department

    @api.depends('name', 'code', 'code.code', 'code.name')
    def _compute_display_name(self):
        for ou in self:
            try:
                name = ou.name or ''
                code_str = ''
                if ou.code:
                    code_val = ou.code.code or ou.code.name or ''
                    code_str = str(code_val).strip()
                if code_str:
                    ou.display_name = f"[{code_str}] {name}"
                else:
                    ou.display_name = name
            except Exception:
                # Fallback purely in-memory to prevent re-querying an aborted PostgreSQL transaction
                ou.display_name = ou._origin.name if hasattr(ou, '_origin') and getattr(ou._origin, 'name', False) else ''

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if isinstance(value, str) and value.strip():
            term = value.strip()
            conditions = [('code.name', operator, term)]
            if term.isdigit():
                num = int(term)
                conditions.append(('code.code', '=', num))
                conditions.append(('sol_id', '=', num))
            for cond in conditions:
                domain = ['|', cond] + domain
        return domain

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.user_ids += self.env.user
        return records

    def write(self, vals):
        old_managers = {unit.id: unit.manager_id for unit in self} if 'manager_id' in vals else {}
        res = super().write(vals)
        if not self.env.context.get('_in_ou_hierarchy_sync'):
            if 'manager_id' in vals:
                self._sync_unit_employees_hierarchy(old_managers=old_managers)
            elif 'parent_unit' in vals:
                for unit in self:
                    if unit.manager_id and unit.parent_unit and unit.parent_unit.manager_id:
                        p_mgr = unit.parent_unit.manager_id
                        if p_mgr.id != unit.manager_id.id:
                            unit.manager_id.with_context(_in_ou_hierarchy_sync=True).write({
                                'parent_id': p_mgr.id,
                                'coach_id': p_mgr.id,
                                'planning_parent_id': p_mgr.id,
                            })
        return res

    def _sync_unit_employees_hierarchy(self, old_managers=None):
        """Automatically propagate the Operating Unit's manager to all employees
        assigned to this unit as their default operating unit.
        Also sets the manager of the unit manager to the parent unit's manager.
        Ensures manager's own default_operating_unit_id matches this unit,
        and unlinks this manager from other operating units to prevent duplicate leadership.
        """
        if self.env.context.get('_in_ou_hierarchy_sync'):
            return

        ctx = dict(self.env.context, _in_ou_hierarchy_sync=True)
        self_sync = self.with_context(ctx)

        for unit in self_sync:
            manager = unit.manager_id
            if manager:
                # 1. Unassign this manager from any other operating unit to avoid duplicate branch leadership
                other_units = self.env['operating.unit'].with_context(ctx).search([
                    ('id', '!=', unit.id),
                    ('manager_id', '=', manager.id),
                    ('active', '=', True),
                ])
                if other_units:
                    other_units.write({'manager_id': False})

                # 2. Align the manager's own default operating unit to this unit
                if manager.default_operating_unit_id.id != unit.id:
                    manager.with_context(ctx).write({
                        'default_operating_unit_id': unit.id,
                    })

                # 3. Propagate manager to all employees in this unit (excluding the manager themselves)
                employees = self.env['hr.employee'].with_context(ctx).search([
                    ('default_operating_unit_id', '=', unit.id),
                    ('id', '!=', manager.id),
                ])
                if employees:
                    employees.write({
                        'parent_id': manager.id,
                        'coach_id': manager.id,
                        'planning_parent_id': manager.id,
                    })

                # 4. For the unit manager themselves, their manager is the parent unit's manager
                if unit.parent_unit and unit.parent_unit.manager_id:
                    parent_mgr = unit.parent_unit.manager_id
                    if parent_mgr.id != manager.id:
                        manager.with_context(ctx).write({
                            'parent_id': parent_mgr.id,
                            'coach_id': parent_mgr.id,
                            'planning_parent_id': parent_mgr.id,
                        })

    def action_sync_employees_to_manager(self):
        """Manual action button to immediately align all employees in this unit
        with the assigned Operating Unit manager.
        Works for a single unit or multiple selected units.
        """
        total_synced_units = 0
        total_synced_employees = 0
        for unit in self:
            if not unit.manager_id:
                continue
            unit._sync_unit_employees_hierarchy()
            emp_count = self.env['hr.employee'].search_count([
                ('default_operating_unit_id', '=', unit.id),
                ('id', '!=', unit.manager_id.id),
            ])
            total_synced_units += 1
            total_synced_employees += emp_count

        if len(self) == 1:
            unit = self[0]
            if not unit.manager_id:
                raise UserError(_("Please select a Manager for this Operating Unit before synchronizing."))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Hierarchy Synchronized'),
                    'message': _('%d employee(s) in "%s" now report to Manager %s.') % (
                        total_synced_employees, unit.name, unit.manager_id.name
                    ),
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Hierarchy Synchronized'),
                    'message': _('Synchronized %d employee(s) across %d operating unit(s).') % (
                        total_synced_employees, total_synced_units
                    ),
                    'sticky': False,
                    'type': 'success',
                }
            }

    def action_auto_detect_and_sync_branch_managers(self):
        """Detect and set manager for branches where manager_id is currently empty,
        based on active employees in that branch holding a Branch Manager job position.
        """
        updated_count = 0
        target_units = self if self else self.search([
            ('work_unit_type', '=', 'branch'),
            ('manager_id', '=', False),
            ('active', '=', True)
        ])
        for branch in target_units:
            if branch.manager_id:
                continue
            # Search active employee with 'Branch Manager' in job title in this unit
            mgr_emp = self.env['hr.employee'].search([
                ('default_operating_unit_id', '=', branch.id),
                ('active', '=', True),
                '|',
                ('job_id.name', 'ilike', 'branch manager'),
                ('job_position.name', 'ilike', 'branch manager'),
            ])
            if len(mgr_emp) == 1:
                branch.write({'manager_id': mgr_emp.id})
                updated_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Branch Managers Detected'),
                'message': _('Successfully detected and synchronized managers for %d branch(es).') % updated_count,
                'sticky': False,
                'type': 'success',
            }
        }

    def unlink(self):
        raise UserError(_(
            "Operating Units cannot be deleted. Please archive them instead."
        ))


    hardship_allowance = fields.Float(
        string='Hardship Allowance',
        default=0.00,
        digits=(16, 2),
    )
    tax_exempt = fields.Float(
        string="Tax Exemption",
        digits=(16, 4),
        default=0.0,
        help="Stored as a fraction (0.04 = 4%). Enter the percentage in the form, e.g. 4.",
    )

    @api.constrains('tax_exempt')
    def _check_tax_exempt(self):
        for rec in self:
            if rec.tax_exempt < 0 or rec.tax_exempt > 1:
                raise UserError(_('Tax Exemption must be between 0% and 100%.'))

    # ── Python Constraints ────────────────────────────────────────────────
    @api.constrains('sol_id')
    def _check_sol_id_positive(self):
        for rec in self:
            if rec.sol_id <= 0:
                raise UserError(_('Sol ID must be a positive number.'))


    @api.constrains('hardship_allowance')
    def _check_hardship_allowance(self):
        for rec in self:
            if rec.hardship_allowance < 0:
                raise UserError(
                    _('Hardship Allowance cannot be negative.')
                )

    # ── Button Actions ────────────────────────────────────────────────────
    def action_recompute_establishment(self):
        """Recomputes baseline, active, total, and vacant counts for all job positions in this unit."""
        self.ensure_one()
        if self.job_position_ids:
            self.job_position_ids._compute_baseline_count()
            self.job_position_ids._compute_active_employee_count()
            self.job_position_ids._compute_total_headcount()
            self.job_position_ids._compute_vacant_position_count()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Establishment Refreshed'),
                'message': _('Job positions and active employee counts for "%s" have been recalculated.') % self.name,
                'sticky': False,
                'type': 'success',
            }
        }

    def action_save_operating_unit(self):
        """Triggered by the Save button — shows success toast then returns to list."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Operating Unit "%s" has been saved successfully.') % self.name,
                'sticky': False,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'operating.unit',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            },
        }

    def action_archive_operating_unit(self):
        """Toggle active — Archive if active, Unarchive if archived."""
        self.ensure_one()
        name = self.name
        new_state = not self.active
        self.write({'active': new_state})
        title = _('Unarchived') if new_state else _('Archived')
        msg = _('Operating Unit "%s" has been %s.') % (name, title.lower())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'sticky': False,
                'type': 'warning' if not new_state else 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'operating.unit',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            },
        }
