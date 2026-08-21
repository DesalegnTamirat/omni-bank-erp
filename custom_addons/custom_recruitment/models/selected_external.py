from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class ExternalRecruitmentSelected(models.Model):
    _name = "external.recruitment.selected"
    _description = "External Recruitment Selected"
    _inherit = "mail.thread"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)

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
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    vacancy_reference = fields.Char(string="Vacancy Reference")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    written_exam_date = fields.Datetime(string="Written Exam Date")
    exam_location = fields.Text(string="Exam Location")
    interview_accepted_count = fields.Float(string="Interview Accepted Count")
    interview_date = fields.Datetime(string="Interview Date")
    interview_location = fields.Text(string="Interview Location")
    exam_scheduled = fields.Selection([('Yes', 'Yes'),
                                       ('No', 'No')], string="Exam Scheduled", default='No')
    interview_scheduled = fields.Selection([('Yes', 'Yes'),
                                            ('No', 'No')], string="Interview Scheduled", default='No')
    relevant_experience = fields.Integer(string="Relevant Experience")
    highest_cgpa = fields.Integer(string="Highest CGPA")
    vacancy_id = fields.Integer(string="Vacancy ID")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")

    has_delegation_requests = fields.Boolean(
        compute='_compute_has_delegation_requests',
        string="Has Delegation Requests"
    )

    @api.depends('ext_rec_panel.delegation_state', 'ext_rec_panel.response_status')
    def _compute_has_delegation_requests(self):
        for rec in self:
            rec.has_delegation_requests = any(
                (line.delegation_state and line.delegation_state != 'draft') or line.response_status == 'delegation_requested'
                for line in rec.ext_rec_panel
            )

    show_reschedule_button = fields.Boolean(
        compute='_compute_show_reschedule_button',
        string="Show Reschedule Button"
    )

    @api.depends('panel_notified', 'ext_rec_panel.response_status')
    def _compute_show_reschedule_button(self):
        for rec in self:
            if not rec.panel_notified or not rec.ext_rec_panel:
                rec.show_reschedule_button = False
            else:
                rec.show_reschedule_button = any(
                    line.response_status in ['unavailable', 'reschedule_requested']
                    for line in rec.ext_rec_panel
                )
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('draft', 'Draft'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status", default='draft')
    state = fields.Selection([('draft', 'Draft'), ("notify_approver", "Notify Approvers"), ("evaluate", "Evaluate"), ("approved", "Approved")], string="State", default='draft')

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'external_recruitment_selected') THEN
                    UPDATE external_recruitment_selected 
                    SET state = 'notify_approver',
                        status = 'notify'
                    WHERE state IS NULL OR state IN ('', 'draft')
                       OR status IS NULL OR status IN ('', 'draft');
                END IF;

                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'external_recruitment_selected_candidates') THEN
                    UPDATE external_recruitment_selected_candidates 
                    SET selection_type = COALESCE(NULLIF(selection_type, ''), 'selected')
                    WHERE selection_type IS NULL OR selection_type = '';
                END IF;
            END $$;
        """)
        return res
    panel_notified = fields.Boolean(string="Panel Notified", default=False)
    exam_scores_fetched = fields.Boolean(string="Exam Scores Fetched", default=False)
    interview_scores_fetched = fields.Boolean(string="Interview Scores Fetched", default=False)
    scores_computed = fields.Boolean(string="Scores Computed", default=False)
    selection_notified = fields.Boolean(string="Selection Notified", default=False)
    written_exam_weight = fields.Float(
        string="Written Exam Weight (%)",
        default=50.0,
        help="Weight percentage for Written Exam score calculation (default: 50.0%)."
    )
    interview_weight = fields.Float(
        string="Interview Weight (%)",
        default=50.0,
        help="Weight percentage for Interview score calculation (default: 50.0%)."
    )

    @api.onchange("written_exam_weight")
    def _onchange_written_exam_weight(self):
        if self.written_exam_weight is not False and 0 <= self.written_exam_weight <= 100:
            self.interview_weight = round(100.0 - self.written_exam_weight, 2)

    @api.onchange("interview_weight")
    def _onchange_interview_weight(self):
        if self.interview_weight is not False and 0 <= self.interview_weight <= 100:
            self.written_exam_weight = round(100.0 - self.interview_weight, 2)

    @api.onchange("job_category", "job_position")
    def _onchange_set_brd_default_weights(self):
        """
        BRD Matrix Default Auto-Population for External:
        - Managerial & Junior: 50% Written Exam + 50% Interview
        - Non-Managerial: 60% Written Exam + 40% Interview
        """
        cat_str = (self.job_category or "").lower()
        if "non" in cat_str or "non-managerial" in cat_str:
            self.written_exam_weight = 60.0
            self.interview_weight = 40.0
        else:
            self.written_exam_weight = 50.0
            self.interview_weight = 50.0

    total_candidates_count = fields.Integer(string="Total Applicants", compute="_compute_candidate_counts")
    selected_candidates_count = fields.Integer(string="Selected", compute="_compute_candidate_counts")
    reserve_candidates_count = fields.Integer(string="Reserve Pool", compute="_compute_candidate_counts")
    disqualified_candidates_count = fields.Integer(string="Disqualified", compute="_compute_candidate_counts")

    @api.depends("ext_rec_sel", "ext_rec_sel.selection_type")
    def _compute_candidate_counts(self):
        for rec in self:
            cands = rec.ext_rec_sel
            rec.total_candidates_count = len(cands)
            rec.selected_candidates_count = len(cands.filtered(lambda c: c.selection_type == 'selected'))
            rec.reserve_candidates_count = len(cands.filtered(lambda c: c.selection_type == 'reserved'))
            rec.disqualified_candidates_count = len(cands.filtered(lambda c: c.selection_type == 'rejected'))

    ext_rec_sel = fields.One2many("external.recruitment.selected.candidates", "ext_rec_sel_cand",
                                      string="Selected candidates for External Recruitment")
    ext_rec_panel = fields.One2many("external.recruitment.panel", "ext_panel",
                                        string="Selected Panel for Recruitment")
    recr_exter_selected_team_id = fields.One2many("external.recrt.delegation.team", "exter_rec_del_id", string="External Recruitment Selected Delegation Team")

    def notify_approver(self):
        if not self.scores_computed:
            raise UserError(_("Sequence Error: You must compute & rank candidate scores ('Compute & Rank Scores') before notifying approvers."))
        p_id = self.id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT job_vacancy_minute_external(%s)', (p_id,))
        except Exception as e:
            _logger.warning("Stored procedure job_vacancy_minute_external failed: %s", e)

        # Pure python fallback to sync result summary rank if stored procedure fails
        vac = self.env["job.vacancy"].search([("reference", "=", self.vacancy_reference)], limit=1)
        if vac and self.ext_rec_sel:
            try:
                vac.hiring_rank_details.unlink()
                rank_lines = []
                sorted_cands = sorted(self.ext_rec_sel, key=lambda c: c.weighted_score or 0.0, reverse=True)
                for idx, cand in enumerate(sorted_cands, start=1):
                    name_str = cand.applicant_name.partner_name if (cand.applicant_name and getattr(cand.applicant_name, 'partner_name', False)) else (cand.applicant_name.name if cand.applicant_name else 'Applicant')
                    rank_lines.append((0, 0, {
                        'no': idx,
                        'rank': idx,
                        'applicant_name': name_str,
                        'result': str(cand.weighted_score or 0.0),
                        'statues': cand.selection_type or 'Pending',
                    }))
                if rank_lines:
                    vac.write({'hiring_rank_details': rank_lines})
            except Exception as ex:
                _logger.warning("Python fallback rank generation warning: %s", ex)

        for com in self.recr_exter_selected_team_id:
            usr = False
            if com.employee_name:
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)], limit=1)
            elif com.alternate_committee_member:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)], limit=1)
            if usr:
                self.mail_channel_msgs(usr.id, self.vacancy_reference or '', self.job_position.name if self.job_position else '')
        self.state = "notify_approver"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approver Notified'),
                'message': _('Committee members have been notified for vacancy selection approval.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear Committee<br>Candidates have been shortlisted for the position: <b>%s</b> (Ref: <b>%s</b>).<br><br>Kindly approve.") % (arg1, ref)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def evaluate(self):
        if self.state not in ('notify_approver', 'evaluate', 'approved'):
            raise UserError(_("Sequence Error: You must notify approvers ('Notify Approver') before approving the selection."))
        n = 0
        usr_name = self.env.user.name
        for val in self.recr_exter_selected_team_id:
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
        if n == 0 and self.recr_exter_selected_team_id:
            # Auto-approve for administrator override if user not explicitly on delegation list
            if self.env.user.has_group('hr.group_hr_manager'):
                for val in self.recr_exter_selected_team_id:
                    val.approve = True
            else:
                raise ValidationError(_("Sorry!! You are not assigned as an evaluator for this selection."))
        
        self.state = "evaluate"
        self.status = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved'),
                'message': _('Selection process has been successfully approved!'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def send_mail(self, email, subject_column, comments):
        if not email:
            return
        try:
            mail_values = {
                'subject': subject_column,
                'body_html': f"<p>{comments.replace('\n', '<br>')}</p>",
                'email_to': email,
            }
            self.env['mail.mail'].sudo().create(mail_values).send()
        except Exception:
            pass

    def _get_applicant_display_name(self, app):
        if not app or not app.applicant_name:
            return 'Candidate'
        applicant = app.applicant_name
        return getattr(applicant, 'partner_name', False) or getattr(applicant, 'display_name', False) or 'Candidate'

    def notify_written_exam(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date before notifying candidates.'))
        for app in self.ext_rec_sel:
            if app.select_flag and app.applicant_email:
                message = _("Greetings %s,\n\nJob Position: %s\nWe invite you for the Written Exam on %s at %s.\n\nBest Regards,\nBunna Bank S.C.") % (
                    self._get_applicant_display_name(app),
                    self.job_position.name if self.job_position else '',
                    str(self.written_exam_date),
                    self.exam_location or 'Main Branch'
                )
                subject = _("Written Exam Notification - %s") % (self.job_position.name if self.job_position else '')
                self.send_mail(app.applicant_email, subject, message)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_exam_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_exam_evaluation_sheet failed: %s", e)
        self.exam_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Notification Sent'),
                'message': _('Written Exam notifications sent to candidates.'),
                'type': 'success',
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

        for cand in self.ext_rec_sel:
            if not cand.applicant_name:
                continue

            app = cand.applicant_name
            # Domain to match written exam attempt in assessment system
            domain = [('applicant_id', '=', app.id)]
            if vac_id:
                domain.append('|')
                domain.append(('session_id.vacancy_id', '=', vac_id))
                domain.append(('session_id.vacancy_id.reference', '=', vac_ref or ''))
            elif job_id:
                domain.append(('session_id.job_id', '=', job_id))

            attempt = attempt_model.search(domain, order='id desc', limit=1)
            if not attempt and job_id:
                attempt = attempt_model.search([('applicant_id', '=', app.id), ('session_id.job_id', '=', job_id)], order='id desc', limit=1)
            if not attempt:
                attempt = attempt_model.search([('applicant_id', '=', app.id)], order='id desc', limit=1)

            if attempt:
                cand.written_exam_score = attempt.score_percentage
                fetched_count += 1

        # 2. Legacy SQL procedure fallback (only if function exists in Postgres DB)
        try:
            self.env.cr.execute("SELECT 1 FROM pg_proc WHERE proname = 'applicant_exam_score'")
            if self.env.cr.fetchone():
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT applicant_exam_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_exam_score error: %s", e)

        # 3. Evaluate 50% written exam threshold for candidate selection
        for cand in self.ext_rec_sel:
            score = cand.written_exam_score or 0.0
            if score < 50.0:
                cand.select_flag = False
                cand.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score

        self.exam_scores_fetched = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Written Exam scores fetched successfully for %d candidate(s) from Written Assessment Module.') % fetched_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_interview_panel(self):
        if not self.exam_scores_fetched:
            raise UserError(_("Sequence Error: You must fetch written exam scores ('Fetch Exam Score') before notifying the interview panel."))
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date before notifying the panel.'))
        pos_title = self._get_position_title()
        for val in self.ext_rec_panel:
            if val.emp_name:
                val.write({'response_status': 'pending'})
                usr = val.emp_name.user_id.partner_id if (val.emp_name and val.emp_name.user_id) else False
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, pos_title, str(self.interview_date), self.interview_location or 'Head Office')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT notify_panel_external_interview(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure notify_panel_external_interview failed: %s", e)
        self.panel_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Notified'),
                'message': _('Interview Panel Members have been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs_panel(self, rec_id, emp, position, date, loc):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        pos_title = position or self._get_position_title()
        message = Markup(_("Dear %s,<br/>You are selected as an Interview Panel Member for position <b>%s</b>.<br/>Date: %s<br/>Location: %s")) % (emp, pos_title, str(date) if date else _("TBD"), loc or _("Head Office"))
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def action_open_reschedule_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule Interview & Reassign Panel'),
            'res_model': 'reschedule.interview.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_external_selected_id': self.id,
                'default_new_interview_date': self.interview_date or fields.Date.today(),
                'default_new_interview_location': self.interview_location or '',
            }
        }

    def notify_interview(self):
        if not self.exam_scores_fetched:
            raise UserError(_("Sequence Error: You must fetch written exam scores ('Fetch Exam Score') before sending interview invitations to candidates."))
        if not self.panel_notified:
            raise UserError(_("Sequence Error: You must notify the Interview Panel ('Notify Interview Panel') before sending interview invitations to candidates."))
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date before notifying candidates.'))
        for app in self.ext_rec_sel:
            score = app.written_exam_score or 0.0
            if score < 50.0:
                app.select_flag = False
                app.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score
            else:
                if app.select_flag and app.applicant_email:
                    message = _("Greetings %s,\n\nJob Position: %s\nYou are invited for an Interview on %s at %s.\n\nBest Regards,\nBunna Bank S.C.") % (
                        self._get_applicant_display_name(app),
                        self.job_position.name if self.job_position else '',
                        str(self.interview_date),
                        self.interview_location or 'Head Office'
                    )
                    subject = _("Call for Interview - %s") % (self.job_position.name if self.job_position else '')
                    self.send_mail(app.applicant_email, subject, message)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_interview_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_interview_evaluation_sheet failed: %s", e)
        self.interview_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Notifications Sent'),
                'message': _('Interview invitations dispatched to candidates.'),
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

            exam_w = (rec.written_exam_weight if rec.written_exam_weight is not False else 50.0) / 100.0
            intv_w = (rec.interview_weight if rec.interview_weight is not False else 50.0) / 100.0

            for cand in rec.ext_rec_sel:
                app_rec = cand.applicant_name if hasattr(cand, 'applicant_name') and cand.applicant_name else False
                emp_rec = cand.emp_name if hasattr(cand, 'emp_name') and cand.emp_name else False

                app_id_int = app_rec.id if app_rec and hasattr(app_rec, 'id') and not isinstance(app_rec, int) else (app_rec if isinstance(app_rec, int) else False)
                emp_id_int = emp_rec.id if emp_rec and hasattr(emp_rec, 'id') and not isinstance(emp_rec, int) else (emp_rec if isinstance(emp_rec, int) else False)

                names_to_check = []
                if emp_rec:
                    names_to_check.append(emp_rec.name.strip() if hasattr(emp_rec, 'name') and emp_rec.name else str(emp_rec).strip())
                if hasattr(cand, 'display_name') and cand.display_name:
                    names_to_check.append(str(cand.display_name).strip())
                if app_rec:
                    p_name = getattr(app_rec, 'partner_name', False)
                    a_name = getattr(app_rec, 'name', False)
                    if p_name:
                        names_to_check.append(str(p_name).strip())
                    if a_name:
                        names_to_check.append(str(a_name).strip())

                cbis_res = False

                # 1. Search by applicant_id
                if app_id_int:
                    cbis_res = CBISCand.search([('applicant_id', '=', app_id_int)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 2. Search by employee_id
                if not cbis_res and emp_id_int:
                    cbis_res = CBISCand.search([('employee_id', '=', emp_id_int)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)

                # 3. Search by Name (exact =ilike, partial ilike, keyword)
                if not cbis_res:
                    for name in names_to_check:
                        if not name:
                            continue
                        clean_n = name.split('(')[0].strip()
                        cbis_res = CBISCand.search([('candidate_name', '=ilike', clean_n)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)
                        if not cbis_res:
                            cbis_res = CBISCand.search([('candidate_name', 'ilike', clean_n)], order='average_interview_score desc, submitted_eval_count desc, id desc', limit=1)
                        if cbis_res:
                            break

                fetched_score = 0.0
                if cbis_res:
                    fetched_score = cbis_res.average_interview_score or 0.0
                else:
                    final_res = False
                    if app_id_int:
                        final_res = FinalResult.search([('applicant_id', '=', app_id_int)], order='id desc', limit=1)
                    if not final_res and emp_id_int:
                        final_res = FinalResult.search([('employee_id', '=', emp_id_int)], order='id desc', limit=1)
                    if not final_res:
                        for name in names_to_check:
                            if name:
                                clean_n = name.split('(')[0].strip()
                                final_res = FinalResult.search([('candidate_name', '=ilike', clean_n)], order='id desc', limit=1)
                                if not final_res:
                                    final_res = FinalResult.search([('candidate_name', 'ilike', clean_n)], order='id desc', limit=1)
                                if final_res:
                                    break

                    if final_res:
                        fetched_score = getattr(final_res, 'final_score', 0.0) or getattr(final_res, 'average_score', 0.0) or getattr(final_res, 'interview_score', 0.0) or 0.0
                    else:
                        score_rec = False
                        if app_id_int:
                            score_rec = CandScore.search([('applicant_id', '=', app_id_int)], order='id desc', limit=1)
                        if not score_rec:
                            for name in names_to_check:
                                if name:
                                    clean_n = name.split('(')[0].strip()
                                    score_rec = CandScore.search([('candidate_name', '=ilike', clean_n)], order='id desc', limit=1)
                                    if score_rec:
                                        break
                        if score_rec:
                            fetched_score = getattr(score_rec, 'interview_score', 0.0) or 0.0

                exam_val = cand.written_exam_score or 0.0
                intv_val = fetched_score
                weighted = round((exam_val * exam_w) + (intv_val * intv_w), 2)

                cand.write({
                    'interview_score': fetched_score,
                    'weighted_score': weighted
                })

            rec.interview_scores_fetched = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Interview scores fetched successfully from panel final results. Proceed to Compute & Rank Scores.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _get_external_weights(self):
        """
        Fetches Written Exam and Interview weight percentages directly from the 
        Assessment module Weight Profiles (assessment.weight.profile).
        """
        self.ensure_one()
        exam_w, int_w = (60.0, 40.0)

        if "assessment.weight.profile" in self.env:
            role_lvl = "non_managerial"
            vac = self.env["job.vacancy"].browse(self.vacancy_id) if self.vacancy_id else False
            if vac and getattr(vac, "interview_type", False):
                role_lvl = vac.interview_type

            profile = self.env["assessment.weight.profile"].sudo().get_profile_for_candidate("external", role_lvl)
            if profile and profile.line_ids:
                exam_w, int_w = 0.0, 0.0
                for line in profile.line_ids:
                    if line.component == "exam":
                        exam_w = line.weight_percentage
                    elif line.component == "interview":
                        int_w = line.weight_percentage

        return (exam_w, int_w)

    def compute_weighted_score(self):
        """
        Enterprise Candidate Scoring & Auto-Selection Engine:
        1. Calculates weighted score using Assessment Weight Profile (written_exam_score * exam_weight) + (interview_score * interview_weight)
        2. Applies 50% Disqualification Gate (Exam < 50% or Interview < 50% or Weighted < 50%)
        3. Ranks non-disqualified candidates with tie-breaking (Female priority & Exam score)
        4. Auto-selects Top N candidates matching Number of Vacancies (no_of_vacancies)
        5. Assigns remaining qualified candidates to Reserve Pool ('reserved')
        """
        for rec in self:
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT applicant_weighted_score(%s)', (rec.id,))
            except Exception as e:
                _logger.warning("Stored procedure applicant_weighted_score failed: %s", e)
            slots = rec.no_of_vacancies or 1
            eligible_candidates = []
            
            exam_w, int_w = rec._get_external_weights()
            exam_weight_pct = exam_w / 100.0
            interview_weight_pct = int_w / 100.0

            for app in rec.ext_rec_sel:
                exam = app.written_exam_score or 0.0
                interview = app.interview_score or 0.0
                app.weighted_score = round((exam * exam_weight_pct) + (interview * interview_weight_pct), 2)
                
                # 50% Disqualification Gate (FR-REC rules)
                disqualified = False
                reasons = []
                if exam < 50.0:
                    disqualified = True
                    reasons.append(_("Written Exam score %.1f%% < 50%%") % exam)
                if interview < 50.0:
                    disqualified = True
                    reasons.append(_("Interview score %.1f%% < 50%%") % interview)
                if app.weighted_score < 50.0:
                    disqualified = True
                    reasons.append(_("Final Weighted score %.1f%% < 50%%") % app.weighted_score)

                if disqualified:
                    app.selection_type = 'rejected'
                    app.remarks = _("Disqualified: %s") % ("; ".join(reasons))
                else:
                    eligible_candidates.append(app)

            # Rank eligible candidates with tie-breaking
            def sort_key(c):
                gender_str = (getattr(c.applicant_name, 'gender', '') or '').lower()
                gender_priority = 0 if gender_str == 'female' else 1
                return (-c.weighted_score, gender_priority, -(c.written_exam_score or 0.0))

            sorted_candidates = sorted(eligible_candidates, key=sort_key)

            # Auto-select top N based on vacancy slots
            top_selected = sorted_candidates[:slots]
            reserve_pool = sorted_candidates[slots:]

            for idx, cand in enumerate(top_selected, start=1):
                cand.selection_type = 'selected'
                cand.remarks = _("Selected (Rank %d)") % idx

            for idx, cand in enumerate(reserve_pool, start=slots + 1):
                cand.selection_type = 'reserved'
                cand.remarks = _("Reserve Pool (Rank %d)") % idx

            rec.scores_computed = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Weighted Scores & Selection Computed'),
                'message': _('Candidate scores computed: Top candidates selected, overflow reserved, and disqualifications applied.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_generate_minute(self):
        """
        Generates printable External Selection Committee Minute report containing
        ONLY candidates who are finally Selected (excluding Reserved & Disqualified).
        """
        self.ensure_one()
        return self.env.ref('custom_recruitment.action_report_internal_recruitment_minute').report_action(self)

    def action_open_digital_minute(self):
        """
        Opens or creates the digital committee selection minute record
        for external recruitment selection process.
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

        if self.ext_rec_panel:
            for panel in self.ext_rec_panel:
                emp = panel.delegate_employee_id if (getattr(panel, 'delegation_state', False) == 'approved' and getattr(panel, 'delegate_employee_id', False)) else panel.emp_name
                user = emp.user_id if (emp and getattr(emp, 'user_id', False)) else False
                if not user and emp:
                    user = self.env['res.users'].search([('employee_id', '=', emp.id)], limit=1)
                if user and user.id not in added_uids:
                    added_uids.add(user.id)
                    signature_vals.append((0, 0, {
                        'user_id': user.id,
                        'role': getattr(panel, 'selection_criteria', 'Panel Member') or 'Panel Member',
                        'state': 'pending',
                    }))

        if self.recr_exter_selected_team_id:
            for member in self.recr_exter_selected_team_id:
                user = member.employee_name or member.alternate_committee_member
                if user and user.id not in added_uids:
                    added_uids.add(user.id)
                    role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                    signature_vals.append((0, 0, {
                        'user_id': user.id,
                        'role': role_label,
                        'state': 'pending',
                    }))

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
        for cand in self.ext_rec_sel:
            cand_name = cand.applicant_name.partner_name if (cand.applicant_name and getattr(cand.applicant_name, 'partner_name', False)) else (cand.applicant_name.name if cand.applicant_name else cand.emp_name or 'Applicant')
            status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else ('reserve' if cand.selection_type in ('reserved', 'Reserve') else 'failed')
            line_vals.append((0, 0, {
                'applicant_id': cand.applicant_name.id if cand.applicant_name else False,
                'candidate_name': cand_name,
                'written_score': cand.written_exam_score or 0.0,
                'interview_score': cand.interview_score or 0.0,
                'final_score': cand.weighted_score or 0.0,
                'rank': getattr(cand, 'rank', 0) or 0,
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
                "External Recruitment Selection Minute for position '%s'.\n"
                "Total Applicants: %s | Vacancy Slots: %s"
            ) % (pos_name, len(self.ext_rec_sel), self.no_of_vacancies or 1)

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

    def notify_selection(self):
        if self.state not in ('evaluate', 'approved') and self.status not in ('evaluate', 'approved'):
            raise UserError(_("Sequence Error: Selection process must be approved ('Approve Selection') before sending final selection notifications to candidates."))

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT applicant_update_status(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_update_status failed: %s", e)
        for app in self.ext_rec_sel:
            if app.selection_type in ['selected', 'Selected'] and app.applicant_email:
                message = _("Congratulations %s!\n\nYou have been selected for the position of %s at Bunna Bank S.C.\nOur HR department will contact you shortly.\n\nBest Regards,\nBunna Bank S.C.") % (
                    self._get_applicant_display_name(app),
                    self.job_position.name if self.job_position else ''
                )
                subject = _("Congratulations! Selection Notification - %s") % (self.job_position.name if self.job_position else '')
                self.send_mail(app.applicant_email, subject, message)
        self.selection_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Selection Notified'),
                'message': _('Selection results dispatched to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_rejection(self):
        for app in self.ext_rec_sel:
            if app.selection_type == "Rejected":
                e_mail = app.applicant_email
                message = (
                    "Greetings!! \n Miss/Mr/Mrs. %(name)s\nJob Reference: %(job)s\n"
                    "We are sorry to inform you that you are not selected for the job position.\n"
                    "We hope you will do better next time.\nAll the Best!!"
                ) % {'name': app.applicant_name.name, 'job': self.job_position.name}
                subject = "Rejection notification Reg. " + str(self.job_position.name)
                try:
                    self.send_mail(e_mail, subject, message)
                except Exception:
                    pass


class ExternalRecruitmentSelectedCandidates(models.Model):
    _name = "external.recruitment.selected.candidates"
    _description = "Eligible Applicants"
    _rec_name = "display_name"

    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    applicant_email = fields.Char(string="Email")
    emp_name = fields.Char(string="emp name")
    display_name = fields.Char(string="Display Name", compute="_compute_display_name", store=True)
    active = fields.Boolean(default=True)

    @api.depends('applicant_name', 'emp_name')
    def _compute_display_name(self):
        for rec in self:
            if rec.applicant_name and rec.applicant_name.partner_name:
                rec.display_name = rec.applicant_name.partner_name
            elif rec.emp_name:
                rec.display_name = rec.emp_name
            else:
                rec.display_name = _("Candidate #%s") % rec.id

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    emp_grade = fields.Char(string="Grade")
    emp_position = fields.Char(string="Position")
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
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
    written_exam_score = fields.Float(string="Written Exam Score")
    interview_score = fields.Float(string="Interview Score")
    weighted_score = fields.Float(string="Weighted Score")
    exam_notified = fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([
        ('selected', 'Selected'),
        ('reserved', 'Reserved'),
        ('rejected', 'Rejected')
    ], string="Result", default='selected')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    ext_rec_sel_cand = fields.Many2one("external.recruitment.selected",
                                           string="Selected candidates for External Recruitment")


class InternalRecruitmentPanel(models.Model):
    _name = "external.recruitment.panel"
    _description = "External Recruitment Panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    emp_position = fields.Char(string="Position")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    selection_criteria = fields.Selection([('Exam', 'Exam'),
                                       ('Interview', 'Interview')], string="Assessment Type",default='Exam')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    accepted = fields.Boolean(string="Accepted", default=False)
    panel_status = fields.Char(string="panel_status")
    ext_panel = fields.Many2one("external.recruitment.selected", string="Select Panel for Recruitment")

    job_position_id = fields.Many2one('hr.job', string="Job Position", related='ext_panel.job_position', readonly=True)
    interview_date = fields.Datetime(string="Scheduled Date & Time", related='ext_panel.interview_date', readonly=True)
    interview_location = fields.Text(string="Interview Location", readonly=True)
    vacancy_reference = fields.Char(string="Vacancy Reference", related='ext_panel.vacancy_reference', readonly=True)

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
                'default_ext_panel_member_id': self.id,
                'default_external_selected_id': self.ext_panel.id if self.ext_panel else False,
            }
        }

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
            if rec.ext_panel:
                rec.ext_panel.message_post(body=_(
                    "HR approved interview panel delegation: <b>%s</b> replaced by <b>%s</b>."
                ) % (old_name, new_emp.name))

    def action_reject_delegation(self):
        for rec in self:
            rec.write({
                'delegation_state': 'rejected',
                'response_status': 'unavailable',
            })
            if rec.ext_panel:
                rec.ext_panel.message_post(body=_(
                    "HR rejected panel delegation request for <b>%s</b>."
                ) % (rec.emp_name.name if rec.emp_name else _("Panel Member")))



class ExternalRecruitmentSelectedDelegation(models.Model):
    _name = "external.recrt.delegation.team"
    _description = "External Recrt Delegation Team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
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
    exter_rec_del_id = fields.Many2one("external.recruitment.selected", string="External Recruitment Selected Delegation Team")
