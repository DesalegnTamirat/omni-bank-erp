# models/operating_unit_job_position.py
from odoo.exceptions import UserError
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OperatingUnitJobPosition(models.Model):
    _name = 'operating.unit.job.position'
    _description = 'Job Position Planning per Operating Unit'
    _rec_name = 'job_position_id'

    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'unique_job_position_per_operating_unit',
            'unique(operating_unit_id, job_position_id)',
            'This Job Position has already been added for this Work Unit.',
        ),
    ]

    operating_unit_id = fields.Many2one(
        comodel_name='operating.unit',
        string='Work Unit',
        required=True,
        ondelete='cascade',
    )
    job_position_id = fields.Many2one(
        # comodel_name='employee.job',
        comodel_name='hr.job',
        string='Job Position',
        required=True,
    )

    # Manually entered
    approved_plan_count = fields.Integer(
        string='Approved Plan Count',
        default=0,
    )

    # Computed from hr.employee — live count, not stored
    active_employee_count = fields.Integer(
        string='Active Employee Count',
        compute='_compute_active_employee_count',
    )

    vacant_position_count = fields.Integer(
        string='Vacant Position Count',
        compute='_compute_vacant_position_count',
        store=True,
    )

    # Stubs — always 0 for now, wired up later
    lateral_count = fields.Integer(
        string='Lateral Count',
        compute='_compute_stub_zero',
    )
    promotion_count = fields.Integer(
        string='Promotion Count',
        compute='_compute_stub_zero',
    )
    replacement_count = fields.Integer(
        string='Replacement Count',
        compute='_compute_stub_zero',
    )

    # @api.depends('operating_unit_id', 'job_position_id')
    # def _compute_active_employee_count(self):
    #     Employee = self.env['hr.employee']
    #     for rec in self:
    #         if rec.operating_unit_id and rec.job_position_id:
    #             rec.active_employee_count = Employee.search_count([
    #                 ('active', '=', True),
    #                 ('employee_job_id', '=', rec.job_position_id.id),
    #                 ('operating_unit_ids', 'in', rec.operating_unit_id.id),
    #             ])
    #         else:
    #             rec.active_employee_count = 0
    @api.depends('operating_unit_id', 'job_position_id')
    def _compute_active_employee_count(self):
        Employee = self.env['hr.employee']
        for rec in self:
            if rec.operating_unit_id and rec.job_position_id:
                rec.active_employee_count = Employee.search_count([
                    ('active', '=', True),
                    ('job_position', '=', rec.job_position_id.id),  # was employee_job_id
                    ('operating_unit_ids', 'in', rec.operating_unit_id.id),
                ])
            else:
                rec.active_employee_count = 0

    @api.depends('approved_plan_count', 'active_employee_count')
    def _compute_vacant_position_count(self):
        for rec in self:
            rec.vacant_position_count = (
                    rec.approved_plan_count - rec.active_employee_count
            )

    def _compute_stub_zero(self):
        for rec in self:
            rec.lateral_count = 0
            rec.promotion_count = 0
            rec.replacement_count = 0

    @api.constrains('operating_unit_id', 'job_position_id')
    def _check_unique_job_position(self):
        for rec in self:
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('operating_unit_id', '=', rec.operating_unit_id.id),
                ('job_position_id', '=', rec.job_position_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Job Position '%s' is already added for Work Unit '%s'."
                ) % (rec.job_position_id.display_name, rec.operating_unit_id.display_name))

    def unlink(self):
        raise UserError(_(
            "Job Position lines cannot be deleted. Please archive them instead."
        ))

class HrEmployeeJobPositionSync(models.Model):
        """Keeps operating.unit.job.position counts in sync whenever an
        employee's job or operating unit assignment changes. Kept in this
        file (rather than hr_employee.py) since the sync logic belongs
        conceptually to the job-position-planning feature, not to the
        core employee model.
        """
        _inherit = 'hr.employee'

        def write(self, vals):
            if self.env.context.get('in_sync_job_position_counts'):
                return super().write(vals)
            res = super().write(vals)
            if 'job_position' in vals or 'operating_unit_ids' in vals:
                self.with_context(in_sync_job_position_counts=True)._sync_job_position_counts()
            return res

        @api.model_create_multi
        def create(self, vals_list):
            if self.env.context.get('in_sync_job_position_counts'):
                return super().create(vals_list)
            records = super().create(vals_list)
            records.with_context(in_sync_job_position_counts=True)._sync_job_position_counts()
            return records

        def _sync_job_position_counts(self):
            OUJobPosition = self.env['operating.unit.job.position']
            job_ids = self.mapped('job_position').ids
            ou_ids = self.mapped('operating_unit_ids').ids
            if job_ids and ou_ids:
                lines = OUJobPosition.search([
                    ('job_position_id', 'in', job_ids),
                    ('operating_unit_id', 'in', ou_ids),
                ])
                lines._compute_active_employee_count()