# -*- coding: utf-8 -*-


from datetime import datetime
import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class HrApplicantScoringFields(models.Model):
    """
    Fields on hr.applicant that reference custom_recruitment models
    (recruitment.candidate.score, recruitment.offer.letter).
    """
    _inherit = "hr.applicant"

    internal_reference_no = fields.Char(string='Reference No.', copy=False)

    # Domain now references app_reference directly — the candidate list is
    # restricted to Selected candidates belonging to the chosen vacancy.
    # Empty/False app_reference => vacancy_id = False => no candidates shown,
    # forcing the user to pick Applicant Reference first.
    candidate_score_id = fields.Many2one(
        "recruitment.candidate.score",
        string="Selected Candidate",
        domain="[('selection_status', '=', 'selected'), ('vacancy_id', '=', app_reference)]",
        copy=False,
        help="Select a candidate marked 'Selected' for the chosen Applicant "
             "Reference (Vacancy). Only candidates belonging to that vacancy "
             "are shown."
    )

    # Real selectable field — picking a vacancy here cascades Job Position,
    # Application Type, and Preferred Location (see _apply_vacancy_defaults),
    # and restricts candidate_score_id's list above. Raises an error if the
    # chosen vacancy has no candidate marked 'Selected' yet.
    app_reference = fields.Many2one(
        "job.vacancy",
        string="Applicant Reference",
        copy=False,
        domain="[('vacancy_status', 'in', ['evaluate', 'published'])]",
        help="Select the Vacancy this application is for. Must already have "
             "at least one 'Selected' candidate — Job Position, Application "
             "Type and Preferred Location are auto-filled from it and locked."
    )

    hr_new_ids = fields.One2many('hr.health.applicant', 'employee_id', string='Health wellness',
                                 help='Hr application Information')
    date_of_birth = fields.Date("Date of Birth")
    place_of_birth = fields.Char("Place of Birth")
    gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
        string='Gender', default='male')
    worked_in_bunna_earlier = fields.Boolean(string="Worked in Bunna Earlier")
    current_company = fields.Char("Current Company")
    current_working_location = fields.Char("Current Working Location")
    contract_created_new = fields.Boolean(string="Create Contract")
    offer_letter_sent = fields.Boolean(string="Offer Letter Sent", copy=False)
    working_status = fields.Selection(
        [('active', 'Active'), ('terminated', 'Terminated'), ('resigned', 'Resigned')],
        string='Working Status')
    willing_to_join_immediately = fields.Boolean("Willing to join Immediately")
    date_of_availability = fields.Date("Date of Availability")
    internal_employee_name = fields.Char("Employee Name")
    employee_number = fields.Char("Employee Number")
    employee_grade = fields.Char("Employee Grade", compute="_compute_employee_grade")
    employee_position = fields.Char("Employee Position", compute="_compute_employee_position")
    employee_work_unit = fields.Char("Current Work Unit")
    promotion_date = fields.Date("Date of Promotion")
    employment_start_date = fields.Date("Employment Start Date")
    final_work_unit = fields.Many2one("operating.unit", string="Assigned Work Unit",
                                      help='Enter the Appointed Work Unit')
    preferred_location = fields.Char("Preferred Location")
    vacancy_reference = fields.Char("Vacancy Reference")
    cc_workunits = fields.Many2many("operating.unit", "apllicant_rel", string="CC To:",
                                    help="Enter the Workunits to be copied")
    application_type = fields.Selection(
        [('Internal', 'Internal'), ('External', 'External'), ('Referral', 'Referral')],
        string='Application Type', default='Internal')
    select_flag = fields.Boolean(string="Select")
    application_status = fields.Char(string="Application Status")
    job_offer_status = fields.Char(string="Job Offer")
    rejection_reason = fields.Text(string="Rejection Reason")
    age = fields.Char(string="Age", compute='_calculate_age')
    manager = fields.Many2one("hr.employee", string="Manager")

    def _apply_vacancy_defaults(self, vacancy):
        """
        Cascade triggered from either app_reference or candidate_score_id.
        Job Position, Application Type, Preferred Location, and Vacancy
        Reference are all derived from the vacancy and locked readonly in
        the view once app_reference is set.
        """
        self.ensure_one()
        if not vacancy:
            return
        self.job_id = vacancy.job_position
        if vacancy.recruitment_type == 'Internal':
            self.application_type = 'Internal'
        elif vacancy.recruitment_type == 'External':
            self.application_type = 'External'
        self.preferred_location = vacancy.operating_unit_id.name or False
        self.vacancy_reference = vacancy.reference

    @api.onchange('app_reference')
    def _onchange_app_reference(self):
        """
        Selecting Applicant Reference cascades vacancy defaults, but first
        requires the vacancy to already have at least one candidate marked
        'Selected' — otherwise this raises and blocks the pick outright.
        Also clears any previously chosen candidate_score_id that no longer
        belongs to the new vacancy, so the two fields can't drift apart.
        """
        for rec in self:
            if not rec.app_reference:
                continue
            vacancy = rec.app_reference

            has_selected_candidate = self.env['recruitment.candidate.score'].search_count([
                ('vacancy_id', '=', vacancy.id),
                ('selection_status', '=', 'selected'),
            ])
            if not has_selected_candidate:
                raise UserError(_(
                    "Vacancy %s has no candidate marked as 'Selected'. "
                    "Please complete candidate scoring and selection for "
                    "this vacancy before choosing it as the Applicant "
                    "Reference."
                ) % vacancy.reference)

            if rec.candidate_score_id and rec.candidate_score_id.vacancy_id != vacancy:
                rec.candidate_score_id = False

            rec._apply_vacancy_defaults(vacancy)

    @api.onchange('candidate_score_id')
    def _onchange_candidate_score_id(self):
        """
        Also sets app_reference from the score's vacancy and runs the same
        cascade, so both entry points land on identical values.
        """
        for rec in self:
            score = rec.candidate_score_id
            if not score:
                continue
            rec.gender = score.gender
            rec.partner_name = score.candidate_name

            if score.vacancy_id:
                rec.app_reference = score.vacancy_id
                rec._apply_vacancy_defaults(score.vacancy_id)

            if score.recruitment_type == 'internal' and score.employee_id:
                rec.employee_id = score.employee_id
                rec.internal_employee_name = score.employee_id.name

    @api.constrains('app_reference', 'application_type')
    def _check_application_type_matches_vacancy(self):
        """
        Application Type must match the vacancy's Recruitment Type exactly —
        no other value permitted, regardless of how the record is written
        (form, import, API).
        """
        for rec in self:
            if not rec.app_reference:
                continue
            expected = rec.app_reference.recruitment_type
            if expected and rec.application_type != expected:
                raise ValidationError(_(
                    "Application Type must be '%s' to match the Recruitment "
                    "Type of vacancy %s. It cannot be changed independently."
                ) % (expected, rec.app_reference.reference))

    @api.constrains('app_reference', 'candidate_score_id')
    def _check_candidate_score_matches_vacancy(self):
        """
        Server-side backstop (catches import/API writes that bypass the
        onchange): Selected Candidate must belong to the same vacancy as
        Applicant Reference, and that vacancy must actually have at least
        one 'Selected' candidate.
        """
        for rec in self:
            if not rec.app_reference:
                continue

            has_selected_candidate = self.env['recruitment.candidate.score'].search_count([
                ('vacancy_id', '=', rec.app_reference.id),
                ('selection_status', '=', 'selected'),
            ])
            if not has_selected_candidate:
                raise ValidationError(_(
                    "Vacancy %s has no candidate marked as 'Selected'. "
                    "Applicant Reference cannot be set to a vacancy with no "
                    "selected candidates."
                ) % rec.app_reference.reference)

            if rec.candidate_score_id and rec.candidate_score_id.vacancy_id != rec.app_reference:
                raise ValidationError(_(
                    "Selected Candidate must belong to vacancy %s "
                    "(Applicant Reference). Please choose a candidate from "
                    "that vacancy's selected list."
                ) % rec.app_reference.reference)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.candidate_score_id and rec.candidate_score_id.recruitment_type == 'external' \
                    and not rec.candidate_score_id.applicant_id:
                rec.candidate_score_id.applicant_id = rec.id
        return records

    def _calculate_age(self):
        for partner in self:
            if partner.date_of_birth:
                dob_str = fields.Date.to_string(partner.date_of_birth)
                date_format = '%Y-%m-%d'
                dob = datetime.strptime(dob_str, date_format)
                today = datetime.now()
                age_years = today.year - dob.year
                age_months = today.month - dob.month
                if today.day < dob.day:
                    age_months -= 1
                if age_months < 0:
                    age_years -= 1
                    age_months += 12
                if age_years == 0:
                    partner.age = "{} months".format(age_months)
                elif age_months == 0:
                    partner.age = "{} years".format(age_years)
                else:
                    partner.age = "{} years {} months".format(age_years, age_months)
            else:
                partner.age = "N/A"

    def _compute_employee_grade(self):
        for emp in self:
            grd = self.env["hr.job"].search([("name", "=", emp.job_id.name)])
            if grd:
                emp.employee_grade = grd.grade.grade_name
                return emp.employee_grade
            else:
                emp.employee_grade = "N/A"
                return emp.employee_grade

    def _compute_employee_position(self):
        for emp in self:
            if emp.job_id:
                emp.employee_position = emp.job_id.name
                return emp.employee_position
            else:
                emp.employee_position = emp.job_id.name
                return emp.employee_position

    def action_applicant_send(self):
        self.ensure_one()
        self.offer_letter_sent = True
        '''
        Opens a window to compose an email using the standard mail compose
        wizard, addressed to the applicant.
        '''
        try:
            compose_form_id = self.env.ref('mail.email_compose_message_wizard_form').id
        except ValueError:
            compose_form_id = False

        ctx = {
            'default_model': 'hr.applicant',
            'default_res_ids': self.ids,
            'default_use_template': False,
            'default_composition_mode': 'comment',
            'email_to': self.email_from,
            'force_email': True,
        }
        lang = "en_US"

        if ctx.get('default_template_id'):
            template = self.env['mail.template'].browse(ctx['default_template_id'])
            if template and template.lang:
                lang = template.lang

        self = self.with_context(lang=lang)

        return {
            'name': 'Compose Email',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }


class HrHealthApplicant(models.Model):
    _name = "hr.health.applicant"
    _description = "Hr Applications"
    _rec_name = "checklist"

    employee_id = fields.Many2one("hr.applicant", string="Employee", help='Select corresponding Employee')
    checklist = fields.Char("Checklist")
    uploaded = fields.Boolean("Uploaded")
    verified = fields.Boolean("Verified")

    def set_to_draft(self):
        pass


class HrApplicantPromotion(models.Model):
    """
    Promotion / contract-creation workflow and the Recruitment Criteria
    sub-tables (Education Qualification / Experience / Competencies /
    Vacancies) on hr.applicant.
    """
    _inherit = 'hr.applicant'
    _description = "Job Position"

    qualification_id = fields.One2many('hr_qualification_info_applicant', 'applicant_id', 'Education Qualification')
    experiance_id = fields.One2many('hr_experience_info_applicant', 'applicant_id', 'Experiance')
    competencies_id = fields.One2many('hr_competencies_info_applicant', 'applicant_id', 'Competencies')
    hr_new_department_ids = fields.One2many('hr_new_department_info_applicant', 'applicant_id', 'Department Info')
    prmt_emp = fields.Selection([("Draft", "Draft"), ("Yes", "Yes")], string="Promote Employee", default="Draft")

    functions = fields.Selection([
        ('create_new_employee_from_applicant', 'Create New Employee From Applicant'),
        ('promote_employee', 'Promote Employee')
    ])
    responsible_display = fields.Char(string="Responsible", compute="_compute_user_id")

    def _compute_user_id(self):
        for val in self:
            usr = self.env["hr.job"].search([("name", "=", val.job_id.name)])
            val.responsible_display = val.user_id.name if val.user_id else ''
            return val.responsible_display

    def create_contract(self):
        if not self.employee_id:
            raise UserError('Please link an Employee to this applicant before creating a contract.')
        if not self.employment_start_date:
            raise UserError('Please specify the Employment Start Date')

        p_id = self.employee_id.id
        self.env.cr.execute('SELECT populate_emp_identification(%s)', (p_id,))
        self.env.cr.execute('SELECT create_new_employee_contract(%s)', (p_id,))
        self.env['hr.employee'].invalidate_model()
        self.env['hr.applicant'].invalidate_model()

    def promote_employee(self):
        self.functions = 'promote_employee'
        p_id = self.employee_id.id
        if not self.promotion_date:
            raise UserError('Please specify the Promotion Date')
        else:
            self.env.cr.execute('SELECT promote_employee(%s)', (p_id,))
            self.env['hr.employee'].invalidate_model()
        if self.application_type == "Internal":
            self.env["bb.internal"].create({
                'applicant_id': self.id,
                'applicant_name': self.partner_name
            })
        if self.application_type == "External":
            self.env["bb.external"].create({
                'applicant_id': self.id,
                'applicant_name': self.partner_name
            })
        self.ref_num()
        self.prmt_emp = "Yes"

    def ref_num(self):
        if self.application_type == "Internal":
            ref = self.env["bb.internal"].search([("applicant_id", "=", self.id)])
            self.internal_reference_no = str(ref.int_reference) + str("/2023/24")

        if self.application_type == "External":
            ref = self.env["bb.external"].search([("applicant_id", "=", self.id)])
            self.internal_reference_no = str(ref.ext_reference) + str("/2023/24")

    def create_new_employee_from_applicant(self):
        self.functions = 'create_new_employee_from_applicant'
        res = super(HrApplicantPromotion, self).create_employee_from_applicant()
        if res.get("res_id", False):
            employee_multi = self.env["hr.employee"].search([("id", "=", res.get("res_id", False))])
            qualifications_list = []
            for val in self.qualification_id:
                qualifications_list.append((0, 0, {"qualification": val.qualification, "requirement": val.requirement,
                                                   "response": val.response, "employee_id": employee_multi.id}))
            experience_list = []
            for val in self.experiance_id:
                experience_list.append((0, 0, {"experience": val.experience, "requirement": val.requirement,
                                               "response": val.response, "employee_id": employee_multi.id}))
            competencies_list = []
            for val in self.competencies_id:
                competencies_list.append((0, 0, {"competencies": val.competencies, "requirement": val.requirement,
                                                 "response": val.response, "employee_id": employee_multi.id}))

            employee_multi.write({"qualification_id": qualifications_list, "experiance_id": experience_list,
                                  "competencies_id": competencies_list})


class HrQualificationInfoApplicant(models.Model):
    _name = "hr_qualification_info_applicant"
    _description = "qualification Profile"
    _rec_name = "qualification"

    applicant_id = fields.Many2one('hr.applicant', string="Employee", help='Select corresponding Employee')
    qualification = fields.Char(string="Qualification")
    requirement = fields.Float(string="Requirement(CGPA)")
    response = fields.Float(string="Response")


class HrExperienceInfoApplicant(models.Model):
    _name = "hr_experience_info_applicant"
    _description = "experience Profile"
    _rec_name = "experience"

    applicant_id = fields.Many2one('hr.applicant', string="Employee", help='Select corresponding Employee')
    experience = fields.Char(string="Experience")
    requirement = fields.Float(string="Requirement(Years)")
    response = fields.Float(string="Response")


class HrCompetenciesInfoApplicant(models.Model):
    _name = "hr_competencies_info_applicant"
    _description = "Competencies Profile"
    _rec_name = "competencies"

    applicant_id = fields.Many2one('hr.applicant', string="Employee", help='Select corresponding Employee')
    competencies = fields.Char(string="Competencies")
    requirement = fields.Char(string="Requirement")
    response = fields.Char(string="Response")


class HrNewDepartmentInfoApplicant(models.Model):
    _name = "hr_new_department_info_applicant"
    _rec_name = "work_unit"

    applicant_id = fields.Many2one('hr.applicant', string="Employee", help='Select corresponding Employee')
    work_unit = fields.Many2one('operating.unit', string="Work Unit", help='Select Work Unit')
    number_of_vacancies = fields.Integer("Number of Vacancies")
    response = fields.Char(string="Response")