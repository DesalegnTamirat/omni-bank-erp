from email.policy import default

from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
import logging

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
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('draft', 'Draft'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status", default='draft')
    state = fields.Selection([('draft', 'Draft'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="State", default='draft')

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'new_internal_recruitment_selected' AND column_name = 'state') THEN
                    EXECUTE 'UPDATE new_internal_recruitment_selected 
                             SET state = ''notify'',
                                 status = ''notify''
                             WHERE state IS NULL OR state IN ('''', ''draft'')
                                OR status IS NULL OR status IN ('''', ''draft'')';
                END IF;

                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'new_internal_recruitment_selected_candidates' AND column_name = 'promotion_status') THEN
                    EXECUTE 'UPDATE new_internal_recruitment_selected_candidates 
                             SET promotion_status = COALESCE(NULLIF(promotion_status, ''''), ''draft''),
                                 selection_type = COALESCE(NULLIF(selection_type, ''''), ''selected'')
                             WHERE promotion_status IS NULL OR promotion_status = ''''
                                OR selection_type IS NULL OR selection_type = ''''';
                END IF;
            END $$;
        """)
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
        message = Markup(_("Dear Committee,<br/>Candidates have been shortlisted for internal selection: <b>%s</b> (Ref: <b>%s</b>).<br/><br/>Kindly approve.")) % (pos_title, ref or '')
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

    def mail_channel_msgs_exam(self, rec_id, emp, position, date, location):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        message = Markup(_("Dear %s,<br/>You have been shortlisted for the Written Exam for position <b>%s</b>.<br/>Date: %s<br/>Location: %s<br/><br/>All The Best!")) % (emp, pos_title, str(date) if date else _("TBD"), location or _("Main Office"))
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def mail_channel_msgs_interview(self, rec_id, emp, position, date, location):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        message = Markup(_("Dear %s,<br/>You have been shortlisted for the Interview for position <b>%s</b>.<br/>Date: %s<br/>Location: %s<br/><br/>All The Best!")) % (emp, pos_title, str(date) if date else _("TBD"), location or _("Head Office"))
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_written_exam(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date before sending notifications.'))
        count = 0
        exam_date_str = str(self.written_exam_date)
        position_name = self.job_position.name if self.job_position else ''
        location_name = self.exam_location or 'Main Office'

        for val in self.new_int_rec_sel:
            if val.emp_name and (val.select_flag or val.select_flag is None):
                partner = self._get_partner_for_employee(val.emp_name)
                if partner:
                    _logger.info("[notify_written_exam] Sending written exam notification to %s (Partner ID=%s)", val.emp_name.name, partner.id)
                    self.mail_channel_msgs_exam(partner.id, val.emp_name.name, position_name, exam_date_str, location_name)
                    val.exam_notified = 'Yes'
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

    def notify_interview_panel(self):
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date before notifying the panel.'))
        pos_title = self._get_position_title()
        for val in self.new_int_rec_panel:
            if val.emp_name:
                val.write({'response_status': 'pending'})
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, pos_title, self.interview_date, self.interview_location or 'Head Office')
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

    def mail_channel_msgs_panel(self, rec_id, emp, position, date, loc):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        message = Markup(_("Dear %s,<br/>You are selected as an Interview Panel Member for position <b>%s</b>.<br/>Date: %s<br/>Location: %s")) % (emp, pos_title, str(date) if date else _("TBD"), loc or _("Head Office"))
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_exam_panel(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date.'))
        pos_title = self._get_position_title()
        for val in self.new_int_rec_panel:
            if val.emp_name:
                usr = self._get_partner_for_employee(val.emp_name)
                if usr:
                    self.mail_channel_msgs_exam_panel(usr.id, val.emp_name.name, pos_title, self.written_exam_date, self.exam_location or 'Main Office')
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

    def mail_channel_msgs_exam_panel(self, rec_id, emp, position, date, loc):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        message = Markup(_("Dear %s,<br/>You are selected as an Exam Panel Member for position <b>%s</b>.<br/>Date: %s<br/>Location: %s")) % (emp, pos_title, str(date) if date else _("TBD"), loc or _("Main Office"))
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

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
                if val.emp_name and (val.select_flag or val.select_flag is None):
                    usr = self._get_partner_for_employee(val.emp_name)
                    if usr:
                        self.mail_channel_msgs_interview(usr.id, val.emp_name.name, self.job_position.name if self.job_position else '', str(self.interview_date), self.interview_location or 'Head Office')
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
            is_vac_published = (rec.vacancy_id and rec.vacancy_id.vacancy_status == 'published')
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
                if cand.promotion_type == 'same_unit':
                    if cand.promotion_status not in ('promoted', 'released'):
                        emp = cand.emp_name
                        vals = {}
                        if rec.job_position:
                            if hasattr(emp, 'job_id'):
                                vals['job_id'] = rec.job_position.id
                            if hasattr(emp, 'job_position'):
                                vals['job_position'] = rec.job_position.id
                            if hasattr(emp, 'department_id') and rec.job_position.department_id:
                                vals['department_id'] = rec.job_position.department_id.id

                        if rec.job_grade:
                            if hasattr(emp, 'emp_grade'):
                                vals['emp_grade'] = rec.job_grade

                        if vals:
                            emp.write(vals)

                        # Update Many2one employee.grade & Char emp_grade
                        _update_employee_job_grade(emp, rec.job_grade or rec.job_grade_id)

                        cand.promotion_status = 'promoted'
                        same_unit_count += 1
                else:
                    if cand.promotion_status not in ('released', 'promoted'):
                        cand.promotion_status = 'pending_release'
                        diff_unit_count += 1

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
                        msg1 = _("We are pleased to inform you that you have been Selected for position ")
                        msg2 = _("<br>Please indicate your acceptance of promotion in the system.<br><br>Congratulations!")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
                    elif val.selection_type in ['reserve', 'reserved', 'Reserve', 'Reserved']:
                        msg1 = _("We are pleased to inform you that you have been placed in the Reserve Pool for position ")
                        msg2 = _("<br>Your status is valid for 6 months.")
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
        message = _("Dear %s,<br>%s%s%s") % (emp, msg1, position, msg2)
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
                    msg1 = _("Thank you for your interest in position ")
                    msg2 = _("<br>We regret to inform you that you were not selected for this position.<br>We wish you all the best in your career.")
                    self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
                    val.decision_notified = 'Rejected'

		
class NewInternalRecruitmentSelectedDelegation(models.Model):
    _name = "new.recrt.delegation.team"
    _description = "New Recrt Delegation Team"

    role = fields.Selection([
        ("chair_person", "Chair Person"),
        ("member", "Member"),
        ("secretary", "Secretary"),
        ("member_secretary", "Member & Secretary"),
        ("approver", "Approver"),
    ], string="Role", default="member")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
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
        ('selected', 'Selected'),
        ('reserve', 'Reserved'),
        ('rejected', 'Disqualified')
    ], string="Result", default='selected')
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
        return {
            'name': _('Candidate Release Form (Different Work Unit)'),
            'type': 'ir.actions.act_window',
            'res_model': 'new.internal.recruitment.release.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
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





