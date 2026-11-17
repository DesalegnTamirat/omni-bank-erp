from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta


class HrEmployeeTransferHistory(models.Model):
    _name = 'hr.employee.transfer.history'
    _description = 'Employee Transfer History'
    _order = 'start_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today,
        required=True,
    )
    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
    )
    end_date = fields.Date(
        string='End Date',
    )
    duration = fields.Char(
        string='Duration', compute='_compute_duration', store=True,
        help="Difference between end date and start date.",
    )
    is_current = fields.Boolean(
        string='Current Transfer', compute='_compute_is_current', store=True,
        help="True when this row has no end date.",
    )
    transfer_reason = fields.Char(string='Transfer Reason')
    reason_for_movement = fields.Selection([
        ('promotion', 'Promotion'),
        ('acting_assignment', 'Acting Assignment'),
        ('acting_termination', 'Acting Termination'),
        ('assignment', 'Assignment'),
        ('lateral_transfer', 'Lateral Transfer'),
        ('transfer', 'Transfer'),
        ('placement', 'Placement'),
        ('job_reclassification', 'Job Reclassification'),
        ('placement_and_adjustment', 'Placement and Adjustment'),
        ('re_assignment', 'Re-Assignment'),
        ('alteration_of_job_title', 'Alteration of Job Title'),
        ('appointment', 'Appointment'),
        ('job_rotation', 'Job Rotation'),
        ('temporary_assignment', 'Temporary Assignment'),
    ], string='Reason for Movement', index=True)
    transfer_initiation_type = fields.Selection([
        ('self_initiated', 'Self-Initiated'),
        ('bank_initiated', 'Bank-Initiated'),
    ], string='Transfer Initiation Type', default='bank_initiated', index=True)

    # From
    from_operating_unit_id = fields.Many2one('operating.unit', string='From Operating Unit')
    from_department_id = fields.Many2one('hr.department', string='From Department')
    from_job_id = fields.Many2one('hr.job', string='From Position')
    from_grade_id = fields.Many2one('employee.grade', string='From Grade')

    # To
    to_operating_unit_id = fields.Many2one('operating.unit', string='To Operating Unit')
    to_department_id = fields.Many2one('hr.department', string='To Department')
    to_job_id = fields.Many2one('hr.job', string='To Position')
    to_grade_id = fields.Many2one('employee.grade', string='To Grade')

    @api.depends('end_date')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.end_date

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            self.from_operating_unit_id = emp.default_operating_unit_id
            self.from_department_id = emp.department_id
            self.from_job_id = emp.job_position or emp.job_id
            self.from_grade_id = emp.job_grade
            # Transfers are strictly within the SAME job position and SAME grade:
            self.to_job_id = self.from_job_id
            self.to_grade_id = self.from_grade_id
            self.to_department_id = self.from_department_id
            self.reason_for_movement = 'transfer'
            self.transfer_reason = 'Transfer'
            if not self.start_date:
                self.start_date = fields.Date.context_today(self)
            if not self.date:
                self.date = fields.Date.context_today(self)

    @api.onchange('to_job_id')
    def _onchange_to_job_id(self):
        if self.to_job_id:
            if self.to_job_id.department_id and not self.to_department_id:
                self.to_department_id = self.to_job_id.department_id
            if hasattr(self.to_job_id, 'grade') and self.to_job_id.grade and not self.to_grade_id:
                self.to_grade_id = self.to_job_id.grade
            if self.from_job_id and self.to_job_id != self.from_job_id:
                return {
                    'warning': {
                        'title': _("Invalid Position for Transfer"),
                        'message': _(
                            "Transfer History requires the same Job Position (%s). "
                            "If the employee is changing positions (Lateral Transfer), please record it under Job History."
                        ) % (self.from_job_id.name or '')
                    }
                }

    @api.onchange('reason_for_movement')
    def _onchange_reason_for_movement(self):
        if self.reason_for_movement and not self.transfer_reason:
            self.transfer_reason = dict(self._fields['reason_for_movement'].selection).get(self.reason_for_movement, 'Transfer')

    def _check_hr_management_rights(self):
        user = self.env.user
        is_hr = (
            user.has_group('hr.group_hr_user')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )
        if not is_hr and not self.env.su:
            raise UserError(_("Only HR Officers and Administrators can create, edit, or delete Transfer History records."))

    def unlink(self):
        self._check_hr_management_rights()
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        self._check_hr_management_rights()
        for vals in vals_list:
            if not vals.get('reason_for_movement') and vals.get('transfer_reason'):
                mapped = self.env['hr.job.history'].map_reason_for_change_to_movement(vals['transfer_reason'])
                if mapped:
                    vals['reason_for_movement'] = mapped
        records = super().create(vals_list)
        # Sync to hr.job.history if not called from sync
        if not self.env.context.get('skip_job_history_sync'):
            for rec in records:
                start_d = rec.start_date or rec.date or fields.Date.context_today(rec)
                existing = self.env['hr.job.history'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('job_history_start_date', '=', start_d),
                    ('reason_for_movement', 'in', ['transfer', 'lateral_transfer']),
                ], limit=1)
                if not existing:
                    self.env['hr.job.history'].sudo().with_context(skip_transfer_history_sync=True).create({
                        'employee_id': rec.employee_id.id,
                        'job_history_start_date': start_d,
                        'job_history_end_date': rec.end_date,
                        'reason_for_change': 'transfer',
                        'reason_for_movement': rec.reason_for_movement or 'transfer',
                        'transfer_initiation_type': rec.transfer_initiation_type or 'bank_initiated',
                        'from_operating_unit_id': rec.from_operating_unit_id.id if rec.from_operating_unit_id else False,
                        'to_operating_unit_id': rec.to_operating_unit_id.id if rec.to_operating_unit_id else False,
                        'from_department_id': rec.from_department_id.id if rec.from_department_id else False,
                        'to_department_id': rec.to_department_id.id if rec.to_department_id else False,
                        'from_job_id': rec.from_job_id.id if rec.from_job_id else False,
                        'to_job_id': rec.to_job_id.id if rec.to_job_id else False,
                        'from_grade_id': rec.from_grade_id.id if rec.from_grade_id else False,
                        'to_grade_id': rec.to_grade_id.id if rec.to_grade_id else False,
                        'position': rec.to_job_id.name if rec.to_job_id else False,
                    })
        return records

    def write(self, vals):
        self._check_hr_management_rights()
        if 'transfer_reason' in vals and not vals.get('reason_for_movement'):
            mapped = self.env['hr.job.history'].map_reason_for_change_to_movement(vals['transfer_reason'])
            if mapped:
                vals['reason_for_movement'] = mapped
        res = super().write(vals)
        if not self.env.context.get('skip_job_history_sync'):
            for rec in self:
                start_d = rec.start_date or rec.date or fields.Date.context_today(rec)
                jh = self.env['hr.job.history'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('job_history_start_date', '=', start_d),
                    ('reason_for_movement', '=', 'transfer'),
                ], limit=1)
                if jh:
                    jh.sudo().with_context(skip_transfer_history_sync=True).write({
                        'job_history_end_date': rec.end_date,
                        'from_operating_unit_id': rec.from_operating_unit_id.id if rec.from_operating_unit_id else False,
                        'to_operating_unit_id': rec.to_operating_unit_id.id if rec.to_operating_unit_id else False,
                        'from_department_id': rec.from_department_id.id if rec.from_department_id else False,
                        'to_department_id': rec.to_department_id.id if rec.to_department_id else False,
                        'from_job_id': rec.from_job_id.id if rec.from_job_id else False,
                        'to_job_id': rec.to_job_id.id if rec.to_job_id else False,
                        'from_grade_id': rec.from_grade_id.id if rec.from_grade_id else False,
                        'to_grade_id': rec.to_grade_id.id if rec.to_grade_id else False,
                    })
        return res

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.start_date:
                rec.duration = ''
                continue
            start = rec.start_date
            end = rec.end_date or today
            if end < start:
                rec.duration = '0 Days'
                continue
            diff = relativedelta(end, start)
            parts = []
            if diff.years > 0:
                parts.append(f"{diff.years} Year{'s' if diff.years > 1 else ''}")
            if diff.months > 0:
                parts.append(f"{diff.months} Month{'s' if diff.months > 1 else ''}")
            if diff.days > 0 or not parts:
                parts.append(f"{diff.days} Day{'s' if diff.days != 1 else ''}")
            rec.duration = ", ".join(parts)

    @api.constrains('start_date', 'end_date')
    def _check_start_end_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                if rec.start_date > rec.end_date:
                    raise ValidationError(
                        _("Start Date (%s) cannot be greater than End Date (%s). "
                          "End Date cannot be below Start Date.")
                        % (rec.start_date, rec.end_date)
                    )

    @api.onchange('start_date', 'end_date')
    def _onchange_start_end_dates(self):
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                return {
                    'warning': {
                        'title': _("Invalid Date Range"),
                        'message': _("Start Date cannot be greater than End Date, and End Date cannot be below Start Date."),
                    }
                }

    @api.constrains('from_job_id', 'to_job_id', 'from_grade_id', 'to_grade_id', 'from_operating_unit_id', 'to_operating_unit_id', 'reason_for_movement')
    def _check_transfer_criteria(self):
        for rec in self:
            if rec.reason_for_movement and rec.reason_for_movement not in ('transfer',):
                raise ValidationError(
                    _("Transfer History is strictly for transfers with the same position and grade in a different location. "
                      "Movement reason '%s' must be recorded under Job History.")
                    % dict(rec._fields['reason_for_movement'].selection).get(rec.reason_for_movement, rec.reason_for_movement)
                )
            if rec.from_job_id and rec.to_job_id and rec.from_job_id.id != rec.to_job_id.id:
                raise ValidationError(
                    _("Transfer History is strictly for transfers with the same position and grade in a different location. "
                      "Position changed from '%s' to '%s' (Lateral Transfer), which must be recorded under Job History.")
                    % (rec.from_job_id.name, rec.to_job_id.name)
                )
            if rec.from_grade_id and rec.to_grade_id and rec.from_grade_id.id != rec.to_grade_id.id:
                raise ValidationError(
                    _("Transfer History requires matching grades (%s -> %s). Grade changes (Promotions/Demotions) must be recorded under Job History.")
                    % (rec.from_grade_id.grade_name or rec.from_grade_id.name, rec.to_grade_id.grade_name or rec.to_grade_id.name)
                )
            if rec.from_operating_unit_id and rec.to_operating_unit_id and rec.from_operating_unit_id.id == rec.to_operating_unit_id.id:
                raise ValidationError(
                    _("Transfer History requires a change in Operating Unit (Location). "
                      "From Operating Unit and To Operating Unit cannot be the same.")
                )
