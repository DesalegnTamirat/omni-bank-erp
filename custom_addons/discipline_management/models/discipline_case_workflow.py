from datetime import timedelta
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class DisciplineCaseWorkflow(models.Model):
    _inherit = 'discipline.case'

    def action_delete_draft(self):
        """Allow creators to safely purge draft cases and redirect back to case list."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft cases can be deleted.'))
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Disciplinary Cases'),
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
        }

    def action_withdraw_initiated_case(self):
        """Allow creators to safely soft-delete (withdraw) initiated cases before escalation."""
        self.ensure_one()
        if self.state != 'initiated':
            raise UserError(_('Only initiated cases can be withdrawn/soft-deleted.'))
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Disciplinary Cases'),
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
        }

    def action_initiate(self):
        for rec in self:
            if not rec.description:
                raise UserError(_('Detailed Description is mandatory before initiating a case.'))
            # Governance Check: Committee escalation cases can only be initiated by Directors, Executive Authorities, Audit, or Admins
            if rec.case_action_track == 'committee_escalation':
                user = self.env.user
                is_authorized_initiator = (
                    rec.is_director_user or
                    rec.is_chief_user or
                    rec.is_ceo_user or
                    rec.is_cpco_user or
                    rec.is_pomd_user or
                    rec.is_hr_admin or
                    rec.is_auditor_user or
                    bool(rec.director_id and rec.director_id.id == user.id) or
                    bool(rec.chief_id and rec.chief_id.id == user.id) or
                    user.has_group('discipline_management.group_discipline_director') or
                    user.has_group('discipline_management.group_discipline_cpco') or
                    user.has_group('discipline_management.group_discipline_ceo') or
                    user.has_group('discipline_management.group_discipline_auditor') or
                    user.has_group('discipline_management.group_discipline_admin') or
                    user.has_group('base.group_system')
                )
                if not is_authorized_initiator:
                    raise UserError(_(
                        "Unauthorized Action Pathway: Only Directorate Directors and above executive authorities, "
                        "Internal Audit, or HR Administration can directly initiate a Formal Committee Escalation case. "
                        "Line Managers must use 'Escalate to Director Review' to route high-severity offenses through their Directorate Director."
                    ))

            # Governance Check: Coach Enforcement Authority Limit for Direct Action
            if rec.case_action_track == 'direct_enforce':
                cfg_punish, max_rank, allowed_levels = rec._get_coach_max_authority()
                punish_ranks = {
                    'verbal_warning': 1,
                    'first_warning_penalty': 2,
                    'second_warning_penalty': 3,
                    'final_warning_penalty': 4,
                    'demotion': 5,
                    'dismissal': 6,
                }
                sev_ranks = {
                    'level_5': 1,
                    'level_4': 2,
                    'level_3': 3,
                    'level_2': 4,
                    'level_1': 6,
                }
                case_punish_rank = punish_ranks.get(rec.punishment_type or rec.decided_punishment_type, 1)
                case_sev_rank = sev_ranks.get(rec.severity_level or (rec.severity_level_id and rec.severity_level_id.code), 1)
                if (case_punish_rank > max_rank) or (case_sev_rank > max_rank):
                    cfg_display = dict(self.env['res.config.settings']._fields['discipline_coach_max_punishment'].selection).get(cfg_punish, cfg_punish) if 'discipline_coach_max_punishment' in self.env['res.config.settings']._fields else cfg_punish
                    raise UserError(_(
                        "Coach Enforcement Authority Limit Exceeded:\n\n"
                        "Per Bank Disciplinary Governance Configuration, Direct Coaches / Line Managers are authorized to directly enforce sanctions up to: %s.\n\n"
                        "This offense (%s) carries a severity/sanction that exceeds your authorized sanction limit.\n\n"
                        "Please click the 'Escalate to Next Hierarchy' button to route this case for formal review."
                    ) % (cfg_display, rec.offense_id.name or rec.severity_level_id.name or ''))

            rec.with_context(force_write=True).write({'state': 'initiated'})
            partners_to_notify = []
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
            rep_sudo = rec.reported_by_id.sudo() if rec.reported_by_id else False
            if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                partners_to_notify.append(emp_sudo.user_id.partner_id.id)
            if rep_sudo and rep_sudo.user_id and rep_sudo.user_id.partner_id:
                partners_to_notify.append(rep_sudo.user_id.partner_id.id)
            rec.message_post(
                body=Markup(_('Disciplinary case <strong>%s</strong> initiated for employee %s.') % (rec.name, emp_sudo.name if emp_sudo else '')),
                partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
            )
            rec._send_employee_discuss_direct_message(message_type='initiate')

    def _get_group_users(self, xml_id):
        """Retrieve active users belonging to an XML-defined group in modern Odoo 19."""
        group = self.env.ref(xml_id, raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        return group.all_user_ids or group.user_ids or self.env['res.users']

    def action_coach_submit_to_director(self):
        """Submit the disciplinary case to the Directorate Director / Deputy Chief for intermediate review."""
        for rec in self:
            if not rec.description:
                raise UserError(_('Detailed Description is mandatory before escalating a case to the next hierarchy.'))
            if not rec.director_id:
                dir_u, chief_u = rec._resolve_case_hierarchy_stakeholders()
                rec.director_id = dir_u
                if not rec.chief_id and chief_u:
                    rec.chief_id = chief_u
            if rec.director_id:
                rec.sudo().with_context(force_write=True, force_escalate=True).write({
                    'case_action_track': 'committee_escalation',
                    'state': 'submitted_director',
                    'reviewer_id': rec.director_id.id,
                })
                partners_to_notify = []
                emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
                if rec.director_id.partner_id:
                    partners_to_notify.append(rec.director_id.partner_id.id)
                if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                    partners_to_notify.append(emp_sudo.user_id.partner_id.id)
                rec.message_post(
                    body=Markup(_('Case <strong>%s</strong> escalated to Formal Disciplinary Track and submitted to Next Hierarchy (%s) for review.') % (rec.name, rec.director_id.name)),
                    partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                )
                rec._send_employee_discuss_direct_message(message_type='initiate')
                rec._notify_assigned_secretaries_on_routing(rec.director_id, 'Director Review')
            else:
                # If no director in line, submit directly to Chief
                rec.sudo().with_context(force_write=True, force_escalate=True).write({
                    'case_action_track': 'committee_escalation',
                })
                rec.action_submit_to_chief()

    def action_director_forward_to_chief(self):
        """Director endorses and forwards the case to the Respective Chief Officer."""
        for rec in self:
            rec.action_submit_to_chief()

    def action_director_resolve(self):
        """Director directly resolves/enforces the case within departmental authority."""
        for rec in self:
            rec.action_approve_and_enforce()

    def action_submit_to_chief(self):
        """Submit the disciplinary case to the respective Chief Officer for review and escalation routing."""
        for rec in self:
            if not rec.chief_id:
                dir_u, chief_u = rec._resolve_case_hierarchy_stakeholders()
                rec.chief_id = chief_u
            rec.sudo().with_context(force_write=True, force_escalate=True).write({
                'case_action_track': 'committee_escalation',
                'state': 'submitted_chief',
                'reviewer_id': rec.chief_id.id if rec.chief_id else False,
                'chief_id': rec.chief_id.id if rec.chief_id else False
            })
            partners_to_notify = []
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
            if rec.chief_id and rec.chief_id.partner_id:
                partners_to_notify.append(rec.chief_id.partner_id.id)
            if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                partners_to_notify.append(emp_sudo.user_id.partner_id.id)
            rec.message_post(
                body=Markup(_('Case <strong>%s</strong> submitted to Respective Executive Officer (%s) for executive review.') % (rec.name, rec.chief_id.name if rec.chief_id else 'Executive Officer')),
                partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
            )
            rec._send_chief_submission_discuss_notification()
            if rec.chief_id:
                rec._notify_assigned_secretaries_on_routing(rec.chief_id, 'Chief Review')

    def action_chief_exonerate(self):
        """Chief Officer reviews and officially exonerates the employee, dropping all charges."""
        for rec in self:
            rec.with_context(force_write=True).write({
                'state': 'closed',
                'punishment_type': 'exonerate',
                'penalty_percentage': 0.0,
                'fine_days': 0.0,
                'active_duration_days': 0,
                'final_decision_date': fields.Date.context_today(self),
                'approver_id': self.env.user.id,
            })
            partners = []
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
            if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                partners.append(emp_sudo.user_id.partner_id.id)
            rec.message_post(
                body=Markup(_('Case <strong>%s</strong> officially Exonerated and Closed by Respective Chief Officer %s. Clean employment record maintained.') % (rec.name, self.env.user.name)),
                partner_ids=partners if partners else False,
            )
            rec._sync_linked_suspensions('exonerate')
            rec._send_chief_exoneration_discuss_notification()

    def action_chief_escalate_to_audit(self):
        """Disallowed per policy governance: Only CEO can refer cases to Internal Audit for investigation."""
        raise UserError(_("Authority Restriction: Executive Chiefs cannot directly refer cases to Internal Audit. Please refer the case to the Chief Executive Officer (CEO) for investigation referral."))

    def action_escalate_case(self):
        """
        Dynamically escalate the case step-by-step along the supervisory hierarchy.
        - If the next supervisor is an intermediate executive (e.g., Deputy Chief -> Chief):
          Update chief_id, retain state in 'submitted_chief', and notify the next executive.
        - If the next supervisor is the CEO (or top of the chain):
          Transition state to 'ceo_review', set escalation_target to 'ceo', and notify the CEO.
        """
        for rec in self:
            current_user = self.env.user
            if not (rec.is_case_chief_user or rec.is_hr_admin or current_user._is_superuser()):
                raise UserError(_("Authority Restriction: Only the active reviewing executive (%s) or HR Administrator can escalate this case.") % (rec.chief_id.name if rec.chief_id else _("Assigned Executive")))

            next_user, is_ceo, target_label = rec._get_next_escalation_supervisor()
            
            if is_ceo or not next_user:
                # Top-level executive escalation to CEO
                rec.escalation_target = 'ceo'
                rec.with_context(force_write=True).write({'state': 'ceo_review'})
                
                EmpModel = self.env['hr.employee'].sudo()
                ceo_user = EmpModel.get_ceo_user()
                target_user = next_user or ceo_user
                
                notification_body = _(
                    '<p>⚖️ <strong>Executive Case Escalation</strong></p>'
                    '<p>Case <strong>%s</strong> officially escalated by %s to Chief Executive Officer (CEO) %s for executive review.</p>'
                ) % (rec.name, current_user.name, target_user.name if target_user else "CEO")
                
                partners_to_notify = []
                if target_user and target_user.partner_id:
                    partners_to_notify.append(target_user.partner_id.id)
                emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
                if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                    partners_to_notify.append(emp_sudo.user_id.partner_id.id)
                    
                rec.message_post(
                    body=Markup(notification_body),
                    partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                )
                if target_user and target_user.partner_id:
                    rec._send_discuss_direct_message(current_user, target_user.partner_id, notification_body)
            else:
                # Step-by-step intermediate executive escalation (e.g. Deputy Chief -> Chief)
                rec.with_context(force_write=True).write({
                    'chief_id': next_user.id,
                    'state': 'submitted_chief',
                })
                
                notification_body = _(
                    '<p>⚖️ <strong>Executive Case Escalation</strong></p>'
                    '<p>Case <strong>%s</strong> escalated by %s to %s for executive review.</p>'
                ) % (rec.name, current_user.name, target_label)
                
                rec.message_post(
                    body=Markup(notification_body),
                    partner_ids=[next_user.partner_id.id] if next_user.partner_id else False,
                )
                if next_user.partner_id:
                    rec.sudo().message_subscribe(partner_ids=[next_user.partner_id.id])
                    rec._send_discuss_direct_message(current_user, next_user.partner_id, notification_body)
                    rec._notify_assigned_secretaries_on_routing(next_user)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Case Escalated'),
                'message': _('Disciplinary case has been successfully escalated to the next authority.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    action_chief_escalate_to_ceo = action_escalate_case

    def action_ceo_announce_audit_and_suspend(self):
        """CEO action: formally announce case to Audit Directorate for investigation and instruct Committee Secretary (POMD) to suspend the employee."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'investigating'})
            
            EmpModel = self.env['hr.employee'].sudo()
            audit_user = EmpModel.get_audit_director_user()
            sec_user = EmpModel.get_secretary_user()
            cpco_user = EmpModel.get_cpco_user()
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False

            is_mgr = rec.is_managerial or (rec.staff_category == 'managerial') or bool(emp_sudo and emp_sudo.is_managerial)
            suspending_auth_label = _('Chief People & Culture Officer (CPCO)') if is_mgr else _('Disciplinary Committee Secretary (POMD)')
            
            partners_to_notify = []
            if audit_user and audit_user.partner_id:
                partners_to_notify.append(audit_user.partner_id.id)
            if is_mgr:
                if cpco_user and cpco_user.partner_id:
                    partners_to_notify.append(cpco_user.partner_id.id)
            else:
                if sec_user and sec_user.partner_id:
                    partners_to_notify.append(sec_user.partner_id.id)
                if cpco_user and cpco_user.partner_id:
                    partners_to_notify.append(cpco_user.partner_id.id)
            if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                partners_to_notify.append(emp_sudo.user_id.partner_id.id)

            rec.message_post(
                body=Markup(_(
                    '<strong>CEO Executive Directive:</strong><br/>'
                    '1. Case officially assigned to Audit Directorate for formal investigation.<br/>'
                    '2. %s instructed to execute employee precautionary suspension.'
                )) % suspending_auth_label,
                partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
            )

            # 1. Create linked Investigation record if none exists
            if not rec.investigation_ids.sudo():
                self.env['discipline.investigation'].sudo().create({
                    'case_id': rec.id,
                    'title': _('Audit Investigation: %s') % rec.name,
                    'applicable_policy': rec.offense_id.name if rec.offense_id else _('Bank Disciplinary Policy'),
                    'summary_findings': False,
                    'investigator_recommendation': False,
                })

            # 2. Create Precautionary Suspension Record
            existing_suspension = rec.suspension_ids.sudo().filtered(lambda s: s.state != 'revoked')
            if not existing_suspension:
                start_dt = fields.Date.context_today(self)
                end_dt = self.env['discipline.suspension'].calculate_suspension_end_date(start_dt)
                self.env['discipline.suspension'].sudo().create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'suspension_type': 'without_pay',
                    'start_date': start_dt,
                    'end_date': end_dt,
                    'reason': _('Precautionary suspension pending audit investigation per CEO directive.'),
                    'initiating_unit': 'directorate',
                    'state': 'draft',
                })

            rec._send_ceo_announce_audit_discuss_notification()

    def action_ceo_assign_to_audit(self):
        """Backward compatibility alias for action_ceo_announce_audit_and_suspend."""
        return self.action_ceo_announce_audit_and_suspend()

    def action_ceo_forward_to_committee_chair(self):
        """CEO reviews audit report and forwards case and investigation to Disciplinary Committee Chairman (CPCO)."""
        for rec in self:
            if not (rec.is_ceo_user or rec.is_hr_admin or self.env.user._is_superuser()):
                raise UserError(_('Authority Restriction: Only the Chief Executive Officer (CEO) can forward cases to the Disciplinary Committee Chairman.'))

            cpco_user = self.env['hr.employee'].sudo().get_cpco_user()
            cpco_name = cpco_user.name if cpco_user else _('Chief People & Culture Officer')

            rec.with_context(force_write=True).write({
                'state': 'chairman_review',
            })
            # Transition linked investigations from submitted_ceo -> forwarded_cpco so CPCO gains visibility
            invs_to_forward = rec.investigation_ids.sudo().filtered(lambda i: i.state in ('submitted_ceo', 'approved'))
            if invs_to_forward:
                invs_to_forward.write({'state': 'forwarded_cpco'})
                for inv in invs_to_forward:
                    inv.message_post(
                        body=Markup(_(
                            'Investigation forwarded to Disciplinary Committee Chairman (%s) by CEO %s.'
                        ) % (cpco_name, self.env.user.name)),
                        partner_ids=[cpco_user.partner_id.id] if (cpco_user and cpco_user.partner_id) else False,
                    )

            rec.message_post(
                body=Markup(_(
                    'Case and Audit Investigation forwarded by Chief Executive Officer (CEO: %s) to Disciplinary Committee Chairman (CPCO: %s) for review.'
                ) % (self.env.user.name, cpco_name)),
                partner_ids=[cpco_user.partner_id.id] if (cpco_user and cpco_user.partner_id) else False,
            )
            rec._send_ceo_forward_to_chair_discuss_notification()

    def action_chair_forward_to_secretary(self):
        """Disciplinary Committee Chairman (CPCO) reviews case and forwards to Committee Secretary (POMD) for scheduling hearing."""
        for rec in self:
            if not (rec.is_cpco_user or rec.is_hr_admin or rec.is_ceo_user or self.env.user._is_superuser()):
                raise UserError(_('Authority Restriction: Only the Disciplinary Committee Chairman (CPCO) can forward cases to the Committee Secretary for meeting scheduling.'))
            rec.with_context(force_write=True).write({
                'state': 'committee_review',
                'is_locked_for_committee': True,
            })
            # Transition linked investigations to 'approved' so POMD and Committee Panel Members gain access
            invs_to_release = rec.investigation_ids.sudo().filtered(lambda i: i.state in ('submitted_ceo', 'forwarded_cpco'))
            if invs_to_release:
                invs_to_release.write({'state': 'approved'})

            sec_user = self.env['hr.employee'].sudo().get_secretary_user()
            sec_name = sec_user.name if sec_user else _('People Operations Management Director')
            ceo_user = self.env['hr.employee'].sudo().get_ceo_user()
            
            partners_to_notify = []
            if sec_user and sec_user.partner_id:
                partners_to_notify.append(sec_user.partner_id.id)
            if ceo_user and ceo_user.partner_id:
                partners_to_notify.append(ceo_user.partner_id.id)

            rec.message_post(
                body=Markup(_(
                    '<strong>CPCO Action — Case &amp; Investigation Referred to Committee Secretary (POMD):</strong><br/>'
                    '• Decision Maker: %s (CPCO)<br/>'
                    '• Action: Case referred to Committee Secretary (%s) to schedule the formal committee hearing.<br/>'
                    '• Status: Locked for Committee Review (committee_review)'
                ) % (self.env.user.name, sec_name)),
                partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
            )
            # Tag & notify secretary on released investigations
            if invs_to_release and sec_user and sec_user.partner_id:
                for inv in invs_to_release:
                    inv.message_post(
                        body=Markup(_(
                            '<strong>Investigation Dossier Released to Committee Secretary:</strong><br/>'
                            '• Released by: %s (Disciplinary Committee Chairman / CPCO)<br/>'
                            '• Assigned Secretary: <strong>%s (POMD)</strong><br/>'
                            '• Action Required: Schedule Disciplinary Committee Hearing and Summon Panel<br/>'
                            '• Status: Released to Committee / POMD (approved)'
                        ) % (self.env.user.name, sec_name)),
                        partner_ids=[sec_user.partner_id.id],
                    )

            rec._send_chair_forward_to_secretary_discuss_notification()

    def action_ceo_forward_to_committee(self):
        """Forward directly to committee chair."""
        return self.action_ceo_forward_to_committee_chair()

    def action_cpco_endorse_exoneration(self):
        """CPCO / Executive Action: officially endorse Audit Directorate Exoneration findings, close case, and revoke suspensions."""
        for rec in self:
            if not (rec.is_cpco_user or rec.is_hr_admin or rec.is_ceo_user):
                raise UserError(_('Authority Restriction: Only the Chief People & Culture Officer (CPCO) or CEO can endorse exonerations.'))
            rec.with_context(force_write=True).write({
                'state': 'closed',
                'punishment_type': 'exonerate',
                'final_decision_date': fields.Date.context_today(self),
                'approver_id': self.env.user.id,
            })

            # Revert any disciplinary markings on employee
            if rec.employee_id:
                rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                    'active_disciplinary_action': False,
                    'is_ineligible_for_promotion_transfer': False,
                    'is_suspended': False,
                    'suspension_type': False,
                })

            # Revoke linked suspensions & restore ERP access/backpay
            rec._sync_linked_suspensions('exonerate')

            # Multi-stakeholder notifications
            ceo_user = self.env['hr.employee'].sudo().get_ceo_user()
            audit_user = self.env['hr.employee'].sudo().get_audit_director_user()
            sec_user = self.env['hr.employee'].sudo().get_secretary_user()

            partners_to_notify = []
            if ceo_user and ceo_user.partner_id:
                partners_to_notify.append(ceo_user.partner_id.id)
            if audit_user and audit_user.partner_id:
                partners_to_notify.append(audit_user.partner_id.id)
            if sec_user and sec_user.partner_id:
                partners_to_notify.append(sec_user.partner_id.id)
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
            if emp_sudo and emp_sudo.user_id and emp_sudo.user_id.partner_id:
                partners_to_notify.append(emp_sudo.user_id.partner_id.id)

            rec.message_post(
                body=_(
                    '<strong>Executive Action — Case Exonerated &amp; Closed:</strong><br/>'
                    '• Decision Maker: %s (CPCO / Executive Authority)<br/>'
                    '• Employee: %s<br/>'
                    '• Decision: The Audit Directorate investigation findings of <strong>No Fault Found (Exonerated)</strong> have been officially endorsed.<br/>'
                    '• Immediate Effects: All precautionary suspensions are revoked, full salary backpay and ERP access are restored, and the case is closed with immediate effect.'
                ) % (self.env.user.name, emp_sudo.name if emp_sudo else _('Employee')),
                partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
            )

    def action_ceo_endorse_exoneration(self):
        """Backward compatibility alias for action_cpco_endorse_exoneration."""
        return self.action_cpco_endorse_exoneration()

    def action_start_investigation(self):
        for rec in self:
            rec.reviewer_id = self.env.user
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('Investigation process started by %s.') % self.env.user.name)

    def action_send_to_committee(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'committee_review', 'is_locked_for_committee': True})
            rec.message_post(body=_('Case submitted for Disciplinary Committee Review and locked for feedback.'))

    def action_committee_feedback_received(self):
        """Unlock case when committee feedback is received and notify HR officer."""
        for rec in self:
            rec.with_context(force_write=True).write({'is_locked_for_committee': False})
            rec.message_post(body=_('Committee feedback received. Case unlocked for review.'))

    def action_schedule_committee_meeting(self):
        """Open form to schedule a Disciplinary Committee Meeting pre-populated with panel members."""
        self.ensure_one()
        existing_meeting = self.committee_meeting_ids.filtered(lambda m: m.state not in ('completed', 'cancelled'))[:1]
        if existing_meeting:
            return self.action_open_active_committee_meeting()

        EmpModel = self.env['hr.employee'].sudo()
        case_sudo = self.sudo()
        emp = case_sudo.employee_id
        ceo_user = EmpModel.get_ceo_user()
        ceo_user_id = ceo_user.id if ceo_user else False
        
        # 1. Chairperson: CPCO
        cpco_user = EmpModel.get_cpco_user()
        
        # 2. Respective Director (Case Initiator / Reporting Director who escalated, never CEO)
        resp_dir_user = False
        if case_sudo.director_id and case_sudo.director_id.id != ceo_user_id:
            resp_dir_user = case_sudo.director_id
        elif case_sudo.reported_by_id and case_sudo.reported_by_id.sudo().user_id and case_sudo.reported_by_id.sudo().user_id.id != ceo_user_id:
            resp_dir_user = case_sudo.reported_by_id.sudo().user_id
        elif emp and emp.department_id and emp.department_id.sudo().manager_id and emp.department_id.sudo().manager_id.sudo().user_id:
            mgr_u = emp.department_id.sudo().manager_id.sudo().user_id
            if mgr_u.id != ceo_user_id:
                resp_dir_user = mgr_u
        if not resp_dir_user and emp:
            for sup in emp.sudo().get_supervisor_chain():
                if sup.sudo().user_id and sup.sudo().user_id.id != ceo_user_id:
                    if sup.sudo().executive_level in ('director', 'chief') or 'director' in (sup.sudo().job_id.name or '').lower():
                        resp_dir_user = sup.sudo().user_id
                        break

        # 3. Legal Member
        legal_user = EmpModel.get_legal_user()
        
        # 4. Secretary: POMD
        sec_user = EmpModel.get_secretary_user()
        
        # 5. Union Rep
        union_user = EmpModel.get_union_user()

        seen_uids = set()
        member_ids = []
        for u in [cpco_user, resp_dir_user, legal_user, sec_user, union_user]:
            if u and u.id not in seen_uids:
                seen_uids.add(u.id)
                member_ids.append(u.id)

        default_vals = {
            'default_case_id': self.id,
            'default_is_case_readonly': True,
            'default_committee_chair_id': cpco_user.id if cpco_user else False,
            'default_respective_director_id': resp_dir_user.id if resp_dir_user else False,
            'default_legal_director_id': legal_user.id if legal_user else False,
            'default_pomd_secretary_id': sec_user.id if sec_user else False,
            'default_labour_union_rep_id': union_user.id if union_user else False,
            'default_member_ids': [(6, 0, member_ids)],
            'default_present_members_count': 0,
        }

        return {
            'name': _('Schedule Committee Meeting — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'view_mode': 'form',
            'target': 'current',
            'context': default_vals,
        }

    def action_open_active_committee_meeting(self):
        """Open the active/in-progress committee meeting linked to this case, validating the scheduled date."""
        self.ensure_one()
        meeting = self.committee_meeting_ids.filtered(lambda m: m.state not in ('completed', 'cancelled'))[:1]
        if not meeting:
            meeting = self.committee_meeting_ids[:1]
        if not meeting:
            return self.action_schedule_committee_meeting()

        today = fields.Date.context_today(self)
        if meeting.state == 'scheduled' and meeting.meeting_date and today < meeting.meeting_date:
            raise UserError(_(
                "Premature Hearing Access: The Disciplinary Committee meeting is scheduled for %(meeting_date)s. "
                "Today is %(today)s. The hearing session cannot be opened before the scheduled meeting date. "
                "If the hearing must be held earlier, the Committee Secretary (POMD) must reschedule the meeting date."
            ) % {
                'meeting_date': format_date(self.env, meeting.meeting_date),
                'today': format_date(self.env, today),
            })

        return {
            'name': _('Committee Meeting — %s') % meeting.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'res_id': meeting.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_submit_for_approval(self):
        recom_to_punishment = {
            'dismissal': 'dismissal',
            'final_warning': 'final_warning_penalty',
            'second_warning': 'second_warning_penalty',
            'first_warning': 'first_warning_penalty',
            'verbal_warning': 'verbal_warning',
            'demotion': 'demotion',
            'exonerate': 'exonerate',
            'custom': 'custom',
        }
        for rec in self:
            completed_meeting = rec.committee_meeting_ids.filtered(lambda m: m.state == 'completed' and m.final_recommendation)
            if not completed_meeting and not rec.decided_punishment_type:
                raise UserError(_('A completed Committee Meeting with a finalized recommendation is required before submitting for approval.'))
            if not rec.decided_punishment_type and not rec.punishment_type:
                if completed_meeting:
                    punish_val = recom_to_punishment.get(completed_meeting[-1].final_recommendation, completed_meeting[-1].final_recommendation)
                    rec.with_context(force_write=True).write({
                        'decided_punishment_type': punish_val,
                        'punishment_type': punish_val,
                    })
                else:
                    raise UserError(_('Please assign the Committee Decided Punishment before submitting for final executive approval.'))
            rec.with_context(force_write=True).write({'state': 'pending_approval', 'is_locked_for_committee': False})
            rec.message_post(body=_('Disciplinary case and decided punishment submitted for final executive approval.'))

    def action_return_revision(self):
        """Return case to Initiator / Line Manager for revision."""
        for rec in self:
            if rec.state not in ['pending_approval', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Only cases under review/pending approval can be returned for revision.'))
            rec.with_context(force_write=True).write({'state': 'draft'})
            rec.message_post(body=_('Case returned to Initiator for revision by %s.') % self.env.user.name)

    def action_reject(self):
        """Reject disciplinary case."""
        for rec in self:
            if rec.state not in ['pending_approval', 'initiated', 'investigating', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Case cannot be rejected in its current state.'))
            rec.with_context(force_write=True).write({'state': 'closed'})
            rec._sync_linked_suspensions('exonerate')
            rec.message_post(body=_('Disciplinary case rejected and closed by %s.') % self.env.user.name)

    def action_acknowledge_receipt(self):
        """Record official delivery and acknowledgment of the disciplinary notice, starting the appeal window."""
        for rec in self:
            rec.delivery_receipt_date = fields.Date.context_today(self)
            rec.message_post(body=_('Disciplinary decision letter delivery acknowledged on %s. 10-day appeal countdown is active.') % rec.delivery_receipt_date)

    def action_approve_and_enforce(self):
        """Enforces the disciplinary penalty (Coach/Manager direct enforcement for Levels 2-5, or Committee/Executive enforcement)."""
        for rec in self:
            current_user = self.env.user
            # For Coach Direct Enforcement track (not formal escalation)
            if rec.case_action_track == 'direct_enforce':
                if not rec.severity_level_id:
                    raise UserError(_('Severity Level is required for Coach Direct Enforcement.'))
                if not rec.description:
                    raise UserError(_('Detailed Description of Misconduct is required before enforcing this case.'))
                cfg_punish, max_rank, allowed_levels = self._get_coach_max_authority()
                
                punish_ranks = {
                    'verbal_warning': 1,
                    'first_warning_penalty': 2,
                    'second_warning_penalty': 3,
                    'final_warning_penalty': 4,
                    'demotion': 5,
                    'dismissal': 6,
                }
                sev_ranks = {
                    'level_5': 1,
                    'level_4': 2,
                    'level_3': 3,
                    'level_2': 4,
                    'level_1': 6,
                }
                case_punish_rank = punish_ranks.get(rec.punishment_type or rec.decided_punishment_type, 1)
                case_sev_rank = sev_ranks.get(rec.severity_level or (rec.severity_level_id and rec.severity_level_id.code), 1)

                is_exceeded = (case_punish_rank > max_rank) or (case_sev_rank > max_rank)
                if is_exceeded:
                    if (not current_user.has_group('discipline_management.group_discipline_admin') and 
                        not current_user.has_group('discipline_management.group_discipline_ceo') and 
                        not current_user.has_group('discipline_management.group_discipline_cpco')):
                        
                        cfg_display = dict(self.env['res.config.settings']._fields['discipline_coach_max_punishment'].selection).get(cfg_punish, cfg_punish) if 'discipline_coach_max_punishment' in self.env['res.config.settings']._fields else cfg_punish
                        raise UserError(_(
                            'Coach Direct Enforcement Authority Limit Exceeded:\n\n'
                            'Per Bank Disciplinary Governance Configuration, Direct Coaches / Line Managers are authorized to directly enforce sanctions up to: %s.\n\n'
                            'This disciplinary case involves: %s (%s), which exceeds your direct enforcement authority.\n'
                            'Please route/escalate this case to the Respective Chief / Executive Disciplinary Committee.'
                        ) % (cfg_display, rec.severity_level_id.name or rec.severity_level, rec.punishment_type or rec.decided_punishment_type))
            else:
                # Committee-escalated / Pending Approval track: CPCO (Committee Chairman), CEO, or HR Admin can approve and enforce
                if not (rec.is_cpco_user or rec.is_ceo_user or rec.is_hr_admin or current_user._is_superuser()):
                    raise UserError(_(
                        'Authority Restriction: Only the Disciplinary Committee Chairman (CPCO), Chief Executive Officer (CEO), or HR Admin is authorized to approve and enforce Disciplinary Committee decisions.'
                    ))
                if not rec.severity_level_id and not rec.decided_punishment_type and not rec.punishment_type:
                    raise UserError(_('Severity Level and Final Decided Punishment must be assigned before enforcing this case.'))

            # Digital Signature Validation & Auto-Population
            if not rec.is_exonerated_case and (not rec.signatory_signature or len(rec.signatory_signature) < 50):
                user_saved_sig = getattr(current_user, 'discipline_digital_signature', False) or getattr(current_user, 'digital_signature', False)
                if not user_saved_sig:
                    prev_case = self.search([
                        ('signatory_signature', '!=', False),
                        '|', ('initiator_id', '=', current_user.id), ('create_uid', '=', current_user.id)
                    ], order='id desc', limit=1)
                    if prev_case and prev_case.signatory_signature:
                        user_saved_sig = prev_case.signatory_signature
                if user_saved_sig:
                    rec.with_context(force_write=True).write({'signatory_signature': user_saved_sig})
                else:
                    if rec.case_action_track == 'direct_enforce':
                        raise UserError(_(
                            "Mandatory Digital Signature Required:\n\n"
                            "Enforcing without signature is prevented. As the Line Manager / Supervisor enforcing this disciplinary decision, "
                            "you must draw or load your digital signature under 'Digital Sign-off' before enforcing the official disciplinary notice."
                        ))
                    else:
                        raise UserError(_(
                            "Mandatory Digital Signature Required:\n\n"
                            "Enforcing without signature is prevented. As the Executive Authority (CPCO / CEO) approving and enforcing this "
                            "Disciplinary Committee decision, you must provide your digital signature under 'Digital Sign-off' before enforcing this case."
                        ))

            # Final validation check
            if not rec.is_exonerated_case and (not rec.signatory_signature or len(rec.signatory_signature) < 50):
                raise UserError(_(
                    "Mandatory Digital Signature Required:\n\n"
                    "Enforcing without signature is prevented. An authentic digital signature must be provided under 'Digital Sign-off'."
                ))

            # Auto-persist signature to user profile so future cases never ask again
            if rec.signatory_signature and not getattr(current_user, 'discipline_digital_signature', False):
                try:
                    current_user.sudo().write({'discipline_digital_signature': rec.signatory_signature})
                except Exception:
                    pass

            rec.signatory_id = current_user
            rec.approver_id = current_user
            rec._validate_segregation_of_duties()

            # Verify linked committee meetings are completed with quorum (only if committee route)
            if rec.committee_meeting_ids:
                for meeting in rec.committee_meeting_ids:
                    if meeting.state != 'completed' or not meeting.is_quorum_met:
                        raise UserError(_('Cannot enforce case decision. Linked committee meeting (%s) must be in Completed state with valid panel quorum.') % meeting.name)

            rec.final_decision_date = fields.Date.context_today(self)
            if not rec.delivery_receipt_date:
                rec.delivery_receipt_date = rec.final_decision_date
            rec.with_context(force_write=True).write({'state': 'enforced'})

            # Update employee disciplinary record and set internal mobility restrictions
            is_ineligible = (
                rec.severity_level in ['level_1', 'level_2'] or
                rec.punishment_type in ['dismissal', 'demotion', 'final_warning_penalty']
            )
            emp_sudo = rec.sudo().employee_id
            emp_sudo.with_context(no_leave_resource_calendar_update=True).write({
                'active_disciplinary_action': True,
                'is_ineligible_for_promotion_transfer': is_ineligible,
                'disciplinary_warning_count': emp_sudo.disciplinary_warning_count + 1,
                'last_disciplinary_date': rec.final_decision_date,
            })

            # Demotion handling (generates draft record in Employee Service for HR placement)
            if rec.is_demotion_decided or rec.punishment_type == 'demotion' or rec.decided_punishment_type == 'demotion':
                rec.action_apply_demotion()

            # Immediate Payroll Deduction: Financial penalties are scheduled immediately upon enforcement
            # regardless of whether the appeal window is open or what the appeal status is.
            is_dismissal = (rec.punishment_type == 'dismissal' or rec.decided_punishment_type == 'dismissal')
            has_financial_penalty = (
                (not rec.is_managerial and rec.penalty_percentage > 0.0) or
                (rec.is_managerial and rec.fine_days > 0.0) or
                (is_dismissal and bool(rec.suspension_ids.filtered(lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed', 'converted_dismissal'])))
            )
            if has_financial_penalty:
                rec.with_context(force_write=True).write({'deduction_status': 'scheduled'})
                rec._generate_immediate_payroll_penalty_line()
            else:
                rec.with_context(force_write=True).write({'deduction_status': 'not_applicable'})
                self.env['discipline.payroll.penalty'].sudo().search([
                    ('case_id', '=', rec.id),
                    ('state', '=', 'pending')
                ]).unlink()

            # Dismissal Handling & Separation Workflow (Only triggered when final sanction is dismissal)
            is_dismissal = (rec.punishment_type == 'dismissal' or rec.decided_punishment_type == 'dismissal')
            if is_dismissal:
                rec._sync_linked_suspensions('dismissal')
                rec.action_approve_dismissal()
            elif rec.punishment_type == 'exonerate' or rec.decided_punishment_type == 'exonerate':
                rec._sync_linked_suspensions('exonerate')
            else:
                # For non-dismissal decisions (Demotion, Warnings, Fines), auto-reinstate any active precautionary suspensions
                rec._sync_linked_suspensions('reinstate')

            # Fast executive notification to chatter and Discuss direct message to employee
            rec._post_enforcement_notification()
            rec._send_employee_discuss_direct_message(message_type='enforce')
            if hasattr(rec, '_dispatch_cc_stakeholder_notifications'):
                rec._dispatch_cc_stakeholder_notifications()

            # Only for Disciplinary Committee track cases enforced by CPCO, formally brief CEO
            is_committee_enforcement = (
                rec.case_action_track == 'committee' or bool(rec.committee_meeting_ids)
            ) and rec.case_action_track != 'direct_enforce'
            if is_committee_enforcement and not rec.is_ceo_user and hasattr(rec, '_send_committee_enforcement_ceo_notification'):
                rec._send_committee_enforcement_ceo_notification()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Decision Enforced'),
                'message': _('Disciplinary Case %s has been successfully enforced.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model
    def _compute_target_payroll_month(self, target_date=None):
        """
        Returns the immediate payroll month and year for the enforcement date without any mid-month (Day 15) cutoff delay.
        When payroll runs (typically on the 23rd of the month), any penalty enforced beforehand is automatically deducted.
        Returns tuple: (month_str '1'-'12', target_year int)
        """
        if not target_date:
            target_date = fields.Date.today()
        return str(target_date.month), target_date.year

    def _process_appeal_window_deductions(self):
        return self.action_process_appeal_window_deductions()

    def action_process_appeal_window_deductions(self):
        """
        Ensures payroll penalty lines are synchronized with the current enforced penalty on the case.
        Does NOT apply any Day-15 cutoff delay or appeal-window freeze.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state not in ('enforced', 'closed', 'appealed'):
                continue

            is_dismissal_case = (rec.punishment_type == 'dismissal' or rec.decided_punishment_type == 'dismissal')
            has_financial_penalty = (
                (not rec.is_managerial and rec.penalty_percentage > 0.0) or
                (rec.is_managerial and rec.fine_days > 0.0) or
                (is_dismissal_case and bool(rec.suspension_ids.filtered(lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed', 'converted_dismissal'])))
            )
            if not has_financial_penalty:
                if rec.deduction_status not in ('refund_scheduled', 'refunded'):
                    rec.deduction_status = 'not_applicable'
                pending_pens = self.env['discipline.payroll.penalty'].sudo().search([
                    ('case_id', '=', rec.id),
                    ('transaction_type', '=', 'deduction'),
                    ('state', '=', 'pending')
                ])
                if pending_pens:
                    pending_pens.unlink()
                continue

            eff_date = rec.final_decision_date or today
            target_month, _target_year = self._compute_target_payroll_month(eff_date)

            if not rec.payroll_month:
                rec.payroll_month = target_month
            rec.computed_deduction_month = rec.payroll_month or target_month

            existing_penalties = self.env['discipline.payroll.penalty'].sudo().search([
                ('case_id', '=', rec.id),
                ('transaction_type', '=', 'deduction'),
            ])
            month_dict = dict(rec._fields['payroll_month'].selection) if 'payroll_month' in rec._fields else {}
            month_display = month_dict.get(rec.payroll_month or target_month, str(rec.payroll_month or target_month))

            # If a deduction has already been transferred or deducted in payslip, do not overwrite it here
            processed_deductions = existing_penalties.filtered(lambda p: p.state in ('transferred', 'deducted'))
            if processed_deductions:
                continue

            # 1. Percentage / Managerial Sanction Deduction (still pending)
            percentage_pens = existing_penalties.filtered(lambda p: p.penalty_type in ('percentage', 'managerial') and p.state == 'pending')
            pen_vals = False
            if not rec.is_managerial and rec.penalty_percentage > 0.0:
                pen_vals = {
                    'penalty_type': 'percentage',
                    'penalty_percentage': rec.penalty_percentage,
                    'managerial_days': 0,
                    'effective_date': eff_date,
                    'payroll_month': rec.payroll_month or target_month,
                    'notes': _('Enforced percentage penalty of %s%% for Case %s (Payroll Month: %s).') % (
                        rec.penalty_percentage, rec.name, month_display
                    ),
                }
            elif rec.is_managerial and rec.fine_days > 0.0:
                pen_vals = {
                    'penalty_type': 'managerial',
                    'penalty_percentage': 0.0,
                    'managerial_days': int(rec.fine_days),
                    'effective_date': eff_date,
                    'payroll_month': rec.payroll_month or target_month,
                    'notes': _('Enforced managerial penalty of %d day(s) for Case %s (Payroll Month: %s).') % (
                        int(rec.fine_days), rec.name, month_display
                    ),
                }

            if pen_vals:
                if percentage_pens:
                    percentage_pens[0].write(pen_vals)
                    if len(percentage_pens) > 1:
                        percentage_pens[1:].unlink()
                else:
                    pen_vals.update({
                        'case_id': rec.id,
                        'employee_id': rec.employee_id.id,
                        'transaction_type': 'deduction',
                        'state': 'pending',
                    })
                    self.env['discipline.payroll.penalty'].sudo().create(pen_vals)
            elif rec.penalty_percentage == 0.0 and rec.fine_days == 0.0:
                percentage_pens.write({
                    'penalty_percentage': 0.0,
                    'managerial_days': 0,
                    'state': 'cancelled',
                    'notes': _('Penalty cancelled / waived following exoneration for Case %s.') % rec.name
                })

            # 2. Unpaid suspension deductions: Applicable ONLY for Dismissals.
            is_dismissal_case = (rec.punishment_type == 'dismissal' or rec.decided_punishment_type == 'dismissal')
            active_swp = rec.suspension_ids.filtered(
                lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed', 'converted_dismissal']
            )
            existing_swp_pens = self.env['discipline.payroll.penalty'].sudo().search([
                ('case_id', '=', rec.id),
                ('penalty_type', '=', 'suspension_without_pay')
            ])
            if is_dismissal_case:
                for susp in active_swp:
                    swp_for_susp = existing_swp_pens.filtered(lambda p: p.suspension_id.id == susp.id)
                    if not swp_for_susp:
                        self.env['discipline.payroll.penalty'].sudo().create({
                            'case_id': rec.id,
                            'employee_id': rec.employee_id.id,
                            'transaction_type': 'deduction',
                            'penalty_type': 'suspension_without_pay',
                            'suspension_id': susp.id,
                            'suspension_days': susp.working_days_count,
                            'effective_date': eff_date,
                            'payroll_month': rec.payroll_month or target_month,
                            'state': 'pending',
                            'notes': _('Enforced without-pay suspension deduction for %d days for Case %s (Payroll Month: %s - Dismissal).') % (
                                susp.working_days_count, rec.name, month_display
                            )
                        })
            else:
                pending_swp = existing_swp_pens.filtered(lambda p: p.state == 'pending')
                if pending_swp:
                    pending_swp.unlink()

            if not has_financial_penalty:
                if rec.deduction_status not in ('refund_scheduled', 'refunded'):
                    rec.deduction_status = 'not_applicable'
            elif rec.deduction_status not in ('transferred', 'deducted', 'refund_scheduled', 'refunded'):
                rec.deduction_status = 'scheduled'

    _process_appeal_window_deductions = action_process_appeal_window_deductions

    @api.model
    def _cron_process_appeal_window_deductions(self):
        """Legacy cron compatibility: ensures any legacy appeal_pending cases are immediately scheduled."""
        cases = self.search([
            ('state', 'in', ['enforced', 'closed']),
            ('deduction_status', '=', 'appeal_pending'),
        ])
        if cases:
            cases._process_appeal_window_deductions()

    def action_coach_exonerate_attendance(self):
        """Allows direct coach / manager to exonerate an auto-initiated attendance case upon reviewing valid justification."""
        self.ensure_one()
        if not self.is_system_generated:
            raise UserError(_('Only system-generated attendance cases can be exonerated directly by the coach.'))
        if self.state not in ('draft', 'initiated'):
            raise UserError(_('Case cannot be exonerated in current state.'))
        
        self.write({
            'state': 'closed',
            'is_revoked': True,
            'revocation_reason': _('Exonerated by Direct Coach / Manager upon review of attendance justification.'),
            'revocation_date': fields.Date.context_today(self),
            'revoked_by_id': self.env.user.id,
            'deduction_status': 'cancelled',
            'punishment_type': 'exonerate',
            'penalty_percentage': 0.0,
            'fine_days': 0.0,
        })
        self._sync_linked_suspensions('exonerate')
        self.message_post(body=_('Attendance disciplinary case exonerated and closed by Direct Coach (%s). Zero penalty applied.') % self.env.user.name)

    def _generate_immediate_payroll_penalty_line(self):
        """Immediately instantiates discipline.payroll.penalty record upon enforcement for immediate payroll deduction.
        No Day-15 cutoff calculation is applied; the effective date is the enforcement date itself so payroll
        automatically deducts it in the current payroll run (even if enforced on the 22nd before the 23rd payroll run).
        """
        for rec in self:
            today = fields.Date.context_today(rec)
            target_month = str(today.month)
            rec.payroll_month = target_month
            rec.computed_deduction_month = target_month
        self.action_process_appeal_window_deductions()

    def action_apply_demotion(self):
        """Generate a draft record in Employee Service (employee.demotion) for HR placement.
        The Disciplinary Committee determines demotion; HR handles selecting the new position,
        grade, and location in Employee Services."""
        for rec in self:
            emp = rec.employee_id.sudo()
            case_updates = {}
            if not rec.previous_job_id and emp.job_id:
                case_updates['previous_job_id'] = emp.job_id.id

            if 'employee.demotion' in self.env:
                DemotionModel = self.env['employee.demotion'].sudo()
                # Check if a demotion record already exists for this case
                existing_demotion = DemotionModel.search([
                    ('employee_name', '=', emp.id),
                    ('disciplinary_case_ref', '=', rec.name),
                    ('state', '!=', 'cancel'),
                ], limit=1)
                if not existing_demotion:
                    demot_vals = {
                        'employee_name': emp.id,
                        'reason': 'discipline',
                        'disciplinary_case_ref': rec.name,
                        'change_date': rec.final_decision_date or fields.Date.context_today(self),
                        'debarment_months': 12,
                        'demotion_type': 'all',
                        'state': 'draft',
                    }
                    existing_demotion = DemotionModel.create(demot_vals)

                case_updates['demotion_id'] = existing_demotion.id
                if case_updates:
                    rec.sudo().with_context(force_write=True).write(case_updates)

                rec.message_post(body=_(
                    "Disciplinary Demotion Sanction Enforced: Draft Demotion Record '%s' generated in Employee Service. "
                    "HR will review and assign the new position, grade, and work unit."
                ) % (existing_demotion.ref_num or existing_demotion.id))

    def action_approve_dismissal(self):
        """Execute final approval of Level 1 Dismissal, triggering separation and revoking system access."""
        for rec in self:
            rec._sync_linked_suspensions('dismissal')
            rec._process_employee_dismissal()

    def _process_employee_dismissal(self):
        """Handle separation and access revocation with extensible hook."""
        for rec in self:
            emp = rec.sudo().employee_id
            write_vals = {'active': False}
            departure_reason = self.env.ref('hr.departure_fired', raise_if_not_found=False)
            if departure_reason and 'departure_reason_id' in emp._fields:
                write_vals['departure_reason_id'] = departure_reason.id
            if 'departure_date' in emp._fields:
                write_vals['departure_date'] = rec.final_decision_date
            if 'departure_description' in emp._fields:
                write_vals['departure_description'] = _('Dismissed under Disciplinary Case %s on %s.') % (rec.name, rec.final_decision_date)
            emp.sudo().with_context(no_leave_resource_calendar_update=True).write(write_vals)
            if emp.user_id:
                emp.user_id.sudo().write({'active': False})
                rec.message_post(body=_('System user access for user %s disabled due to dismissal.') % emp.user_id.name)

            rec._on_employee_dismissed(emp)

    def _on_employee_dismissed(self, employee):
        """Extensible event hook for separation management module integration."""
        Separation = self.env.get('hr.separation') or self.env.get('employee.separation')
        if Separation:
            Separation.sudo().create({
                'employee_id': employee.id,
                'separation_type': 'dismissal',
                'case_id': self.id,
                'reason': _('Disciplinary dismissal under Case %s.') % self.name,
            })

    def action_open_revocation_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Revocation Authority Violation: Only HR Administrators can initiate case revocation.'))
        if self.is_exonerated_case or self.punishment_type == 'exonerate' or self.appeal_outcome_type == 'exonerated':
            raise UserError(_('Invalid Action: Case "%s" has already been fully exonerated on appeal. An exonerated case has no active penalties and cannot be revoked.') % self.name)
        return {
            'name': _('Revoke Disciplinary Case'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.revocation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id}
        }

    def _validate_appeal_submission_access(self, is_on_behalf=False):
        """Validate whether current user is authorized to submit a direct or on-behalf appeal."""
        self.ensure_one()
        current_user = self.env.user
        if is_on_behalf:
            if not (current_user.has_group('discipline_management.group_discipline_pomd') or
                    current_user.has_group('discipline_management.group_discipline_admin') or
                    current_user.has_group('base.group_system')):
                raise UserError(_('Authority Restriction: Only the People Operations Management Directorate (POMD) or HR Administrator can lodge an appeal on behalf of an employee.'))
            is_dismissal = (self.severity_level == 'level_1' or self.punishment_type == 'dismissal' or self.decided_punishment_type == 'dismissal')
            if not is_dismissal:
                raise UserError(_('Appeals on behalf of employees can only be lodged for dismissal cases. For other disciplinary sanctions, the employee must submit the appeal directly.'))
        else:
            emp = self.sudo().employee_id
            is_emp = bool(
                (emp and emp.user_id and emp.user_id.id == current_user.id) or
                (current_user.sudo().employee_id and current_user.sudo().employee_id.id == emp.id) or
                (hasattr(current_user, 'employee_ids') and emp and emp.id in current_user.sudo().employee_ids.ids)
            )
            if not is_emp:
                raise UserError(_('Appeal Access Restriction: Direct appeals can only be submitted by the employee (%s) subject to this disciplinary case.') % (emp.name if emp else _('Staff')))

    def _action_open_appeal_wizard(self, level='first', is_on_behalf=False):
        self.ensure_one()

        # 1. Active appeal validation: ensure no other appeal is currently active on this case
        active_appeals = self.appeal_ids.filtered(lambda a: a.state in ('draft', 'submitted', 'under_review'))
        if active_appeals:
            act_app = active_appeals[0]
            act_state = dict(act_app._fields['state'].selection).get(act_app.state, act_app.state)
            act_level = dict(act_app._fields['appeal_level'].selection).get(act_app.appeal_level, act_app.appeal_level)
            raise UserError(_(
                'Active Appeal in Progress: Case "%(case)s" already has an active appeal (Ref: %(ref)s, %(level)s Stage) '
                'currently in "%(state)s" status.\n\n'
                'Under Bank Disciplinary Policy, only one active appeal can exist at a time. '
                'The pending appeal must be formally decided before another appeal can be requested.'
            ) % {
                'case': self.name,
                'ref': act_app.name,
                'level': act_level,
                'state': act_state,
            })

        # 2. Sequential completion validation
        parent_appeal = False
        if level == 'second':
            first_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
            if not first_appeal:
                raise UserError(_('A 1st Level Appeal must exist before submitting a 2nd Level Appeal.'))
            if first_appeal[0].state != 'decided':
                raise UserError(_('The 1st Level Appeal (%s) must be decided before submitting a 2nd Level Appeal.') % first_appeal[0].name)
            parent_appeal = first_appeal[0]
        elif level == 'third':
            second_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
            if not second_appeal:
                raise UserError(_('A 2nd Level Appeal must exist before submitting a 3rd Level Appeal.'))
            if second_appeal[0].state != 'decided':
                raise UserError(_('The 2nd Level Appeal (%s) must be decided before submitting a 3rd Level Appeal.') % second_appeal[0].name)
            parent_appeal = second_appeal[0]
        elif level == 'fourth':
            third_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'third')
            if not third_appeal:
                raise UserError(_('A 3rd Level Appeal must exist before submitting a 4th Level Appeal.'))
            if third_appeal[0].state != 'decided':
                raise UserError(_('The 3rd Level Appeal (%s) must be decided before submitting a 4th Level Appeal.') % third_appeal[0].name)
            parent_appeal = third_appeal[0]

        title = _('Submit Appeal for Case %s') % self.name
        if is_on_behalf:
            title = _('Lodge Appeal on Behalf of %s') % (self.sudo().employee_id.name if self.sudo().employee_id else _('Staff'))

        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_parent_appeal_id': parent_appeal.id if parent_appeal else False,
                'default_appeal_level': level,
                'default_is_submitted_on_behalf': is_on_behalf,
                'default_submitted_by_id': self.env.user.id if is_on_behalf else False,
                'default_submission_date': fields.Date.context_today(self),
                'discipline_scope': True,
            }
        }

    def action_create_appeal(self):
        self._validate_appeal_submission_access(is_on_behalf=False)
        if any(a.acceptance_state in ('accepted', 'window_closed') for a in self.appeal_ids):
            raise UserError(_('Appeal decision has already been formally accepted and finalized for this case. Further appeals cannot be submitted.'))
        level = self.next_appeal_level or 'first'
        if level == 'first' and not self.is_appeal_window_open:
            raise UserError(_(
                'Appeal Window Closed: The 10-calendar-day appeal submission window has expired. '
                'Appeal deadline was %s.'
            ) % (self.appeal_deadline or 'N/A'))
        return self._action_open_appeal_wizard(level=level, is_on_behalf=False)

    def action_create_second_appeal(self):
        self._validate_appeal_submission_access(is_on_behalf=False)
        return self._action_open_appeal_wizard(level='second', is_on_behalf=False)

    def action_create_third_appeal(self):
        self._validate_appeal_submission_access(is_on_behalf=False)
        return self._action_open_appeal_wizard(level='third', is_on_behalf=False)

    def action_create_fourth_appeal(self):
        self._validate_appeal_submission_access(is_on_behalf=False)
        return self._action_open_appeal_wizard(level='fourth', is_on_behalf=False)

    def action_create_appeal_on_behalf(self):
        self._validate_appeal_submission_access(is_on_behalf=True)
        level = self.next_appeal_level or 'first'
        return self._action_open_appeal_wizard(level=level, is_on_behalf=True)

    def action_create_second_appeal_on_behalf(self):
        self._validate_appeal_submission_access(is_on_behalf=True)
        return self._action_open_appeal_wizard(level='second', is_on_behalf=True)

    def action_create_third_appeal_on_behalf(self):
        self._validate_appeal_submission_access(is_on_behalf=True)
        return self._action_open_appeal_wizard(level='third', is_on_behalf=True)

    def action_create_fourth_appeal_on_behalf(self):
        self._validate_appeal_submission_access(is_on_behalf=True)
        return self._action_open_appeal_wizard(level='fourth', is_on_behalf=True)

    def action_view_appeals(self):
        self.ensure_one()
        return {
            'name': _('Appeals — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id, 'discipline_scope': True},
        }

    def action_view_investigations(self):
        self.ensure_one()
        return {
            'name': _('Audit Investigations — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.investigation',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {
                'default_case_id': self.id,
                'default_employee_id': self.employee_id.id if self.employee_id else False,
                'default_offense_id': self.offense_id.id if self.offense_id else False,
            },
        }

    def action_view_committee_meetings(self):
        self.ensure_one()
        return {
            'name': _('Committee Meetings — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def action_view_suspensions(self):
        self.ensure_one()
        return {
            'name': _('Suspensions — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.suspension',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def _sync_linked_suspensions(self, outcome):
        """
        Option 1: Case-driven automated suspension synchronization.
        outcome: 'dismissal', 'exonerate', 'reinstate'
        """
        for rec in self:
            active_suspensions = rec.suspension_ids.sudo().filtered(
                lambda s: s.state in ('active', 'extended', 'pending_approval', 'referred_bod', 'converted_dismissal')
            )
            if not active_suspensions:
                continue
            for susp in active_suspensions:
                if outcome == 'dismissal':
                    susp.write({
                        'state': 'converted_dismissal',
                        'backpay_status': 'not_applicable',
                    })
                    susp.message_post(
                        body=_('Precautionary suspension automatically converted to DISMISSAL following final case verdict (%s).') % rec.name
                    )
                elif outcome == 'exonerate':
                    susp.sudo().with_context(force_reinstate=True).action_revoke_exonerated()
                elif outcome == 'reinstate':
                    susp.sudo().with_context(force_reinstate=True).action_reinstate_employee()

    def action_audit_submit_to_ceo(self):
        """Internal Audit Directorate submits audit-initiated case directly to CEO."""
        for rec in self:
            rec.write({
                'state': 'ceo_review',
                'case_action_track': 'audit_referral',
            })
            rec.message_post(body=_('Case %s submitted by Internal Audit Directorate directly to Chief Executive Officer (CEO) for executive review.') % rec.name)
