# -*- coding: utf-8 -*-

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
    identification_id = fields.Char(string="Employee Identification")
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

    def _auto_init(self):
        res = super()._auto_init()
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
        return res

    # ------------------------------------------------------------------
    # Contact info
    # ------------------------------------------------------------------
    mobile_phone = fields.Char(string="Work Mobile")
    work_phone = fields.Char(string="Work Phone")
    work_email = fields.Char(string="Work Email")
    private_email = fields.Char(string="Personal Email", groups=False)
    personal_email = fields.Char(string="Personal Email")
    phone_num = fields.Char(string="Personal Phone")
    personal_phone = fields.Char(string="Personal Phone")
    alternative_mobile = fields.Char(string='Alternate Mobile')
    emergency_contact_2_name = fields.Char(string="Emergency Contact 2 Name", help="Emergency Contact 2 Name")
    emergency_contact_2_phone = fields.Char(string="Emergency Contact 2 Phone", help="Emergency Contact 2 Phone")
    emergency_contact_relation = fields.Char(string="Emergency Contact Relationship")
    gender = fields.Selection(
        selection=[
            ('male', 'Male'),
            ('female', 'Female'),
        ],
        string='Gender',
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
    father_name1 = fields.Char(string='Father Name')
    grand_father_name = fields.Char(string='Grand Father Name')
    grand_father_name1 = fields.Char(string='Grand Father Name')
    mother_name = fields.Char(string="Mother Name")
    mother_name1 = fields.Char(string="Mother Name")
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
    contact = fields.Char("Contact")
    age = fields.Char(string="Age")
    citizenship_attachment = fields.Binary(string="Citizenship / ID Document", attachment=True)
    citizenship_attachment_filename = fields.Char(string="Citizenship Attachment Filename")

    @api.onchange('birthday')
    def _onchange_birthday_compute_age(self):
        if self.birthday:
            today = fields.Date.today()
            age_years = relativedelta(today, self.birthday).years
            self.age = str(max(0, age_years))

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
    # Languages
    # ------------------------------------------------------------------
    languages = fields.Char(string="Languages")
    language_ids = fields.Many2many('res.lang', string="Languages")
    languages_ids = fields.One2many('hr.languages', 'employee_id', string='HR Languages', help='Languages Information')


    current_company = fields.Char("Current Company")
    working_status = fields.Char("Working Status")
    willing_to_join_immediately = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Willing to Join Immediately', default='yes')
    date_of_availability = fields.Date("Date of Availability")
    # first_contract_date is a computed field defined in hr_employee_contract.py
    job_name = fields.Char(string="Job Name", help="Job Name")
    job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position")

    job_grade = fields.Many2one("employee.grade", string="Job Grade", help="Job Grade")
    department_id = fields.Many2one('hr.department', string='Department')
    operating_unit_ids = fields.Many2many('operating.unit', string="Operating Units")
    default_operating_unit_id = fields.Many2one('operating.unit', string="Default Operating Unit")
    start_date = fields.Date(string="Start Date")
    location = fields.Char("Location")
    status = fields.Char("Status")
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
        return employees

    def write(self, vals):
        self._sync_hierarchy_vals(vals)
        if self.env.context.get('in_sync_criteria_from_job'):
            return super().write(vals)
        res = super().write(vals)
        if 'job_id' in vals or 'job_position' in vals:
            self.with_context(in_sync_criteria_from_job=True)._sync_criteria_from_job()
        return res

    @api.onchange('job_id', 'job_position', 'edu_ids', 'education_detail_ids')
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

            # 2. Experience from Job Position
            if job:
                existing_exp_ids = set(employee.experiance_id.mapped('experience.id'))
                exp_cmds = []
                for e in job.experiance_id:
                    if e.experience and (force or e.experience.id not in existing_exp_ids):
                        if e.experience.id in existing_exp_ids and force:
                            continue
                        exp_cmds.append((0, 0, {
                            'experience': e.experience.id,
                            'requirement': e.requirement,
                            'response': e.response,
                            'smart_search': e.smart_search or 'yes',
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
        self.write({'active': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Archived'),
                'message': _("Employee '%s' has been archived successfully.") % name,
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Employees',
                    'res_model': 'hr.employee',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            }
        }


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
        string="Start Date",
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