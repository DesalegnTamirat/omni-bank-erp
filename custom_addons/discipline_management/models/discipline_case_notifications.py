# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class DisciplineCaseNotifications(models.Model):
    _inherit = 'discipline.case'

    def _send_discuss_direct_message(self, sender_user, target_partner, msg_html):
        """Safely dispatch 1-on-1 Odoo Discuss direct chat message on discipline.case."""
        if not target_partner or not sender_user:
            return
        try:
            partner = target_partner.partner_id if hasattr(target_partner, 'partner_id') and target_partner.partner_id else target_partner
            sender_partner = sender_user.partner_id if hasattr(sender_user, 'partner_id') else sender_user
            if not partner or not sender_partner:
                return

            channel = False
            DiscussChannel = self.env['discuss.channel'].sudo()
            if hasattr(DiscussChannel, '_get_or_create_chat'):
                channel = DiscussChannel.with_user(sender_user)._get_or_create_chat(
                    partners_to=[partner.id]
                )
            elif hasattr(DiscussChannel, 'channel_get'):
                channel_info = DiscussChannel.channel_get(partners_to=[sender_partner.id, partner.id])
                if channel_info and 'id' in channel_info:
                    channel = DiscussChannel.browse(channel_info['id'])

            if channel:
                channel.sudo().with_user(sender_user).message_post(
                    body=Markup(msg_html) if not isinstance(msg_html, Markup) else msg_html,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_partner.id,
                )
        except Exception as e:
            _logger.warning("Failed to dispatch Discuss direct message for case: %s", str(e))

    def _post_discuss_dm(self, sender_user, recipient_user, msg_body, subscribe_case=True):
        """Shared helper to post a 1-on-1 Odoo Discuss direct message from sender_user to recipient_user."""
        self.ensure_one()
        if not sender_user or not sender_user.partner_id or not recipient_user or not recipient_user.partner_id:
            return
        sender_partner = sender_user.partner_id
        recipient_partner = recipient_user.partner_id

        if subscribe_case:
            self.message_subscribe(partner_ids=[recipient_partner.id])

        try:
            channel = False
            DiscussChannel = self.env['discuss.channel']
            if hasattr(DiscussChannel, '_get_or_create_chat'):
                channel = DiscussChannel.with_user(sender_user)._get_or_create_chat(partners_to=[recipient_partner.id])
            elif hasattr(DiscussChannel, 'channel_get'):
                channel_info = DiscussChannel.sudo().channel_get(partners_to=[sender_partner.id, recipient_partner.id])
                if channel_info and 'id' in channel_info:
                    channel = DiscussChannel.sudo().browse(channel_info['id'])

            if channel:
                channel.message_post(
                    body=msg_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_partner.id,
                )
        except Exception:
            pass

    def _get_case_severity_display(self):
        """Return human-readable severity level label for notifications."""
        self.ensure_one()
        if self.severity_level_id:
            return self.severity_level_id.name
        return dict(self._fields['severity_level'].selection).get(self.severity_level, self.severity_level or _('N/A'))

    def _send_employee_discuss_direct_message(self, message_type='enforce'):
        """Send official notification directly into 1-on-1 Odoo Discuss direct message channel for the employee."""
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            emp_user = emp.user_id if emp else False
            if not emp_user or not emp_user.partner_id:
                continue

            manager_user = (rec.reported_by_id and rec.reported_by_id.sudo().user_id) or rec.env.user
            if message_type == 'initiate':
                msg_body = Markup(_(
                    '<p><strong>Disciplinary Case Notice</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>A formal disciplinary case (Ref: <strong>%s</strong>) has been initiated regarding alleged misconduct: <em>%s</em> (Incident Date: %s).</p>'
                    '<p>You can view full details in Bunna Bank ERP under <strong>Discipline Management</strong>.</p>'
                ) % (
                    emp.name,
                    rec.name,
                    rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                    rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A'),
                ))
            else:
                sanction_name = dict(rec._fields['punishment_type'].selection).get(rec.punishment_type, str(rec.punishment_type or ''))
                penalty_details = []
                if rec.penalty_percentage > 0.0:
                    penalty_details.append(_('%s%% Salary Deduction') % rec.penalty_percentage)
                if rec.fine_days > 0.0:
                    penalty_details.append(_('%d Day(s) Salary Fine') % int(rec.fine_days))
                penalty_sub = (' (' + ', '.join(penalty_details) + ')') if penalty_details else ''

                appeal_days_text = f"{rec.get_appeal_window_days()} working days" if hasattr(rec, 'get_appeal_window_days') else "5 working days"
                msg_body = Markup(_(
                    '<p><strong>Official Disciplinary Decision &amp; Warning Notice</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>A formal disciplinary decision has been enforced under Case Reference: <strong>%s</strong>.</p>'
                    '<ul>'
                    '<li><strong>Misconduct Clause:</strong> %s</li>'
                    '<li><strong>Enforced Sanction:</strong> %s%s</li>'
                    '<li><strong>Decision Date:</strong> %s</li>'
                    '<li><strong>Statutory Appeal Deadline:</strong> %s (%s statutory window)</li>'
                    '</ul>'
                    '<p>You have the right to lodge a formal written appeal in Bunna Bank ERP within %s.</p>'
                ) % (
                    emp.name,
                    rec.name,
                    rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                    sanction_name,
                    penalty_sub,
                    rec.final_decision_date.strftime('%B %d, %Y') if rec.final_decision_date else fields.Date.today(),
                    rec.appeal_deadline.strftime('%B %d, %Y') if rec.appeal_deadline else _('%s from receipt') % appeal_days_text,
                    appeal_days_text,
                    appeal_days_text,
                ))

            rec._post_discuss_dm(manager_user, emp_user, msg_body, subscribe_case=True)

    def _dispatch_cc_stakeholder_notifications(self):
        """Dispatches CC notifications to designated governance stakeholders upon case enforcement:
        1. People Operations Management Directorate (POMD) - for personnel file record
        2. Coach of Coach (e.g. Directorate Director Derese) - for division management oversight
        3. Internal Audit Directorate - for compliance tracking
        """
        for rec in self:
            sender_user = rec.approver_id or rec.enforced_by_id or self.env.user
            emp = rec.employee_id.sudo() if rec.employee_id else False
            emp_name = rec.employee_name_amharic or (emp.name if emp else _('Employee'))
            sanction_name = rec.get_sanction_display_text_amharic() if hasattr(rec, 'get_sanction_display_text_amharic') else (rec.punishment_type or '')
            eth_date_str = rec.get_ethiopian_date_long(rec.final_decision_date) if hasattr(rec, 'get_ethiopian_date_long') else str(rec.final_decision_date or '')

            # CC Recipients
            cc_recipients = []

            # 1. POMD (Personnel Operations Management Directorate)
            pomd_user = self.env['hr.employee'].sudo().get_pomd_user()
            if pomd_user and pomd_user.id != sender_user.id:
                cc_recipients.append((pomd_user, 'ለሰው ኃይል ኦፕሬሽንስ አስተዳደር ዳይሬክቶሬት (POMD)'))

            # 2. Coach of Coach (e.g. Directorate Director Derese)
            coach_of_coach = rec._get_coach_of_coach() if hasattr(rec, '_get_coach_of_coach') else False
            if coach_of_coach and coach_of_coach.user_id and coach_of_coach.user_id.id != sender_user.id:
                job_title = coach_of_coach.job_id.name if coach_of_coach.job_id else 'ዳይሬክተር'
                cc_recipients.append((coach_of_coach.user_id, f'ለ{coach_of_coach.name} ({job_title})'))

            # 3. Internal Audit Directorate (Only for Committee / Escalated cases, not direct enforcement)
            if rec.case_action_track != 'direct_enforce':
                audit_user = self.env['hr.employee'].sudo().get_audit_director_user()
                if audit_user and audit_user.id != sender_user.id:
                    cc_recipients.append((audit_user, 'ለውስጥ ኦዲት ዳይሬክቶሬት'))

            # Send Discuss DM and log in chatter
            notified_labels = []
            for recipient_user, role_desc in cc_recipients:
                if not recipient_user.partner_id:
                    continue
                notified_labels.append(f"{recipient_user.name} ({role_desc})")
                msg_body = Markup(_(
                    '<p><strong>የዲሲፕሊን ውሳኔ ማሳወቂያ ግልባጭ (CC: Formal Disciplinary Notice Notification)</strong></p>'
                    '<p>ክቡር/ክብርት %s፣</p>'
                    '<p>በሠራተኛ <strong>%s</strong> ላይ የተላለፈው ይፋዊ የዲሲፕሊን ውሳኔ ተፈጻሚ ተደርጓል (Case Ref: <strong>%s</strong>)።</p>'
                    '<ul>'
                    '<li><strong>የጥፋት ዓይነት፡</strong> %s</li>'
                    '<li><strong>የተወሰነው ቅጣት፡</strong> %s</li>'
                    '<li><strong>የተወሰነበት ቀን፡</strong> %s</li>'
                    '<li><strong>የይግባኝ ማቅረቢያ ጊዜ፡</strong> %s የሥራ ቀናት</li>'
                    '</ul>'
                    '<p>ይህ የዲሲፕሊን ውሳኔ በቡና ባንክ የሰው ኃይል አስተዳደር ሥርዓት ውስጥ በግልባጭ (CC) ለእርስዎ እንዲደርስ የተደረገ ነው።</p>'
                ) % (
                    recipient_user.name,
                    emp_name,
                    rec.name,
                    rec.offense_id.name if rec.offense_id else _('የዲሲፕሊን ጥፋት'),
                    sanction_name,
                    eth_date_str,
                    rec.get_appeal_window_days() if hasattr(rec, 'get_appeal_window_days') else 10,
                ))
                rec._post_discuss_dm(sender_user, recipient_user, msg_body, subscribe_case=True)

            if notified_labels:
                rec.message_post(
                    body=Markup(_('<strong>CC Stakeholder Notifications Dispatched:</strong><br/>%s') % '<br/>'.join(f'• {lbl}' for lbl in notified_labels)),
                    subtype_xmlid='mail.mt_note'
                )

    def _send_chief_submission_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to the Respective Chief Officer upon case submission."""
        for rec in self:
            chief_user = rec.chief_id or self.env['hr.employee'].get_cpco_user()
            if not chief_user or not chief_user.partner_id:
                continue

            sender_user = (rec.sudo().reported_by_id and rec.sudo().reported_by_id.user_id) or rec.initiator_id or self.env.user
            if not sender_user.partner_id or sender_user.partner_id.id == chief_user.partner_id.id:
                continue

            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            msg_body = Markup(_(
                '<p><strong>Formal Disciplinary Case Forwarded for Executive Review</strong></p>'
                '<p>Dear %s,</p>'
                '<p>A formal disciplinary case (Ref: <strong>%s</strong>) regarding subject employee <strong>%s</strong> has been submitted to you by <strong>%s</strong> for executive review and decision.</p>'
                '<ul>'
                '<li><strong>Misconduct Clause:</strong> %s</li>'
                '<li><strong>Severity Classification:</strong> %s</li>'
                '<li><strong>Misconduct Incident Date:</strong> %s</li>'
                '<li><strong>Legal Citation:</strong> %s</li>'
                '</ul>'
                '<p>Please access Bunna Bank ERP under <strong>Discipline Management &gt; Disciplinary Cases</strong> to review the incident facts and proceed with escalation routing or exoneration.</p>'
            ) % (
                chief_user.name,
                rec.name,
                rec.sudo().employee_id.name if rec.sudo().employee_id else _('N/A'),
                sender_user.name,
                rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                sev_name,
                incident_str,
                rec.legal_article_display or _('N/A'),
            ))
            rec._post_discuss_dm(sender_user, chief_user, msg_body, subscribe_case=True)

    def _send_chief_exoneration_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to Subject Employee and Initiator when Chief exonerates."""
        for rec in self:
            sender_user = self.env.user
            emp = rec.sudo().employee_id

            # 1. Notify Subject Employee
            if emp and emp.user_id and emp.user_id.partner_id:
                emp_user = emp.user_id
                msg_body = Markup(_(
                    '<p><strong>Official Disciplinary Exoneration Notice</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>We are pleased to inform you that disciplinary case (Ref: <strong>%s</strong>) regarding alleged misconduct has been reviewed by <strong>%s</strong> (Respective Chief Officer) and <strong>OFFICIALLY EXONERATED &amp; CLOSED</strong>.</p>'
                    '<p>All charges have been dropped, and your employment record remains clear with zero disciplinary penalties.</p>'
                ) % (
                    emp.name,
                    rec.name,
                    sender_user.name,
                ))
                rec._post_discuss_dm(sender_user, emp_user, msg_body, subscribe_case=False)

            # 2. Notify Initiator / Director
            initiator_user = (rec.sudo().reported_by_id and rec.sudo().reported_by_id.user_id) or rec.initiator_id
            if initiator_user and initiator_user.partner_id and initiator_user.id != sender_user.id:
                msg_body = Markup(_(
                    '<p><strong>Executive Decision Update: Case Exonerated &amp; Closed</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Disciplinary case (Ref: <strong>%s</strong>) regarding employee <strong>%s</strong> was reviewed by <strong>%s</strong> (Respective Chief Officer) and officially exonerated with no sanction.</p>'
                ) % (
                    initiator_user.name,
                    rec.name,
                    emp.name if emp else _('N/A'),
                    sender_user.name,
                ))
                rec._post_discuss_dm(sender_user, initiator_user, msg_body, subscribe_case=False)

    def _send_chief_to_audit_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to Audit Directorate Director and CEO when Chief escalates for investigation."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            audit_user = EmpModel.get_audit_director_user()
            ceo_user = EmpModel.get_ceo_user()
            sender_user = self.env.user
            emp = rec.sudo().employee_id

            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            chief_notes_html = Markup(_('<p><strong>Chief Executive Directive / Investigation Scope:</strong><br/><em>%s</em></p>') % rec.chief_review_notes) if rec.chief_review_notes else ''

            # 1. Notify Audit Directorate Director
            if audit_user and audit_user.partner_id and audit_user.id != sender_user.id:
                msg_body = Markup(_(
                    '<p><strong>Disciplinary Investigation Assignment Directive</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Disciplinary case (Ref: <strong>%s</strong>) regarding employee <strong>%s</strong> has been formally escalated to the Internal Audit Directorate by <strong>%s</strong> (Respective Chief Officer) for thorough investigation and findings submission.</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                    '<li><strong>Alleged Misconduct:</strong> %s</li>'
                    '<li><strong>Severity Classification:</strong> %s</li>'
                    '<li><strong>Incident Date:</strong> %s</li>'
                    '<li><strong>Legal Citation:</strong> %s</li>'
                    '</ul>'
                    '%s'
                    '<p>Please assign an auditor in Bunna Bank ERP under <strong>Hearings &amp; Investigations &gt; Investigations</strong>.</p>'
                ) % (
                    audit_user.name,
                    rec.name,
                    emp.name if emp else _('N/A'),
                    sender_user.name,
                    emp.name if emp else _('N/A'),
                    rec.sudo().job_id.name if rec.sudo().job_id else _('Staff'),
                    rec.sudo().department_id.name if rec.sudo().department_id else _('Department'),
                    rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                    sev_name,
                    incident_str,
                    rec.legal_article_display or _('N/A'),
                    chief_notes_html,
                ))
                rec._post_discuss_dm(sender_user, audit_user, msg_body, subscribe_case=True)

            # 2. Notify CEO for awareness
            if ceo_user and ceo_user.partner_id and ceo_user.id != sender_user.id:
                msg_body = Markup(_(
                    '<p><strong>Executive Notification: Case Referred to Audit Investigation</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Please be informed that <strong>%s</strong> (Respective Chief Officer) has escalated disciplinary case (Ref: <strong>%s</strong>) regarding <strong>%s</strong> to the Audit Directorate for comprehensive investigation.</p>'
                    '<ul>'
                    '<li><strong>Misconduct Clause:</strong> %s</li>'
                    '<li><strong>Incident Date:</strong> %s</li>'
                    '<li><strong>Audit Directorate:</strong> Assigned for Investigation</li>'
                    '</ul>'
                    '%s'
                ) % (
                    ceo_user.name,
                    sender_user.name,
                    rec.name,
                    emp.name if emp else _('N/A'),
                    rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                    incident_str,
                    chief_notes_html,
                ))
                rec._post_discuss_dm(sender_user, ceo_user, msg_body, subscribe_case=True)

    def _send_chief_to_ceo_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to CEO when Chief escalates case."""
        for rec in self:
            ceo_user = self.env['hr.employee'].sudo().get_ceo_user()
            if not ceo_user or not ceo_user.partner_id:
                continue

            sender_user = self.env.user
            if not sender_user.partner_id or sender_user.partner_id.id == ceo_user.partner_id.id:
                continue

            emp = rec.sudo().employee_id
            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            chief_notes_html = Markup(_('<p><strong>Chief Executive Directive / Remarks:</strong><br/><em>%s</em></p>') % rec.chief_review_notes) if rec.chief_review_notes else ''
            msg_body = Markup(_(
                '<p><strong>Formal Disciplinary Case Escalated to CEO for Executive Review</strong></p>'
                '<p>Dear %s,</p>'
                '<p>Disciplinary case (Ref: <strong>%s</strong>) regarding employee <strong>%s</strong> has been escalated to you by <strong>%s</strong> (Respective Chief Officer) for your executive review and directive.</p>'
                '<ul>'
                '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                '<li><strong>Misconduct Clause:</strong> %s</li>'
                '<li><strong>Severity Classification:</strong> %s</li>'
                '<li><strong>Incident Date:</strong> %s</li>'
                '<li><strong>Legal Citation:</strong> %s</li>'
                '</ul>'
                '%s'
                '<p>Please access Bunna Bank ERP under <strong>Discipline Management &gt; Disciplinary Cases</strong> to review and assign for investigation / committee scheduling.</p>'
            ) % (
                ceo_user.name,
                rec.name,
                emp.name if emp else _('N/A'),
                sender_user.name,
                emp.name if emp else _('N/A'),
                rec.sudo().job_id.name if rec.sudo().job_id else _('Staff'),
                rec.sudo().department_id.name if rec.sudo().department_id else _('Department'),
                rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                sev_name,
                incident_str,
                rec.legal_article_display or _('N/A'),
                chief_notes_html,
            ))
            rec._post_discuss_dm(sender_user, ceo_user, msg_body, subscribe_case=True)

    def _send_ceo_announce_audit_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to Audit Directorate Director and POMD Secretary upon CEO directive."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            audit_user = EmpModel.get_audit_director_user()
            sec_user = EmpModel.get_secretary_user()
            sender_user = self.env.user
            emp = rec.sudo().employee_id

            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            ceo_notes_html = Markup(_('<p><strong>CEO Directive &amp; Investigation Mandate:</strong><br/><em>%s</em></p>') % rec.ceo_assignment_notes) if rec.ceo_assignment_notes else ''

            # 1. Notify Audit Directorate Director
            if audit_user and audit_user.partner_id and audit_user.id != sender_user.id:
                msg_body = Markup(_(
                    '<p><strong>CEO Directive: Immediate Disciplinary Audit Investigation</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Disciplinary case (Ref: <strong>%s</strong>) regarding employee <strong>%s</strong> has been officially referred to the Internal Audit Directorate by the <strong>Chief Executive Officer (CEO)</strong> for formal investigation.</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                    '<li><strong>Misconduct Clause:</strong> %s</li>'
                    '<li><strong>Severity Level:</strong> %s</li>'
                    '<li><strong>Incident Date:</strong> %s</li>'
                    '</ul>'
                    '%s'
                    '<p>Please access Bunna Bank ERP to assign a Lead Auditor and commence the investigation.</p>'
                ) % (
                    audit_user.name,
                    rec.name,
                    emp.name if emp else _('N/A'),
                    emp.name if emp else _('N/A'),
                    rec.sudo().job_id.name if rec.sudo().job_id else _('Staff'),
                    rec.sudo().department_id.name if rec.sudo().department_id else _('Department'),
                    rec.offense_id.name if rec.offense_id else _('Misconduct Clause'),
                    sev_name,
                    incident_str,
                    ceo_notes_html,
                ))
                rec._post_discuss_dm(sender_user, audit_user, msg_body, subscribe_case=True)

            # 2. Notify Disciplinary Committee Secretary (POMD) for Precautionary Suspension
            if sec_user and sec_user.partner_id and sec_user.id != sender_user.id:
                msg_body = Markup(_(
                    '<p><strong>CEO Directive: Precautionary Employee Suspension Instruction</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Per directive of the <strong>Chief Executive Officer (CEO)</strong>, employee <strong>%s</strong> is subject to immediate 30-day precautionary suspension pending audit investigation on case <strong>%s</strong>.</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                    '<li><strong>Suspension Type:</strong> 30 Days Precautionary (Without Pay)</li>'
                    '<li><strong>Case Ref:</strong> %s</li>'
                    '</ul>'
                    '%s'
                    '<p>Please review and execute the precautionary suspension notice in Bunna Bank ERP under <strong>Suspensions</strong>.</p>'
                ) % (
                    sec_user.name,
                    emp.name if emp else _('N/A'),
                    rec.name,
                    emp.name if emp else _('N/A'),
                    rec.sudo().job_id.name if rec.sudo().job_id else _('Staff'),
                    rec.sudo().department_id.name if rec.sudo().department_id else _('Department'),
                    rec.name,
                    ceo_notes_html,
                ))
                rec._post_discuss_dm(sender_user, sec_user, msg_body, subscribe_case=True)

    def _send_ceo_forward_to_chair_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message exclusively to CPCO (Committee Chairman) when CEO forwards investigated case."""
        for rec in self:
            cpco_user = self.env['hr.employee'].sudo().get_cpco_user()
            if not cpco_user or not cpco_user.partner_id:
                continue

            sender_user = self.env.user
            if not sender_user.partner_id or sender_user.partner_id.id == cpco_user.partner_id.id:
                ceo_user = self.env['hr.employee'].sudo().get_ceo_user()
                if ceo_user and ceo_user.partner_id and ceo_user.id != cpco_user.id:
                    sender_user = ceo_user
                else:
                    admin_user = self.env.ref('base.user_admin', raise_if_not_found=False)
                    if admin_user and admin_user.partner_id and admin_user.id != cpco_user.id:
                        sender_user = admin_user

            if not sender_user or not sender_user.partner_id:
                continue

            emp = rec.sudo().employee_id
            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            ceo_notes_html = Markup(_('<p><strong>CEO Directive / Remarks:</strong><br/><em>%s</em></p>') % rec.ceo_assignment_notes) if rec.ceo_assignment_notes else ''

            # Extract latest investigation findings
            inv = rec.investigation_ids.sorted(key=lambda i: i.id, reverse=True)[:1]
            inv_info_html = ""
            action_guidance_html = ""
            if inv:
                outcome_label = _('Substantiated (Liable)') if inv.finding_outcome == 'liable' else _('Unsubstantiated (Exonerated)')
                liables = ', '.join([l.sudo().employee_id.name for l in inv.sudo().liable_employee_ids if l.sudo().employee_id]) if inv.liable_employee_ids else (emp.name if inv.finding_outcome == 'liable' and emp else _('None (Exonerated)'))
                loss_str = ""
                if inv.is_cash_shortage and inv.financial_loss_amount > 0:
                    loss_status = dict(inv._fields['loss_resolution_status'].selection).get(inv.loss_resolution_status, 'N/A')
                    loss_str = f"<li><strong>Financial Shortage / Loss:</strong> ETB {inv.financial_loss_amount:,.2f} ({loss_status})</li>"

                inv_info_html = (
                    f"<li><strong>Investigation Ref:</strong> {inv.name}</li>"
                    f"<li><strong>Audit Conclusion:</strong> <strong>{outcome_label}</strong></li>"
                    f"<li><strong>Liable Personnel Identified:</strong> {liables}</li>"
                    f"{loss_str}"
                )
                if inv.finding_outcome == 'liable':
                    action_guidance_html = (
                        "<p><strong>Next Action Required:</strong><br/>"
                        "Please open <strong>Discipline Management</strong> in Bunna Bank ERP to review the full audit findings and click "
                        "<strong>'Forward to Secretary'</strong> "
                        "to instruct POMD to schedule the formal Disciplinary Committee hearing.</p>"
                    )
                else:
                    action_guidance_html = (
                        "<p><strong>Next Action Required:</strong><br/>"
                        "Audit concluded that the allegations are unsubstantiated. "
                        "You may review the case and click <strong>'Endorse Exoneration'</strong> to close the case and revoke any precautionary suspension.</p>"
                    )
            else:
                action_guidance_html = (
                    "<p><strong>Next Action Required:</strong><br/>"
                    "Please access Bunna Bank ERP under <strong>Discipline Management</strong> to review the case and instruct the Committee Secretary to schedule a committee hearing.</p>"
                )

            ceo_name = sender_user.name
            msg_body = Markup(
                f"<p><strong>CONFIDENTIAL EXECUTIVE BRIEFING: DISCIPLINARY CASE FORWARDED TO COMMITTEE CHAIRMAN</strong></p>"
                f"<p>Dear {cpco_user.name},</p>"
                f"<p>The <strong>Chief Executive Officer ({ceo_name})</strong> has reviewed the completed audit investigation for Disciplinary Case <strong>{rec.name}</strong> and officially forwarded it to you as <strong>Disciplinary Committee Chairman (CPCO)</strong> for committee review.</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp.name if emp else _('N/A')} ({rec.sudo().job_id.name if rec.sudo().job_id else _('Staff')}, {rec.sudo().department_id.name if rec.sudo().department_id else _('Department')})</li>"
                f"<li><strong>Alleged Misconduct:</strong> {rec.offense_id.name if rec.offense_id else _('Misconduct Clause')}</li>"
                f"<li><strong>Severity Level:</strong> {sev_name}</li>"
                f"<li><strong>Incident Date:</strong> {incident_str}</li>"
                f"{inv_info_html}"
                f"</ul>"
                f"{ceo_notes_html}"
                f"{action_guidance_html}"
            )
            rec._post_discuss_dm(sender_user, cpco_user, msg_body, subscribe_case=True)

    def _send_chair_forward_to_secretary_discuss_notification(self):
        """Send 1-on-1 Odoo Discuss direct message to Committee Secretary (POMD) when CPCO forwards case for hearing scheduling."""
        for rec in self:
            sec_user = self.env['hr.employee'].sudo().get_secretary_user()
            if not sec_user or not sec_user.partner_id:
                continue

            sender_user = self.env.user
            if not sender_user.partner_id or sender_user.partner_id.id == sec_user.partner_id.id:
                cpco_user = self.env['hr.employee'].sudo().get_cpco_user()
                if cpco_user and cpco_user.partner_id and cpco_user.id != sec_user.id:
                    sender_user = cpco_user
                else:
                    admin_user = self.env.ref('base.user_admin', raise_if_not_found=False)
                    if admin_user and admin_user.partner_id and admin_user.id != sec_user.id:
                        sender_user = admin_user

            if not sender_user or not sender_user.partner_id:
                continue

            emp = rec.sudo().employee_id
            incident_str = rec.incident_date.strftime('%B %d, %Y') if rec.incident_date else _('N/A')
            sev_name = rec._get_case_severity_display()
            cpco_name = sender_user.name

            # Extract latest investigation findings
            inv = rec.investigation_ids.sorted(key=lambda i: i.id, reverse=True)[:1]
            inv_info_html = ""
            if inv:
                outcome_label = _('Substantiated (Liable)') if inv.finding_outcome == 'liable' else _('Unsubstantiated (Exonerated)')
                liables = ', '.join([l.sudo().employee_id.name for l in inv.sudo().liable_employee_ids if l.sudo().employee_id]) if inv.liable_employee_ids else (emp.name if inv.finding_outcome == 'liable' and emp else _('None'))
                loss_str = ""
                if inv.is_cash_shortage and inv.financial_loss_amount > 0:
                    loss_status = dict(inv._fields['loss_resolution_status'].selection).get(inv.loss_resolution_status, 'N/A')
                    loss_str = f"<li><strong>Financial Shortage / Loss:</strong> ETB {inv.financial_loss_amount:,.2f} ({loss_status})</li>"

                inv_info_html = (
                    f"<li><strong>Investigation Ref:</strong> {inv.name}</li>"
                    f"<li><strong>Audit Conclusion:</strong> <strong>{outcome_label}</strong></li>"
                    f"<li><strong>Liable Personnel Identified:</strong> {liables}</li>"
                    f"{loss_str}"
                )

            msg_body = Markup(
                f"<p><strong>DIRECTIVE: SCHEDULE DISCIPLINARY COMMITTEE HEARING</strong></p>"
                f"<p>Dear {sec_user.name} (Committee Secretary / POMD),</p>"
                f"<p>The <strong>Disciplinary Committee Chairman ({cpco_name} / CPCO)</strong> has reviewed the completed audit investigation dossier for Disciplinary Case <strong>{rec.name}</strong> and officially forwarded the matter to you for formal committee scheduling.</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp.name if emp else _('N/A')} ({rec.sudo().job_id.name if rec.sudo().job_id else _('Staff')}, {rec.sudo().department_id.name if rec.sudo().department_id else _('Department')})</li>"
                f"<li><strong>Misconduct Clause:</strong> {rec.offense_id.name if rec.offense_id else _('Misconduct Clause')}</li>"
                f"<li><strong>Severity Classification:</strong> {sev_name}</li>"
                f"<li><strong>Incident Date:</strong> {incident_str}</li>"
                f"{inv_info_html}"
                f"</ul>"
                f"<p><strong>Required Immediate Action:</strong><br/>"
                f"Please open <strong>Discipline Management</strong> in Bunna Bank ERP, access Case <strong>{rec.name}</strong>, "
                f"and click <strong>'Schedule Meeting'</strong> to establish the committee session, assign panel members, "
                f"set the hearing date/time, and generate the formal hearing summons for the subject employee.</p>"
            )
            rec._post_discuss_dm(sender_user, sec_user, msg_body, subscribe_case=True)

    def _post_enforcement_notification(self):
        """Send fast, high-performance structured executive decision notification to case chatter and employee."""
        self.ensure_one()
        emp = self.sudo().employee_id
        is_direct = self.case_action_track == 'direct_enforce'
        issuer_name = (self.initiator_id.name or self.sudo().reported_by_id.name or self.approver_id.name or self.env.user.name) if is_direct else (self.approver_id.name or self.env.user.name)
        issuer_role = _('Line Manager / Coach') if is_direct else _('Disciplinary Committee / Authorized Executive Approver')

        sanction_name = dict(self._fields['punishment_type'].selection).get(self.punishment_type, str(self.punishment_type or ''))
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(_('%s%% Salary Deduction') % self.penalty_percentage)
        if self.fine_days > 0.0:
            penalty_details.append(_('%d Day(s) Salary Fine') % int(self.fine_days))
        penalty_sub = (' (' + ', '.join(penalty_details) + ')') if penalty_details else ''

        appeal_days_text = f"{self.get_appeal_window_days()} working days" if hasattr(self, 'get_appeal_window_days') else "5 working days"
        body_html = Markup(_(
            '<p><strong>Official Disciplinary Decision &amp; Warning Notice</strong></p>'
            '<p>A formal disciplinary action has been enforced by <strong>%s</strong> (%s).</p>'
            '<ul>'
            '<li><strong>Case Reference:</strong> %s</li>'
            '<li><strong>Employee:</strong> %s</li>'
            '<li><strong>Misconduct Clause:</strong> %s</li>'
            '<li><strong>Enforced Sanction:</strong> %s%s</li>'
            '<li><strong>Decision Date:</strong> %s</li>'
            '<li><strong>Statutory Appeal Deadline:</strong> %s (%s window)</li>'
            '</ul>'
            '<p>The official warning letter can be viewed and printed directly using the <strong>Print Disciplinary Notice</strong> button at the top header.</p>'
        ) % (
            issuer_name,
            issuer_role,
            self.name,
            emp.name if emp else _('Staff'),
            self.offense_id.name if self.offense_id else _('Misconduct Clause'),
            sanction_name,
            penalty_sub,
            self.final_decision_date.strftime('%B %d, %Y') if self.final_decision_date else fields.Date.today(),
            self.appeal_deadline.strftime('%B %d, %Y') if self.appeal_deadline else _('%s from receipt') % appeal_days_text,
            appeal_days_text
        ))

        partner_ids = []
        if emp and emp.user_id and emp.user_id.partner_id:
            partner_ids.append(emp.user_id.partner_id.id)
        if self.sudo().reported_by_id and self.sudo().reported_by_id.user_id and self.sudo().reported_by_id.user_id.partner_id:
            partner_ids.append(self.sudo().reported_by_id.user_id.partner_id.id)

        self.message_post(
            body=body_html,
            partner_ids=list(set(partner_ids)),
            subtype_xmlid='mail.mt_comment'
        )

    @api.model
    def _cron_check_sla_escalations(self):
        today = fields.Date.context_today(self)
        breached_cases = self.search([
            ('state', 'in', ['initiated', 'investigating', 'committee_review', 'pending_approval']),
            ('sla_deadline', '<', today),
            ('is_sla_exceeded', '=', True)
        ])
        for case in breached_cases:
            case.message_post(
                body=_('SLA BREACH ALERT: Disciplinary Case %s has exceeded its resolution SLA deadline of %s.') % (case.name, case.sla_deadline),
                message_type='notification'
            )

    @api.model
    def _cron_check_appeal_window_expiry(self):
        today = fields.Date.context_today(self)
        expired_cases = self.search([
            ('state', '=', 'enforced'),
            ('appeal_deadline', '<', today)
        ])
        for case in expired_cases:
            case.message_post(body=_('Appeal submission window of 10 calendar days has expired for Case %s.') % case.name)

    def _send_committee_enforcement_ceo_notification(self):
        """Send executive briefing directly to the CEO when a committee decision is enforced by the CPCO."""
        for rec in self:
            # Strictly restricted to Disciplinary Committee track cases (never direct coach cases)
            if rec.case_action_track == 'direct_enforce':
                continue
            if rec.case_action_track != 'committee' and not rec.committee_meeting_ids:
                continue

            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            if not ceo_user:
                continue

            # If CEO themselves enforced it, no briefing needed
            if rec.env.user.id == ceo_user.id or rec.is_ceo_user:
                continue

            # Strictly verify enforcing authority is CPCO / Committee Chairman
            cpco_user = EmpModel.get_cpco_user()
            is_cpco = (cpco_user and rec.env.user.id == cpco_user.id) or rec.env.user.has_group('discipline_management.group_discipline_cpco')
            if not is_cpco:
                continue

            ceo_name = (ceo_user.partner_id.name or ceo_user.name or _('CEO')).strip()
            cpco_name = rec.env.user.name
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Staff')
            emp_job = emp.job_id.name if emp and emp.job_id else ''
            dept_name = rec.sudo().department_id.name if rec.sudo().department_id else ''
            sanction_display = rec.get_sanction_display_text()
            article_display = rec.legal_article_display or (rec.offense_id and rec.offense_id.name) or _('Policy Clause')
            today_str = fields.Date.context_today(self).strftime('%B %d, %Y')

            msg_body = Markup(
                f"<p><strong>EXECUTIVE BRIEFING: COMMITTEE CASE ENFORCED BY CPCO</strong></p>"
                f"<p>Dear {ceo_name},</p>"
                f"<p>The Disciplinary Committee decision on Case <strong>{rec.name}</strong> has been officially approved and enforced by the Disciplinary Committee Chairman (CPCO):</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp_name}" + (f" ({emp_job}, {dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Violated Clause:</strong> {article_display}</li>"
                f"<li><strong>Enforced Sanction:</strong> <strong>{sanction_display}</strong></li>"
                f"<li><strong>Enforcing Authority:</strong> {cpco_name} (CPCO / Committee Chairman)</li>"
                f"<li><strong>Enforcement Date:</strong> {today_str}</li>"
                f"</ul>"
                f"<p>The statutory appeal window is now active. Full committee minutes and resolution are accessible on the case record.</p>"
            )

            rec.message_post(
                body=msg_body,
                partner_ids=[ceo_user.partner_id.id] if ceo_user.partner_id else False,
                subtype_xmlid='mail.mt_comment',
            )
            rec._post_discuss_dm(rec.env.user, ceo_user, msg_body, subscribe_case=True)

    @api.model
    def _cron_check_case_sla_deadlines(self):
        """Daily cron check to monitor stage SLAs and statutory prescription deadlines, alerting secretaries and reviewers."""
        active_cases = self.search([
            ('state', 'not in', ['closed', 'revoked', 'enforced'])
        ])
        for case in active_cases:
            case._compute_stage_sla_tracking()
            if case.sla_status in ('warning', 'overdue'):
                status_label = _('CRITICAL: CASE EXPIRING / OVERDUE') if case.sla_status == 'overdue' else _('WARNING: APPROACHING SLA DEADLINE')
                deadline_date = case.stage_deadline or case.prescription_deadline
                case.message_post(
                    body=Markup(_(
                        '<strong>%(status)s</strong><br/>'
                        'Disciplinary Case <strong>%(case_name)s</strong> (Current Stage: <strong>%(stage)s</strong>) '
                        'has been in this stage for %(days)d day(s). Target deadline: <strong>%(deadline)s</strong>.<br/>'
                        'Executive secretaries and reviewers are requested to expedite action to prevent prescription.'
                    ) % {
                        'status': status_label,
                        'case_name': case.name,
                        'stage': dict(case._fields['state'].selection).get(case.state, case.state),
                        'days': case.days_in_stage,
                        'deadline': deadline_date.strftime('%B %d, %Y') if deadline_date else 'Immediate',
                    }),
                    message_type='notification',
                    subtype_xmlid='mail.mt_comment',
                )

        # Dispatch consolidated executive & assistant morning digest via Discuss DM
        if hasattr(self, '_cron_case_expiration_followup_alerts'):
            self._cron_case_expiration_followup_alerts()

    def _notify_assigned_secretaries_on_routing(self, target_executive, stage_name=None):
        """
        Notify assigned secretaries when a case routes to their executive.
        Dispatches a confidential Discuss notification containing milestone flow and deadlines only.
        """
        for rec in self:
            if not target_executive:
                continue
            sec_users = target_executive.get_assigned_secretary_users()
            if not sec_users:
                continue

            base_url = rec.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            action_url = f"{base_url}/web#id={rec.id}&model=discipline.case&view_type=form" if base_url else f"/web#id={rec.id}&model=discipline.case&view_type=form"
            stage_display = stage_name or (dict(rec._fields['state'].selection).get(rec.state, rec.state) if 'state' in rec._fields else rec.state)
            deadline_str = rec.stage_deadline.strftime('%B %d, %Y') if rec.stage_deadline else _('Immediate')
            presc_str = rec.prescription_deadline.strftime('%B %d, %Y') if rec.prescription_deadline else _('Imminent')
            sender = rec.env.user or rec.env.ref('base.user_root')

            for sec in sec_users:
                if sec.id == target_executive.id:
                    continue
                body = Markup(
                    f"<div style='font-family: Arial, sans-serif; max-width: 650px;'>"
                    f"<p style='color: #856404; font-weight: bold; font-size: 14px;'>🔔 NEW CASE PENDING YOUR EXECUTIVE ({target_executive.name})</p>"
                    f"<p>Dear {sec.name},</p>"
                    f"<p>Disciplinary Case <strong>{rec.name}</strong> has been routed to <strong>{target_executive.name}</strong> for review and executive action in stage <strong>{stage_display}</strong>.</p>"
                    f"<table style='width: 100%; border: 1px solid #dee2e6; border-collapse: collapse; font-size: 13px; margin: 10px 0;'>"
                    f"  <tr style='background: #f8f9fa; border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Subject Employee</td><td style='padding: 6px;'>{rec.employee_id.name or '-'}</td></tr>"
                    f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Department / Branch</td><td style='padding: 6px;'>{rec.department_id.name or '-'}</td></tr>"
                    f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Current Stage</td><td style='padding: 6px;'>{stage_display}</td></tr>"
                    f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Stage SLA Target</td><td style='padding: 6px;'>{rec.stage_target_days} day(s) (Deadline: {deadline_str})</td></tr>"
                    f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Statutory Prescription Deadline</td><td style='padding: 6px; color: #dc3545; font-weight: bold;'>{presc_str}</td></tr>"
                    f"</table>"
                    f"<p style='margin-top: 12px;'>"
                    f"  <a href='{action_url}' style='background-color: #795548; color: #ffffff; padding: 7px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block; font-size: 12px;'>"
                    f"      👉 Open Case {rec.name} in Follow-up Tracker"
                    f"  </a>"
                    f"</p>"
                    f"<p style='color: #6c757d; font-size: 11px; margin-top: 10px; font-style: italic;'>"
                    f"  🔒 Confidentiality Mandate: Detailed misconduct allegations and evidence dossiers remain confidential to the reviewing executive."
                    f"</p>"
                    f"</div>"
                )
                rec._post_discuss_dm(sender, sec, body, subscribe_case=False)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _notify_thread_by_email(self, message, recipients_data, **kwargs):
        """
        Discipline Management Email Notification Gate:
        When email notifications are disabled in Discipline Settings,
        suppress external SMTP emails for all discipline models (discipline.*)
        to prevent SMTP delivery errors on test/dev environments without mail servers.
        In-app Discuss and Chatter activity remain fully functional.
        """
        is_discipline_record = (
            (self._name and self._name.startswith('discipline.')) or
            (message and message.model and message.model.startswith('discipline.'))
        )
        if is_discipline_record:
            ICP = self.env['ir.config_parameter'].sudo()
            enable_email = ICP.get_param('discipline.enable_email_notifications', default='False').strip().lower() in ('true', '1')
            if not enable_email:
                return True
        return super()._notify_thread_by_email(message, recipients_data, **kwargs)
