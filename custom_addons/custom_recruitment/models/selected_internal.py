import os
import base64
import logging
from email.policy import default

from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
from .recruitment_offer_letter import amount_to_words_birr

# Initialize the logger
_logger = logging.getLogger(__name__)


def _format_clean_text(val):
    if not val:
        return False
    if isinstance(val, dict):
        return val.get('en_US') or (list(val.values())[0] if val.values() else False)
    if isinstance(val, str):
        s_val = val.strip()
        if 'en_US' in s_val or s_val.startswith('{'):
            import re
            m = re.search(r"en_US['\"]\s*:\s*['\"]([^'\"]+)", s_val)
            if m:
                return m.group(1)
            try:
                import ast, json
                parsed = ast.literal_eval(s_val) if s_val.startswith("{'") else json.loads(s_val)
                if isinstance(parsed, dict):
                    return parsed.get('en_US') or (list(parsed.values())[0] if parsed.values() else s_val)
            except Exception:
                pass
        return s_val
    return str(val)


def _update_employee_job_grade(emp, grade_val):
    if not emp or not grade_val:
        return
    
    vals = {}
    grade_rec = False

    if isinstance(grade_val, int):
        grade_rec = emp.env['employee.grade'].browse(grade_val)
    elif isinstance(grade_val, str) and grade_val.isdigit():
        grade_rec = emp.env['employee.grade'].browse(int(grade_val))
    
    if not grade_rec and isinstance(grade_val, str):
        g_str = grade_val.strip()
        grade_rec = emp.env['employee.grade'].search([
            '|', ('grade_name', '=ilike', g_str), ('grade_code', '=ilike', g_str)
        ], limit=1)
        if not grade_rec and 'grade' in g_str.lower():
            clean_str = g_str.lower().replace('grade', '').strip()
            grade_rec = emp.env['employee.grade'].search([
                '|', ('grade_name', '=ilike', clean_str), ('grade_code', '=ilike', clean_str)
            ], limit=1)

    if grade_rec and grade_rec.exists():
        if hasattr(emp, 'job_grade'):
            vals['job_grade'] = grade_rec.id
        if hasattr(emp, 'grade'):
            vals['grade'] = grade_rec.id

    if hasattr(emp, 'emp_grade'):
        vals['emp_grade'] = str(grade_val)

    if vals:
        emp.write(vals)


def _update_pbms_and_operating_unit_counts(env, operating_unit_id, job_id, count=1):
    """
    Increments fulfilled_quantity on pbms.plan.category.line
    and recomputes operating.unit.job.position metrics for (operating_unit_id, job_id).
    """
    if not operating_unit_id or not job_id:
        return

    ou_id = operating_unit_id.id if hasattr(operating_unit_id, 'id') else operating_unit_id
    j_id = job_id.id if hasattr(job_id, 'id') else job_id

    if 'pbms.plan.category.line' in env:
        PbmsLine = env['pbms.plan.category.line'].sudo()
        lines = PbmsLine.search([
            ('line_type', '=', 'manpower'),
            ('org_unit_id', '=', ou_id),
            ('job_id', '=', j_id),
        ])
        for line in lines:
            curr_fulfilled = line.fulfilled_quantity or 0
            line.write({'fulfilled_quantity': curr_fulfilled + count})

    if 'operating.unit.job.position' in env:
        OUJobPos = env['operating.unit.job.position'].sudo()
        pos_lines = OUJobPos.search([
            ('operating_unit_id', '=', ou_id),
            ('job_position_id', '=', j_id),
        ])
        if pos_lines:
            pos_lines._recompute_all_counts()


class NewInternalRecruitmentSelected(models.Model):
    _name = "new.internal.recruitment.selected"
    _description = "New Internal Recruitment Selected"
    _inherit = "mail.thread"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Prohibit hard deletion of recruitment selection records for compliance """
        raise UserError(_("Deletion of recruitment selection records is strictly prohibited for audit integrity. You may archive records instead."))

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
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company", default=1)
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice", default=12)
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion", default=12)
    minimum_pms_score = fields.Float(string="Minimum PMS Score", default=75.0)
    transfer_eval_mode = fields.Selection([
        ('standard', 'Standard (Exam + Interview)'),
        ('interview_only', 'Interview Only'),
        ('transfer_matrix_only', 'Transfer Matrix Only'),
    ], string='Transfer Evaluation Mode', default='transfer_matrix_only')
    supervisor_rec_requested = fields.Boolean(string="Supervisor Recommendation Requested", default=False)
    app_date_weight = fields.Float(string="Application Date Weight (%)", default=20.0)
    experience_weight = fields.Float(string="Experience Weight (%)", default=20.0)
    location_weight = fields.Float(string="Location Weight (%)", default=20.0)
    recommendation_weight = fields.Float(string="Recommendation Weight (%)", default=10.0)
    status = fields.Selection([('draft', 'Draft'), ('shortlist', 'Shortlisted'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status", default='draft')
    state = fields.Selection([('draft', 'Draft'), ('shortlist', 'Shortlisted'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="State", default='draft')
    exam_candidate_summary = fields.Text(
        string="Exam & Selected Candidates Summary",
        help="Summary regarding exams (written & interview) and selected candidates for the Approval Committee review."
    )

    committee_notified = fields.Boolean(string="Committee Notified", default=False)
    minute_signed = fields.Boolean(string="Minute Signed", default=False)
    employees_promoted = fields.Boolean(string="Employees Promoted", default=False)

    def _auto_init(self):
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    ALTER TABLE new_internal_recruitment_selected 
                    ADD COLUMN IF NOT EXISTS approval_hierarchy_type VARCHAR,
                    ADD COLUMN IF NOT EXISTS chairperson_id INT4,
                    ADD COLUMN IF NOT EXISTS panel_member_id INT4,
                    ADD COLUMN IF NOT EXISTS secretary_id INT4,
                    ADD COLUMN IF NOT EXISTS observer_id INT4;

                    UPDATE new_internal_recruitment_selected 
                    SET state = 'notify',
                        status = 'notify'
                    WHERE state IS NULL OR state IN ('', 'draft')
                       OR status IS NULL OR status IN ('', 'draft');

                    UPDATE new_internal_recruitment_selected_candidates 
                    SET promotion_status = COALESCE(NULLIF(promotion_status, ''), 'draft'),
                        selection_type = 'pending'
                    WHERE selection_type IS NULL 
                       OR selection_type = '' 
                       OR (selection_type IN ('selected', 'Selected') AND (rank IS NULL OR rank = 0) AND (weighted_score IS NULL OR weighted_score = 0));
                """)
        except Exception as e:
            _logger.warning("Safe update on new_internal_recruitment_selected: %s", e)
        return res
    panel_notified = fields.Boolean(string="Panel Notified", default=False)
    exam_scores_fetched = fields.Boolean(string="Exam Scores Fetched", default=False)
    interview_scores_fetched = fields.Boolean(string="Interview Scores Fetched", default=False)
    scores_computed = fields.Boolean(string="Scores Computed", default=False)
    selection_notified = fields.Boolean(string="Selection Notified", default=False)
    vacancy_reference = fields.Char(string="Vacancy Reference")
    vacancy_id = fields.Integer(string="Vacancy ID")

    has_delegation_requests = fields.Boolean(
        compute='_compute_has_delegation_requests',
        string="Has Delegation Requests"
    )

    @api.depends('new_int_rec_panel.delegation_state', 'new_int_rec_panel.response_status')
    def _compute_has_delegation_requests(self):
        for rec in self:
            rec.has_delegation_requests = any(
                (line.delegation_state and line.delegation_state != 'draft') or line.response_status == 'delegation_requested'
                for line in rec.new_int_rec_panel
            )

    show_reschedule_button = fields.Boolean(
        compute='_compute_show_reschedule_button',
        string="Show Reschedule Button"
    )

    @api.depends('panel_notified', 'new_int_rec_panel.response_status')
    def _compute_show_reschedule_button(self):
        for rec in self:
            if not rec.panel_notified or not rec.new_int_rec_panel:
                rec.show_reschedule_button = False
            else:
                rec.show_reschedule_button = any(
                    line.response_status in ['unavailable', 'reschedule_requested']
                    for line in rec.new_int_rec_panel
                )

    # ── Per-vacancy configurable assessment weights ─────────────────────────
    # HR configures these BEFORE computing the final score.
    # They override the global weight matrix for this specific vacancy.
    pms_weight = fields.Float(
        string="PMS Weight (%)", default=40.0, digits=(5, 2),
        help="Weight % for PMS score in the final weighted score formula."
    )
    written_weight = fields.Float(
        string="Written Exam Weight (%)", default=30.0, digits=(5, 2),
        help="Weight % for Written Exam score in the final weighted score formula."
    )
    interview_weight = fields.Float(
        string="Interview Weight (%)", default=30.0, digits=(5, 2),
        help="Weight % for Interview score in the final weighted score formula."
    )

    @api.onchange("job_category", "job_position", "transfer_eval_mode")
    def _onchange_set_internal_brd_default_weights(self):
        """
        BRD Matrix Default Auto-Population:
        - Transfer / Lateral: 30% PMS + 20% App Date + 20% Exp + 20% Loc + 10% Rec
        - Managerial: 60% PMS + 40% Interview (0% Exam)
        - Non-Managerial: 40% PMS + 30% Exam + 30% Interview
        - Junior: 50% PMS + 25% Exam + 25% Interview
        """
        is_transfer = self.transfer_eval_mode == 'transfer_matrix_only' or (
            self.vacancy_id and getattr(self.vacancy_id, 'internal_movement_type', False) in ('lateral', 'transfer')
        )
        if is_transfer:
            self.pms_weight = 30.0
            self.app_date_weight = 20.0
            self.experience_weight = 20.0
            self.location_weight = 20.0
            self.recommendation_weight = 10.0
            self.written_weight = 0.0
            self.interview_weight = 0.0
            return

        cat_str = (self.job_category or "").lower()
        if "managerial" in cat_str and "non" not in cat_str:
            self.pms_weight = 60.0
            self.written_weight = 0.0
            self.interview_weight = 40.0
        elif "junior" in cat_str:
            self.pms_weight = 50.0
            self.written_weight = 25.0
            self.interview_weight = 25.0
        else:
            self.pms_weight = 40.0
            self.written_weight = 30.0
            self.interview_weight = 30.0
    written_exam_date = fields.Datetime(string="Written Exam Date")
    exam_location=fields.Text(string="Exam Location")
    interview_accepted_count = fields.Float(string="Interview Accepted Count")
    exam_scheduled = fields.Selection([('Yes', 'Yes'),
                                            ('No', 'No')], string="Exam Scheduled", default='No')
    interview_scheduled = fields.Selection([('Yes', 'Yes'),
                                       ('No', 'No')], string="Interview Scheduled",default='No')
    interview_date = fields.Datetime(string="Interview Date")
    interview_location = fields.Text(string="Interview Location")
    promotion_revocation_days=fields.Date(string="Promotion Revocation Days")
    new_int_rec_sel = fields.One2many("new.internal.recruitment.selected.candidates", "new_int_sel_cand", string="Selected candidates for Recruitment")
    new_int_rec_panel = fields.One2many("new.internal.recruitment.panel", "new_int_panel",string="Selected Panel for Recruitment")
    recr_selected_team_id = fields.One2many("new.recrt.delegation.team", "new_rec_del_id", string="Internal Recruitment Selected Delegation Team")

    approval_hierarchy_type = fields.Selection(
        [
            ("ho_district_grade2_plus", "Head Office & District Grade II and above"),
            ("non_managerial_ho", "For all non-managerial head office"),
            ("non_managerial_district", "For all non-managerial district"),
        ],
        string="Approval Hierarchy Category",
        tracking=True,
    )
    chairperson_id = fields.Many2one("res.users", string="Chairperson", tracking=True)
    panel_member_id = fields.Many2one("res.users", string="Panel Member", tracking=True)
    secretary_id = fields.Many2one("res.users", string="Panel Member & Secretary", tracking=True)
    observer_id = fields.Many2one(
        "res.users", string="Labor Representative (Observer)", tracking=True,
        help="Observer role (optional to sign)"
    )

    def _get_partner_for_employee(self, emp):
        if not emp:
            return False
        if getattr(emp, 'user_id', False) and emp.user_id.partner_id:
            return emp.user_id.partner_id
        if getattr(emp, 'work_contact_id', False):
            return emp.work_contact_id
        if getattr(emp, 'name', False):
            partner = self.env["res.partner"].search([("name", "=", emp.name)], limit=1)
            if partner:
                return partner
        return False

    def _get_partner_for_user(self, user):
        if not user:
            return False
        if getattr(user, 'partner_id', False):
            return user.partner_id
        if getattr(user, 'name', False):
            partner = self.env["res.partner"].search([("name", "=", user.name)], limit=1)
            if partner:
                return partner
        return False

    total_candidates_count = fields.Integer(string="Total Applicants", compute="_compute_candidate_counts")
    selected_candidates_count = fields.Integer(string="Selected", compute="_compute_candidate_counts")
    reserve_candidates_count = fields.Integer(string="Reserve Pool", compute="_compute_candidate_counts")
    disqualified_candidates_count = fields.Integer(string="Disqualified", compute="_compute_candidate_counts")

    @api.depends("new_int_rec_sel", "new_int_rec_sel.selection_type")
    def _compute_candidate_counts(self):
        for rec in self:
            cands = rec.new_int_rec_sel
            rec.total_candidates_count = len(cands)
            rec.selected_candidates_count = len(cands.filtered(lambda c: c.selection_type in ('selected', 'Selected')))
            rec.reserve_candidates_count = len(cands.filtered(lambda c: c.selection_type in ('reserve', 'reserved', 'Reserve', 'Reserved')))
            rec.disqualified_candidates_count = len(cands.filtered(lambda c: c.selection_type in ('rejected', 'Disqualified')))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.vacancy_id or rec.vacancy_reference:
                self.env.cr.execute("""
                    UPDATE job_vacancy
                    SET selected_recruitment_id = %s
                    WHERE id = %s OR (reference IS NOT NULL AND reference = %s)
                """, (rec.id, rec.vacancy_id or 0, rec.vacancy_reference or ''))
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.vacancy_id or rec.vacancy_reference:
                self.env.cr.execute("""
                    UPDATE job_vacancy
                    SET selected_recruitment_id = %s
                    WHERE id = %s OR (reference IS NOT NULL AND reference = %s)
                """, (rec.id, rec.vacancy_id or 0, rec.vacancy_reference or ''))
        return res

    def notify(self):
        if not self.scores_computed:
            raise UserError(_("Sequence Error: You must compute & rank final scores ('Compute Final Scores') before notifying approvers."))
        selected_cands = self.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        if not selected_cands:
            raise UserError(_("No candidates have passed both the examination and interview assessments (minimum 50% required in each stage). Cannot proceed to notify the approval committee."))
        if not self.recr_selected_team_id or not self.recr_selected_team_id.filtered(lambda t: t.employee_name or t.alternate_committee_member):
            raise UserError(_("Please add committee members in the Committee / Delegation Team tab before notifying approvers."))
        p_id = self.id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT job_vacancy_minute(%s)', (p_id,))
        except Exception as e:
            _logger.warning("Stored procedure job_vacancy_minute failed: %s", e)
        for com in self.recr_selected_team_id:
            usr = False
            if com.employee_name:
                usr = self._get_partner_for_user(com.employee_name)
            elif com.alternate_committee_member:
                usr = self._get_partner_for_user(com.alternate_committee_member)
            if usr:
                self.mail_channel_msgs(usr.id, self.vacancy_reference or '', self.job_position.name if self.job_position else '')
        self.status = "notify"
        self.state = "notify"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approvers Notified'),
                'message': _('Committee members have been notified for internal vacancy selection approval.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = arg1 or self._get_position_title()
        message = (
            f"Dear Committee,\n\n"
            f"Candidates have been shortlisted for internal selection:\n\n"
            f"• Position: {pos_title}\n"
            f"• Reference: {ref or ''}\n\n"
            f"Kindly review and approve."
        )
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def evaluate(self):
        if self.state not in ('notify', 'evaluate', 'approved'):
            raise UserError(_("Sequence Error: You must notify approvers ('Notify Approvers') before approving the selection."))
        selected_cands = self.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        if not selected_cands:
            raise UserError(_("Cannot approve selection because no candidates passed the examination and interview assessments."))
        n = 0
        usr_name = self.env.user.name
        for val in self.recr_selected_team_id:
            if val.status == "unavailable":
                if val.alternate_committee_member and val.alternate_committee_member.name == usr_name:
                    n += 1
                    val.approve = True
                    break
            else:
                if val.employee_name and val.employee_name.name == usr_name:
                    n += 1
                    val.approve = True
                    break
        if n == 0 and self.recr_selected_team_id:
            if self.env.user.has_group('hr.group_hr_manager'):
                for val in self.recr_selected_team_id:
                    val.approve = True
            else:
                raise ValidationError(_("Sorry!! You are not assigned as an evaluator for this selection."))
        self.status = "evaluate"
        self.state = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved'),
                'message': _('Internal selection process has been successfully approved!'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _format_date_time_parts(self, dt):
        if not dt:
            return ('TBD', 'TBD')
        try:
            if isinstance(dt, str):
                dt = fields.Datetime.to_datetime(dt)
            return (dt.strftime('%b %d, %Y'), dt.strftime('%I:%M %p'))
        except Exception:
            return (str(dt), '')

    def mail_channel_msgs_exam(self, rec_id, emp, position, date, location, work_unit=None):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        unit_str = work_unit or self._get_hiring_work_units()
        date_part, time_part = self._format_date_time_parts(date)
        loc_str = location or 'Main Branch'
        message = (
            f"Dear {emp},\n\n"
            f"You have been selected for written exam assessment for the position of {pos_title} for {unit_str} work unit. "
            f"Your exam is scheduled for {date_part} at {time_part} at {loc_str}. "
            f"Please confirm your attendance through the ERP portal.\n\n"
            f"Best of luck!"
        )
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def mail_channel_msgs_interview(self, rec_id, emp, position, date, location, work_unit=None):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        unit_str = work_unit or self._get_hiring_work_units()
        date_part, time_part = self._format_date_time_parts(date)
        loc_str = location or 'Head Office'
        message = (
            f"Dear {emp},\n\n"
            f"You have been selected for an interview assessment for the position of {pos_title} for {unit_str} work unit. "
            f"Your interview is scheduled for {date_part} at {time_part} at {loc_str}.\n\n"
            f"Best of luck!"
        )
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_written_exam(self):
        if not self.new_int_rec_sel:
            raise UserError(_("No candidates found in the shortlisted selection list. Please shortlist candidates first."))
        registered_cands = self.new_int_rec_sel.filtered(lambda c: c.emp_name and c.select_flag and c.selection_type != 'rejected')
        if not registered_cands:
            raise UserError(_("No registered/eligible candidates found to notify for the written exam. Please shortlist active candidates first."))
        if not self.written_exam_date:
            vac = False
            if self.vacancy_id:
                vac = self.env['job.vacancy'].browse(self.vacancy_id)
            elif self.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
            if vac and vac.exists() and vac.written_exam_date:
                self.written_exam_date = vac.written_exam_date
                if not self.exam_location and vac.exam_location:
                    self.exam_location = vac.exam_location
        if not self.written_exam_date or not self.exam_location:
            raise UserError(_('Please specify both the Written Exam Date and Exam Location before sending notifications.'))
        count = 0
        position_name = self.job_position.name if self.job_position else ''
        location_name = self.exam_location or 'Main Branch'
        unit_name = self._get_hiring_work_units()

        for val in registered_cands:
            partner = self._get_partner_for_employee(val.emp_name)
            if partner:
                _logger.info("[notify_written_exam] Sending written exam notification to %s (Partner ID=%s)", val.emp_name.name, partner.id)
                self.mail_channel_msgs_exam(partner.id, val.emp_name.name, position_name, self.written_exam_date, location_name, work_unit=unit_name)
                val.exam_notified = 'Yes'
                val.select_flag = True
                count += 1
            else:
                _logger.warning("[notify_written_exam] Could not locate res.partner for employee: %s (ID=%s)", val.emp_name.name, val.emp_name.id)

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (self.id,))
                self.env.cr.execute('SELECT employee_notify_written_exam(%s)', (self.id,))
                self.env.cr.execute('SELECT populate_exam_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedures for written exam failed: %s", e)

        self.exam_scheduled = 'Yes'
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
        if vac and vac.exists():
            vac.sudo().write({'exam_scheduled': 'Yes', 'exam_notified': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Notification Sent'),
                'message': _('Written Exam notifications dispatched to %s internal candidate(s).') % count,
                'type': 'success' if count > 0 else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_select_all_candidates(self):
        """ Select all candidate records at once """
        for rec in self:
            if rec.new_int_rec_sel:
                rec.new_int_rec_sel.write({'select_flag': True})

    def action_deselect_all_candidates(self):
        """ Deselect all candidate records at once """
        for rec in self:
            if rec.new_int_rec_sel:
                rec.new_int_rec_sel.write({'select_flag': False})

    def fetch_exam_score(self):
        if self.exam_scheduled != 'Yes':
            raise UserError(_("Sequence Error: You must notify candidates for the Written Exam ('Notify Written Exam') before fetching exam scores."))
        
        # 1. Fetch written exam scores from Assessment Module (exam.candidate.attempt)
        attempt_model = self.env['exam.candidate.attempt']
        vac_id = self.vacancy_id
        vac_ref = self.vacancy_reference
        job_id = self.job_position.id if self.job_position else False
        fetched_count = 0

        for cand in self.new_int_rec_sel:
            if not cand.emp_name:
                continue

            emp = cand.emp_name
            # Domain to match written exam attempt in assessment system
            domain = [('employee_id', '=', emp.id)]
            if vac_id:
                domain.append('|')
                domain.append(('session_id.vacancy_id', '=', vac_id))
                domain.append(('session_id.vacancy_id.reference', '=', vac_ref or ''))
            elif job_id:
                domain.append(('session_id.job_id', '=', job_id))

            attempt = attempt_model.search(domain, order='id desc', limit=1)
            if not attempt and job_id:
                attempt = attempt_model.search([('employee_id', '=', emp.id), ('session_id.job_id', '=', job_id)], order='id desc', limit=1)
            if not attempt:
                attempt = attempt_model.search([('employee_id', '=', emp.id)], order='id desc', limit=1)

            if attempt:
                cand.written_exam_score = attempt.score_percentage
                fetched_count += 1

        # 2. Legacy SQL procedure fallback (only if function exists in Postgres DB)
        try:
            self.env.cr.execute("SELECT 1 FROM pg_proc WHERE proname = 'employee_exam_score'")
            if self.env.cr.fetchone():
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT employee_exam_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_exam_score error: %s", e)

        if not self.new_int_rec_sel:
            raise UserError(_("No candidates found in the shortlisted selection list. Please shortlist candidates first."))

        # Check if any candidate actually took the exam / has a score
        has_any_score = any(cand.written_exam_score and cand.written_exam_score > 0 for cand in self.new_int_rec_sel)
        if fetched_count == 0 and not has_any_score:
            raise UserError(_("No exam scores found. None of the shortlisted candidates have completed their written exam assessment yet."))

        # 3. Evaluate 50% written exam threshold for candidate selection
        for cand in self.new_int_rec_sel:
            score = cand.written_exam_score or 0.0
            if score < 50.0:
                cand.select_flag = False
                cand.selection_type = 'rejected'
                cand.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score

        self.exam_scores_fetched = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Scores Fetched'),
                'message': _('Written Exam scores fetched successfully for %d candidate(s) from Written Assessment Module.') % (fetched_count or len([c for c in self.new_int_rec_sel if c.written_exam_score])),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _get_position_title(self):
        self.ensure_one()
        if self.job_position and self.job_position.name:
            return self.job_position.name
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
            if vac.exists() and vac.job_position and vac.job_position.name:
                return vac.job_position.name
        if self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
            if vac and vac.job_position and vac.job_position.name:
                return vac.job_position.name
        return _("N/A")

    def _get_hiring_work_units(self):
        self.ensure_one()
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)

        if vac and vac.exists():
            if vac.hiring_details:
                units = [hd.work_unit.name for hd in vac.hiring_details if hd.work_unit and hd.work_unit.name]
                if units:
                    return ", ".join(dict.fromkeys(units))
            if vac.operating_unit_id and vac.operating_unit_id.name:
                return vac.operating_unit_id.name

        if self.job_location:
            return self.job_location
        return _("Head Office")

    def notify_interview_panel(self):
        if not self.new_int_rec_panel or not self.new_int_rec_panel.filtered(lambda p: p.emp_name):
            raise UserError(_("Please add at least one panel member in the Panel Members tab before notifying the panel."))
        
        # Validate that at least one candidate passed the written exam (>= 50%)
        if self.new_int_rec_sel:
            passing_cands = self.new_int_rec_sel.filtered(lambda c: (c.written_exam_score or 0.0) >= 50.0 and c.selection_type != 'rejected')
            if not passing_cands:
                raise UserError(_("No candidates have passed the written examination (minimum 50% score required). Cannot proceed to notify the interview panel."))

        if not self.interview_date:
            vac = False
            if self.vacancy_id:
                vac = self.env['job.vacancy'].browse(self.vacancy_id)
            elif self.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
            if vac and vac.exists() and vac.interview_date:
                self.interview_date = vac.interview_date
                if not self.interview_location and vac.interview_location:
                    self.interview_location = vac.interview_location
        if not self.interview_date or not self.interview_location:
            raise UserError(_('Please specify both the Interview Date and Interview Location before notifying the panel.'))
        pos_title = self._get_position_title()
        work_unit_str = self._get_hiring_work_units()
        for val in self.new_int_rec_panel:
            if val.emp_name:
                val.write({'response_status': 'pending'})
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, pos_title, self.interview_date, self.interview_location, work_unit=work_unit_str)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT notify_panel_internal_interview(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure notify_panel_internal_interview failed: %s", e)
        self.panel_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Notified'),
                'message': _('Interview Panel members have been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_notify_panel_members(self):
        """Alias for notify_interview_panel to ensure consistent proxy delegation."""
        return self.notify_interview_panel()

    def action_open_reschedule_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule Interview & Reassign Panel'),
            'res_model': 'reschedule.interview.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_internal_selected_id': self.id,
                'default_new_interview_date': self.interview_date or fields.Date.today(),
                'default_new_interview_location': self.interview_location or '',
            }
        }

    def action_open_supervisor_evaluation_wizard(self):
        """Opens batch or single supervisor evaluation wizard for candidates in this selection process."""
        self.ensure_one()
        cands = self.new_int_rec_sel.filtered(lambda c: c.emp_name)
        if not cands:
            raise UserError(_("No candidates found to evaluate."))

        # Filter candidates by current user's direct subordinates if user is not HR manager
        is_hr = self.env.user.has_group('custom_recruitment.group_recruitment_officer') or self.env.user.has_group('custom_recruitment.group_recruitment_manager')
        if not is_hr:
            user_emp = self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
            subordinates = cands.filtered(lambda c: c.emp_name.parent_id.id == user_emp.id or c.emp_name.coach_id.id == user_emp.id)
            if subordinates:
                cands = subordinates

        lines = [(0, 0, {
            'candidate_id': c.id,
            'employee_id': c.emp_name.id,
            'current_position': c.emp_name.job_id.name if c.emp_name and c.emp_name.job_id else '',
            'current_work_unit': c.emp_name.default_operating_unit_id.name if c.emp_name and c.emp_name.default_operating_unit_id else '',
            'service_in_company': c.service_in_company or 0.0,
            'pms_score': c.pms_score or 0.0,
            'recommendation_score': c.supervisor_recommendation_score or 100.0,
            'recommendation_remarks': c.supervisor_remarks or '',
        }) for c in cands]

        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Grant Supervisor Recommendation Marks'),
            'res_model': 'supervisor.recommendation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_vacancy_id': vac.id if vac and vac.exists() else False,
                'default_selected_recruitment_id': self.id,
                'default_is_batch': True,
                'default_line_ids': lines,
            }
        }

    def action_request_supervisor_recommendation(self):
        """Request supervisor recommendation for eligible transfer/lateral candidates."""
        self.ensure_one()
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
        if vac and vac.exists():
            return vac.action_request_supervisor_recommendation()

        cands = self.new_int_rec_sel.filtered(lambda c: c.emp_name) if hasattr(self, 'new_int_rec_sel') else []
        if not cands:
            raise UserError(_("No eligible candidates found to request supervisor recommendation."))

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        pos_title = self.job_position.name if self.job_position else _('Job Position')
        ref_str = self.vacancy_reference or _('TBD')

        supervisor_cands = {}
        for cand in cands:
            emp = cand.emp_name
            sup = emp.parent_id or emp.coach_id
            if sup and sup.user_id and sup.user_id.partner_id:
                supervisor_cands.setdefault(sup, []).append(cand)

        if not supervisor_cands:
            raise UserError(_("None of the eligible candidates have a direct supervisor/coach linked to an active user account."))

        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        notified_supervisors = []
        eval_url = f"{base_url.rstrip('/')}/recruitment/supervisor_evaluation/{vac.id if vac else self.id}"

        for sup, sup_c_list in supervisor_cands.items():
            partner_id = sup.user_id.partner_id.id
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner_id])
            c_names = ", ".join(c.emp_name.name for c in sup_c_list)
            
            msg = (
                f"<div style='font-family: inherit; font-size: 14px; line-height: 1.5;'>"
                f"<p>Dear <b>{sup.name}</b>,</p>"
                f"<p>Your subordinate(s) <b>{c_names}</b> have applied for the vacancy: <b>{pos_title}</b> (Ref: <code>{ref_str}</code>).</p>"
                f"<p>Kindly evaluate and grant their <b>Supervisor Recommendation Marks (0 - 100%)</b> and evaluation comments in the system before candidate ranking:</p>"
                f"<p style='margin: 16px 0;'>"
                f"<a href='{eval_url}' style='display:inline-block; padding:9px 18px; background-color:#541718; color:#ffffff; text-decoration:none; border-radius:4px; font-weight:bold; font-size:13px;'>"
                f"⭐ Evaluate My Candidate(s)"
                f"</a>"
                f"</p>"
                f"<p style='color: #666; font-size: 12px;'>Direct link: <a href='{eval_url}'>{eval_url}</a></p>"
                f"<p>Best regards,<br/><b>Bunna Bank Talent Acquisition &amp; OD</b></p>"
                f"</div>"
            )
            channel.message_post(body=Markup(msg), message_type='comment', subtype_xmlid='mail.mt_comment')

            if sup.user_id:
                try:
                    existing_act = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'new.internal.recruitment.selected'),
                        ('res_id', '=', self.id),
                        ('user_id', '=', sup.user_id.id),
                        ('summary', 'ilike', 'Supervisor Recommendation'),
                    ], limit=1)
                    if not existing_act:
                        self.activity_schedule(
                            activity_type_id=todo_type.id if todo_type else False,
                            summary=_('Supervisor Recommendation: %s (%s)') % (pos_title, c_names),
                            note=Markup(_("<p>Please evaluate recommendation marks for: <b>%s</b></p><p><a href='%s'>Click here to evaluate</a></p>") % (c_names, eval_url)),
                            user_id=sup.user_id.id
                        )
                except Exception:
                    pass

            if sup.name not in notified_supervisors:
                notified_supervisors.append(sup.name)

        self.supervisor_rec_requested = True
        msg_body = _("Supervisor recommendation requested for %d candidate(s). Notified Supervisors: %s") % (
            len(cands), ", ".join(notified_supervisors)
        )
        try:
            self.message_post(body=msg_body)
        except Exception:
            pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Evaluation Links Sent'),
                'message': _('Supervisor evaluation notification links sent successfully to: %s') % (
                    ", ".join(notified_supervisors)
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _format_datetime_friendly(self, dt):
        if not dt:
            return 'TBD'
        try:
            if isinstance(dt, str):
                dt = fields.Datetime.to_datetime(dt)
            return dt.strftime("%b %d, %Y %I:%M %p")
        except Exception:
            return str(dt)

    def mail_channel_msgs_panel(self, rec_id, emp, position, date, loc, work_unit=None):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        unit_str = work_unit or self._get_hiring_work_units()
        date_str = self._format_datetime_friendly(date)
        loc_str = loc or 'Head Office'
        message = (
            f"<p>Dear <b>{emp}</b>,</p>"
            f"<p>You are selected as an <b>Interview Panel Member</b> for:</p>"
            f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
            f"<li><b>Position:</b> {pos_title}</li>"
            f"<li><b>Work Unit:</b> {unit_str}</li>"
            f"<li><b>Date:</b> {date_str}</li>"
            f"<li><b>Location:</b> {loc_str}</li>"
            f"</ul>"
        )
        channel.message_post(body=Markup(message), message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_exam_panel(self):
        if not self.new_int_rec_panel or not self.new_int_rec_panel.filtered(lambda p: p.emp_name):
            raise UserError(_("Please add at least one panel member in the Panel Members tab before notifying the panel."))
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date.'))
        pos_title = self._get_position_title()
        work_unit_str = self._get_hiring_work_units()
        for val in self.new_int_rec_panel:
            if val.emp_name:
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    self.mail_channel_msgs_exam_panel(usr.id, val.emp_name.name, pos_title, self.written_exam_date, self.exam_location or 'Main Office', work_unit=work_unit_str)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Panel Notified'),
                'message': _('Exam Panel members have been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs_exam_panel(self, rec_id, emp, position, date, loc, work_unit=None):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        unit_str = work_unit or self._get_hiring_work_units()
        date_str = self._format_datetime_friendly(date)
        loc_str = loc or 'Main Office'
        message = (
            f"<p>Dear <b>{emp}</b>,</p>"
            f"<p>You are selected as an <b>Exam Panel Member</b> for:</p>"
            f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
            f"<li><b>Position:</b> {pos_title}</li>"
            f"<li><b>Work Unit:</b> {unit_str}</li>"
            f"<li><b>Date:</b> {date_str}</li>"
            f"<li><b>Location:</b> {loc_str}</li>"
            f"</ul>"
        )
        channel.message_post(body=Markup(message), message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_interview(self):
        if not self.exam_scores_fetched:
            raise UserError(_("Sequence Error: You must fetch written exam scores ('Fetch Exam Score') before sending interview invitations to candidates."))
        if not self.panel_notified:
            raise UserError(_("Sequence Error: You must notify the Interview Panel ('Notify Interview Panel') before sending interview invitations to candidates."))
        if not self.interview_date:
            vac = False
            if self.vacancy_id:
                vac = self.env['job.vacancy'].browse(self.vacancy_id)
            elif self.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
            if vac and vac.exists() and vac.interview_date:
                self.interview_date = vac.interview_date
                if not self.interview_location and vac.interview_location:
                    self.interview_location = vac.interview_location
        if not self.interview_date or not self.interview_location:
            raise UserError(_('Please specify both the Interview Date and Interview Location before sending candidate invitations.'))

        passing_cands = self.new_int_rec_sel.filtered(lambda c: (c.written_exam_score or 0.0) >= 50.0 and c.selection_type != 'rejected')
        if not passing_cands:
            raise UserError(_("No candidates have passed the written examination (minimum 50% score required). Cannot proceed with interview notification."))
        for val in self.new_int_rec_sel:
            score = val.written_exam_score or 0.0
            if score < 50.0:
                val.select_flag = False
                val.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score
            else:
                if val.emp_name and val.selection_type != 'rejected':
                    usr = self._get_partner_for_employee(val.emp_name)
                    if usr:
                        self.mail_channel_msgs_interview(
                            usr.id, val.emp_name.name, self.job_position.name if self.job_position else '',
                            self.interview_date, self.interview_location,
                            work_unit=self._get_hiring_work_units()
                        )
                        val.interview_notified = 'Yes'
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT update_interview_panel_acceptance(%s)', (self.id,))
                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (self.id,))
                self.env.cr.execute('SELECT employee_notify_interview(%s)', (self.id,))
                self.env.cr.execute('SELECT populate_interview_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedures for interview failed: %s", e)
        self.interview_scheduled = 'Yes'
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)
        if vac and vac.exists():
            vac.sudo().write({'interview_scheduled': 'Yes'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Notifications Sent'),
                'message': _('Interview notifications dispatched to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def fetch_interview_score(self):
        FinalResult = self.env["interview.final.result"]
        CBISCand = self.env["cbis.interview.candidate"]
        CandScore = self.env["recruitment.candidate.score"]

        for rec in self:
            rec.interview_scheduled = 'Yes'
            vac_obj = rec.vacancy_id
            vac_id_int = vac_obj.id if hasattr(vac_obj, 'id') and not isinstance(vac_obj, int) else (vac_obj if isinstance(vac_obj, int) else False)
            vac_ref = rec.vacancy_reference
            pms_w, exam_w, int_w = rec._get_internal_weights()

            # Eligible candidates for interview (not disqualified at exam stage)
            cands_to_evaluate = rec.new_int_rec_sel.filtered(lambda c: c.selection_type != 'rejected' or (c.written_exam_score or 0.0) >= 50.0)
            if not cands_to_evaluate:
                cands_to_evaluate = rec.new_int_rec_sel

            if not cands_to_evaluate:
                raise UserError(_("No candidates found in the selection list. Please shortlist candidates first."))

            cand_eval_info = []

            for cand in cands_to_evaluate:
                emp = cand.emp_name if hasattr(cand, 'emp_name') and cand.emp_name else False
                emp_id_int = emp.id if emp and hasattr(emp, 'id') and not isinstance(emp, int) else (emp if isinstance(emp, int) else False)

                raw_name = False
                if emp:
                    raw_name = emp.name if hasattr(emp, 'name') and emp.name else str(emp)
                elif hasattr(cand, 'display_name') and cand.display_name:
                    raw_name = str(cand.display_name)
                elif hasattr(cand, 'candidate_name') and cand.candidate_name:
                    raw_name = str(cand.candidate_name)

                clean_name = raw_name.split('(')[0].strip() if raw_name else False
                emp_code = getattr(emp, 'barcode', False) or getattr(emp, 'identification_id', False) or (f"EMP-{emp.id:05d}" if emp and hasattr(emp, 'id') else False)

                cbis_res = False

                # 1. Search cbis.interview.candidate by employee_id
                if emp_id_int:
                    cbis_res = CBISCand.search([('employee_id', '=', emp_id_int)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 2. Search cbis.interview.candidate by candidate_code
                if not cbis_res and emp_code:
                    cbis_res = CBISCand.search([('candidate_code', '=ilike', emp_code)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 3. Search cbis.interview.candidate by exact candidate_name (=ilike)
                if not cbis_res and clean_name:
                    cbis_res = CBISCand.search([('candidate_name', '=ilike', clean_name)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 4. Search cbis.interview.candidate by partial candidate_name (ilike)
                if not cbis_res and clean_name:
                    cbis_res = CBISCand.search([('candidate_name', 'ilike', clean_name)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 5. Search cbis.interview.candidate by first + last name keywords
                if not cbis_res and clean_name:
                    parts = clean_name.split()
                    if len(parts) >= 2:
                        first_last = f"{parts[0]}%{parts[-1]}"
                        cbis_res = CBISCand.search([('candidate_name', '=ilike', first_last)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                is_absent = False
                is_evaluated = False
                fetched_score = 0.0

                if cbis_res:
                    if cbis_res.is_absent or cbis_res.state == 'absent':
                        is_absent = True
                        fetched_score = 0.0
                    elif cbis_res.submitted_eval_count > 0 or cbis_res.state in ('evaluated', 'locked') or (cbis_res.average_interview_score and cbis_res.average_interview_score > 0):
                        is_evaluated = True
                        fetched_score = cbis_res.average_interview_score or 0.0
                else:
                    # Fallback to interview.final.result
                    final_res = False
                    if emp_id_int:
                        final_res = FinalResult.search([('employee_id', '=', emp_id_int)], order='id desc', limit=1)
                    if not final_res and clean_name:
                        final_res = FinalResult.search([('candidate_name', '=ilike', clean_name)], order='id desc', limit=1)
                    if not final_res and clean_name:
                        final_res = FinalResult.search([('candidate_name', 'ilike', clean_name)], order='id desc', limit=1)

                    if final_res:
                        score_val = getattr(final_res, 'final_score', 0.0) or getattr(final_res, 'average_score', 0.0) or getattr(final_res, 'interview_score', 0.0) or 0.0
                        if score_val > 0:
                            is_evaluated = True
                            fetched_score = score_val
                    else:
                        # Fallback to recruitment.candidate.score
                        score_rec = False
                        if emp_id_int:
                            score_rec = CandScore.search([('employee_id', '=', emp_id_int)], limit=1)
                        if not score_rec and clean_name:
                            score_rec = CandScore.search([('candidate_name', '=ilike', clean_name)], limit=1)
                        if score_rec:
                            score_val = getattr(score_rec, 'interview_score', 0.0) or 0.0
                            if score_val > 0:
                                is_evaluated = True
                                fetched_score = score_val

                cand_eval_info.append({
                    'cand': cand,
                    'is_absent': is_absent,
                    'is_evaluated': is_evaluated,
                    'fetched_score': fetched_score,
                })

            total_cands = len(cand_eval_info)
            absent_cands = [info for info in cand_eval_info if info['is_absent']]
            evaluated_cands = [info for info in cand_eval_info if info['is_evaluated']]
            pending_cands = [info for info in cand_eval_info if not info['is_absent'] and not info['is_evaluated']]

            # Validation: Detect if all candidates were absent or no evaluations conducted
            if len(absent_cands) == total_cands and total_cands > 0:
                raise UserError(_("All candidates were marked absent for the interview assessment in CBIS. No candidates were present to take the interview examination."))

            if not evaluated_cands:
                if len(absent_cands) > 0:
                    raise UserError(_("No candidates have completed their interview evaluation yet in CBIS (%d candidate(s) marked absent, %d pending).") % (len(absent_cands), len(pending_cands)))
                else:
                    raise UserError(_("Interview evaluations have not been completed yet in CBIS. None of the candidates have submitted interview evaluations."))

            # Apply scores to candidates
            for info in cand_eval_info:
                cand = info['cand']
                pms = cand.pms_score or 0.0
                exam = cand.written_exam_score or 0.0
                fetched_score = info['fetched_score']
                weighted = round((pms * pms_w / 100.0) + (exam * exam_w / 100.0) + (fetched_score * int_w / 100.0), 2)

                if info['is_absent']:
                    cand.write({
                        'interview_score': 0.0,
                        'weighted_score': weighted,
                        'select_flag': False,
                        'selection_type': 'rejected',
                        'remarks': _("Disqualified: Marked absent during interview assessment."),
                    })
                elif info['is_evaluated']:
                    if fetched_score < 50.0:
                        cand.write({
                            'interview_score': fetched_score,
                            'weighted_score': weighted,
                            'select_flag': False,
                            'selection_type': 'rejected',
                            'remarks': _("Disqualified: Interview score (%.2f%%) is below 50%% threshold.") % fetched_score,
                        })
                    else:
                        cand.write({
                            'interview_score': fetched_score,
                            'weighted_score': weighted,
                            'select_flag': True,
                            'selection_type': 'interview',
                            'remarks': _("Interview Completed (Score: %.2f%%)") % fetched_score,
                        })
                else:
                    # Pending candidate without evaluation
                    cand.write({
                        'interview_score': 0.0,
                        'weighted_score': weighted,
                        'select_flag': False,
                        'selection_type': 'rejected',
                        'remarks': _("Disqualified: No interview evaluation submitted in CBIS."),
                    })

            rec.interview_scores_fetched = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Scores Fetched'),
                'message': _('Interview scores fetched successfully (%d evaluated, %d absent). Proceed to Compute & Rank Scores.') % (len(evaluated_cands), len(absent_cands)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _get_internal_weights(self):
        """
        Fetches PMS, Written Exam, and Interview weight percentages directly from the 
        Assessment module Weight Profiles (assessment.weight.profile).
        """
        self.ensure_one()
        pms_w, exam_w, int_w = (40.0, 30.0, 30.0)

        if "assessment.weight.profile" in self.env:
            role_lvl = "non_managerial"
            vac = self.env["job.vacancy"].browse(self.vacancy_id) if self.vacancy_id else False
            if vac and getattr(vac, "interview_type", False):
                role_lvl = vac.interview_type

            profile = self.env["assessment.weight.profile"].sudo().get_profile_for_candidate("internal", role_lvl)
            if profile and profile.line_ids:
                pms_w, exam_w, int_w = 0.0, 0.0, 0.0
                for line in profile.line_ids:
                    if line.component == "pms":
                        pms_w = line.weight_percentage
                    elif line.component == "exam":
                        exam_w = line.weight_percentage
                    elif line.component == "interview":
                        int_w = line.weight_percentage

        return (pms_w, exam_w, int_w)

    def _compute_scores_on_lines(self):
        """
        Compute weighted_score and rank for all candidate lines using the
        vacancy-configured weights (PMS %, Written %, Interview %) or Transfer Matrix weights.
        Returns list of (cand_line, weighted_score) tuples sorted by score desc.
        """
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)

        is_lateral_transfer = False
        if self.transfer_eval_mode == 'transfer_matrix_only':
            is_lateral_transfer = True
        elif vac and vac.exists():
            if vac.transfer_eval_mode == 'transfer_matrix_only' or vac.internal_movement_type in ('lateral', 'transfer') or 'LAT' in (vac.reference or '').upper():
                is_lateral_transfer = True

        all_candidates = [
            cand for cand in self.new_int_rec_sel
            if cand.emp_name
        ]

        scored = []
        if is_lateral_transfer:
            w_pms = self.pms_weight or 0.0
            w_app = self.app_date_weight or 0.0
            w_exp = self.experience_weight or 0.0
            w_loc = self.location_weight or 0.0
            w_rec = self.recommendation_weight or 0.0
            if (w_pms + w_app + w_exp + w_loc + w_rec) == 0.0:
                w_pms, w_app, w_exp, w_loc, w_rec = 30.0, 20.0, 20.0, 20.0, 10.0

            # Ensure candidate fields (service, experience, application_date) have sensible values
            today = fields.Date.context_today(self)
            for cand in all_candidates:
                emp = cand.emp_name
                if not cand.application_date and cand.create_date:
                    cand.application_date = cand.create_date.date()
                elif not cand.application_date:
                    cand.application_date = today

                if not cand.service_in_company and emp:
                    if getattr(emp, 'months_of_service', False):
                        cand.service_in_company = round(emp.months_of_service / 12.0, 2)
                    elif getattr(emp, 'service_start_date', False):
                        cand.service_in_company = round((today - emp.service_start_date).days / 365.25, 2)
                    elif getattr(emp, 'joining_date', False):
                        cand.service_in_company = round((today - emp.joining_date).days / 365.25, 2)

                if not cand.relevant_experience and emp:
                    if getattr(emp, 'relevant_experience', False):
                        cand.relevant_experience = emp.relevant_experience
                    elif cand.service_in_company:
                        cand.relevant_experience = cand.service_in_company

            max_exp = max([cand.relevant_experience or cand.service_in_company or 1.0 for cand in all_candidates] or [1.0]) or 1.0
            max_loc = max([cand.service_in_company or 1.0 for cand in all_candidates] or [1.0]) or 1.0

            dates = [cand.application_date or (cand.create_date.date() if cand.create_date else False) for cand in all_candidates]
            dates = [d for d in dates if d]
            min_date = min(dates) if dates else False
            max_date = max(dates) if dates else False
            date_span = (max_date - min_date).days if (min_date and max_date) else 0

            for cand in all_candidates:
                pms = cand.pms_score or 0.0
                rec_score = cand.supervisor_recommendation_score if cand.supervisor_recommendation_score > 0 else 100.0
                exp_val = cand.relevant_experience or cand.service_in_company or 0.0
                exp_score = min(100.0, (exp_val / max_exp * 100.0)) if max_exp else 100.0
                loc_val = cand.service_in_company or 0.0
                loc_score = min(100.0, (loc_val / max_loc * 100.0)) if max_loc else 100.0

                if date_span and date_span > 0:
                    cand_date = cand.application_date or (cand.create_date.date() if cand.create_date else min_date)
                    days_from_earliest = (cand_date - min_date).days if cand_date else 0
                    app_score = max(0.0, min(100.0, 100.0 * (1.0 - (days_from_earliest / float(date_span)))))
                else:
                    app_score = 100.0

                deduction = cand.written_warning or 0.0
                ws = round(
                    (pms * w_pms / 100.0)
                    + (app_score * w_app / 100.0)
                    + (exp_score * w_exp / 100.0)
                    + (loc_score * w_loc / 100.0)
                    + (rec_score * w_rec / 100.0)
                    - deduction,
                    2
                )
                ws = max(0.0, ws)
                cand.app_date_score = round(app_score, 2)
                cand.experience_score = round(exp_score, 2)
                cand.location_score = round(loc_score, 2)
                cand.weighted_score = ws
                scored.append((cand, ws))
        else:
            pms_w, exam_w, int_w = self._get_internal_weights()
            for cand in all_candidates:
                pms  = cand.pms_score or 0.0
                exam = cand.written_exam_score or 0.0
                intv = cand.interview_score or 0.0
                ws = round((pms * pms_w / 100.0) + (exam * exam_w / 100.0) + (intv * int_w / 100.0), 2)
                cand.weighted_score = ws
                scored.append((cand, ws))

        # Sort: descending score, female priority tie-breaker, PMS tie-breaker
        def sort_key(item):
            c, ws = item
            gender_priority = 0 if (c.emp_gender or '').lower() == 'female' else 1
            return (-ws, gender_priority, -(c.pms_score or 0.0))

        sorted_scored = sorted(scored, key=sort_key)
        for idx, (cand, ws) in enumerate(sorted_scored):
            cand.rank = idx + 1

        return sorted_scored

    def action_compute_and_rank(self):
        """
        Computes weighted final scores directly on the candidates in new.internal.recruitment.selected,
        ranks them based on score & female priority, and assigns selection decisions:
        - Top N (up to no_of_vacancies) with score >= 50% are set to 'selected'
        - Remaining candidates with score >= 50% are set to 'reserve'
        - Candidates with score < 50% are set to 'rejected' (Disqualified)
        No score transfer to external recruitment scoring model is needed for internal vacancies.
        """
        for rec in self:
            vac = False
            if rec.vacancy_id:
                vac = self.env['job.vacancy'].browse(rec.vacancy_id)
            elif rec.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', rec.vacancy_reference)], limit=1)

            is_lateral_transfer = False
            if rec.transfer_eval_mode == 'transfer_matrix_only':
                is_lateral_transfer = True
            elif vac and vac.exists():
                if vac.transfer_eval_mode == 'transfer_matrix_only' or vac.internal_movement_type in ('lateral', 'transfer') or 'LAT' in (vac.reference or '').upper():
                    is_lateral_transfer = True

            if is_lateral_transfer:
                w_pms = rec.pms_weight or 0.0
                w_app = rec.app_date_weight or 0.0
                w_exp = rec.experience_weight or 0.0
                w_loc = rec.location_weight or 0.0
                w_rec = rec.recommendation_weight or 0.0
                tot = w_pms + w_app + w_exp + w_loc + w_rec
                if tot == 0.0:
                    w_pms, w_app, w_exp, w_loc, w_rec = 30.0, 20.0, 20.0, 20.0, 10.0
                    tot = 100.0
                elif abs(tot - 100.0) > 0.01:
                    raise UserError(_(
                        "Transfer Evaluation weights must sum to 100%%.\n"
                        "Currently: PMS %(pms)s%% + App Date %(app)s%% + Experience %(exp)s%% + Location %(loc)s%% + Recommendation %(rec)s%% = %(total)s%%\n"
                        "Please correct the weights before computing scores."
                    ) % {'pms': w_pms, 'app': w_app, 'exp': w_exp, 'loc': w_loc, 'rec': w_rec, 'total': tot})
            else:
                pms_w, exam_w, int_w = rec._get_internal_weights()
                total_weight = pms_w + exam_w + int_w
                if abs(total_weight - 100.0) > 0.01:
                    raise UserError(_(
                        "Assessment weights must sum to 100%%.\n"
                        "Currently: PMS %(pms)s%% + Written %(exam)s%% + Interview %(intv)s%% = %(total)s%%\n"
                        "Please correct the weights before computing scores."
                    ) % {'pms': pms_w, 'exam': exam_w, 'intv': int_w, 'total': total_weight})

            # Sort and compute scores on active candidate lines
            results = rec._compute_scores_on_lines()
            rec.scores_computed = True

            # Determine number of vacancies
            vac_slots = rec.no_of_vacancies or 1
            if vac and vac.no_of_vacancies > 0:
                vac_slots = vac.no_of_vacancies

            selected_count = 0
            reserve_count = 0
            disqualified_count = 0

            # Rank and assign selection_type & rank
            for idx, (cand, score) in enumerate(results):
                cand.rank = idx + 1
                if idx < vac_slots:
                    if score >= 50.0:
                        cand.selection_type = 'selected'
                        cand.select_flag = True
                        selected_count += 1
                    else:
                        cand.selection_type = 'rejected'
                        cand.select_flag = False
                        cand.remarks = _("Disqualified: Weighted score (%.2f%%) is below 50%% threshold.") % score
                        disqualified_count += 1
                else:
                    if score >= 50.0:
                        cand.selection_type = 'reserve'
                        cand.select_flag = True
                        reserve_count += 1
                    else:
                        cand.selection_type = 'rejected'
                        cand.select_flag = False
                        cand.remarks = _("Disqualified: Weighted score (%.2f%%) is below 50%% threshold.") % score
                        disqualified_count += 1

            total = len(results)

            if selected_count == 0:
                raise UserError(_("No candidates have passed the evaluation. All candidates scored below the 50% threshold. Cannot proceed to candidate ranking or committee approval."))

        if is_lateral_transfer:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Transfer Evaluation Scores Computed & Selection Decisions Applied'),
                    'message': _(
                        'Transfer Weights: PMS %(pms)s%% · App Date %(app)s%% · Experience %(exp)s%% · Location %(loc)s%% · Rec %(rec)s%%\n'
                        '%(total)s candidates ranked for %(slots)s transfer vacancy slot(s):\n'
                        '• %(sel)s Selected\n'
                        '• %(res)s Reserved\n'
                        '• %(disq)s Disqualified (<50%%)\n'
                        'You can now proceed to "Notify Approval Committee".'
                    ) % {
                        'pms': w_pms, 'app': w_app, 'exp': w_exp, 'loc': w_loc, 'rec': w_rec,
                        'total': total, 'slots': vac_slots,
                        'sel': selected_count, 'res': reserve_count, 'disq': disqualified_count
                    },
                    'type': 'success',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Final Scores Computed & Selection Decisions Applied'),
                'message': _(
                    'Weights: PMS %(pms)s%% · Written %(exam)s%% · Interview %(intv)s%%\n'
                    '%(total)s candidates ranked for %(slots)s vacancy slot(s):\n'
                    '• %(sel)s Selected\n'
                    '• %(res)s Reserved\n'
                    '• %(disq)s Disqualified (<50%%)\n'
                    'You can now proceed to "Notify Approval Committee".'
                ) % {
                    'pms': pms_w, 'exam': exam_w, 'intv': int_w,
                    'total': total, 'slots': vac_slots,
                    'sel': selected_count, 'res': reserve_count, 'disq': disqualified_count
                },
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_generate_minute(self):
        """
        Generates printable Internal Selection Committee Minute report containing
        ONLY candidates who are finally Selected (excluding Reserved & Disqualified).
        """
        self.ensure_one()
        return self.env.ref('custom_recruitment.action_report_internal_recruitment_minute').report_action(self)

    def action_open_digital_minute(self):
        """
        Opens or creates the digital committee selection minute record
        for internal recruitment selection process.
        """
        self.ensure_one()
        Minute = self.env["recruitment.selection.minute"]

        vac_id = False
        if self.vacancy_id:
            vac = self.env["job.vacancy"].browse(self.vacancy_id)
            if vac.exists():
                vac_id = vac.id
        if not vac_id and self.vacancy_reference:
            vac = self.env["job.vacancy"].search([("reference", "=", self.vacancy_reference)], limit=1)
            if vac:
                vac_id = vac.id

        minute_rec = False
        if vac_id:
            minute_rec = Minute.search([("vacancy_id", "=", vac_id)], order="id desc", limit=1)

        signature_vals = []
        added_uids = set()

        # 1. Panel Members from Process Record (checking approved delegation)
        if self.new_int_rec_panel:
            for panel in self.new_int_rec_panel:
                emp = panel.delegate_employee_id if (panel.delegation_state == 'approved' and panel.delegate_employee_id) else panel.emp_name
                user = emp.user_id if (emp and getattr(emp, 'user_id', False)) else False
                if not user and emp:
                    user = self.env['res.users'].search([('employee_id', '=', emp.id)], limit=1)
                if user and user.id not in added_uids:
                    added_uids.add(user.id)
                    signature_vals.append((0, 0, {
                        'user_id': user.id,
                        'role': panel.selection_criteria or 'Panel Member',
                        'state': 'pending',
                    }))

        # 2. Delegation Team from Process Record
        if self.recr_selected_team_id:
            for member in self.recr_selected_team_id:
                user = member.employee_name or member.alternate_committee_member
                if user and user.id not in added_uids:
                    added_uids.add(user.id)
                    role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                    signature_vals.append((0, 0, {
                        'user_id': user.id,
                        'role': role_label,
                        'state': 'pending',
                    }))

        # 3. Vacancy Panel Members
        if vac and vac.memb_panel_vac:
            for pm in vac.memb_panel_vac:
                u_id = pm.user_id.id if pm.user_id else (pm.employee_id.user_id.id if pm.employee_id and pm.employee_id.user_id else False)
                if not u_id and pm.panel_member_name:
                    emp = self.env['hr.employee'].search([('name', '=ilike', pm.panel_member_name)], limit=1)
                    u_id = emp.user_id.id if emp and emp.user_id else False
                if u_id and u_id not in added_uids:
                    added_uids.add(u_id)
                    signature_vals.append((0, 0, {
                        'user_id': u_id,
                        'role': pm.role or pm.panel_type or 'Panel Member',
                        'state': 'pending',
                    }))

        # 4. Vacancy Responsible
        if vac and vac.responsible and vac.responsible.user_id:
            resp_u_id = vac.responsible.user_id.id
            if resp_u_id not in added_uids:
                added_uids.add(resp_u_id)
                signature_vals.append((0, 0, {
                    'user_id': resp_u_id,
                    'role': 'Recruitment Responsible / HR',
                    'state': 'pending',
                }))

        line_vals = []
        for cand in self.new_int_rec_sel:
            if cand.emp_name:
                status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else ('reserve' if cand.selection_type in ('reserve', 'Reserved') else 'failed')
                line_vals.append((0, 0, {
                    'employee_id': cand.emp_name.id,
                    'candidate_name': cand.emp_name.name,
                    'pms_score': cand.pms_score or 0.0,
                    'written_score': cand.written_exam_score or 0.0,
                    'interview_score': cand.interview_score or 0.0,
                    'final_score': cand.weighted_score or 0.0,
                    'rank': cand.rank or 0,
                    'selection_status': status_val,
                }))

        if minute_rec:
            if minute_rec.state in ('draft', 'pending_approval'):
                if signature_vals:
                    minute_rec.committee_signature_ids.unlink()
                    minute_rec.write({'committee_signature_ids': signature_vals})
                if line_vals:
                    minute_rec.ranking_line_ids.unlink()
                    minute_rec.write({'ranking_line_ids': line_vals})
        else:
            if not vac_id:
                raise UserError(_("Cannot create Selection Minute without a valid Target Vacancy."))

            pos_name = self.job_position.name if self.job_position else (self.vacancy_reference or 'Vacancy')
            summary = _(
                "Internal Recruitment Selection Minute for position '%s'.\n"
                "Total Candidates: %s | Vacancy Slots: %s"
            ) % (pos_name, len(self.new_int_rec_sel), self.no_of_vacancies or 1)

            minute_rec = Minute.create({
                'vacancy_id': vac_id,
                'meeting_date': fields.Date.context_today(self),
                'decision_summary': summary,
                'committee_signature_ids': signature_vals,
                'ranking_line_ids': line_vals,
            })
            if not line_vals:
                minute_rec.action_load_candidates_from_vacancy()

        if minute_rec and minute_rec.state == 'draft':
            try:
                minute_rec.action_submit_to_committee()
            except Exception as e:
                _logger.warning("Could not auto-submit minute in action_open_digital_minute: %s", e)

        return {
            'name': _('Digital Selection Minute'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.selection.minute',
            'res_id': minute_rec.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_notify_panel_digital_sign(self):
        """
        Ensures the Digital Selection Minute is created/populated, then dispatches
        digital signature request notifications exclusively to panel members.
        """
        self.ensure_one()
        if not self.scores_computed:
            raise UserError(_("Sequence Error: You must compute & rank candidate scores ('Compute & Rank Scores') before notifying the panel for digital sign-off."))

        res_action = self.action_open_digital_minute()
        minute_id = res_action.get('res_id')
        if minute_id:
            minute_rec = self.env["recruitment.selection.minute"].browse(minute_id)
            if minute_rec.state == 'draft':
                minute_rec.action_submit_to_committee()
            else:
                minute_rec.action_notify_panel_members()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Members Notified for Digital Sign-Off'),
                'message': _('Digital sign-off request notifications successfully sent to interview panel members.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_promote_selected_employees(self):
        """
        Promotes selected candidates:
        - Same Work Unit candidates: Automatically updates job position & grade on hr.employee.
        - Different Work Unit candidates: Flags as 'Pending Release' — requires Coach/Manager Release Form.
        """
        for rec in self:
            vac = False
            if rec.vacancy_id and isinstance(rec.vacancy_id, int):
                vac = self.env['job.vacancy'].browse(rec.vacancy_id)
            elif hasattr(rec.vacancy_id, 'vacancy_status'):
                vac = rec.vacancy_id
            if not vac and rec.vacancy_reference:
                vac = self.env['job.vacancy'].search([('reference', '=', rec.vacancy_reference)], limit=1)

            is_vac_published = bool(vac and vac.exists() and vac.vacancy_status == 'published')
            if rec.state not in ('evaluate', 'approved', 'published') and rec.status not in ('evaluate', 'approved', 'published') and not is_vac_published:
                raise UserError(_("Sequence Error: Selection process must be approved before promoting employees."))

            selected_lines = rec.new_int_rec_sel.filtered(
                lambda c: c.selection_type in ('selected', 'Selected') and c.emp_name
            )
            if not selected_lines:
                raise UserError(_("No selected candidates found to promote."))

            same_unit_count = 0
            diff_unit_count = 0

            for cand in selected_lines:
                # Ensure sequence & promotion date are populated
                if not cand.promotion_ref_no:
                    seq_val = self.env['ir.sequence'].next_by_code('bunna.internal.promotion.letter')
                    cand.promotion_ref_no = seq_val or ('BB/TAOD/%04d/%s' % (cand.id, fields.Date.today().year))
                if not cand.promotion_date:
                    cand.promotion_date = fields.Date.context_today(self)
                if not cand.promoted_salary or cand.promoted_salary <= 0:
                    cand.promoted_salary = cand.get_promoted_salary_figure()

                if cand.promotion_type == 'same_unit':
                    if cand.promotion_status not in ('promoted', 'released'):
                        emp = cand.emp_name
                        job_pos = rec.job_position
                        grade_val = rec.job_grade or getattr(rec, 'job_grade_id', False)
                        
                        # Resolve grade record
                        grade_rec = False
                        if grade_val:
                            if isinstance(grade_val, int):
                                grade_rec = self.env['employee.grade'].browse(grade_val)
                            else:
                                g_str = _format_clean_text(grade_val)
                                if g_str and str(g_str).strip().isdigit():
                                    grade_rec = self.env['employee.grade'].browse(int(str(g_str).strip()))
                                elif g_str:
                                    grade_rec = self.env['employee.grade'].search([
                                        '|', ('grade_name', '=ilike', str(g_str).strip()), ('grade_code', '=ilike', str(g_str).strip())
                                    ], limit=1)

                        vals = {}
                        if job_pos:
                            if hasattr(emp, 'job_id'):
                                vals['job_id'] = job_pos.id
                            if hasattr(emp, 'job_position'):
                                vals['job_position'] = job_pos.id
                            if hasattr(emp, 'job_name'):
                                vals['job_name'] = job_pos.name
                            if hasattr(emp, 'department_id') and job_pos.department_id:
                                vals['department_id'] = job_pos.department_id.id

                        if grade_rec and grade_rec.exists():
                            if hasattr(emp, 'job_grade'):
                                vals['job_grade'] = grade_rec.id
                            if hasattr(emp, 'grade'):
                                vals['grade'] = grade_rec.id
                            if hasattr(emp, 'emp_grade'):
                                vals['emp_grade'] = grade_rec.grade_name or str(grade_val)
                        elif grade_val and hasattr(emp, 'emp_grade'):
                            vals['emp_grade'] = str(grade_val)

                        if vals:
                            emp.sudo().with_context(job_history_reason='promotion').write(vals)

                        # Update salary, job position & grade on hr.version & contract
                        v_vals = {}
                        if cand.promoted_salary and cand.promoted_salary > 0:
                            v_vals['wage'] = cand.promoted_salary
                        if job_pos:
                            v_vals['job_id'] = job_pos.id
                        if grade_rec and grade_rec.exists() and 'job_grade' in self.env['hr.version']._fields:
                            v_vals['job_grade'] = grade_rec.id

                        if v_vals:
                            if hasattr(emp, 'version_id') and emp.version_id:
                                try:
                                    emp.version_id.sudo().write(v_vals)
                                except Exception as e:
                                    _logger.warning("Could not update version_id on same unit promotion: %s", e)
                            elif 'hr.version' in self.env:
                                ver = self.env['hr.version'].sudo().search([('employee_id', '=', emp.id)], limit=1)
                                if ver:
                                    try:
                                        ver.write(v_vals)
                                    except Exception as e:
                                        _logger.warning("Could not update hr.version on same unit promotion: %s", e)

                        if hasattr(emp, 'contract_id') and emp.contract_id:
                            c_vals = {}
                            if cand.promoted_salary and cand.promoted_salary > 0:
                                c_vals['wage'] = cand.promoted_salary
                            if job_pos:
                                c_vals['job_id'] = job_pos.id
                            if c_vals:
                                try:
                                    emp.contract_id.sudo().write(c_vals)
                                except Exception as e:
                                    _logger.warning("Could not update contract wage: %s", e)

                        # Log department.history
                        today = fields.Date.context_today(self)
                        if 'department.history' in self.env:
                            try:
                                self.env['department.history'].sudo().create({
                                    'employee_id': emp.id,
                                    'employee_name': emp.name,
                                    'new_job_title': job_pos.id if job_pos else (emp.job_id.id if emp.job_id else False),
                                    'job_grade': grade_rec.id if grade_rec and grade_rec.exists() else (emp.job_grade.id if hasattr(emp, 'job_grade') and emp.job_grade else False),
                                    'job_history_start_date': today,
                                    'reason': _('Promotion via Internal Recruitment'),
                                    'operating_unit': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                                })
                            except Exception as e:
                                _logger.warning("Failed to create department.history: %s", e)

                        cand.promotion_status = 'promoted'
                        same_unit_count += 1
                        cand.action_send_promotion_notification()
                        _update_pbms_and_operating_unit_counts(self.env, emp.default_operating_unit_id or emp.operating_unit_id, job_pos or emp.job_id, count=1)
                else:
                    if cand.promotion_status not in ('released', 'promoted'):
                        cand.promotion_status = 'pending_release'
                        diff_unit_count += 1
                        cand.action_send_promotion_notification()

            message = _(
                "Promotion Processing Completed:\n"
                "• %s employee(s) in Same Work Unit promoted automatically (position & grade updated).\n"
                "• %s employee(s) in Different Work Unit marked as Pending Release (requires Coach/Manager Release Form)."
            ) % (same_unit_count, diff_unit_count)

            rec.message_post(body=message)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Selected Employees Promotion Processed'),
                    'message': message,
                    'type': 'success' if same_unit_count > 0 else 'warning',
                    'sticky': True if diff_unit_count > 0 else False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

    def action_print_all_promotion_letters(self):
        self.ensure_one()
        selected_candidates = self.new_int_rec_sel.filtered(
            lambda c: c.selection_type in ('selected', 'Selected') and c.emp_name
        )
        if not selected_candidates:
            raise UserError(_("No selected candidates found to print promotion letters."))
        for cand in selected_candidates:
            if not cand.promotion_ref_no:
                seq_val = self.env['ir.sequence'].next_by_code('bunna.internal.promotion.letter')
                cand.promotion_ref_no = seq_val or ('BB/TAOD/%04d/%s' % (cand.id, fields.Date.today().year))
            if not cand.promotion_date:
                cand.promotion_date = fields.Date.context_today(self)
            if not cand.promoted_salary or cand.promoted_salary <= 0:
                cand.promoted_salary = cand.get_promoted_salary_figure()
        return self.env.ref('custom_recruitment.action_report_internal_promotion_letter').report_action(selected_candidates)

    def action_transfer_to_candidate_scores(self):
        """
        Transfers internal candidates and their scores (PMS, written exam, interview)
        plus the vacancy-configured weights (PMS %, Written %, Interview %) to the central
        recruitment.candidate.score model, then automatically runs disqualification check
        and auto-selection ranking in recruitment.candidate.score.
        """
        for rec in self:
            pms_w, exam_w, int_w = rec._get_internal_weights()
            total_weight = pms_w + exam_w + int_w
            if abs(total_weight - 100.0) > 0.01:
                raise UserError(_(
                    "Assessment weights must sum to 100%%.\n"
                    "Currently: PMS %(pms)s%% + Written %(exam)s%% + Interview %(intv)s%% = %(total)s%%\n"
                    "Please correct the weights before transferring."
                ) % {'pms': pms_w, 'exam': exam_w, 'intv': int_w, 'total': total_weight})

            vac = False
            if rec.vacancy_id:
                vac = self.env["job.vacancy"].browse(rec.vacancy_id)
            if not vac and rec.vacancy_reference:
                vac = self.env["job.vacancy"].search([("reference", "=", rec.vacancy_reference)], limit=1)

            if not vac.no_of_vacancies or vac.no_of_vacancies <= 0:
                if rec.no_of_vacancies and rec.no_of_vacancies > 0:
                    vac.no_of_vacancies = rec.no_of_vacancies
                else:
                    vac.no_of_vacancies = 1

            # Make sure weighted scores are computed on candidate lines
            rec._compute_scores_on_lines()

            Score = self.env["recruitment.candidate.score"]
            transferred_scores = self.env["recruitment.candidate.score"]

            for cand in rec.new_int_rec_sel:
                if cand.emp_name and (cand.select_flag or cand.select_flag is None):
                    existing = Score.search([
                        ("vacancy_id", "=", vac.id),
                        ("employee_id", "=", cand.emp_name.id),
                    ], limit=1)

                    vals = {
                        "vacancy_id": vac.id,
                        "employee_id": cand.emp_name.id,
                        "pms_score": cand.pms_score or 0.0,
                        "written_score": cand.written_exam_score or 0.0,
                        "interview_score": cand.interview_score or 0.0,
                        "pms_weight": pms_w,
                        "written_weight": exam_w,
                        "interview_weight": int_w,
                        "weights_manually_set": True,
                        "gender": cand.emp_name.gender or False,
                    }

                    if existing:
                        existing.write(vals)
                        transferred_scores |= existing
                    else:
                        new_score = Score.create(vals)
                        transferred_scores |= new_score

            if transferred_scores:
                all_vac_scores = Score.search([("vacancy_id", "=", vac.id)])
                all_vac_scores.action_apply_disqualification_check()
                all_vac_scores.action_auto_select_candidates()

            rec.scores_computed = True
            return {
                "name": _("Candidate Scores & Ranking"),
                "type": "ir.actions.act_window",
                "res_model": "recruitment.candidate.score",
                "view_mode": "list,form",
                "domain": [("vacancy_id", "=", vac.id)],
                "context": {
                    "default_vacancy_id": vac.id,
                    "search_default_vacancy_id": vac.id,
                },
            }


    def compute_weighted_score(self):
        """Delegates to action_compute_and_rank for vacancy-weighted scoring and ranking."""
        return self.action_compute_and_rank()

    def notify_selection(self):
        vac_id = False
        if getattr(self, 'vacancy_id', False):
            vac_id = self.vacancy_id if isinstance(self.vacancy_id, int) else getattr(self.vacancy_id, 'id', False)
        vac_ref = getattr(self, 'vacancy_reference', False) or getattr(self, 'recruitment_reference', False)
        if not vac_id and vac_ref:
            vac = self.env["job.vacancy"].search([("reference", "=", vac_ref)], limit=1)
            if vac:
                vac_id = vac.id

        minute_rec = False
        if vac_id:
            minute_rec = self.env["recruitment.selection.minute"].search([
                ("vacancy_id", "=", vac_id),
                ("state", "=", "approved")
            ], limit=1)

        if not minute_rec:
            raise UserError(_("Sequence Error: The Recruitment Approval Committee minute has not been approved yet. You cannot notify selected candidates until the selection minute is approved and finalized."))

        vac = self.env["job.vacancy"].browse(vac_id) if vac_id else False
        is_lateral = (
            (vac and getattr(vac, 'internal_movement_type', False) in ('lateral', 'transfer'))
            or (vac and getattr(vac, 'transfer_eval_mode', False) == 'transfer_matrix_only')
            or (vac_ref and 'LAT' in str(vac_ref).upper())
            or (getattr(self, 'transfer_eval_mode', False) == 'transfer_matrix_only')
        )

        for val in self.new_int_rec_sel:
            if val.emp_name and (val.select_flag or val.select_flag is None):
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    if val.selection_type in ['selected', 'Selected']:
                        if is_lateral:
                            msg1 = _("We are pleased to inform you that you have been Selected for Lateral Transfer to the position of ")
                            summary_msg = _('Action Required: Respond to Transfer Offer (%s)') % (self.job_position.name if self.job_position else '')
                            note_text = _("<p>Congratulations! <a href='%s'>Click here to Review and Respond to Transfer Offer</a></p>")
                        else:
                            msg1 = _("We are pleased to inform you that you have been Selected for Internal Promotion to the position of ")
                            summary_msg = _('Action Required: Respond to Promotion Offer (%s)') % (self.job_position.name if self.job_position else '')
                            note_text = _("<p>Congratulations! <a href='%s'>Click here to Review and Respond to Promotion Offer</a></p>")

                        msg2 = _("\n\nPlease review and indicate your acceptance/response via the ERP portal.\n\nCongratulations!")
                        self.mail_channel_msgs_selection(
                            usr.id, val.emp_name.name, msg1,
                            self.job_position.name if self.job_position else '',
                            msg2, candidate_id=val.id, is_lateral=is_lateral
                        )
                        if val.emp_name and val.emp_name.user_id:
                            try:
                                todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                                p_url = f"{base_url.rstrip('/')}/recruitment/transfer_acceptance/{val.id}" if base_url else f"/recruitment/transfer_acceptance/{val.id}"
                                self.activity_schedule(
                                    activity_type_id=todo_type.id if todo_type else False,
                                    summary=summary_msg,
                                    note=Markup(note_text % p_url),
                                    user_id=val.emp_name.user_id.id,
                                )
                            except Exception:
                                pass
                    elif val.selection_type in ['reserve', 'reserved', 'Reserve', 'Reserved']:
                        msg1 = _("We are pleased to inform you that you have been placed in the Reserve Pool for the position of ")
                        msg2 = _("\n\nYour status is valid for 6 months.")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2, is_lateral=is_lateral)
                    val.decision_notified = 'Yes'
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT employee_notify_result(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_notify_result failed: %s", e)
        self.selection_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Selection Notified'),
                'message': _('Selection results dispatched to internal candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
    
    def mail_channel_msgs_selection(self, rec_id, emp, msg1, position, msg2, candidate_id=None, is_lateral=False):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        portal_btn = ""
        if candidate_id:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            portal_url = f"{base_url.rstrip('/')}/recruitment/transfer_acceptance/{candidate_id}" if base_url else f"/recruitment/transfer_acceptance/{candidate_id}"
            btn_title = _("👉 Review &amp; Respond to Transfer Offer (Accept / Decline)") if is_lateral else _("👉 Review &amp; Respond to Promotion Offer (Accept / Decline)")
            portal_btn = (
                f"<div style='margin: 16px 0;'>"
                f"<a href='{portal_url}' target='_blank' style='"
                f"display: inline-block; padding: 10px 22px; background-color: #541718; "
                f"color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold; "
                f"box-shadow: 0 2px 4px rgba(0,0,0,0.15); font-size: 13px;'>"
                f"{btn_title}"
                f"</a>"
                f"<p style='color: #666; font-size: 12px; margin-top: 6px;'>Direct link: <a href='{portal_url}'>{portal_url}</a></p>"
                f"</div>"
            )
        clean_msg2 = msg2.replace('\n', '<br/>')
        msg = (
            f"<div style='font-family: inherit; font-size: 14px; line-height: 1.5;'>"
            f"<p>Dear <b>{emp}</b>,</p>"
            f"<p>{msg1}<b>{position}</b>.{clean_msg2}</p>"
            f"{portal_btn}"
            f"<p>Best regards,<br/><b>Bunna Bank Talent Acquisition &amp; Human Capital</b></p>"
            f"</div>"
        )
        channel.message_post(
            body=Markup(msg),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def notify_rejection(self):
        for val in self.new_int_rec_sel:
            if val.emp_name and (val.select_flag or val.select_flag is None):
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    msg1 = _("Thank you for your interest in the position of ")
                    msg2 = _("\n\nWe regret to inform you that you were not selected for this position.\nWe wish you all the best in your future career endeavors.")
                    self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
                    val.decision_notified = 'Rejected'

		
class NewInternalRecruitmentSelectedDelegation(models.Model):
    _name = "new.recrt.delegation.team"
    _description = "New Recrt Delegation Team"

    def _auto_init(self):
        super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE new_recrt_delegation_team SET role = 'chairperson' WHERE role = 'chair_person';
                    UPDATE new_recrt_delegation_team SET role = 'secretary' WHERE role IN ('secretary', 'member_secretary');
                    UPDATE new_recrt_delegation_team SET role = 'panel_member' WHERE role IN ('member', 'approver') OR role IS NULL;
                    UPDATE new_recrt_delegation_team SET status = 'active' WHERE status IS NULL OR status = '';
                """)
        except Exception as e:
            _logger.warning("Migration query on new_recrt_delegation_team failed: %s", e)

    role = fields.Selection([
        ("chairperson", "Chairperson"),
        ("panel_member", "Panel Member"),
        ("secretary", "Panel Member & Secretary"),
        ("observer", "Labor Representative (Observer)"),
    ], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    active = fields.Boolean(default=True)
    eligible_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_eligible_user_ids',
        string='Eligible Approvers'
    )

    @api.depends('role', 'new_rec_del_id', 'new_rec_del_id.vacancy_id', 'new_rec_del_id.workunit_id')
    def _compute_eligible_user_ids(self):
        for rec in self:
            domain = rec._get_role_user_domain(rec.role)
            rec.eligible_user_ids = self.env['res.users'].search(domain)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.onchange('role', 'new_rec_del_id')
    def _onchange_role_get_user_domain(self):
        """
        Dynamically filters employee_name and alternate_committee_member based on the role:
        - 'panel_member': Strictly from Vacancy's Hiring Work Unit.
        - 'secretary': Strictly from Vacancy Responsible Officer's Work Unit (HR / Recruitment).
        - 'chairperson' / 'observer': Across company.
        """
        domain = self._get_role_user_domain(self.role)
        self.eligible_user_ids = self.env['res.users'].search(domain)
        if self.employee_name and self.employee_name.id not in self.eligible_user_ids.ids:
            self.employee_name = False
        if self.alternate_committee_member and self.alternate_committee_member.id not in self.eligible_user_ids.ids:
            self.alternate_committee_member = False
        return {
            'domain': {
                'employee_name': domain,
                'alternate_committee_member': domain,
            }
        }

    def _get_role_user_domain(self, role=None):
        role_val = role or self.role or 'panel_member'
        sel = self.new_rec_del_id
        vac = False
        if sel:
            vac_id = getattr(sel, 'vacancy_id', False)
            if isinstance(vac_id, int) and vac_id > 0:
                vac = self.env['job.vacancy'].browse(vac_id)
            elif hasattr(vac_id, 'operating_unit_id') and vac_id:
                vac = vac_id
            if not vac and getattr(sel, 'vacancy_reference', False):
                vac = self.env['job.vacancy'].search([('reference', '=', sel.vacancy_reference)], limit=1)

        # 1. Panel Member: From Vacancy's Hiring Work Unit (and its parent District) AND Vacancy Responsible Officer's Work Unit
        if role_val == 'panel_member':
            ou_set = set()

            def _is_district_or_branch_ou(ou_ref):
                if not ou_ref:
                    return False
                try:
                    curr = ou_ref
                    if isinstance(ou_ref, int) and ou_ref > 0:
                        curr = self.env['operating.unit'].browse(ou_ref)
                    if not curr or not curr.exists():
                        return False
                    w_type = getattr(curr, 'work_unit_type', False)
                    if w_type in ('district_office', 'branch', 'sub_branch', 'regional_office', 'service_center'):
                        return True
                    name_str = str(getattr(curr, 'name', '') or '').lower()
                    code_str = str(getattr(curr, 'code', '') or '').lower()
                    return 'branch' in name_str or 'district' in name_str or 'branch' in code_str or 'district' in code_str
                except Exception:
                    return False

            def _get_ho_root_and_children(ou_ref):
                res = set()
                if not ou_ref:
                    return res
                curr = ou_ref
                if isinstance(ou_ref, int) and ou_ref > 0:
                    curr = self.env['operating.unit'].browse(ou_ref)
                if not curr or not curr.exists():
                    return res
                while curr.parent_unit and curr.parent_unit.exists() and not _is_district_or_branch_ou(curr.parent_unit):
                    curr = curr.parent_unit
                res.add(curr.id)
                frontier = [curr.id]
                while frontier:
                    children = self.env['operating.unit'].search([('parent_unit', 'in', frontier)])
                    new_ids = set(children.ids) - res
                    if not new_ids:
                        break
                    res.update(new_ids)
                    frontier = list(new_ids)
                return res

            hiring_ou = False
            if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
                hiring_ou = vac.operating_unit_id
            elif sel and getattr(sel, 'workunit_id', False):
                w_id = sel.workunit_id
                hiring_ou = self.env['operating.unit'].browse(w_id) if isinstance(w_id, int) else w_id
            elif sel and getattr(sel, 'job_location', False):
                ou = self.env['operating.unit'].search([('name', '=ilike', str(sel.job_location).strip())], limit=1)
                if ou:
                    hiring_ou = ou
            elif self.env.context.get('parent_operating_unit_id'):
                p_ou = self.env.context.get('parent_operating_unit_id')
                hiring_ou = self.env['operating.unit'].browse(p_ou) if isinstance(p_ou, int) else p_ou
            elif self.env.context.get('parent_workunit_id'):
                p_wu = self.env.context.get('parent_workunit_id')
                hiring_ou = self.env['operating.unit'].browse(p_wu) if isinstance(p_wu, int) else p_wu

            if hiring_ou and hiring_ou.exists():
                if not _is_district_or_branch_ou(hiring_ou):
                    ou_set.update(_get_ho_root_and_children(hiring_ou))
                else:
                    ou_set.add(hiring_ou.id)
                    parent = getattr(hiring_ou, 'parent_unit', False)
                    if parent and parent.exists():
                        ou_set.add(parent.id)
                    else:
                        district_name = getattr(hiring_ou, 'district', False)
                        if district_name and isinstance(district_name, str) and district_name.strip() and district_name.lower() not in ('false', 'none', 'n/a'):
                            dist_ou = self.env['operating.unit'].search([('name', '=ilike', district_name.strip())], limit=1)
                            if dist_ou and dist_ou.exists():
                                ou_set.add(dist_ou.id)

            # Responsible Person's Operating Unit (for both Head Office and District)
            if vac and getattr(vac, 'responsible', False) and vac.responsible and getattr(vac.responsible, 'default_operating_unit_id', False):
                ou_set.add(vac.responsible.default_operating_unit_id.id)
            if vac and getattr(vac, 'responsible_employee', False) and vac.responsible_employee and getattr(vac.responsible_employee, 'default_operating_unit_id', False):
                ou_set.add(vac.responsible_employee.default_operating_unit_id.id)
            if sel and getattr(sel, 'responsible_employee', False) and sel.responsible_employee and getattr(sel.responsible_employee, 'default_operating_unit_id', False):
                ou_set.add(sel.responsible_employee.default_operating_unit_id.id)
            if self.env.context.get('parent_responsible_id'):
                r_id = self.env.context.get('parent_responsible_id')
                emp = self.env['hr.employee'].browse(r_id) if isinstance(r_id, int) else r_id
                if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
                    ou_set.add(emp.default_operating_unit_id.id)

            if ou_set:
                employees = self.env['hr.employee'].search([
                    ('default_operating_unit_id', 'in', list(ou_set)),
                    ('active', '=', True),
                    ('user_id', '!=', False)
                ])
                user_ids = employees.mapped('user_id').ids
                if user_ids:
                    return [('id', 'in', user_ids)]

        # 2. Panel Member & Secretary: Strictly from Vacancy Responsible Officer's Work Unit (HR / Recruitment)
        elif role_val == 'secretary':
            resp_ou = False
            if vac and hasattr(vac, 'responsible') and vac.responsible and vac.responsible.default_operating_unit_id:
                resp_ou = vac.responsible.default_operating_unit_id.id
            elif self.env.context.get('parent_responsible_id'):
                r_id = self.env.context.get('parent_responsible_id')
                emp = self.env['hr.employee'].browse(r_id) if isinstance(r_id, int) else r_id
                if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
                    resp_ou = emp.default_operating_unit_id.id
            if not resp_ou:
                ou = self.env['operating.unit'].search([('name', 'ilike', 'Onboarding and Recruitment')], limit=1)
                if not ou:
                    ou = self.env['operating.unit'].search([('name', 'ilike', 'Recruitment')], limit=1)
                if ou:
                    resp_ou = ou.id
            if resp_ou:
                employees = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', resp_ou),
                    ('active', '=', True),
                    ('user_id', '!=', False)
                ])
                user_ids = employees.mapped('user_id').ids
                if user_ids:
                    return [('id', 'in', user_ids)]

        # 3. Chairperson / Observer / Default: All active employees linked to users
        all_emps = self.env['hr.employee'].search([
            ('active', '=', True),
            ('user_id', '!=', False)
        ])
        user_ids = all_emps.mapped('user_id').ids
        return [('id', 'in', user_ids)] if user_ids else []

    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="Status", default="active")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    is_mandatory = fields.Boolean(string="Mandatory?", default=True)
    digital_signature = fields.Binary(string="Digital Signature", copy=False)
    signed_on = fields.Datetime(string="Signed Date & Time", readonly=True, copy=False)
    approve = fields.Boolean(string="Approve", readonly=True)
    new_rec_del_id = fields.Many2one("new.internal.recruitment.selected", string="Internal Recruitment Selected Delegation Team")
	


class InternalRecruitmentSelectedCandidates(models.Model):
    _name = "new.internal.recruitment.selected.candidates"
    _description = "New Internal Recruitment Selected Candidates"
    _order = "rank asc, weighted_score desc, id asc"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


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
    emp_position = fields.Char(string="Position", compute="_compute_employee_details", store=False)
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
    emp_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    emp_gender = fields.Char(string="Gender")
    current_work_unit = fields.Char(string="Current Location", compute="_compute_employee_details", store=False)
    current_department = fields.Char(string="Current Department", compute="_compute_employee_details", store=False)
    service_in_company = fields.Float(string="Service in Company")
    educational_qualification = fields.Char(string="Educational Qualification")
    cgpa = fields.Float(string="CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(
        string="PMS Score",
        store=True,
        help="Pre-filled from the employee's active contract PMS score. Can be manually overridden by HR."
    )
    preferred_location=fields.Char(string="Preferred Location")
    #preferred_location = fields.Many2one( "operating.unit",  string="Preferred Location")
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    written_exam_score = fields.Float(string="Written Exam Score")
    interview_score = fields.Float(string="Interview Score")
    supervisor_recommendation_score = fields.Float(string="Supervisor Recommendation Score", default=0.0)
    supervisor_remarks = fields.Text(string="Supervisor Recommendation Remarks")
    application_date = fields.Date(
        string="Application Date",
        compute="_compute_application_date",
        store=True,
        readonly=False,
    )
    app_date_score = fields.Float(string="App Date Score", default=0.0)
    experience_score = fields.Float(string="Experience Score", default=0.0)
    location_score = fields.Float(string="Location Score", default=0.0)

    @api.depends('create_date')
    def _compute_application_date(self):
        for rec in self:
            if not rec.application_date:
                rec.application_date = rec.create_date.date() if rec.create_date else fields.Date.context_today(rec)

    # pms_score = fields.Float(string="PMS Score")
    weighted_score = fields.Float(string="Weighted Score")
    rank = fields.Integer(string="Rank", default=0)
    # selection_type = fields.Char(string="Selection Type")
    exam_notified =fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([
        ('pending', 'Pending Evaluation'),
        ('shortlisted', 'Shortlisted'),
        ('exam', 'Selected for Exam'),
        ('interview', 'Selected for Interview'),
        ('selected', 'Selected to hire'),
        ('reserve', 'Reserved'),
        ('rejected', 'Disqualified')
    ], string="Result", default='pending')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select",default=True)
    new_int_sel_cand = fields.Many2one("new.internal.recruitment.selected", string="Selected candidates for Recruitment")

    promotion_type = fields.Selection([
        ('same_unit', 'Same Work Unit'),
        ('diff_unit', 'Different Work Unit')
    ], string="Promotion Type", compute="_compute_promotion_type", store=True)

    promotion_status = fields.Selection([
        ('draft', 'Pending'),
        ('promoted', 'Promoted (Same Unit)'),
        ('pending_release', 'Pending Release'),
        ('released', 'Released & Promoted')
    ], string="Promotion Status", default='draft')

    coach_id = fields.Many2one("hr.employee", string="Coach / Manager", compute="_compute_coach_id", store=True, readonly=False)
    release_date = fields.Date(string="Release Date")
    release_remarks = fields.Text(string="Release Remarks")
    release_handover = fields.Selection([
        ('completed', 'Handover Completed'),
        ('pending', 'Pending Handover')
    ], string="Handover Status")

    acceptance_status = fields.Selection([
        ('pending', 'Pending Response'),
        ('accepted', 'Accepted'),
        ('rejected', 'Declined')
    ], string="Offer Acceptance Status", default='pending')
    acceptance_date = fields.Date(string="Response Date")
    rejection_reason = fields.Text(string="Reason for Declining")

    def action_accept_promotion(self):
        """Candidate accepts the promotion/transfer offer."""
        for rec in self:
            rec.write({
                'acceptance_status': 'accepted',
                'acceptance_date': fields.Date.context_today(self),
            })
            emp_name = rec.emp_name.name if rec.emp_name else _('Candidate')
            parent_rec = rec.new_int_sel_cand
            if parent_rec:
                parent_rec.message_post(
                    body=_("<b>Offer Accepted:</b> Candidate <b>%s</b> has ACCEPTED the promotion/transfer offer.") % emp_name
                )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offer Accepted'),
                'message': _('Promotion/Transfer offer accepted successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_decline_promotion(self):
        """Opens decline wizard to capture reason for declining promotion/transfer offer."""
        self.ensure_one()
        return {
            'name': _('Decline / Reject Promotion or Transfer Offer'),
            'type': 'ir.actions.act_window',
            'res_model': 'internal.selection.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
            }
        }

    def confirm_decline_promotion(self, reason):
        """
        Executed when a candidate declines the promotion/transfer offer.
        Marks candidate as rejected/declined, then automatically promotes the next
        highest-ranked candidate from the Reserve Pool (score >= 50%) and dispatches notification.
        """
        for rec in self:
            emp_name = rec.emp_name.name if rec.emp_name else _('Candidate')
            parent_rec = rec.new_int_sel_cand

            rec.write({
                'acceptance_status': 'rejected',
                'acceptance_date': fields.Date.context_today(self),
                'rejection_reason': reason,
                'selection_type': 'rejected',
                'select_flag': False,
                'remarks': _("Offer Declined: %s") % reason,
            })

            if parent_rec:
                parent_rec.message_post(
                    body=Markup(_("<b>Offer Declined:</b> Candidate <b>%s</b> has declined the promotion/transfer offer.<br/><b>Reason:</b> %s") % (emp_name, reason))
                )

                # ── AUTO-REPLACEMENT FROM RESERVE POOL ──
                reserve_cands = parent_rec.new_int_rec_sel.filtered(
                    lambda c: c.id != rec.id
                    and c.selection_type in ('reserve', 'reserved', 'Reserve', 'Reserved')
                    and (c.weighted_score or 0.0) >= 50.0
                    and c.emp_name
                ).sorted(key=lambda c: (c.rank or 9999, -(c.weighted_score or 0.0)))

                if reserve_cands:
                    next_cand = reserve_cands[0]
                    next_name = next_cand.emp_name.name
                    next_cand.write({
                        'selection_type': 'selected',
                        'select_flag': True,
                        'acceptance_status': 'pending',
                        'remarks': _("Promoted from Reserve Pool following decline by %s (Rank: %s, Score: %.2f%%).") % (
                            emp_name, next_cand.rank, next_cand.weighted_score or 0.0
                        )
                    })

                    # Dispatch Selection Notification to newly promoted reserve candidate
                    vac_id = parent_rec.vacancy_id if isinstance(parent_rec.vacancy_id, int) else getattr(parent_rec.vacancy_id, 'id', False)
                    vac_ref = getattr(parent_rec, 'vacancy_reference', False) or getattr(parent_rec, 'recruitment_reference', False)
                    vac = parent_rec.env["job.vacancy"].browse(vac_id) if vac_id else (parent_rec.env["job.vacancy"].search([("reference", "=", vac_ref)], limit=1) if vac_ref else False)
                    is_lat = (
                        (vac and getattr(vac, 'internal_movement_type', False) in ('lateral', 'transfer'))
                        or (vac and getattr(vac, 'transfer_eval_mode', False) == 'transfer_matrix_only')
                        or (vac_ref and 'LAT' in str(vac_ref).upper())
                        or (getattr(parent_rec, 'transfer_eval_mode', False) == 'transfer_matrix_only')
                    )

                    usr = parent_rec._get_partner_for_employee(next_cand.emp_name)
                    pos_title = parent_rec.job_position.name if parent_rec.job_position else (parent_rec._get_position_title() if hasattr(parent_rec, '_get_position_title') else '')
                    if usr:
                        if is_lat:
                            msg1 = _("We are pleased to inform you that you have been Selected for Lateral Transfer from the Reserve Pool for the position of ")
                            summary_msg = _('Action Required: Respond to Transfer Offer (%s)') % pos_title
                            note_txt = _("<p>You have been selected from the Reserve Pool. <a href='%s'>Click here to Review and Respond to Transfer Offer</a></p>")
                        else:
                            msg1 = _("We are pleased to inform you that you have been Selected for Internal Promotion from the Reserve Pool for the position of ")
                            summary_msg = _('Action Required: Respond to Promotion Offer (%s)') % pos_title
                            note_txt = _("<p>You have been selected from the Reserve Pool. <a href='%s'>Click here to Review and Respond to Promotion Offer</a></p>")

                        msg2 = _("\n\nPlease review and indicate your acceptance/response via the ERP portal.\n\nCongratulations!")
                        parent_rec.mail_channel_msgs_selection(usr.id, next_name, msg1, pos_title, msg2, candidate_id=next_cand.id, is_lateral=is_lat)
                        if next_cand.emp_name and next_cand.emp_name.user_id:
                            try:
                                todo_type = parent_rec.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                                base_url = parent_rec.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                                p_url = f"{base_url.rstrip('/')}/recruitment/transfer_acceptance/{next_cand.id}" if base_url else f"/recruitment/transfer_acceptance/{next_cand.id}"
                                parent_rec.activity_schedule(
                                    activity_type_id=todo_type.id if todo_type else False,
                                    summary=summary_msg,
                                    note=Markup(note_txt % p_url),
                                    user_id=next_cand.emp_name.user_id.id,
                                )
                            except Exception:
                                pass

                    parent_rec.message_post(
                        body=Markup(_(
                            "<b>Automatic Reserve Promotion:</b> Candidate <b>%s</b> has been automatically promoted from the Reserve Pool to <b>Selected</b> (Rank: %s, Score: %.2f%%) and notified to accept/decline."
                        ) % (next_name, next_cand.rank, next_cand.weighted_score or 0.0))
                    )
        return True

    def action_open_supervisor_rec_wizard(self):
        """Opens modal wizard to grade / grant supervisor recommendation marks for this candidate."""
        self.ensure_one()
        vac = False
        if self.new_int_sel_cand and self.new_int_sel_cand.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.new_int_sel_cand.vacancy_id)
        elif self.new_int_sel_cand and self.new_int_sel_cand.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.new_int_sel_cand.vacancy_reference)], limit=1)

        emp = self.emp_name
        sup = emp.parent_id if emp and emp.parent_id else (emp.coach_id if emp and emp.coach_id else False)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Grant Supervisor Recommendation Marks'),
            'res_model': 'supervisor.recommendation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
                'default_vacancy_id': vac.id if vac and vac.exists() else False,
                'default_selected_recruitment_id': self.new_int_sel_cand.id if self.new_int_sel_cand else False,
                'default_employee_id': emp.id if emp else False,
                'default_job_position': vac.job_position.name if vac and vac.job_position else (self.new_int_sel_cand.job_position.name if self.new_int_sel_cand and self.new_int_sel_cand.job_position else ''),
                'default_current_position': emp.job_id.name if emp and emp.job_id else (emp.job_position.name if emp and emp.job_position else ''),
                'default_current_grade': emp.job_grade.grade_name if emp and emp.job_grade else '',
                'default_current_work_unit': emp.default_operating_unit_id.name if emp and emp.default_operating_unit_id else '',
                'default_current_department': emp.department_id.name if emp and emp.department_id else '',
                'default_service_in_company': self.service_in_company or 0.0,
                'default_pms_score': self.pms_score or 0.0,
                'default_supervisor_id': sup.id if sup else False,
                'default_recommendation_score': self.supervisor_recommendation_score or 100.0,
                'default_recommendation_remarks': self.supervisor_remarks or '',
                'default_is_batch': False,
            }
        }

    # ── Promotion Letter Fields (Official Bunna Bank Stationery) ──────────
    promotion_ref_no = fields.Char(string="Promotion Reference No", copy=False, readonly=True)
    salutation = fields.Selection([
        ('ato', 'Ato'),
        ('woy', 'W/y'),
        ('wro', 'W/ro')
    ], string="Salutation", compute="_compute_salutation", store=True, readonly=False)
    promoted_salary = fields.Float(string="Promoted Monthly Salary (ETB)", default=0.0)
    promotion_date = fields.Date(string="Promotion Date", default=fields.Date.context_today)
    signatory_config_id = fields.Many2one('recruitment.signatory.config', string="Signatory Configuration")


    @api.depends('emp_name', 'emp_name.gender')
    def _compute_salutation(self):
        for rec in self:
            gender = rec.emp_name.gender if rec.emp_name else False
            if gender == 'female':
                rec.salutation = 'woy'
            elif gender == 'male':
                rec.salutation = 'ato'
            elif not rec.salutation:
                rec.salutation = 'ato'

    def get_salutation_label(self):
        self.ensure_one()
        # Direct check on employee gender for 100% accuracy
        if self.emp_name and self.emp_name.gender:
            g = str(self.emp_name.gender).strip().lower()
            if g == 'female':
                return 'W/y'
            elif g == 'male':
                return 'Ato'
        if self.salutation:
            labels = dict(self._fields['salutation'].selection)
            return labels.get(self.salutation, 'Ato/W/y')
        return 'Ato/W/y'

    def _get_grade_base_salary(self):
        """Retrieve the official monthly base salary defined for the candidate's target employee grade."""
        self.ensure_one()
        grade_val = False
        if self.new_int_sel_cand:
            grade_val = self.new_int_sel_cand.job_grade or getattr(self.new_int_sel_cand, 'job_grade_id', False)
        if not grade_val and getattr(self, 'vacancy_id', False):
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
            if vac and vac.exists():
                grade_val = getattr(vac, 'job_grade', False) or getattr(vac, 'grade', False)

        salary = 0.0
        # 1. Look up via employee.grade ORM model
        if grade_val and 'employee.grade' in self.env:
            grade_rec = False
            if isinstance(grade_val, int):
                grade_rec = self.env['employee.grade'].browse(grade_val)
            elif hasattr(grade_val, 'base_salary'):
                grade_rec = grade_val
            else:
                g_str = _format_clean_text(grade_val)
                grade_rec = self.env['employee.grade'].search([
                    '|', ('grade_name', '=ilike', str(g_str).strip()), ('grade_code', '=ilike', str(g_str).strip())
                ], limit=1)
                if not grade_rec and 'grade' in str(g_str).lower():
                    clean_str = str(g_str).lower().replace('grade', '').strip()
                    grade_rec = self.env['employee.grade'].search([
                        '|', ('grade_name', '=ilike', clean_str), ('grade_code', '=ilike', clean_str)
                    ], limit=1)
            if grade_rec and grade_rec.exists():
                salary = getattr(grade_rec, 'base_salary', 0.0) or getattr(grade_rec, 'starting_salary', 0.0) or 0.0

        # 2. Look up via hr.employee.grade ORM model
        if not salary and grade_val and 'hr.employee.grade' in self.env:
            grade_rec = False
            if isinstance(grade_val, int):
                grade_rec = self.env['hr.employee.grade'].browse(grade_val)
            else:
                g_str = _format_clean_text(grade_val)
                grade_rec = self.env['hr.employee.grade'].search([
                    '|', ('name', '=ilike', str(g_str).strip()), ('code', '=ilike', str(g_str).strip())
                ], limit=1)
            if grade_rec and grade_rec.exists():
                salary = getattr(grade_rec, 'base_salary', 0.0) or 0.0

        # 3. Direct SQL query fallback on employee_grade table (covers custom DB setups)
        if not salary and grade_val:
            g_str = _format_clean_text(grade_val)
            clean_code = str(g_str).replace('Grade', '').replace('grade', '').strip()
            try:
                self.env.cr.execute("""
                    SELECT base_salary FROM employee_grade 
                    WHERE base_salary > 0 AND (
                        grade_name ILIKE %s OR grade_code ILIKE %s OR 
                        grade_code ILIKE %s OR grade_name ILIKE %s
                    )
                    ORDER BY id DESC LIMIT 1
                """, (f"%{g_str}%", f"%{g_str}%", f"{clean_code}", f"%{clean_code}%"))
                row = self.env.cr.fetchone()
                if row and row[0]:
                    salary = float(row[0])
            except Exception:
                pass

        return salary or 0.0

    def compute_promoted_salary_from_grade_and_version(self):
        """
        Computes promoted salary step based on:
        1. Candidate's current wage from hr_versions / contract / employee (W_current).
        2. Target grade base salary and increment steps (S_0, S_1, S_2, ..., S_10).
        3. Algorithm:
           - S_0 = target_grade.base_salary
           - Step increments S_1..S_10 from target_grade.increment_id (amount_1..amount_10) 
             or dynamically computed using salary_factor.
           - Iterate through steps S_0, S_1, S_2, ...
             - If step S <= W_current: skip step (current wage already >= S).
             - If step S > W_current:
               - Calculate diff = S - W_current.
               - If diff < 1000 ETB: skip step (raise gain is less than 1000 ETB threshold).
               - If diff >= 1000 ETB: select step S.
        """
        self.ensure_one()
        emp = self.emp_name
        current_wage = 0.0

        if emp:
            if hasattr(emp, 'version_id') and emp.version_id and getattr(emp.version_id, 'wage', False):
                current_wage = float(emp.version_id.wage or 0.0)
            if not current_wage and 'hr.version' in self.env:
                ver = self.env['hr.version'].sudo().search([('employee_id', '=', emp.id)], limit=1)
                if ver and getattr(ver, 'wage', False):
                    current_wage = float(ver.wage or 0.0)
            if not current_wage and hasattr(emp, 'contract_id') and emp.contract_id and getattr(emp.contract_id, 'wage', False):
                current_wage = float(emp.contract_id.wage or 0.0)
            if not current_wage and hasattr(emp, 'wage') and emp.wage:
                current_wage = float(emp.wage or 0.0)

        grade_val = False
        if self.new_int_sel_cand:
            grade_val = self.new_int_sel_cand.job_grade or getattr(self.new_int_sel_cand, 'job_grade_id', False)
        if not grade_val and getattr(self, 'vacancy_id', False):
            vac_id = self.vacancy_id.id if hasattr(self.vacancy_id, 'id') else self.vacancy_id
            vac = self.env['job.vacancy'].browse(vac_id)
            if vac and vac.exists():
                grade_val = getattr(vac.job_id, 'job_grade', False) or getattr(vac, 'job_grade', False) or getattr(vac, 'grade', False)

        grade_rec = False
        if grade_val and 'employee.grade' in self.env:
            if isinstance(grade_val, int):
                grade_rec = self.env['employee.grade'].browse(grade_val)
            elif hasattr(grade_val, 'base_salary') or hasattr(grade_val, 'salary_factor'):
                grade_rec = grade_val
            else:
                g_str = _format_clean_text(grade_val)
                if g_str:
                    grade_rec = self.env['employee.grade'].search([
                        '|', ('grade_name', '=ilike', str(g_str).strip()), ('grade_code', '=ilike', str(g_str).strip())
                    ], limit=1)

        base_salary = 0.0
        salary_factor = 1.05

        if grade_rec and grade_rec.exists():
            base_salary = float(getattr(grade_rec, 'base_salary', 0.0) or getattr(grade_rec, 'starting_salary', 0.0) or 0.0)
            salary_factor = float(getattr(grade_rec, 'salary_factor', 1.05) or 1.05)

        if not base_salary:
            base_salary = float(self._get_grade_base_salary() or 0.0)

        steps = []
        if base_salary > 0:
            steps.append(base_salary)

        if grade_rec and grade_rec.exists() and hasattr(grade_rec, 'increment_id') and grade_rec.increment_id:
            inc = grade_rec.increment_id
            for seq in range(1, 11):
                amt = float(getattr(inc, f'amount_{seq}', 0.0) or 0.0)
                if amt > 0:
                    steps.append(amt)

        if len(steps) <= 1 and base_salary > 0 and salary_factor > 1.0:
            curr_step = base_salary
            for _ in range(1, 11):
                curr_step = round(curr_step * salary_factor, 2)
                steps.append(curr_step)

        if not steps:
            return current_wage or 0.0

        steps = sorted(list(set(steps)))

        if current_wage <= 0:
            return steps[0]

        chosen_salary = False
        for step_val in steps:
            if step_val <= current_wage:
                continue
            diff = step_val - current_wage
            if diff >= 1000.0:
                chosen_salary = step_val
                break

        if not chosen_salary:
            highest_step = steps[-1]
            factor = salary_factor if salary_factor > 1.0 else 1.05
            curr_step = max(highest_step, current_wage)
            while True:
                curr_step = round(curr_step * factor, 2)
                if (curr_step - current_wage) >= 1000.0:
                    chosen_salary = curr_step
                    break

        return chosen_salary or current_wage or 0.0

    def get_promoted_salary_figure(self):
        """Returns the monthly salary figure, resolving automatically from target grade steps & hr_versions wage."""
        self.ensure_one()
        sal = self.compute_promoted_salary_from_grade_and_version()
        if sal and sal > 0 and self.promoted_salary != sal:
            try:
                self.sudo().write({'promoted_salary': sal})
            except Exception:
                pass
        return sal or self.promoted_salary or 0.0

    def get_promoted_salary_in_words(self):
        self.ensure_one()
        sal = self.get_promoted_salary_figure()
        if sal and sal > 0:
            return amount_to_words_birr(sal)
        return ""

    def _get_parent_vacancy(self):
        self.ensure_one()
        parent_rec = self.new_int_sel_cand
        if parent_rec:
            if getattr(parent_rec, 'vacancy_id', False):
                vac_id = parent_rec.vacancy_id
                if isinstance(vac_id, int):
                    vac = self.env['job.vacancy'].browse(vac_id)
                    if vac.exists():
                        return vac
                elif hasattr(vac_id, 'job_position'):
                    return vac_id
            if getattr(parent_rec, 'vacancy_reference', False):
                vac = self.env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)
                if vac.exists():
                    return vac
        return False

    def get_new_job_position_name(self):
        self.ensure_one()
        vac = self._get_parent_vacancy()
        if vac and vac.job_position:
            return vac.job_position.name
        if self.new_int_sel_cand and self.new_int_sel_cand.job_position:
            return self.new_int_sel_cand.job_position.name
        return ""

    def get_new_job_grade_name(self):
        self.ensure_one()
        vac = self._get_parent_vacancy()
        if vac and vac.job_grade:
            return _format_clean_text(vac.job_grade)
        if self.new_int_sel_cand:
            grade_val = self.new_int_sel_cand.job_grade or getattr(self.new_int_sel_cand, 'job_grade_id', False)
            if grade_val:
                return _format_clean_text(grade_val)
        return ""

    def get_target_work_unit_name(self):
        self.ensure_one()
        if self.preferred_location:
            return _format_clean_text(self.preferred_location)
        vac = self._get_parent_vacancy()
        if vac and vac.operating_unit_id:
            return _format_clean_text(vac.operating_unit_id.name)
        parent_rec = self.new_int_sel_cand
        if parent_rec and parent_rec.job_location:
            return _format_clean_text(parent_rec.job_location)
        return ""

    def get_current_work_unit_name(self):
        self.ensure_one()
        if self.current_work_unit:
            return _format_clean_text(self.current_work_unit)
        if self.emp_name:
            unit = getattr(self.emp_name, 'default_operating_unit_id', False) or getattr(self.emp_name, 'operating_unit_id', False)
            if unit:
                return _format_clean_text(unit.name)
        return ""

    def is_candidate_in_pomd(self):
        self.ensure_one()
        curr_dept = (self.current_department or (self.emp_name.department_id.name if self.emp_name and self.emp_name.department_id else '')).lower()
        curr_unit = (self.current_work_unit or (self.emp_name.default_operating_unit_id.name if self.emp_name and getattr(self.emp_name, 'default_operating_unit_id', False) else '')).lower()
        return (
            'pomd' in curr_dept or 'people' in curr_dept or 'human resource' in curr_dept or
            'pomd' in curr_unit or 'people' in curr_unit or 'human resource' in curr_unit
        )

    def get_letter_subject(self):
        self.ensure_one()
        parent_rec = self.new_int_sel_cand
        vac = False
        if parent_rec and parent_rec.vacancy_id:
            vac = self.env['job.vacancy'].browse(parent_rec.vacancy_id)
        elif parent_rec and parent_rec.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)
        if (parent_rec and parent_rec.transfer_eval_mode == 'transfer_matrix_only') or (vac and (vac.transfer_eval_mode == 'transfer_matrix_only' or vac.internal_movement_type in ('lateral', 'transfer'))):
            return "Lateral Transfer"
        return "Promotion"

    def get_letter_action_verb(self):
        self.ensure_one()
        if self.get_letter_subject() == "Lateral Transfer":
            return "transferred"
        return "promoted"

    def get_signatory_config(self):
        self.ensure_one()
        if self.signatory_config_id:
            return self.signatory_config_id
        target_unit = self.get_target_work_unit_name() or self.get_current_work_unit_name()
        sig = False
        if 'recruitment.signatory.config' in self.env:
            sig = self.env['recruitment.signatory.config'].get_signatory_for_unit(
                work_unit=target_unit, doc_type='promotion_letter'
            )
            if not sig:
                sig = self.env['recruitment.signatory.config'].get_signatory_for_unit(
                    work_unit=target_unit, doc_type='employment_letter'
                )
            if not sig:
                sig = self.env['recruitment.signatory.config'].search([('active', '=', True)], limit=1)
        return sig or False

    def get_signatory_name(self):
        self.ensure_one()
        sig = self.signatory_config_id or self.get_signatory_config()
        if sig and sig.signatory_name:
            return sig.signatory_name
        return ""

    def get_signatory_title(self):
        self.ensure_one()
        sig = self.signatory_config_id or self.get_signatory_config()
        if sig and sig.signatory_title:
            return sig.signatory_title
        return "Director, People Operations Management Directorate"

    def get_signatory_company(self):
        self.ensure_one()
        sig = self.signatory_config_id or self.get_signatory_config()
        if sig and sig.signatory_company:
            return sig.signatory_company
        return "Bunna Bank S.C."

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_signature_stamp_base64(self):
        self.ensure_one()
        sig = self.signatory_config_id or self.get_signatory_config()
        if sig:
            b64 = sig.get_signature_stamp_base64()
            if b64:
                return b64

        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    def get_promotion_letter_cc_lines(self):
        self.ensure_one()
        lines = []
        curr_unit = self.get_current_work_unit_name()
        target_unit = self.get_target_work_unit_name()

        if curr_unit:
            lines.append(f"{curr_unit}")
        if target_unit and target_unit != curr_unit:
            lines.append(f"{target_unit}")

        lines.append("IT Security Management Directorate")
        lines.append("People Operations Management Directorate")
        return lines

    def action_print_promotion_letter(self):
        self.ensure_one()
        if not self.promotion_ref_no:
            seq_val = self.env['ir.sequence'].next_by_code('bunna.internal.promotion.letter')
            self.promotion_ref_no = seq_val or ('BB/TAOD/%04d/%s' % (self.id, fields.Date.today().year))
        if not self.promotion_date:
            self.promotion_date = fields.Date.context_today(self)
        if not self.promoted_salary or self.promoted_salary <= 0:
            self.promoted_salary = self.get_promoted_salary_figure()
        if not self.signatory_config_id:
            sig = self.get_signatory_config()
            if sig:
                self.signatory_config_id = sig.id
        return self.env.ref('custom_recruitment.action_report_internal_promotion_letter').report_action(self)

    def action_send_promotion_notification(self):
        for rec in self:
            if not rec.emp_name:
                continue
            ref_no = rec.promotion_ref_no or 'N/A'
            unit_type_msg = _("Same Work Unit") if rec.promotion_type == 'same_unit' else _("Different Work Unit (Pending Release)")
            letter_type_msg = _("Image 1 (Different Work Unit with Release Clause)") if rec.promotion_type == 'diff_unit' else _("Image 2 (Same Work Unit)")
            body_html = Markup(
                "<b>%(title)s: %(emp_name)s</b><br/>"
                "• Promotion Reference: <b>%(ref_no)s</b><br/>"
                "• Promoted Position: %(job)s<br/>"
                "• Job Grade: %(grade)s<br/>"
                "• Target Work Unit: %(target_unit)s<br/>"
                "• Transfer Status: <i>%(status)s</i><br/>"
                "• Official Promotion Letter: %(letter_type)s has been issued."
            ) % {
                'title': _("Internal Promotion Notification"),
                'emp_name': rec.emp_name.name,
                'ref_no': ref_no,
                'job': rec.get_new_job_position_name() or 'N/A',
                'grade': rec.get_new_job_grade_name() or 'N/A',
                'target_unit': rec.get_target_work_unit_name() or 'N/A',
                'status': unit_type_msg,
                'letter_type': letter_type_msg,
            }
            if rec.new_int_sel_cand:
                rec.new_int_sel_cand.message_post(body=body_html, message_type='notification')
            if hasattr(rec.emp_name, 'message_post'):
                rec.emp_name.message_post(body=body_html, message_type='notification')

    @api.depends('current_work_unit', 'preferred_location', 'new_int_sel_cand.job_location', 'new_int_sel_cand.vacancy_id', 'emp_name', 'emp_name.default_operating_unit_id')
    def _compute_promotion_type(self):
        for rec in self:
            cand_unit = rec.get_current_work_unit_name()
            if not cand_unit and rec.emp_name and getattr(rec.emp_name, 'default_operating_unit_id', False):
                cand_unit = rec.emp_name.default_operating_unit_id.name or ''
            cand_unit = cand_unit.strip().lower()

            target_unit = rec.get_target_work_unit_name()
            if not target_unit and rec.new_int_sel_cand and rec.new_int_sel_cand.job_location:
                target_unit = rec.new_int_sel_cand.job_location or ''
            if not target_unit and rec.new_int_sel_cand and getattr(rec.new_int_sel_cand, 'vacancy_id', False):
                vac = rec.new_int_sel_cand.vacancy_id
                if isinstance(vac, int) and vac > 0:
                    vac = self.env['job.vacancy'].browse(vac)
                if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
                    target_unit = vac.operating_unit_id.name or ''
            target_unit = target_unit.strip().lower()

            if cand_unit and target_unit and cand_unit != target_unit:
                rec.promotion_type = 'diff_unit'
            else:
                rec.promotion_type = 'same_unit'

    @api.depends('emp_name')
    def _compute_coach_id(self):
        for rec in self:
            if rec.emp_name:
                rec.coach_id = rec.emp_name.coach_id or rec.emp_name.parent_id or False
            else:
                rec.coach_id = False

    def action_open_release_wizard(self):
        self = self.sudo()
        self.ensure_one()
        if self.promotion_type == 'same_unit':
            raise UserError(_("This candidate is promoted within the Same Work Unit. No release form is required as employee master data and versioned contract records are updated automatically."))

        emp = self.emp_name.sudo() if self.emp_name else False
        parent_rec = self.new_int_sel_cand.sudo() if self.new_int_sel_cand else False

        # 1. Current Position (Ref #1)
        curr_pos = self.emp_position
        if not curr_pos and emp:
            curr_pos = (
                (emp.job_position.name if hasattr(emp, 'job_position') and emp.job_position else False) or
                (emp.job_id.name if hasattr(emp, 'job_id') and emp.job_id else False) or
                (emp.job_name if hasattr(emp, 'job_name') and emp.job_name else False) or
                getattr(emp, 'job_title', False)
            )

        # 2. Current Work Unit (Ref #1)
        curr_unit = self.current_work_unit
        if not curr_unit and emp:
            curr_unit = (
                (emp.default_operating_unit_id.name if getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id else False) or
                (emp.department_id.operating_unit_id.name if getattr(emp, 'department_id', False) and emp.department_id and getattr(emp.department_id, 'operating_unit_id', False) and emp.department_id.operating_unit_id else False) or
                (emp.operating_unit_ids[0].name if getattr(emp, 'operating_unit_ids', False) and emp.operating_unit_ids else False)
            )

        # 3. Target Placement Work Unit (Ref #2)
        target_unit = self.preferred_location or (parent_rec.job_location if parent_rec else False)

        # 4. Vacancy Lookup
        vac = False
        if parent_rec:
            vac_id = getattr(parent_rec, 'vacancy_id', False)
            if isinstance(vac_id, int) and vac_id > 0:
                vac = self.env['job.vacancy'].browse(vac_id)
            elif hasattr(vac_id, 'operating_unit_id'):
                vac = vac_id
            if not vac and getattr(parent_rec, 'vacancy_reference', False):
                vac = self.env['job.vacancy'].search([('reference', '=', parent_rec.vacancy_reference)], limit=1)

        if not vac and getattr(self, 'vacancy_id', False):
            c_vac_id = self.vacancy_id
            if isinstance(c_vac_id, int) and c_vac_id > 0:
                vac = self.env['job.vacancy'].browse(c_vac_id)

        if not target_unit and vac and vac.exists():
            if hasattr(vac, 'hiring_details') and vac.hiring_details:
                units = [hd.work_unit.name for hd in vac.hiring_details if hd.work_unit and hd.work_unit.name]
                if units:
                    target_unit = ", ".join(dict.fromkeys(units))
            if not target_unit and vac.operating_unit_id and vac.operating_unit_id.name:
                target_unit = vac.operating_unit_id.name

        # 5. New Job Position & Grade
        new_job = parent_rec.job_position if parent_rec and parent_rec.job_position else (vac.job_position if vac and vac.exists() else False)

        new_grade_str = False
        if vac and vac.exists():
            if getattr(vac, 'grade', False) and vac.grade and vac.grade.grade_name:
                new_grade_str = vac.grade.grade_name
            elif getattr(vac, 'job_grade', False) and vac.job_grade and vac.job_grade.grade_name:
                new_grade_str = vac.job_grade.grade_name
        if not new_grade_str and new_job:
            if getattr(new_job, 'grade', False) and new_job.grade and new_job.grade.grade_name:
                new_grade_str = new_job.grade.grade_name
            elif getattr(new_job, 'job_grade', False) and new_job.job_grade and new_job.job_grade.grade_name:
                new_grade_str = new_job.job_grade.grade_name
        if not new_grade_str and parent_rec and parent_rec.job_grade:
            new_grade_str = parent_rec.job_grade

        # 6. Coach / Manager
        coach = self.coach_id or (
            emp.coach_id or emp.parent_id if emp else False
        )

        return {
            'name': _('Candidate Release Form (Different Work Unit)'),
            'type': 'ir.actions.act_window',
            'res_model': 'new.internal.recruitment.release.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
                'default_employee_id': emp.id if emp else False,
                'default_current_position': _format_clean_text(curr_pos) or 'N/A',
                'default_current_work_unit': _format_clean_text(curr_unit) or 'N/A',
                'default_target_work_unit': _format_clean_text(target_unit) or 'N/A',
                'default_new_job_position_id': new_job.id if new_job else False,
                'default_new_job_grade': _format_clean_text(new_grade_str) or 'N/A',
                'default_coach_id': coach.id if coach else False,
                'active_id': self.id,
                'active_model': self._name,
            }
        }
    
    @api.depends('emp_name', 'emp_name.job_position', 'emp_name.job_id', 'emp_name.department_id', 'emp_name.default_operating_unit_id')
    def _compute_employee_details(self):
        for record in self:
            if record.emp_name:
                pos_val = record.emp_name.job_position.name if record.emp_name.job_position else (record.emp_name.job_id.name if record.emp_name.job_id else False)
                dept_val = record.emp_name.department_id.name if record.emp_name.department_id else False
                unit_val = record.emp_name.default_operating_unit_id.name if getattr(record.emp_name, 'default_operating_unit_id', False) else False

                record.emp_position = _format_clean_text(pos_val)
                record.current_department = _format_clean_text(dept_val)
                record.current_work_unit = _format_clean_text(unit_val)
            else:
                record.emp_position = False
                record.current_department = False
                record.current_work_unit = False

    @api.onchange('emp_name')
    def _onchange_emp_name_prefill_pms(self):
        """Pre-fill PMS score, experience, service, and application date when employee is selected.
        HR can freely override the values afterward."""
        today = fields.Date.context_today(self)
        for record in self:
            if record.emp_name:
                emp = record.emp_name
                contract_pms = emp.contract_id.pms_score if emp.contract_id else 0.0
                if not record.pms_score:
                    record.pms_score = contract_pms or 0.0
                if not record.application_date:
                    record.application_date = record.create_date.date() if record.create_date else today

                if not record.service_in_company:
                    if getattr(emp, 'months_of_service', False):
                        record.service_in_company = round(emp.months_of_service / 12.0, 2)
                    elif getattr(emp, 'service_start_date', False):
                        record.service_in_company = round((today - emp.service_start_date).days / 365.25, 2)
                    elif getattr(emp, 'joining_date', False):
                        record.service_in_company = round((today - emp.joining_date).days / 365.25, 2)

                if not record.relevant_experience:
                    if getattr(emp, 'relevant_experience', False):
                        record.relevant_experience = emp.relevant_experience
                    elif record.service_in_company:
                        record.relevant_experience = record.service_in_company

class InternalRecruitmentPanel(models.Model):
    _name = "new.internal.recruitment.panel"
    _description = "New Internal Recruitment Panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def _grant_panel_member_group(self):
        group_panel = self.env.ref("assessment_system.group_assessment_panel_member", raise_if_not_found=False)
        if not group_panel:
            return
        for rec in self:
            if rec.emp_name and rec.emp_name.user_id:
                user = rec.emp_name.user_id
                groups = getattr(user, 'group_ids', False) or getattr(user, 'groups_id', False)
                if groups is not False and group_panel not in groups:
                    field_name = 'group_ids' if 'group_ids' in user._fields else 'groups_id'
                    user.sudo().write({field_name: [(4, group_panel.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._grant_panel_member_group()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "emp_name" in vals:
            self._grant_panel_member_group()
        return res

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    emp_position = fields.Char(string="Position")
    position_id = fields.Integer(string="Position Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
    workunit_id = fields.Integer(string="Workunit Id")
    selection_criteria = fields.Selection([
                                       ('Interview', 'Interview')], string="Assessment Type", default='Interview')
    accepted = fields.Boolean(string="Accepted" ,default=False)
    panel_status= fields.Char(string="panel_status")
    select_flag = fields.Boolean(string="Select")
    new_int_panel = fields.Many2one("new.internal.recruitment.selected", string="Select Panel for Recruitment")

    job_position_id = fields.Many2one('hr.job', string="Job Position", related='new_int_panel.job_position', readonly=True)
    interview_date = fields.Datetime(string="Scheduled Date & Time", related='new_int_panel.interview_date', readonly=True)
    interview_location = fields.Text(string="Interview Location", related='new_int_panel.interview_location', readonly=True)
    vacancy_reference = fields.Char(string="Vacancy Reference", related='new_int_panel.vacancy_reference', readonly=True)

    eligible_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_eligible_employee_ids',
        string='Eligible Panel Employees'
    )

    def _get_eligible_panel_info(self, vac=False, sel=False):
        target_ou_ids = set()
        resp_ou_ids = set()

        def _is_district_or_branch_ou(ou_ref):
            if not ou_ref:
                return False
            try:
                curr = ou_ref
                if isinstance(ou_ref, int) and ou_ref > 0:
                    curr = self.env['operating.unit'].browse(ou_ref)
                if not curr or not curr.exists():
                    return False
                w_type = getattr(curr, 'work_unit_type', False)
                if w_type in ('district_office', 'branch', 'sub_branch', 'regional_office', 'service_center'):
                    return True
                name_str = str(getattr(curr, 'name', '') or '').lower()
                code_str = str(getattr(curr, 'code', '') or '').lower()
                return 'branch' in name_str or 'district' in name_str or 'branch' in code_str or 'district' in code_str
            except Exception:
                return False

        def _get_ho_root_and_children(ou_ref):
            res = set()
            if not ou_ref:
                return res
            curr = ou_ref
            if isinstance(ou_ref, int) and ou_ref > 0:
                curr = self.env['operating.unit'].browse(ou_ref)
            if not curr or not curr.exists():
                return res
            while curr.parent_unit and curr.parent_unit.exists() and not _is_district_or_branch_ou(curr.parent_unit):
                curr = curr.parent_unit
            res.add(curr.id)
            frontier = [curr.id]
            while frontier:
                children = self.env['operating.unit'].search([('parent_unit', 'in', frontier)])
                new_ids = set(children.ids) - res
                if not new_ids:
                    break
                res.update(new_ids)
                frontier = list(new_ids)
            return res

        # 1. Hiring Work Unit
        hiring_ou = False
        if vac and getattr(vac, 'operating_unit_id', False):
            hiring_ou = vac.operating_unit_id
        elif sel and getattr(sel, 'workunit_id', False):
            w_id = sel.workunit_id
            hiring_ou = self.env['operating.unit'].browse(w_id) if isinstance(w_id, int) else w_id
        elif sel and getattr(sel, 'job_location', False):
            ou = self.env['operating.unit'].search([('name', '=ilike', str(sel.job_location).strip())], limit=1)
            if ou:
                hiring_ou = ou
        elif self.env.context.get('parent_operating_unit_id'):
            p_ou = self.env.context.get('parent_operating_unit_id')
            hiring_ou = self.env['operating.unit'].browse(p_ou) if isinstance(p_ou, int) else p_ou
        elif self.env.context.get('parent_workunit_id'):
            p_wu = self.env.context.get('parent_workunit_id')
            hiring_ou = self.env['operating.unit'].browse(p_wu) if isinstance(p_wu, int) else p_wu

        if hiring_ou and hiring_ou.exists():
            dept = getattr(hiring_ou, 'department', False)
            dept_name = dept.name if dept else ''

            is_ho = False
            if dept_name and 'head office' in dept_name.lower():
                is_ho = True
            elif not _is_district_or_branch_ou(hiring_ou):
                is_ho = True

            if is_ho:
                # Rule 1 (Head Office): Include ONLY the Hiring Work Unit operating unit itself
                target_ou_ids.add(hiring_ou.id)
            else:
                # Rule 2 (District/Branch - Out of Head Office): Target ONLY the District operating unit
                dist_ou = False
                if dept:
                    dist_ou = self.env['operating.unit'].search([
                        ('name', '=ilike', dept.name),
                        ('work_unit_type', '=', 'district_office')
                    ], limit=1)
                    if not dist_ou:
                        dist_ou = self.env['operating.unit'].search([('name', '=ilike', dept.name)], limit=1)

                if not dist_ou and getattr(hiring_ou, 'parent_unit', False):
                    p = hiring_ou.parent_unit
                    if getattr(p, 'work_unit_type', '') == 'district_office' or 'district' in (p.name or '').lower():
                        dist_ou = p

                if not dist_ou and getattr(hiring_ou, 'district', False):
                    dist_name = hiring_ou.district
                    dist_ou = self.env['operating.unit'].search([('name', '=ilike', dist_name)], limit=1)

                if dist_ou and dist_ou.exists():
                    target_ou_ids.add(dist_ou.id)
                else:
                    target_ou_ids.add(hiring_ou.id)

        # 2. Responsible Person's Operating Unit (for both Head Office and District)
        sources = [s for s in (vac, sel) if s]
        for src in sources:
            if getattr(src, 'responsible', False) and src.responsible:
                resp_emp = src.responsible
                if getattr(resp_emp, 'default_operating_unit_id', False):
                    resp_ou_ids.add(resp_emp.default_operating_unit_id.id)
                if getattr(resp_emp, 'user_id', False) and getattr(resp_emp.user_id, 'employee_id', False):
                    resp_user_emp = resp_emp.user_id.employee_id
                    if getattr(resp_user_emp, 'default_operating_unit_id', False):
                        resp_ou_ids.add(resp_user_emp.default_operating_unit_id.id)
            if getattr(src, 'responsible_employee', False) and src.responsible_employee:
                resp_emp = src.responsible_employee
                if getattr(resp_emp, 'default_operating_unit_id', False):
                    resp_ou_ids.add(resp_emp.default_operating_unit_id.id)

            del_teams = getattr(src, 'vac_del_team_id', False) or getattr(src, 'new_recrt_delegation_team', False) or getattr(src, 'external_recrt_delegation_team', False)
            if del_teams:
                for del_line in del_teams:
                    emp_user = getattr(del_line, 'employee_name', False)
                    if emp_user and getattr(emp_user, 'employee_id', False):
                        emp = emp_user.employee_id
                        if getattr(emp, 'default_operating_unit_id', False):
                            resp_ou_ids.add(emp.default_operating_unit_id.id)
                    alt_user = getattr(del_line, 'alternate_committee_member', False)
                    if alt_user and getattr(alt_user, 'employee_id', False):
                        alt_emp = alt_user.employee_id
                        if getattr(alt_emp, 'default_operating_unit_id', False):
                            resp_ou_ids.add(alt_emp.default_operating_unit_id.id)

            hierarchy_users = [
                getattr(src, 'chairperson_id', False),
                getattr(src, 'panel_member_id', False),
                getattr(src, 'secretary_id', False),
                getattr(src, 'observer_id', False),
            ]
            for user in hierarchy_users:
                if user and getattr(user, 'employee_id', False):
                    emp = user.employee_id
                    if getattr(emp, 'default_operating_unit_id', False):
                        resp_ou_ids.add(emp.default_operating_unit_id.id)

        return list(target_ou_ids), list(resp_ou_ids)

    def _get_eligible_operating_units(self, vac=False, sel=False):
        target_ou_ids, resp_ou_ids = self._get_eligible_panel_info(vac=vac, sel=sel)
        return list(set(target_ou_ids) | set(resp_ou_ids))

    def _get_eligible_employees(self, vac=False, sel=False):
        return self.env['hr.employee'].search([('active', '=', True)])

    @api.depends(
        'new_int_panel',
        'new_int_panel.workunit_id',
        'new_int_panel.chairperson_id',
        'new_int_panel.panel_member_id',
        'new_int_panel.secretary_id',
        'new_int_panel.observer_id',
    )
    def _compute_eligible_employee_ids(self):
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        for rec in self:
            rec.eligible_employee_ids = all_emps

    @api.onchange('new_int_panel', 'selection_criteria')
    def _onchange_new_int_panel_domain(self):
        """Allow all active employees to be selected as panel members."""
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        self.eligible_employee_ids = all_emps
        domain = [('active', '=', True)]
        return {'domain': {'emp_name': domain}}

        domain = [('active', '=', True)]
        self.eligible_employee_ids = self.env['hr.employee'].search(domain)
        return {'domain': {'emp_name': domain}}

    # Rescheduling & Delegation fields
    response_status = fields.Selection([
        ('pending', 'Pending Response'),
        ('accepted', 'Accepted'),
        ('unavailable', 'Unavailable'),
        ('reschedule_requested', 'Reschedule Requested'),
        ('delegation_requested', 'Delegation Requested')
    ], string="Response Status", default='pending')

    response_reason = fields.Text(string="Response Reason / Notes")
    proposed_interview_date = fields.Datetime(string="Proposed Date & Time")
    delegate_employee_id = fields.Many2one("hr.employee", string="Proposed Alternate Member")
    delegation_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_hr', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Delegation Status", default='draft')

    def action_open_response_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel Member Interview Response'),
            'res_model': 'panel.member.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_panel_member_id': self.id,
                'default_internal_selected_id': self.new_int_panel.id if self.new_int_panel else False,
            }
        }

    def action_accept_assignment(self):
        """Allow panel member to directly accept panel invitation in Assessment System."""
        for rec in self:
            rec.write({
                'response_status': 'accepted',
                'accepted': True,
                'response_reason': _("Accepted by panel member"),
            })
            if rec.new_int_panel:
                rec.new_int_panel.message_post(body=_(
                    "Interview Panel Member <b>%s</b> accepted the interview assignment."
                ) % (rec.emp_name.name if rec.emp_name else _("Panel Member")))

    def action_reject_assignment(self):
        """Allow panel member to declare unavailability / reject panel invitation in Assessment System."""
        for rec in self:
            rec.write({
                'response_status': 'unavailable',
                'accepted': False,
                'response_reason': _("Declared unavailable / rejected by panel member"),
            })
            if rec.new_int_panel:
                rec.new_int_panel.message_post(body=_(
                    "Interview Panel Member <b>%s</b> declared unavailability / rejected the interview assignment."
                ) % (rec.emp_name.name if rec.emp_name else _("Panel Member")))

    def action_approve_delegation(self):
        for rec in self:
            if rec.delegation_state != 'pending_hr' or not rec.delegate_employee_id:
                raise UserError(_("No pending delegation request found for approval."))
            old_name = rec.emp_name.name if rec.emp_name else _("Panel Member")
            new_emp = rec.delegate_employee_id
            rec.write({
                'emp_name': new_emp.id,
                'accepted': True,
                'delegation_state': 'approved',
                'response_status': 'accepted',
                'response_reason': _("Delegated from %s (Approved by HR)") % old_name,
            })
            if rec.new_int_panel:
                rec.new_int_panel.message_post(body=_(
                    "HR approved interview panel delegation: <b>%s</b> replaced by <b>%s</b>."
                ) % (old_name, new_emp.name))

    def action_reject_delegation(self):
        for rec in self:
            rec.write({
                'delegation_state': 'rejected',
                'response_status': 'unavailable',
            })
            if rec.new_int_panel:
                rec.new_int_panel.message_post(body=_(
                    "HR rejected panel delegation request for <b>%s</b>."
                ) % (rec.emp_name.name if rec.emp_name else _("Panel Member")))





