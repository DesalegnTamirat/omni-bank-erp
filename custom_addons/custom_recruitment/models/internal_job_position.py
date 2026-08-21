from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from datetime import date


class InternalJobPosition(models.Model):
    _name = "employee.recruitment.available"
    _description = "Internal Job Position"
    _rec_name = "operating_unit"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    vacancy_reference = fields.Char(string="Vacancy Reference", readonly=True)
    vacancy_id = fields.Integer(string="Vacancy ID")
    recruitment_reference = fields.Char(string="Recruitment Reference", readonly=True)
    employee_applicant = fields.Char("Employee Applicant", readonly=True)
    operating_unit = fields.Char("Operating Unit", readonly=True)
    job_location = fields.Char("Work Unit")
    job_position = fields.Char("Job Position", readonly=True)
    employee_grade = fields.Char("Grade", readonly=True)
    employee_category = fields.Char("Employee Category", readonly=True)
    type_of_employment = fields.Char("Type of Employment")
    number_of_vacancies = fields.Integer("Number of Vacancies")
    vacancy_announced_on = fields.Date("Vacancy Announced On", readonly=True)
    last_date_to_apply = fields.Date("Last Date to Apply", readonly=True)
    job_description = fields.Text("Job Description", readonly=True)
    application_reason = fields.Text("Application Reason")
    allowance_difference = fields.Float("Difference in Allowance")
    employee_id = fields.Integer("Employee Id")
    preferred_location = fields.Many2one('operating.unit', string="Preferred Location")
    employee_user_id = fields.Integer("Employee User Id")
    job_position_id = fields.Integer("Job Position Id")
    application_status = fields.Char("Application Status", default='New')
    employee_vacancy_ids = fields.One2many('employee.vacancy.available', 'vacancy_id', 'Vacancy Info')
    rejection_reason = fields.Text("Rejection Reason")

    def apply(self):
        p_id = self.id
        today = date.today()
        n = 0
        x = 0
        for val in self.employee_vacancy_ids:
            if val:
                x = x + 1
                if val.location_preference > 0:
                    n = n + 1
        if x > 0:
            if n > 0:
                if self.last_date_to_apply and self.last_date_to_apply < today:
                    raise ValidationError(_('You cannot apply after the Last Date to Apply.'))
                else:
                    # Auto-fill employee_id if missing from the available vacancy record
                    for rec in self:
                        if not rec.employee_id:
                            emp = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
                            if not emp:
                                emp = self.env['hr.employee'].search([('create_uid', '=', self.env.uid)], limit=1)
                            if emp:
                                rec.write({
                                    'employee_id': emp.id,
                                    'employee_user_id': self.env.uid,
                                    'employee_applicant': emp.name,
                                })

                    self.env.cr.execute('SELECT internal_application(%s)', (p_id,))
                    self.env.invalidate_all()
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Application Submitted'),
                            'message': _('Your application has been successfully submitted.'),
                            'type': 'success',
                            'sticky': False,
                            'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                        }
                    }
            else:
                raise ValidationError(_('Please enter your preferences of work units.'))

    def accept_promotion(self):
        p_id = self.employee_id
        self.env.cr.execute('SELECT employee_notify_promotion_acceptance(%s)', (p_id,))

    def reject_promotion(self):
        p_id = self.employee_id
        self.env.cr.execute('SELECT employee_notify_promotion_rejection(%s)', (p_id,))

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE FUNCTION public.internal_application(p_id integer)
             RETURNS void
             LANGUAGE plpgsql
            AS $function$
            DECLARE
                rec_h record;
                rec_e record;
                rec_edu record;
                rec_j record;
                max_loc_id integer;
                min_loc_id integer;
                max_vacancy_id integer;
                pref_loc_id integer;
                v_nirs_id integer;
                combined_pref_location Text;
            BEGIN
                SELECT MAX(COALESCE(location_preference,0)) INTO max_loc_id 
                FROM employee_vacancy_available eva
                WHERE vacancy_id = p_id; 
                
                SELECT MIN(COALESCE(location_preference,0)) INTO min_loc_id 
                FROM employee_vacancy_available eva
                WHERE vacancy_id = p_id;
            
                SELECT MAX(id) INTO max_vacancy_id 
                FROM employee_vacancy_available 
                WHERE vacancy_id = p_id;
            
                SELECT STRING_AGG(a.operating_unit, ',') INTO combined_pref_location
                FROM (
                    SELECT operating_unit
                    FROM employee_vacancy_available
                    WHERE COALESCE(location_preference,0) > 0
                      AND vacancy_id = p_id
                    ORDER BY location_preference
                ) a;
            
                IF max_loc_id = 0 THEN 
                    pref_loc_id := max_vacancy_id;
                ELSIF max_loc_id > 0 THEN
                    -- Added LIMIT 1 to prevent CardinalityViolation when multiple locations share min_loc_id
                    SELECT id INTO pref_loc_id
                    FROM employee_vacancy_available 
                    WHERE location_preference = min_loc_id
                      AND vacancy_id = p_id
                    ORDER BY id LIMIT 1;
                END IF;
            
                FOR rec_h IN 
                    SELECT DISTINCT ON (era.id)
                           era.id AS recruitment_available_id,
                           CONCAT(he.name, ' - ', COALESCE(era.job_position, hj.name->>'en_US', 'Position')) AS application_name,
                           COALESCE(jv.job_position, era.job_position_id, hj.id) AS job_position_id,
                           CAST('Y' AS boolean) AS active, 
                           1 AS stage_id,
                           he.company_id,
                           COALESCE(era.employee_user_id, he.user_id) AS employee_user_id,
                           he.name AS partner_name,
                           he.work_phone,
                           he.mobile_phone,
                           he.department_id,
                           he.id AS emp_id,
                           'normal' AS kanban_state,
                           COALESCE(hj.create_date, NOW()) AS create_date,
                           he.create_uid,
                           COALESCE(hj.write_uid, he.write_uid) AS write_uid,
                           he.write_date,
                           he_responsible.user_id AS user_id2,
                           he.birthday,
                           he.place_of_birth,
                           he.gender,
                           'Bunna Bank' AS current_company,
                           'Yes' AS working_status,
                           CAST('Y' AS boolean) AS willing_to_join_immediately,
                           NULL AS date_of_availability,
                           ou.name AS employee_work_unit,
                           he.employee_identification AS employee_number,
                           eg.grade_name AS employee_grade,
                           COALESCE(hj.name->>'en_US', era.job_position) AS employee_position,
                           he.name AS internal_employee_name,
                           COALESCE((SELECT pms_score FROM internal_candidates_v WHERE employee_id = he.id LIMIT 1), 0.0) AS pms_score,
                           hd.name AS current_department,
                           COALESCE(era.vacancy_reference, jv.reference) AS vacancy_reference,
                           nirs.id AS new_int_sel_cand,
                           COALESCE(era.vacancy_id, jv.id) AS vacancy_id,
                           COALESCE(era.recruitment_reference, jv.recruitment_reference) AS recruitment_reference
                    FROM employee_recruitment_available era
                    JOIN hr_employee he ON (
                        (era.employee_id IS NOT NULL AND he.id = era.employee_id)
                        OR (era.employee_id IS NULL AND era.employee_user_id IS NOT NULL AND he.user_id = era.employee_user_id)
                        OR (era.employee_id IS NULL AND era.employee_user_id IS NULL AND (he.user_id = era.create_uid OR he.create_uid = era.create_uid))
                    )
                    LEFT JOIN hr_job hj ON he.job_position = hj.id
                    LEFT JOIN employee_grade eg ON he.job_grade = eg.id
                    LEFT JOIN hr_department hd ON he.department_id = hd.id
                    LEFT JOIN job_vacancy jv ON (era.vacancy_id = jv.id OR (era.vacancy_reference IS NOT NULL AND jv.reference = era.vacancy_reference))
                    LEFT JOIN hr_employee he_responsible ON jv.responsible = he_responsible.id
                    LEFT JOIN operating_unit ou ON he.default_operating_unit_id = ou.id
                    LEFT JOIN new_internal_recruitment_selected nirs ON (
                        (era.vacancy_reference IS NOT NULL AND nirs.vacancy_reference = era.vacancy_reference)
                        OR (era.vacancy_id IS NOT NULL AND nirs.vacancy_id = era.vacancy_id)
                    )
                    WHERE era.id = p_id
                LOOP
                    INSERT INTO hr_applicant (
                        id, job_id, active, stage_id, company_id, user_id,
                        partner_name, partner_phone, department_id, internal_employee_id, kanban_state,
                        create_uid, create_date, write_uid, write_date,
                        date_of_birth, place_of_birth, gender,
                        current_company, working_status, willing_to_join_immediately,
                        employee_grade, employee_position, internal_employee_name, application_type,
                        vacancy_reference, preferred_location
                    ) VALUES (
                        NEXTVAL('hr_applicant_id_seq'), rec_h.job_position_id,
                        rec_h.active, rec_h.stage_id, rec_h.company_id, rec_h.employee_user_id,
                        rec_h.partner_name, rec_h.mobile_phone, rec_h.department_id, rec_h.emp_id, rec_h.kanban_state,
                        rec_h.create_uid, (NOW()::TIMESTAMP(0)), rec_h.write_uid, (NOW()::TIMESTAMP(0)),
                        rec_h.birthday, rec_h.place_of_birth, rec_h.gender,
                        rec_h.current_company, rec_h.working_status, rec_h.willing_to_join_immediately,
                        rec_h.employee_grade, rec_h.employee_position,
                        rec_h.internal_employee_name, 'Internal', rec_h.vacancy_reference, combined_pref_location
                    );

                    -- Ensure header record exists in new_internal_recruitment_selected
                    v_nirs_id := rec_h.new_int_sel_cand;
                    IF v_nirs_id IS NULL THEN
                        SELECT id INTO v_nirs_id
                        FROM new_internal_recruitment_selected
                        WHERE (rec_h.vacancy_reference IS NOT NULL AND vacancy_reference = rec_h.vacancy_reference)
                           OR (rec_h.vacancy_id IS NOT NULL AND vacancy_id = rec_h.vacancy_id)
                        LIMIT 1;

                        IF v_nirs_id IS NULL THEN
                            v_nirs_id := NEXTVAL('new_internal_recruitment_selected_id_seq');
                            INSERT INTO new_internal_recruitment_selected (
                                id, vacancy_reference, vacancy_id, job_position, recruitment_reference,
                                create_uid, create_date, write_uid, write_date, active
                            ) VALUES (
                                v_nirs_id, rec_h.vacancy_reference, rec_h.vacancy_id, rec_h.job_position_id,
                                rec_h.recruitment_reference, rec_h.create_uid, (NOW()::TIMESTAMP(0)),
                                rec_h.write_uid, (NOW()::TIMESTAMP(0)), TRUE
                            );
                        END IF;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM new_internal_recruitment_selected_candidates
                        WHERE new_int_sel_cand = v_nirs_id AND emp_name = rec_h.emp_id
                    ) THEN
                        INSERT INTO new_internal_recruitment_selected_candidates (
                            id, new_int_sel_cand, emp_name, emp_position, current_work_unit, pms_score,
                            create_uid, create_date, write_uid, write_date, current_department, select_flag,
                            preferred_location, active
                        ) VALUES (
                            NEXTVAL('new_internal_recruitment_selected_candidates_id_seq'), v_nirs_id,
                            rec_h.emp_id, rec_h.employee_position, rec_h.employee_work_unit, rec_h.pms_score,
                            rec_h.create_uid, (NOW()::TIMESTAMP(0)), rec_h.write_uid, (NOW()::TIMESTAMP(0)),
                            rec_h.current_department, FALSE, combined_pref_location, TRUE
                        );
                    END IF;

                    -- Note: Education and previous occupation data remain on the employee record
                    -- and can be accessed via the hr.employee link (internal_employee_id)

                    UPDATE employee_recruitment_available 
                    SET application_status = 'Applied' 
                    WHERE id = rec_h.recruitment_available_id;
                END LOOP;
            END;
            $function$
        """)


class InternalJobVacancy(models.Model):
    _name = "employee.vacancy.available"
    _description = "Internal Job Vacancies"
    _rec_name = "operating_unit"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    vacancy_id = fields.Many2one('employee.recruitment.available', string="Employee Vacancy")
    employee_applicant = fields.Char("Employee Applicant")
    operating_unit = fields.Char("Work Unit", readonly=True)
    number_of_vacancies = fields.Integer("Number of Vacancies")
    location_preference = fields.Integer(string="Location Preference", help='Provide Location Preference',
                                         )
