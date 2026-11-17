# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup, escape

NON_MANAGERIAL_DURATION = 60
MANAGERIAL_DURATION = 75
NOTIFICATION_DAYS_EARLY = 15
NOTIFICATION_DAYS_URGENT = 5
PASS_SCORE_THRESHOLD_PCT = 70.0


class HrEmployeeProbation(models.Model):
    _name = "hr.employee.probation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Employee Probation Management"
    _rec_name = "name"
    _order = "probation_end_date asc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    # -- Employee & Position Details (Bunna Bank Probationer Form Header) --
    eligible_employee_ids = fields.Many2many(
        "hr.employee",
        compute="_compute_eligible_employee_ids",
        string="Eligible Probationers",
    )
    employee_id = fields.Many2one("hr.employee", string="Name of Probationer", required=True, tracking=True)
    job_position_id = fields.Many2one(
        "hr.job", string="Position Title", compute="_compute_from_employee", store=True, readonly=True
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Place of Assignment", compute="_compute_from_employee", store=True, readonly=True
    )
    department_id = fields.Many2one(
        "hr.department", string="Department", related="employee_id.department_id", store=True, readonly=True
    )
    supervisor_id = fields.Many2one(
        "hr.employee",
        string="Immediate Supervisor / Evaluator",
        compute="_compute_from_employee",
        store=True,
        readonly=True,
        tracking=True,
    )
    evaluator_name = fields.Char(string="Name of Evaluator", related="supervisor_id.name", readonly=True)
    evaluator_position = fields.Char(string="Evaluator Position", compute="_compute_evaluator_position", store=True)

    source_recruitment = fields.Selection(
        [("internal", "Internal Recruitment"), ("external", "External Recruitment")],
        string="Recruitment Source", default="external",
    )
    recruitment_reference = fields.Char(string="Recruitment Reference")

    # -- Duration & Category --
    employee_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Employee Category", required=True, default="Non Managerial", tracking=True,
        help="Drives statutory probation duration: 60 days for Non-Managerial, 75 days for Managerial.",
    )
    probation_start_date = fields.Date(
        string="Employment / Start Date",
        compute="_compute_from_employee",
        store=True,
        readonly=True,
    )
    duration_days = fields.Integer(
        string="Probation Duration (Days)", compute="_compute_duration_days", store=True, readonly=True,
    )
    probation_end_date = fields.Date(
        string="Probation End Date", compute="_compute_probation_end_date", store=True, readonly=True,
    )
    working_days_elapsed = fields.Integer(
        string="Working Days Elapsed",
        compute="_compute_working_days_elapsed",
        help="Number of working days elapsed since employment/probation start date.",
    )
    working_days_remaining = fields.Integer(
        string="Working Days Remaining",
        compute="_compute_working_days_elapsed",
        help="Number of working days remaining until probation ends.",
    )

    # -- Extension --
    is_extended = fields.Boolean(string="Probation Extended", default=False, readonly=True, copy=False)
    extension_days = fields.Integer(string="Extension Days", default=0, copy=False)
    extension_reason = fields.Text(string="Extension Reason", copy=False)

    # -- Notifications --
    notification_sent = fields.Boolean(string="Supervisor Notified", default=False, readonly=True, copy=False)
    notification_date = fields.Datetime(string="Notification Sent On", readonly=True, copy=False)

    # -- Performance Scoring (Bunna Bank Evaluation Table) --
    criteria_line_ids = fields.One2many(
        "hr.employee.probation.criteria.line", "probation_id", string="Evaluation Criteria"
    )
    total_score = fields.Float(string="Total Score", compute="_compute_scores", store=True)
    max_possible_score = fields.Float(string="Max Possible Score", compute="_compute_scores", store=True)
    percentage_score = fields.Float(string="Evaluation Result Out of 100", compute="_compute_scores", store=True, digits=(5, 2))
    is_pass_score = fields.Boolean(string="Meets Passing Threshold (70%)", compute="_compute_scores", store=True)

    # -- Recommendation & Observation (Form Footer) --
    recommend_permanent = fields.Selection(
        [
            ("yes", "Yes - Recommend for Permanent Employment"),
            ("no", "No - Do Not Recommend for Permanent Employment"),
        ],
        string="Recommend for Permanent Employment?", tracking=True,
    )

    # -- Committee / Delegation --
    delegation_team_ids = fields.One2many(
        "hr.employee.probation.delegation.team", "probation_id", string="Delegation Committee"
    )
    committee_evaluated = fields.Boolean(string="Committee Evaluated", default=False, readonly=True, copy=False)
    in_charge_id = fields.Many2one("hr.employee", string="TDD In-Charge Officer")

    # -- Outcome & State --
    outcome = fields.Selection(
        [
            ("pending", "Pending"),
            ("satisfactory", "Satisfactory (Permanency Confirmation)"),
            ("unsatisfactory", "Unsatisfactory (Contract Termination)"),
        ],
        string="Outcome", default="pending", required=True, tracking=True,
    )
    outcome_date = fields.Date(string="Outcome Recorded On", readonly=True, copy=False)
    outcome_notes = fields.Text(string="Comments & Observations")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("notified", "Supervisor Notified"),
            ("evaluated", "Evaluated"),
            ("completed", "Completed / Permanency Confirmed"),
            ("terminated", "Contract Terminated"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    job_description = fields.Text(
        string="Position Description",
        compute="_compute_job_description",
        store=True,
        readonly=False,
        help="Position description fetched from Job Position (Text type)."
    )
    cc_block_display = fields.Text(
        string="CC Workunits",
        compute="_compute_cc_block_display",
        help="Calculated CC recipients according to Bunna Bank policy."
    )
    employee_email = fields.Char(
        string="Employee Email",
        compute="_compute_emails",
        store=True,
        readonly=False,
        help="Email address of the employee for permanent letter dispatch."
    )
    supervisor_email = fields.Char(
        string="Supervisor Email",
        compute="_compute_emails",
        store=True,
        readonly=False,
        help="Email address of the supervisor/evaluator for permanent letter dispatch."
    )
    permanent_letter_sent = fields.Boolean(
        string="Permanent Letter Sent", default=False, readonly=True, copy=False, tracking=True
    )
    permanent_letter_sent_date = fields.Datetime(
        string="Permanent Letter Sent On", readonly=True, copy=False
    )
    permanent_letter_ref = fields.Char(
        string="Permanent Letter Ref", copy=False, tracking=True,
        help="Official Confirmation of Permanent Employment Letter Reference Number "
    )

    signatory_config_id = fields.Many2one(
        'recruitment.signatory.config',
        string='Signatory & Stamp Configuration',
        help='Configuration providing the official signature and stamp for Permanent Confirmation'
    )

    def get_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        sig = self.get_signatory_config()
        if sig and hasattr(sig, 'get_letter_signature_data'):
            data = sig.get_letter_signature_data()
            name = self.get_signatory_name()
            title = self.get_signatory_title()
            comp = self.get_signatory_company()
            if name:
                data['signatory_name'] = name
            if title:
                data['signatory_title'] = title
            if comp:
                data['signatory_company'] = comp
            return data
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': sig.get_signature_stamp_base64() if (sig and hasattr(sig, 'get_signature_stamp_base64')) else '',
            'signatory_name': self.get_signatory_name(),
            'signatory_title': self.get_signatory_title(),
            'signatory_company': self.get_signatory_company(),
        }

    def get_signatory_config(self):
        self.ensure_one()
        if self.signatory_config_id:
            return self.signatory_config_id
        return self.env['recruitment.signatory.config'].get_signatory_for_unit(
            work_unit=self.operating_unit_id,
            department=self.department_id,
            doc_type='permanent_letter'
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

    # -------------------------------------------------------------------------
    @api.depends("job_position_id", "job_position_id.job_description", "job_position_id.description")
    def _compute_job_description(self):
        import re
        for rec in self:
            job = rec.job_position_id
            if job:
                desc = job.job_description or job.description or ""
                if desc:
                    # Strip html tags if html markup
                    cleaned = re.sub(r'<[^>]+>', ' ', str(desc)).strip()
                    rec.job_description = re.sub(r'\s+', ' ', cleaned)
                else:
                    rec.job_description = ""
            else:
                rec.job_description = ""

    @api.depends("department_id", "operating_unit_id", "employee_category")
    def _compute_cc_block_display(self):
        for rec in self:
            lines = rec.get_permanent_letter_cc_lines()
            rec.cc_block_display = "\n".join(lines) if lines else ""

    @api.depends("employee_id", "employee_id.work_email", "employee_id.private_email", "supervisor_id", "supervisor_id.work_email")
    def _compute_emails(self):
        for rec in self:
            if not rec.employee_email and rec.employee_id:
                rec.employee_email = (
                    rec.employee_id.work_email
                    or rec.employee_id.private_email
                    or (rec.employee_id.user_id.email if rec.employee_id.user_id else False)
                    or ""
                )
            if not rec.supervisor_email:
                sup = rec.supervisor_id or rec.employee_id.parent_id or rec.employee_id.coach_id
                rec.supervisor_email = (
                    (sup.work_email if sup else False)
                    or (sup.private_email if sup else False)
                    or (sup.user_id.email if (sup and sup.user_id) else False)
                    or ""
                )

    def action_send_permanent_letter(self, raise_if_no_email=True):
        """Dispatches the official Confirmation of Permanent Employment Letter PDF
        to both the newly hired employee and their supervisor via email."""
        self.ensure_one()
        if self.state != 'completed' or self.outcome != 'satisfactory':
            raise UserError(_("Permanent Confirmation Letter can only be sent for completed probations with a Satisfactory outcome."))

        # 1. Ensure official reference is generated
        if not self.permanent_letter_ref:
            prefix = "BB/TAOD" if self.employee_category == "Managerial" else "BB/POMD"
            year = fields.Date.today().year
            seq = self.env['ir.sequence'].next_by_code('hr.employee.probation.permanent.letter')
            if not seq:
                seq = str(self.id).zfill(4)
            self.permanent_letter_ref = f"{prefix}/{seq}/{year}"

        # 2. Resolve recipient email addresses
        emp_email = (
            self.employee_email
            or self.employee_id.work_email
            or self.employee_id.private_email
            or (self.employee_id.user_id.email if self.employee_id.user_id else False)
            or ''
        ).strip()

        sup = self.supervisor_id or self.employee_id.parent_id or self.employee_id.coach_id
        sup_email = (
            self.supervisor_email
            or (sup.work_email if sup else False)
            or (sup.private_email if sup else False)
            or (sup.user_id.email if (sup and sup.user_id) else False)
            or ''
        ).strip()

        if not emp_email and not sup_email:
            msg = _(
                "Cannot send Permanent Confirmation Letter: Neither the employee (%s) nor their supervisor has an email address registered.\n\n"
                "Please enter an email address in the 'Employee Email' or 'Supervisor Email' field before sending."
            ) % (self.employee_id.name or '')
            if raise_if_no_email:
                raise UserError(msg)
            _logger.warning(msg)
            return False

        # 3. Generate official PDF attachment
        report_action = self.env.ref('custom_recruitment.action_report_probation_permanent_letter')
        pdf_content, _dummy = report_action._render_qweb_pdf(report_action.id, res_ids=[self.id])
        emp_clean_name = (self.employee_id.name or 'Employee').replace(' ', '_')
        attachment = self.env['ir.attachment'].sudo().create({
            'name': f"Confirmation_of_Permanent_Employment_{emp_clean_name}.pdf",
            'type': 'binary',
            'raw': pdf_content,
            'res_model': 'hr.employee.probation',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        # 4. Compose official Bunna Bank email content
        emp_name = self.employee_id.name or 'Employee'
        sup_name = sup.name if sup else 'Supervisor'
        job_title = self.job_position_id.name if self.job_position_id else 'Staff Member'
        prob_start = self.probation_start_date.strftime('%B %d, %Y') if self.probation_start_date else ''
        prob_end = self.probation_end_date.strftime('%B %d, %Y') if self.probation_end_date else ''
        duration = self.get_permanent_letter_duration_days()
        signatory_name = self.get_signatory_name() or 'People Operations & Talent Management Directorate'
        signatory_title = self.get_signatory_title() or 'Director, People Operations & Talent Management Directorate'
        ref_no = self.permanent_letter_ref or self.name

        body_html = f"""
        <div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222222; line-height: 1.6; max-width: 650px;">
            <p>Dear <strong>{emp_name}</strong>,</p>
            <p>We are pleased to inform you that you have successfully completed your probation period of <strong>{duration} working days</strong> on <strong>{prob_end}</strong> as <strong>{job_title}</strong> and have become a permanent staff member of <strong>Bunna Bank S.C.</strong></p>
            <p>Please note that your future progress in the Bank depends on your commitment to meet the Bank's set objectives and your readiness to meet the demands of our customers.</p>
            <p>Please find attached your official signed and stamped <strong>Confirmation of Permanent Employment Letter</strong> (Ref. No: <strong>{ref_no}</strong>).</p>
            <p>We congratulate you on this milestone and wish you continued success in your career at Bunna Bank!</p>
            <br/>
            <p style="margin-bottom: 2px;">Sincerely yours,</p>
            <strong>{signatory_name}</strong><br/>
            <strong>{signatory_title}</strong><br/>
            <strong>Bunna Bank S.C.</strong>
            <div style="margin-top: 24px; padding-top: 10px; border-top: 1px solid #eeeeee; font-size: 12px; color: #555555;">
                <strong>CC:</strong> Supervisor / Evaluator: {sup_name} {f'({sup_email})' if sup_email else ''}<br/>
                Place of Assignment: {self.operating_unit_id.name or 'Bunna Bank S.C.'}
            </div>
        </div>
        """

        # 5. Dispatch Email
        mail_server = self.env['ir.mail_server'].sudo().search([], limit=1)
        email_from = mail_server.smtp_user if mail_server and mail_server.smtp_user else (self.env.user.email or 'hr@bunnabanksc.com')

        to_emails = [e for e in [emp_email, sup_email] if e]
        email_to_str = ", ".join(to_emails)

        mail_values = {
            'subject': f"Confirmation of Permanent Employment - {emp_name} - Bunna Bank S.C.",
            'body_html': body_html,
            'email_to': email_to_str,
            'email_from': f"Bunna Bank HR <{email_from}>" if '<' not in email_from else email_from,
            'mail_server_id': mail_server.id if mail_server else False,
            'attachment_ids': [(4, attachment.id)],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        try:
            mail.send(raise_exception=False)
        except Exception as mail_ex:
            _logger.warning("Permanent letter email dispatch warning: %s", mail_ex)

        # 6. Update tracking fields and chatter
        self.write({
            'permanent_letter_sent': True,
            'permanent_letter_sent_date': fields.Datetime.now(),
        })

        self.message_post(
            body=_(
                "Confirmation of Permanent Employment Letter (Ref: <b>%s</b>) emailed to:<br/>"
                "• Employee: <b>%s</b> (%s)<br/>"
                "• Supervisor: <b>%s</b> (%s)"
            ) % (ref_no, emp_name, emp_email or 'No email', sup_name, sup_email or 'No email'),
            subject=_("Permanent Letter Dispatched"),
            attachment_ids=[attachment.id]
        )

        if self.employee_id:
            try:
                self.employee_id.message_post(
                    body=_(
                        "Official Confirmation of Permanent Employment Letter (Ref: <b>%s</b>) issued and dispatched by email to employee and supervisor."
                    ) % ref_no,
                    subject=_("Permanent Employment Confirmed"),
                    attachment_ids=[attachment.id]
                )
            except Exception as e:
                _logger.warning("Could not post to employee record chatter: %s", e)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Permanent Letter Emailed'),
                'message': _('Confirmation of Permanent Employment Letter has been successfully sent to %s.') % email_to_str,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_print_permanent_letter(self):
        """Prints the official Bunna Bank Confirmation of Permanent Employment letter.
        Only accessible after probation is completed with a Satisfactory outcome."""
        self.ensure_one()
        if self.state != 'completed' or self.outcome != 'satisfactory':
            raise UserError(_("Permanent Employment Confirmation Letter can only be generated for completed probations with a Satisfactory outcome."))

        if not self.permanent_letter_ref:
            prefix = "BB/TAOD" if self.employee_category == "Managerial" else "BB/POMD"
            year = fields.Date.today().year
            seq = self.env['ir.sequence'].next_by_code('hr.employee.probation.permanent.letter')
            if not seq:
                seq = str(self.id).zfill(4)
            self.permanent_letter_ref = f"{prefix}/{seq}/{year}"

        return self.env.ref('custom_recruitment.action_report_probation_permanent_letter').report_action(self)

    def get_barlow_font_faces(self):
        """Provides Barlow Medium font embedding for QWeb PDF printing."""
        try:
            from hr_employee_custom.models.report_font_utils import get_barlow_font_faces_css
            return get_barlow_font_faces_css()
        except Exception:
            return ""

    def get_permanent_letter_recipient_title(self):
        self.ensure_one()
        emp = self.employee_id
        if not emp:
            return "Ato"
        title = getattr(emp, 'title', False)
        if title and hasattr(title, 'name') and title.name:
            t = title.name.strip()
            if t in ('Ato', 'W/ro', 'W/t', 'W/y', 'Dr.'):
                return t
        gender = getattr(emp, 'gender', False)
        if gender == 'female':
            return "W/y"
        return "Ato"

    def get_permanent_letter_recipient_name_with_title(self):
        self.ensure_one()
        title = self.get_permanent_letter_recipient_title()
        name = (self.employee_id.name if self.employee_id else "").strip()
        for prefix in ['Ato ', 'W/y ', 'W/ro ', 'W/t ', 'Dr. ']:
            if name.startswith(prefix):
                return name
        return f"{title} {name}"

    def get_permanent_letter_salutation_name(self):
        self.ensure_one()
        title = self.get_permanent_letter_recipient_title()
        name = (self.employee_id.name if self.employee_id else "").strip()
        for prefix in ['Ato ', 'W/y ', 'W/ro ', 'W/t ', 'Dr. ']:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
                break
        first_name = name.split()[0] if name else ""
        return f"{title} {first_name}"

    def get_permanent_letter_city(self):
        self.ensure_one()
        ou = self.operating_unit_id
        if ou and ou.name:
            ou_name = ou.name.strip()
            if "head office" in ou_name.lower():
                return "Addis Ababa"
            if "branch" in ou_name.lower():
                clean_name = ou_name.replace("Branch", "").strip()
                if clean_name:
                    return clean_name
            return ou_name
        loc = getattr(self.employee_id, 'work_location_id', False)
        if loc and loc.name:
            return loc.name
        return "Addis Ababa"

    def get_permanent_letter_duration_days(self):
        self.ensure_one()
        if self.employee_category == "Managerial":
            return 75
        return 60

    def get_permanent_letter_cc_lines(self):
        """Determines official CC recipients according to Bunna Bank guidelines:
        - If department of the employee is District -> Default Operating Unit, their respective District, Main Branch, Bunna Bank S.C. (and Finance Directorate if non-managerial).
        - If department is Head Office -> ONLY their Operating Unit only, Bunna Bank S.C."""
        self.ensure_one()
        lines = []
        dept = self.department_id or (self.employee_id.department_id if self.employee_id else False)
        dept_name = (dept.name if dept else "").strip()
        
        ou = self.operating_unit_id or (self.employee_id.default_operating_unit_id if self.employee_id else False)
        ou_name = (ou.name if ou else "").strip()

        is_district = "district" in dept_name.lower() or "area" in dept_name.lower()

        if is_district:
            # 1. District Case: default operating unit and their respective district
            if self.employee_category != "Managerial":
                lines.append("Finance Directorate")
            if dept_name:
                lines.append(dept_name)
            if ou_name and ou_name.lower() != dept_name.lower():
                lines.append(ou_name)
            lines.append("Main Branch")
            lines.append("Bunna Bank S.C.")
        else:
            # 2. Head Office Case: only his operating unit only
            if ou_name:
                lines.append(ou_name)
            elif dept_name:
                lines.append(dept_name)
            lines.append("Bunna Bank S.C.")

        return lines


    # Sequence & Reference Generation
    # -------------------------------------------------------------------------
    @api.model
    def _get_fiscal_year_prefix(self):
        """Computes the current fiscal-year prefix (July–June cycle)."""
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/PROB/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_reference(self):
        prefix = self._get_fiscal_year_prefix()
        self.env.cr.execute("""
            SELECT name FROM hr_employee_probation
            WHERE name IS NOT NULL AND name != 'New' AND name LIKE %s
            ORDER BY id DESC LIMIT 1
        """, (prefix + '%',))
        result = self.env.cr.fetchone()
        if result and result[0]:
            _, _, numeric_part = result[0].rpartition('/')
            try:
                next_number = int(numeric_part) + 1
            except ValueError:
                next_number = 1
        else:
            next_number = 1
        return f"{prefix}{str(next_number).zfill(5)}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self._get_next_reference()
            if vals.get("recommend_permanent") == "no" and not vals.get("outcome"):
                vals["outcome"] = "unsatisfactory"
            elif vals.get("recommend_permanent") == "yes" and not vals.get("outcome"):
                vals["outcome"] = "satisfactory"
        records = super().create(vals_list)
        for rec in records:
            if not rec.criteria_line_ids:
                rec.action_populate_criteria()
        return records

    @api.onchange("recommend_permanent")
    def _onchange_recommend_permanent(self):
        if self.recommend_permanent == "yes":
            self.outcome = "satisfactory"
        elif self.recommend_permanent == "no":
            self.outcome = "unsatisfactory"
        elif not self.recommend_permanent:
            self.outcome = "pending"

    @api.onchange("outcome")
    def _onchange_outcome(self):
        if self.outcome == "satisfactory":
            self.recommend_permanent = "yes"
        elif self.outcome == "unsatisfactory":
            self.recommend_permanent = "no"
        elif self.outcome == "pending":
            self.recommend_permanent = False

    def write(self, vals):
        if "recommend_permanent" in vals and "outcome" not in vals:
            if vals.get("recommend_permanent") == "no":
                vals["outcome"] = "unsatisfactory"
            elif vals.get("recommend_permanent") == "yes":
                vals["outcome"] = "satisfactory"
            elif not vals.get("recommend_permanent"):
                vals["outcome"] = "pending"
        elif "outcome" in vals and "recommend_permanent" not in vals:
            if vals.get("outcome") == "satisfactory":
                vals["recommend_permanent"] = "yes"
            elif vals.get("outcome") == "unsatisfactory":
                vals["recommend_permanent"] = "no"
            elif vals.get("outcome") == "pending":
                vals["recommend_permanent"] = False

        user = self.env.user
        emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if emp and any(
            (rec.supervisor_id and rec.supervisor_id.id == emp.id)
            or (rec.employee_id and rec.employee_id.coach_id and rec.employee_id.coach_id.id == emp.id)
            or (rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.id == emp.id)
            for rec in self
        ):
            return super(HrEmployeeProbation, self.sudo()).write(vals)

        return super().write(vals)

    @api.depends("employee_id")
    def _compute_eligible_employee_ids(self):
        """Filters employee selection strictly to new hires within their statutory probation period:
        duration is below 60 working days for Non-Managerial and 75 working days for Managerial."""
        today = fields.Date.context_today(self)

        calendar = self.env.company.resource_calendar_id
        leave_domain = [("resource_id", "=", False)]
        if calendar:
            leave_domain.append(("calendar_id", "in", [False, calendar.id]))
        holiday_leaves = self.env["resource.calendar.leaves"].sudo().search(leave_domain)
        holiday_ranges = []
        for h in holiday_leaves:
            if h.date_from and h.date_to:
                holiday_ranges.append((h.date_from.date(), h.date_to.date()))

        work_weekdays = (
            set(int(att.dayofweek) for att in calendar.attendance_ids)
            if calendar and calendar.attendance_ids
            else {0, 1, 2, 3, 4}
        )

        def _count_work_days(start_d, end_d):
            if not start_d or not end_d or start_d > end_d:
                return 0
            curr = start_d
            count = 0
            while curr <= end_d:
                if curr.weekday() in work_weekdays and not any(s <= curr <= e for s, e in holiday_ranges):
                    count += 1
                curr += timedelta(days=1)
            return count

        completed_ids = set(
            self.env["hr.employee.probation"].sudo().search([
                ("state", "in", ["completed", "terminated"])
            ]).mapped("employee_id.id")
        )

        cutoff_date = today - timedelta(days=180)
        recent_employees = self.env["hr.employee"].sudo().search([
            ("active", "=", True),
            "|", "|",
            ("service_hire_date", ">=", cutoff_date),
            ("start_date", ">=", cutoff_date),
            ("probation_start_date", ">=", cutoff_date),
        ])

        eligible_ids = set()
        for emp in recent_employees:
            hire_d = (
                emp.service_hire_date
                or emp.probation_start_date
                or emp.start_date
                or (emp.create_date.date() if emp.create_date else False)
            )
            if not hire_d:
                continue

            job = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
            cat = getattr(job, "employee_category", False) or getattr(emp, "employee_category", False) or "Non Managerial"
            max_limit = 75 if cat == "Managerial" else 60

            elapsed = 0 if hire_d > today else _count_work_days(hire_d, today)
            if elapsed <= max_limit:
                eligible_ids.add(emp.id)

        for rec in self:
            current_id = rec.employee_id.id if rec.employee_id else False
            available = (eligible_ids - completed_ids)
            if current_id:
                available.add(current_id)
            rec.eligible_employee_ids = self.env["hr.employee"].sudo().browse(list(available))

    @api.depends(
        "employee_id",
        "employee_id.parent_id",
        "employee_id.coach_id",
        "employee_id.service_hire_date",
        "employee_id.probation_start_date",
        "employee_id.start_date",
    )
    def _compute_from_employee(self):
        for rec in self:
            if rec.employee_id:
                rec.job_position_id = getattr(rec.employee_id, 'job_position', False) or getattr(rec.employee_id, 'job_id', False) or False
                rec.operating_unit_id = getattr(rec.employee_id, 'default_operating_unit_id', False) or False
                rec.supervisor_id = rec.employee_id.parent_id or rec.employee_id.coach_id or False
                hire_d = (
                    rec.employee_id.service_hire_date
                    or rec.employee_id.probation_start_date
                    or rec.employee_id.start_date
                    or (rec.employee_id.create_date.date() if rec.employee_id.create_date else False)
                    or fields.Date.context_today(self)
                )
                rec.probation_start_date = hire_d
            else:
                rec.job_position_id = False
                rec.operating_unit_id = False
                rec.supervisor_id = False
                rec.probation_start_date = fields.Date.context_today(self)

    @api.depends("supervisor_id", "supervisor_id.job_id")
    def _compute_evaluator_position(self):
        for rec in self:
            if rec.supervisor_id:
                rec.evaluator_position = getattr(rec.supervisor_id, 'job_title', False) or (
                    rec.supervisor_id.job_id.name if rec.supervisor_id.job_id else ""
                )
            else:
                rec.evaluator_position = ""

    @api.depends("employee_category")
    def _compute_duration_days(self):
        for rec in self:
            rec.duration_days = (
                MANAGERIAL_DURATION if rec.employee_category == "Managerial" else NON_MANAGERIAL_DURATION
            )

    @api.depends("probation_start_date", "duration_days", "extension_days", "employee_id")
    def _compute_probation_end_date(self):
        for rec in self:
            if not (rec.probation_start_date and rec.duration_days):
                rec.probation_end_date = False
                continue

            target_working_days = rec.duration_days + (rec.extension_days or 0)
            if target_working_days <= 0:
                rec.probation_end_date = rec.probation_start_date
                continue

            calendar = (
                rec.employee_id.resource_calendar_id
                or rec.env.company.resource_calendar_id
                or False
            )

            # Public holidays / Global leaves domain (excluding leaves where resource_id is set for specific employees)
            leave_domain = [('resource_id', '=', False)]
            if calendar:
                leave_domain.append(('calendar_id', 'in', [False, calendar.id]))

            holiday_leaves = self.env['resource.calendar.leaves'].search(leave_domain)
            holiday_ranges = []
            for h in holiday_leaves:
                if h.date_from and h.date_to:
                    holiday_ranges.append((h.date_from.date(), h.date_to.date()))

            # Working days of week (0=Mon ... 6=Sun). Default: Monday to Friday
            if calendar and calendar.attendance_ids:
                work_weekdays = set(int(att.dayofweek) for att in calendar.attendance_ids)
            else:
                work_weekdays = {0, 1, 2, 3, 4}

            curr_date = rec.probation_start_date
            counted_days = 0
            max_days_limit = 500  # Safeguard against infinite loops
            iterations = 0

            while counted_days < target_working_days and iterations < max_days_limit:
                iterations += 1
                is_workday = curr_date.weekday() in work_weekdays
                is_holiday = any(start_d <= curr_date <= end_d for start_d, end_d in holiday_ranges)

                if is_workday and not is_holiday:
                    counted_days += 1

                if counted_days < target_working_days:
                    curr_date += timedelta(days=1)

            rec.probation_end_date = curr_date

    @api.depends("criteria_line_ids.score", "criteria_line_ids.coefficient")
    def _compute_scores(self):
        for rec in self:
            total = sum(line.score for line in rec.criteria_line_ids)
            max_score = sum(5 * line.coefficient for line in rec.criteria_line_ids if line.coefficient)
            pct = (total / max_score * 100.0) if max_score > 0 else 0.0
            rec.total_score = total
            rec.max_possible_score = max_score
            rec.percentage_score = pct
            rec.is_pass_score = pct >= PASS_SCORE_THRESHOLD_PCT

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                job = getattr(rec.employee_id, 'job_position', False) or getattr(rec.employee_id, 'job_id', False)
                if job and hasattr(job, 'employee_category') and job.employee_category:
                    rec.employee_category = job.employee_category
                rec.supervisor_id = rec.employee_id.parent_id or rec.employee_id.coach_id or False
                hire_d = rec.employee_id.service_hire_date or rec.employee_id.probation_start_date or rec.employee_id.start_date
                if hire_d:
                    rec.probation_start_date = hire_d



    # -------------------------------------------------------------------------
    # Actions & Workflow
    # -------------------------------------------------------------------------

    @api.depends("probation_start_date", "probation_end_date", "duration_days")
    def _compute_working_days_elapsed(self):
        today = fields.Date.context_today(self)
        calendar = self.env.company.resource_calendar_id
        leave_domain = [('resource_id', '=', False)]
        if calendar:
            leave_domain.append(('calendar_id', 'in', [False, calendar.id]))
        holiday_leaves = self.env['resource.calendar.leaves'].sudo().search(leave_domain)
        holiday_ranges = [(h.date_from.date(), h.date_to.date()) for h in holiday_leaves if h.date_from and h.date_to]
        work_weekdays = (
            set(int(att.dayofweek) for att in calendar.attendance_ids)
            if calendar and calendar.attendance_ids
            else {0, 1, 2, 3, 4}
        )

        for rec in self:
            if not rec.probation_start_date:
                rec.working_days_elapsed = 0
                rec.working_days_remaining = rec.duration_days or 0
                continue
            if rec.probation_start_date > today:
                rec.working_days_elapsed = 0
                rec.working_days_remaining = rec.duration_days or 0
                continue
            curr = rec.probation_start_date
            elapsed = 0
            while curr <= today:
                if curr.weekday() in work_weekdays and not any(s <= curr <= e for s, e in holiday_ranges):
                    elapsed += 1
                curr += timedelta(days=1)
            rec.working_days_elapsed = elapsed
            rec.working_days_remaining = max(0, (rec.duration_days or 0) - elapsed)

    @api.model
    def _auto_sync_eligible_probations(self):
        """Automatically creates hr.employee.probation records for active employees within
        their statutory probation period (60 working days for Non-Managerial, 75 working days
        for Managerial) from their employment start date."""
        today = fields.Date.context_today(self)
        calendar = self.env.company.resource_calendar_id
        leave_domain = [('resource_id', '=', False)]
        if calendar:
            leave_domain.append(('calendar_id', 'in', [False, calendar.id]))
        holiday_leaves = self.env['resource.calendar.leaves'].sudo().search(leave_domain)
        holiday_ranges = [(h.date_from.date(), h.date_to.date()) for h in holiday_leaves if h.date_from and h.date_to]
        work_weekdays = (
            set(int(att.dayofweek) for att in calendar.attendance_ids)
            if calendar and calendar.attendance_ids
            else {0, 1, 2, 3, 4}
        )

        def _count_work_days(start_d, end_d):
            if not start_d or not end_d or start_d > end_d:
                return 0
            curr = start_d
            cnt = 0
            while curr <= end_d:
                if curr.weekday() in work_weekdays and not any(s <= curr <= e for s, e in holiday_ranges):
                    cnt += 1
                curr += timedelta(days=1)
            return cnt

        cutoff_date = today - timedelta(days=180)
        recent_employees = self.env['hr.employee'].sudo().search([
            ('active', '=', True),
            '|', '|', '|',
            ('service_hire_date', '>=', cutoff_date),
            ('start_date', '>=', cutoff_date),
            ('probation_start_date', '>=', cutoff_date),
            ('create_date', '>=', cutoff_date),
        ])

        existing_emp_ids = set(self.sudo().search([]).mapped('employee_id.id'))

        for emp in recent_employees:
            if emp.id in existing_emp_ids:
                continue
            if emp.user_id and emp.user_id._is_superuser():
                continue
            if emp.name and emp.name.strip().lower() == 'administrator':
                continue

            hire_d = (
                emp.service_hire_date
                or emp.probation_start_date
                or emp.start_date
                or (emp.create_date.date() if emp.create_date else False)
            )
            if not hire_d:
                continue

            job = getattr(emp, 'job_position', False) or getattr(emp, 'job_id', False)
            cat = getattr(job, 'employee_category', False) or getattr(emp, 'employee_category', False) or 'Non Managerial'
            max_limit = 75 if cat == 'Managerial' else 60

            elapsed = 0 if hire_d > today else _count_work_days(hire_d, today)
            if elapsed <= max_limit:
                try:
                    self.sudo().create({
                        'employee_id': emp.id,
                        'employee_category': 'Managerial' if cat == 'Managerial' else 'Non Managerial',
                        'probation_start_date': hire_d,
                        'state': 'draft',
                    })
                    existing_emp_ids.add(emp.id)
                except Exception as e:
                    _logger.warning("Failed to auto-create probation record for employee %s (%s): %s", emp.name, emp.id, e)

    @api.model
    def action_open_probation_management(self):
        """Action invoked by menu 'Probation Management'. Automatically ensures all eligible employees
        have probation records and displays them in list view without manual creation."""
        self.sudo()._auto_sync_eligible_probations()
        action = self.env["ir.actions.act_window"]._for_xml_id("custom_recruitment.action_hr_employee_probation")
        today = fields.Date.context_today(self)
        domain = [('probation_end_date', '>=', today), ('state', 'not in', ('completed', 'terminated'))]

        user = self.env.user
        is_hr_admin = (
            user.has_group('custom_recruitment.group_recruitment_administrator')
            or user.has_group('custom_recruitment.group_recruitment_manager')
            or user.has_group('hr.group_hr_manager')
            or self.env.is_superuser()
        )
        if not is_hr_admin:
            emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if emp:
                domain.extend([
                    '|', '|',
                    ('employee_id.coach_id', '=', emp.id),
                    ('supervisor_id', '=', emp.id),
                    ('employee_id.parent_id', '=', emp.id),
                ])
            else:
                domain.append(('id', '=', 0))

        action['domain'] = domain
        action['context'] = dict(self.env.context, search_default_filter_within_duration=1, search_default_filter_not_completed=1)
        return action

    @api.model
    def web_search_read(self, *args, **kwargs):
        if not self.env.context.get('skip_probation_sync'):
            try:
                self.with_context(skip_probation_sync=True)._auto_sync_eligible_probations()
            except Exception as e:
                _logger.warning("Probation auto-sync in web_search_read failed: %s", e)

        # Enforce exclusion of completed probations by default unless explicitly searched
        domain = kwargs.get('domain')
        if domain is None and args:
            domain = args[0]
        domain = list(domain) if domain else []

        has_state_filter = any(
            isinstance(term, (list, tuple)) and len(term) >= 2 and term[0] == 'state'
            for term in domain
        )
        if not has_state_filter:
            domain.append(('state', 'not in', ('completed', 'terminated')))
            if 'domain' in kwargs or not args:
                kwargs['domain'] = domain
            else:
                args = (domain,) + args[1:]

        return super().web_search_read(*args, **kwargs)

    def action_populate_criteria(self):
        """Populate evaluation criteria from master data (emp.probation.criteria)."""
        CriteriaMaster = self.env["emp.probation.criteria"]
        all_criteria = CriteriaMaster.search([], order="id asc")
        for rec in self:
            existing_criteria = rec.criteria_line_ids.mapped("criteria_id")
            to_add = all_criteria - existing_criteria
            lines = [(0, 0, {
                "criteria_id": c.id,
                "coefficient": c.coefficient or 1,
                "rating": "3",
            }) for c in to_add]
            if lines:
                rec.write({"criteria_line_ids": lines})

    def action_start(self):
        for rec in self:
            if not rec.probation_start_date:
                raise ValidationError(_("Please set the Probation Start Date before starting probation."))
            if not rec.criteria_line_ids:
                rec.action_populate_criteria()
            rec.state = "in_progress"
            rec.message_post(body=_("Probation started for %s.") % rec.employee_id.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Started'),
                'message': _('Probation period is now In Progress.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    def _notify_supervisor(self, body):
        self.ensure_one()
        if self.supervisor_id and self.supervisor_id.user_id and self.supervisor_id.user_id.partner_id:
            partner = self.supervisor_id.user_id.partner_id
            channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
            channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

    def action_notify_supervisor(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            if rec.notification_sent:
                continue
            prob_url = f"{base_url.rstrip('/')}/web#id={rec.id}&model=hr.employee.probation&view_type=form" if base_url else f"/web#id={rec.id}&model=hr.employee.probation&view_type=form"
            sup_name = rec.supervisor_id.name if rec.supervisor_id else _("Supervisor")
            emp_name = rec.employee_id.name if rec.employee_id else ""
            pos_name = rec.job_position_id.name if rec.job_position_id else ""
            end_d = str(rec.probation_end_date or "")
            body = Markup(
                f"<p>Dear <b>{escape(sup_name)}</b>,</p>"
                f"<p>This is a reminder that the probation period of <b>{escape(emp_name)}</b> ({escape(pos_name)}) is due to end on <b>{escape(end_d)}</b>.</p>"
                f"<p>Please complete the Performance Evaluation Criteria Form (Bunna Bank S.C.) and record the outcome (Satisfactory / Unsatisfactory / Extension) before that date.</p>"
                f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                f"<a href='{prob_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                f"👉 Open Probation Performance Evaluation"
                f"</a>"
                f"</div>"
                f"<p>Thank you.</p>"
            )
            rec._notify_supervisor(body)
            rec.message_post(body=_("Supervisor notified of upcoming probation end date."))
            rec.write({
                "notification_sent": True,
                "notification_date": fields.Datetime.now(),
                "state": "notified",
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Notified'),
                'message': _('Supervisor has been notified successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    @api.model
    def _cron_notify_upcoming_probation_end(self):
        target_date = fields.Date.context_today(self) + timedelta(days=NOTIFICATION_DAYS_URGENT)
        records = self.search([
            ("state", "in", ["draft", "in_progress"]),
            ("notification_sent", "=", False),
            ("outcome", "=", "pending"),
            ("probation_end_date", "<=", target_date),
        ])
        records.action_notify_supervisor()

    def action_committee_evaluate(self):
        """Committee evaluation voting mechanism."""
        for rec in self:
            if not rec.delegation_team_ids:
                raise UserError(_("No delegation committee assigned for evaluation."))
            current_user = self.env.user
            found = False
            for member in rec.delegation_team_ids:
                if member.status == "unavailable":
                    if member.alternate_committee_member == current_user:
                        member.approve = True
                        found = True
                        break
                elif member.employee_name == current_user:
                    member.approve = True
                    found = True
                    break
            if not found:
                raise UserError(_("You are not assigned as an active or alternate committee member for this probation."))

            all_approved = all(m.approve for m in rec.delegation_team_ids)
            if all_approved:
                rec.write({"committee_evaluated": True, "state": "evaluated"})
                rec.message_post(body=_("Committee evaluation complete. All members have approved."))
            else:
                rec.message_post(body=_("Committee vote registered by %s.") % current_user.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Committee Vote Registered'),
                'message': _('Evaluation vote saved successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    def action_extend_probation(self):
        for rec in self:
            if rec.extension_days <= 0:
                raise UserError(_("Please specify the number of extension days (e.g. 30 days)."))
            if not rec.extension_reason:
                raise UserError(_("Please provide a business justification for the probation extension."))
            rec.write({
                "is_extended": True,
                "outcome": "extended",
                "state": "extended",
                "notification_sent": False,
            })
            rec.message_post(body=_(
                "Probation extended by %d days. Reason: %s. New end date: %s"
            ) % (rec.extension_days, rec.extension_reason, rec.probation_end_date))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Extended'),
                'message': _('Probation period extended.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_record_outcome(self):
        """Record final probation outcome and execute HR contract updates (Confirmation or Termination)."""
        for rec in self:
            if rec.outcome == "pending":
                raise UserError(_("Please select an Outcome (Satisfactory or Unsatisfactory)."))

            today = fields.Date.context_today(self)
            rec.write({
                "outcome_date": today,
            })

            if rec.outcome == "satisfactory":
                rec.sudo().state = "completed"
                rec.sudo().recommend_permanent = "yes"
                if "hr.version" in self.env:
                    contracts = self.env["hr.version"].sudo().search([("employee_id", "=", rec.employee_id.id)])
                    if contracts:
                        contracts.sudo().write({"approval_status": "approved", "state": "open"})
                if hasattr(rec.employee_id, "employee_type"):
                    sel_keys = [k for k, _ in rec.employee_id._fields["employee_type"]._description_selection(self.env)]
                    target_key = "employee" if "employee" in sel_keys else ("permanent" if "permanent" in sel_keys else False)
                    if target_key:
                        rec.employee_id.sudo().write({"employee_type": target_key})
                rec.sudo().message_post(body=_("Probation completed successfully. Employee confirmed as permanent."))
                try:
                    rec.action_send_permanent_letter(raise_if_no_email=False)
                except Exception as send_err:
                    _logger.warning("Auto-send permanent letter on outcome completion warning: %s", send_err)

            elif rec.outcome == "unsatisfactory":
                rec.sudo().state = "terminated"
                rec.sudo().recommend_permanent = "no"
                if "hr.version" in self.env:
                    contracts = self.env["hr.version"].sudo().search([("employee_id", "=", rec.employee_id.id)])
                    if contracts:
                        contracts.sudo().write({"state": "cancel"})
                rec.sudo().message_post(body=_("Probation completed: Unsatisfactory outcome. Contract terminated."))

        outcome_label = dict(self[:1]._fields["outcome"].selection).get(self[:1].outcome, self[:1].outcome)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Outcome Recorded'),
                'message': _('Probation outcome recorded: %s.') % outcome_label,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


class HrEmployeeProbationCriteriaLine(models.Model):
    _name = "hr.employee.probation.criteria.line"
    _description = "Employee Probation Criteria Line"

    def write(self, vals):
        user = self.env.user
        emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if emp and any(
            (rec.probation_id.supervisor_id and rec.probation_id.supervisor_id.id == emp.id)
            or (rec.probation_id.employee_id and rec.probation_id.employee_id.coach_id and rec.probation_id.employee_id.coach_id.id == emp.id)
            or (rec.probation_id.employee_id and rec.probation_id.employee_id.parent_id and rec.probation_id.employee_id.parent_id.id == emp.id)
            for rec in self
        ):
            return super(HrEmployeeProbationCriteriaLine, self.sudo()).write(vals)
        return super().write(vals)

    probation_id = fields.Many2one("hr.employee.probation", string="Probation", ondelete="cascade", required=True)
    criteria_id = fields.Many2one("emp.probation.criteria", string="Evaluation Criteria", required=True)
    criteria_name = fields.Char(string="Criteria Name", related="criteria_id.emp_evaluation_criteria", readonly=True)
    description = fields.Text(string="Guideline Question / Scope", related="criteria_id.description", readonly=True)
    rating = fields.Selection([
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ], string="Rating (1-5)", default="3", required=True)
    coefficient = fields.Integer(string="Coefficient", related="criteria_id.coefficient", store=True, readonly=True)
    score = fields.Integer(string="Score", compute="_compute_score", store=True)

    @api.depends("rating", "coefficient")
    def _compute_score(self):
        for rec in self:
            if rec.rating and rec.coefficient:
                rec.score = int(rec.rating) * rec.coefficient
            else:
                rec.score = 0


class HrEmployeeProbationDelegationTeam(models.Model):
    _name = "hr.employee.probation.delegation.team"
    _description = "Employee Probation Delegation Team Member"

    probation_id = fields.Many2one("hr.employee.probation", string="Probation", ondelete="cascade", required=True)
    role = fields.Selection([
        ("chair_person", "Chair Person"),
        ("member", "Member"),
        ("secretary", "Secretary"),
        ("member_secretary", "Member & Secretary"),
    ], string="Role", default="member", required=True)
    employee_name = fields.Many2one("res.users", string="Committee Member", required=True)
    operating_unit = fields.Char(
        string="Work Unit", related="employee_name.employee_id.default_operating_unit_id.name", readonly=True
    )
    status = fields.Selection([
        ("active", "Active"), ("unavailable", "Unavailable")
    ], string="Status", default="active")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(
        string="Alt Work Unit", related="alternate_committee_member.employee_id.default_operating_unit_id.name", readonly=True
    )
    approve = fields.Boolean(string="Approved", default=False, readonly=True)


class HrEmployeeProbationSync(models.Model):
    _inherit = 'hr.employee'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get('skip_probation_sync'):
            try:
                self.env['hr.employee.probation'].sudo()._auto_sync_eligible_probations()
            except Exception as e:
                _logger.warning("Failed to auto-sync probation on employee creation: %s", e)
        return records
