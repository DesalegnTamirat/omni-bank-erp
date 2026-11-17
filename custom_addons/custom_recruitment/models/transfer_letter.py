# -*- coding: utf-8 -*-
import base64
import logging
import os
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)


class TransferLetter(models.Model):
    """
    Official Lateral Transfer Letter (Placement & Handover Notice) for Bunna Bank S.C.
    Replicates the official template with current vs target placement, salary/grade maintenance,
    handover instructions, and release directives.
    """
    _name = 'transfer.letter'
    _description = 'Bunna Bank Lateral Transfer Letter'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'letter_date desc, id desc'

    name = fields.Char(
        string='Letter Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent to Employee'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    transfer_type = fields.Selection([
        ('transfer', 'Transfer'),
        ('lateral', 'Lateral Transfer'),
    ], string='Transfer Type', compute='_compute_transfer_type', store=True, readonly=False, tracking=True)

    @api.depends('current_position_name', 'new_position_name', 'current_work_unit_name', 'new_work_unit_name')
    def _compute_transfer_type(self):
        for rec in self:
            cur_pos = (rec.current_position_name or '').strip().lower()
            new_pos = (rec.new_position_name or '').strip().lower()
            for suf in [' (managerial)', ' (non managerial)', ' [managerial]', ' [non managerial]']:
                cur_pos = cur_pos.replace(suf, '').strip()
                new_pos = new_pos.replace(suf, '').strip()
            if cur_pos and new_pos and cur_pos == new_pos:
                rec.transfer_type = 'transfer'
            else:
                rec.transfer_type = 'lateral'

    def get_letter_subject(self):
        self.ensure_one()
        if self.transfer_type == 'transfer':
            return 'Subject: - Transfer'
        return 'Subject: - Lateral Transfer'

    def get_letter_document_title(self):
        self.ensure_one()
        if self.transfer_type == 'transfer':
            return _('Transfer Letter')
        return _('Lateral Transfer Letter')

    acceptance_status = fields.Selection([
        ('pending', 'Pending Acceptance'),
        ('accepted', 'Accepted'),
        ('rejected', 'Refused / Declined'),
    ], string="Transfer Acceptance Status", default='pending')
    acceptance_date = fields.Datetime(string="Acceptance / Response Date", readonly=True)
    rejection_reason = fields.Text(string="Refusal / Decline Reason")

    def action_open_offer_response_wizard(self):
        """Opens the interactive Offer Response wizard (Accept or Decline) for the candidate."""
        self.ensure_one()
        return {
            'name': _('Respond to Transfer Offer'),
            'type': 'ir.actions.act_window',
            'res_model': 'internal.selection.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transfer_letter_id': self.id,
                'default_transfer_request_id': self.transfer_request_id.id if self.transfer_request_id else False,
                'default_response_action': 'accept',
            }
        }

    def action_accept_transfer(self):
        """Employee accepts transfer letter."""
        for rec in self:
            now = fields.Datetime.now()
            rec.write({
                'acceptance_status': 'accepted',
                'acceptance_date': now,
            })
            if rec.transfer_request_id:
                try:
                    rec.transfer_request_id.sudo().action_accept_transfer()
                except Exception as e:
                    _logger.warning("Could not sync accept to transfer request: %s", e)

            # Close any pending mail.activity for this letter
            activities = self.env['mail.activity'].sudo().search([
                ('res_model', '=', 'transfer.letter'),
                ('res_id', '=', rec.id),
            ])
            for act in activities:
                try:
                    act.sudo().action_feedback(feedback=_("Transfer letter accepted by employee on %s") % fields.Date.today())
                except Exception:
                    pass

            rec.message_post(
                body=_("Lateral transfer letter ACCEPTED by employee on %s.") % fields.Date.today(),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Accepted'),
                'message': _('Lateral transfer letter has been marked as ACCEPTED.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_decline_transfer(self):
        """Opens decline wizard to capture refusal reason."""
        self.ensure_one()
        return {
            'name': _('Decline / Refuse Transfer Letter'),
            'type': 'ir.actions.act_window',
            'res_model': 'internal.selection.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transfer_letter_id': self.id,
            }
        }

    def confirm_decline_transfer(self, reason):
        """Executed by decline wizard when employee declines transfer letter."""
        for rec in self:
            now = fields.Datetime.now()
            rec.write({
                'acceptance_status': 'rejected',
                'acceptance_date': now,
                'rejection_reason': reason,
            })
            if rec.transfer_request_id:
                rec.transfer_request_id.confirm_decline_transfer(reason)
            rec.message_post(body=_("Lateral transfer letter DECLINED / REFUSED by employee.<br/><b>Reason:</b> %s") % reason)
        return True

    # ── Linked Records ────────────────────────────────────────────────
    transfer_request_id = fields.Many2one(
        'employee.transfer.request', string='Transfer Request', tracking=True
    )
    minutes_id = fields.Many2one(
        'transfer.committee.minutes', string='Committee Minutes', tracking=True
    )
    vacancy_id = fields.Many2one(
        'job.vacancy', string='Job Vacancy', tracking=True
    )
    selected_candidate_id = fields.Many2one(
        'new.internal.recruitment.selected.candidates', string='Selected Candidate Line', tracking=True
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Transferred Employee', required=True, tracking=True
    )

    # ── Recipient Details ──────────────────────────────────────────────
    employee_title = fields.Selection([
        ('Ato', 'Ato'),
        ('W/ro', 'W/ro'),
        ('W/t', 'W/t'),
    ], string='Salutation', default='Ato', required=True)
    employee_name = fields.Char(
        string='Employee Name', required=True, tracking=True
    )
    employee_email = fields.Char(
        string='Employee Email', compute='_compute_employee_email', store=True, readonly=False
    )
    employee_id_number = fields.Char(
        string='ID No', help='Employee Badge ID or National ID'
    )
    employee_address = fields.Char(
        string='Location / City', default='Addis Ababa'
    )

    # ── Transfer & Placement Details ───────────────────────────────────
    letter_date = fields.Date(
        string='Letter Date', default=fields.Date.context_today, required=True
    )
    effective_date = fields.Date(
        string='Date of Transfer (Effective Date)', default=fields.Date.context_today, required=True,
        help='Official date on which the transfer takes effect.'
    )

    current_work_unit_name = fields.Char(
        string='Current Work Unit', required=True,
        help='Work unit / branch where employee is currently stationed.'
    )
    current_position_name = fields.Char(
        string='Current Position', required=True,
        help='Current job position held.'
    )

    new_work_unit_name = fields.Char(
        string='New Work Unit (Target)', required=True,
        help='New work unit / branch transferred to.'
    )
    new_position_name = fields.Char(
        string='New Position (Target)', required=True,
        help='New job position assigned.'
    )

    job_grade_name = fields.Char(
        string='Maintained Job Grade', required=True,
        help='Job grade maintained upon transfer.'
    )
    monthly_salary = fields.Float(
        string='Maintained Monthly Salary (Birr)', digits=(16, 2), required=True, tracking=True
    )

    # ── Signatory & Distribution ───────────────────────────────────────
    signatory_config_id = fields.Many2one(
        'recruitment.signatory.config',
        string='Signatory & Stamp Configuration',
        help='Configuration providing the official signature, stamp, and executive name'
    )
    signatory_name = fields.Char(
        string='Signatory Name',
        default='Abayneh Habtie',
        tracking=True
    )
    signatory_title = fields.Char(
        string='Authorized Signatory',
        default='People Operation Management Directorate'
    )
    signatory_company = fields.Char(
        string='Company', default='Bunna Bank S.C.'
    )
    cc_extra_work_units = fields.Char(
        string='Other Respective Work Units',
        help='Additional work units / departments to be notified.'
    )

    # ── Computations ───────────────────────────────────────────────────
    @api.depends('employee_id')
    def _compute_employee_email(self):
        for rec in self:
            if rec.employee_id:
                rec.employee_email = (rec.employee_id.work_email or '').strip()
            elif not rec.employee_email:
                rec.employee_email = False

    def get_formatted_employee_name(self):
        self.ensure_one()
        title = self.employee_title or 'Ato'
        name = (self.employee_name or (self.employee_id.name if self.employee_id else '')).strip()
        for t in ['Ato', 'W/ro', 'W/t', 'Dr.', 'Mr.', 'Mrs.', 'Ms.']:
            if name.lower().startswith(t.lower() + ' '):
                name = name[len(t):].strip()
                break
        return f"{title} {name}" if name else title

    def get_salutation_title_and_first_name(self):
        self.ensure_one()
        formatted = self.get_formatted_employee_name()
        parts = formatted.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1]}"
        return formatted

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

    def get_transfer_letter_cc_lines(self):
        """Returns list of CC recipient work units matching the official transfer letter."""
        self.ensure_one()
        lines = []
        if self.current_work_unit_name:
            lines.append(self.current_work_unit_name)
        if self.new_work_unit_name and self.new_work_unit_name != self.current_work_unit_name:
            lines.append(self.new_work_unit_name)
        lines.append("IT Security Management Directorate")
        if self.cc_extra_work_units:
            for extra in self.cc_extra_work_units.split(","):
                extra_clean = extra.strip()
                if extra_clean and extra_clean not in lines:
                    lines.append(extra_clean)
        return lines

    def get_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        sig = self.signatory_config_id
        if not sig and 'recruitment.signatory.config' in self.env:
            sig = self.env['recruitment.signatory.config'].get_signatory_for_unit(
                work_unit=self.new_work_unit_name, doc_type='transfer_letter'
            )
        if sig and hasattr(sig, 'get_letter_signature_data'):
            data = sig.get_letter_signature_data()
            if self.signatory_name:
                data['signatory_name'] = self.signatory_name
            if self.signatory_title:
                data['signatory_title'] = self.signatory_title
            if self.signatory_company:
                data['signatory_company'] = self.signatory_company
            return data
        legacy = self.get_signature_stamp_base64()
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': legacy,
            'signatory_name': self.signatory_name or 'Abayneh Markos',
            'signatory_title': self.signatory_title or 'People Operation Management Directorate',
            'signatory_company': self.signatory_company or 'Bunna Bank S.C.',
        }

    def get_signature_stamp_base64(self):
        """Returns Base64 data URI of the authorized signature & Bunna Bank rubber stamp."""
        self.ensure_one()
        if self.signatory_config_id:
            b64 = self.signatory_config_id.get_signature_stamp_base64()
            if b64:
                return b64

        active_sig = self.env['recruitment.signatory.config'].get_signatory_for_unit(
            work_unit=self.new_work_unit_name, doc_type='transfer_letter'
        )
        if active_sig:
            b64 = active_sig.get_signature_stamp_base64()
            if b64:
                return b64

        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    # ── CRUD & Sequence ───────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('signatory_config_id'):
                target_unit = vals.get('new_work_unit_name')
                if not target_unit and vals.get('transfer_request_id'):
                    tr = self.env['employee.transfer.request'].browse(vals['transfer_request_id'])
                    if tr.exists():
                        target_unit = tr.target_vacancy_id.operating_unit_id or tr.current_operating_unit_id

                active_sig = self.env['recruitment.signatory.config'].get_signatory_for_unit(
                    work_unit=target_unit, doc_type='transfer_letter'
                )
                if active_sig:
                    vals['signatory_config_id'] = active_sig.id
                    if not vals.get('signatory_name'):
                        vals['signatory_name'] = active_sig.signatory_name
                    if not vals.get('signatory_title'):
                        vals['signatory_title'] = active_sig.signatory_title
                    if not vals.get('signatory_company'):
                        vals['signatory_company'] = active_sig.signatory_company

            if vals.get('name', _('New')) == _('New'):
                seq_code = 'bunna.lateral.transfer.letter'
                seq_name = self.env['ir.sequence'].next_by_code(seq_code)
                if not seq_name:
                    year = fields.Date.today().year
                    month = f"{fields.Date.today().month:02d}"
                    count = self.env['ir.sequence'].search_count([('code', '=', seq_code)]) + 1
                    seq_name = f"-BB/POMD/{count:02d}/{month}/{year}"
                vals['name'] = seq_name
        records = super().create(vals_list)
        # Link back to transfer request if applicable
        for rec in records:
            if rec.transfer_request_id and not rec.transfer_request_id.transfer_letter_id:
                rec.transfer_request_id.sudo().write({'transfer_letter_id': rec.id})
            if rec.selected_candidate_id and not rec.selected_candidate_id.transfer_letter_id:
                rec.selected_candidate_id.sudo().write({'transfer_letter_id': rec.id})
        return records

    # ── Workflow Actions ───────────────────────────────────────────────
    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_print_transfer_letter(self):
        self.ensure_one()
        return self.env.ref('custom_recruitment.action_report_lateral_transfer_letter').report_action(self)

    def action_send_transfer_letter(self):
        """Sends the lateral transfer letter with official PDF attachment to the employee's email,
        dispatches Discuss notifications, schedules systray activity, and sends Discuss DM."""
        self.ensure_one()
        email_target = (self.employee_id.work_email or self.employee_email or '').strip()
        if not email_target:
            raise UserError(_(
                "Employee Work Email Missing!\n\n"
                "Cannot send Lateral Transfer Letter because no official work email was found for %s.\n"
                "Please ensure the employee has a valid Work Email configured in their employee profile before sending."
            ) % (self.employee_name or self.employee_id.name or 'this employee'))

        # Determine employee user and partner
        emp_user = self.employee_id.user_id or self.env['res.users'].sudo().search([
            '|', ('partner_id.email', '=', email_target), ('login', '=', email_target)
        ], limit=1)
        emp_partner = emp_user.partner_id if emp_user else (self.employee_id.address_home_id or False)
        if not emp_partner:
            emp_partner = self.env['res.partner'].sudo().search([('email', '=', email_target)], limit=1)
            if not emp_partner:
                emp_partner = self.env['res.partner'].sudo().create({
                    'name': self.employee_name or self.employee_id.name,
                    'email': email_target,
                })

        # 1. Generate PDF attachment using QWeb report
        report = self.env.ref('custom_recruitment.action_report_lateral_transfer_letter', raise_if_not_found=False)
        attachments = []
        if report:
            pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
                'custom_recruitment.action_report_lateral_transfer_letter', [self.id]
            )
            clean_name = (self.employee_name or 'Employee').replace(' ', '_')
            doc_title = self.get_letter_document_title().replace(' ', '_')
            attachment = self.env['ir.attachment'].sudo().create({
                'name': f"{doc_title}_{clean_name}.pdf",
                'type': 'binary',
                'raw': pdf_content,
                'res_model': 'transfer.letter',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(attachment.id)

        # 2. Compose Email Content
        salutation = self.get_salutation_title_and_first_name()
        eff_date = self.effective_date.strftime('%B %d, %Y') if self.effective_date else 'the transfer date'

        message_body = _(
            "<div style='font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222222; line-height: 1.6; max-width: 650px;'>"
            "<p>Dear <strong>%s</strong>,</p>"
            "<p>Please find attached your official <strong>Lateral Transfer Letter</strong> from Bunna Bank S.C.<br>"
            "You are transferred to <strong>%s</strong> effective <strong>%s</strong> in the position of <strong>%s</strong>.</p>"
            "<p>Please review the attached letter for handover and reporting instructions.</p>"
            "<p>Wishing you success in your new assignment!</p>"
            "<br>"
            "<p style='margin-bottom: 2px;'>Sincerely yours,</p>"
            "<strong>%s</strong><br>"
            "<strong>%s</strong>"
            "</div>"
        ) % (salutation, self.new_work_unit_name, eff_date, self.new_position_name, self.signatory_title, self.signatory_company)

        # 3. Create mail and dispatch with authorized sender to pass SMTP verification
        default_from = self.env['ir.config_parameter'].sudo().get_param('mail.default.from') or 'natnael.negussie@bunnabanksc.com'
        mail_server = self.env['ir.mail_server'].sudo().search([], limit=1)
        sender_email = mail_server.smtp_user if (mail_server and mail_server.smtp_user) else default_from
        sender_formatted = f'"{self.env.user.name} via Bunna Bank" <{sender_email}>'

        mail_values = {
            'subject': _("Official Lateral Transfer Letter - %s - Bunna Bank S.C.") % (self.new_position_name or 'Lateral Transfer'),
            'body_html': message_body,
            'email_from': sender_formatted,
            'reply_to': self.env.user.email_formatted or sender_formatted,
            'email_to': email_target,
            'attachment_ids': [(6, 0, attachments)] if attachments else [],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        try:
            mail.send()
        except Exception as mail_ex:
            _logger.warning("Lateral transfer letter email dispatch warning: %s", mail_ex)

        # 4. Subscribe employee partner as follower
        if emp_partner:
            try:
                self.message_subscribe(partner_ids=[emp_partner.id])
            except Exception:
                pass

        # 5. Schedule Systray Activity ("To-Do") for the employee
        todo_act_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        model_id = self.env['ir.model'].search([('model', '=', 'transfer.letter')], limit=1)
        if emp_user and todo_act_type and model_id:
            existing_act = self.env['mail.activity'].sudo().search([
                ('res_model', '=', 'transfer.letter'),
                ('res_id', '=', self.id),
                ('user_id', '=', emp_user.id)
            ], limit=1)
            if not existing_act:
                self.env['mail.activity'].sudo().create({
                    'activity_type_id': todo_act_type.id,
                    'note': _("Please review and acknowledge your official Lateral Transfer Letter %s to %s.") % (
                        self.name, self.new_work_unit_name
                    ),
                    'summary': _("Review & Acknowledge Transfer Letter %s") % self.name,
                    'user_id': emp_user.id,
                    'res_model_id': model_id.id,
                    'res_id': self.id,
                    'date_deadline': fields.Date.context_today(self),
                })

        # 6. Send targeted Discuss message notification to employee
        notif_msg = None
        if emp_partner:
            try:
                notif_msg = self.message_notify(
                    partner_ids=[emp_partner.id],
                    subject=_("Official Lateral Transfer Letter: %s") % self.name,
                    body=_(
                        "Dear %s,\n\n"
                        "Your official Lateral Transfer Letter %s to %s has been dispatched.\n"
                        "Please open the record to review and accept/acknowledge your transfer."
                    ) % (self.employee_name or self.employee_id.name, self.name, self.new_work_unit_name),
                    email_layout_xmlid="mail.mail_notification_light",
                )
            except Exception as e:
                _logger.warning("Could not send message_notify: %s", e)

        # 7. Post public comment in Chatter with @mention
        mention_html = f'<a href="#" data-oe-model="res.partner" data-oe-id="{emp_partner.id}">@{emp_partner.name}</a>' if emp_partner else email_target
        posted_msg = self.message_post(
            body=_(
                "<p>Official Lateral Transfer Letter dispatched to employee %s (Email: <b>%s</b>).</p>"
                "<p>Please review the attached PDF transfer letter and proceed with acceptance.</p>"
            ) % (mention_html, email_target),
            subject=_("Lateral Transfer Letter Dispatched"),
            partner_ids=[emp_partner.id] if emp_partner else [],
            attachment_ids=attachments,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        # 8. Enforce Discuss Inbox delivery
        all_msg_ids = [m.id for m in (notif_msg, posted_msg) if m]
        if all_msg_ids and emp_partner:
            notifs = self.env['mail.notification'].sudo().search([
                ('mail_message_id', 'in', all_msg_ids),
                ('res_partner_id', '=', emp_partner.id),
            ])
            if notifs:
                notifs.write({
                    'notification_type': 'inbox',
                    'notification_status': 'sent',
                    'is_read': False,
                })

        # 9. Send 1-on-1 Discuss Direct Message (DM)
        if 'discuss.channel' in self.env and emp_partner and emp_user and emp_user.id != self.env.user.id:
            try:
                chat_channel = self.env['discuss.channel'].sudo()._get_or_create_chat(
                    partners_to=[self.env.user.partner_id.id, emp_partner.id]
                )
                if chat_channel:
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                    letter_url = f"{base_url.rstrip('/')}/web#id={self.id}&model=transfer.letter&view_type=form" if base_url else f"/web#id={self.id}&model=transfer.letter&view_type=form"
                    dm_msg = chat_channel.sudo().message_post(
                        body=Markup(
                            f"<p>Hello <b>{escape(emp_partner.name)}</b>,</p>"
                            f"<p>Your official Lateral Transfer Letter <b>{escape(self.name or '')}</b> for transfer to <b>{escape(self.new_work_unit_name or '')}</b> "
                            f"has been issued with official PDF attachment.</p>"
                            f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                            f"<a href='{letter_url}' target='_blank' style='display: inline-block; padding: 9px 18px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                            f"👉 View &amp; Acknowledge Transfer Letter"
                            f"</a>"
                            f"</div>"
                        ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        attachment_ids=attachments,
                    )
                    dm_notifs = self.env['mail.notification'].sudo().search([
                        ('mail_message_id', '=', dm_msg.id),
                        ('res_partner_id', '=', emp_partner.id),
                    ])
                    if dm_notifs:
                        dm_notifs.write({
                            'notification_type': 'inbox',
                            'notification_status': 'sent',
                            'is_read': False,
                        })
            except Exception as e:
                _logger.warning("Could not send Discuss DM to %s: %s", emp_partner.name, e)

        # 9.5. Dispatch CC Notifications via Discuss & Work Email to Work Unit Managers
        cc_lines = self.get_transfer_letter_cc_lines()
        if cc_lines:
            try:
                from .cc_dispatch_service import dispatch_letter_cc_notifications
                details_html = (
                    f"• Transferred Employee: <b>{self.employee_name or self.employee_id.name}</b><br/>"
                    f"• Letter Reference: <b>{self.name}</b><br/>"
                    f"• New Position: <b>{self.new_position_name}</b><br/>"
                    f"• Target Work Unit: <b>{self.new_work_unit_name}</b><br/>"
                    f"• Current Work Unit: <b>{self.current_work_unit_name}</b><br/>"
                    f"• Effective Date: <b>{eff_date}</b>"
                )
                dispatch_letter_cc_notifications(
                    self,
                    cc_lines,
                    letter_title=_("Lateral Transfer Letter"),
                    letter_subject=_("Lateral Transfer of %s") % (self.employee_name or self.employee_id.name),
                    details_html=details_html,
                    attachment_ids=attachments,
                    candidate_emp=self.employee_id,
                )
            except Exception as cc_err:
                _logger.warning("Error dispatching CC notifications for transfer letter: %s", cc_err)

        # 10. Update status to sent
        self.write({'state': 'sent'})

        # Also post update on linked transfer request if exists
        if self.transfer_request_id:
            try:
                self.transfer_request_id.sudo().message_post(
                    body=_(
                        "Official Lateral Transfer Letter %s has been dispatched to %s."
                    ) % (self.name, mention_html),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    attachment_ids=attachments,
                )
            except Exception:
                pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Letter Dispatched'),
                'message': _('Official Lateral Transfer Letter has been successfully emailed to %s and dispatched via Discuss.') % email_target,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
