# -*- coding: utf-8 -*-
"""
hr_applicant.py
Extends the core hr.applicant model with custom recruitment fields required
by Bunna Bank's recruitment process (Internal / External recruitment journeys).
"""
from email.policy import default

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


# # ── Applicant qualification line ───────────────────────────────────────────
# class ApplicantQualificationLine(models.Model):
#     _name = 'applicant.qualification.line'
#     _description = 'Applicant Qualification Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     qualification = fields.Many2one(
#         'recruitment.qualification', string='Qualification',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
#     active = fields.Boolean(default=True)
# 
#     def unlink(self):
#         """ Soft delete: Archive records instead of removing from DB """
#         for rec in self:
#             rec.write({'active': False})
#         return True
# 
# 
# # ── Applicant experience line ──────────────────────────────────────────────
# class ApplicantExperienceLine(models.Model):
#     _name = 'applicant.experience.line'
#     _description = 'Applicant Experience Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     experience = fields.Many2one(
#         'recruitment.experience', string='Experience',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
# 
# 
# # ── Applicant competency line ──────────────────────────────────────────────
# class ApplicantCompetencyLine(models.Model):
#     _name = 'applicant.competency.line'
#     _description = 'Applicant Competency Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     competencies = fields.Many2one(
#         'recruitment.competency', string='Competency',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
#     active = fields.Boolean(default=True)
# 
#     def unlink(self):
#         """ Soft delete: Archive records instead of removing from DB """
#         for rec in self:
#             rec.write({'active': False})
#         return True


# ── hr.applicant extension ─────────────────────────────────────────────────
class HrApplicantCustom(models.Model):
    """Extends hr.applicant with Bunna Bank recruitment-specific fields."""
    _inherit = 'hr.applicant'

    # ── Application classification ─────────────────────────────────────────
    application_type = fields.Selection([
        ('Internal', 'Internal'),
        ('External', 'External'),
    ], string='Application Type', default='External',
        help='Whether this is an internal transfer/promotion or external hire.')

    app_reference = fields.Many2one(
        'job.vacancy', string='Vacancy Reference',
        help='Links this applicant to a specific job vacancy.',
    )
    vacancy_reference = fields.Char(
        string='Vacancy No.',
        related='app_reference.reference', store=True, readonly=True,
    )
    preferred_location = fields.Char(
        string='Preferred Location',
        help='Applicant preferred work location.',
    )
    candidate_score_id = fields.Many2one(
        'recruitment.candidate.score', string='Candidate Score',
        help='Link to the candidate score record for this applicant.',
    )

    # ── External ATS Candidate Profile Link ─────────────────────────────────
    candidate_profile_id = fields.Many2one(
        'candidate.profile',
        string='Candidate Master Profile',
        ondelete='set null',
        index=True,
        help='Link to the applicant\'s master candidate profile / electronic CV.',
    )
    cover_letter = fields.Text(
        string='Cover Letter',
        help='Vacancy-specific cover letter submitted by candidate.',
    )
    expected_salary = fields.Float(
        string='Expected Salary',
        help='Expected monthly salary in ETB.',
    )
    notice_period_days = fields.Integer(
        string='Notice Period (Days)',
        help='Notice period required with current employer.',
    )

    # ── Bunna-specific application status tracking ────────────────────────
    # NOTE: core hr.applicant already defines 'application_status' as a
    # computed field (ongoing/hired/refused/archived). We use a separate
    # field 'bunna_app_status' to track the Bunna recruitment workflow stage
    # without overriding the core field.
    bunna_app_status = fields.Selection([
        ('draft', 'Draft'),
        ('shortlisted', 'Shortlisted'),
        ('interview', 'Interview'),
        ('offer', 'Offer Issued'),
        ('hired', 'Hired'),
        ('rejected', 'Rejected'),
    ], string='Bunna Application Status', default='draft', tracking=True)

    job_offer_status = fields.Selection([
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ], string='Job Offer Status')

    rejection_reason = fields.Text(string='Rejection Reason')
    offer_letter_sent = fields.Boolean(string='Offer Letter Sent', default=False)
    contract_created_new = fields.Boolean(string='Contract Created', default=False)

    active_leave_status = fields.Char(
        string="Leave Status", compute="_compute_applicant_leave_status", store=False,
        help="Displays active leave status if applicant is currently an employee on leave."
    )
    active_disciplinary_status = fields.Selection(
        [
            ("none", "No Active Warning"),
            ("first_warning", "First Warning (Severity Level 4)"),
            ("second_warning", "Second Warning (Severity Level 3)"),
            ("last_written_warning", "Active Last Written Warning (Severity Level 1/2)"),
        ],
        string="Discipline Warning Level",
        compute="_compute_applicant_disciplinary_status",
        store=False,
        help="Pulled from Discipline Management (discipline.case) based on case severity levels."
    )

    @api.depends('internal_employee_id')
    def _compute_applicant_disciplinary_status(self):
        for rec in self:
            emp = rec.internal_employee_id
            if emp and 'discipline.case' in self.env:
                active_cases = self.env['discipline.case'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'enforced'),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or 'final_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'first_warning'
                    else:
                        rec.active_disciplinary_status = 'none'
                else:
                    rec.active_disciplinary_status = 'none'
            else:
                rec.active_disciplinary_status = 'none'

    @api.depends('internal_employee_id')
    def _compute_applicant_leave_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            emp = rec.internal_employee_id
            if emp:
                leaves = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leaves:
                    rec.active_leave_status = leaves.holiday_status_id.name if leaves.holiday_status_id else _("On Leave")
                else:
                    rec.active_leave_status = _("Active")
            else:
                rec.active_leave_status = _("N/A")


    def action_validate_completeness(self):
        """Validate applicant profile completeness. Automatically reject incomplete submissions."""
        for rec in self:
            missing = []
            if rec.application_type == 'External':
                if not (rec.partner_name or rec.name):
                    missing.append(_("Full Name"))
                if not rec.email_from:
                    missing.append(_("Email"))
                if not rec.partner_phone:
                    missing.append(_("Phone Number"))
                if not rec.gender:
                    missing.append(_("Gender"))
                if not rec.date_of_birth:
                    missing.append(_("Date of Birth"))
            elif rec.application_type == 'Internal':
                if not rec.internal_employee_id:
                    missing.append(_("Internal Employee"))

            if missing:
                reason = _("Rejected Incomplete Submission. Missing mandatory fields: %s") % ", ".join(missing)
                rec.write({
                    'bunna_app_status': 'rejected',
                    'rejection_reason': reason,
                    'active': False,
                })
                rec.message_post(body=reason)
                return False
        return True


    cv_attachment_id = fields.Many2one('ir.attachment', string='CV Attachment', compute='_compute_cv_attachment_id',
                                       store=False)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    def _compute_cv_attachment_id(self):
        for rec in self:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', rec.id)
            ], limit=1, order='id desc')
            rec.cv_attachment_id = att.id if att else False

    def action_download_cv(self):
        self.ensure_one()
        att = self.cv_attachment_id
        if not att:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', self.id)
            ], limit=1, order='id desc')
        if not att:
            raise ValidationError(_("No CV attachment found for this applicant."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{att.id}?download=true',
            'target': 'new',
        }

    # ── Personal information ───────────────────────────────────────────────
    date_of_birth = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    place_of_birth = fields.Char(string='Place of Birth')
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender')

    # ── Work history / suitability flags ──────────────────────────────────
    worked_in_bunna_earlier = fields.Boolean(
        string='Previously Worked at Bunna Bank', default=False,
    )
    current_company = fields.Char(string='Current Company')
    current_working_location = fields.Char(string='Current Working Location')
    working_status = fields.Selection([
        ('employed', 'Employed'),
        ('unemployed', 'Unemployed'),
        ('self_employed', 'Self-Employed'),
    ], string='Working Status', default='unemployed')
    willing_to_join_immediately = fields.Boolean(
        string='Willing to Join Immediately', default=False,
    )
    date_of_availability = fields.Date(string='Date of Availability')
    functions = fields.Char(string='Functions', help='Internal compute helper flag.')
    prmt_emp = fields.Char(string='Promote Employee Flag', default='No')

    # ── Internal applicant details ─────────────────────────────────────────
    # NOTE: the DB already has an 'internal_employee_name' varchar column with
    # stored employee names. We keep that as a Char field for backward-compat
    # and introduce 'internal_employee_id' (Many2one) with a different DB column.
    internal_employee_name = fields.Char(
        string='Internal Employee Name (Legacy)',
        help='Previously stored as free text. Kept for backward compatibility.',
    )
    internal_employee_id = fields.Many2one(
        'hr.employee', string='Internal Employee',
        help='Select the internal employee applying for this vacancy.',
    )
    employee_work_unit = fields.Char(
        string='Current Work Unit',
        compute='_compute_employee_work_unit',
        store=False, readonly=True,
    )
    employee_number = fields.Char(
        string='Employee ID',
        compute='_compute_employee_number',
        store=False, readonly=True,
    )
    employee_grade = fields.Char(string='Employee Grade')
    employee_position = fields.Char(string='Current Position')
    manager = fields.Many2one('hr.employee', string='Direct Manager')
    promotion_date = fields.Date(string='Last Promotion Date')
    employment_start_date = fields.Date(string='Employment Start Date')
    final_work_unit = fields.Many2one('hr.department', string='Assigned Work Unit', ondelete='set null')
    cc_workunits = fields.Many2many(
        'hr.department', string='CC Work Units',
        help="Additional departments CC'd on this application.",
    )

    # ── Qualifications / Experience / Competency tabs ─────────────────────
    qualification_id = fields.One2many(
        'hr_qualification_info_job', 'applicant_id',
        string='Education Qualifications',
    )
    experiance_id = fields.One2many(
        'hr_experience_info_job', 'applicant_id',
        string='Experience',
    )
    competencies_id = fields.One2many(
        'hr_competencies_info_job', 'applicant_id',
        string='Competencies',
    )
    hr_new_department_ids = fields.One2many(
        'hr_new_department_info_job', 'applicant_id',
        string='Vacancies',
    )

    # ── Computed fields ────────────────────────────────────────────────────
    @api.depends('date_of_birth')
    def _compute_age(self):
        from datetime import date
        today = date.today()
        for rec in self:
            if rec.date_of_birth:
                dob = rec.date_of_birth
                rec.age = (today - dob).days // 365
            else:
                rec.age = 0

    @api.depends('internal_employee_id')
    def _compute_employee_work_unit(self):
        for rec in self:
            rec.employee_work_unit = rec.internal_employee_id.department_id.name or ''

    @api.depends('internal_employee_id')
    def _compute_employee_number(self):
        for rec in self:
            rec.employee_number = rec.internal_employee_id.barcode or ''

    # ── Onchange: cascade vacancy reference fields ─────────────────────────
    @api.onchange('app_reference')
    def _onchange_app_reference(self):
        for rec in self:
            if rec.app_reference:
                rec.application_type = (
                    'Internal' if rec.app_reference.internal_movement_type in ('internal', 'promotion', 'lateral')
                    else 'External'
                )

    # ── Button actions ─────────────────────────────────────────────────────
    def create_contract(self):
        """Placeholder: triggers contract creation workflow."""
        self.write({'contract_created_new': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contract Created'),
                'message': _('Contract has been created for %s.') % self.partner_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def promote_employee(self):
        """Placeholder: triggers internal employee promotion workflow."""
        self.write({'prmt_emp': 'Yes'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employee Promoted'),
                'message': _('Promotion has been initiated for %s.') % self.partner_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_applicant_send(self):
        """Placeholder: triggers offer letter sending workflow."""
        self.write({'offer_letter_sent': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offer Letter Sent'),
                'message': _('Offer Letter has been sent for %s.') % self.partner_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.onchange('job_id')
    def _onchange_job_id_sync_criteria(self):
        if not self.job_id:
            return
        
        # Clear existing lines first
        self.qualification_id = [(5, 0, 0)]
        self.experiance_id = [(5, 0, 0)]
        self.competencies_id = [(5, 0, 0)]
        
        # Inherit qualifications
        qual_lines = []
        for line in self.job_id.qualification_id:
            qual_lines.append((0, 0, {
                'qualification': line.qualification.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.qualification_id = qual_lines
        
        # Inherit experiences
        exp_lines = []
        for line in self.job_id.experiance_id:
            exp_lines.append((0, 0, {
                'experience': line.experience.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.experiance_id = exp_lines
        
        # Inherit competencies
        comp_lines = []
        for line in self.job_id.competencies_id:
            comp_lines.append((0, 0, {
                'competencies': line.competencies.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.competencies_id = comp_lines


    def _auto_sync_external_recruitment_eligible(self):
        for app in self:
            if app.app_reference:
                rec_ext = self.env['employee.recruitment.external'].sudo().search([('vacancy_id', '=', app.app_reference.id)], limit=1)
                if not rec_ext:
                    rec_ext = self.env['employee.recruitment.external'].sudo().create({
                        'vacancy_id': app.app_reference.id,
                        'job_position': app.app_reference.job_position.id if app.app_reference.job_position else False,
                        'vacancy_reference': app.app_reference.reference,
                        'responsible': app.app_reference.responsible.id if app.app_reference.responsible else self.env.user.employee_id.id,
                    })
                
                existing = self.env['external.recruitment.eligible.employees'].sudo().search([
                    ('external_recruitment_id', '=', rec_ext.id),
                    ('applicant_name', '=', app.id),
                ], limit=1)
                
                if not existing:
                    cand = app.candidate_profile_id
                    self.env['external.recruitment.eligible.employees'].sudo().create({
                        'external_recruitment_id': rec_ext.id,
                        'applicant_name': app.id,
                        'applicant_email': app.email_from or (cand.email if cand else ''),
                        'applicant_phone': cand.phone if cand else (app.partner_phone or ''),
                        'date_of_birth': getattr(cand, 'dob', False) if cand else False,
                        'gender': getattr(cand, 'gender', False) if cand else False,
                        'highest_cgpa': getattr(cand, 'cgpa', 0.0) if cand else 0.0,
                        'total_experience': getattr(cand, 'total_experience', 0.0) if cand else 0.0,
                    })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('job_id') and not vals.get('qualification_id') and not vals.get('experiance_id') and not vals.get('competencies_id'):
                job = self.env['hr.job'].browse(vals['job_id'])
                
                # Qualifications
                qual_lines = []
                for line in job.qualification_id:
                    qual_lines.append((0, 0, {
                        'qualification': line.qualification.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if qual_lines:
                    vals['qualification_id'] = qual_lines
                    
                # Experiences
                exp_lines = []
                for line in job.experiance_id:
                    exp_lines.append((0, 0, {
                        'experience': line.experience.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if exp_lines:
                    vals['experiance_id'] = exp_lines
                    
                # Competencies
                comp_lines = []
                for line in job.competencies_id:
                    comp_lines.append((0, 0, {
                        'competencies': line.competencies.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if comp_lines:
                    vals['competencies_id'] = comp_lines
                    
        res = super().create(vals_list)
        res._auto_sync_external_recruitment_eligible()

        # Guarantee every applicant record is stored and linked under Master Candidate Profiles (CVs)
        for app in res:
            if not app.candidate_profile_id:
                email = (app.email_from or '').strip().lower()
                phone = (app.partner_phone or '').strip()
                name = app.partner_name or app.name or 'Unnamed Candidate'

                candidate = False
                if email:
                    candidate = self.env['candidate.profile'].sudo().search([('email', '=ilike', email)], limit=1)
                if not candidate and phone:
                    candidate = self.env['candidate.profile'].sudo().search([('phone', '=', phone)], limit=1)
                if not candidate and app.partner_id:
                    candidate = self.env['candidate.profile'].sudo().search([('partner_id', '=', app.partner_id.id)], limit=1)

                if not candidate:
                    partner = app.partner_id
                    if not partner and email:
                        partner = self.env['res.partner'].sudo().search([('email', '=ilike', email)], limit=1)
                    if not partner:
                        partner = self.env['res.partner'].sudo().create({
                            'name': name,
                            'email': email or False,
                            'phone': phone or False,
                        })
                    candidate = self.env['candidate.profile'].sudo().create({
                        'name': name,
                        'email': email or f'candidate_{app.id}@placeholder.com',
                        'phone': phone or '',
                        'partner_id': partner.id,
                    })

                app.sudo().write({'candidate_profile_id': candidate.id})
                candidate.sync_from_application(app)

        return res

    def write(self, vals):
        if 'job_id' in vals and vals.get('job_id'):
            job = self.env['hr.job'].browse(vals['job_id'])
            
            # Qualifications
            qual_lines = [(5, 0, 0)]
            for line in job.qualification_id:
                qual_lines.append((0, 0, {
                    'qualification': line.qualification.id,
                    'requirement': str(line.requirement or ''),
                    'response': str(line.response or ''),
                }))
            vals['qualification_id'] = qual_lines
                
            # Experiences
            exp_lines = [(5, 0, 0)]
            for line in job.experiance_id:
                exp_lines.append((0, 0, {
                    'experience': line.experience.id,
                    'requirement': str(line.requirement or ''),
                    'response': str(line.response or ''),
                }))
            vals['experiance_id'] = exp_lines
                
            # Competencies
            comp_lines = [(5, 0, 0)]
            for line in job.competencies_id:
                comp_lines.append((0, 0, {
                    'competencies': line.competencies.id,
                    'requirement': str(line.requirement or ''),
                    'response': str(line.response or ''),
                }))
            vals['competencies_id'] = comp_lines

        return super().write(vals)
