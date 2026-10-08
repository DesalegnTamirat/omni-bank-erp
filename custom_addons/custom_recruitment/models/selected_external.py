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
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice", default=12)
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion", default=12)
    minimum_pms_score = fields.Float(string="Minimum PMS Score", default=75.0)
    status = fields.Selection([('draft', 'Draft'), ('shortlist', 'Shortlisted'), ('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status", default='draft')
    state = fields.Selection([('draft', 'Draft'), ('shortlist', 'Shortlisted'), ("notify_approver", "Notify Approvers"), ("evaluate", "Evaluate"), ("approved", "Approved")], string="State", default='draft')
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
                    ALTER TABLE external_recruitment_selected 
                    ADD COLUMN IF NOT EXISTS approval_hierarchy_type VARCHAR,
                    ADD COLUMN IF NOT EXISTS chairperson_id INT4,
                    ADD COLUMN IF NOT EXISTS panel_member_id INT4,
                    ADD COLUMN IF NOT EXISTS secretary_id INT4,
                    ADD COLUMN IF NOT EXISTS observer_id INT4;

                    UPDATE external_recruitment_selected 
                    SET state = 'notify_approver',
                        status = 'notify'
                    WHERE state IS NULL OR state IN ('', 'draft')
                       OR status IS NULL OR status IN ('', 'draft');

                    UPDATE external_recruitment_selected_candidates 
                    SET selection_type = 'shortlisted'
                    WHERE selection_type IS NULL OR selection_type = ''
                       OR (selection_type = 'selected' AND (weighted_score IS NULL OR weighted_score = 0) AND (interview_score IS NULL OR interview_score = 0) AND (written_exam_score IS NULL OR written_exam_score = 0));
                """)
        except Exception as e:
            _logger.warning("Safe update on external_recruitment_selected: %s", e)
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

    def notify_approver(self):
        if not self.scores_computed:
            raise UserError(_("Sequence Error: You must compute & rank candidate scores ('Compute & Rank Scores') before notifying approvers."))
        selected_cands = self.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        if not selected_cands:
            raise UserError(_("No candidates have passed both the written examination and interview assessments (minimum 50% required in each stage). Cannot proceed to notify the approval committee."))
        if not self.recr_exter_selected_team_id or not self.recr_exter_selected_team_id.filtered(lambda t: t.employee_name or t.alternate_committee_member):
            raise UserError(_("Please add committee members in the Committee / Delegation Team tab before notifying approvers."))
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
        message = (
            f"Dear Committee,\n\n"
            f"Candidates have been shortlisted for external selection:\n\n"
            f"• Position: {arg1}\n"
            f"• Reference: {ref}\n\n"
            f"Kindly review and approve."
        )
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def evaluate(self):
        if self.state not in ('notify_approver', 'evaluate', 'approved'):
            raise UserError(_("Sequence Error: You must notify approvers ('Notify Approver') before approving the selection."))
        selected_cands = self.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        if not selected_cands:
            raise UserError(_("Cannot approve selection because no candidates passed the examination and interview assessments."))
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
    def _format_date_time_parts(self, dt):
        if not dt:
            return ('TBD', 'TBD')
        try:
            if isinstance(dt, str):
                dt = fields.Datetime.to_datetime(dt)
            return (dt.strftime('%b %d, %Y'), dt.strftime('%I:%M %p'))
        except Exception:
            return (str(dt), '')

    def notify_written_exam(self):
        if not self.ext_rec_sel:
            raise UserError(_("No candidates found in the shortlisted selection list. Please shortlist candidates first."))
        registered_cands = self.ext_rec_sel.filtered(lambda c: c.applicant_name and c.select_flag and c.selection_type != 'rejected')
        if not registered_cands:
            raise UserError(_("No registered/eligible candidates found to notify for the written exam. Please shortlist active candidates first."))
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)

        # Pull exam schedule from linked vacancy if missing on this record
        if not self.written_exam_date and vac and vac.exists():
            if getattr(vac, 'written_exam_date', False):
                self.written_exam_date = vac.written_exam_date
            elif vac.selected_recruitment_id and vac.selected_recruitment_id.written_exam_date:
                self.written_exam_date = vac.selected_recruitment_id.written_exam_date
            if getattr(vac, 'exam_location', False) and not self.exam_location:
                self.exam_location = vac.exam_location
            elif vac.selected_recruitment_id and vac.selected_recruitment_id.exam_location and not self.exam_location:
                self.exam_location = vac.selected_recruitment_id.exam_location

        if not self.written_exam_date or not self.exam_location:
            raise UserError(_('Please specify both the Written Exam Date and Exam Location before notifying candidates.'))

        # Sync exam schedule to vacancy record
        if vac and vac.exists():
            vac.sudo().write({
                'written_exam_date': self.written_exam_date,
                'exam_location': self.exam_location or 'Head Office',
                'exam_notified': True,
            })

        pos_title = self._get_position_title()
        unit_str = self._get_hiring_work_units()
        date_part, time_part = self._format_date_time_parts(self.written_exam_date)
        loc_str = self.exam_location or 'Head Office'

        for app in self.ext_rec_sel:
            if app.select_flag:
                app.selection_type = 'exam'
                if app.applicant_name:
                    app.applicant_name.sudo().write({'bunna_app_status': 'exam'})
                if app.applicant_email:
                    cand_name = self._get_applicant_display_name(app)
                    message = (
                        f"Dear {cand_name},\n\n"
                        f"You have been selected for written exam assessment for the position of {pos_title} for {unit_str} work unit. "
                        f"Your exam is scheduled for {date_part} at {time_part} at {loc_str}.\n\n"
                        f"Best of luck!"
                    )
                    subject = _("Written Exam Notification - %s") % pos_title
                    self.send_mail(app.applicant_email, subject, message)

                    # Log on applicant
                    try:
                        app.applicant_name.message_post(
                            body=Markup(
                                f"<p>Dear <b>{cand_name}</b>,</p>"
                                f"<p>You have been selected for written exam assessment for the position of <b>{pos_title}</b> for <b>{unit_str}</b> work unit.</p>"
                                f"<p>Your exam is scheduled for <b>{date_part}</b> at <b>{time_part}</b> at <b>{loc_str}</b>.</p>"
                                f"<p><b>Best of luck!</b></p>"
                            ),
                            subject=subject
                        )
                    except Exception:
                        pass
                    # Discuss chat notification if user exists
                    partner = app.applicant_name.partner_id or (app.applicant_name.candidate_profile_id.partner_id if app.applicant_name.candidate_profile_id else False)
                    if partner:
                        try:
                            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                            channel.message_post(
                                body=Markup(
                                    f"<p>Dear <b>{cand_name}</b>,</p>"
                                    f"<p>You have been selected for written exam assessment for the position of <b>{pos_title}</b> for <b>{unit_str}</b> work unit.</p>"
                                    f"<p>Your exam is scheduled for <b>{date_part}</b> at <b>{time_part}</b> at <b>{loc_str}</b>.</p>"
                                    f"<p><b>Best of luck!</b></p>"
                                ),
                                message_type='comment',
                                subtype_xmlid='mail.mt_comment'
                            )
                        except Exception:
                            pass

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_exam_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_exam_evaluation_sheet failed: %s", e)
        self.exam_scheduled = 'Yes'
        if vac and vac.exists():
            vac.sudo().write({'exam_scheduled': 'Yes'})
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

        if not self.ext_rec_sel:
            raise UserError(_("No candidates found in the shortlisted selection list. Please shortlist candidates first."))

        # Check if any candidate actually took the exam / has a score
        has_any_score = any(cand.written_exam_score and cand.written_exam_score > 0 for cand in self.ext_rec_sel)
        if fetched_count == 0 and not has_any_score:
            raise UserError(_("No exam scores found. None of the shortlisted candidates have completed their written exam assessment yet."))

    def action_select_all_candidates(self):
        """ Select all candidate records at once """
        for rec in self:
            if rec.ext_rec_sel:
                rec.ext_rec_sel.write({'select_flag': True})

    def action_deselect_all_candidates(self):
        """ Deselect all candidate records at once """
        for rec in self:
            if rec.ext_rec_sel:
                rec.ext_rec_sel.write({'select_flag': False})

        # 3. Evaluate 50% written exam threshold for candidate selection
        for cand in self.ext_rec_sel:
            score = cand.written_exam_score or 0.0
            if score < 50.0 and cand.written_exam_score is not False:
                cand.select_flag = False
                cand.selection_type = 'rejected'
                cand.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score
                if cand.applicant_name:
                    cand.applicant_name.sudo().write({'bunna_app_status': 'rejected'})
            elif score >= 50.0:
                cand.select_flag = True
                cand.selection_type = 'interview'
                cand.remarks = _("Selected for Interview (Written Exam: %.2f%%)") % score
                if cand.applicant_name:
                    cand.applicant_name.sudo().write({'bunna_app_status': 'interview'})

        self.exam_scores_fetched = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Written Exam scores fetched successfully for %d candidate(s) from Written Assessment Module.') % (fetched_count or len([c for c in self.ext_rec_sel if c.written_exam_score])),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_interview_panel(self):
        if not self.exam_scores_fetched:
            raise UserError(_("Sequence Error: You must fetch written exam scores ('Fetch Exam Score') before notifying the interview panel."))
        if not self.ext_rec_panel or not self.ext_rec_panel.filtered(lambda p: p.emp_name):
            raise UserError(_("Please add at least one panel member in the Panel Members tab before notifying the panel."))
        if self.ext_rec_sel:
            passing_cands = self.ext_rec_sel.filtered(lambda c: (c.written_exam_score or 0.0) >= 50.0 and c.select_flag and c.selection_type != 'rejected')
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
        for val in self.ext_rec_panel:
            if val.emp_name:
                val.write({'response_status': 'pending'})
                usr = val.emp_name.user_id.partner_id if (val.emp_name and val.emp_name.user_id) else False
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, pos_title, str(self.interview_date), self.interview_location, work_unit=work_unit_str)
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

    def action_notify_panel_members(self):
        """Alias for notify_interview_panel to ensure consistent proxy delegation."""
        return self.notify_interview_panel()

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
        loc_str = loc
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
        vac = False
        if self.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.vacancy_id)
        elif self.vacancy_reference:
            vac = self.env['job.vacancy'].search([('reference', '=', self.vacancy_reference)], limit=1)

        # Pull interview schedule from linked vacancy if missing on this record
        if not self.interview_date and vac and vac.exists():
            if getattr(vac, 'interview_date', False):
                self.interview_date = vac.interview_date
            elif vac.selected_recruitment_id and vac.selected_recruitment_id.interview_date:
                self.interview_date = vac.selected_recruitment_id.interview_date
            if getattr(vac, 'interview_location', False) and not self.interview_location:
                self.interview_location = vac.interview_location
            elif vac.selected_recruitment_id and vac.selected_recruitment_id.interview_location and not self.interview_location:
                self.interview_location = vac.selected_recruitment_id.interview_location

        if not self.interview_date or not self.interview_location:
            raise UserError(_('Please specify both the Interview Date and Interview Location before notifying candidates.'))

        # Validate that at least one candidate passed the written exam (>= 50%)
        passing_cands = self.ext_rec_sel.filtered(lambda c: (c.written_exam_score or 0.0) >= 50.0 and c.select_flag)
        if not passing_cands:
            raise UserError(_("No candidates have passed the written examination (minimum 50% score required). Cannot proceed with interview notification."))

        # Sync interview schedule to vacancy record
        if vac and vac.exists():
            vac.sudo().write({
                'interview_date': self.interview_date,
                'interview_location': self.interview_location or 'Head Office',
                'interview_notified': True,
            })

        pos_title = self._get_position_title()
        unit_str = self._get_hiring_work_units()
        date_part, time_part = self._format_date_time_parts(self.interview_date)
        loc_str = self.interview_location or 'Head Office'

        for app in self.ext_rec_sel:
            score = app.written_exam_score or 0.0
            if score < 50.0 and app.written_exam_score is not False:
                app.select_flag = False
                app.selection_type = 'rejected'
                app.remarks = _("Disqualified: Written Exam score (%.2f%%) is below 50%% threshold.") % score
                if app.applicant_name:
                    app.applicant_name.sudo().write({'bunna_app_status': 'rejected'})
            else:
                app.selection_type = 'interview'
                if app.select_flag and app.applicant_email:
                    cand_name = self._get_applicant_display_name(app)
                    message = (
                        f"Dear {cand_name},\n\n"
                        f"You have been selected for an interview assessment for the position of {pos_title} for {unit_str} work unit. "
                        f"Your interview is scheduled for {date_part} at {time_part} at {loc_str}.\n\n"
                        f"Best of luck!"
                    )
                    subject = _("Call for Interview - %s") % pos_title
                    self.send_mail(app.applicant_email, subject, message)

                    # Log on applicant and update bunna status
                    if app.applicant_name:
                        app.applicant_name.sudo().write({'bunna_app_status': 'interview'})
                        try:
                            app.applicant_name.message_post(
                                body=Markup(
                                    f"<p>Dear <b>{cand_name}</b>,</p>"
                                    f"<p>You have been selected for an interview assessment for the position of <b>{pos_title}</b> for <b>{unit_str}</b> work unit.</p>"
                                    f"<p>Your interview is scheduled for <b>{date_part}</b> at <b>{time_part}</b> at <b>{loc_str}</b>.</p>"
                                    f"<p><b>Best of luck!</b></p>"
                                ),
                                subject=subject
                            )
                        except Exception:
                            pass
                        # Discuss chat notification if user exists
                        partner = app.applicant_name.partner_id or (app.applicant_name.candidate_profile_id.partner_id if app.applicant_name.candidate_profile_id else False)
                        if partner:
                            try:
                                channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                                channel.message_post(
                                    body=Markup(
                                        f"<p>Dear <b>{cand_name}</b>,</p>"
                                        f"<p>You have been selected for an interview assessment for the position of <b>{pos_title}</b> for <b>{unit_str}</b> work unit.</p>"
                                        f"<p>Your interview is scheduled for <b>{date_part}</b> at <b>{time_part}</b> at <b>{loc_str}</b>.</p>"
                                        f"<p><b>Best of luck!</b></p>"
                                    ),
                                    message_type='comment',
                                    subtype_xmlid='mail.mt_comment'
                                )
                            except Exception:
                                pass

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_interview_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_interview_evaluation_sheet failed: %s", e)
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
            if rec.interview_scheduled != 'Yes' and not rec.panel_notified:
                raise UserError(_("Sequence Error: You must notify candidates for the interview ('Notify Interview') before fetching interview scores."))
            rec.interview_scheduled = 'Yes'
            vac_obj = rec.vacancy_id
            vac_id_int = vac_obj.id if hasattr(vac_obj, 'id') and not isinstance(vac_obj, int) else (vac_obj if isinstance(vac_obj, int) else False)
            vac_ref = rec.vacancy_reference

            exam_w = (rec.written_exam_weight if rec.written_exam_weight is not False else 50.0) / 100.0
            intv_w = (rec.interview_weight if rec.interview_weight is not False else 50.0) / 100.0

            # Identify candidates eligible for interview (those not disqualified at exam stage)
            cands_to_evaluate = rec.ext_rec_sel.filtered(lambda c: c.selection_type != 'rejected' or (c.written_exam_score or 0.0) >= 50.0)
            if not cands_to_evaluate:
                cands_to_evaluate = rec.ext_rec_sel

            if not cands_to_evaluate:
                raise UserError(_("No candidates found in the selection list. Please shortlist candidates first."))

            cand_eval_info = []

            for cand in cands_to_evaluate:
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
                        score_val = getattr(final_res, 'final_score', 0.0) or getattr(final_res, 'average_score', 0.0) or getattr(final_res, 'interview_score', 0.0) or 0.0
                        if score_val > 0:
                            is_evaluated = True
                            fetched_score = score_val
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

            # Apply interview scores and update candidates
            for info in cand_eval_info:
                cand = info['cand']
                exam_val = cand.written_exam_score or 0.0
                fetched_score = info['fetched_score']
                weighted = round((exam_val * exam_w) + (fetched_score * intv_w), 2)

                if info['is_absent']:
                    cand.write({
                        'interview_score': 0.0,
                        'weighted_score': weighted,
                        'select_flag': False,
                        'selection_type': 'rejected',
                        'remarks': _("Disqualified: Marked absent during interview assessment."),
                    })
                    if cand.applicant_name:
                        cand.applicant_name.sudo().write({'bunna_app_status': 'rejected'})
                elif info['is_evaluated']:
                    if fetched_score < 50.0:
                        cand.write({
                            'interview_score': fetched_score,
                            'weighted_score': weighted,
                            'select_flag': False,
                            'selection_type': 'rejected',
                            'remarks': _("Disqualified: Interview score (%.2f%%) is below 50%% threshold.") % fetched_score,
                        })
                        if cand.applicant_name:
                            cand.applicant_name.sudo().write({'bunna_app_status': 'rejected'})
                    else:
                        cand.write({
                            'interview_score': fetched_score,
                            'weighted_score': weighted,
                            'select_flag': True,
                            'selection_type': 'interview',
                            'remarks': _("Interview Completed (Score: %.2f%%)") % fetched_score,
                        })
                        if cand.applicant_name:
                            cand.applicant_name.sudo().write({'bunna_app_status': 'interview'})
                else:
                    # Pending candidate without evaluation
                    cand.write({
                        'interview_score': 0.0,
                        'weighted_score': weighted,
                        'select_flag': False,
                        'selection_type': 'rejected',
                        'remarks': _("Disqualified: No interview evaluation submitted in CBIS."),
                    })
                    if cand.applicant_name:
                        cand.applicant_name.sudo().write({'bunna_app_status': 'rejected'})

            rec.interview_scores_fetched = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Interview scores fetched successfully (%d evaluated, %d absent). Proceed to Compute & Rank Scores.') % (len(evaluated_cands), len(absent_cands)),
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
            if not rec.interview_scores_fetched:
                raise UserError(_("Sequence Error: You must fetch interview scores ('Fetch Interview Score') before computing and ranking candidate scores."))
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
                    if app.applicant_name:
                        app.applicant_name.sudo().write({'bunna_app_status': 'rejected'})
                else:
                    eligible_candidates.append(app)

            if not eligible_candidates:
                raise UserError(_("No candidates have passed the evaluation. All candidates scored below the 50% threshold in the written exam or interview assessment. Cannot proceed to candidate ranking or committee approval."))

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
                if cand.applicant_name:
                    cand.applicant_name.sudo().write({'bunna_app_status': 'offer'})

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

    def action_compute_and_rank(self):
        """Alias for compute_weighted_score to ensure consistent proxy delegation."""
        return self.compute_weighted_score()

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
    _order = "rank asc, weighted_score desc, id asc"

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
    educational_qualification = fields.Char(string="Educational Qualification", compute="_compute_applicant_details", store=True, readonly=False)
    cgpa = fields.Float(string="CGPA", compute="_compute_applicant_details", store=True, readonly=False)
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(string="PMS Score")
    preferred_location = fields.Char(string="Preferred Location", compute="_compute_applicant_details", store=True, readonly=False)
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    written_exam_score = fields.Float(string="Written Exam Score")
    interview_score = fields.Float(string="Interview Score")
    weighted_score = fields.Float(string="Weighted Score")
    exam_notified = fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([
        ('shortlisted', 'Shortlisted'),
        ('exam', 'Selected for Exam'),
        ('interview', 'Selected for Interview'),
        ('selected', 'Selected'),
        ('reserved', 'Reserved'),
        ('rejected', 'Disqualified')
    ], string="Result", default='shortlisted')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    ext_rec_sel_cand = fields.Many2one("external.recruitment.selected",
                                           string="Selected candidates for External Recruitment")

    @api.depends('applicant_name', 'applicant_name.email_from', 'applicant_name.preferred_location',
                 'applicant_name.latest_cgpa', 'applicant_name.highest_education',
                 'applicant_name.candidate_profile_id', 'applicant_name.candidate_profile_id.latest_cgpa',
                 'applicant_name.candidate_profile_id.highest_education',
                 'applicant_name.candidate_profile_id.city',
                 'applicant_name.candidate_profile_id.region',
                 'applicant_name.candidate_profile_id.education_ids',
                 'applicant_name.candidate_profile_id.education_ids.cgpa')
    def _compute_applicant_details(self):
        for rec in self:
            app = rec.applicant_name
            if app:
                # 1. Email
                if not rec.applicant_email or rec.applicant_email != app.email_from:
                    rec.applicant_email = app.email_from or ''

                # 2. Preferred Location
                loc = app.preferred_location or (app.candidate_profile_id.city if app.candidate_profile_id else False) or (app.candidate_profile_id.region if app.candidate_profile_id else False)
                if loc:
                    rec.preferred_location = loc
                elif not rec.preferred_location:
                    rec.preferred_location = _("Head Office")

                # 3. CGPA
                cand_cgpa = getattr(app, 'latest_cgpa', 0.0)
                if not cand_cgpa and app.candidate_profile_id:
                    cand_cgpa = getattr(app.candidate_profile_id, 'latest_cgpa', 0.0)
                    if not cand_cgpa and app.candidate_profile_id.education_ids:
                        edus = app.candidate_profile_id.education_ids.filtered(lambda e: e.cgpa > 0)
                        if edus:
                            cand_cgpa = edus[0].cgpa
                if not cand_cgpa and hasattr(app, 'qualification_id'):
                    for q in app.qualification_id:
                        if hasattr(q, 'response') and q.response:
                            try:
                                val = float(str(q.response).strip())
                                if 0.0 < val <= 4.0:
                                    cand_cgpa = val
                                    break
                            except Exception:
                                pass
                if cand_cgpa:
                    rec.cgpa = cand_cgpa

                # 4. Educational Qualification
                edu_name = getattr(app, 'highest_education', False)
                if not edu_name and app.candidate_profile_id:
                    edu_name = getattr(app.candidate_profile_id, 'highest_education', False)
                    if not edu_name and app.candidate_profile_id.education_ids:
                        edu_name = app.candidate_profile_id.education_ids[0].qualification_name or app.candidate_profile_id.education_ids[0].field_of_study
                if not edu_name and hasattr(app, 'qualification_id'):
                    for q in app.qualification_id:
                        if q.qualification and q.qualification.qualification:
                            edu_name = q.qualification.qualification
                            break
                if not edu_name and getattr(app, 'type_id', False) and app.type_id.name:
                    edu_name = app.type_id.name
                if edu_name:
                    rec.educational_qualification = edu_name

                # 5. Gender
                gender = getattr(app, 'gender', False)
                if not gender and app.candidate_profile_id:
                    gender = getattr(app.candidate_profile_id, 'gender', False)
                if gender:
                    rec.emp_gender = gender

    def _auto_init(self):
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE external_recruitment_selected_candidates cand
                    SET 
                        applicant_email = COALESCE(NULLIF(cand.applicant_email, ''), app.email_from, cp.email),
                        preferred_location = COALESCE(NULLIF(cand.preferred_location, ''), NULLIF(app.preferred_location, ''), NULLIF(cp.city, ''), NULLIF(cp.region, ''), 'Head Office'),
                        cgpa = CASE 
                            WHEN cand.cgpa > 0 THEN cand.cgpa 
                            WHEN cp.latest_cgpa > 0 THEN cp.latest_cgpa 
                            ELSE COALESCE((SELECT edu.cgpa FROM candidate_education edu WHERE edu.candidate_id = cp.id AND edu.cgpa > 0 ORDER BY edu.end_date DESC LIMIT 1), 0.0)
                        END,
                        educational_qualification = COALESCE(
                            NULLIF(cand.educational_qualification, ''), 
                            NULLIF(cp.highest_education, ''), 
                            (SELECT edu.qualification_name FROM candidate_education edu WHERE edu.candidate_id = cp.id ORDER BY edu.end_date DESC LIMIT 1),
                            (SELECT rt.name->>'en_US' FROM hr_recruitment_degree rt WHERE rt.id = app.type_id),
                            (SELECT rt.name::text FROM hr_recruitment_degree rt WHERE rt.id = app.type_id)
                        ),
                        emp_gender = COALESCE(NULLIF(cand.emp_gender, ''), NULLIF(cp.gender, ''), NULLIF(app.gender, ''))
                    FROM hr_applicant app
                    LEFT JOIN candidate_profile cp ON cp.id = app.candidate_profile_id
                    WHERE cand.applicant_name = app.id;
                """)
        except Exception as e:
            _logger.warning("Error in external_recruitment_selected_candidates _auto_init backfill: %s", e)
        return res


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
                w_children = children.filtered(lambda u: u.work_unit_type not in ('district_office', 'branch', 'sub_branch', 'regional_office', 'service_center'))
                new_ids = set(w_children.ids) - res
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

            # Vacancy Delegation / Approval Team
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

            # Hierarchy users (Chairperson, Panel Member, Secretary, Observer)
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
        'ext_panel',
        'ext_panel.workunit_id',
        'ext_panel.chairperson_id',
        'ext_panel.panel_member_id',
        'ext_panel.secretary_id',
        'ext_panel.observer_id',
    )
    def _compute_eligible_employee_ids(self):
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        for rec in self:
            rec.eligible_employee_ids = all_emps

    @api.onchange('ext_panel', 'selection_criteria')
    def _onchange_ext_panel_domain(self):
        """Allow all active employees to be selected as panel members."""
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        self.eligible_employee_ids = all_emps
        domain = [('active', '=', True)]
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

    def _auto_init(self):
        super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE external_recrt_delegation_team SET role = 'chairperson' WHERE role = 'chair_person';
                    UPDATE external_recrt_delegation_team SET role = 'secretary' WHERE role IN ('secretary', 'member_secretary');
                    UPDATE external_recrt_delegation_team SET role = 'panel_member' WHERE role IN ('member', 'approver') OR role IS NULL;
                    UPDATE external_recrt_delegation_team SET status = 'active' WHERE status IS NULL OR status = '';
                """)
        except Exception as e:
            _logger.warning("Migration query on external_recrt_delegation_team failed: %s", e)

    role = fields.Selection([
        ("chairperson", "Chairperson"),
        ("panel_member", "Panel Member"),
        ("secretary", "Panel Member & Secretary"),
        ("observer", "Labor Representative (Observer)"),
    ], string="Role", default="panel_member")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    active = fields.Boolean(default=True)
    eligible_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_eligible_user_ids',
        string='Eligible Approvers'
    )

    @api.depends('role', 'exter_rec_del_id', 'exter_rec_del_id.vacancy_id', 'exter_rec_del_id.workunit_id')
    def _compute_eligible_user_ids(self):
        for rec in self:
            domain = rec._get_role_user_domain(rec.role)
            rec.eligible_user_ids = self.env['res.users'].search(domain)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.onchange('role', 'exter_rec_del_id')
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
        sel = self.exter_rec_del_id
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
    exter_rec_del_id = fields.Many2one("external.recruitment.selected", string="External Recruitment Selected Delegation Team")
