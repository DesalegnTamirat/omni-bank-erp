# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta
from math import fabs
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    _description = "Employee information"

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    identification_id = fields.Char(string="Employee Identification")
    # Kept distinct from identification_id above - different field, used by
    # the legacy hr_employee_view.xml (see module docstring above).
    employee_identification = fields.Char(string="Employee Identification", help="Employee Id")

    # ------------------------------------------------------------------
    # Contact info
    # ------------------------------------------------------------------
    mobile_phone = fields.Char(string="Work Mobile")
    work_phone = fields.Char(string="Work Phone")
    work_email = fields.Char(string="Work Email")
    private_email = fields.Char(string="Personal Email")
    personal_email = fields.Char(string="Personal Email")
    phone_num = fields.Char(string="Personal Phone")
    personal_phone = fields.Char(string="Personal Phone")
    alternative_mobile = fields.Char(string='Alternate Mobile')
    emergency_contact_2_name = fields.Char(string="Emergency Contact 2 Name", help="Emergency Contact 2 Name")
    emergency_contact_2_phone = fields.Char(string="Emergency Contact 2 Phone", help="Emergency Contact 2 Phone")
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
    house_number = fields.Char(string="House Number", help="House Number")
    city = fields.Char(string="City", help="City")
    sub_city = fields.Char(string="Sub City", help="Sub City")
    region = fields.Char(string="Region", help="Region")
    woreda = fields.Char(string="Woreda", help="Woreda")
    kebele = fields.Char(string="Kebele", help="Kebele")

    # ------------------------------------------------------------------
    # Family / personal
    # ------------------------------------------------------------------
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
    details = fields.Char("Details")
    any_health_ssues = fields.Boolean("Any Health Issues")
    health_issue = fields.Char("Health Issue")
    details1 = fields.Char("Details")
    clinic_name = fields.Char("Clinic Name")
    doctor_name = fields.Char("Doctor Name")
    contact = fields.Char("Contact")
    conviction_of_crime = fields.Boolean("Conviction of crime")
    crime_no = fields.Char("Crime No")
    age = fields.Char(string="Age")

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
    first_contract_date = fields.Date(string='First Contract Date')
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

    @api.depends('parent_id')
    def _compute_planning_parent(self):
        for employee in self:
            manager = employee.parent_id
            previous_manager = employee._origin.parent_id

            if manager and (
                    employee.planning_parent_id == previous_manager
                    or not employee.planning_parent_id
            ):
                employee.planning_parent_id = manager

            elif not employee.planning_parent_id:
                employee.planning_parent_id = False

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

    qualification_id = fields.One2many('hr.qualification.info.employee', 'employee_id', 'Education Qualification')
    experiance_id = fields.One2many('hr.experience.info.employee', 'employee_id', 'Experiance')
    competencies_id = fields.One2many('hr.competencies.info.employee', 'employee_id', 'Competencies')

    # From employee_fields_application (hr_employee_hrMaster.py)
    responsible_user_id = fields.Many2one('res.users', "Responsible", default=lambda self: self.env.uid)

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
        groups="hr.group_hr_user",
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
        groups="hr.group_hr_user",
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
        groups="hr.group_hr_user",
        readonly=True,
        compute="_compute_service_duration",
        help="Service duration in days",
    )
    service_duration_years = fields.Integer(
        string="Service Duration (years)",
        groups="hr.group_hr_user",
        readonly=True,
        compute="_compute_service_duration_display",
    )
    service_duration_months = fields.Integer(
        string="Service Duration (months)",
        groups="hr.group_hr_user",
        readonly=True,
        compute="_compute_service_duration_display",
    )
    service_duration_days = fields.Integer(
        string="Service Duration (days)",
        groups="hr.group_hr_user",
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