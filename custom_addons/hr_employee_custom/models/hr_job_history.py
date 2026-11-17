# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


# Mapping dictionary consolidated from 'Reason fo change  types.xlsx'
REASON_CHANGE_TO_MOVEMENT_MAPPING = {
    # Acting Assignment
    'acing assignment': 'acting_assignment',
    'actig assignment': 'acting_assignment',
    'acting': 'acting_assignment',
    'acting  assignment': 'acting_assignment',
    'acting assginment': 'acting_assignment',
    'acting assigment': 'acting_assignment',
    'acting assignement': 'acting_assignment',
    'acting assignemnt': 'acting_assignment',
    'acting assignm,ent': 'acting_assignment',
    'acting assignment': 'acting_assignment',
    'acting assignmnet': 'acting_assignment',
    'acting assignmrent': 'acting_assignment',
    'acting position title change': 'acting_assignment',
    'acting start': 'acting_assignment',
    'actng assignment': 'acting_assignment',
    'acting_role': 'acting_assignment',
    # Acting Termination
    'acting atermination': 'acting_termination',
    'acting end': 'acting_termination',
    'acting termibnation': 'acting_termination',
    'acting termination': 'acting_termination',
    'acting termination & assignment': 'acting_termination',
    'acting terminaton': 'acting_termination',
    'revocation of acting': 'acting_termination',
    'termination acting assignment': 'acting_termination',
    'termination of acting assignment': 'acting_termination',
    'termination of acting termination': 'acting_termination',
    # Placement and Adjustment
    'adjustment': 'placement_and_adjustment',
    # Alteration of Job Title
    'alteraion of job title': 'alteration_of_job_title',
    'alteration of job naming': 'alteration_of_job_title',
    'alteration of job titel': 'alteration_of_job_title',
    'alteration of job title': 'alteration_of_job_title',
    'alteration of job title change': 'alteration_of_job_title',
    'alteration of job title naming': 'alteration_of_job_title',
    'alteration of job tittle naming': 'alteration_of_job_title',
    'alternation job title': 'alteration_of_job_title',
    'alternation job title naming': 'alteration_of_job_title',
    'alternation of job title naming': 'alteration_of_job_title',
    'change job postion': 'alteration_of_job_title',
    'change of job position': 'alteration_of_job_title',
    'job name change': 'alteration_of_job_title',
    'job name changed': 'alteration_of_job_title',
    'job position change': 'alteration_of_job_title',
    'job title alteration': 'alteration_of_job_title',
    'job title chagne': 'alteration_of_job_title',
    'job title change': 'alteration_of_job_title',
    'job title change & transfer': 'alteration_of_job_title',
    'job title changed': 'alteration_of_job_title',
    'job title chnage': 'alteration_of_job_title',
    'job title chnge': 'alteration_of_job_title',
    'job title name change': 'alteration_of_job_title',
    'job title naming': 'alteration_of_job_title',
    'job titlechange': 'alteration_of_job_title',
    'job tittle change': 'alteration_of_job_title',
    'revised position': 'alteration_of_job_title',
    'tile change': 'alteration_of_job_title',
    'title chagne': 'alteration_of_job_title',
    'title chan': 'alteration_of_job_title',
    'title chaneg': 'alteration_of_job_title',
    'title change': 'alteration_of_job_title',
    'title chnage': 'alteration_of_job_title',
    'titlechange': 'alteration_of_job_title',
    'tktle change': 'alteration_of_job_title',
    # Appointment
    'appointment': 'appointment',
    # Assignment
    'assginment': 'assignment',
    'assigned': 'assignment',
    'assignment': 'assignment',
    'assignmnet': 'assignment',
    # Placement
    'demotion': 'placement',
    'placemenet': 'placement',
    'placement': 'placement',
    'placment': 'placement',
    'placement & adjustment': 'placement',
    'placement and adjustment': 'placement',
    'discipline': 'placement',
    # Job Reclassification
    'job classification': 'job_reclassification',
    'job grading': 'job_reclassification',
    'job re-classification': 'job_reclassification',
    'job re-classified': 'job_reclassification',
    'job reclasfication': 'job_reclassification',
    'job reclassification': 'job_reclassification',
    'job reclassified': 'job_reclassification',
    'job title reclassified': 'job_reclassification',
    'new job grading': 'job_reclassification',
    'reclassification': 'job_reclassification',
    'reclassification of position': 'job_reclassification',
    'reclassified': 'job_reclassification',
    'renaming and job reclassification': 'job_reclassification',
    # Job Rotation
    'job rotation': 'job_rotation',
    # Lateral Transfer
    'latera transfer': 'lateral_transfer',
    'lateral transfer': 'lateral_transfer',
    'lateral transfer transfer': 'lateral_transfer',
    'laterally transferred': 'lateral_transfer',
    'laterar transfer': 'lateral_transfer',
    'laterla transfer': 'lateral_transfer',
    'latteral transfer': 'lateral_transfer',
    # Promotion
    'pomotion': 'promotion',
    'position': 'promotion',
    'promoted': 'promotion',
    'promotio': 'promotion',
    'promotion': 'promotion',
    'promotiom': 'promotion',
    'promoton': 'promotion',
    'promtion': 'promotion',
    'prpmotion': 'promotion',
    'romotion': 'promotion',
    # Re-Assignment
    're assignment': 're_assignment',
    're-assignment': 're_assignment',
    # Temporary Assignment
    'temporarily assignment': 'temporary_assignment',
    'temporary assignment': 'temporary_assignment',
    # Transfer
    'transfer': 'transfer',
}

class HrJobHistory(models.Model):
    _name = 'hr.job.history'
    _description = 'Employee Job History'
    _order = 'job_history_start_date desc, id desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee Name', required=True,
        ondelete='cascade', index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    old_wage = fields.Monetary(string='Old Wage', currency_field='currency_id', readonly=True)
    new_wage = fields.Monetary(string='New Wage', currency_field='currency_id', readonly=True)
    disturbance_payment = fields.Monetary(
        string='Disturbance Payment',
        currency_field='currency_id',
        compute='_compute_disturbance_payment',
        store=True,
        readonly=True,
        help="Disturbance payment for Bank-Initiated transfers: 15% of basic salary for outline branch, 10% for city branch.",
    )

    from_operating_unit_id = fields.Many2one('operating.unit', string='From Operating Unit')
    to_operating_unit_id = fields.Many2one('operating.unit', string='To Operating Unit')
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit',
        related='to_operating_unit_id', store=True, readonly=False,
    )

    from_department_id = fields.Many2one('hr.department', string='From Department')
    to_department_id = fields.Many2one('hr.department', string='To Department')
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='to_department_id', store=True, readonly=False,
    )

    from_grade_id = fields.Many2one('employee.grade', string='From Grade')
    to_grade_id = fields.Many2one('employee.grade', string='To Grade')
    grade_id = fields.Many2one(
        'employee.grade', string='Grade',
        related='to_grade_id', store=True, readonly=False,
    )

    from_job_id = fields.Many2one('hr.job', string='From Position')
    to_job_id = fields.Many2one('hr.job', string='To Position')
    job_id = fields.Many2one(
        'hr.job', string='Job Name',
        related='to_job_id', store=True, readonly=False,
    )

    position = fields.Char(string='Position')
    job_history_start_date = fields.Date(string='Job History Start Date')
    job_history_end_date = fields.Date(string='Job History End Date')
    duration = fields.Char(
        string='Duration', compute='_compute_duration', store=True,
        help="Difference between end date and start date."
    )
    reason_for_change = fields.Selection([
        ('promotion', 'Promotion'),
        ('transfer', 'Transfer'),
        ('lateral_transfer', 'Lateral Transfer'),
        ('demotion', 'Demotion'),
        ('acting_role', 'Acting Role'),
        ('recruitment', 'Recruitment / New Hire'),
        ('resignation', 'Resignation'),
        ('termination', 'Termination'),
        ('other', 'Other'),
    ], string='Reason for Change', default='other')
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
    ], string='Transfer Initiation Type', default='self_initiated', index=True)
    is_current = fields.Boolean(
        string='Current Position', compute='_compute_is_current', store=True,
        help="True when this row has no end date, i.e. it is the employee's active position.",
    )

    @api.depends('transfer_initiation_type', 'to_operating_unit_id', 'new_wage', 'old_wage', 'employee_id')
    def _compute_disturbance_payment(self):
        for rec in self:
            if rec.transfer_initiation_type != 'bank_initiated':
                rec.disturbance_payment = 0.0
                continue

            wage = rec.new_wage or rec.old_wage or 0.0
            if not wage and rec.employee_id:
                emp = rec.employee_id
                if hasattr(emp, 'contract_id') and emp.contract_id and getattr(emp.contract_id, 'wage', False):
                    wage = float(emp.contract_id.wage or 0.0)
                elif hasattr(emp, 'wage') and emp.wage:
                    wage = float(emp.wage or 0.0)
                elif hasattr(emp, 'current_wage') and emp.current_wage:
                    wage = float(emp.current_wage or 0.0)

            dest = rec.to_operating_unit_id
            rate = 0.0
            if dest:
                loc_type = (dest.location_type or '').strip().lower()
                dist = (dest.district or '').strip().lower()
                reg = (dest.region or '').strip().lower()
                name = (dest.name or '').strip().lower()

                if loc_type == 'outline' or 'outline' in dist or 'outlying' in dist or 'outline' in name or 'outlying' in name:
                    rate = 0.15
                elif loc_type == 'city_branch' or 'city' in dist or 'addis' in dist or 'city' in name or 'addis' in reg:
                    rate = 0.10
                else:
                    if dist and any(x in dist for x in ('bahir dar', 'adama', 'hawassa', 'jimma', 'mekelle', 'dessie', 'dire dawa')):
                        rate = 0.15
                    else:
                        rate = 0.10

            rec.disturbance_payment = round(wage * rate, 2)

    @api.onchange('transfer_initiation_type', 'to_operating_unit_id', 'new_wage', 'old_wage', 'employee_id')
    def _onchange_disturbance_payment(self):
        self._compute_disturbance_payment()

    @api.depends('job_history_end_date')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.job_history_end_date

    @api.model
    def map_reason_for_change_to_movement(self, reason_str):
        """Maps freeform or historical reason_for_change strings to standard reason_for_movement keys."""
        if not reason_str:
            return False
        clean = str(reason_str).strip().lower()
        return REASON_CHANGE_TO_MOVEMENT_MAPPING.get(clean, False)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            self.from_operating_unit_id = emp.default_operating_unit_id
            self.from_department_id = emp.department_id
            self.from_job_id = emp.job_position or emp.job_id
            self.from_grade_id = emp.job_grade
            if hasattr(emp, 'contract_id') and emp.contract_id:
                self.old_wage = emp.contract_id.wage
            elif hasattr(emp, 'current_wage'):
                self.old_wage = emp.current_wage
            if not self.job_history_start_date:
                self.job_history_start_date = fields.Date.context_today(self)

    @api.onchange('to_job_id')
    def _onchange_to_job_id(self):
        if self.to_job_id:
            if self.to_job_id.department_id and not self.to_department_id:
                self.to_department_id = self.to_job_id.department_id
            if hasattr(self.to_job_id, 'grade') and self.to_job_id.grade and not self.to_grade_id:
                self.to_grade_id = self.to_job_id.grade
            if not self.position:
                self.position = self.to_job_id.name

    @api.onchange('to_grade_id', 'reason_for_movement', 'reason_for_change', 'old_wage')
    def _onchange_to_grade_id_calculate_wage(self):
        is_promo = (self.reason_for_movement == 'promotion' or self.reason_for_change == 'promotion')
        if is_promo:
            if self.to_grade_id and self.old_wage:
                self.new_wage = self._calculate_grade_step_salary(self.to_grade_id, self.old_wage)
            elif self.to_grade_id and getattr(self.to_grade_id, 'base_salary', False):
                self.new_wage = self.to_grade_id.base_salary
            else:
                self.new_wage = self.old_wage or 0.0
        elif self.reason_for_movement in ('transfer', 'lateral_transfer') or self.reason_for_change in ('transfer', 'lateral_transfer'):
            self.new_wage = self.old_wage or 0.0
        else:
            self.new_wage = self.old_wage or 0.0

    @api.onchange('reason_for_movement')
    def _onchange_reason_for_movement(self):
        if self.reason_for_movement:
            movement_to_change = {
                'promotion': 'promotion',
                'acting_assignment': 'acting_role',
                'acting_termination': 'acting_role',
                'transfer': 'transfer',
                'lateral_transfer': 'transfer',
                'assignment': 'other',
                'demotion': 'demotion',
                'recruitment': 'recruitment',
            }
            if not self.reason_for_change or self.reason_for_change == 'other':
                self.reason_for_change = movement_to_change.get(self.reason_for_movement, 'other')

    @api.onchange('reason_for_change')
    def _onchange_reason_for_change(self):
        if self.reason_for_change and not self.reason_for_movement:
            mapped = self.map_reason_for_change_to_movement(self.reason_for_change)
            if mapped:
                self.reason_for_movement = mapped

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reason_for_movement') and vals.get('reason_for_change'):
                mapped = self.map_reason_for_change_to_movement(vals['reason_for_change'])
                if mapped:
                    vals['reason_for_movement'] = mapped
        records = super().create(vals_list)
        # Sync transfer records to hr.employee.transfer.history:
        # STRICT RULE: Transfer History ONLY holds transfers with SAME position, SAME grade, and DIFFERENT Operating Unit.
        # Lateral transfers (position changes) and promotions/demotions MUST NOT be synced to Transfer History.
        if not self.env.context.get('skip_transfer_history_sync'):
            for rec in records:
                is_pure_transfer = (
                    rec.reason_for_movement == 'transfer'
                    and rec.from_job_id == rec.to_job_id
                    and rec.from_grade_id == rec.to_grade_id
                    and rec.from_operating_unit_id
                    and rec.to_operating_unit_id
                    and rec.from_operating_unit_id != rec.to_operating_unit_id
                )
                if is_pure_transfer:
                    start_d = rec.job_history_start_date or fields.Date.context_today(rec)
                    existing = self.env['hr.employee.transfer.history'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('start_date', '=', start_d),
                    ], limit=1)
                    if not existing:
                        self.env['hr.employee.transfer.history'].with_context(skip_job_history_sync=True).create({
                            'employee_id': rec.employee_id.id,
                            'date': start_d,
                            'start_date': start_d,
                            'end_date': rec.job_history_end_date,
                            'transfer_reason': 'Transfer',
                            'reason_for_movement': 'transfer',
                            'transfer_initiation_type': rec.transfer_initiation_type or 'bank_initiated',
                            'from_operating_unit_id': rec.from_operating_unit_id.id if rec.from_operating_unit_id else False,
                            'to_operating_unit_id': rec.to_operating_unit_id.id if rec.to_operating_unit_id else False,
                            'from_department_id': rec.from_department_id.id if rec.from_department_id else False,
                            'to_department_id': rec.to_department_id.id if rec.to_department_id else False,
                            'from_job_id': rec.from_job_id.id if rec.from_job_id else False,
                            'to_job_id': rec.to_job_id.id if rec.to_job_id else False,
                            'from_grade_id': rec.from_grade_id.id if rec.from_grade_id else False,
                            'to_grade_id': rec.to_grade_id.id if rec.to_grade_id else False,
                        })
        return records

    def write(self, vals):
        if 'reason_for_change' in vals and not vals.get('reason_for_movement'):
            mapped = self.map_reason_for_change_to_movement(vals['reason_for_change'])
            if mapped:
                vals['reason_for_movement'] = mapped
        res = super().write(vals)
        if not self.env.context.get('skip_transfer_history_sync'):
            for rec in self:
                is_pure_transfer = (
                    rec.reason_for_movement == 'transfer'
                    and rec.from_job_id == rec.to_job_id
                    and rec.from_grade_id == rec.to_grade_id
                    and rec.from_operating_unit_id
                    and rec.to_operating_unit_id
                    and rec.from_operating_unit_id != rec.to_operating_unit_id
                )
                if is_pure_transfer:
                    start_d = rec.job_history_start_date or fields.Date.context_today(rec)
                    trf = self.env['hr.employee.transfer.history'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('start_date', '=', start_d),
                    ], limit=1)
                    if trf:
                        trf.with_context(skip_job_history_sync=True).write({
                            'end_date': rec.job_history_end_date,
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

    @api.depends('job_history_start_date', 'job_history_end_date')
    def _compute_duration(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.job_history_start_date:
                rec.duration = ''
                continue
            start = rec.job_history_start_date
            end = rec.job_history_end_date or today
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

    @api.constrains('job_history_start_date', 'job_history_end_date')
    def _check_start_end_dates(self):
        for rec in self:
            if rec.job_history_start_date and rec.job_history_end_date:
                if rec.job_history_start_date > rec.job_history_end_date:
                    raise ValidationError(
                        _("Start Date (%s) cannot be greater than End Date (%s). "
                          "End Date cannot be below Start Date.")
                        % (rec.job_history_start_date, rec.job_history_end_date)
                    )

    @api.onchange('job_history_start_date', 'job_history_end_date')
    def _onchange_start_end_dates(self):
        if self.job_history_start_date and self.job_history_end_date:
            if self.job_history_start_date > self.job_history_end_date:
                return {
                    'warning': {
                        'title': _("Invalid Date Range"),
                        'message': _("Start Date cannot be greater than End Date, and End Date cannot be below Start Date."),
                    }
                }



class HrEmployeeJobHistory(models.Model):
    """Automatically maintains hr.job.history whenever an employee's
    position, grade, department, or operating unit changes — regardless
    of which flow triggers the change (promotion, demotion, transfer,
    acting role, recruitment, or a direct edit on the employee form).
    """
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'hr.job.history', 'employee_id',
        string='Job History',
        help="Chronological list of job positions — used by the Experience Letter report.",
    )
    transfer_history_ids = fields.One2many(
        'hr.employee.transfer.history', 'employee_id',
        string='Transfer History',
        help="Chronological list of employee lateral transfers and branch reassignments.",
    )

    def action_view_job_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_job_history')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_transfer_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_employee_transfer_history')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_contract_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_employee_contract_history')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_training_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_training_history')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_view_reinstated_history(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_reinstated_history')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    _JOB_HISTORY_TRACKED_FIELDS = (
        'job_position',
        'job_id',
        'job_grade',
        'default_operating_unit_id',
        'department_id',
    )

    def _get_job_id(self, emp, vals=None):
        """Extracts job position ID from employee record or incoming write vals."""
        if vals:
            if 'job_id' in vals and vals['job_id']:
                return vals['job_id']
            if 'job_position' in vals and vals['job_position']:
                return vals['job_position']
        if hasattr(emp, 'job_id') and emp.job_id:
            return emp.job_id.id
        if hasattr(emp, 'job_position') and emp.job_position:
            return emp.job_position.id
        return False

    def _get_employee_current_wage(self, emp):
        """Finds the current wage of the employee from contract (hr.version) or grade structure."""
        contracts = self.env['hr.version'].search([
            ('employee_id', '=', emp.id),
            ('state', 'in', ['open', 'probation', 'draft'])
        ], order='id desc', limit=1)

        if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
            contracts = emp.contract_id

        if contracts:
            if getattr(contracts, 'wage', 0.0):
                return contracts.wage
            if getattr(contracts, 'base_salary', 0.0):
                return contracts.base_salary

        if emp.job_grade:
            return self._calculate_grade_step_salary(emp.job_grade, 0.0)

        return 0.0

    def write(self, vals):
        if self.env.context.get('in_job_history_logging'):
            return super().write(vals)

        # ── Auto-sync hierarchy ───────────────────────────────────────────
        # Direction 1: work unit changed → update manager hierarchy fields.
        # Direction 2: manager changed (no explicit work unit) → update work unit.
        # This runs before the job-history snapshot so the "before" state is
        # captured correctly from the DB, and the "after" state reflects the
        # fully synced record.
        if not self.env.context.get('_hierarchy_sync_in_progress'):
            ctx = dict(self.env.context, _hierarchy_sync_in_progress=True)
            env = self.env(context=ctx)
            OperatingUnit = env['operating.unit']

            new_ou_id = vals.get('default_operating_unit_id')
            new_parent_id = vals.get('parent_id')

            if new_ou_id:
                # Direction 1: resolve manager of the new operating unit
                ou = OperatingUnit.browse(new_ou_id)
                manager = ou.manager_id if ou else False
                if manager:
                    for emp in self:
                        if manager.id != emp.id:
                            # Only inject if not already explicitly provided
                            vals.setdefault('parent_id', manager.id)
                            vals.setdefault('coach_id', manager.id)
                            vals.setdefault('planning_parent_id', manager.id)
                            break  # same manager applies to all emps in set

            elif new_parent_id and 'default_operating_unit_id' not in vals:
                # Direction 2: resolve operating unit managed by the new manager
                # Only when unambiguous (manager runs exactly one active unit)
                managed_units = OperatingUnit.search(
                    [('manager_id', '=', new_parent_id), ('active', '=', True)],
                    limit=2,
                )
                if len(managed_units) == 1:
                    vals.setdefault('default_operating_unit_id', managed_units[0].id)
        # ── End auto-sync ─────────────────────────────────────────────────

        tracked_fields = [f for f in self._JOB_HISTORY_TRACKED_FIELDS if f in vals]

        before = {}
        if tracked_fields:
            for emp in self:
                old_wage = self._get_employee_current_wage(emp)
                old_job_id = emp.job_id.id if emp.job_id else (emp.job_position.id if emp.job_position else False)
                before[emp.id] = {
                    'job_position': old_job_id,
                    'job_grade': emp.job_grade.id if emp.job_grade else False,
                    'default_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                    'department_id': emp.department_id.id if emp.department_id else False,
                    'wage': old_wage,
                }

        res = super().write(vals)

        if tracked_fields:
            self.with_context(in_job_history_logging=True)._log_job_history_changes(before)

        return res

    def _calculate_grade_step_salary(self, new_grade, old_wage):
        """Determines the appropriate salary step for a new grade based on the
        salary structure (base_salary and increment steps amount_1..10).

        Mandatory Rule: The new salary MUST exceed the old salary by at least 1,000.
        If current salary >= base salary of new grade, it finds the next step in new_grade
        where step_salary >= old_wage + 1000.
        """
        if not new_grade:
            return old_wage or 0.0

        steps = []
        if getattr(new_grade, 'base_salary', False) and new_grade.base_salary > 0:
            steps.append(new_grade.base_salary)

        inc = getattr(new_grade, 'increment_id', False)
        if inc:
            inc_rec = inc[0] if len(inc) > 0 else inc
            for i in range(1, 11):
                amt = getattr(inc_rec, f'amount_{i}', 0.0)
                if amt and amt > 0:
                    steps.append(amt)

        if not steps:
            return old_wage or 0.0

        steps = sorted(list(set(steps)))

        if not old_wage or old_wage <= 0:
            return steps[0]

        # Mandatory minimum salary increase threshold (+1,000)
        target_min_wage = old_wage + 1000.0

        for step_val in steps:
            if step_val >= target_min_wage:
                return step_val

        # If old_wage + 1000 exceeds all steps in the new grade, use max step available
        return steps[-1]

    def _log_job_history_changes(self, before):
        JobHistory = self.env['hr.job.history']
        today = fields.Date.context_today(self)
        reason = self.env.context.get('job_history_reason', 'other')

        for emp in self:
            old = before.get(emp.id)
            if old is None:
                continue

            new_job_id = emp.job_id.id if emp.job_id else (emp.job_position.id if emp.job_position else False)
            new_grade_id = emp.job_grade.id if emp.job_grade else False
            new_ou_id = emp.default_operating_unit_id.id if emp.default_operating_unit_id else False
            new_dept_id = emp.department_id.id if emp.department_id else False

            new = {
                'job_position': new_job_id,
                'job_grade': new_grade_id,
                'default_operating_unit_id': new_ou_id,
                'department_id': new_dept_id,
            }

            if (old['job_position'] == new['job_position'] and
                old['job_grade'] == new['job_grade'] and
                old['default_operating_unit_id'] == new['default_operating_unit_id'] and
                old['department_id'] == new['department_id']):
                continue

            job_obj = self.env['hr.job'].browse(new_job_id) if new_job_id else False
            position_name = job_obj.name if job_obj else False

            # Synchronize job_position, job_id, and job_name on hr.employee
            emp_vals = {}
            if new_job_id:
                if 'job_position' in emp._fields and (not emp.job_position or emp.job_position.id != new_job_id):
                    emp_vals['job_position'] = new_job_id
                if 'job_id' in emp._fields and (not emp.job_id or emp.job_id.id != new_job_id):
                    emp_vals['job_id'] = new_job_id
                if 'job_name' in emp._fields and position_name and emp.job_name != position_name:
                    emp_vals['job_name'] = position_name
            if emp_vals:
                emp.with_context(in_job_history_logging=True).write(emp_vals)

            old_wage = old.get('wage', 0.0)
            new_grade = emp.job_grade
            grade_changed = (old['job_grade'] != new_grade_id)

            if grade_changed and new_grade:
                if reason == 'demotion':
                    new_wage = old_wage
                else:
                    new_wage = self._calculate_grade_step_salary(new_grade, old_wage)
            else:
                new_wage = old_wage

            contracts = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ])
            if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
                contracts = emp.contract_id

            if contracts:
                contract_vals = {}
                version_fields = self.env['hr.version']._fields
                if reason != 'demotion' and new_wage and 'wage' in version_fields:
                    contract_vals['wage'] = new_wage
                if new_grade_id and 'job_grade' in version_fields:
                    contract_vals['job_grade'] = new_grade_id
                if new_job_id and 'job_id' in version_fields:
                    contract_vals['job_id'] = new_job_id
                if new_job_id and 'job_position' in version_fields:
                    contract_vals['job_position'] = new_job_id
                if new_ou_id and 'operating_unit_id' in version_fields:
                    contract_vals['operating_unit_id'] = new_ou_id
                if new_dept_id and 'department_id' in version_fields:
                    contract_vals['department_id'] = new_dept_id

                if contract_vals:
                    contracts.write(contract_vals)

            # Determine reason_for_movement and transfer_initiation_type
            pos_changed = (old['job_position'] != new_job_id)
            ou_changed = (old['default_operating_unit_id'] != new_ou_id)

            ctx_mov_reason = self.env.context.get('reason_for_movement') or self.env.context.get('movement_reason')
            if ctx_mov_reason:
                determined_movement_reason = ctx_mov_reason
            elif reason and self.env['hr.job.history'].map_reason_for_change_to_movement(reason):
                determined_movement_reason = self.env['hr.job.history'].map_reason_for_change_to_movement(reason)
            elif reason == 'demotion' or self.env.context.get('demotion'):
                determined_movement_reason = 'placement'
            elif grade_changed and pos_changed:
                determined_movement_reason = 'promotion'
            elif not grade_changed and pos_changed:
                determined_movement_reason = 'lateral_transfer'
            elif not grade_changed and not pos_changed and ou_changed:
                determined_movement_reason = 'transfer'
            elif grade_changed:
                determined_movement_reason = 'promotion'
            else:
                determined_movement_reason = 'transfer' if ou_changed else 'lateral_transfer'

            ctx_init_type = self.env.context.get('transfer_initiation_type')
            if ctx_init_type:
                determined_init_type = ctx_init_type
            elif (self.env.context.get('transfer_request_id') or
                  self.env.context.get('from_transfer_request') or
                  self.env.context.get('from_transfer_vacancy')):
                determined_init_type = 'self_initiated'
            else:
                determined_init_type = 'bank_initiated'

            # 1. Job History ALWAYS logs ALL movements (Promotion, Lateral Transfer, Transfer, Assignment, Placement, etc.)
            open_history = JobHistory.search([
                ('employee_id', '=', emp.id),
                ('job_history_end_date', '=', False),
            ], order='job_history_start_date desc', limit=1)

            if open_history:
                open_history.job_history_end_date = today

            JobHistory.create({
                'employee_id': emp.id,
                'from_job_id': old['job_position'],
                'to_job_id': new_job_id,
                'from_grade_id': old['job_grade'],
                'to_grade_id': new_grade_id,
                'from_operating_unit_id': old['default_operating_unit_id'],
                'to_operating_unit_id': new_ou_id,
                'from_department_id': old['department_id'],
                'to_department_id': new_dept_id,
                'old_wage': old_wage,
                'new_wage': new_wage,
                'position': position_name,
                'job_history_start_date': today,
                'reason_for_change': (
                    reason if reason in ('promotion', 'transfer', 'lateral_transfer', 'demotion', 'acting_role', 'recruitment', 'resignation', 'termination')
                    else ('promotion' if grade_changed else ('lateral_transfer' if pos_changed else 'transfer'))
                ),
                'reason_for_movement': determined_movement_reason,
                'transfer_initiation_type': determined_init_type,
            })

            # 2. Transfer History ONLY logs if it is a pure Transfer:
            # Same position, same grade, different operating unit.
            # Lateral transfers (different position title) MUST NOT be recorded in Transfer History!
            is_pure_transfer = (
                not grade_changed and not pos_changed and ou_changed
            )
            if is_pure_transfer:
                open_transfer = self.env['hr.employee.transfer.history'].search([
                    ('employee_id', '=', emp.id),
                    ('end_date', '=', False),
                ], order='start_date desc, id desc', limit=1)

                if open_transfer:
                    open_transfer.end_date = today

                self.env['hr.employee.transfer.history'].create({
                    'employee_id': emp.id,
                    'date': today,
                    'start_date': today,
                    'transfer_reason': 'Transfer',
                    'reason_for_movement': 'transfer',
                    'transfer_initiation_type': determined_init_type,
                    'from_operating_unit_id': old['default_operating_unit_id'],
                    'from_department_id': old['department_id'],
                    'from_job_id': old['job_position'],
                    'from_grade_id': old['job_grade'],
                    'to_operating_unit_id': new_ou_id,
                    'to_department_id': new_dept_id,
                    'to_job_id': new_job_id,
                    'to_grade_id': new_grade_id,
                })

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for emp in employees:
            job_id = self._get_job_id(emp)
            if job_id or emp.job_grade:
                initial_wage = self._get_employee_current_wage(emp)
                new_wage = self._calculate_grade_step_salary(emp.job_grade, initial_wage) if emp.job_grade else initial_wage

                contracts = self.env['hr.version'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['open', 'probation', 'draft'])
                ])
                if not contracts and hasattr(emp, 'contract_id') and emp.contract_id:
                    contracts = emp.contract_id

                if contracts and new_wage:
                    version_fields = self.env['hr.version']._fields
                    contract_vals = {}
                    if 'wage' in version_fields:
                        contract_vals['wage'] = new_wage
                    if emp.job_grade and 'job_grade' in version_fields:
                        contract_vals['job_grade'] = emp.job_grade.id
                    if job_id and 'job_id' in version_fields:
                        contract_vals['job_id'] = job_id
                    if emp.default_operating_unit_id and 'operating_unit_id' in version_fields:
                        contract_vals['operating_unit_id'] = emp.default_operating_unit_id.id
                    if emp.department_id and 'department_id' in version_fields:
                        contract_vals['department_id'] = emp.department_id.id
                    if contract_vals:
                        contracts.write(contract_vals)

                job_obj = self.env['hr.job'].browse(job_id) if job_id else False
                position_name = job_obj.name if job_obj else False

                self.env['hr.job.history'].create({
                    'employee_id': emp.id,
                    'to_job_id': job_id,
                    'to_grade_id': emp.job_grade.id if emp.job_grade else False,
                    'to_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                    'to_department_id': emp.department_id.id if emp.department_id else False,
                    'old_wage': initial_wage,
                    'new_wage': new_wage,
                    'position': position_name,
                    'job_history_start_date': fields.Date.context_today(self),
                    'reason_for_change': 'recruitment',
                })
        return employees

    # ── Experience Letter Helper Methods ─────────────────────────
    def get_experience_letter_salutation(self):
        """Determine employee salutation based on gender and marital status."""
        self.ensure_one()
        gender = (self.gender or '').strip().lower()
        if gender in ('female', 'f'):
            return 'W/y'
        return 'Ato' 

    def get_experience_letter_pronouns(self):
        """Returns pronouns dictionary based on employee gender."""
        self.ensure_one()
        gender = (self.gender or '').strip().lower()
        if gender in ('female', 'f'):
            return {
                'subj': 'She',
                'subj_lower': 'she',
                'obj': 'her',
                'poss': 'her',
                'poss_cap': 'Her',
            }
        return {
            'subj': 'He',
            'subj_lower': 'he',
            'obj': 'him',
            'poss': 'his',
            'poss_cap': 'His',
        }

    def get_experience_letter_ref_no(self):
        """Returns official formatted reference number for experience letter."""
        self.ensure_one()
        seq = self.env['ir.sequence'].next_by_code('employee.experience.letter')
        if seq:
            return seq
        digits = ''.join(filter(str.isdigit, str(self.identification_id or self.barcode or self.id))) or str(self.id)
        year_suffix = fields.Date.context_today(self).strftime('%y')
        return f"BB/POMD-PSR/{digits}/0{year_suffix}"

    def get_sorted_job_history(self):
        """Returns employee's job history records sorted in ascending chronological order,
        including the active/current position ending with 'To date.' if not already present."""
        self.ensure_one()
        histories = []
        if hasattr(self, 'job_history_ids') and self.job_history_ids:
            histories = list(self.job_history_ids.sorted(
                key=lambda h: (h.job_history_start_date or date.min, h.id or 0)
            ))

        # Check if an open history record already exists (end_date is False)
        has_open_record = any(not h.job_history_end_date for h in histories)

        if not has_open_record:
            current_start = False
            if histories:
                last_end = max(h.job_history_end_date for h in histories if h.job_history_end_date)
                if last_end:
                    current_start = last_end + timedelta(days=1)

            # Check if latest transfer has a more recent start date
            if hasattr(self, 'employee_transfer_ids') and self.employee_transfer_ids:
                transfers = self.employee_transfer_ids.sorted(
                    key=lambda t: t.start_date or t.date or fields.Date.min
                )
                if transfers:
                    t_date = transfers[-1].start_date or transfers[-1].date
                    if t_date and (not current_start or t_date > current_start):
                        current_start = t_date

            if not current_start:
                if hasattr(self, 'first_contract_date') and self.first_contract_date:
                    current_start = self.first_contract_date
                elif hasattr(self, 'contract_id') and self.contract_id and self.contract_id.date_start:
                    current_start = self.contract_id.date_start
                elif self.create_date:
                    current_start = self.create_date.date()
                else:
                    current_start = fields.Date.context_today(self)

            current_job = self.job_id or self.env['hr.job']
            current_pos = (
                (self.job_id and self.job_id.name)
                or getattr(self, 'job_title', False)
                or (getattr(self, 'job_position', False) and self.job_position.name)
                or ''
            )

            class _CurrentJobHistoryItem:
                def __init__(self, job_id, position, start_date, end_date):
                    self.job_id = job_id
                    self.position = position
                    self.job_history_start_date = start_date
                    self.job_history_end_date = end_date

                def __bool__(self):
                    return True

            histories.append(_CurrentJobHistoryItem(
                job_id=current_job,
                position=current_pos,
                start_date=current_start,
                end_date=False
            ))

        return histories

    def get_experience_letter_start_date(self):
        """Returns the earliest start date formatted as YYYY-MM-DD."""
        self.ensure_one()
        if hasattr(self, 'first_contract_date') and self.first_contract_date:
            return self.first_contract_date.strftime('%Y-%m-%d')
        histories = self.get_sorted_job_history()
        if histories and histories[0].job_history_start_date:
            return histories[0].job_history_start_date.strftime('%Y-%m-%d')
        if hasattr(self, 'contract_id') and self.contract_id and self.contract_id.date_start:
            return self.contract_id.date_start.strftime('%Y-%m-%d')
        if self.create_date:
            return self.create_date.strftime('%Y-%m-%d')
        return fields.Date.context_today(self).strftime('%Y-%m-%d')

    def _amount_to_words_title_en(self, amt):
        """Convert a numerical amount to English words in Title Case."""
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

        def helper(num):
            if num < 20:
                return ones[num]
            elif num < 100:
                rem = num % 10
                return tens[num // 10] + ('-' + ones[rem] if rem else '')
            elif num < 1000:
                rem = num % 100
                return ones[num // 100] + ' Hundred' + (' ' + helper(rem) if rem else '')
            elif num < 1000000:
                thousands = num // 1000
                rem = num % 1000
                return helper(thousands) + ' Thousand' + (' ' + helper(rem) if rem else '')
            elif num < 1000000000:
                millions = num // 1000000
                rem = num % 1000000
                return helper(millions) + ' Million' + (' ' + helper(rem) if rem else '')
            else:
                billions = num // 1000000000
                rem = num % 1000000000
                return helper(billions) + ' Billion' + (' ' + helper(rem) if rem else '')

        amt = round(float(amt), 2)
        int_part = int(amt)
        cents = int(round((amt - int_part) * 100))
        res = helper(int_part).strip() if int_part > 0 else 'Zero'
        if cents > 0:
            res += f' and {cents:02d}/100'
        return res

    def get_experience_letter_salary_info(self):
        """Fetches employee's monthly gross wage from contract, grade, or history,
        returning both formatted numeric string and Title Case words."""
        self.ensure_one()
        wage = 0.0

        # 1. From hr.version contract
        if 'hr.version' in self.env:
            contracts = self.env['hr.version'].search([
                ('employee_id', '=', self.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if contracts:
                if getattr(contracts, 'wage', 0.0):
                    wage = contracts.wage
                elif getattr(contracts, 'base_salary', 0.0):
                    wage = contracts.base_salary

        # 2. From standard hr.contract
        if not wage and hasattr(self, 'contract_id') and self.contract_id and getattr(self.contract_id, 'wage', 0.0):
            wage = self.contract_id.wage

        # 3. From job grade structure
        if not wage:
            grade = getattr(self, 'job_grade', False) or getattr(self, 'grade_id', False)
            if grade:
                if hasattr(self, '_calculate_grade_step_salary'):
                    wage = self._calculate_grade_step_salary(grade, 0.0)
                elif getattr(grade, 'base_salary', False):
                    wage = grade.base_salary

        # 4. From latest job history row
        if not wage and hasattr(self, 'job_history_ids') and self.job_history_ids:
            latest = self.job_history_ids.sorted(
                key=lambda h: (h.job_history_start_date or fields.Date.min, h.id or 0),
                reverse=True
            )[:1]
            if latest and latest.new_wage:
                wage = latest.new_wage

        fig_str = f"{wage:,.2f}" if wage else "0.00"
        words_str = self._amount_to_words_title_en(wage) if wage else "Zero"
        return {
            'amount': wage,
            'figure': fig_str,
            'words': words_str,
        }

    def get_experience_letter_signatory_name(self):
        """Returns signatory name from system parameter, signatory config, or default."""
        param_name = self.env['ir.config_parameter'].sudo().get_param('hr_experience_letter_signatory')
        if param_name:
            return param_name
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type='experience_letter')
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and sig.signatory_name:
                    return sig.signatory_name
            except Exception:
                pass
        return 'Melesse Leykun'

    def get_experience_letter_signatory_title(self):
        """Returns signatory title from system parameter, signatory config, or default."""
        param_title = self.env['ir.config_parameter'].sudo().get_param('hr_experience_letter_signatory_title')
        if param_title:
            return param_title
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type='experience_letter')
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and sig.signatory_title:
                    return sig.signatory_title
            except Exception:
                pass
        return 'Manager- People Service and Reward Division'

    def get_experience_letter_signature_stamp(self):
        """Returns Base64 data URI of authorized signature and official rubber stamp."""
        self.ensure_one()
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type='experience_letter')
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and hasattr(sig, 'get_signature_stamp_base64'):
                    b64 = sig.get_signature_stamp_base64()
                    if b64:
                        return b64
            except Exception:
                pass

        comp = self.company_id or self.env.company
        if hasattr(comp, 'certificate_signature') and comp.certificate_signature:
            raw = comp.certificate_signature
            b64_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            return f"data:image/png;base64,{b64_str}"

        return ""

    def get_experience_letter_logo_data_uri(self):
        """Returns base64 data URI of the official Bunna Bank logo for experience letters."""
        import base64
        import os
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            module_dir = os.path.dirname(curr_dir)
            logo_path = os.path.join(module_dir, 'static', 'src', 'img', 'bunna_logo.jpg')
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('utf-8')
                    return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            pass
        if hasattr(self, 'company_id') and self.company_id and self.company_id.logo:
            raw = self.company_id.logo
            b64_str = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            return f"data:image/png;base64,{b64_str}"
        return "/hr_employee_custom/static/src/img/bunna_logo.jpg"