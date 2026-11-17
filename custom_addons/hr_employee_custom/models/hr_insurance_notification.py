from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, date, timedelta, timezone
import pytz

class HrInsuranceNotification(models.Model):
    _name = 'hr.insurance.notification'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Insurance Incident Notification'
    _order = 'id desc'

    name = fields.Char(
        string='Notification Reference',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New')
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    requested_by_id = fields.Many2one(
        'res.users',
        string='Created By User',
        default=lambda self: self.env.user,
        readonly=True
    )
    department_id = fields.Many2one(
        'hr.department',
        related='employee_id.department_id',
        string='Department',
        store=True,
        readonly=True
    )
    job_id = fields.Many2one(
        'hr.job',
        related='employee_id.job_id',
        string='Position',
        store=True,
        readonly=True
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        related='employee_id.operating_unit_id',
        string='Branch / Operating Unit',
        store=True,
        readonly=True
    )
    contact_number = fields.Char(
        string='Contact Number',
        required=True,
        tracking=True,
        help="Primary contact phone number during the incident/recovery period."
    )

    # Accident Details (FR-INS-003)
    accident_date = fields.Date(
        string='Accident / Incident Date',
        required=True,
        tracking=True,
        default=fields.Date.today
    )
    HOUR_SELECTION = [(f"{i:02d}", f"{i:02d}") for i in range(1, 13)]
    MINUTE_SELECTION = [(f"{i:02d}", f"{i:02d}") for i in range(60)]
    @api.model
    def _get_current_ethiopian_time(self):
        """Get current local time in Ethiopia (Addis Ababa, UTC+3) in Ethiopian local 12-hour format:
        Standard 6:00 AM -> Ethiopian 12:00 (AM)
        Standard 7:00 AM -> Ethiopian 01:00 (AM)
        Standard 12:00 PM -> Ethiopian 06:00 (AM)
        Standard 1:00 PM -> Ethiopian 07:00 (PM)
        Standard 6:00 PM -> Ethiopian 12:00 (PM)
        """
        try:
            tz = pytz.timezone('Africa/Addis_Ababa')
            now_eth = datetime.now(tz)
        except Exception:
            now_eth = datetime.now(timezone(timedelta(hours=3)))
        
        std_hour = now_eth.hour
        minute = now_eth.minute
        
        eth_hour = (std_hour - 6) % 12
        if eth_hour == 0:
            eth_hour = 12
            
        period = 'AM' if eth_hour in (12, 1, 2, 3, 4, 5, 6) else 'PM'
        return f"{eth_hour:02d}", f"{minute:02d}", period

    @api.model
    def _default_accident_hour(self):
        hour, _, _ = self._get_current_ethiopian_time()
        return hour

    @api.model
    def _default_accident_minute(self):
        _, minute, _ = self._get_current_ethiopian_time()
        return minute

    @api.model
    def _default_accident_time_period(self):
        _, _, period = self._get_current_ethiopian_time()
        return period

    PERIOD_SELECTION = [
        ('AM', 'AM'),
        ('PM', 'PM'),
    ]

    accident_hour = fields.Selection(
        HOUR_SELECTION,
        string='Hour',
        default=_default_accident_hour,
        required=True,
        tracking=True,
        help="Hour in Ethiopian local time (12-hour cycle starting at 12:00 morning)."
    )
    accident_minute = fields.Selection(
        MINUTE_SELECTION,
        string='Minute',
        default=_default_accident_minute,
        required=True,
        tracking=True,
    )
    accident_time_period = fields.Selection(
        PERIOD_SELECTION,
        string='Period (AM / PM)',
        default=_default_accident_time_period,
        required=True,
        tracking=True,
        help="Period of the day: automatically sets to AM (12:00 - 06:00) or PM (07:00 - 12:00) based on Ethiopian local time."
    )
    accident_time = fields.Char(
        string='Accident / Incident Time',
        compute='_compute_accident_time',
        inverse='_inverse_accident_time',
        store=True,
        tracking=True,
        help="Full formatted time of the accident/incident."
    )
    accident_time_display = fields.Char(
        string='Accident Time',
        related='accident_time',
        store=True,
    )
    accident_place = fields.Char(
        string='Accident Location / Place',
        required=True,
        tracking=True
    )
    incident_description = fields.Text(
        string='Incident Description(When, Where, How ,etc)',
        required=True,
        tracking=True,
        help="Detailed explanation of how the accident or illness occurred (When, Where, How ,etc)."
    )
    hospital_name = fields.Char(
        string='Hospital / Health Facility Name',
        required=True,
        tracking=True
    )
    injury_type = fields.Selection([
        ('physical_injury', 'Physical Injury / Disability'),
        ('occupational_illness', 'Occupational Illness'),
        ('medical_emergency', 'Medical Emergency'),
        ('traffic_accident', 'Traffic / Vehicle Accident'),
        ('fatal_injury', 'Fatal Incident'),
        ('other', 'Other Incident / Illness')
    ], string='Type of Injury / Illness', required=True, tracking=True)

    # 30 Working Days Validation (FR-INS-002)
    submission_date = fields.Date(
        string='Submission Date',
        default=fields.Date.today,
        readonly=True,
        tracking=True
    )
    working_days_delay = fields.Integer(
        string='Working Days Delay',
        compute='_compute_working_days_delay',
        store=True,
        help="Number of working days between Accident Date and Submission Date."
    )
    is_late_submission = fields.Boolean(
        string='Late Submission (>30 Working Days)',
        compute='_compute_working_days_delay',
        store=True,
        tracking=True
    )
    late_justification = fields.Text(
        string='Mandatory Late Justification',
        tracking=True,
        help="Required justification when notification is submitted after 30 working days."
    )

    # Documents (FR-INS-004, FR-INS-005)
    document_ids = fields.One2many(
        'hr.insurance.document',
        'notification_id',
        string='Supporting Documents'
    )
    attachment = fields.Binary(
        string='Attachment (Base64)',
        attachment=True,
        help="Base64 encoded primary supporting document / incident attachment."
    )
    attachment_filename = fields.Char(
        string='Attachment Filename'
    )

    # Workflow & State Machine (FR-INS-006, FR-INS-007)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted (Pending POMD Review)'),
        ('under_review', 'Under POMD Review'),
        ('returned', 'Returned for Correction'),
        ('approved', 'Approved by POMD'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed')
    ], string='Status', default='draft', tracking=True, copy=False)

    reviewed_by_id = fields.Many2one(
        'res.users',
        string='Reviewed By (POMD)',
        readonly=True,
        tracking=True
    )
    review_date = fields.Datetime(
        string='Review Date',
        readonly=True,
        tracking=True
    )
    pomd_comments = fields.Text(
        string='POMD Review Comments',
        tracking=True
    )
    rejection_reason = fields.Text(
        string='Rejection Reason',
        readonly=True,
        tracking=True
    )
    return_reason = fields.Text(
        string='Return Reason',
        readonly=True,
        tracking=True
    )

    # Audit Trail (FR-INS-010)
    submitted_date = fields.Datetime(string='Submitted Date', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved Date', readonly=True, copy=False)
    rejected_date = fields.Datetime(string='Rejected Date', readonly=True, copy=False)
    returned_date = fields.Datetime(string='Returned Date', readonly=True, copy=False)

    # Record Integration (FR-INS-009)
    insurance_record_id = fields.Many2one(
        'hr.insurance.record',
        string='Created Insurance Record',
        readonly=True,
        copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code('hr.insurance.notification') or False
                if not seq:
                    year = date.today().year
                    count = self.sudo().search_count([]) + 1
                    vals['name'] = f'INS/{year}/{count:05d}'
                else:
                    vals['name'] = seq
            if 'employee_id' in vals and not vals.get('contact_number'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                if emp:
                    vals['contact_number'] = emp.mobile_phone or emp.work_phone or ''
            if 'accident_hour' in vals and not vals.get('accident_time_period'):
                try:
                    h = int(vals['accident_hour'])
                    vals['accident_time_period'] = 'AM' if h in (12, 1, 2, 3, 4, 5, 6) else 'PM'
                except (ValueError, TypeError):
                    pass
        return super(HrInsuranceNotification, self).create(vals_list)

    def write(self, vals):
        if 'accident_hour' in vals and 'accident_time_period' not in vals:
            try:
                h = int(vals['accident_hour'])
                vals['accident_time_period'] = 'AM' if h in (12, 1, 2, 3, 4, 5, 6) else 'PM'
            except (ValueError, TypeError):
                pass
        return super(HrInsuranceNotification, self).write(vals)

    @api.onchange('accident_hour')
    def _onchange_accident_hour(self):
        """Automatically set period to AM (12:00-06:00) or PM (07:00-12:00) based on Ethiopian local time when hour is selected."""
        if self.accident_hour:
            try:
                h = int(self.accident_hour)
                if h in (12, 1, 2, 3, 4, 5, 6):
                    self.accident_time_period = 'AM'
                elif h in (7, 8, 9, 10, 11):
                    self.accident_time_period = 'PM'
            except (ValueError, TypeError):
                pass

    @api.depends('accident_hour', 'accident_minute', 'accident_time_period')
    def _compute_accident_time(self):
        period_labels = {
            'AM': 'AM',
            'PM': 'PM',
            'morning': 'AM',
            'afternoon': 'PM',
        }
        for rec in self:
            h = rec.accident_hour or '09'
            m = rec.accident_minute or '00'
            p = period_labels.get(rec.accident_time_period, 'AM')
            rec.accident_time = f"{h}:{m} {p}"

    def _inverse_accident_time(self):
        for rec in self:
            if rec.accident_time:
                parts = rec.accident_time.strip().split()
                time_str = parts[0] if parts else ''
                period_str = parts[1].upper() if len(parts) > 1 else ''
                if ':' in time_str:
                    h, m = time_str.split(':')[:2]
                    try:
                        int_h = int(h)
                        int_m = int(m)
                        if 1 <= int_h <= 12:
                            rec.accident_hour = f"{int_h:02d}"
                        elif int_h > 12:
                            rec.accident_hour = f"{(int_h - 12):02d}"
                        elif int_h == 0:
                            rec.accident_hour = '12'
                        if 0 <= int_m <= 59:
                            rec.accident_minute = f"{int_m:02d}"
                    except ValueError:
                        pass
                if 'PM' in period_str or 'AFTERNOON' in period_str:
                    rec.accident_time_period = 'PM'
                elif 'AM' in period_str or 'MORNING' in period_str:
                    rec.accident_time_period = 'AM'
                elif rec.accident_hour:
                    try:
                        h = int(rec.accident_hour)
                        rec.accident_time_period = 'AM' if h in (12, 1, 2, 3, 4, 5, 6) else 'PM'
                    except ValueError:
                        rec.accident_time_period = 'AM'

    @api.depends('accident_date', 'submission_date')
    def _compute_working_days_delay(self):
        for rec in self:
            if not rec.accident_date:
                rec.working_days_delay = 0
                rec.is_late_submission = False
                continue

            sub_dt = rec.submission_date or date.today()
            if rec.accident_date > sub_dt:
                rec.working_days_delay = 0
                rec.is_late_submission = False
                continue

            cur_dt = rec.accident_date + timedelta(days=1)
            work_days = 0
            while cur_dt <= sub_dt:
                if cur_dt.weekday() < 5:  # Mon-Fri
                    work_days += 1
                cur_dt += timedelta(days=1)

            rec.working_days_delay = work_days
            rec.is_late_submission = work_days > 30

    @api.constrains('state', 'is_late_submission', 'late_justification', 'document_ids', 'attachment')
    def _check_submission_validations(self):
        for rec in self:
            if rec.state in ['submitted', 'under_review', 'approved']:
                if not rec.accident_date or not rec.accident_time or not rec.accident_place or not rec.hospital_name or not rec.incident_description or not rec.injury_type or not rec.contact_number:
                    raise ValidationError(_("All mandatory fields (Accident Date, Time, Location, Hospital Name, Injury Type, Contact Number, and Incident Description) must be provided before submission."))

                if rec.is_late_submission and (not rec.late_justification or not rec.late_justification.strip()):
                    raise ValidationError(_(
                        "This insurance notification is submitted after %s working days (exceeding the 30-working-day limit).\n"
                        "A mandatory justification explaining the delay is required prior to submission."
                    ) % rec.working_days_delay)

                if not rec.document_ids and not rec.attachment:
                    raise ValidationError(_("At least one supporting document (e.g., Medical Certificate, Police Report, Medical Invoice) or attachment must be uploaded prior to submission."))

    def action_submit(self):
        for rec in self:
            if rec.state not in ['draft', 'returned']:
                raise UserError(_("Only draft or returned notifications can be submitted."))
            
            # Perform pre-submission validations before state mutation
            if not rec.accident_date or not rec.accident_time or not rec.accident_place or not rec.hospital_name or not rec.incident_description or not rec.injury_type or not rec.contact_number:
                raise ValidationError(_("All mandatory fields (Accident Date, Time, Location, Hospital Name, Injury Type, Contact Number, and Incident Description) must be provided before submission."))

            if rec.is_late_submission and (not rec.late_justification or not rec.late_justification.strip()):
                raise ValidationError(_(
                    "This insurance notification is submitted after %s working days (exceeding the 30-working-day limit).\n"
                    "A mandatory justification explaining the delay is required prior to submission."
                ) % rec.working_days_delay)

            if not rec.document_ids and not rec.attachment:
                raise ValidationError(_("At least one supporting document (e.g., Medical Certificate, Police Report, Medical Invoice) or attachment must be uploaded prior to submission."))

            # Auto-create supporting document record if user attached a file directly
            if rec.attachment and not rec.document_ids:
                self.env['hr.insurance.document'].create({
                    'notification_id': rec.id,
                    'document_type': 'other',
                    'name': rec.attachment_filename or _('Supporting Document'),
                    'file': rec.attachment,
                    'filename': rec.attachment_filename or 'attachment.pdf',
                })

            rec.submission_date = date.today()
            rec.submitted_date = fields.Datetime.now()
            rec.write({'state': 'submitted'})
            rec._notify_pomd_officers()
            rec._notify_employee_state_change(_("SUBMITTED for POMD review"))

    def action_under_review(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_("Only submitted notifications can be placed under review."))
            rec.write({
                'state': 'under_review',
                'reviewed_by_id': self.env.user.id,
                'review_date': fields.Datetime.now()
            })
            rec._notify_employee_state_change(_("placed UNDER REVIEW by POMD"))

    def action_approve(self):
        for rec in self:
            if rec.state not in ['submitted', 'under_review']:
                raise UserError(_("Only submitted or under-review notifications can be approved."))
            
            rec_vals = {
                'employee_id': rec.employee_id.id,
                'notification_id': rec.id,
                'name': f"INS-REC/{rec.name}",
                'accident_date': rec.accident_date,
                'injury_type': rec.injury_type,
                'hospital_name': rec.hospital_name,
                'incident_description': rec.incident_description,
                'approval_date': fields.Datetime.now(),
                'approved_by_id': self.env.user.id,
                'claim_status': 'pending_claim'
            }
            ins_rec = self.env['hr.insurance.record'].sudo().create(rec_vals)

            rec.write({
                'state': 'approved',
                'approved_date': fields.Datetime.now(),
                'reviewed_by_id': self.env.user.id,
                'review_date': fields.Datetime.now(),
                'insurance_record_id': ins_rec.id
            })
            rec._notify_employee_state_change(_("APPROVED by POMD. Official insurance record %s has been created.") % ins_rec.name)

    def action_reset_to_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def _get_pomd_partners(self):
        partners = self.env['res.partner']
        for xmlid in ['hr.group_hr_user', 'hr.group_hr_manager']:
            g = self.env.ref(xmlid, raise_if_not_found=False)
            if g and g.user_ids:
                partners |= g.user_ids.mapped('partner_id')
        return partners

    def _notify_pomd_officers(self):
        for rec in self:
            pomd_partners = rec._get_pomd_partners()
            if not pomd_partners:
                continue

            msg = _(
                "Insurance Incident Notification %s has been SUBMITTED by %s.\n"
                "Accident Date: %s | Injury Type: %s | Late Submission: %s"
            ) % (
                rec.name,
                rec.employee_id.name if rec.employee_id else '',
                rec.accident_date,
                dict(rec._fields['injury_type'].selection).get(rec.injury_type, ''),
                _("Yes (%s days delay)") % rec.working_days_delay if rec.is_late_submission else _("No")
            )
            subj = _("Insurance Notification Submitted: %s") % rec.name

            # 1. Post message on chatter with elevated sudo
            msg_record = rec.sudo().message_post(
                body=msg,
                subject=subj,
                partner_ids=pomd_partners.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            if msg_record:
                notifs = self.env['mail.notification'].sudo().search([
                    ('mail_message_id', '=', msg_record.id),
                    ('res_partner_id', 'in', pomd_partners.ids)
                ])
                if notifs:
                    notifs.sudo().write({'notification_type': 'inbox', 'is_read': False})

            # 2. Post Direct Message into Discuss App Direct Chat Channel for each POMD Officer
            sender_partner = self.env.user.partner_id
            for p in pomd_partners:
                if p and p != sender_partner:
                    try:
                        partners = list({p.id, sender_partner.id})
                        if len(partners) == 2:
                            ch = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=partners)
                            if ch:
                                ch.sudo().message_post(
                                    body=msg,
                                    message_type='comment',
                                    subtype_xmlid='mail.mt_comment',
                                )
                    except Exception:
                        pass

            # 3. Schedule Activity for POMD Officers
            act_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            for p in pomd_partners:
                u = p.user_ids and p.user_ids[0]
                if u and u != self.env.user:
                    try:
                        rec.sudo().activity_schedule(
                            activity_type_id=act_type.id if act_type else False,
                            summary=_("Insurance Notification Review: %s") % rec.name,
                            note=msg,
                            user_id=u.id
                        )
                    except Exception:
                        pass

    def _notify_employee_state_change(self, action_desc):
        for rec in self:
            emp_partner = rec.employee_id.user_id.partner_id if (rec.employee_id and rec.employee_id.user_id) else False
            if not emp_partner:
                continue

            msg = _("Your Insurance Notification %s has been %s.") % (rec.name, action_desc)
            subj = _("Insurance Notification Status Update: %s") % rec.name

            # 1. Post message on chatter with elevated sudo
            msg_record = rec.sudo().message_post(
                body=msg,
                subject=subj,
                partner_ids=[emp_partner.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            if msg_record:
                notifs = self.env['mail.notification'].sudo().search([
                    ('mail_message_id', '=', msg_record.id),
                    ('res_partner_id', '=', emp_partner.id)
                ])
                if notifs:
                    notifs.sudo().write({'notification_type': 'inbox', 'is_read': False})

            # 2. Post Direct Message into Discuss App Direct Chat Channel
            sender_partner = self.env.user.partner_id
            if emp_partner != sender_partner:
                try:
                    partners = list({emp_partner.id, sender_partner.id})
                    if len(partners) == 2:
                        ch = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=partners)
                        if ch:
                            ch.sudo().message_post(
                                body=msg,
                                message_type='comment',
                                subtype_xmlid='mail.mt_comment',
                            )
                except Exception:
                    pass


class HrInsuranceDocument(models.Model):
    _name = 'hr.insurance.document'
    _description = 'Insurance Supporting Document'

    notification_id = fields.Many2one(
        'hr.insurance.notification',
        string='Insurance Notification',
        required=True,
        ondelete='cascade'
    )
    document_type = fields.Selection([
        ('medical_cert', 'Medical Certificate / Discharge Summary'),
        ('police_report', 'Police Report (Traffic / Accident)'),
        ('medical_invoice', 'Medical Invoices / Receipts'),
        ('referral_letter', 'Referral Letter'),
        ('other', 'Other Supporting Evidence')
    ], string='Document Type', required=True, default='medical_cert')
    name = fields.Char(string='Document Description / Title', required=True)
    file = fields.Binary(
        string='Attachment File',
        required=True,
        attachment=True,
        help="Base64-encoded file content."
    )
    filename = fields.Char(string='File Name')
    attachment = fields.Binary(
        string='Attachment (Base64)',
        related='file',
        readonly=False,
        store=True,
        attachment=True,
        help="Base64 encoded binary attachment (alias of file)."
    )
    attachment_filename = fields.Char(
        string='Attachment Filename',
        related='filename',
        readonly=False,
        store=True
    )
    notes = fields.Text(string='Notes / Comments')


class HrInsuranceRecord(models.Model):
    _name = 'hr.insurance.record'
    _inherit = ['mail.thread']
    _description = 'Employee Insurance Approved Record'
    _order = 'id desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade', tracking=True)
    notification_id = fields.Many2one('hr.insurance.notification', string='Source Incident Notification', readonly=True)
    name = fields.Char(string='Record Reference', required=True, tracking=True)
    accident_date = fields.Date(string='Accident Date', required=True, tracking=True)
    injury_type = fields.Selection([
        ('physical_injury', 'Physical Injury / Disability'),
        ('occupational_illness', 'Occupational Illness'),
        ('medical_emergency', 'Medical Emergency'),
        ('traffic_accident', 'Traffic / Vehicle Accident'),
        ('fatal_injury', 'Fatal Incident'),
        ('other', 'Other Incident / Illness')
    ], string='Injury / Illness Type', required=True, tracking=True)
    hospital_name = fields.Char(string='Hospital Name')
    incident_description = fields.Text(string='Incident Details')
    approval_date = fields.Datetime(string='POMD Approval Date', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)

    claim_status = fields.Selection([
        ('pending_claim', 'Pending Underwriter Claim'),
        ('submitted_to_insurer', 'Submitted to Insurance Company'),
        ('claimed', 'Claimed / Reimbursed'),
        ('rejected_by_insurer', 'Rejected by Insurance Company'),
        ('closed', 'Closed')
    ], string='Insurance Claim Status', default='pending_claim', tracking=True)

    claim_amount = fields.Float(string='Claim Amount (ETB)', tracking=True)
    reimbursed_amount = fields.Float(string='Reimbursed Amount (ETB)', tracking=True)
    reimbursement_date = fields.Date(string='Reimbursement Date', tracking=True)
    notes = fields.Text(string='Claim Notes / Remarks')
