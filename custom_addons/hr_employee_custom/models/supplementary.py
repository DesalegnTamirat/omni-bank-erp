import logging
from datetime import timedelta
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

class Supplementary_details(models.Model):
    _name = "supplementary.role"
    _description = "Supplementary role"
    _rec_name = "reference"

    def _default_requesting_operating_unit(self):
        user = self.env.user
        if user.employee_id and user.employee_id.default_operating_unit_id:
            return user.employee_id.default_operating_unit_id
        if hasattr(user, 'default_operating_unit_id') and user.default_operating_unit_id:
            return user.default_operating_unit_id
        return False

    reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    sr_ref = fields.Char(string="SR Reference", readonly=True)
    allowed_operating_unit_ids = fields.Many2many(
        "operating.unit",
        compute="_compute_allowed_operating_units",
        string="Allowed Operating Units"
    )
    requesting_operating_unit = fields.Many2one("operating.unit", string="Requesting operating Unit", default=_default_requesting_operating_unit)
    acting_employee = fields.Many2one("hr.employee", "Acting Employee")
    employee_name = fields.Many2one("hr.employee", "Employee Name")
    employee_id = fields.Char(string="Employee Id")
    acting_basic_per_month = fields.Float("Acting Basic per Month")
    acting_basic = fields.Float("New Basic Salary")
    base_salary = fields.Float("Base Salary")
    step_increment_value = fields.Float("Step Increment Value")
    existing_basic = fields.Float("Existing Basic Salary")
    acting_position = fields.Many2one("hr.job", "Vacant Position")
    current_job_position = fields.Many2one("hr.job", "Current Job Position", readonly=True)
    current_work_unit = fields.Many2one("operating.unit", "Current Work Unit", readonly=True)
    acting_job_position = fields.Many2one("hr.job", "Acting Job Position", readonly=True)
    acting_work_unit = fields.Char("Acting Work Unit", readonly=True)
    acting_reason = fields.Char("Acting Reason")
    basic_difference = fields.Float("Difference in Basic", readonly=True)
    allowance_difference = fields.Float("Difference in Allowances", readonly=True)
    start_date = fields.Date("Start Date")
    payment_date_start = fields.Date(
        string="Payment Date Start",
        compute="_compute_payment_date_start",
        store=True,
        readonly=True,
        help="Payment start date for acting employee, which begins after 30 days from the acting start date."
    )
    end_date = fields.Date("End Date")
    status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
    ], string="Status", default='draft', compute='_compute_status', store=True)
    first_month = fields.Float('First month', default=0.00)
    second_month = fields.Float('Second Month', default=0.25)
    third_month = fields.Float('Third Month', default=0.25)
    more_than_four = fields.Float('More Than Four', default=0.50)
    job_grade = fields.Many2one('employee.grade', string='Current Job Grade', help="Job Grade", readonly=True)
    job_category = fields.Char(string='Current Job Category', readonly=True)
    job_grade1 = fields.Many2one('employee.grade', string='Acting Job Grade', help="Job Grade", readonly=True)
    job_category1 = fields.Char(string='Acting Job Category', help="Job Category", readonly=True) 
    cc_workunits = fields.Many2many("operating.unit", string="CC To:", help="Enter the Workunits to be copied")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
    ], string="State", default='draft')
    is_managerial = fields.Boolean(
        string="Is Managerial Position",
        compute="_compute_is_managerial",
        store=True,
        help="Indicates whether the acting/vacant position is Managerial (eligible for acting allowance & benefits)."
    )
    can_review_or_approve = fields.Boolean(
        string="Can Review or Approve",
        compute="_compute_can_review_or_approve"
    )
    revoked_date = fields.Date("Revoked Date")
    supplementary_details = fields.One2many("hr.supplementary.salary", "supplementary_id2", "Supplementary Salary Details")
    supplementary_payouts = fields.One2many("hr.supplementary.payout", "supplementary_id3", "Supplementary Salary Payouts")
    sup_delg_team = fields.One2many("supplementary.delegation.team", "supp_role_del_id", "Supplementary Delegation Team")

    def _auto_init(self):
        # Drop legacy foreign key constraints if field was converted from Many2one to Char
        self.env.cr.execute("""
            ALTER TABLE supplementary_role 
            DROP CONSTRAINT IF EXISTS supplementary_role_job_category_fkey;
            ALTER TABLE supplementary_role 
            DROP CONSTRAINT IF EXISTS supplementary_role_job_category1_fkey;
        """)
        return super()._auto_init()


    def _get_summary_info(self):
        """Extract clean summary strings for notification messages without any HTML tags."""
        self.ensure_one()
        emp_name = (self.employee_name.name if self.employee_name else False) or (self.acting_employee.name if self.acting_employee else False) or 'N/A'
        vacant_pos = (self.acting_position.name if self.acting_position else False) or (self.acting_job_position.name if self.acting_job_position else False) or (self.acting_employee.job_position.name if self.acting_employee and self.acting_employee.job_position else False) or 'N/A'
        unit = (self.requesting_operating_unit.name if self.requesting_operating_unit else False) or (self.acting_work_unit if self.acting_work_unit else False) or (self.current_work_unit.name if self.current_work_unit else False) or (self.employee_name.default_operating_unit_id.name if self.employee_name and self.employee_name.default_operating_unit_id else False) or 'N/A'
        ref = self.reference or ''
        return ref, emp_name, vacant_pos, unit

    def _get_stakeholder_partners(self):
        """Collect partner IDs of Employee, Coach, and Creator."""
        partners = set()
        for rec in self:
            employees = [e for e in (rec.employee_name, rec.acting_employee) if e]
            for emp in employees:
                if emp.user_id and emp.user_id.partner_id:
                    partners.add(emp.user_id.partner_id.id)
                elif emp.work_contact_id:
                    partners.add(emp.work_contact_id.id)
                if emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.partner_id:
                    partners.add(emp.coach_id.user_id.partner_id.id)
                elif emp.coach_id and emp.coach_id.work_contact_id:
                    partners.add(emp.coach_id.work_contact_id.id)
                if emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.partner_id:
                    partners.add(emp.parent_id.user_id.partner_id.id)
                elif emp.parent_id and emp.parent_id.work_contact_id:
                    partners.add(emp.parent_id.work_contact_id.id)
            if rec.create_uid and rec.create_uid.partner_id:
                partners.add(rec.create_uid.partner_id.id)
        return list(partners)

    def _get_committee_partners(self):
        """Collect partner IDs for active/alternate committee delegation members."""
        partners = set()
        for rec in self:
            for com in rec.sup_delg_team:
                user = False
                if com.status == 'unavailable' and com.alternate_committee_member:
                    user = com.alternate_committee_member
                elif com.employee_name:
                    user = com.employee_name
                if user and user.partner_id:
                    partners.add(user.partner_id.id)
        return list(partners)

    def _get_hr_partners(self):
        """Collect partner IDs for HR Officers and HR Managers."""
        partners = set()
        for xml_id in ('hr.group_hr_user', 'hr.group_hr_manager'):
            grp = self.env.ref(xml_id, raise_if_not_found=False)
            if grp:
                for u in grp.user_ids:
                    if u.partner_id and not u.share:
                        partners.add(u.partner_id.id)
        return list(partners)

    def _send_stage_notification(self, partner_ids, subject, body_text):
        """Send 1-on-1 direct message via discuss.channel using sudo."""
        if not partner_ids:
            return 0
        sent_count = 0
        from .mail_thread_patch import format_notification_body_html
        formatted_body = format_notification_body_html(body_text)
        for pid in set(partner_ids):
            if not pid:
                continue
            try:
                channel = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[pid])
                if channel:
                    channel.sudo().message_post(
                        body=formatted_body,
                        subject=subject,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                    sent_count += 1
            except Exception as e:
                _logger.warning("Supplementary role: Failed to send notification to partner %s: %s", pid, e)
        return sent_count

    def mail_channel_msgs(self, rec_id, ref, arg1):
        """Backward-compatible wrapper for legacy notification calls."""
        if not rec_id:
            return
        msg = (
            f"Dear Committee,\n\n"
            f"A New Acting form is created with following details:\n"
            f"• Reference No: {ref}\n"
            f"• Employee Name: {arg1}\n\n"
            f"Kindly approve."
        )
        self._send_stage_notification([rec_id], f"Acting Role: {ref}", msg)


    @api.depends_context('uid')
    def _compute_allowed_operating_units(self):
        user = self.env.user
        is_hr_admin = (
            self.env.is_superuser()
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
        )
        if is_hr_admin:
            # Employee module admins can select from all operating units
            all_ous = self.env['operating.unit'].search([])
        else:
            # Non-admin users can ONLY select their own operating unit(s)
            ou_ids = set()
            if hasattr(user, 'operating_unit_ids') and user.operating_unit_ids:
                ou_ids.update(user.operating_unit_ids.ids)
            if hasattr(user, 'default_operating_unit_id') and user.default_operating_unit_id:
                ou_ids.add(user.default_operating_unit_id.id)
            if user.employee_id and user.employee_id.default_operating_unit_id:
                ou_ids.add(user.employee_id.default_operating_unit_id.id)
            all_ous = self.env['operating.unit'].browse(list(ou_ids))

        for rec in self:
            rec.allowed_operating_unit_ids = all_ous

    @api.constrains('requesting_operating_unit')
    def _check_requesting_operating_unit(self):
        user = self.env.user
        is_hr_admin = (
            self.env.is_superuser()
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
        )
        if is_hr_admin:
            return
        for rec in self:
            if rec.requesting_operating_unit and rec.allowed_operating_unit_ids:
                if rec.requesting_operating_unit not in rec.allowed_operating_unit_ids:
                    allowed_names = ', '.join(rec.allowed_operating_unit_ids.mapped('name'))
                    raise ValidationError(_(
                        "Access Restriction:\n"
                        "You can only select your own operating unit (%(units)s) as the Requesting Operating Unit. "
                        "Only employees with Admin access in Employee module can select other operating units."
                    ) % {'units': allowed_names})


    @api.depends_context('uid')
    def _compute_allowed_operating_units(self):
        user = self.env.user
        is_hr_admin = (
            self.env.is_superuser()
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
        )
        if is_hr_admin:
            # Employee module admins can select from all operating units
            all_ous = self.env['operating.unit'].search([])
        else:
            # Non-admin users can ONLY select their own operating unit(s)
            ou_ids = set()
            if hasattr(user, 'operating_unit_ids') and user.operating_unit_ids:
                ou_ids.update(user.operating_unit_ids.ids)
            if hasattr(user, 'default_operating_unit_id') and user.default_operating_unit_id:
                ou_ids.add(user.default_operating_unit_id.id)
            if user.employee_id and user.employee_id.default_operating_unit_id:
                ou_ids.add(user.employee_id.default_operating_unit_id.id)
            all_ous = self.env['operating.unit'].browse(list(ou_ids))

        for rec in self:
            rec.allowed_operating_unit_ids = all_ous

    @api.constrains('requesting_operating_unit')
    def _check_requesting_operating_unit(self):
        user = self.env.user
        is_hr_admin = (
            self.env.is_superuser()
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
        )
        if is_hr_admin:
            return
        for rec in self:
            if rec.requesting_operating_unit and rec.allowed_operating_unit_ids:
                if rec.requesting_operating_unit not in rec.allowed_operating_unit_ids:
                    allowed_names = ', '.join(rec.allowed_operating_unit_ids.mapped('name'))
                    raise ValidationError(_(
                        "Access Restriction:\n"
                        "You can only select your own operating unit (%(units)s) as the Requesting Operating Unit. "
                        "Only employees with Admin access in Employee module can select other operating units."
                    ) % {'units': allowed_names})

    def _is_people_operation_approver(self):
        """Check if current user is authorized to review or approve acting requests:
        1. Superuser / HR Manager
        2. Employee ID 4561 (Mahlet Mulatu Libassie) or identification_id 4561
        3. Coach ID is 4561
        4. Operating unit is under People Operation Directorate (OU 1003)
        """
        user = self.env.user
        if self.env.is_superuser() or user.has_group('hr.group_hr_manager'):
            return True
        emp = user.employee_id
        if not emp:
            return False
        if emp.id == 4561 or getattr(emp, 'identification_id', '') == '4561':
            return True
        if emp.coach_id and (emp.coach_id.id == 4561 or getattr(emp.coach_id, 'identification_id', '') == '4561'):
            return True
        if emp.default_operating_unit_id:
            if emp.default_operating_unit_id.id == 1003:
                return True
            ou_name = (emp.default_operating_unit_id.name or '').lower()
            if any(term in ou_name for term in ['people operation', 'human resource']):
                return True
        return False

    def _compute_can_review_or_approve(self):
        is_approver = self._is_people_operation_approver()
        for rec in self:
            rec.can_review_or_approve = is_approver

    def _get_acting_notification_partners(self):
        """Collect partner IDs strictly for:
        1. The Requestor (create_uid / employee who initiated the request)
        2. Employee ID 4561 and any employee whose coach_id is 4561 in hr.employee
        """
        partners = set()
        for rec in self:
            # 1. Requestor
            if rec.create_uid and rec.create_uid.partner_id:
                partners.add(rec.create_uid.partner_id.id)
            if rec.acting_employee and rec.acting_employee.user_id and rec.acting_employee.user_id.partner_id:
                partners.add(rec.acting_employee.user_id.partner_id.id)
            elif rec.acting_employee and rec.acting_employee.work_contact_id:
                partners.add(rec.acting_employee.work_contact_id.id)

        # 2. Employees from hr.employee where id = 4561 or coach_id = 4561
        authorized_emps = self.env['hr.employee'].sudo().search([
            '|',
            ('id', '=', 4561),
            ('coach_id', '=', 4561),
        ])
        for emp in authorized_emps:
            if emp.user_id and emp.user_id.partner_id:
                partners.add(emp.user_id.partner_id.id)
            elif emp.work_contact_id:
                partners.add(emp.work_contact_id.id)

        return list(partners)

    def _get_people_operation_partners(self):
        """Collect partner IDs for People Operation Directorate staff and Coach 4561."""
        partners = set()
        # Employee 4561 & direct coach 4561
        approvers = self.env['hr.employee'].sudo().search([
            '|', '|',
            ('id', '=', 4561),
            ('identification_id', '=', '4561'),
            ('coach_id', '=', 4561),
        ])
        for emp in approvers:
            if emp.user_id and emp.user_id.partner_id:
                partners.add(emp.user_id.partner_id.id)
            elif emp.work_contact_id:
                partners.add(emp.work_contact_id.id)

        # Operating Unit 1003 (People Operation Management Directorate)
        ou_emps = self.env['hr.employee'].sudo().search([
            ('default_operating_unit_id', '=', 1003),
        ])
        for emp in ou_emps:
            if emp.user_id and emp.user_id.partner_id:
                partners.add(emp.user_id.partner_id.id)

        # HR Managers
        for p in self._get_hr_partners():
            partners.add(p)

        return list(partners)

    @api.depends('start_date')
    def _compute_payment_date_start(self):
        for rec in self:
            if rec.start_date:
                rec.payment_date_start = rec.start_date + timedelta(days=30)
            else:
                rec.payment_date_start = False

    @api.depends('state')
    def _compute_status(self):
        for rec in self:
            rec.status = rec.state or 'draft'

    @api.depends('acting_position', 'acting_position.employee_category', 'acting_job_position', 'acting_job_position.employee_category', 'job_category1')
    def _compute_is_managerial(self):
        for rec in self:
            job = rec.acting_position or rec.acting_job_position
            is_mgr = False
            if job:
                if hasattr(job, 'employee_category') and job.employee_category:
                    cat_str = str(job.employee_category).strip().lower()
                    if 'managerial' in cat_str and 'non' not in cat_str:
                        is_mgr = True
                elif hasattr(job, 'is_managerial'):
                    is_mgr = bool(job.is_managerial)
                elif hasattr(job, 'name') and job.name:
                    jname = job.name.lower()
                    if any(k in jname for k in ['manager', 'director', 'chief', 'head', 'vice president', 'president']):
                        is_mgr = True
            elif rec.job_category1:
                cat_str = (rec.job_category1.name if hasattr(rec.job_category1, 'name') else str(rec.job_category1)).lower()
                if 'managerial' in cat_str and 'non' not in cat_str:
                    is_mgr = True
            rec.is_managerial = is_mgr

    def _auto_compute_managerial_benefits(self):
        pass

    def action_submit(self):
        for rec in self:
            rec.state = 'submitted'
            rec.status = 'submitted'
            ref, emp_name, vacant_pos, unit = rec._get_summary_info()
            recipients = set(rec._get_acting_notification_partners())
            cat_label = 'Managerial' if rec.is_managerial else 'Non-Managerial'
            msg = (
                f"Dear Colleague,\n\n"
                f"Supplementary / Acting Role request {ref} has been SUBMITTED:\n"
                f"• Acting Employee: {emp_name}\n"
                f"• Vacant Position: {vacant_pos}\n"
                f"• Position Category: {cat_label}\n"
                f"• Work Unit: {unit}\n\n"
                f"Kindly review and evaluate."
            )
            rec._send_stage_notification(recipients, f"Acting Role Submitted: {ref}", msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Submitted'),
                'message': _('Supplementary role request has been submitted to People Operation for review.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_under_review(self):
        for rec in self:
            if not rec._is_people_operation_approver():
                raise UserError(_("Only authorized employees under the People Operation Management Directorate (or Coach ID 4561) can move this request to Under Review."))
            rec.state = 'under_review'
            rec.status = 'under_review'
            ref, emp_name, vacant_pos, unit = rec._get_summary_info()
            recipients = set(rec._get_acting_notification_partners())
            cat_label = 'Managerial' if rec.is_managerial else 'Non-Managerial'
            msg = (
                f"Dear Colleague,\n\n"
                f"Supplementary / Acting Role request {ref} for {emp_name} ({vacant_pos}, {cat_label}) "
                f"is now UNDER REVIEW by People Operation Directorate."
            )
            rec._send_stage_notification(recipients, f"Acting Role Under Review: {ref}", msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Under Review'),
                'message': _('Supplementary role request is now under review.'),
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _apply_acting_position_to_employee(self):
        """Applies the acting/supplementary position to the employee profile and active contract."""
        for rec in self:
            emp = rec.employee_name or rec.acting_employee
            acting_pos = rec.acting_position or rec.acting_job_position
            if not emp or not acting_pos:
                continue

            emp_vals = {
                'job_position': acting_pos.id,
                'job_id': acting_pos.id,
            }
            if 'job_name' in emp._fields and acting_pos.name:
                emp_vals['job_name'] = acting_pos.name
            if 'job_title' in emp._fields and acting_pos.name:
                emp_vals['job_title'] = acting_pos.name
            if rec.job_grade1 and 'job_grade' in emp._fields:
                emp_vals['job_grade'] = rec.job_grade1.id
            if rec.requesting_operating_unit and 'default_operating_unit_id' in emp._fields:
                emp_vals['default_operating_unit_id'] = rec.requesting_operating_unit.id
            if acting_pos.department_id and 'department_id' in emp._fields:
                emp_vals['department_id'] = acting_pos.department_id.id

            emp.sudo().with_context(in_job_history_logging=True).write(emp_vals)

            # Also synchronize active contracts / versions (hr.version)
            contracts = self.env['hr.version'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'draft', 'probation']),
            ])
            if contracts:
                c_vals = {}
                v_fields = contracts._fields
                if 'job_id' in v_fields:
                    c_vals['job_id'] = acting_pos.id
                if 'job_position' in v_fields:
                    c_vals['job_position'] = acting_pos.id
                if rec.job_grade1 and 'job_grade' in v_fields:
                    c_vals['job_grade'] = rec.job_grade1.id
                if rec.requesting_operating_unit and 'operating_unit_id' in v_fields:
                    c_vals['operating_unit_id'] = rec.requesting_operating_unit.id
                if acting_pos.department_id and 'department_id' in v_fields:
                    c_vals['department_id'] = acting_pos.department_id.id
                if c_vals:
                    contracts.write(c_vals)

    def _revert_to_substantive_position(self):
        """Reverts the employee profile and active contract back to substantive position."""
        for rec in self:
            emp = rec.employee_name or rec.acting_employee
            orig_pos = rec.current_job_position
            if not emp or not orig_pos:
                continue

            rev_vals = {
                'job_position': orig_pos.id,
                'job_id': orig_pos.id,
            }
            if 'job_name' in emp._fields and orig_pos.name:
                rev_vals['job_name'] = orig_pos.name
            if 'job_title' in emp._fields and orig_pos.name:
                rev_vals['job_title'] = orig_pos.name
            if rec.job_grade and 'job_grade' in emp._fields:
                rev_vals['job_grade'] = rec.job_grade.id
            if rec.current_work_unit and 'default_operating_unit_id' in emp._fields:
                rev_vals['default_operating_unit_id'] = rec.current_work_unit.id
            if orig_pos.department_id and 'department_id' in emp._fields:
                rev_vals['department_id'] = orig_pos.department_id.id

            emp.sudo().with_context(in_job_history_logging=True).write(rev_vals)

            contracts = self.env['hr.version'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'draft', 'probation']),
            ])
            if contracts:
                c_vals = {}
                v_fields = contracts._fields
                if 'job_id' in v_fields:
                    c_vals['job_id'] = orig_pos.id
                if 'job_position' in v_fields:
                    c_vals['job_position'] = orig_pos.id
                if rec.job_grade and 'job_grade' in v_fields:
                    c_vals['job_grade'] = rec.job_grade.id
                if rec.current_work_unit and 'operating_unit_id' in v_fields:
                    c_vals['operating_unit_id'] = rec.current_work_unit.id
                if orig_pos.department_id and 'department_id' in v_fields:
                    c_vals['department_id'] = orig_pos.department_id.id
                if c_vals:
                    contracts.write(c_vals)

    def action_approve(self):
        for rec in self:
            if not rec._is_people_operation_approver():
                raise UserError(_("Only authorized employees under the People Operation Management Directorate (or Coach ID 4561) can approve Supplementary Role requests."))
            # Record acting role in hr.job.history cleanly via ORM
            emp = rec.employee_name or rec.acting_employee
            if emp:
                try:
                    self.env['hr.job.history'].sudo().create({
                        'employee_id': emp.id,
                        'from_job_id': emp.job_position.id if emp.job_position else False,
                        'to_job_id': rec.acting_position.id if rec.acting_position else (rec.acting_job_position.id if rec.acting_job_position else False),
                        'from_grade_id': emp.job_grade.id if emp.job_grade else False,
                        'to_grade_id': rec.job_grade1.id if rec.job_grade1 else False,
                        'from_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                        'to_operating_unit_id': rec.requesting_operating_unit.id if rec.requesting_operating_unit else False,
                        'job_history_start_date': rec.start_date,
                        'job_history_end_date': rec.end_date,
                        'reason_for_change': 'acting_role',
                    })
                except Exception as e:
                    _logger.warning("Failed to create acting job history for employee %s: %s", emp.id, e)
            # Apply acting position to employee profile & contract
            rec._apply_acting_position_to_employee()

            rec.state = 'approved'
            rec.status = 'approved'

            ref, emp_name, vacant_pos, unit = rec._get_summary_info()
            start_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else 'N/A'
            end_date = rec.end_date.strftime('%Y-%m-%d') if rec.end_date else 'N/A'
            cat_label = 'Managerial' if rec.is_managerial else 'Non-Managerial'

            appr_msg = (
                f"Dear Colleague,\n\n"
                f"Supplementary / Acting Role assignment {ref} has been APPROVED.\n\n"
                f"• Employee: {emp_name}\n"
                f"• Acting Position: {vacant_pos}\n"
                f"• Category: {cat_label}\n"
                f"• Start Date: {start_date}\n"
                f"• End Date: {end_date}\n\n"
                f"The acting position history has been activated in the employee profile."
            )
            recipients = set(rec._get_acting_notification_partners())
            rec._send_stage_notification(recipients, f"Supplementary Role Approved: {ref}", appr_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supplementary Role Approved'),
                'message': _('Supplementary Role approved and notifications sent to all stakeholders.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'approved':
                rec._revert_to_substantive_position()
            rec.state = 'draft'
            rec.status = 'draft'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reset to Draft'),
                'message': _('Supplementary Role reset to Draft.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_print_acting_letter(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("You can only print the Acting Letter once the request is approved."))
        if self.is_managerial:
            return self.env.ref('hr_employee_custom.action_acting_assignment_managerial').report_action(self)
        else:
            return self.env.ref('hr_employee_custom.action_acting_assignment').report_action(self)

    def notify(self):
        for rec in self:
            ref, emp_name, vacant_pos, unit = rec._get_summary_info()

            # 1. Notify Committee Members
            committee_pids = rec._get_committee_partners()
            if committee_pids:
                com_msg = (
                    f"Dear Committee Member,\n\n"
                    f"A New Supplementary / Acting Role request has been submitted for your evaluation:\n"
                    f"• Reference No: {ref}\n"
                    f"• Acting Employee: {emp_name}\n"
                    f"• Vacant Position: {vacant_pos}\n"
                    f"• Operating Unit: {unit}\n\n"
                    f"Kindly review and evaluate the assignment."
                )
                rec._send_stage_notification(committee_pids, f"Acting Role Evaluation Request: {ref}", com_msg)

            # 2. Notify Employee & Coach/Creator
            stakeholder_pids = rec._get_stakeholder_partners()
            if stakeholder_pids:
                stk_msg = (
                    f"Dear Colleague,\n\n"
                    f"Supplementary Role request {ref} for {emp_name} "
                    f"(Acting as {vacant_pos}) has been submitted to the Evaluation Committee."
                )
                rec._send_stage_notification(stakeholder_pids, f"Acting Role Submitted: {ref}", stk_msg)

            rec.state = "notify"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Sent'),
                'message': _('Committee members and stakeholders have been notified for stage: Notify Committee.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def evaluate(self):
        for rec in self:
            n = 0
            current_user = self.env.user
            for val in rec.sup_delg_team:
                if val.status == "unavailable":
                    if current_user.id == val.employee_name.id:
                        raise ValidationError(_("Sorry! You cannot evaluate this request as you are marked unavailable."))
                    elif val.alternate_committee_member and current_user.id == val.alternate_committee_member.id:
                        val.approve = True
                        n += 1
                        break
                else:
                    if val.employee_name and (val.employee_name.id == current_user.id or val.employee_name.name == current_user.name):
                        val.approve = True
                        n += 1
                        break

            # If user is admin/HR manager, allow evaluating unapproved member line
            if n == 0 and (self.env.is_superuser() or current_user.has_group('hr.group_hr_manager')):
                unapproved = rec.sup_delg_team.filtered(lambda t: not t.approve)
                if unapproved:
                    unapproved[0].approve = True
                    n += 1
                elif not rec.sup_delg_team:
                    n += 1

            if n == 0:
                raise ValidationError(_("Sorry! You are not assigned to evaluate this request."))

            cnt = sum(1 for vals in rec.sup_delg_team if vals.approve)
            mem_cnt = len(rec.sup_delg_team)

            if cnt >= mem_cnt:
                rec.state = "evaluate"
                # Notify Stakeholders & HR that all evaluations are complete
                ref, emp_name, vacant_pos, unit = rec._get_summary_info()

                eval_msg = (
                    f"Dear HR Team & Supervisor,\n\n"
                    f"All Evaluation Committee members have completed their evaluation for Supplementary Role {ref} "
                    f"(Employee: {emp_name}, Acting Position: {vacant_pos}).\n\n"
                    f"The request is now ready for Benefits and Allowance calculation."
                )
                recipients = set(rec._get_stakeholder_partners() + rec._get_hr_partners())
                rec._send_stage_notification(recipients, f"Supplementary Role Evaluated: {ref}", eval_msg)

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Evaluation Completed'),
                        'message': _('All committee evaluations are complete. HR and stakeholders have been notified.'),
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Evaluation Recorded'),
                        'message': _('Your evaluation has been recorded (%s/%s committee members completed).') % (cnt, mem_cnt),
                        'type': 'info',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                    }
                }

    @api.onchange('acting_employee')
    def _onchange_acting_employee_info(self):
        if self.acting_employee:
            emp = self.acting_employee
            self.employee_name = emp
            self.employee_id = emp.identification_id if hasattr(emp, 'identification_id') else str(emp.id)
            self.current_job_position = emp.job_position
            self.current_work_unit = emp.default_operating_unit_id
            if emp.job_grade:
                self.job_grade = emp.job_grade
            if emp.job_position and hasattr(emp.job_position, 'employee_category') and emp.job_position.employee_category:
                self.job_category = emp.job_position.employee_category
            elif emp.job_grade and hasattr(emp.job_grade, 'category') and emp.job_grade.category:
                self.job_category = emp.job_grade.category.category_name
            else:
                self.job_category = 'Non Managerial'

            if not self.requesting_operating_unit and emp.default_operating_unit_id:
                self.requesting_operating_unit = emp.default_operating_unit_id

            if self.acting_position and hasattr(self.acting_position, 'department_id') and self.acting_position.department_id.operating_unit_id:
                self.acting_work_unit = self.acting_position.department_id.operating_unit_id.name
            elif self.requesting_operating_unit:
                self.acting_work_unit = self.requesting_operating_unit.name
            elif emp.default_operating_unit_id:
                self.acting_work_unit = emp.default_operating_unit_id.name

        if (self.employee_name or self.acting_employee) and (self.acting_position or self.job_grade1):
            return self._validate_acting_sequence_warning()

    @api.onchange('employee_name')
    def _onchange_employee_name_info(self):
        if self.employee_name:
            emp = self.employee_name
            if not self.acting_employee:
                self.acting_employee = emp
            self.employee_id = emp.identification_id if hasattr(emp, 'identification_id') else str(emp.id)
            self.current_job_position = emp.job_position
            self.current_work_unit = emp.default_operating_unit_id
            if emp.job_grade:
                self.job_grade = emp.job_grade
            if emp.job_position and hasattr(emp.job_position, 'employee_category') and emp.job_position.employee_category:
                self.job_category = emp.job_position.employee_category
            elif emp.job_grade and hasattr(emp.job_grade, 'category') and emp.job_grade.category:
                self.job_category = emp.job_grade.category.category_name
            else:
                self.job_category = 'Non Managerial'

            if not self.requesting_operating_unit and emp.default_operating_unit_id:
                self.requesting_operating_unit = emp.default_operating_unit_id

        if (self.employee_name or self.acting_employee) and (self.acting_position or self.job_grade1):
            return self._validate_acting_sequence_warning()

    @api.onchange('acting_position')
    def _onchange_acting_position_info(self):
        if self.acting_position:
            pos = self.acting_position
            self.acting_job_position = pos
            if pos.grade:
                self.job_grade1 = pos.grade
            if hasattr(pos, 'employee_category') and pos.employee_category:
                self.job_category1 = pos.employee_category
            elif pos.grade and hasattr(pos.grade, 'category') and pos.grade.category:
                self.job_category1 = pos.grade.category.category_name
            else:
                self.job_category1 = 'Non Managerial'

            if hasattr(pos, 'department_id') and pos.department_id.operating_unit_id:
                self.acting_work_unit = pos.department_id.operating_unit_id.name
            elif self.requesting_operating_unit:
                self.acting_work_unit = self.requesting_operating_unit.name

        if (self.employee_name or self.acting_employee) and (self.acting_position or self.job_grade1):
            return self._validate_acting_sequence_warning()

    def _validate_acting_sequence_warning(self):
        emp_grade = self.job_grade or (self.employee_name.job_grade if self.employee_name else False)
        target_grade = self.job_grade1 or (self.acting_position.grade if self.acting_position else False)
        if emp_grade and target_grade and hasattr(emp_grade, 'is_eligible_acting_grade'):
            if not emp_grade.is_eligible_acting_grade(target_grade):
                curr_code = emp_grade.grade_name or emp_grade.grade_code
                tgt_code = target_grade.grade_name or target_grade.grade_code
                curr_num = emp_grade.get_grade_level_num() if hasattr(emp_grade, 'get_grade_level_num') else 0
                tgt_num = target_grade.get_grade_level_num() if hasattr(target_grade, 'get_grade_level_num') else 0
                msg = _(
                    "Acting Sequence Rule Notice:\n\n"
                    "Employee '%(emp)s' holds %(curr)s (Level %(cl)s), "
                    "which does NOT match the acting sequence for Grade %(tgt)s (Level %(tl)s).\n\n"
                    "Under the Acting Sequence Rules, acting is restricted to the next progression grade(s) "
                    "(e.g., VI ➔ VII/VIII, VII & VIII ➔ IX, IX ➔ X/XI, X ➔ XI/XII). "
                    "Assignments to lower, equal, or multi-step higher grades violate policy."
                ) % {
                    'emp': self.employee_name.name if self.employee_name else '',
                    'curr': curr_code,
                    'cl': curr_num,
                    'tgt': tgt_code,
                    'tl': tgt_num,
                }
                return {
                    'warning': {
                        'title': _("Acting Sequence Warning"),
                        'message': msg,
                    }
                }
        return {}

    @api.constrains('employee_name', 'acting_position', 'job_grade', 'job_grade1')
    def _check_acting_grade_sequence(self):
        for rec in self:
            emp_grade = rec.job_grade or (rec.employee_name.job_grade if rec.employee_name else False)
            target_grade = rec.job_grade1 or (rec.acting_position.grade if rec.acting_position else False)
            if emp_grade and target_grade and hasattr(emp_grade, 'is_eligible_acting_grade'):
                if not emp_grade.is_eligible_acting_grade(target_grade):
                    curr_code = emp_grade.grade_name or emp_grade.grade_code
                    tgt_code = target_grade.grade_name or target_grade.grade_code
                    curr_num = emp_grade.get_grade_level_num() if hasattr(emp_grade, 'get_grade_level_num') else 0
                    tgt_num = target_grade.get_grade_level_num() if hasattr(target_grade, 'get_grade_level_num') else 0
                    raise ValidationError(_(
                        "Invalid Acting Assignment Sequence!\n\n"
                        "Employee '%(emp)s' has substantive Grade %(curr)s (Level %(cl)s), "
                        "which cannot act in vacant position Grade %(tgt)s (Level %(tl)s).\n\n"
                        "The Acting Sequence Rule permits upward progression to any higher job grade up to a maximum of 4 job grades difference "
                        "(e.g., Grade VI can act in Grade VII, VIII, IX, or X). "
                        "Assigning to equal, lower, or more than 4 grades higher is strictly prohibited."
                    ) % {
                        'emp': rec.employee_name.name if rec.employee_name else '',
                        'curr': curr_code,
                        'cl': curr_num,
                        'tgt': tgt_code,
                        'tl': tgt_num,
                    })

    def close_acting_position(self):
        for rec in self:
            rec._revert_to_substantive_position()
            rec.state = "close_acting_position"
            rec.status = "revoked"

            ref, emp_name, vacant_pos, unit = rec._get_summary_info()

            close_msg = (
                f"Dear Colleague,\n\n"
                f"Supplementary / Acting Role {ref} has been CLOSED / REVOKED.\n\n"
                f"Employee {emp_name} has completed the acting role in {vacant_pos} "
                f"and reverted to their substantive position."
            )
            recipients = set(rec._get_stakeholder_partners() + rec._get_hr_partners())
            rec._send_stage_notification(recipients, f"Supplementary Role Closed: {ref}", close_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Acting Position Closed'),
                'message': _('Acting position closed and notifications sent to all stakeholders.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('supplementary.role') or _('New')
            if vals.get('employee_name') and not vals.get('job_grade'):
                emp = self.env['hr.employee'].browse(vals['employee_name'])
                if emp.job_grade:
                    vals['job_grade'] = emp.job_grade.id
            if vals.get('acting_position') and not vals.get('job_grade1'):
                job = self.env['hr.job'].browse(vals['acting_position'])
                if job.grade:
                    vals['job_grade1'] = job.grade.id
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            updates = {}
            if rec.employee_name and not rec.job_grade and rec.employee_name.job_grade:
                updates['job_grade'] = rec.employee_name.job_grade.id
            if rec.acting_position and not rec.job_grade1 and rec.acting_position.grade:
                updates['job_grade1'] = rec.acting_position.grade.id
            if updates:
                super(Supplementary_details, rec).write(updates)
        return res

    def approve(self):
        for rec in self:
            # Record acting role in hr.job.history cleanly via ORM
            emp = rec.employee_name or rec.acting_employee
            if emp:
                try:
                    self.env['hr.job.history'].sudo().create({
                        'employee_id': emp.id,
                        'from_job_id': emp.job_position.id if emp.job_position else False,
                        'to_job_id': rec.acting_position.id if rec.acting_position else (rec.acting_job_position.id if rec.acting_job_position else False),
                        'from_grade_id': emp.job_grade.id if emp.job_grade else False,
                        'to_grade_id': rec.job_grade1.id if rec.job_grade1 else False,
                        'from_operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                        'to_operating_unit_id': rec.requesting_operating_unit.id if rec.requesting_operating_unit else False,
                        'job_history_start_date': rec.start_date,
                        'job_history_end_date': rec.end_date,
                        'reason_for_change': 'acting_role',
                    })
                except Exception as e:
                    _logger.warning("Failed to create acting job history for employee %s: %s", emp.id, e)
            rec._apply_acting_position_to_employee()

            rec.state = "approved"
            rec.status = "approved"

            ref, emp_name, vacant_pos, unit = rec._get_summary_info()
            start_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else 'N/A'
            end_date = rec.end_date.strftime('%Y-%m-%d') if rec.end_date else 'N/A'

            appr_msg = (
                f"Dear Colleague,\n\n"
                f"Supplementary / Acting Role assignment {ref} has been APPROVED.\n\n"
                f"• Employee: {emp_name}\n"
                f"• Acting Position: {vacant_pos}\n"
                f"• Start Date: {start_date}\n"
                f"• End Date: {end_date}\n\n"
                f"The acting position history has been activated in the employee profile."
            )
            recipients = set(rec._get_acting_notification_partners())
            rec._send_stage_notification(recipients, f"Supplementary Role Approved: {ref}", appr_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supplementary Role Approved'),
                'message': _('Supplementary Role approved and notifications sent to all stakeholders.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def populate_benefits(self):
        for rec in self:
            rec.state = "populate_benefits"

            ref, emp_name, vacant_pos, unit = rec._get_summary_info()

            ben_msg = (
                f"Dear Colleague,\n\n"
                f"Benefits have been populated for Supplementary Role {ref} "
                f"({emp_name} acting as {vacant_pos}).\n\n"
                f"Please proceed to calculate Allowance Payouts."
            )
            recipients = set(rec._get_stakeholder_partners() + rec._get_hr_partners())
            rec._send_stage_notification(recipients, f"Supplementary Role Benefits Populated: {ref}", ben_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Benefits Populated'),
                'message': _('Benefits populated successfully and notifications sent.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def populate_acting_Allowance(self):
        for rec in self:
            rec.state = "populate_acting_Allowance"

            ref, emp_name, vacant_pos, unit = rec._get_summary_info()

            allow_msg = (
                f"Dear Colleague,\n\n"
                f"Acting Allowance Payouts have been computed for Supplementary Role {ref} "
                f"({emp_name} acting as {vacant_pos}).\n\n"
                f"The request is ready for final Approval."
            )
            recipients = set(rec._get_stakeholder_partners() + rec._get_hr_partners())
            rec._send_stage_notification(recipients, f"Supplementary Role Allowance Computed: {ref}", allow_msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Allowance Payouts Computed'),
                'message': _('Allowance payouts populated successfully and notifications sent.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }


class job_multi_record(models.Model):
    _name = "hr.supplementary.salary"
    _description = "Supplementary Salary Details"
    _rec_name = "internal_name"
    supplementary_id2 = fields.Many2one('supplementary.role', string="Salary", help='Select corresponding Salary')
    internal_name = fields.Char(string='Internal Name', help='Internal Name')
    old_value = fields.Float("Old Value")
    new_value = fields.Float("New Value")

class job_multi_record_payout(models.Model):
    _name = "hr.supplementary.payout"
    _description = "Supplementary Salary Payout"
    supplementary_id3 = fields.Many2one('supplementary.role', string="Salary", help='Select corresponding Salary')
    hr_period_id = fields.Integer(string="Period Id")
    hr_period_name = fields.Char(string="Payroll Period ")
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    effective_days = fields.Integer(string="Effective Days")
    factor = fields.Float(string="Factor")
    payout_value = fields.Float("Payout")
    status = fields.Boolean("Status")

class SupplementaryDelegation(models.Model):
    _name = "supplementary.delegation.team"
    _description = "Supplementary Delegation Team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Alt. Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    supp_role_del_id = fields.Many2one("supplementary.role", string="Supplementary Delegation Team")


class HrEmployeeSupplementaryInherit(models.Model):
    _inherit = 'hr.employee'

    supplementary_count = fields.Integer(
        string='Supplementary Count',
        compute='_compute_supplementary_count',
    )

    def _compute_supplementary_count(self):
        for employee in self:
            employee.supplementary_count = self.env['supplementary.role'].search_count(
                [('employee_name', '=', employee.id)]
            )
