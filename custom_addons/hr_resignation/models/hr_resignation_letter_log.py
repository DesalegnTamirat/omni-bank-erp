# -*- coding: utf-8 -*-
import base64
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class HrResignationLetterLog(models.Model):
    _name = 'hr.resignation.letter.log'
    _description = 'Resignation Printed Letter Audit Log'
    _order = 'print_date desc, id desc'

    resignation_id = fields.Many2one(
        'hr.resignation',
        string='Separation Reference',
        required=True,
        ondelete='cascade',
        index=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='resignation_id.employee_id',
        store=True,
        index=True
    )
    letter_type = fields.Selection([
        ('acceptance', 'Resignation Acceptance Letter'),
        ('termination_memo', 'Notification of Termination (Memo)'),
        ('certificate_of_release', 'Certificate of Release / Experience'),
        ('settlement', 'Settlement Statement'),
        ('exit_interview', 'Exit Interview Report'),
        ('other', 'Other Printable Document'),
    ], string='Letter Type', required=True, default='acceptance')

    letter_name = fields.Char(string='Document Title', required=True)
    printed_by = fields.Many2one(
        'res.users',
        string='Printed By',
        default=lambda self: self.env.user,
        readonly=True,
        index=True
    )
    print_date = fields.Datetime(
        string='Print Date & Time',
        default=fields.Datetime.now,
        readonly=True,
        index=True
    )
    source = fields.Selection([
        ('manual_print', 'User Print Action'),
        ('system_auto', 'Auto-Generated on Approval'),
    ], string='Generation Source', default='manual_print', readonly=True)

    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Stored PDF Document',
        ondelete='set null'
    )
    attachment_datas = fields.Binary(
        related='attachment_id.datas',
        string='PDF File',
        readonly=True
    )
    file_name = fields.Char(
        related='attachment_id.name',
        string='File Name',
        readonly=True
    )

    def action_download_pdf(self):
        self.ensure_one()
        if not self.attachment_id:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'new',
        }


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        res = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        try:
            report_sudo = self._get_report(report_ref)
            if report_sudo and report_sudo.model == 'hr.resignation' and res_ids and res and res[0]:
                pdf_content = res[0]
                self._log_resignation_printed_letter(report_sudo, res_ids, pdf_content)
        except Exception as e:
            _logger.warning("Failed to log printed letter in hr_resignation: %s", e)
        return res

    def _log_resignation_printed_letter(self, report_sudo, res_ids, pdf_content):
        if not pdf_content:
            return
        Resignation = self.env['hr.resignation'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        LetterLog = self.env['hr.resignation.letter.log'].sudo()

        is_auto = bool(self.env.context.get('resignation_auto_approval'))
        source = 'system_auto' if is_auto else 'manual_print'
        report_xml_id = report_sudo.get_external_id().get(report_sudo.id, '')

        for res_id in res_ids:
            rec = Resignation.browse(res_id)
            if not rec.exists():
                continue

            # Determine letter type and friendly title
            if report_xml_id == 'hr_resignation.action_report_notification_of_termination':
                l_type = 'termination_memo'
                title = 'Notification of Termination'
            elif report_xml_id == 'hr_resignation.action_report_resignation_acceptance':
                if rec.notice_period_accepted == 'no':
                    l_type = 'termination_memo'
                    title = 'Notification of Termination'
                else:
                    l_type = 'acceptance'
                    title = 'Resignation Acceptance Letter'
            elif report_xml_id == 'hr_resignation.action_report_certificate_of_release':
                l_type = 'certificate_of_release'
                title = 'Certificate of Release'
            elif report_xml_id == 'hr_resignation.action_report_settlement_statement':
                l_type = 'settlement'
                title = 'Settlement Statement'
            elif report_xml_id == 'hr_resignation.action_report_exit_interview':
                l_type = 'exit_interview'
                title = 'Exit Interview Report'
            else:
                l_type = 'other'
                title = report_sudo.name or 'Printed Letter'

            emp_name = rec.employee_id.name or rec.name
            doc_filename = f"{title} - {emp_name}.pdf"

            # Create attachment to preserve exact PDF snapshot in DB
            b64_content = base64.b64encode(pdf_content) if isinstance(pdf_content, (bytes, bytearray)) else pdf_content
            attachment = Attachment.create({
                'name': doc_filename,
                'type': 'binary',
                'datas': b64_content,
                'res_model': 'hr.resignation',
                'res_id': rec.id,
                'mimetype': 'application/pdf',
            })

            # Create log entry
            LetterLog.create({
                'resignation_id': rec.id,
                'letter_type': l_type,
                'letter_name': doc_filename,
                'printed_by': self.env.user.id,
                'print_date': fields.Datetime.now(),
                'source': source,
                'attachment_id': attachment.id,
            })

            # Post chatter message
            source_label = "Auto-generated on approval" if is_auto else "Printed"
            rec.message_post(
                body=_(
                    "<p>📄 <strong>%(source)s:</strong> %(title)s by <strong>%(user)s</strong> on %(time)s.</p>"
                ) % {
                    'source': source_label,
                    'title': title,
                    'user': self.env.user.name,
                    'time': fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }
            )
