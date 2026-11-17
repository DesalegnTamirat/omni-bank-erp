# -*- coding: utf-8 -*-

import re
import logging

_logger = logging.getLogger(__name__)
from datetime import datetime, time, timedelta
from math import fabs
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    _description = "Employee information"

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    identification_id = fields.Char(string="Identification ID")
    employee_identification = fields.Char(
        string="Employee Identification",
        help="Employee Id",
        compute="_compute_employee_identification",
        inverse="_inverse_employee_identification",
        store=True,
        readonly=False,
    )
    national_id = fields.Char(string="National Identification Number")
    employee_tin = fields.Char(string="Tax Identification Number (TIN)")

    # Resolve Odoo 19 Access Rights Inconsistency warnings for base hr.employee view elements
    is_user_active = fields.Boolean(groups=False)
    barcode = fields.Char(groups=False)

    # ------------------------------------------------------------------
    # Personal Information Security Access
    # ------------------------------------------------------------------
    can_view_personal_info = fields.Boolean(
        string="Can View Personal Information",
        compute="_compute_can_view_personal_info",
        store=False,
    )

    @api.depends_context('uid')
    def _compute_can_view_personal_info(self):
        has_admin_hr_access = (
            self.env.is_admin()
            or self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_user')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_manager')
        )
        current_uid = self.env.uid
        current_email = (self.env.user.email or '').strip().lower()
        for emp in self:
            if has_admin_hr_access:
                emp.can_view_personal_info = True
            elif emp.user_id and emp.user_id.id == current_uid:
                emp.can_view_personal_info = True
            elif current_email and emp.work_email and emp.work_email.strip().lower() == current_email:
                emp.can_view_personal_info = True
            else:
                emp.can_view_personal_info = False

    def _check_private_fields(self, field_names):
        """Allow employees to view their own private fields without public profile restrictions."""
        has_admin_hr_access = (
            self.env.is_admin()
            or self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_user')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_manager')
        )
        if has_admin_hr_access:
            return
        current_emp_id = self.env.user.employee_id.id
        current_uid = self.env.uid
        current_email = (self.env.user.email or '').strip().lower()
        if self and all(
            emp.id == current_emp_id
            or (emp.user_id and emp.user_id.id == current_uid)
            or (current_email and emp.work_email and emp.work_email.strip().lower() == current_email)
            for emp in self
        ):
            return
        return super()._check_private_fields(field_names)

    def fetch(self, field_names=None):
        """Allow employees to load full employee records when viewing their own profile."""
        if self.browse().has_access('read'):
            return super().fetch(field_names)
        has_admin_hr_access = (
            self.env.is_admin()
            or self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_user')
            or self.env.user.has_group('hr_recruitment.group_hr_recruitment_manager')
        )
        current_emp_id = self.env.user.employee_id.id
        current_uid = self.env.uid
        current_email = (self.env.user.email or '').strip().lower()
        if has_admin_hr_access or (self and all(
            emp.id == current_emp_id
            or (emp.user_id and emp.user_id.id == current_uid)
            or (current_email and emp.work_email and emp.work_email.strip().lower() == current_email)
            for emp in self
        )):
            return super(HrEmployee, self.sudo()).fetch(field_names)
        return super().fetch(field_names)

    # ------------------------------------------------------------------
    # Resignation Fields (Updated from hr_resignation module)
    # ------------------------------------------------------------------
    resignation_status = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('release_date_set', 'Release Date Set'),
        ('handover_completed', 'Handover Completed'),
        ('clearance_in_progress', 'Clearance In Progress'),
        ('cleared', 'Cleared'),
        ('settled', 'Settled'),
        ('completed', 'Completed'),
        ('returned', 'Returned'),
        ('revoked', 'Revoked'),
    ], string="Resignation Status", readonly=True, copy=False, default=False, tracking=True)
    resignation_remarks = fields.Text(string="Resignation Remarks", readonly=True, copy=False, default=False)
    resignation_approved_date = fields.Date(string="Resignation Approved Date", readonly=True, copy=False, default=False)

    work_permit_status = fields.Selection([
        ('none', 'Not Applicable'),
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Work Permit Status', compute='_compute_work_permit_status', store=True)

    age_group = fields.Selection([
        ('under_25', '< 25 Years'),
        ('25_34', '25 - 34 Years'),
        ('35_44', '35 - 44 Years'),
        ('45_54', '45 - 54 Years'),
        ('55_plus', '55+ Years'),
    ], string='Age Group', compute='_compute_demographic_groups', store=True)

    tenure_group = fields.Selection([
        ('under_1', '< 1 Year'),
        ('1_3', '1 - 3 Years'),
        ('3_5', '3 - 5 Years'),
        ('5_10', '5 - 10 Years'),
        ('10_plus', '10+ Years'),
    ], string='Length of Service Group', compute='_compute_demographic_groups', store=True)

    @api.depends('work_permit_expiration_date')
    def _compute_work_permit_status(self):
        today = fields.Date.today()
        for rec in self:
            if not rec.work_permit_expiration_date:
                rec.work_permit_status = 'none'
            elif rec.work_permit_expiration_date < today:
                rec.work_permit_status = 'expired'
            elif (rec.work_permit_expiration_date - today).days <= 30:
                rec.work_permit_status = 'expiring_soon'
            else:
                rec.work_permit_status = 'valid'

    @api.depends('birthday', 'start_date', 'service_start_date', 'first_contract_date', 'age')
    def _compute_demographic_groups(self):
        today = fields.Date.today()
        for rec in self:
            # Age Group
            age_val = False
            if rec.age:
                try:
                    age_val = int(str(rec.age).strip())
                except (ValueError, TypeError):
                    age_val = False
            if not age_val and rec.birthday:
                age_val = relativedelta(today, rec.birthday).years

            if not age_val:
                rec.age_group = False
            elif age_val < 25:
                rec.age_group = 'under_25'
            elif 25 <= age_val <= 34:
                rec.age_group = '25_34'
            elif 35 <= age_val <= 44:
                rec.age_group = '35_44'
            elif 45 <= age_val <= 54:
                rec.age_group = '45_54'
            else:
                rec.age_group = '55_plus'

            # Tenure Group
            join_date = rec.service_start_date or rec.start_date or rec.first_contract_date
            if not join_date:
                rec.tenure_group = False
            else:
                years = relativedelta(today, join_date).years
                if years < 1:
                    rec.tenure_group = 'under_1'
                elif 1 <= years < 3:
                    rec.tenure_group = '1_3'
                elif 3 <= years < 5:
                    rec.tenure_group = '3_5'
                elif 5 <= years < 10:
                    rec.tenure_group = '5_10'
                else:
                    rec.tenure_group = '10_plus'

    @api.constrains('identification_id', 'employee_identification', 'national_id', 'employee_tin')
    def _check_unique_identifications(self):
        for record in self:
            # Enforce unique Employee ID
            emp_id = (record.identification_id or record.employee_identification or '').strip()
            if emp_id:
                duplicate = self.search([
                    ('id', '!=', record.id),
                    '|',
                    ('identification_id', '=', emp_id),
                    ('employee_identification', '=', emp_id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Employee Identification '%s' is already registered for employee '%s'."
                    ) % (emp_id, duplicate.name))

            # Enforce unique National ID Number
            nat_id = (record.national_id or '').strip()
            if nat_id:
                duplicate = self.search([
                    ('id', '!=', record.id),
                    ('national_id', '=', nat_id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "National Identification Number '%s' is already registered for employee '%s'."
                    ) % (nat_id, duplicate.name))

            # Enforce unique Tax Identification Number (TIN)
            tin = (record.employee_tin or '').strip()
            if tin:
                duplicate = self.search([
                    ('id', '!=', record.id),
                    ('employee_tin', '=', tin),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Tax Identification Number (TIN) '%s' is already registered for employee '%s'."
                    ) % (tin, duplicate.name))

    @api.constrains('mobile_phone', 'work_phone', 'phone_num', 'personal_phone', 'alternative_mobile', 'emergency_contact_2_phone')
    def _check_ethiopian_phone_numbers(self):
        for rec in self:
            phones = [
                (rec.mobile_phone, _("Work Mobile")),
                (rec.work_phone, _("Work Phone")),
                (rec.phone_num, _("Personal Phone")),
                (rec.personal_phone, _("Personal Phone")),
                (rec.alternative_mobile, _("Alternate Mobile")),
                (rec.emergency_contact_2_phone, _("Emergency Contact 2 Phone")),
            ]
            for phone_val, label in phones:
                if phone_val:
                    cleaned = re.sub(r'[\s\-\(\)]', '', str(phone_val).strip())
                    if cleaned and not re.match(r'^(\+251|00251|251|0)(9|7|1|2|3|4|5)\d{7,8}$', cleaned):
                        raise ValidationError(_(
                            "Invalid Ethiopian phone number '%s' for %s. "
                            "Please enter a valid Ethiopian phone/mobile number starting with 09, 07, 011, or +251 (e.g. 0911223344, 0711223344, or +251911223344)."
                        ) % (phone_val, label))

    @api.depends('identification_id')
    def _compute_employee_identification(self):
        for emp in self:
            emp.employee_identification = emp.identification_id

    def _inverse_employee_identification(self):
        for emp in self:
            if emp.identification_id != emp.employee_identification:
                emp.identification_id = emp.employee_identification

    @api.onchange('identification_id')
    def _onchange_identification_id_sync(self):
        if self.identification_id != self.employee_identification:
            self.employee_identification = self.identification_id

    @api.onchange('employee_identification')
    def _onchange_employee_identification_sync(self):
        if self.employee_identification != self.identification_id:
            self.identification_id = self.employee_identification

    def _register_hook(self):
        res = super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'hr_employee' 
                      AND column_name IN ('delegated_from_manager_id', 'active_delegation_id');
                """)
                existing = {row[0] for row in self.env.cr.fetchall()}
                if 'delegated_from_manager_id' not in existing:
                    self.env.cr.execute("ALTER TABLE hr_employee ADD COLUMN IF NOT EXISTS delegated_from_manager_id integer;")
                if 'active_delegation_id' not in existing:
                    self.env.cr.execute("ALTER TABLE hr_employee ADD COLUMN IF NOT EXISTS active_delegation_id integer;")
        except Exception:
            pass
        return res

    def _auto_init(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'hr_employee' 
                      AND column_name IN ('delegated_from_manager_id', 'active_delegation_id');
                """)
                existing = {row[0] for row in self.env.cr.fetchall()}
                if 'delegated_from_manager_id' not in existing:
                    self.env.cr.execute("ALTER TABLE hr_employee ADD COLUMN IF NOT EXISTS delegated_from_manager_id integer;")
                if 'active_delegation_id' not in existing:
                    self.env.cr.execute("ALTER TABLE hr_employee ADD COLUMN IF NOT EXISTS active_delegation_id integer;")
        except Exception:
            pass
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE hr_employee
                    SET identification_id = employee_identification
                    WHERE (identification_id IS NULL OR identification_id = '')
                      AND employee_identification IS NOT NULL AND employee_identification != '';
                    UPDATE hr_employee
                    SET employee_identification = identification_id
                    WHERE (employee_identification IS NULL OR employee_identification = '')
                      AND identification_id IS NOT NULL AND identification_id != '';
                """)
        except Exception:
            pass
        return res

    # ------------------------------------------------------------------
    # Contact info
    # ------------------------------------------------------------------
    mobile_phone = fields.Char(string="Work Mobile")
    work_phone = fields.Char(string="Work Phone")
    work_email = fields.Char(string="Work Email")
    private_email = fields.Char(string="Personal Email", groups=False)
    personal_email = fields.Char(string="Alternative Personal Email")
    phone_num = fields.Char(string="Personal Phone")
    personal_phone = fields.Char(string="Alternative Personal Phone")
    alternative_mobile = fields.Char(string='Alternate Mobile')
    emergency_contact_2_name = fields.Char(string="Emergency Contact 2 Name", help="Emergency Contact 2 Name")
    emergency_contact_2_phone = fields.Char(string="Emergency Contact 2 Phone", help="Emergency Contact 2 Phone")
    emergency_contact_relation = fields.Char(string="Emergency Contact Relationship")
    gender = fields.Selection(
        selection=[
            ('male', 'Male'),
            ('female', 'Female'),
        ],
        string='Employee Gender',
        store=True,
    )
    # ------------------------------------------------------------------
    # Address / locality
    # ------------------------------------------------------------------
    nationality = fields.Many2one('res.country', string="Nationality")
    house_number = fields.Char(string="House Number", help="House Number")
    city = fields.Char(string="City", help="City")
    sub_city = fields.Char(string="Sub City", help="Sub City")
    region = fields.Char(string="Region", help="Region")
    woreda = fields.Char(string="Woreda", help="Woreda")
    kebele = fields.Char(string="Kebele", help="Kebele")

    # Marital & Spouse Details
    marital = fields.Selection([
        ('single', 'Single'),
        ('married', 'Married'),
        ('divorced', 'Divorced'),
    ], string='Marital Status')
    marital_status_date = fields.Date(string="Effective Date of Status Change")
    former_spouse_name = fields.Char(string="Former Spouse Full Name")
    is_previously_married = fields.Boolean(
        string='Was Previously Married',
        compute='_compute_is_previously_married',
        store=True,
        readonly=False,
    )

    @api.depends('marital', 'former_spouse_name')
    def _compute_is_previously_married(self):
        for rec in self:
            if rec.marital in ('divorced', 'widower') or rec.former_spouse_name:
                rec.is_previously_married = True
            elif not rec.is_previously_married:
                rec.is_previously_married = False

    divorce_certificate = fields.Binary(string="Divorce Certificate/Document", attachment=True)
    divorce_certificate_filename = fields.Char(string="Divorce Certificate Filename")

    @api.onchange('marital')
    def _onchange_marital_status(self):
        if self.marital and self.marital != 'single':
            self.marital_status_date = fields.Date.today()
        else:
            self.marital_status_date = False

    short_name = fields.Char(string="Short  Name", related='resource_id.name', required=False, store=True,
                             readonly=False)
    father_name = fields.Char(string='Father Name')
    father_name1 = fields.Char(string='Father Name (Alt)')
    grand_father_name = fields.Char(string='Grand Father Name')
    grand_father_name1 = fields.Char(string='Grand Father Name (Alt)')
    mother_name = fields.Char(string="Mother Name")
    mother_name1 = fields.Char(string="Mother Name (Alt)")
    relation_employee = fields.Char(string='Relation with employee', required=False)
    religion = fields.Char(string='Religion', required=False)
    blood_group = fields.Char(string="Blood Group", help="Blood Group")
    any_disabilities = fields.Boolean("Any Disabilities")
    disability_category = fields.Selection([
        ('physical', 'Physical'),
        ('visual', 'Visual'),
        ('hearing', 'Hearing'),
        ('other', 'Other'),
    ], string="Disability Category")
    disability_level = fields.Selection([
        ('mild', 'Mild'),
        ('moderate', 'Moderate'),
        ('severe', 'Severe'),
    ], string="Disability Level")
    disability_details = fields.Char("Disability Details")

    @api.onchange('any_disabilities')
    def _onchange_any_disabilities(self):
        if not self.any_disabilities:
            self.disability_category = False
            self.disability_level = False
            self.disability_details = False
    birthday = fields.Date(string='Date of Birth', groups="base.group_user", tracking=True)
    place_of_birth = fields.Char(string='Place of Birth', groups="base.group_user", tracking=True)
    country_of_birth = fields.Many2one('res.country', string='Country of Birth', groups="base.group_user", tracking=True)
    contact = fields.Char("Contact")
    age = fields.Char(string="Age", compute='_compute_age', inverse='_inverse_age', store=True)
    citizenship_attachment = fields.Binary(string="Citizenship / ID Document", attachment=True)
    citizenship_attachment_filename = fields.Char(string="Citizenship Attachment Filename")

    @api.depends('birthday')
    def _compute_age(self):
        today = fields.Date.today()
        for rec in self:
            if rec.birthday:
                rec.age = str(max(0, relativedelta(today, rec.birthday).years))
            else:
                rec.age = False

    def _inverse_age(self):
        today = fields.Date.today()
        for rec in self:
            if rec.age and str(rec.age).strip().isdigit():
                age_years = int(str(rec.age).strip())
                estimated_birth_year = today.year - age_years
                if not rec.birthday or rec.birthday.year != estimated_birth_year:
                    month = rec.birthday.month if rec.birthday else 1
                    day = min(rec.birthday.day if rec.birthday else 1, 28)
                    rec.birthday = fields.Date.to_date(f"{estimated_birth_year:04d}-{month:02d}-{day:02d}")

    @api.onchange('birthday')
    def _onchange_birthday_compute_age(self):
        if self.birthday:
            today = fields.Date.today()
            age_years = relativedelta(today, self.birthday).years
            self.age = str(max(0, age_years))
        else:
            self.age = False

    @api.onchange('age')
    def _onchange_age_compute_birthday(self):
        if self.age and str(self.age).strip().isdigit():
            today = fields.Date.today()
            age_years = int(str(self.age).strip())
            estimated_birth_year = today.year - age_years
            if not self.birthday or self.birthday.year != estimated_birth_year:
                # Maintain month/day if set, otherwise default to Jan 1st
                month = self.birthday.month if self.birthday else 1
                day = min(self.birthday.day if self.birthday else 1, 28)
                self.birthday = fields.Date.to_date(f"{estimated_birth_year:04d}-{month:02d}-{day:02d}")

    # ------------------------------------------------------------------
    # Active Directory Integration Fields & Provisioning
    # ------------------------------------------------------------------
    ad_username = fields.Char(string="AD Username / sAMAccountName", copy=False, readonly=True)
    ad_upn = fields.Char(string="AD UserPrincipalName", copy=False, readonly=True)
    ad_dn = fields.Char(string="Active Directory DN", copy=False, readonly=True)
    ad_sync_status = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('failed', 'Sync Failed'),
    ], string="AD Sync Status", default='not_synced', copy=False, readonly=True)
    ad_sync_date = fields.Datetime(string="AD Synced On", copy=False, readonly=True)
    ad_sync_error = fields.Text(string="AD Sync Error", copy=False, readonly=True)

    def action_sync_to_ad(self):
        """Trigger Active Directory account provisioning for this employee."""
        self.ensure_one()
        ad_service = self.env['ad.ldap.service'].with_context(force_ad_provision=True)
        result = ad_service.provision_employee(self)

        now = fields.Datetime.now()
        if result.get('success'):
            vals = {
                'ad_username': result.get('username'),
                'ad_upn': result.get('upn'),
                'ad_dn': result.get('dn'),
                'ad_sync_status': 'synced',
                'ad_sync_date': now,
                'ad_sync_error': False,
            }
            if not self.work_email and result.get('mail'):
                vals['work_email'] = result.get('mail')
            self.write(vals)

            msg = _("Active Directory user created successfully:<br/>"
                    "• <b>sAMAccountName:</b> %s<br/>"
                    "• <b>UserPrincipalName:</b> %s<br/>"
                    "• <b>DistinguishedName:</b> %s") % (
                result.get('username'), result.get('upn'), result.get('dn')
            )
            self.message_post(body=msg)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AD Provisioning Succeeded'),
                    'message': _('Account %s created in Active Directory.') % result.get('upn'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            err = result.get('error') or _('Unknown error during AD provisioning.')
            self.write({
                'ad_sync_status': 'failed',
                'ad_sync_date': now,
                'ad_sync_error': err,
            })
            self.message_post(body=_("Active Directory provisioning failed: %s") % err)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AD Provisioning Notice'),
                    'message': err,
                    'type': 'warning',
                    'sticky': True,
                }
            }

    # ------------------------------------------------------------------
    # Languages
    # ------------------------------------------------------------------
    languages = fields.Char(string="Languages (Text)")
    language_ids = fields.Many2many('res.lang', string="Languages")
    languages_ids = fields.One2many('hr.languages', 'employee_id', string='HR Languages', help='Languages Information')


    current_company = fields.Char("Current Company")
    working_status = fields.Char("Working Status")
    willing_to_join_immediately = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Willing to Join Immediately', default='yes')
    date_of_availability = fields.Date("Date of Availability")
    # first_contract_date is a computed field defined in hr_employee_contract.py
    job_name = fields.Char(string="Job Title Name", help="Job Name")
    allowed_job_ids = fields.Many2many(
        'hr.job',
        string='Allowed Job Positions',
        compute='_compute_allowed_job_ids',
    )
    job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position", domain="[('id', 'in', allowed_job_ids)]")

    job_grade = fields.Many2one("employee.grade", string="Job Grade", help="Job Grade")
    department_id = fields.Many2one('hr.department', string='Department')
    operating_unit_ids = fields.Many2many('operating.unit', string="Operating Units")
    default_operating_unit_id = fields.Many2one('operating.unit', string="Default Operating Unit")

    @api.depends('default_operating_unit_id')
    def _compute_allowed_job_ids(self):
        OUJob = self.env['operating.unit.job.position'].sudo()
        HrJob = self.env['hr.job'].sudo()
        for emp in self:
            ou = emp.default_operating_unit_id
            if ou:
                lines = OUJob.search([
                    ('operating_unit_id', '=', ou.id),
                    ('active', '=', True)
                ])
                job_ids = lines.mapped('job_position_id').filtered(lambda j: j.active).ids
                emp.allowed_job_ids = [(6, 0, job_ids)]
            else:
                emp.allowed_job_ids = [(6, 0, HrJob.search([('active', '=', True)]).ids)]

    @api.onchange('default_operating_unit_id')
    def _onchange_default_operating_unit_id_filter_jobs(self):
        if self.default_operating_unit_id:
            lines = self.env['operating.unit.job.position'].sudo().search([
                ('operating_unit_id', '=', self.default_operating_unit_id.id),
                ('active', '=', True)
            ])
            job_ids = lines.mapped('job_position_id').filtered(lambda j: j.active).ids
            if self.job_id and self.job_id.id not in job_ids:
                self.job_id = False
            if getattr(self, 'job_position', False) and self.job_position.id not in job_ids:
                self.job_position = False
            return {'domain': {
                'job_id': [('operating_unit_job_ids.operating_unit_id', '=', self.default_operating_unit_id.id)],
                'job_position': [('operating_unit_job_ids.operating_unit_id', '=', self.default_operating_unit_id.id)],
            }}
        return {'domain': {
            'job_id': [('active', '=', True)],
            'job_position': [('active', '=', True)],
        }}
    start_date = fields.Date(string="Start Date")
    location = fields.Char("Location")
    status = fields.Char("Employee Status")
    remarks = fields.Char("Remarks if any")
    releived_on = fields.Char("Releived on")

    # ------------------------------------------------------------------
    # Probation
    # ------------------------------------------------------------------
    probation_start_date = fields.Date(
        string="Probation Start date",
        help="Probation Start date",
        compute="_compute_probation_start_date",
        store=True,
        readonly=True,
    )
    probation_end_date = fields.Date(
        string="Probation End Date",
        help="Probation End Date",
        compute="_compute_probation_end_date",
        store=True,
        readonly=True,
    )

    probation_period = fields.Integer(
        string="Probation Period",
        compute="_compute_probation_period",
        store=True,
        readonly=True,
    )
    probationary_details = fields.Text(
        string='Probationary Details',
        compute="_compute_probationary_details",
        store=True,
        readonly=True,
    )

    # Category-based probation periods (in days), keyed by the technical
    # value of hr.job.employee_category ('Managerial' / 'Non Managerial').
    _PROBATION_DAYS_BY_CATEGORY = {
        'Managerial': 75,
        'Non Managerial': 60,
    }

    @api.depends("job_position.employee_category", "job_position.probation_period")
    def _compute_probation_period(self):
        for employee in self:
            job = employee.job_position
            category = job.employee_category if job else False
            if category in self._PROBATION_DAYS_BY_CATEGORY:
                employee.probation_period = self._PROBATION_DAYS_BY_CATEGORY[category]
            else:
                # Fallback: no/unrecognized category on the job, use
                # whatever probation_period is set directly on hr.job.
                employee.probation_period = job.probation_period or 0

    @api.depends("service_hire_date")
    def _compute_probation_start_date(self):
        for employee in self:
            employee.probation_start_date = employee.service_hire_date

    @api.depends("probation_start_date", "probation_period")
    def _compute_probation_end_date(self):
        for employee in self:
            if employee.probation_start_date and employee.probation_period:
                employee.probation_end_date = (
                    employee.probation_start_date + timedelta(days=employee.probation_period)
                )
            else:
                employee.probation_end_date = False

    @api.depends("probation_start_date", "probation_end_date", "probation_period")
    def _compute_probationary_details(self):
        for employee in self:
            if employee.probation_start_date and employee.probation_end_date:
                duration = relativedelta(
                    employee.probation_end_date, employee.probation_start_date
                )
                parts = []
                if duration.years:
                    parts.append(_("%s year(s)") % duration.years)
                if duration.months:
                    parts.append(_("%s month(s)") % duration.months)
                if duration.days:
                    parts.append(_("%s day(s)") % duration.days)
                duration_str = ", ".join(parts) if parts else _("0 days")
                employee.probationary_details = _("Probation period: %s, from %s to %s") % (
                    duration_str,
                    employee.probation_start_date.strftime("%b %d, %Y"),
                    employee.probation_end_date.strftime("%b %d, %Y"),
                )
            else:
                employee.probationary_details = False

    # ------------------------------------------------------------------
    # Pension
    # ------------------------------------------------------------------
    pension_number = fields.Char(string="Pension Number", help="Pension Number")
    pension_no = fields.Char("Pension No")


    payroll_status = fields.Integer(string="Payroll Status")
    info_section = fields.Selection([
        ('insurance', 'Insurance'),
        ('pension', 'Pension')
    ], string='Information Section')
    validation_state = fields.Selection([
        ('draft', 'Draft'),
        ('Under_review', 'Under Review'),
        ('approved', 'Approved')
    ], string="Employee Data Validation State", default='Under_review')
    entry_progress = fields.Integer(string="Entry Progress", default=0)
    exit_progress = fields.Integer(string="Exit Progress", default=0)

    # ------------------------------------------------------------------
    # Hierarchy / management
    # ------------------------------------------------------------------
    hr_officer_id = fields.Many2one('res.users', string="HR Officer Assigned")
    alternate_parent = fields.Integer(string="Incharge Manager Partner ID")
    alternate_manager = fields.Integer(string="Incharge Manager")
    planning_parent_partner_id = fields.Integer()

    planning_parent_id = fields.Many2one(
        'hr.employee',
        string="Planning Parent",
        compute='_compute_planning_parent',
        store=True,
        readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    delegated_from_manager_id = fields.Many2one(
        'hr.employee',
        string="Delegated From Manager",
        help="Original manager prior to active delegation",
    )
    active_delegation_id = fields.Many2one(
        'hr.employee.delegation',
        string="Active Delegation Record",
        help="Currently active delegation affecting this employee's hierarchy",
    )

    @api.onchange('department_id')
    def _onchange_department_id_sync_manager(self):
        if self.department_id:
            dept = self.department_id
            mgr = dept.manager_id or (dept.parent_id.manager_id if dept.parent_id else False)
            if mgr and mgr.id != self.id:
                self.parent_id = mgr
                self.coach_id = mgr
                self.planning_parent_id = mgr

    @api.onchange('parent_id')
    def _onchange_parent_id_sync_hierarchy(self):
        val = self.parent_id
        self.coach_id = val
        self.planning_parent_id = val

    @api.onchange('coach_id')
    def _onchange_coach_id_sync_hierarchy(self):
        val = self.coach_id
        self.parent_id = val
        self.planning_parent_id = val

    @api.onchange('planning_parent_id')
    def _onchange_planning_parent_id_sync_hierarchy(self):
        val = self.planning_parent_id
        self.parent_id = val
        self.coach_id = val

    @api.model
    def _resolve_workunit_manager_and_department(self, operating_unit, job_position=False, employee=False):
        """Resolve the appropriate department and reporting manager for a given operating unit.
        Returns: (department_id, manager_id)
        """
        if not operating_unit:
            return False, False

        # 1. Resolve Department
        dept = False
        if job_position and getattr(job_position, 'department_id', False):
            dept = job_position.department_id
        elif getattr(operating_unit, 'department', False):
            dept = operating_unit.department

        if not dept:
            dept = self.env['hr.department'].sudo().search([('operating_unit_id', '=', operating_unit.id)], limit=1)
        if not dept:
            dept = self.env['hr.department'].sudo().search([('name', '=ilike', operating_unit.name)], limit=1)
        if not dept and getattr(operating_unit, 'parent_unit', False):
            dept = operating_unit.parent_unit.department or self.env['hr.department'].sudo().search([('operating_unit_id', '=', operating_unit.parent_unit.id)], limit=1)

        # 2. Resolve Manager
        emp_id = employee.id if employee else (self.id if len(self) == 1 else False)
        mgr = False

        if getattr(operating_unit, 'manager_id', False) and operating_unit.manager_id.id != emp_id:
            mgr = operating_unit.manager_id

        if not mgr:
            domain = [('default_operating_unit_id', '=', operating_unit.id), ('active', '=', True)]
            if emp_id:
                domain.append(('id', '!=', emp_id))
            ou_emps = self.env['hr.employee'].sudo().search(domain)

            directors = []
            team_leads = []
            for e in ou_emps:
                j_name = (e.job_id.name or e.job_title or (e.job_position.name if getattr(e, 'job_position', False) else '') or '').lower()
                if any(k in j_name for k in ('director', 'chief', 'district manager', 'branch manager')):
                    directors.append(e)
                elif any(k in j_name for k in ('team leader', 'team lead', 'division manager', 'head', 'supervisor', 'manager')):
                    team_leads.append(e)

            if job_position and team_leads:
                jp_name = (getattr(job_position, 'name', '') or '').lower()
                jp_tokens = set([w for w in jp_name.replace('-', ' ').replace(',', ' ').replace('(', ' ').replace(')', ' ').split()
                                 if len(w) > 3 and w not in ('senior', 'principal', 'junior', 'officer', 'expert', 'lead', 'team', 'division')])
                for tl in team_leads:
                    tl_name = (tl.job_id.name or tl.job_title or (tl.job_position.name if getattr(tl, 'job_position', False) else '') or '').lower()
                    tl_tokens = set([w for w in tl_name.replace('-', ' ').replace(',', ' ').replace('(', ' ').replace(')', ' ').split()
                                     if len(w) > 3 and w not in ('senior', 'principal', 'junior', 'officer', 'expert', 'lead', 'team', 'division')])
                    if jp_tokens.intersection(tl_tokens):
                        mgr = tl
                        break

            if not mgr and directors:
                mgr = directors[0]
                if not operating_unit.manager_id:
                    try:
                        operating_unit.sudo().write({'manager_id': mgr.id})
                    except Exception:
                        pass
            elif not mgr and team_leads:
                mgr = team_leads[0]
                if not operating_unit.manager_id:
                    try:
                        operating_unit.sudo().write({'manager_id': mgr.id})
                    except Exception:
                        pass

        if not mgr and dept and getattr(dept, 'manager_id', False) and dept.manager_id.id != emp_id:
            mgr = dept.manager_id

        if not mgr and getattr(operating_unit, 'parent_unit', False):
            parent_ou = operating_unit.parent_unit
            if getattr(parent_ou, 'manager_id', False) and parent_ou.manager_id.id != emp_id:
                mgr = parent_ou.manager_id
            else:
                p_domain = [('default_operating_unit_id', '=', parent_ou.id), ('active', '=', True)]
                if emp_id:
                    p_domain.append(('id', '!=', emp_id))
                p_lead = self.env['hr.employee'].sudo().search(p_domain, limit=1)
                if p_lead:
                    mgr = p_lead

        return dept, mgr

    @api.onchange('default_operating_unit_id')
    def _onchange_default_operating_unit_sync_manager(self):
        """When the employee's work unit changes, automatically update the
        department and reporting manager (parent_id / coach_id / planning_parent_id)
        to the appropriate department and leadership for the new operating unit.
        """
        new_ou = self.default_operating_unit_id
        if not new_ou:
            return
        emp_origin = self._origin if self._origin else self
        job_pos = self.job_id or self.job_position
        dept, mgr = self._resolve_workunit_manager_and_department(new_ou, job_pos, emp_origin)
        if dept:
            self.department_id = dept
        if mgr and mgr.id != emp_origin.id:
            self.parent_id = mgr
            self.coach_id = mgr
            if hasattr(self, 'planning_parent_id'):
                self.planning_parent_id = mgr

    @api.onchange('parent_id')
    def _onchange_parent_sync_operating_unit(self):
        """When the manager (parent_id) is changed directly, update
        default_operating_unit_id to the operating unit that the new manager
        manages — but only if the new manager is the registered manager_id of
        exactly one operating unit AND the operating unit hasn't already been
        set to match.  This avoids overwriting intentional unit selections when
        the manager runs multiple units.
        """
        new_manager = self.parent_id
        if not new_manager:
            return
        # Find operating units where this employee is the manager
        managed_units = self.env['operating.unit'].search(
            [('manager_id', '=', new_manager.id), ('active', '=', True)],
            limit=2,
        )
        if len(managed_units) == 1:
            # Only auto-assign when unambiguous (manager runs exactly one unit)
            if self.default_operating_unit_id != managed_units:
                self.default_operating_unit_id = managed_units[0]

    @api.depends('parent_id', 'coach_id')
    def _compute_planning_parent(self):
        for employee in self:
            if employee.parent_id:
                employee.planning_parent_id = employee.parent_id
                employee.coach_id = employee.parent_id
            elif employee.coach_id:
                employee.planning_parent_id = employee.coach_id
                employee.parent_id = employee.coach_id
            elif employee.planning_parent_id:
                employee.parent_id = employee.planning_parent_id
                employee.coach_id = employee.planning_parent_id
            else:
                employee.planning_parent_id = False
                employee.coach_id = False

    @api.model
    def _sync_hr_coach_group(self):
        """Automatically grant/revoke group_hr_coach for users whose employee is a coach_id of active employees."""
        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return
        try:
            with self.env.cr.savepoint():
                coach_group = self.env.ref('hr_employee_custom.group_hr_coach', raise_if_not_found=False)
                if not coach_group:
                    return

                self.env.cr.execute("""
                    SELECT DISTINCT coach.user_id
                    FROM hr_employee sub
                    JOIN hr_employee coach ON (coach.id = sub.coach_id OR coach.id = sub.parent_id)
                    WHERE sub.active = TRUE AND coach.active = TRUE AND coach.user_id IS NOT NULL;
                """)
                rows = self.env.cr.fetchall()
                coach_user_ids = set(r[0] for r in rows if r[0])

                current_coach_users = set(coach_group.user_ids.ids)

                users_to_add = coach_user_ids - current_coach_users
                users_to_remove = current_coach_users - coach_user_ids

                if users_to_add:
                    coach_group.sudo().write({'user_ids': [(4, uid) for uid in users_to_add]})
                if users_to_remove:
                    admin_ids = {1, 2}
                    removable = users_to_remove - admin_ids
                    if removable:
                        coach_group.sudo().write({'user_ids': [(3, uid) for uid in removable]})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Related record lines (One2many)
    # ------------------------------------------------------------------
    Supplementary_ids = fields.One2many('supplementary.multi.role', 'employee_id', string='supplementary Role',
                                        help='supplementary Role Information')
    fam_ids = fields.One2many('hr.employee.family', 'employee_id', string='Family', help='Family Information')
    part_time_ids = fields.One2many('part.time.employment', 'employee_id', string='Part Time Employment',
                                    help='Part Time Employment Information')
    edu_ids = fields.One2many('hr.employee.education', 'employee_id', string='Education', help='Education Information')
    due_ids = fields.One2many('hr.due', 'employee_id', string='Third Party Dues', help='Dues Information')
    gurentee_ids = fields.One2many('guarentees.details', 'employee_id', string='Guarantee',
                                   help='gurentees Role Information')

    award_ids = fields.One2many('hr.awards', 'employee_id', string='Awards Received',
                                help='Awards Received Information')
    award_count = fields.Integer(string='Award Count', compute='_compute_award_count')
    bank_ids = fields.One2many('bank.info', 'employee_id', string='Bank Info', help='Bank Information')
    pension_info = fields.One2many("pension.multi.record", 'employee_id', string="Pension Information",
                                   help='Pension Information')
    sponsorship_info = fields.One2many("education.fee.sponsorship", 'sponsorship_id',
                                       string=" Education Fee Sponsorship", help=' Education Fee Sponsorship')
    commitment_info = fields.One2many("training.commitment", 'commitment_id', string="Training Commitment",
                                      help=' Training Commitment')

    qualification_id = fields.One2many('hr_qualification_info_job', 'employee_id', 'Education Qualification')
    experiance_id = fields.One2many('hr_experience_info_job', 'employee_id', 'Experiance')
    competencies_id = fields.One2many('hr_competencies_info_job', 'employee_id', 'Competencies')

    # From employee_fields_application (hr_employee_hrMaster.py)
    responsible_user_id = fields.Many2one('res.users', "Responsible", default=lambda self: self.env.uid)

    # ------------------------------------------------------------------
    # Recruitment Criteria Synchronization
    # ------------------------------------------------------------------
    def _sync_identification_vals(self, vals):
        if 'identification_id' in vals and 'employee_identification' not in vals:
            vals['employee_identification'] = vals['identification_id']
        elif 'employee_identification' in vals and 'identification_id' not in vals:
            vals['identification_id'] = vals['employee_identification']
        elif 'identification_id' in vals and 'employee_identification' in vals:
            val = vals.get('identification_id') or vals.get('employee_identification')
            vals['identification_id'] = val
            vals['employee_identification'] = val

    def _sync_hierarchy_vals(self, vals):
        self._sync_identification_vals(vals)
        emp_ids = self.ids if self else []

        # 1. Operating Unit manager takes precedence
        if 'default_operating_unit_id' in vals and vals.get('default_operating_unit_id'):
            ou = self.env['operating.unit'].browse(vals['default_operating_unit_id'])
            if ou.manager_id:
                if ou.manager_id.id not in emp_ids:
                    # Regular staff in this unit report to the unit manager
                    vals['parent_id'] = ou.manager_id.id
                    vals['coach_id'] = ou.manager_id.id
                    vals['planning_parent_id'] = ou.manager_id.id
                elif ou.parent_unit and ou.parent_unit.manager_id and ou.parent_unit.manager_id.id not in emp_ids:
                    # Unit manager reports to parent unit manager
                    vals['parent_id'] = ou.parent_unit.manager_id.id
                    vals['coach_id'] = ou.parent_unit.manager_id.id
                    vals['planning_parent_id'] = ou.parent_unit.manager_id.id

        # 2. Fallback to department manager only if OU manager not set and parent_id not provided
        elif 'department_id' in vals and vals['department_id'] and 'parent_id' not in vals and 'coach_id' not in vals and 'planning_parent_id' not in vals:
            dept = self.env['hr.department'].browse(vals['department_id'])
            mgr = dept.manager_id or (dept.parent_id.manager_id if dept.parent_id else False)
            if mgr and mgr.id not in emp_ids:
                vals['parent_id'] = mgr.id
                vals['coach_id'] = mgr.id
                vals['planning_parent_id'] = mgr.id

        if 'parent_id' in vals and vals['parent_id']:
            vals['coach_id'] = vals['parent_id']
            vals['planning_parent_id'] = vals['parent_id']
        elif 'planning_parent_id' in vals and vals['planning_parent_id']:
            vals['parent_id'] = vals['planning_parent_id']
            vals['coach_id'] = vals['planning_parent_id']
        elif 'coach_id' in vals and vals['coach_id']:
            vals['parent_id'] = vals['coach_id']
            vals['planning_parent_id'] = vals['coach_id']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sync_hierarchy_vals(vals)
        if self.env.context.get('in_sync_criteria_from_job'):
            return super().create(vals_list)
        employees = super().create(vals_list)
        employees.with_context(in_sync_criteria_from_job=True)._sync_criteria_from_job()
        # Sync coach security group whenever a new employee with a coach/parent is created
        coach_fields = {'coach_id', 'parent_id'}
        if any(f in (vals_list[0] if vals_list else {}) for f in coach_fields):
            self._sync_hr_coach_group()

        # Notify POMD Operating Unit Manager(s) on New Employee Creation
        for emp in employees:
            emp._notify_pomd_manager_on_creation()

        # Automatically provision new employee into Active Directory (OU=newusers)
        for emp in employees:
            if not self.env.context.get('skip_ad_provision'):
                try:
                    ad_service = self.env['ad.ldap.service'].with_context(force_ad_provision=True)
                    result = ad_service.provision_employee(emp)
                    now = fields.Datetime.now()
                    if result.get('success'):
                        vals_ad = {
                            'ad_username': result.get('username'),
                            'ad_upn': result.get('upn'),
                            'ad_dn': result.get('dn'),
                            'ad_sync_status': 'synced',
                            'ad_sync_date': now,
                            'ad_sync_error': False,
                        }
                        if not emp.work_email and result.get('mail'):
                            vals_ad['work_email'] = result.get('mail')
                        emp.sudo().write(vals_ad)
                        msg = _("Active Directory user automatically provisioned in newusers:<br/>"
                                "• <b>Username:</b> %s<br/>"
                                "• <b>UPN:</b> %s<br/>"
                                "• <b>DN:</b> %s") % (
                            result.get('username'), result.get('upn'), result.get('dn')
                        )
                        emp.message_post(body=msg)
                    else:
                        emp.sudo().write({
                            'ad_sync_status': 'failed',
                            'ad_sync_error': result.get('error'),
                        })
                        _logger.warning("Auto AD provision failed for %s: %s", emp.name, result.get('error'))
                except Exception as ad_err:
                    _logger.warning("Auto AD provision error for %s: %s", emp.name, ad_err)

        return employees
    def _notify_pomd_manager_on_creation(self):
        """
        Notify the manager(s) of People Operation Management Directorate operating unit
        via Discuss and email/Outlook when a new employee is created.
        """
        ou = self.env['operating.unit'].sudo().search([
            ('name', 'ilike', 'People Operation Management Directorate')
        ], limit=1)

        recipient_partners = self.env['res.partner']
        recipient_emails = set()

        if ou:
            if ou.manager_id and ou.manager_id.work_contact_id:
                recipient_partners |= ou.manager_id.work_contact_id
                if ou.manager_id.work_email:
                    recipient_emails.add(ou.manager_id.work_email.strip())
            elif ou.manager_id and ou.manager_id.user_id and ou.manager_id.user_id.partner_id:
                recipient_partners |= ou.manager_id.user_id.partner_id
                if ou.manager_id.work_email:
                    recipient_emails.add(ou.manager_id.work_email.strip())

            # Find managers / directors assigned to this operating unit
            ou_leaders = self.env['hr.employee'].sudo().search([
                ('default_operating_unit_id', '=', ou.id),
                '|', ('job_title', 'ilike', 'director'), ('job_title', 'ilike', 'manager')
            ])
            for leader in ou_leaders:
                if leader.work_contact_id:
                    recipient_partners |= leader.work_contact_id
                elif leader.user_id and leader.user_id.partner_id:
                    recipient_partners |= leader.user_id.partner_id
                if leader.work_email:
                    recipient_emails.add(leader.work_email.strip())

            # Also include direct users linked to the operating unit
            for u in ou.user_ids:
                if u.partner_id:
                    recipient_partners |= u.partner_id
                if u.email:
                    recipient_emails.add(u.email.strip())

        # System parameter fallback
        pomd_param = self.env['ir.config_parameter'].sudo().get_param('hr.pomd_manager_partner_id')
        if pomd_param and pomd_param.isdigit():
            p = self.env['res.partner'].sudo().browse(int(pomd_param))
            if p.exists():
                recipient_partners |= p
                if p.email:
                    recipient_emails.add(p.email.strip())

        # Fallback to HR managers group if no specific recipient resolved
        if not recipient_partners and not recipient_emails:
            hr_manager_group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
            if hr_manager_group:
                for u in hr_manager_group.users:
                    if u.partner_id:
                        recipient_partners |= u.partner_id
                    if u.email:
                        recipient_emails.add(u.email.strip())

        for emp in self:
            subject = f"New Employee Created: {emp.name} ({emp.employee_identification or emp.identification_id or 'New'})"
            body = f"""
            <div style="font-family: Arial, sans-serif; font-size: 13px; color: #333333; line-height: 1.5;">
                <p>Dear Manager,</p>
                <p>A new employee record has been created in the HR Employee Master:</p>
                <table style="border-collapse: collapse; width: 100%; max-width: 500px; margin-top: 10px; margin-bottom: 15px;">
                    <tr><td style="padding: 4px 8px; font-weight: bold; width: 35%;">Employee Name:</td><td style="padding: 4px 8px;">{emp.name}</td></tr>
                    <tr><td style="padding: 4px 8px; font-weight: bold;">Employee ID:</td><td style="padding: 4px 8px;">{emp.employee_identification or emp.identification_id or 'N/A'}</td></tr>
                    <tr><td style="padding: 4px 8px; font-weight: bold;">Job Position:</td><td style="padding: 4px 8px;">{emp.job_id.name if emp.job_id else (emp.job_title or 'N/A')}</td></tr>
                    <tr><td style="padding: 4px 8px; font-weight: bold;">Department:</td><td style="padding: 4px 8px;">{emp.department_id.name or 'N/A'}</td></tr>
                    <tr><td style="padding: 4px 8px; font-weight: bold;">Operating Unit:</td><td style="padding: 4px 8px;">{emp.default_operating_unit_id.name or 'N/A'}</td></tr>
                    <tr><td style="padding: 4px 8px; font-weight: bold;">Created By:</td><td style="padding: 4px 8px;">{self.env.user.name}</td></tr>
                </table>
                <p>Regards,<br/>Bunna Bank HR System</p>
            </div>
            """
            # Discuss notification
            if recipient_partners:
                try:
                    emp.sudo().message_post(
                        body=body,
                        subject=subject,
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                        partner_ids=recipient_partners.ids,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Discuss notification failed on employee %s: %s", emp.id, e)

            # Outlook / Email notification
            valid_emails = [em for em in recipient_emails if em and '@' in em]
            for email in valid_emails:
                try:
                    self.env['mail.mail'].sudo().create({
                        'subject': subject,
                        'body_html': body,
                        'email_to': email,
                        'email_from': self.env.user.email or self.env.company.email or 'noreply@bunnabank.com',
                        'auto_delete': False,
                    }).send()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Email notification failed to %s on employee %s: %s", email, emp.id, e)


    def write(self, vals):
        # If moving away from an operating unit that this employee managed, clear manager_id on that old unit
        if 'default_operating_unit_id' in vals and not self.env.context.get('_in_ou_hierarchy_sync'):
            new_ou_id = vals.get('default_operating_unit_id')
            ctx = dict(self.env.context, _in_ou_hierarchy_sync=True)
            for emp in self:
                old_ou = emp.default_operating_unit_id
                if old_ou and old_ou.id != new_ou_id and old_ou.manager_id.id == emp.id:
                    old_ou.with_context(ctx).write({'manager_id': False})

        # When default_operating_unit_id changes, auto-resolve department and manager if not provided
        if 'default_operating_unit_id' in vals and not self.env.context.get('_in_ou_workunit_sync'):
            new_ou_id = vals.get('default_operating_unit_id')
            if new_ou_id and len(self) == 1:
                new_ou = self.env['operating.unit'].browse(new_ou_id)
                if new_ou.exists():
                    emp = self[0]
                    job_pos = (self.env['hr.job'].browse(vals['job_id']) if 'job_id' in vals and vals['job_id']
                               else (self.env['hr.job'].browse(vals['job_position']) if 'job_position' in vals and vals['job_position']
                               else (emp.job_id or emp.job_position)))
                    dept, mgr = self._resolve_workunit_manager_and_department(new_ou, job_pos, emp)
                    if dept and 'department_id' not in vals:
                        vals['department_id'] = dept.id
                    if mgr and mgr.id != emp.id:
                        if 'parent_id' not in vals:
                            vals['parent_id'] = mgr.id
                        if 'coach_id' not in vals:
                            vals['coach_id'] = mgr.id
                        if 'planning_parent_id' not in vals and hasattr(emp, 'planning_parent_id'):
                            vals['planning_parent_id'] = mgr.id

        self._sync_hierarchy_vals(vals)
        if self.env.context.get('in_sync_criteria_from_job'):
            return super().write(vals)
        res = super().write(vals)

        # Synchronize version_id with the new workunit, department, job, and wage
        if any(f in vals for f in ('default_operating_unit_id', 'department_id', 'job_id', 'job_position', 'job_grade', 'grade')):
            for emp in self:
                if hasattr(emp, 'version_id') and emp.version_id:
                    v_vals = {}
                    if emp.default_operating_unit_id and 'operating_unit_id' in emp.version_id._fields:
                        if emp.version_id.operating_unit_id != emp.default_operating_unit_id:
                            v_vals['operating_unit_id'] = emp.default_operating_unit_id.id
                    if emp.department_id and 'department_id' in emp.version_id._fields:
                        if emp.version_id.department_id != emp.department_id:
                            v_vals['department_id'] = emp.department_id.id
                    if (emp.job_id or emp.job_position) and 'job_id' in emp.version_id._fields:
                        cur_job = emp.job_id or emp.job_position
                        if emp.version_id.job_id != cur_job:
                            v_vals['job_id'] = cur_job.id
                    if (emp.job_grade or emp.grade) and 'job_grade' in emp.version_id._fields:
                        cur_grade = emp.job_grade or emp.grade
                        if emp.version_id.job_grade != cur_grade:
                            v_vals['job_grade'] = cur_grade.id
                    if v_vals:
                        try:
                            emp.version_id.sudo().write(v_vals)
                        except Exception as e:
                            _logger.warning('Could not sync version_id for employee %s: %s', emp.id, e)

        # If transferred to a branch without a manager and employee is a Branch Manager, auto-assign as manager
        if 'default_operating_unit_id' in vals and not self.env.context.get('_in_ou_hierarchy_sync'):
            new_ou_id = vals.get('default_operating_unit_id')
            if new_ou_id:
                new_ou = self.env['operating.unit'].browse(new_ou_id)
                if new_ou.exists() and new_ou.work_unit_type == 'branch' and not new_ou.manager_id:
                    ctx = dict(self.env.context, _in_ou_hierarchy_sync=True)
                    for emp in self:
                        job_name = (emp.job_id.name or (emp.job_position.name if emp.job_position else '') or '')
                        if 'branch manager' in job_name.lower():
                            new_ou.with_context(ctx).write({'manager_id': emp.id})
                            break

        if 'job_id' in vals or 'job_position' in vals:
            self.with_context(in_sync_criteria_from_job=True)._sync_criteria_from_job()
        # Sync coach security group whenever coach_id or parent_id changes
        if 'coach_id' in vals or 'parent_id' in vals or 'active' in vals:
            self._sync_hr_coach_group()

        # Automatically disable/enable employee in Active Directory when archived/unarchived
        if 'active' in vals:
            if not vals['active']:
                for emp in self:
                    try:
                        self.env['ad.ldap.service'].disable_employee(emp)
                    except Exception as ad_err:
                        _logger.warning("Could not auto-disable AD user on employee archive for %s: %s", emp.name, ad_err)
            else:
                for emp in self:
                    try:
                        self.env['ad.ldap.service'].enable_employee(emp)
                    except Exception as ad_err:
                        _logger.warning("Could not auto-enable AD user on employee unarchive for %s: %s", emp.name, ad_err)

        return res

    @api.onchange('job_id', 'job_position', 'edu_ids', 'education_detail_ids', 'previous_occupation_ids')
    def _onchange_job_position_sync_criteria(self):
        """Automatically populate recruitment criteria when job position or education records change."""
        self._sync_criteria_from_job()

    def action_sync_recruitment_criteria(self):
        """Method retained for view compatibility."""
        self._sync_criteria_from_job(force=True)
        return True

    def _sync_criteria_from_job(self, force=False):
        """Helper to copy qualification, experience, and competency criteria from Job to Employee,
        and sync education qualifications directly from Employee Education tables."""
        for employee in self:
            job = employee.job_id or employee.job_position

            # Collect education responses from hr.employee.education (edu_ids) & employee.education (education_detail_ids)
            edu_responses = {}
            for edu in employee.edu_ids:
                q_name = False
                if edu.qualification and edu.specialization:
                    q_name = f"{edu.qualification.strip()} - {edu.specialization.strip()}"
                elif edu.qualification:
                    q_name = edu.qualification.strip()
                elif edu.specialization:
                    q_name = edu.specialization.strip()

                if q_name:
                    edu_responses[q_name.lower()] = (q_name, edu.cgpa_percentage or 0.0)

            for edu in employee.education_detail_ids:
                q_name = (edu.qualification or edu.field or (dict(edu._fields['edu_type'].selection).get(edu.edu_type) if edu.edu_type else False))
                if q_name:
                    q_name_str = str(q_name).strip()
                    edu_responses[q_name_str.lower()] = (q_name_str, edu.CGPA or 0.0)

            # 1. Qualifications from Job Position
            if job:
                existing_qual_ids = set(employee.qualification_id.mapped('qualification.id'))
                qual_cmds = []
                for q in job.qualification_id:
                    if q.qualification:
                        q_name_str = getattr(q.qualification, 'display_name', False) or getattr(q.qualification, 'qualification', False) or ''
                        q_name = q_name_str.strip().lower() if q_name_str else ''
                        resp = edu_responses.get(q_name, (None, q.response))[1]
                        if force or q.qualification.id not in existing_qual_ids:
                            if q.qualification.id in existing_qual_ids and force:
                                continue
                            qual_cmds.append((0, 0, {
                                'qualification': q.qualification.id,
                                'requirement': q.requirement,
                                'response': resp,
                                'smart_search': q.smart_search or 'yes',
                            }))
                if qual_cmds:
                    employee.qualification_id = qual_cmds

            # 1b. Qualifications directly from Employee Education tables
            for qual_key, (display_name, cgpa_val) in edu_responses.items():
                rec_qual = self.env['recruitment.qualification'].search(['|', ('display_name', '=ilike', display_name), ('qualification', '=ilike', display_name)], limit=1)
                if not rec_qual:
                    rec_qual = self.env['recruitment.qualification'].create({'qualification': display_name})

                existing_eq = employee.qualification_id.filtered(lambda r: r.qualification and r.qualification.id == rec_qual.id)
                if existing_eq:
                    for eq in existing_eq:
                        eq.response = cgpa_val
                else:
                    employee.qualification_id = [(0, 0, {
                        'qualification': rec_qual.id,
                        'requirement': 0.0,
                        'response': cgpa_val,
                        'smart_search': 'yes',
                    })]

            # 2. Experience from Job Position or Previous History
            total_prev_years = sum(po.duration_years for po in employee.previous_occupation_ids)
            banking_prev_years = sum(po.duration_years for po in employee.previous_occupation_ids if po.banking_experience or po.experience_type == 'banking')

            start_d = employee.start_date or employee.first_contract_date
            co_years = 0.0
            if start_d:
                co_days = (fields.Date.today() - start_d).days
                if co_days > 0:
                    co_years = round(co_days / 365.25, 2)

            calc_total_years = round(total_prev_years + co_years, 2)
            calc_banking_years = round(banking_prev_years + co_years, 2)

            existing_exp_map = {e.experience.id: e for e in employee.experiance_id if e.experience}
            exp_cmds = []

            job_exp_lines = job.experiance_id if job else self.env['hr_experience_info_job']
            for e in job_exp_lines:
                if e.experience:
                    exp_name = (getattr(e.experience, 'display_name', False) or getattr(e.experience, 'experience', False) or '').lower()
                    resp_val = calc_banking_years if 'bank' in exp_name else calc_total_years

                    if e.experience.id in existing_exp_map:
                        existing_exp_map[e.experience.id].response = resp_val
                    else:
                        exp_cmds.append((0, 0, {
                            'experience': e.experience.id,
                            'requirement': e.requirement,
                            'response': resp_val,
                            'smart_search': e.smart_search or 'yes',
                        }))

            # If job position has no experience criteria, populate standard criteria if empty
            if not job_exp_lines and not employee.experiance_id:
                std_exp = self.env['recruitment.experience'].search([('status', '=', 'yes')], limit=2)
                for s_exp in std_exp:
                    exp_name = (getattr(s_exp, 'display_name', False) or getattr(s_exp, 'experience', False) or '').lower()
                    resp_val = calc_banking_years if 'bank' in exp_name else calc_total_years
                    exp_cmds.append((0, 0, {
                        'experience': s_exp.id,
                        'requirement': 0.0,
                        'response': resp_val,
                        'smart_search': 'yes',
                    }))

            if exp_cmds:
                employee.experiance_id = exp_cmds

            # 3. Competencies from Job Position (combining direct job competencies & Competency Management Module matrix)
            if job:
                existing_comp_ids = set(employee.competencies_id.mapped('competencies.id'))
                comp_cmds = []

                # 3a. Direct competencies on job position (hr_competencies_info_job)
                for c in job.competencies_id:
                    if c.competencies and (force or c.competencies.id not in existing_comp_ids):
                        if c.competencies.id in existing_comp_ids and force:
                            continue
                        existing_comp_ids.add(c.competencies.id)
                        comp_cmds.append((0, 0, {
                            'competencies': c.competencies.id,
                            'required_level': getattr(c, 'required_level', 'intermediate') or 'intermediate',
                            'requirement': c.requirement or (c.required_level.capitalize() if getattr(c, 'required_level', False) else 'Intermediate'),
                            'response': c.response,
                            'smart_search': c.smart_search or 'yes',
                        }))

                # 3b. Competencies from Competency Management Module (competency.role.mapping)
                if hasattr(job, 'get_required_competencies'):
                    try:
                        req_comps = job.get_required_competencies()
                        level_map = {'1': 'basic', '2': 'intermediate', '3': 'advanced', '4': 'expert'}
                        for comp_data in req_comps:
                            comp_id = comp_data.get('competency_id')
                            if comp_id and (force or comp_id not in existing_comp_ids):
                                if comp_id in existing_comp_ids and force:
                                    continue
                                existing_comp_ids.add(comp_id)
                                prof_lvl = str(comp_data.get('required_proficiency', '2'))
                                req_lvl_key = level_map.get(prof_lvl, 'intermediate')
                                req_lvl_name = comp_data.get('required_level_name') or req_lvl_key.capitalize()
                                comp_cmds.append((0, 0, {
                                    'competencies': comp_id,
                                    'required_level': req_lvl_key,
                                    'requirement': req_lvl_name,
                                    'smart_search': 'yes',
                                }))
                    except Exception:
                        pass

                if comp_cmds:
                    employee.competencies_id = comp_cmds

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------
    def _compute_award_count(self):
        for employee in self:
            employee.award_count = len(employee.award_ids)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_save_employee(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Saved Successfully'),
                'message': _("Employee '%s' has been saved successfully.") % self.name,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_archive_employee(self):
        self.ensure_one()
        name = self.name
        if self.active:
            self.write({'active': False})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Archived'),
                    'message': _("Employee '%s' has been archived and disabled in Active Directory.") % name,
                    'type': 'warning',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'name': 'Employees',
                        'res_model': 'hr.employee',
                        'res_id': self.id,
                        'view_mode': 'form',
                        'views': [(False, 'form')],
                        'target': 'current',
                    },
                }
            }
        else:
            self.write({'active': True})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Unarchived'),
                    'message': _("Employee '%s' has been unarchived and re-enabled in Active Directory.") % name,
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'name': 'Employees',
                        'res_model': 'hr.employee',
                        'res_id': self.id,
                        'view_mode': 'form',
                        'views': [(False, 'form')],
                        'target': 'current',
                    },
                }
            }

    def action_unarchive_employee(self):
        return self.action_archive_employee()


class HrEmployee(models.Model):
    _inherit = "hr.employee"


    service_hire_date = fields.Date(
        string="Hire Date",
        tracking=True,
        compute="_compute_service_hire_date",
        store=True,
        readonly=True,
        help=(
            "Hire date is normally the date an employee completes new hire paperwork"
        ),
    )
    service_start_date = fields.Date(
        string="Service Start Date",
        tracking=True,readonly=True,
        help=(
            "Start date is the first day the employee actually works and"
            " this date is used for accrual leave allocations calculation"
        ),
    )
    service_termination_date = fields.Date(
        string="Termination Date",
        related="departure_date",readonly=True,
        help=(
            "Termination date is the last day the employee actually works and"
            " this date is used for accrual leave allocations calculation"
        ),
    )
    service_duration = fields.Integer(
        string="Service Duration",
        readonly=True,
        compute="_compute_service_duration",
        help="Service duration in days",
    )
    service_duration_years = fields.Integer(
        string="Service Duration (years)",
        readonly=True,
        compute="_compute_service_duration_display",
    )
    service_duration_months = fields.Integer(
        string="Service Duration (months)",
        readonly=True,
        compute="_compute_service_duration_display",
    )
    service_duration_days = fields.Integer(
        string="Service Duration (days)",
        readonly=True,
        compute="_compute_service_duration_display",
    )

    @api.depends("contract_ids.date_start", "start_date")
    def _compute_service_hire_date(self):
        for employee in self:
            contracts = employee.contract_ids.filtered("date_start").sorted("date_start")
            if contracts:
                employee.service_hire_date = contracts[0].date_start
            else:
                employee.service_hire_date = employee.start_date

    @api.depends("service_start_date", "service_termination_date")
    def _compute_service_duration(self):
        for record in self:
            service_until = record.service_termination_date or fields.Date.today()
            if record.service_start_date and service_until > record.service_start_date:
                service_since = record.service_start_date
                service_duration = fabs(
                    (service_until - service_since) / timedelta(days=1)
                )
                record.service_duration = int(service_duration)
            else:
                record.service_duration = 0

    @api.depends("service_start_date", "service_termination_date")
    def _compute_service_duration_display(self):
        for record in self:
            service_until = record.service_termination_date or fields.Date.today()
            if record.service_start_date and service_until > record.service_start_date:
                service_duration = relativedelta(
                    service_until, record.service_start_date
                )
                record.service_duration_years = service_duration.years
                record.service_duration_months = service_duration.months
                record.service_duration_days = service_duration.days
            else:
                record.service_duration_years = 0
                record.service_duration_months = 0
                record.service_duration_days = 0

    @api.onchange("service_hire_date")
    def _onchange_service_hire_date(self):
        if not self.service_start_date:
            self.service_start_date = self.service_hire_date

    def _get_date_start_work(self):
        service_start_date = self.sudo().service_start_date
        if service_start_date:
            return datetime.combine(service_start_date, time(0, 0, 0))
        else:
            return super()._get_date_start_work()

    @api.model
    def _has_field_access(self, field, operation):
        """Allow read access to employee fields for internal users / Employees User group.
        Record-level rules still strictly restrict which employee records the user can see."""
        if not field.groups or self.env.su:
            return True
        if operation == 'read':
            user = self.env.user
            if user and len(user) == 1 and (
                user._has_group('base.group_user')
                or user._has_group('hr_employee_custom.group_hr_employee_user')
            ):
                return True
        return super()._has_field_access(field, operation)

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
                key=lambda h: (h.job_history_start_date or fields.Date.min, h.id or 0)
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

    def get_experience_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type='experience_letter')
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and hasattr(sig, 'get_letter_signature_data'):
                    data = sig.get_letter_signature_data()
                    param_name = self.env['ir.config_parameter'].sudo().get_param('hr_experience_letter_signatory')
                    param_title = self.env['ir.config_parameter'].sudo().get_param('hr_experience_letter_signatory_title')
                    if param_name:
                        data['signatory_name'] = param_name
                    if param_title:
                        data['signatory_title'] = param_title
                    return data
            except Exception:
                pass
        legacy = self.get_experience_letter_signature_stamp()
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': legacy,
            'signatory_name': self.get_experience_letter_signatory_name(),
            'signatory_title': self.get_experience_letter_signatory_title(),
            'signatory_company': 'Bunna Bank S.C.',
        }

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