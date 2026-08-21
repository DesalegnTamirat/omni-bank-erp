# -*- coding: utf-8 -*-


from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ExternalDefaultShortlistCriteria(models.Model):
    """
    Global default shortlisting criteria used across all external vacancies
    when HR selects 'Default Criteria' during shortlisting.
    Only one active record is expected (enforced by SQL constraint).
    """
    _name = 'external.default.shortlist.criteria'
    _description = 'Default External Shortlist Criteria'
    _rec_name = 'name'

    name = fields.Char(
        string='Criteria Name',
        required=True,
        default='Default Criteria',
        help='Descriptive name for this default criteria set.'
    )
    active = fields.Boolean(default=True)

    # ── Academic ────────────────────────────────────────────────────────────
    minimum_cgpa = fields.Float(
        string='Minimum CGPA',
        default=0.0,
        help='Minimum CGPA required. Set 0 to skip this check.'
    )
    minimum_education = fields.Selection(
        [('diploma', 'Diploma'),
         ('bachelor', "Bachelor's Degree"),
         ('master', "Master's Degree"),
         ('phd', 'PhD / Doctorate')],
        string='Minimum Education Level',
        help='Minimum academic qualification. Leave empty to skip.'
    )

    # ── Experience ───────────────────────────────────────────────────────────
    minimum_experience_years = fields.Float(
        string='Minimum Relevant Experience (Years)',
        default=0.0,
        help='Set 0 to skip.'
    )
    minimum_banking_experience = fields.Float(
        string='Minimum Banking Experience (Years)',
        default=0.0,
        help='Set 0 to skip.'
    )

    # ── Notes ────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes / Description')

    _sql_constraints = [
        ('unique_active_default', 'UNIQUE(active) WHERE active = TRUE',
         'Only one active Default Criteria record is allowed.'),
    ]

    def action_set_as_default(self):
        """Deactivate all other records and set this one as the active default."""
        self.env['external.default.shortlist.criteria'].search(
            [('id', '!=', self.id), ('active', '=', True)]
        ).write({'active': False})
        self.write({'active': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Default Criteria Set'),
                'message': _('"%s" is now the active default shortlisting criteria.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }


class ExternalShortlistChoiceWizard(models.TransientModel):
    """
    First-step wizard shown when HR clicks 'Shortlist Candidates'.
    Presents two choices:
      - Default Criteria : use the global ExternalDefaultShortlistCriteria
      - Specific Criteria: open the existing ExternalRecruitmentShortlistWizard
    """
    _name = 'external.shortlist.choice.wizard'
    _description = 'Shortlist Choice Wizard'

    recruitment_id = fields.Many2one(
        'employee.recruitment.external',
        string='Recruitment Process',
        required=True,
        ondelete='cascade',
        readonly=True
    )

    default_criteria_id = fields.Many2one(
        'external.default.shortlist.criteria',
        string='Default Criteria',
        domain=[('active', '=', True)],
        help='Select an active default shortlist criteria or create a new one.'
    )

    has_default_criteria = fields.Boolean(
        compute='_compute_default_criteria',
        help='True when at least one active default criteria record exists.'
    )

    # Summary fields shown in the wizard for preview and editing
    default_cgpa = fields.Float(related='default_criteria_id.minimum_cgpa', string='Min. CGPA')
    default_exp = fields.Float(related='default_criteria_id.minimum_experience_years', string='Min. Experience (Yrs)')
    default_bank_exp = fields.Float(related='default_criteria_id.minimum_banking_experience',
                                    string='Min. Banking Exp. (Yrs)')
    default_education = fields.Selection(
        related='default_criteria_id.minimum_education',
        string='Min. Education'
    )
    default_criteria_summary = fields.Char(
        string='Default Criteria Summary',
        compute='_compute_default_criteria',
        store=False
    )
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'default_criteria_id' in fields_list:
            active = self.env['external.default.shortlist.criteria'].search(
                [('active', '=', True)], limit=1
            )
            if active:
                res['default_criteria_id'] = active.id
        return res

    @api.depends('default_criteria_id')
    def _compute_default_criteria(self):
        active_criteria = self.env['external.default.shortlist.criteria'].search(
            [('active', '=', True)], limit=1
        )
        for rec in self:
            rec.has_default_criteria = bool(active_criteria)
            criteria = rec.default_criteria_id or active_criteria
            if criteria:
                summary_parts = []
                if criteria.minimum_education:
                    summary_parts.append(_('%s or higher') % dict(
                        diploma=_('Diploma'),
                        bachelor=_("Bachelor's Degree"),
                        master=_("Master's Degree"),
                        phd=_('PhD / Doctorate')
                    ).get(criteria.minimum_education, criteria.minimum_education))
                if criteria.minimum_cgpa > 0:
                    summary_parts.append(_('%s CGPA minimum') % criteria.minimum_cgpa)
                if criteria.minimum_experience_years > 0:
                    summary_parts.append(_('%s years total experience minimum') % criteria.minimum_experience_years)
                if criteria.minimum_banking_experience > 0:
                    summary_parts.append(_('%s years banking experience minimum') % criteria.minimum_banking_experience)
                rec.default_criteria_summary = ', '.join(summary_parts) if summary_parts else _(
                    'No active restrictions.')
            else:
                rec.default_criteria_summary = False

    def action_use_default_criteria(self):
        """Apply the global default criteria and run shortlisting immediately."""
        self.ensure_one()
        if not self.default_criteria_id:
            raise ValidationError(_(
                "No active Default Criteria is configured. "
                "Please go to Recruitment > Configuration > Default Shortlist Criteria "
                "and set up the default criteria first."
            ))

        criteria = self.default_criteria_id
        recruitment = self.recruitment_id

        candidates = recruitment.eligible_emp_external
        if not candidates:
            raise ValidationError(_(
                "There are no registered eligible candidates for this recruitment process."
            ))

        matched_candidates = []
        for candidate in candidates:

            # 1. Minimum education level check
            if criteria.minimum_education:
                level_order = {'diploma': 1, 'bachelor': 2, 'master': 3, 'phd': 4}
                req_rank = level_order.get(criteria.minimum_education, 0)
                cand_rank = level_order.get(candidate.educational_qualification, 0)
                # Also check education lines for highest level
                for edu in candidate.education_ids:
                    edu_rank = level_order.get(edu.level, 0)
                    if edu_rank > cand_rank:
                        cand_rank = edu_rank
                if cand_rank > 0 and cand_rank < req_rank:
                    continue

            # 2. CGPA check
            if criteria.minimum_cgpa > 0:
                cand_cgpas = [candidate.highest_cgpa] if candidate.highest_cgpa else []
                for edu in candidate.education_ids:
                    if edu.cgpa:
                        cand_cgpas.append(edu.cgpa)
                max_cgpa = max(cand_cgpas) if cand_cgpas else 0.0
                if max_cgpa > 0 and max_cgpa < criteria.minimum_cgpa:
                    continue

            # 3. Relevant experience check
            if criteria.minimum_experience_years > 0:
                exp = candidate.relevant_experience or candidate.total_experience or 0.0
                if exp > 0 and exp < criteria.minimum_experience_years:
                    continue

            # 4. Banking experience check
            if criteria.minimum_banking_experience > 0:
                b_exp = candidate.banking_experience or 0.0
                if b_exp > 0 and b_exp < criteria.minimum_banking_experience:
                    continue

            matched_candidates.append(candidate)

        if not matched_candidates:
            raise ValidationError(_(
                "No candidates match the default criteria. "
                "Consider using 'Specific Criteria' to adjust the requirements."
            ))

        # Find or create external.recruitment.selected
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

        # Insert matched candidates
        SelectedCand = self.env['external.recruitment.selected.candidates']
        added = 0
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
                added += 1

        # Mark shortlisting as done — hides the Shortlist button on the form
        recruitment.write({'shortlisting_done': True})

        return {
            'name': _('External Recruitment Selected Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'external.recruitment.selected',
            'view_mode': 'form',
            'res_id': selected_rec.id,
            'target': 'current',
        }

    def action_use_specific_criteria(self):
        """Open the existing specific criteria wizard for this recruitment."""
        self.ensure_one()
        return {
            'name': _('Define Shortlisting Criteria'),
            'type': 'ir.actions.act_window',
            'res_model': 'external.recruitment.shortlist.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_recruitment_id': self.recruitment_id.id,
                'default_minimum_cgpa': 0.0,
                'default_minimum_experience_years': 0.0,
                'default_minimum_banking_experience': 0.0,
            }
        }

    def action_open_default_criteria_config(self):
        self.ensure_one()
        return self.env.ref('custom_recruitment.action_external_default_shortlist_criteria').read()[0]
