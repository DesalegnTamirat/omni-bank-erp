from odoo import api, models, fields, _
import logging

# Initialize the logger
_logger = logging.getLogger(__name__)


class RecruitmentProcessInternal(models.Model):
    _name = "employee.recruitment.internal"
    _inherit = "mail.thread"
    _description = "Internal Recruitment process"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)



    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.job_position.name or str(rec.id)

    job_position = fields.Many2one("hr.job", string="Job Position")
    job_location = fields.Char(string="Work Unit")
    job_grade = fields.Char(string="Grade")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id = fields.Integer(string="Work Unit Id")
    job_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    vacancy_reference = fields.Char(string="Vacancy Reference")
    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    relevant_experience = fields.Integer(string="Relevant Experience (Years)")
    highest_cgpa = fields.Integer(string="Highest CGPA")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    last_date_to_apply = fields.Date(string="Last Date To Apply")
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('notify', 'Notified')], string="Status")
    responsible = fields.Many2one('hr.employee', string="Responsible", required=True)
    eligible_emp = fields.One2many("internal.recruitment.eligible.employees", "internal_recruitment_id",
                                   string="Internal Recruitment")

    def populate_criteria(self):
        """
        Populates eligible candidates for this internal recruitment.
        Delegates to stored procedure public.internal_candidates_criteria.
        """
        for rec in self:
            _logger.info("[populate_criteria] Populating criteria for Internal Recruitment ID=%s", rec.id)
            target_id = rec.vacancy_id.id if rec.vacancy_id else False
            if not target_id and rec.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', rec.vacancy_reference)], limit=1)
                if vac:
                    target_id = vac.id
                    rec.write({'vacancy_id': vac.id})
            if not target_id:
                target_id = rec.id
            self.env.cr.execute('SELECT public.internal_candidates_criteria(%s)', (target_id,))


    def populate_promotion(self):
        p_id = self.id
        self.env.cr.execute('SELECT populate_months_since_promotion(%s)', (p_id,))

    def notify(self):
        p_id = self.id
        _logger.info("Starting notification process for Internal Recruitment ID: %s", self.id)
        
        # Create hr.applicant records in python for all selected eligible employees
        HrApplicant = self.env['hr.applicant']
        vac = self.env["job.vacancy"].search([("reference", "=", self.vacancy_reference)], limit=1)
        
        for val in self.eligible_emp:
            if val.select_flag and val.emp_name:
                existing = HrApplicant.search([
                    ('internal_employee_id', '=', val.emp_name.id),
                    ('job_id', '=', self.job_position.id),
                ], limit=1)
                
                emp_grade = val.emp_name.job_grade.grade_name if val.emp_name.job_grade else ''
                
                if not existing:
                    HrApplicant.create({
                        'partner_name': val.emp_name.name,
                        'email_from': val.emp_name.work_email or '',
                        'partner_phone': val.emp_name.mobile_phone or val.emp_name.work_phone or '',
                        'job_id': self.job_position.id,
                        'application_type': 'Internal',
                        'app_reference': vac.id if vac else False,
                        'internal_employee_id': val.emp_name.id,
                        'bunna_app_status': 'shortlisted',
                        'employee_grade': emp_grade,
                        'employee_position': val.emp_name.job_position.name if val.emp_name.job_position else '',
                        'active': True,
                    })

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT public.internal_applicant(%s)', (p_id,))
        except Exception:
            _logger.warning("Database stored procedure internal_applicant failed or does not exist. Bypassed since Python sync ran successfully.")

        work_units = []
        if vac:
            for rec in vac.hiring_details:
                if rec.work_unit:
                    work_units.append(rec.work_unit.name)
        work_units_str = ", ".join(work_units)

        Available = self.env['employee.recruitment.available']

        n = 0
        for val in self.eligible_emp:
            if val.select_flag and val.emp_name:
                n += 1
                emp_user = val.emp_name.user_id
                _logger.info("Notifying Employee: %s (User ID: %s)", val.emp_name.name, emp_user.id if emp_user else None)

                domain = [('vacancy_reference', '=', self.vacancy_reference)]
                if emp_user:
                    domain = [
                        ('vacancy_reference', '=', self.vacancy_reference),
                        '|', ('employee_id', '=', val.emp_name.id), ('employee_user_id', '=', emp_user.id)
                    ]
                else:
                    domain = [
                        ('vacancy_reference', '=', self.vacancy_reference),
                        ('employee_id', '=', val.emp_name.id)
                    ]

                existing = Available.search(domain, limit=1)
                avail_vals = {
                    'vacancy_id': vac.id if vac else (self.vacancy_id.id if hasattr(self, 'vacancy_id') and self.vacancy_id else False),
                    'vacancy_reference': self.vacancy_reference,
                    'job_position': self.job_position.name if self.job_position else False,
                    'job_location': self.job_location,
                    'employee_grade': self.job_grade,
                    'employee_category': self.job_category,
                    'type_of_employment': self.emp_type,
                    'number_of_vacancies': self.no_of_vacancies,
                    'vacancy_announced_on': self.vacancy_announced_on,
                    'last_date_to_apply': self.last_date_to_apply,
                    'job_description': vac.vacancy_description if vac else '',
                    'employee_id': val.emp_name.id,
                    'employee_user_id': emp_user.id if emp_user else False,
                    'employee_applicant': val.emp_name.name,
                    'application_status': 'New',
                }
                if existing:
                    existing.write(avail_vals)
                    avail_rec = existing
                else:
                    avail_rec = Available.create(avail_vals)

                if vac and vac.hiring_details:
                    avail_rec.employee_vacancy_ids.unlink()
                    vac_lines = [(0, 0, {
                        'operating_unit': h.work_unit.name if h.work_unit else False,
                        'number_of_vacancies': h.number_of_openings or 0,
                        'location_preference': 0,
                    }) for h in vac.hiring_details]
                    avail_rec.write({'employee_vacancy_ids': vac_lines})

                if emp_user and emp_user.partner_id:
                    self.mail_channel_msgs(emp_user.partner_id.id, self.job_position.name if self.job_position else '', self.last_date_to_apply, work_units_str)

        self.status = 'notify'
        return self.status

    def mail_channel_msgs(self, rec_id, ref, arg1, arg2):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = """Hi This is a Message from Bunna Bank HR <br><br>
                    You have been shortlisted for an Internal Recruitment position of <b><u>%s</u></b><br><br>
                    If you are interested, please apply before <b><u>%s</u></b> - The Vacancy is available in <b><u>%s</u></b><br><br>Thanks """ % (
            ref, arg1, arg2)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )


class EligibleEmployees(models.Model):
    _name = "internal.recruitment.eligible.employees"
    _description = "Eligible Employees"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)
    vacancy_id = fields.Many2one("job.vacancy", string="Job Vacancy", index=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    # FR-REC-056: Leave Status — cross-reference with Time Off module (hr.leave)
    # No new model created; reads directly from hr.leave for the linked employee.
    active_leave_status = fields.Char(
        string="Leave Status",
        compute="_compute_leave_status",
        store=False,
        help="Cross-references the Time Off module. Shows leave type (Annual, Medical, Maternity, etc.) "
             "if the employee has an approved leave covering today's date.",
    )

    @api.depends('emp_name')
    def _compute_leave_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            emp = rec.emp_name
            if emp:
                leave = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leave:
                    rec.active_leave_status = leave.holiday_status_id.name if leave.holiday_status_id else _("On Leave")
                else:
                    rec.active_leave_status = _("Active")
            else:
                rec.active_leave_status = _("N/A")

    emp_grade = fields.Char(string="Grade", compute="_compute_employee_details", store=True)
    emp_position = fields.Char(string="Position", compute="_compute_employee_details", store=True)
    emp_category = fields.Char(string="Category", compute="_compute_employee_details", store=True)
    emp_type = fields.Char(string="Employment Type", compute="_compute_employee_details", store=True)
    emp_gender = fields.Char(string="Gender", compute="_compute_employee_details", store=True)
    current_work_unit = fields.Char(string="Current Location", compute="_compute_employee_details", store=True)
    current_department = fields.Char(string="Current Department", compute="_compute_employee_details", store=True)
    service_in_company = fields.Float(string="Service in Company", readonly=True, compute="_compute_employee_details",
                                      store=True)
    educational_qualification = fields.Char(string="Educational Qualification", compute="_compute_employee_details",
                                            store=True)
    total_experience = fields.Float(string="Total Experience", readonly=True, compute="_compute_employee_details",
                                    store=True)
    supervisory_experience = fields.Float(string="Supervisory Experience", readonly=True,
                                          compute="_compute_employee_details", store=True)
    last_promotion = fields.Float(string="Months since last Promotion", readonly=True,
                                  compute="_compute_employee_details", store=True)
    pms_score = fields.Float(string="PMS Score", readonly=True, compute="_compute_employee_details", store=True)
    employment_experience = fields.Float(string="Employment Experience", readonly=True,
                                         compute="_compute_employee_details", store=True)

    current_location_exp = fields.Float(string="Current Location Experience")
    current_position_exp = fields.Float(string="Current Position Experience")
    app_date = fields.Date(string="Application Date")
    recommendation = fields.Float(string="Recommendation")

    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    cgpa = fields.Float(string="CGPA", readonly=True)
    relevant_experience = fields.Float(string="Relevant Experience", readonly=True)
    job_experience = fields.Float(string="Job Experience", readonly=True)
    preferred_location = fields.Char(string="Preferred Location")
    written_warning = fields.Float(string="Months since Written Warning", readonly=True)
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    select_flag = fields.Boolean(string="Select")
    target_position_id = fields.Integer(string="Target Position Id")
    internal_recruitment_id = fields.Many2one("employee.recruitment.internal", string="Internal Recruitment")

    @api.depends('emp_name')
    def _compute_employee_details(self):
        for record in self:
            if not record.emp_name:
                record.update({
                    'emp_grade': False, 'emp_position': False, 'emp_category': False,
                    'emp_type': False, 'emp_gender': False, 'current_work_unit': False,
                    'current_department': False, 'service_in_company': 0.0,
                    'total_experience': 0.0, 'pms_score': 0.0, 'last_promotion': 0.0
                })
                continue

            query = """ SELECT 
                              eg.grade_code AS emp_grade,
                              hj.name AS emp_position,
                              hj.employee_category AS emp_category,
                              hj.type_of_employment AS emp_type,
                              he.gender AS emp_gender,
                              ou.name AS current_work_unit,
                              icv.supervisory_experience,
                              icv.service_in_company,
                              icv.employment_experience,
                              icv.total_experience,
                              icv.educational_qualification, 
                              icv.name as current_department,
                              icv.last_promotion as last_promotion,
                              icv.pms_score
                              FROM hr_employee he
                              LEFT JOIN hr_job hj ON he.job_position = hj.id
                              LEFT JOIN employee_grade eg ON he.job_grade = eg.id
                              LEFT JOIN operating_unit ou ON he.default_operating_unit_id = ou.id
                              LEFT JOIN internal_candidates_v icv ON he.id = icv.employee_id
                              WHERE he.id = %s"""

            self.env.cr.execute(query, (record.emp_name.id,))
            res = self.env.cr.dictfetchone

            if res:
                record.update({
                    'emp_grade': res.get('emp_grade'),
                    'emp_position': res.get('emp_position'),
                    'emp_category': res.get('emp_category'),
                    'emp_type': res.get('emp_type'),
                    'emp_gender': res.get('emp_gender'),
                    'current_work_unit': res.get('current_work_unit'),
                    'current_department': res.get('current_department'),
                    'service_in_company': res.get('service_in_company') or 0.0,
                    'employment_experience': res.get('employment_experience') or 0.0,
                    'total_experience': res.get('total_experience') or 0.0,
                    'pms_score': res.get('pms_score') or 0.0,
                    'supervisory_experience': res.get('supervisory_experience') or 0.0,
                    'last_promotion': res.get('last_promotion') or 0.0,
                    'educational_qualification': res.get('educational_qualification'),
                })
            else:
                record.update({'emp_grade': False, 'emp_position': False})


class InternalSelectedCandidates(models.Model):
    _name = "internal.selected"
    _inherit = "mail.thread"
    _description = "Internal candidates Selection"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.job_position.name or str(rec.id)

    job_position = fields.Many2one("hr.job", string="Job Position")
    job_location = fields.Char(string="Work Unit")
    job_grade = fields.Char(string="Grade")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id = fields.Integer(string="Work Unit Id")
    job_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    relevant_experience = fields.Integer(string="Relevant Experience")
    highest_cgpa = fields.Integer(string="Highest CGPA")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('notify', 'Notified')], string="Status")
    eligible_sel_emp_internal = fields.One2many("internal.selected.employees", "internal_selected_id",
                                                string="Internal Selected Candidates for Recruitment")

    def notify(self):
        p_id = self.job_position.id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT internal_applicant(%s)', (p_id,))
        except Exception:
            _logger.warning("Database procedure internal_applicant failed or missing.")
        self.status = 'notify'
        return self.status


class InternalEligibleEmployees(models.Model):
    _name = "internal.selected.employees"
    _description = "Eligible Employees"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    # FR-REC-056: Leave Status — cross-reference with Time Off module (hr.leave)
    active_leave_status = fields.Char(
        string="Leave Status",
        compute="_compute_leave_status",
        store=False,
        help="Cross-references the Time Off module. Shows leave type (Annual, Medical, Maternity, etc.) "
             "if the employee has an approved leave covering today's date.",
    )

    @api.depends('emp_name')
    def _compute_leave_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            emp = rec.emp_name
            if emp:
                leave = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leave:
                    rec.active_leave_status = leave.holiday_status_id.name if leave.holiday_status_id else _("On Leave")
                else:
                    rec.active_leave_status = _("Active")
            else:
                rec.active_leave_status = _("N/A")

    emp_grade = fields.Char(string="Grade")
    emp_position = fields.Char(string="Position")
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    emp_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    emp_gender = fields.Char(string="Gender")
    current_work_unit = fields.Char(string="Current Location")
    service_in_company = fields.Float(string="Service in Company")
    educational_qualification = fields.Char(string="Educational Qualification")
    cgpa = fields.Float(string="CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(string="PMS Score")
    preferred_location = fields.Char(string="Preferred Location")
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    select_flag = fields.Boolean(string="Select")
    internal_selected_id = fields.Many2one("internal.selected", string="Internal Selected Candidates for Recruitment")


class InternalCandidatesV(models.Model):
    _name = 'internal.candidates.v'
    _table = 'internal_candidates_v'
    _auto = False
    _description = 'Internal Candidates View'

    employee_id = fields.Many2one('hr.employee', string='Employee')
    supervisory_experience = fields.Float(string='Supervisory Experience')
    current_position = fields.Char(string='Current Position')
    service_in_company = fields.Float(string='Service in Company')
    employment_experience = fields.Float(string='Employment Experience')
    total_experience = fields.Float(string='Total Experience')
    educational_qualification = fields.Char(string='Educational Qualification')
    name = fields.Char(string='Current Department')
    last_promotion = fields.Float(string='Months since last Promotion')
    pms_score = fields.Float(string='PMS Score')

    def init(self):
        pass



