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
        self.job_id.write({
            'sourcing_type': 'external',
            'recruitment_type': 'External',
        })
        # Sync recruitment records (this will remove internal records for external sourcing)
        self.job_id._sync_published_vacancy_records
        # Run the external shortlist stored procedure
        self.env.cr.execute('SELECT external_candidates(%s)', (p_id,))


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
    qualification_ids = fields.Many2many(
        'external.applicant.education',
        'ext_shortlist_wizard_education_rel',
        'wizard_id', 'education_id',
        string='Required Study Qualifications',
        help='Select required education qualifications from registered candidate education records.'
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
        string='Required Certifications',
        help='Select required certifications from the configured recruitment certification list.'
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

    # ── Matching Logic ──────────────────────────────────────────────────────────

    def action_submit_criteria(self):
        self.ensure_one
        recruitment = self.recruitment_id

        candidates = recruitment.eligible_emp_external
        if not candidates:
            raise UserError(_("There are no registered eligible candidates for this recruitment process."))

        matched_candidates = []
        for candidate in candidates:

            # 1. CGPA check (only if minimum_cgpa > 0)
            if self.minimum_cgpa > 0:
                cand_cgpas = [candidate.highest_cgpa] if candidate.highest_cgpa else []
                for edu in candidate.education_ids:
                    if edu.cgpa:
                        cand_cgpas.append(edu.cgpa)
                max_cgpa = max(cand_cgpas) if cand_cgpas else 0.0
                if max_cgpa > 0 and max_cgpa < self.minimum_cgpa:
                    continue

            # 2. Relevant experience check (only if minimum_experience_years > 0)
            if self.minimum_experience_years > 0:
                exp = candidate.relevant_experience or candidate.total_experience or 0.0
                if exp > 0 and exp < self.minimum_experience_years:
                    continue

            # 3. Banking experience check (only if minimum_banking_experience > 0)
            if self.minimum_banking_experience > 0:
                b_exp = candidate.banking_experience or 0.0
                if b_exp > 0 and b_exp < self.minimum_banking_experience:
                    continue

            # 4. Supervisory experience check
            if self.minimum_supervisory_experience > 0:
                sup_exp = candidate.supervisory_experience or 0.0
                if sup_exp < self.minimum_supervisory_experience:
                    continue

            # 5. Study qualifications check
            if self.qualification_ids:
                req_quals = []
                for q in self.qualification_ids:
                    if q.field_of_study:
                        req_quals.append(q.field_of_study.strip.lower)
                    if q.level:
                        req_quals.append(str(q.level).strip.lower)

                cand_strings = []
                if candidate.field_of_study:
                    cand_strings.append(candidate.field_of_study.strip.lower)
                if candidate.educational_qualification:
                    cand_strings.append(str(candidate.educational_qualification).strip.lower)
                for edu in candidate.education_ids:
                    if edu.field_of_study:
                        cand_strings.append(edu.field_of_study.strip.lower)
                    if edu.level:
                        cand_strings.append(str(edu.level).strip.lower)

                match_qual = False
                for req in req_quals:
                    if any(req in s or s in req for s in cand_strings):
                        match_qual = True
                        break
                if not match_qual:
                    continue

            # 6. Skills check
            if self.skill_ids:
                req_skills = [s.name.strip.lower for s in self.skill_ids if s.name]
                cand_skills = [s.skill_name.strip.lower for s in candidate.skill_ids if s.skill_name]
                match_skill = any(
                    any(req in cs or cs in req for cs in cand_skills)
                    for req in req_skills
                )
                if not match_skill:
                    continue

            # 7. Certifications check
            if self.cert_ids:
                req_certs = [c.name.strip.lower for c in self.cert_ids if c.name]
                cand_certs = [c.name.strip.lower for c in candidate.certification_ids if c.name]
                match_cert = any(
                    any(req in cc or cc in req for cc in cand_certs)
                    for req in req_certs
                )
                if not match_cert:
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
                age = 0
                if candidate.applicant_age:
                    try:
                        age = int(candidate.applicant_age)
                    except (ValueError, TypeError):
                        pass
                elif candidate.date_of_birth:
                    today = datetime.now.date
                    age = today.year - candidate.date_of_birth.year - (
                        (today.month, today.day) < (candidate.date_of_birth.month, candidate.date_of_birth.day)
                    )
                if age > 0 and age > self.max_age:
                    continue

            # 13. Required Language check
            if self.required_language:
                cand_langs = [l.language for l in candidate.language_ids if l.language]
                if self.required_language not in cand_langs:
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
                })

        recruitment.write({'shortlisting_done': True})

        return {
            'name': _('External Recruitment Selected Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'external.recruitment.selected',
            'view_mode': 'form',
            'res_id': selected_rec.id,
            'target': 'current',
        }
