from datetime import datetime
from dateutil import relativedelta

from odoo import models, api, fields, _
from odoo.exceptions import UserError


class external_candidate_details(models.TransientModel):
    _name = 'external.candidates'
    _description = 'External Candidates'

    job_id = fields.Many2one(
        "job.vacancy",
        string='Job Positions',
        domain=[('reference', '=like', 'BB/EXT/%'), ('vacancy_status', '=', 'published')]
    )

    def shortlist_external_candidates(self):
        # Validate using reference prefix for external vacancies
        if not self.job_id.reference or not self.job_id.reference.startswith('BB/EXT/'):
            raise UserError(_(
                "Please select an external vacancy (reference starting with 'BB/EXT/'). "
                "Use the internal shortlist wizard for internal vacancies."
            ))
        p_id = self.job_id.id
        # Ensure vacancy is marked as external only for external shortlist
        self.job_id.with_context(skip_lock_check=True).write({
            'sourcing_type': 'external',
            'recruitment_type': 'External',
        })

        # Sync recruitment records (this will remove internal records for external sourcing)
        self.job_id._sync_published_vacancy_records()
        # Run the external shortlist stored procedure
        self.env.cr.execute('SELECT public.external_candidates(%s)', (p_id,))



# ── Shortlist Wizard ──────────────────────────────────────────────────────────

class ExternalRecruitmentShortlistWizard(models.TransientModel):
    _name = 'external.recruitment.shortlist.wizard'
    _description = 'External Recruitment Shortlist Wizard'

    recruitment_id = fields.Many2one(
        'employee.recruitment.external', string='Recruitment Process',
        required=True, ondelete='cascade'
    )

    # ── Academic ────────────────────────────────────────────────────────────────
    minimum_cgpa = fields.Float(string='Minimum CGPA',
                                help='Candidates with CGPA >= this value pass. Set 0 to skip.')
    study_qualification_ids = fields.Many2many(
        'recruitment.field.of.study',
        'ext_shortlist_wizard_field_study_rel',
        'wizard_id', 'field_study_id',
        string='Required Study Qualifications',
        help='Select required fields of study / qualifications (from candidate_education). Candidate matches if their study qualification matches any selected.'
    )
    institution_ids = fields.Many2many(
        'recruitment.institution',
        'ext_shortlist_wizard_institution_rel',
        'wizard_id', 'institution_id',
        string='University / Institution',
        help='Select required universities or institutions (from candidate_education). Candidate matches if their educational institution matches any selected.'
    )

    # ── Experience ──────────────────────────────────────────────────────────────
    minimum_experience_years = fields.Float(
        string='Minimum Relevant Experience (Years)',
        help='Candidates with Relevant Experience >= this value pass. Set 0 to skip.'
    )
    minimum_banking_experience = fields.Float(
        string='Minimum Banking Experience (Years)',
        help='Candidates with Banking Sector experience >= this value pass. Set 0 to skip.'
    )
    minimum_supervisory_experience = fields.Float(
        string='Minimum Supervisory Experience (Years)',
        help='Candidates with Supervisory/Managerial experience >= this value pass. Set 0 to skip.'
    )

    # ── Skills & Certifications ──────────────────────────────────────────────────
    skill_ids = fields.Many2many(
        'recruitment.skill',
        'ext_shortlist_wizard_skill_rel',
        'wizard_id', 'skill_id',
        string='Required Skills',
        help='Select required skills from the configured recruitment skill list.'
    )
    cert_ids = fields.Many2many(
        'recruitment.certification',
        'ext_shortlist_wizard_cert_rel',
        'wizard_id', 'cert_id',
        string='Required Certifications (Optional)',
        help='Select required certifications (from candidate_certification). Optional filter — leave empty to skip.'
    )

    # ── Salary & Compensation Filter ────────────────────────────────────────────
    max_expected_salary = fields.Float(
        string='Maximum Expected Salary (ETB)',
        digits=(16, 2),
        help='Filter candidates with Expected Salary <= this amount. Accepts any numeric value. Set 0 to skip.'
    )
    max_current_salary = fields.Float(
        string='Maximum Current Salary (ETB)',
        digits=(16, 2),
        help='Filter candidates with Current Salary <= this amount. Accepts any numeric value. Set 0 to skip.'
    )

    # ── Personal & Demographics ─────────────────────────────────────────────────
    gender = fields.Selection([
        ('any', 'Any'),
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender Preference', default='any')

    max_age = fields.Integer(
        string='Maximum Age (Years)',
        help='Candidates older than this age will be filtered out. Set 0 to skip.'
    )

    # ── Employment Status & Preferences ─────────────────────────────────────────
    working_status = fields.Selection([
        ('any', 'Any'),
        ('employed', 'Currently Employed'),
        ('unemployed', 'Unemployed'),
        ('self_employed', 'Self-Employed'),
    ], string='Working Status', default='any')

    join_immediately = fields.Selection([
        ('any', 'Any'),
        ('yes', 'Yes (Willing to Join Immediately)'),
        ('no', 'No'),
    ], string='Willing to Join Immediately', default='any')

    ex_bunna = fields.Selection([
        ('any', 'Any'),
        ('yes', 'Ex-Bunna Employee Only'),
        ('no', 'Non-Ex-Bunna Only'),
    ], string='Ex-Bunna Employee', default='any')

    # ── Language Requirements ────────────────────────────────────────────────────
    required_language = fields.Selection([
        ('', 'Any Language'),
        ('english', 'English'),
        ('amharic', 'Amharic'),
        ('afaan_oromo', 'Afaan Oromo'),
        ('tigrinya', 'Tigrinya'),
        ('somali', 'Somali (Afaan Soomaali)'),
        ('sidama', 'Sidama'),
        ('wolaytta', 'Wolaytta'),
        ('hadiya', 'Hadiya'),
        ('guragigna', 'Guragigna'),
        ('afar', 'Afar'),
        ('bench', 'Bench'),
        ('dawro', 'Dawro'),
        ('awngi', 'Awngi'),
        ('gamo', 'Gamo'),
        ('konso', 'Konso'),
        ('arabic', 'Arabic'),
        ('french', 'French'),
    ], string='Required Language', default='')

    # ── Auto-Sync Master Data on Wizard Load ────────────────────────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        self._sync_master_data()
        return res

    @api.model
    def _sync_master_data(self):
        cr = self.env.cr
        # Sync Field of Study from candidate_education and external_applicant_education
        try:
            cr.execute("""
                SELECT DISTINCT trim(field_of_study) 
                FROM candidate_education 
                WHERE field_of_study IS NOT NULL AND trim(field_of_study) != ''
                UNION
                SELECT DISTINCT trim(qualification_name) 
                FROM candidate_education 
                WHERE qualification_name IS NOT NULL AND trim(qualification_name) != ''
                UNION
                SELECT DISTINCT trim(other_field_of_study) 
                FROM candidate_education 
                WHERE other_field_of_study IS NOT NULL AND trim(other_field_of_study) != ''
                UNION
                SELECT DISTINCT trim(field_of_study) 
                FROM external_applicant_education 
                WHERE field_of_study IS NOT NULL AND trim(field_of_study) != ''
            """)
            studies = [r[0] for r in cr.fetchall() if r[0]]
            for name in studies:
                if name and not self.env['recruitment.field.of.study'].search([('name', '=ilike', name.strip())], limit=1):
                    self.env['recruitment.field.of.study'].create({'name': name.strip()})
        except Exception:
            pass

        # Sync Institutions from candidate_education and external_applicant_education
        try:
            cr.execute("""
                SELECT DISTINCT trim(institution) 
                FROM candidate_education 
                WHERE institution IS NOT NULL AND trim(institution) != ''
                UNION
                SELECT DISTINCT trim(other_institution) 
                FROM candidate_education 
                WHERE other_institution IS NOT NULL AND trim(other_institution) != ''
                UNION
                SELECT DISTINCT trim(institution_name) 
                FROM external_applicant_education 
                WHERE institution_name IS NOT NULL AND trim(institution_name) != ''
            """)
            insts = [r[0] for r in cr.fetchall() if r[0]]
            for name in insts:
                if name and not self.env['recruitment.institution'].search([('name', '=ilike', name.strip())], limit=1):
                    self.env['recruitment.institution'].create({'name': name.strip()})
        except Exception:
            pass

        # Sync Certifications from candidate_certification and external_applicant_certification
        try:
            cr.execute("""
                SELECT DISTINCT trim(name) 
                FROM candidate_certification 
                WHERE name IS NOT NULL AND trim(name) != ''
                UNION
                SELECT DISTINCT trim(name) 
                FROM external_applicant_certification 
                WHERE name IS NOT NULL AND trim(name) != ''
            """)
            certs = [r[0] for r in cr.fetchall() if r[0]]
            for name in certs:
                if name and not self.env['recruitment.certification'].search([('name', '=ilike', name.strip())], limit=1):
                    self.env['recruitment.certification'].create({'name': name.strip()})
        except Exception:
            pass

    # ── Matching Logic ──────────────────────────────────────────────────────────

    def action_submit_criteria(self):
        self.ensure_one()
        recruitment = self.recruitment_id

        candidates = recruitment.eligible_emp_external
        if not candidates:
            raise UserError(_("There are no registered eligible candidates for this recruitment process."))

        matched_candidates = []
        for candidate in candidates:
            # 0. Resolve Candidate Profile
            prof = candidate.applicant_name.candidate_profile_id if candidate.applicant_name and hasattr(candidate.applicant_name, 'candidate_profile_id') and candidate.applicant_name.candidate_profile_id else False
            if not prof and candidate.applicant_email:
                prof = self.env['candidate.profile'].sudo().search([('email', '=ilike', candidate.applicant_email.strip())], limit=1)
            if not prof and candidate.applicant_name and candidate.applicant_name.email_from:
                prof = self.env['candidate.profile'].sudo().search([('email', '=ilike', candidate.applicant_name.email_from.strip())], limit=1)

            # Sync candidate lines from prof if missing
            if prof:
                vals_to_update = {}
                if not candidate.highest_cgpa and prof.latest_cgpa:
                    vals_to_update['highest_cgpa'] = prof.latest_cgpa
                if not candidate.banking_experience and prof.banking_experience:
                    vals_to_update['banking_experience'] = prof.banking_experience
                if not candidate.total_experience and prof.total_experience_years:
                    vals_to_update['total_experience'] = prof.total_experience_years
                if not candidate.relevant_experience:
                    vals_to_update['relevant_experience'] = (candidate.applicant_name.total_experience_years if candidate.applicant_name and hasattr(candidate.applicant_name, 'total_experience_years') and candidate.applicant_name.total_experience_years else prof.total_experience_years) or 0.0
                if not candidate.gender and prof.gender:
                    vals_to_update['gender'] = prof.gender
                if not candidate.working_status and prof.current_employment_status:
                    vals_to_update['working_status'] = prof.current_employment_status
                if not candidate.current_company and prof.current_company:
                    vals_to_update['current_company'] = prof.current_company
                if not candidate.date_of_birth and prof.date_of_birth:
                    vals_to_update['date_of_birth'] = prof.date_of_birth
                if not candidate.age and prof.age:
                    vals_to_update['age'] = prof.age
                if not candidate.applicant_phone and prof.mobile_phone:
                    vals_to_update['applicant_phone'] = prof.mobile_phone
                if not candidate.applicant_email and prof.email:
                    vals_to_update['applicant_email'] = prof.email
                if not candidate.education_ids and prof.education_ids:
                    edu_cmds = []
                    for edu in prof.education_ids:
                        edu_cmds.append((0, 0, {
                            'level': edu.education_level if edu.education_level in ['diploma', 'bachelor', 'master', 'phd'] else 'bachelor',
                            'field_of_study': edu.field_of_study or edu.other_field_of_study or edu.qualification_name or '',
                            'institution_name': edu.institution or edu.other_institution or '',
                            'graduation_date': edu.end_date or False,
                            'graduation_year': edu.end_date or False,
                            'cgpa': edu.cgpa or 0.0,
                        }))
                    if edu_cmds:
                        vals_to_update['education_ids'] = edu_cmds
                if not candidate.certification_ids and prof.certification_ids:
                    cert_cmds = []
                    for crt in prof.certification_ids:
                        cert_cmds.append((0, 0, {
                            'name': crt.name or '',
                            'issuing_organization': crt.issuing_organization or '',
                            'issue_date': crt.issue_date or False,
                            'expiry_date': crt.expiry_date or False,
                            'cert_url': crt.cert_url or '',
                        }))
                    if cert_cmds:
                        vals_to_update['certification_ids'] = cert_cmds
                if not candidate.skill_ids and prof.skill_ids:
                    skill_cmds = []
                    for sk in prof.skill_ids:
                        skill_cmds.append((0, 0, {
                            'skill_name': sk.name or '',
                            'proficiency': 'Proficient',
                        }))
                    if skill_cmds:
                        vals_to_update['skill_ids'] = skill_cmds
                if not candidate.work_history_ids and prof.experience_ids:
                    hist_cmds = []
                    for exp in prof.experience_ids:
                        hist_cmds.append((0, 0, {
                            'company_name': exp.organization or '',
                            'position_title': exp.position or '',
                            'start_date': exp.start_date or False,
                            'end_date': exp.end_date or False,
                            'is_current': exp.is_current or False,
                            'is_banking': exp.is_banking or False,
                            'reason_for_leaving': exp.reason_for_leaving or '',
                        }))
                    if hist_cmds:
                        vals_to_update['work_history_ids'] = hist_cmds
                
                if vals_to_update:
                    candidate.sudo().write(vals_to_update)

            # 1. CGPA check (only if minimum_cgpa > 0)
            if self.minimum_cgpa > 0:
                cand_cgpas = []
                if candidate.highest_cgpa:
                    cand_cgpas.append(candidate.highest_cgpa)
                for edu in candidate.education_ids:
                    if edu.cgpa:
                        cand_cgpas.append(edu.cgpa)
                if prof:
                    if prof.latest_cgpa:
                        cand_cgpas.append(prof.latest_cgpa)
                    for edu in prof.education_ids:
                        if edu.cgpa:
                            cand_cgpas.append(edu.cgpa)
                if candidate.applicant_name and hasattr(candidate.applicant_name, 'latest_cgpa') and candidate.applicant_name.latest_cgpa:
                    cand_cgpas.append(candidate.applicant_name.latest_cgpa)
                max_cgpa = max(cand_cgpas) if cand_cgpas else 0.0
                if max_cgpa > 0 and max_cgpa < self.minimum_cgpa:
                    continue

            # 2. Relevant experience check (only if minimum_experience_years > 0)
            if self.minimum_experience_years > 0:
                exp = candidate.relevant_experience or candidate.total_experience or (candidate.applicant_name.total_experience_years if candidate.applicant_name and hasattr(candidate.applicant_name, 'total_experience_years') else 0.0) or (prof.total_experience_years if prof else 0.0) or 0.0
                if exp > 0 and exp < self.minimum_experience_years:
                    continue

            # 3. Banking experience check (only if minimum_banking_experience > 0)
            if self.minimum_banking_experience > 0:
                b_exp = candidate.banking_experience or (prof.banking_experience if prof else 0.0) or 0.0
                if b_exp > 0 and b_exp < self.minimum_banking_experience:
                    continue

            # 4. Supervisory experience check
            if self.minimum_supervisory_experience > 0:
                sup_exp = candidate.supervisory_experience or (prof.supervisory_experience if prof else 0.0) or 0.0
                if sup_exp < self.minimum_supervisory_experience:
                    continue

            # 5. Study qualifications / Field of Study check (from candidate_education)
            if self.study_qualification_ids:
                req_quals = [q.name.strip().lower() for q in self.study_qualification_ids if q.name]
                cand_strings = []
                if candidate.field_of_study:
                    cand_strings.append(candidate.field_of_study.strip().lower())
                if candidate.educational_qualification:
                    cand_strings.append(str(candidate.educational_qualification).strip().lower())
                for edu in candidate.education_ids:
                    if edu.field_of_study:
                        cand_strings.append(edu.field_of_study.strip().lower())
                    if edu.level:
                        cand_strings.append(str(edu.level).strip().lower())
                if prof:
                    for edu in prof.education_ids:
                        if edu.field_of_study:
                            cand_strings.append(edu.field_of_study.strip().lower())
                        if edu.other_field_of_study:
                            cand_strings.append(edu.other_field_of_study.strip().lower())
                        if edu.qualification_name:
                            cand_strings.append(edu.qualification_name.strip().lower())
                        if edu.education_level:
                            cand_strings.append(str(edu.education_level).strip().lower())

                match_qual = False
                for req in req_quals:
                    if any(req in s or s in req for s in cand_strings if s):
                        match_qual = True
                        break
                if not match_qual:
                    continue

            # 5b. University / Institution check (from candidate_education)
            if self.institution_ids:
                req_insts = [i.name.strip().lower() for i in self.institution_ids if i.name]
                cand_insts = []
                if candidate.institution_name:
                    cand_insts.append(candidate.institution_name.strip().lower())
                for edu in candidate.education_ids:
                    if edu.institution_name:
                        cand_insts.append(edu.institution_name.strip().lower())
                if prof:
                    for edu in prof.education_ids:
                        if edu.institution:
                            cand_insts.append(edu.institution.strip().lower())
                        if edu.other_institution:
                            cand_insts.append(edu.other_institution.strip().lower())

                match_inst = False
                for req in req_insts:
                    if any(req in ci or ci in req for ci in cand_insts if ci):
                        match_inst = True
                        break
                if not match_inst:
                    continue

            # 6. Skills check
            if self.skill_ids:
                req_skills = [s.name.strip().lower() for s in self.skill_ids if s.name]
                cand_skills = [s.skill_name.strip().lower() for s in candidate.skill_ids if s.skill_name]
                if prof:
                    cand_skills.extend([s.name.strip().lower() for s in prof.skill_ids if s.name])
                match_skill = any(
                    any(req in cs or cs in req for cs in cand_skills if cs)
                    for req in req_skills
                )
                if not match_skill:
                    continue

            # 7. Certifications check (Optional — only filtered if cert_ids selected)
            if self.cert_ids:
                req_certs = [c.name.strip().lower() for c in self.cert_ids if c.name]
                cand_certs = [c.name.strip().lower() for c in candidate.certification_ids if c.name]
                if prof:
                    cand_certs.extend([c.name.strip().lower() for c in prof.certification_ids if c.name])
                if candidate.applicant_name and hasattr(candidate.applicant_name, 'candidate_certification_ids'):
                    cand_certs.extend([c.name.strip().lower() for c in candidate.applicant_name.candidate_certification_ids if c.name])
                if prof:
                    try:
                        self.env.cr.execute("SELECT trim(name) FROM candidate_certification WHERE candidate_id = %s AND active = TRUE", (prof.id,))
                        cand_certs.extend([r[0].strip().lower() for r in self.env.cr.fetchall() if r[0]])
                    except Exception:
                        pass
                match_cert = any(
                    any(req in cc or cc in req for cc in cand_certs if cc)
                    for req in req_certs
                )
                if not match_cert:
                    continue

            # 7b. Salary checks (Expected & Current Salary - accepts any number)
            if self.max_expected_salary > 0:
                cand_exp_sal = candidate.expected_salary or (candidate.applicant_name.expected_salary if candidate.applicant_name else 0.0) or 0.0
                if cand_exp_sal > 0 and cand_exp_sal > self.max_expected_salary:
                    continue

            if self.max_current_salary > 0:
                cand_cur_sal = candidate.current_salary or (candidate.applicant_name.current_salary if candidate.applicant_name and hasattr(candidate.applicant_name, 'current_salary') else 0.0) or (prof.current_salary if prof else 0.0) or 0.0
                if cand_cur_sal > 0 and cand_cur_sal > self.max_current_salary:
                    continue

            # 8. Gender check
            if self.gender and self.gender != 'any':
                if candidate.gender != self.gender:
                    continue

            # 9. Working Status check
            if self.working_status and self.working_status != 'any':
                if candidate.working_status != self.working_status:
                    continue

            # 10. Join Immediately check
            if self.join_immediately and self.join_immediately != 'any':
                if candidate.join_immediately != self.join_immediately:
                    continue

            # 11. Ex-Bunna check
            if self.ex_bunna == 'yes' and not candidate.ex_bunna:
                continue
            elif self.ex_bunna == 'no' and candidate.ex_bunna:
                continue

            # 12. Max Age check
            if self.max_age > 0:
                age = candidate.age or 0
                if not age:
                    if candidate.applicant_age:
                        try:
                            age = int(candidate.applicant_age)
                        except (ValueError, TypeError):
                            pass
                    elif candidate.date_of_birth:
                        today = fields.Date.today()
                        age = today.year - candidate.date_of_birth.year - (
                            (today.month, today.day) < (candidate.date_of_birth.month, candidate.date_of_birth.day)
                        )
                    elif prof and prof.age:
                        age = prof.age
                if age > 0 and age > self.max_age:
                    continue

            # 13. Required Language check
            if self.required_language:
                cand_langs = [l.language.lower() for l in candidate.language_ids if l.language]
                if prof:
                    cand_langs.extend([l.name.lower() for l in prof.language_ids if l.name])
                if self.required_language not in cand_langs and not any(self.required_language in cl for cl in cand_langs):
                    continue

            matched_candidates.append(candidate)

        if not matched_candidates:
            raise UserError(_("No candidates match the specified criteria. Please review the criteria and try again."))

        # ── Find or create external.recruitment.selected ─────────────────────
        SelectedRec = self.env['external.recruitment.selected']
        vacancy_int_id = recruitment.vacancy_id.id if recruitment.vacancy_id else 0
        selected_rec = SelectedRec.search([
            ('vacancy_reference', '=', recruitment.vacancy_reference)
        ], limit=1)
        if not selected_rec and vacancy_int_id:
            selected_rec = SelectedRec.search([
                ('vacancy_id', '=', vacancy_int_id)
            ], limit=1)

        if not selected_rec:
            delegation_lines = []
            if recruitment.vacancy_id:
                for member in recruitment.vacancy_id.vac_del_team_id:
                    role_map = 'member'
                    if member.role:
                        role_clean = member.role.lower().replace(' ', '_')
                        if role_clean in ['chair_person', 'member', 'secretary', 'member_secretary']:
                            role_map = role_clean
                    delegation_lines.append((0, 0, {
                        'role': role_map,
                        'employee_name': member.employee_name.id,
                        'alternate_committee_member': member.alternate_committee_member.id,
                        'status': 'active',
                    }))

            selected_rec = SelectedRec.create({
                'job_position': recruitment.job_position.id,
                'job_location': recruitment.job_location,
                'job_grade': recruitment.job_grade,
                'job_category': recruitment.job_category,
                'vacancy_announced_on': recruitment.vacancy_announced_on,
                'vacancy_reference': recruitment.vacancy_reference,
                'recruitment_reference': recruitment.recruitment_reference,
                'vacancy_id': vacancy_int_id,
                'no_of_vacancies': recruitment.no_of_vacancies,
                'recr_exter_selected_team_id': delegation_lines,
            })

        # ── Insert matched candidates (skip duplicates) ───────────────────────
        SelectedCand = self.env['external.recruitment.selected.candidates']
        for candidate in matched_candidates:
            existing = SelectedCand.search([
                ('ext_rec_sel_cand', '=', selected_rec.id),
                ('applicant_name', '=', candidate.applicant_name.id)
            ], limit=1)
            if not existing:
                SelectedCand.create({
                    'ext_rec_sel_cand': selected_rec.id,
                    'applicant_name': candidate.applicant_name.id,
                    'applicant_email': candidate.applicant_email,
                    'emp_gender': candidate.gender,
                    'educational_qualification': candidate.educational_qualification,
                    'cgpa': candidate.highest_cgpa,
                    'relevant_experience': candidate.relevant_experience,
                    'supervisory_experience': candidate.supervisory_experience,
                    'preferred_location': candidate.preferred_location,
                    'vacancy_id': vacancy_int_id,
                    'select_flag': True,
                    'selection_type': 'shortlisted',
                })
            if candidate.applicant_name:
                candidate.applicant_name.sudo().write({'bunna_app_status': 'shortlisted'})

        recruitment.write({'shortlisting_done': True})
        if recruitment.vacancy_id:
            recruitment.vacancy_id.sudo().write({
                'ext_selected_recruitment_id': selected_rec.id,
                'shortlist_done': True,
                'recruitment_step': 'notify_exam' if recruitment.vacancy_id.has_written_exam else 'notify_panel',
            })
            recruitment.vacancy_id._sync_selected_recruitment_records()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Shortlisting Completed'),
                    'message': _('External candidates shortlisting completed successfully for vacancy %s (%s candidates matched).') % (
                        recruitment.vacancy_id.reference, len(matched_candidates)),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

        return {
            'name': _('External Recruitment Selected Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'external.recruitment.selected',
            'view_mode': 'form',
            'res_id': selected_rec.id,
            'target': 'current',
        }
