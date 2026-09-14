from email.policy import default

from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
import logging
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
    status = fields.Selection([('draft', 'Draft'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status", default='draft')
    state = fields.Selection([('draft', 'Draft'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="State", default='draft')
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

    @api.onchange("job_category", "job_position")
    def _onchange_set_internal_brd_default_weights(self):
        """
        BRD Matrix Default Auto-Population for Internal:
        - Managerial: 60% PMS + 40% Interview (0% Exam)
        - Non-Managerial: 40% PMS + 30% Exam + 30% Interview
        - Junior: 50% PMS + 25% Exam + 25% Interview
        """
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
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date before sending notifications.'))
        count = 0
        position_name = self.job_position.name if self.job_position else ''
        location_name = self.exam_location or 'Main Branch'
        unit_name = self._get_hiring_work_units()

        for val in self.new_int_rec_sel:
            if val.emp_name and val.selection_type != 'rejected':
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

        # 3. Evaluate 50% written exam threshold for candidate selection
        for cand in self.new_int_rec_sel:
            score = cand.written_exam_score or 0.0
            if score < 50.0:
                cand.select_flag = False
                cand.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score

        self.exam_scores_fetched = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Scores Fetched'),
                'message': _('Written Exam scores fetched successfully for %d candidate(s) from Written Assessment Module.') % fetched_count,
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
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date before notifying the panel.'))
        pos_title = self._get_position_title()
        work_unit_str = self._get_hiring_work_units()
        for val in self.new_int_rec_panel:
            if val.emp_name:
                val.write({'response_status': 'pending'})
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, pos_title, self.interview_date, self.interview_location or 'Head Office', work_unit=work_unit_str)
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
            raise UserError(_('Please specify the Interview Date before sending candidate invitations.'))
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
                            self.interview_date, self.interview_location or 'Head Office',
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

            for cand in rec.new_int_rec_sel:
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

                fetched_score = 0.0
                if cbis_res:
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
                        fetched_score = getattr(final_res, 'final_score', 0.0) or getattr(final_res, 'average_score', 0.0) or getattr(final_res, 'interview_score', 0.0) or 0.0
                    else:
                        # Fallback to recruitment.candidate.score
                        score_rec = False
                        if emp_id_int:
                            score_rec = CandScore.search([('employee_id', '=', emp_id_int)], limit=1)
                        if not score_rec and clean_name:
                            score_rec = CandScore.search([('candidate_name', '=ilike', clean_name)], limit=1)
                        if score_rec:
                            fetched_score = getattr(score_rec, 'interview_score', 0.0) or 0.0

                # Calculate updated candidate weighted score
                pms = cand.pms_score or 0.0
                exam = cand.written_exam_score or 0.0
                intv = fetched_score
                weighted = round((pms * pms_w / 100.0) + (exam * exam_w / 100.0) + (intv * int_w / 100.0), 2)

                cand.write({
                    'interview_score': fetched_score,
                    'weighted_score': weighted
                })

            rec.interview_scores_fetched = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Scores Fetched'),
                'message': _('Interview scores fetched successfully from panel final results. Proceed to Compute Final Scores.'),
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
        vacancy-configured weights (PMS %, Written %, Interview %).
        Returns list of (cand_line, weighted_score) tuples sorted by score desc.
        """
        pms_w, exam_w, int_w = self._get_internal_weights()

        all_candidates = [
            cand for cand in self.new_int_rec_sel
            if cand.emp_name
        ]

        # Compute raw weighted score per candidate
        scored = []
        for cand in all_candidates:
            pms  = cand.pms_score or 0.0
            exam = cand.written_exam_score or 0.0
            intv = cand.interview_score or 0.0
            # Weights are percentages — divide by 100
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
            if rec.vacancy_id:
                vac = self.env["job.vacancy"].browse(rec.vacancy_id)
                if vac and vac.no_of_vacancies > 0:
                    vac_slots = vac.no_of_vacancies
            elif rec.vacancy_reference:
                vac = self.env["job.vacancy"].search([("reference", "=", rec.vacancy_reference)], limit=1)
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
                        selected_count += 1
                    else:
                        cand.selection_type = 'rejected'
                        disqualified_count += 1
                else:
                    if score >= 50.0:
                        cand.selection_type = 'reserve'
                        reserve_count += 1
                    else:
                        cand.selection_type = 'rejected'
                        disqualified_count += 1

            total = len(results)

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
                    'You can now click "Generate Minute" to produce the committee minute for selected candidates.'
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

                        # Update salary on contract if specified
                        if cand.promoted_salary and hasattr(emp, 'contract_id') and emp.contract_id:
                            try:
                                emp.contract_id.sudo().write({'wage': cand.promoted_salary})
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
        for val in self.new_int_rec_sel:
            if val.emp_name and (val.select_flag or val.select_flag is None):
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    if val.selection_type in ['selected', 'Selected']:
                        msg1 = _("We are pleased to inform you that you have been Selected for the position of ")
                        msg2 = _("\n\nPlease indicate your acceptance of promotion in the system.\n\nCongratulations!")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
                    elif val.selection_type in ['reserve', 'reserved', 'Reserve', 'Reserved']:
                        msg1 = _("We are pleased to inform you that you have been placed in the Reserve Pool for the position of ")
                        msg2 = _("\n\nYour status is valid for 6 months.")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
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
    
    def mail_channel_msgs_selection(self, rec_id, emp, msg1, position, msg2):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = f"Dear {emp},\n\n{msg1}{position}.{msg2}"
        channel.message_post(
            body=message,
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

        # 1. Panel Member: Strictly from Vacancy's Hiring Work Unit
        if role_val == 'panel_member':
            hiring_ou = False
            if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
                hiring_ou = vac.operating_unit_id.id
            elif sel and getattr(sel, 'workunit_id', False):
                w_id = sel.workunit_id
                hiring_ou = w_id.id if hasattr(w_id, 'id') else w_id
            elif sel and getattr(sel, 'job_location', False):
                ou = self.env['operating.unit'].search([('name', '=ilike', str(sel.job_location).strip())], limit=1)
                if ou:
                    hiring_ou = ou.id
            elif self.env.context.get('parent_operating_unit_id'):
                p_ou = self.env.context.get('parent_operating_unit_id')
                hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)
            elif self.env.context.get('parent_workunit_id'):
                p_wu = self.env.context.get('parent_workunit_id')
                hiring_ou = p_wu if isinstance(p_wu, int) else (p_wu.id if hasattr(p_wu, 'id') else False)

            if hiring_ou:
                employees = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', hiring_ou),
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
    # pms_score = fields.Float(string="PMS Score")
    weighted_score = fields.Float(string="Weighted Score")
    rank = fields.Integer(string="Rank", default=0)
    # selection_type = fields.Char(string="Selection Type")
    exam_notified =fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([
        ('pending', 'Pending Evaluation'),
        ('selected', 'Selected'),
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

    # ── Promotion Letter Fields (Official Bunna Bank Stationery) ──────────
    promotion_ref_no = fields.Char(string="Promotion Reference No", copy=False, readonly=True)
    salutation = fields.Selection([
        ('ato', 'Ato'),
        ('woy', 'W/y'),
        ('wro', 'W/ro')
    ], string="Salutation", compute="_compute_salutation", store=True, readonly=False)
    promoted_salary = fields.Float(string="Promoted Monthly Salary (ETB)", default=0.0)
    promotion_date = fields.Date(string="Promotion Date", default=fields.Date.context_today)
    signatory_config_id = fields.Many2one(
        'recruitment.signatory.config',
        string='Signatory & Stamp Configuration',
        help='Resolved signatory configuration for the target promotion work unit / district.'
    )

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

    def get_promoted_salary_figure(self):
        """Returns the monthly salary figure, resolving automatically from target grade if blank."""
        self.ensure_one()
        sal = self.promoted_salary
        if not sal or sal <= 0:
            sal = self._get_grade_base_salary()
            if sal and sal > 0:
                try:
                    self.sudo().write({'promoted_salary': sal})
                except Exception:
                    pass
        return sal or 0.0

    def get_promoted_salary_in_words(self):
        self.ensure_one()
        sal = self.get_promoted_salary_figure()
        if sal and sal > 0:
            return amount_to_words_birr(sal)
        return ""

    def get_new_job_position_name(self):
        self.ensure_one()
        if self.new_int_sel_cand and self.new_int_sel_cand.job_position:
            return self.new_int_sel_cand.job_position.name
        return ""

    def get_new_job_grade_name(self):
        self.ensure_one()
        if self.new_int_sel_cand:
            grade_val = self.new_int_sel_cand.job_grade or getattr(self.new_int_sel_cand, 'job_grade_id', False)
            if grade_val:
                return _format_clean_text(grade_val)
        return ""

    def get_target_work_unit_name(self):
        self.ensure_one()
        target = self.preferred_location or (self.new_int_sel_cand.job_location if self.new_int_sel_cand else False)
        return _format_clean_text(target) or ""

    def get_current_work_unit_name(self):
        self.ensure_one()
        return _format_clean_text(self.current_work_unit) or ""

    def get_target_operating_unit(self):
        """Resolves the target operating unit (branch or office) for promotion."""
        self.ensure_one()
        if self.new_int_sel_cand and self.new_int_sel_cand.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.new_int_sel_cand.vacancy_id)
            if vac.exists() and vac.operating_unit_id:
                return vac.operating_unit_id

        if self.new_int_sel_cand and self.new_int_sel_cand.workunit_id:
            ou = self.env['operating.unit'].browse(self.new_int_sel_cand.workunit_id)
            if ou.exists():
                return ou

        target_name = self.get_target_work_unit_name()
        if target_name:
            ou = self.env['operating.unit'].search([
                '|', ('name', '=ilike', target_name.strip()),
                     ('district', '=ilike', target_name.strip())
            ], limit=1)
            if ou:
                return ou

        return self.env['operating.unit']

    def get_signatory_config(self):
        """Resolves the active signatory configuration for this promotion."""
        self.ensure_one()
        if self.signatory_config_id:
            return self.signatory_config_id

        target_ou = self.get_target_operating_unit()
        target_name = target_ou or self.get_target_work_unit_name()
        return self.env['recruitment.signatory.config'].get_signatory_for_unit(
            work_unit=target_name,
            doc_type='promotion_letter'
        )

    def get_signatory_name(self):
        self.ensure_one()
        sig = self.get_signatory_config()
        return sig.signatory_name if sig and sig.signatory_name else ""

    def get_signatory_title(self):
        self.ensure_one()
        sig = self.get_signatory_config()
        return sig.signatory_title if sig and sig.signatory_title else "People Operation Management Directorate"

    def get_signatory_company(self):
        self.ensure_one()
        sig = self.get_signatory_config()
        return sig.signatory_company if sig and sig.signatory_company else "Bunna Bank S.C."

    def get_signature_stamp_base64(self):
        self.ensure_one()
        sig = self.get_signatory_config()
        if sig:
            return sig.get_signature_stamp_base64()
        return ""

    def action_print_promotion_letter(self):
        self.ensure_one()
        if not self.signatory_config_id:
            self.signatory_config_id = self.get_signatory_config()
        if not self.promotion_ref_no:
            seq_val = self.env['ir.sequence'].next_by_code('bunna.internal.promotion.letter')
            self.promotion_ref_no = seq_val or ('BB/TAOD/%04d/%s' % (self.id, fields.Date.today().year))
        if not self.promotion_date:
            self.promotion_date = fields.Date.context_today(self)
        if not self.promoted_salary or self.promoted_salary <= 0:
            self.promoted_salary = self.get_promoted_salary_figure()
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

    @api.depends('current_work_unit', 'preferred_location', 'new_int_sel_cand.job_location', 'emp_name')
    def _compute_promotion_type(self):
        for rec in self:
            cand_unit = (rec.current_work_unit or '').strip().lower()
            vacancy_unit = (rec.new_int_sel_cand.job_location or '').strip().lower() if rec.new_int_sel_cand else ''
            pref_unit = (rec.preferred_location or '').strip().lower()

            target_unit = pref_unit or vacancy_unit
            if not cand_unit or not target_unit or cand_unit == target_unit:
                rec.promotion_type = 'same_unit'
            else:
                rec.promotion_type = 'diff_unit'

    @api.depends('emp_name')
    def _compute_coach_id(self):
        for rec in self:
            if rec.emp_name:
                rec.coach_id = rec.emp_name.coach_id or rec.emp_name.parent_id or False
            else:
                rec.coach_id = False

    def action_open_release_wizard(self):
        self.ensure_one()
        emp = self.emp_name
        parent_rec = self.new_int_sel_cand

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
        """Pre-fill PMS score from contract when employee is selected.
        HR can freely override the value afterward."""
        for record in self:
            if record.emp_name:
                contract_pms = record.emp_name.contract_id.pms_score if record.emp_name.contract_id else 0.0
                # Only pre-fill if score hasn't been set yet (don't overwrite manual edits)
                if not record.pms_score:
                    record.pms_score = contract_pms or 0.0
class InternalRecruitmentPanel(models.Model):
    _name = "new.internal.recruitment.panel"
    _description = "New Internal Recruitment Panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

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

    @api.depends('new_int_panel', 'new_int_panel.vacancy_id', 'new_int_panel.workunit_id')
    def _compute_eligible_employee_ids(self):
        for rec in self:
            sel = rec.new_int_panel
            vac = False
            if sel:
                vac_id = getattr(sel, 'vacancy_id', False)
                if isinstance(vac_id, int) and vac_id > 0:
                    vac = self.env['job.vacancy'].browse(vac_id)
                elif hasattr(vac_id, 'operating_unit_id') and vac_id:
                    vac = vac_id
                if not vac and getattr(sel, 'vacancy_reference', False):
                    vac = self.env['job.vacancy'].search([('reference', '=', sel.vacancy_reference)], limit=1)

            hiring_ou = False
            if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
                hiring_ou = vac.operating_unit_id.id
            elif sel and getattr(sel, 'workunit_id', False):
                w_id = sel.workunit_id
                hiring_ou = w_id.id if hasattr(w_id, 'id') else w_id
            elif sel and getattr(sel, 'job_location', False):
                ou = self.env['operating.unit'].search([('name', '=ilike', str(sel.job_location).strip())], limit=1)
                if ou:
                    hiring_ou = ou.id

            elif self.env.context.get('parent_operating_unit_id'):
                p_ou = self.env.context.get('parent_operating_unit_id')
                hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)
            elif self.env.context.get('parent_workunit_id'):
                p_wu = self.env.context.get('parent_workunit_id')
                hiring_ou = p_wu if isinstance(p_wu, int) else (p_wu.id if hasattr(p_wu, 'id') else False)

            if hiring_ou:
                rec.eligible_employee_ids = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', hiring_ou),
                    ('active', '=', True)
                ])
            else:
                rec.eligible_employee_ids = self.env['hr.employee'].search([('active', '=', True)])

    @api.onchange('new_int_panel', 'selection_criteria')
    def _onchange_new_int_panel_domain(self):
        """Filter panel members strictly to the Hiring Work Unit."""
        sel = self.new_int_panel
        vac = False
        if sel:
            vac_id = getattr(sel, 'vacancy_id', False)
            if isinstance(vac_id, int) and vac_id > 0:
                vac = self.env['job.vacancy'].browse(vac_id)
            elif hasattr(vac_id, 'operating_unit_id') and vac_id:
                vac = vac_id
            if not vac and getattr(sel, 'vacancy_reference', False):
                vac = self.env['job.vacancy'].search([('reference', '=', sel.vacancy_reference)], limit=1)

        hiring_ou = False
        if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
            hiring_ou = vac.operating_unit_id.id
        elif sel and getattr(sel, 'workunit_id', False):
            w_id = sel.workunit_id
            hiring_ou = w_id.id if hasattr(w_id, 'id') else w_id
        elif sel and getattr(sel, 'job_location', False):
            ou = self.env['operating.unit'].search([('name', '=ilike', str(sel.job_location).strip())], limit=1)
            if ou:
                hiring_ou = ou.id
        elif self.env.context.get('parent_operating_unit_id'):
            p_ou = self.env.context.get('parent_operating_unit_id')
            hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)
        elif self.env.context.get('parent_workunit_id'):
            p_wu = self.env.context.get('parent_workunit_id')
            hiring_ou = p_wu if isinstance(p_wu, int) else (p_wu.id if hasattr(p_wu, 'id') else False)

        if hiring_ou:
            domain = [('default_operating_unit_id', '=', hiring_ou), ('active', '=', True)]
            self.eligible_employee_ids = self.env['hr.employee'].search(domain)
            if self.emp_name and self.emp_name.id not in self.eligible_employee_ids.ids:
                self.emp_name = False
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





