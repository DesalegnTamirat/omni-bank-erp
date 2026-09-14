# -*- coding: utf-8 -*-
import base64
import logging
import os
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

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

    # ── Linked Records ────────────────────────────────────────────────
    transfer_request_id = fields.Many2one(
        'employee.transfer.request', string='Transfer Request', tracking=True
    )
    minutes_id = fields.Many2one(
        'transfer.committee.minutes', string='Committee Minutes', tracking=True
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
        default='Melesse Leykun',
        tracking=True
    )
    signatory_title = fields.Char(
        string='Authorized Signatory',
        default='Talent Management Directorate'
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
                rec.employee_email = (rec.employee_id.work_email or rec.employee_id.private_email or '').strip()
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
                    seq_name = f"-BB/TMD/{count:02d}/{month}/{year}"
                vals['name'] = seq_name
        records = super().create(vals_list)
        # Link back to transfer request if applicable
        for rec in records:
            if rec.transfer_request_id and not rec.transfer_request_id.transfer_letter_id:
                rec.transfer_request_id.sudo().write({'transfer_letter_id': rec.id})
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
        """Sends the lateral transfer letter with official PDF attachment to the employee's email."""
        self.ensure_one()
        email_target = (self.employee_email or (self.employee_id.work_email or self.employee_id.private_email if self.employee_id else False) or '').strip()
        if not email_target:
            raise UserError(_(
                "Employee Email Address Missing!\n\n"
                "Cannot send Lateral Transfer Letter because no email address was found for %s.\n"
                "Please specify the employee's email address in the 'Employee Email' field before sending."
            ) % (self.employee_name or self.employee_id.name or 'this employee'))

        # 1. Generate PDF attachment using QWeb report
        report = self.env.ref('custom_recruitment.action_report_lateral_transfer_letter', raise_if_not_found=False)
        attachments = []
        if report:
            pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
                'custom_recruitment.action_report_lateral_transfer_letter', [self.id]
            )
            clean_name = (self.employee_name or 'Employee').replace(' ', '_')
            attachment = self.env['ir.attachment'].sudo().create({
                'name': f"Lateral_Transfer_Letter_{clean_name}.pdf",
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

        # 3. Create mail and dispatch
        mail_values = {
            'subject': _("Official Lateral Transfer Letter - %s - Bunna Bank S.C.") % (self.new_position_name or 'Lateral Transfer'),
            'body_html': message_body,
            'email_to': email_target,
            'attachment_ids': [(6, 0, attachments)] if attachments else [],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        try:
            mail.send()
        except Exception as mail_ex:
            _logger.warning("Lateral transfer letter email dispatch warning: %s", mail_ex)

        # 4. Update status and post in chatter
        self.write({'state': 'sent'})
        self.message_post(
            body=_(
                "Official Lateral Transfer Letter dispatched to employee email: <b>%s</b> with PDF attachment."
            ) % email_target,
            subject=_("Lateral Transfer Letter Dispatched"),
            attachment_ids=attachments
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Letter Dispatched'),
                'message': _('Official Lateral Transfer Letter has been successfully emailed to %s.') % email_target,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
