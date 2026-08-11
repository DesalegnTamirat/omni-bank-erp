# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from odoo import models, fields, _, api
import datetime
import re
from odoo.exceptions import ValidationError
from datetime import datetime
from odoo import models, fields
from odoo.exceptions import UserError


# DisciplinaryActionRecord (emp.discipline.action.record) REMOVED — Disciplinary feature removed


class HrEmployeeFamilyInfo(models.Model):
    """Table for keep employee family information"""

    _name = 'hr.employee.family'
    _description = 'HR Employee Family'

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # MODEL NOT DEFINED — 'hr.employee.relation' does not exist anywhere in this
    # module (no model, no view usage found). Looks like an unfinished feature.
    # Uncomment once that model is created (e.g. a Selection field listing
    # relationship types, or a proper hr.employee.relation model).
    # relation_id = fields.Many2one('hr.employee.relation', string="Relation", help="Relationship with the employee")
    member_name = fields.Char(string='Name')
    member_contact = fields.Char(string='Contact No')
    birth_date = fields.Date(string="DOB")
    address = fields.Char(string='Address')


class HrEmployeeEducationInfo(models.Model):
    """Table for keep employee family information"""

    _name = 'hr.employee.education'
    _description = 'HR Employee Education'

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    qualification = fields.Char(string='Qualification')
    specialization = fields.Char(string='Specialization')
    place_of_study = fields.Char(string="Place of Study")
    college_or_school = fields.Char(string="College / School Name")
    university = fields.Char(string="University")
    year_of_admission = fields.Integer(string="Year of Admission")
    year_of_outcome = fields.Integer(string="Year of Outcome")
    cgpa_percentage = fields.Float(string="CGPA/Percentage")
    fulltime = fields.Char(string="Full time/Part time")
    other_information = fields.Char(string="Other Information")


class Hr_third_party_Info(models.Model):
    """Table for keep employee family information"""

    _name = 'hr.due'
    _description = 'HR Third Party Dues'

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    organization_name = fields.Char(string='Organization Name')
    location = fields.Char(string='Location')
    deduction_type = fields.Char(string="Deduction Type")
    total_amount = fields.Integer(string="Total amount")
    monthly_deduction = fields.Integer(string="Monthly Deduction")
    date_from = fields.Date(string="Date From")
    Date_to = fields.Date(string="Date To")
    payable_in_favor_of = fields.Char(string="Payable in favor of")
    Bank = fields.Char(string="Bank")
    Branch = fields.Char(string="Branch")
    Account_No = fields.Integer(string="A/c No")
    IFSC_Code = fields.Integer(string="IFSC Code")
    Reference = fields.Char(string="Reference")


class HrEmployeeLanguageInfo(models.Model):
    _name = 'hr.languages'
    _description = 'HR language details'

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    language = fields.Char(string='Language')
    proficiency = fields.Selection(
        [('excellent', 'Excellent'), ('very good', 'VeryGood'), ('good', 'Good'), ('fair', 'Fair')],
        string='Proficiency', default='excellent')
    name = fields.Char()
    ability_language = fields.Many2many("hr.ability.languages", string="Ability")


class ability_of_languages(models.Model):
    _name = 'hr.ability.languages'
    name = fields.Char(string="Ability")


class part_time_employement(models.Model):
    _name = "part.time.employment"
    _description = "Part Time Employement"
    _rec_name = "employee_name"

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    employee_name = fields.Char("Employer Name")
    address = fields.Char("Address")
    Job_title = fields.Char("Job Title")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
    other_info = fields.Char('Other info')
    state = fields.Selection(
        [('draft', 'Draft'), ('approved', 'Approved')],
        string="Status", default='draft')

    def approve(self):
        part_time_employement = self.env["hr.employee"].search(
            [("user_id", "=", self.env.uid)]
        )
        vals = {
            "employee_id": part_time_employement.id,
            "employee_name": self.employee_name,
            "address": self.address,
            "Job_title": self.Job_title,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "other_info": self.other_info,
        }
        # for val2 in part_time_employement
        self.env["part.time.employment"].create(vals)
        # print("part_time_employement",part_time_employement)
        self.state = "approved"


class grade_multi_Supplementory(models.Model):
    _name = "supplementary.multi.role"
    _description = "Supplementary Role Details"
    _rec_name = "reference_no"
    # grade_code = fields.Many2one("employee.grade", "Grade Code")
    supplementary_position = fields.Char("Supplementary Position")
    reason_for_assignment = fields.Char("Reason for Assignment")
    reference_no = fields.Integer("Reference No")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    other_info = fields.Char('Other Information')


class organization_name_fields(models.Model):
    _inherit = 'hr.resume.line'

    organization_name = fields.Char(
        string='Organization Name'
    )
    ctc = fields.Char(
        string=' CTC (PA)'
    )
    reason_for_leaving = fields.Char(
        string=' Reason for Leaving'
    )
    payment_tax = fields.Char(
        string='Payment of Tax Confirmation'
    )


class Hr_department_Fields(models.Model):
    _inherit = "hr.department"
    operating_unit = fields.Many2one('operating.unit', 'Operating Unit')


#
#
# class late_by(models.Model):
#     _inherit = "hr.attendance"
#     late_by = fields.Char(string="Late By")
#
# class alternate_mobile_fields_new(models.Model):
#     _inherit = "res.partner"
#
#

class hr_job_updated(models.Model):
    _inherit = "hr.job"

    # operating_unit = fields.Many2one('operating.unit', string="Operating Unit")
    vacancy_announced_on = fields.Date(string="Vacancy Announced on")
    employee_category = fields.Selection(
        [('Managerial', 'Managerial'), ('Non Managerial', 'Non Managerial')],
        string='Job Category', default='Non Managerial')
    type_of_employment = fields.Selection(
        [('Permanent', 'Permanent'), ('Contractual', 'Contractual')],
        string='Type of Employment', default='Permanent')
    last_date_to_apply = fields.Date(string="Last Date To Apply")
    analytic_tag = fields.Char(string="Analytic Tag")
    probation_period = fields.Integer(string="Probation Period")
    job_code = fields.Many2one("hr.job", string="Job Code")
    grade = fields.Many2one("employee.grade", "Grade")
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company")
    current_location_exp = fields.Float(string="Current Location Experience",
                                        help="Minimum experience in current location required (from bunna_hr_addons).")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    demoted_employee = fields.Boolean(string="Demoted Employee")
    promotion_revoked = fields.Boolean(string="Promotion Revoked")
    weightage_written_exam = fields.Float(string="Weightage Written Exam")
    weightage_interview = fields.Float(string="Weightage Interview")
    weightage_pms = fields.Float(string="Weightage PMS")
    non_experienced_applicant = fields.Boolean(string="Non Experienced Applicant")

    internal_recruitment_status = fields.Char(string="Internal Recruitment Status", default='New')

    survey_id2 = fields.Char(string="Interview Form")


sql_constraints = [
    ('job_name_uniq', 'unique(name)',
     'A job position with this name already exists! Job names must be unique.'),
]


@api.constrains('name')
def _check_job_name_unique(self):
    for job in self:
        if not job.name:
            continue
        if self.env['hr.job'].search_count([
            ('id', '!=', job.id),
            ('name', '=', job.name),
        ]):
            raise ValidationError(
                "A job position named '%s' already exists. "
                "Job position names must be unique." % job.name
            )


class Hr(models.Model):
    _inherit = "hr.job"

    instruction = fields.Text(string="Instructions")


class late_by(models.Model):
    _inherit = "hr.attendance"
    late_by = fields.Char(string="Late By")


class EducationFeeSponsorship(models.Model):
    _name = 'education.fee.sponsorship'
    sponsorship_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    sponsorhip_reference = fields.Char("Sponsorhip Reference")
    amount = fields.Float("Amount")
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")


class TrainingCommitment(models.Model):
    _name = 'training.commitment'
    commitment_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    training_reference = fields.Char("Training Reference")
    training_type = fields.Char("Training Type")
    amount = fields.Float("Amount")
    commitment_duration = fields.Float("Commitment Duration")
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    outstanding_amount = fields.Date(string="Outstanding Amount")


# NOTE: the 'hr.awards' model previously defined here was removed to avoid
# a duplicate _name declaration conflicting with hr_awards.py, which is the
# authoritative definition (see hr_awards.py).


class pension_multi(models.Model):
    _name = "pension.multi.record"
    _description = "Pension Info"
    _rec_name = "name_of_employer"
    name_of_employer = fields.Char(string="Name of Employer")
    date_of_resignation = fields.Date(string="Date of Resignation")
    pension_contribution_rate = fields.Float(string="Pension Contribution Rate")
    pension_contribution_type = fields.Selection(
        [('employee contribution', 'Employee Contribution'), ('employer contribution', 'Employer Contribution')],
        string='pension_contribution_type', default='employee contribution')
    referance_latter_name = fields.Char(string="Reference letter Name")
    doc_attachment_id10 = fields.Many2many('ir.attachment', 'doc_attach_rel4', 'doc_id11', 'attach_id12',
                                           string="Attachment",
                                           help='You can attach the copy of your document', copy=False)
    retrirement_age = fields.Integer("Retirement Age")

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')


class HrEmployeeAttachment_data(models.Model):
    _inherit = 'ir.attachment'
    doc_attach_rel4 = fields.Many2many('pension.multi.record', 'doc_attachment_id10', 'attach_id12', 'doc_id11',
                                       string="Attachment")
    # DOCUMENT MANAGEMENT MODULE NOT INSTALLED — 'hr.document' model does not
    # exist in this database. Uncomment once that module is installed.
    # attach_rel = fields.Many2many('hr.document', 'attach_id', 'attachment_id3', 'document_id',
    #                               string="Attachment")


class Bank_info(models.Model):
    _name = "bank.info"
    _description = "Bank Info"
    _rec_name = "account_type"
    employee_id = fields.Many2one('hr.version', string="Employee Contract",
                                  help='Select corresponding Employee')
    bank_name = fields.Char(string='Bank Name')
    branch_name = fields.Char(string='Branch Name')
    location = fields.Char(string='Location')
    account_no = fields.Integer(string="Account No")
    ifsc_code = fields.Char(string="IFSC Code")
    account_type = fields.Char(string="Account Type")


class Hr_contact_Fields(models.Model):
    _inherit = "hr.version"
    # company_name = fields.Char(string='Company Name',required=True)

    job_grade = fields.Many2one('employee.grade', 'Job Grade', required=False)
    job_category = fields.Many2one('employee.job', 'Job Name')
    probation_period = fields.Integer(string="Probation Period (months)", help="Probation Period")
    job_description = fields.Text(string="Job Description", help="Job Description")
    employee_tin = fields.Char(string="Employee TIN", help="Employee TIN")
    probation_start_date = fields.Date(string="Probation Start date", help="Probation Start date")
    probation_end_date = fields.Date(string="Probation End Date", help="Probation End Date")
    salary_account = fields.Char(string="Salary Account", help="salary_account")
    od_account = fields.Char(string="OD Account", help="OD Account")
    pf_account = fields.Char(string="PF Account", help="PF Account")
    asbeza_account = fields.Char(string="ASBEZA Account", help="ASBEZA Account")
    indemnity_account = fields.Char(string="Indemnity Account", help="Indemnity Account")
    indemnity_account_balance = fields.Float(string="Indemnity Account Balance", help="Indemnity Account Balance")
    pf_contribution_balance = fields.Float(string="PF Contribution Balance", help="PF Contribution Balance")
    company_car_provided = fields.Selection([('Yes', 'Yes'),
                                             ('No', 'No')], default='No', string="Company Car Provided")
    union_member = fields.Selection([('Yes', 'Yes'),
                                     ('No', 'No')], default='No', string="Member of Labour Union")
    cost_sharing_balance = fields.Float(string="Cost Sharing Balance", help="Cost Sharing Balance")
    cost_sharing_period = fields.Integer(string="Cost Sharing Period", help="Cost Sharing Period")
    total_tax_exemption = fields.Float(string="Total Tax Exemption", help="Total Tax Exemption")
    wrapping_applicable = fields.Boolean(string='Wrapping Applicable')
    pms_score = fields.Float(string="PMS Score")
    pms_rank = fields.Selection([('Outstanding', 'Outstanding'),
                                 ('Excellent', 'Excellent'),
                                 ('Satisfactory', 'Satisfactory'),
                                 ('Unsatisfactory', 'Unsatisfactory')], string="PMS Rank")
    base_salary = fields.Float(string="Base Salary", help="Employee's monthly gross Base Salary")
    factor = fields.Float(string="Factor", help="Employee's monthly gross factor", digits=(16, 3))
    # JOb Position = fields.Many2one('operating.unit', string="JOb Position")
    salary_multi_id = fields.One2many("hr_salary_breakup", 'salary_id', 'Salary Breakup')
    job_categoryy = fields.Char(string="Job Category", compute="_compute_job_categoryy")
    non_monetary_benefits = fields.One2many("non_monetary_benefits", 'benefits_id', 'Non-Monetary Benefits')
    contract_multi_id = fields.One2many("hr.contract.salary", 'contract_salary_id', 'salary Details')
    cash_indemnity_applicable = fields.Boolean(string="Cash Indemnity Applicable")
    fuel_exempted = fields.Boolean(string="Fuel Exempted")
    fuel_exempted_1 = fields.Integer(string="Fuel Exempted 1")

    def start_survey(self):
        pass

    def _compute_job_categoryy(self):
        val = self.env["hr.employee"].search([("name", "=", self.employee_id.name)])
        vals = self.env["hr.job"].search([("name", "=", val.job_position.name)])
        self.job_categoryy = vals.employee_category
        return self.job_category
        # self.job_category=val.employee_category

    # @api.onchange("date_end")
    # def date_difference(self):
    #     start_date =datetime.strptime(self.date_start, "%m/%d/%Y")
    #     end_date =datetime.strptime(self.date_end, "%m/%d/%Y")
    #     self.trial_date_end=(end_date-start_date).days


class job_multi_record(models.Model):
    _name = "hr.contract.salary"
    _description = "salary  Details"
    # PAYROLL MODULE NOT INSTALLED — _rec_name was "contract_salary_rule", but that
    # field is commented out below (depends on hr.salary.rule). Odoo requires
    # _rec_name to point at a field that exists, so it's commented out here too.
    # Restore as _rec_name = "contract_salary_rule" once the payroll module is
    # installed and the field below is uncommented.
    # _rec_name = "contract_salary_rule"
    contract_salary_id = fields.Many2one('hr.version', string="Employee Contract",
                                         help='Select corresponding Employee')
    # PAYROLL MODULE NOT INSTALLED — uncomment once a payroll module providing
    # hr.salary.rule (e.g. hr_payroll_community) is installed.
    # contract_salary_rule = fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
    # contract_internal_name = fields.Char(string='Internal Name', help='Internal Name',
    #                                      related="contract_salary_rule.internal_name")
    contract_value = fields.Float("Value")
    contract_start_date = fields.Date("Start Date", required=True)
    contract_end_date = fields.Date("End Date", required=True)


class hr_salary_breakup(models.Model):
    _name = "hr_salary_breakup"
    _description = "Salary Breakup"
    _rec_name = "pay_elements"
    # employee_contract_new_id = fields.Many2one('hr.contract', string="Employee Contract", help='Select corresponding Employee',
    #                               invisible=1)
    salary_id = fields.Many2one('hr.version', string="Employee Contract", help='Select corresponding Employee')
    pay_elements = fields.Char(string='Pay Elements', required=True)
    category = fields.Char(string='Category', required=True)
    value = fields.Char(string='Value', required=True)
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")


#
class non_monetary_benefits(models.Model):
    _name = "non_monetary_benefits"
    _description = "Non-Monetary Benefits"
    _rec_name = "period_of_issue"
    benefits_id = fields.Many2one('hr.version', string="Employee Contract",
                                  help='Select corresponding Employee')
    period_of_issue = fields.Char(string='Period of Issue', required=True)
    material_issued = fields.Char(string='Material Issued', required=True)
    date_of_issue = fields.Char(string='Date of Issue', required=True)
    remarks = fields.Char(string="Remarks")


class Job(models.Model):
    _inherit = "hr.job"
    _description = "Job Position"
    qualification_id = fields.One2many('hr_qualification_info_job', 'job_id', 'Education Qualification')
    experiance_id = fields.One2many('hr_experience_info_job', 'job_id', 'Experiance')
    competencies_id = fields.One2many('hr_competencies_info_job', 'job_id', 'Competencies')
    grade_recruitment_id = fields.One2many('employee.recruitment.grade', 'employee_id', 'Eligible Grades')
    position_id = fields.One2many('employee.recruitment.position', 'employee_id', 'Eligible Positions')
    hr_new_department_ids = fields.One2many('hr_new_department_info_job', 'job_id', 'Department Info')
    # hr_policy_id = fields.One2many("hr.job.policies", "hr_job_id", string="Hr Policies")
    user_id = fields.Many2one('res.users', "Responsible", tracking=True, default=lambda self: self.env.uid)


class res_users_hr_applicant_responsible(models.Model):
    _inherit = 'res.users'

    @api.onchange('login')
    def validate_mail(self):
        if self.login:
            match = re.match(r'^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', self.login)
            if match == None:
                raise ValidationError('Not a valid E-mail ID')


class res_partner_hr_applicant_responsible(models.Model):
    _inherit = 'res.partner'


class attachment_file(models.Model):
    _inherit = 'ir.attachment'
    # _description = "Job Position"
    # qualification_id = fields.One2many('hr_qualification_info', 'applicant_id', 'Education Qualification')
    # experiance_id = fields.One2many('hr_experience_info', 'applicant_id', 'Experiance')
    # competencies_id = fields.One2many('hr_competencies_info', 'applicant_id', 'Competencies')
    # hr_new_department_ids = fields.One2many('hr_new_department_info', 'applicant_id', 'Department Info')
    # user_id2 = fields.Many2one('res.users', "Responsible", tracking=True, default=lambda self: self.env.uid)


class qualification_multi_record_job(models.Model):
    _name = "hr_qualification_info_job"
    _description = "qualification Profile "
    _rec_name = "qualification"
    job_id = fields.Many2one('hr.job', string="Job Position", help='Select corresponding Job Position')
    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    applicant_id = fields.Many2one('hr.applicant', string="Applicant", help='Select corresponding Applicant')

    # qualification = fields.Char(string="Qualification")
    qualification = fields.Many2one('recruitment.qualification', string="Recruitment Qualification")
    requirement = fields.Float(string="Requirement(CGPA)")
    response = fields.Float(string="Response")
    smart_search = fields.Selection([('yes', 'Y'), ('no', 'N')], string='Smart Search', default='yes')


class EligibleGrades(models.Model):
    _name = "employee.recruitment.grade"
    _description = "Eligible Grades"
    _rec_name = "job_grade"
    employee_id = fields.Many2one('hr.job', string="Employee", help='Select corresponding Employee')

    job_grade = fields.Many2one("employee.grade", string="Job Grade")
    status = fields.Boolean(string="Status")


class EligiblePositions(models.Model):
    _name = "employee.recruitment.position"
    _description = "Eligible Positions"
    _rec_name = "position"
    employee_id = fields.Many2one('hr.job', string="Employee", help='Select corresponding Employee')

    position = fields.Many2one("hr.job", string="Position")
    status = fields.Boolean(string="Status")


class hr_recruitment_stage2(models.Model):
    _inherit = "hr.recruitment.stage"


#
class mail_thread2(models.AbstractModel):
    _inherit = "mail.thread"


class mail_activitymixin2(models.AbstractModel):
    _inherit = "mail.activity.mixin"


class mail_followers2(models.Model):
    _inherit = 'mail.followers'


class res_partner3(models.Model):
    _inherit = 'res.partner'


# PAYROLL MODULE NOT INSTALLED — uncomment once a payroll module providing
# hr.salary.rule (e.g. hr_payroll_community) is installed.
# class inherit_internal_name(models.Model):
#     _inherit = 'hr.salary.rule'
#     _description = "Edit Internal Name In Salary Rules"
#     internal_name = fields.Char(string='Internal Name',
#                                 help="The code of salary rules can be used as reference in computation of other rules. "
#                                      "In that case, it is case sensitive.")
#     value = fields.Float(required=True, help='Use to enter numerical value for calculations')


class experience_multi_record_job(models.Model):
    _name = "hr_experience_info_job"
    _description = "experience Profile"
    _rec_name = "experience"
    job_id = fields.Many2one('hr.job', string="Job Position", help='Select corresponding Job Position')
    applicant_id = fields.Many2one('hr.applicant', string="Applicant", help='Select corresponding Applicant')
    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # experience = fields.Char(string="Experience")
    experience = fields.Many2one('recruitment.experience', string="Experience")
    requirement = fields.Float(string="Requirement(Years)")
    response = fields.Float(string="Response")
    smart_search = fields.Selection([('yes', 'Y'), ('no', 'N')], string='Smart Search', default='yes')


class competencies_multi_record_job(models.Model):
    _name = "hr_competencies_info_job"
    _description = "Competencies Profile"
    _rec_name = "competencies"
    job_id = fields.Many2one('hr.job', string="Job Position", help='Select corresponding Job Position')
    applicant_id = fields.Many2one('hr.applicant', string="Applicant", help='Select corresponding Applicant')
    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # competencies = fields.Char(string="Competencies")
    competencies = fields.Many2one('recruitment.competency', string="Competency")
    requirement = fields.Char(string="Requirement")
    response = fields.Char(string="Response")
    smart_search = fields.Selection([('yes', 'Y'), ('no', 'N')], string='Smart Search', default='yes')


class hr_department_job(models.Model):
    _name = "hr_new_department_info_job"
    # _description = " Department Form"
    _rec_name = "work_unit"
    job_id = fields.Many2one('hr.job', string="Employee", help='Select corresponding Employee')
    applicant_id = fields.Many2one('hr.applicant', string="Applicant", help='Select corresponding Applicant')
    # work_unit = fields.Many2one('operating.unit', string="Work Unit", help='Select Work Unit')
    work_unit = fields.Many2one('vacancy.workunit', string="Work Unit", help='Select Work Unit')
    # recruitment_name = fields.Char("Recruitment Name")
    # requirement_start_date = fields.Date("Recruitment Start date")
    # requirement_end_date = fields.Date("Recruitment End date")
    last_date_to_apply = fields.Date("Last Date To Apply")
    number_of_vacancies = fields.Integer("Number of Vacancies")
    # special_conditions = fields.Integer("Special Conditions")
    # analytic_tag = fields.Char("Analytic tag")
    response = fields.Integer(string="Response")

    def unpublish_jobs(self):
        get_list = self.env["hr_new_department_info_job"].search([])
        for val in get_list:
            if val.last_date_to_apply:
                if (val.last_date_to_apply < datetime.date.today()):
                    val.job_id.write({"is_published": False})

    # url_field = fields.Char('Interview Form', default='https://www.odoo.com')
    def interview_form(self):
        pass
        # survey_id = fields.Char("Interview Form")
    # class time_off(models.Model):


# NOT INSTALLED — this class needs BOTH a loan module (for hr.loan) and a
# payroll module (for hr.salary.rule). Neither is installed. Uncomment once
# both are available.
# class HrLoanField(models.Model):
#     _inherit = 'hr.loan'
#
#     loan_type = fields.Selection(
#         [('vehicle_loan', 'Vehicle Loan'), ('housing_loan', 'Housing Loan'), ('personal_loan', 'Personal Loan'),
#          ('other_loan', 'Other  Loan')], string='Loan Type', default='vehicle_loan')
#     installment_amount = fields.Integer("Installment Amount", required=True)
#     salary_rule_name = fields.Many2one("hr.salary.rule", "Salary Rule Name")
#     salary_rule_code = fields.Char("Salary Rule Code")
#
#     @api.onchange('salary_rule_name')
#     def _onchange_salary_rule_name(self):
#         print("id================================================", self.salary_rule_name.id)
#         salary_rule = self.env['hr.salary.rule'].search([("id", "=", self.salary_rule_name.id)])
#         print("salary_rule", salary_rule)
#         self.salary_rule_code = salary_rule.code


# class AttendanceValidationSheet(models.Model):
#   _inherit = "hr.attendance.validation.sheet"
#  job_grade = fields.Many2one('employee.grade', 'Job Grade', required=True)
# job_category = fields.Many2one('employee.job', 'Job Category')
# job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position")
# operating_unit = fields.Many2one('operating.unit', 'Operating Unit')
# gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
#                         string='Gender', default='male')

# @api.onchange('employee_id')
# def _onchange_acting_employee_info(self):
#    self.job_grade = self.employee_id.job_grade.id
#  self.job_category = self.employee_id.contract_id.job_category.id
#  self.job_position = self.employee_id.job_position.id
# self.operating_unit = self.employee_id.default_operating_unit_id.id


class AllTimeOff(models.Model):
    _inherit = "hr.leave"

    job_grade = fields.Many2one('employee.grade', 'Job Grade', required=False)
    job_category = fields.Many2one('employee.job', 'Job Category')
    job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position")
    operating_unit = fields.Many2one('operating.unit', 'Operating Unit')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              string='Gender', default='male')

    @api.onchange('employee_id')
    def _onchange_acting_employee_info(self):
        self.job_grade = self.employee_id.job_grade.id
        self.job_category = self.employee_id.contract_id.job_category.id
        self.job_position = self.employee_id.job_position.id
        self.operating_unit = self.employee_id.default_operating_unit_id.id

# class EmployeeResignation(models.Model):
#     _inherit = 'hr.resignation'
#     job_category = fields.Many2one('employee.job', 'Job Category')
#     job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position")
#     operating_unit = fields.Many2one('operating.unit', 'Operating Unit')
#     gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
#                               string='Gender', default='male')
# # #
#     @api.onchange('employee_id')
#     def _onchange_acting_employee_info(self):
#         self.job_category = self.employee_id.contract_id.job_category.id
#         self.job_position = self.employee_id.job_position.id
#         self.operating_unit = self.employee_id.default_operating_unit_id.id
