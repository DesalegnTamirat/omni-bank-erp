# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CommitteeMinuteSignWizard(models.TransientModel):
    _name = "committee.minute.sign.wizard"
    _description = "Committee Minute Digital Signature Wizard"

    minute_type = fields.Selection([
        ('recruitment', 'Recruitment Digital Selection Minute'),
        ('transfer', 'Transfer Committee Minute'),
        ('vacancy_delegation', 'Vacancy Approval Delegation'),
    ], string="Minute Type", required=True, readonly=True)

    recruitment_signature_id = fields.Many2one(
        "recruitment.committee.signature", string="Recruitment Signature Line", readonly=True
    )
    transfer_signature_id = fields.Many2one(
        "transfer.committee.signature", string="Transfer Signature Line", readonly=True
    )
    delegation_line_id = fields.Many2one(
        "vacancy.delegation.team", string="Vacancy Delegation Line", readonly=True
    )

    signatory_user_id = fields.Many2one(
        "res.users", string="Designated Signatory User", readonly=True, required=True
    )
    signatory_employee_id = fields.Many2one(
        "hr.employee", string="Signatory Employee", readonly=True
    )
    signatory_role = fields.Char(string="Committee Role", readonly=True)
    minute_reference = fields.Char(string="Minute Reference", readonly=True)

    has_saved_signature = fields.Boolean(
        string="Has Saved Master Signature", compute="_compute_saved_signature", store=False
    )
    saved_signature_preview = fields.Binary(
        string="Saved Signature Preview", compute="_compute_saved_signature", store=False
    )

    signature_mode = fields.Selection([
        ('saved', 'Use My Saved Master Signature (Base64)'),
        ('new', 'Draw / Upload New Signature'),
    ], string="Signature Mode", default='saved', required=True)

    new_signature = fields.Binary(
        string="Draw / Upload Digital Signature", copy=False, attachment=False,
        help="Draw your signature on the canvas or upload an image."
    )
    update_master_signature = fields.Boolean(
        string="Save / Update as my default signature in Employee Master",
        default=True,
        help="If checked, this signature will be stored in your Employee Master record (Base64) for future 1-click committee signings."
    )
    comments = fields.Text(string="Remarks / Comments")

    @api.depends('signatory_user_id')
    def _compute_saved_signature(self):
        for rec in self:
            user = self.env.user
            emp = user.employee_id or (user.employee_ids and user.employee_ids[0])
            sig = emp.digital_signature if (emp and emp.digital_signature) else False
            rec.has_saved_signature = bool(sig)
            rec.saved_signature_preview = sig

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')

        sig_line = False
        if active_model == 'recruitment.committee.signature':
            sig_line = self.env['recruitment.committee.signature'].browse(active_id)
            res['minute_type'] = 'recruitment'
            res['recruitment_signature_id'] = sig_line.id
            res['signatory_user_id'] = sig_line.user_id.id
            res['signatory_role'] = sig_line.role_label or sig_line.role or 'Committee Member'
            res['minute_reference'] = sig_line.minute_id.name if sig_line.minute_id else ''
        elif active_model == 'transfer.committee.signature':
            sig_line = self.env['transfer.committee.signature'].browse(active_id)
            res['minute_type'] = 'transfer'
            res['transfer_signature_id'] = sig_line.id
            res['signatory_user_id'] = sig_line.user_id.id
            res['signatory_role'] = sig_line.role_label or 'Committee Member'
            res['minute_reference'] = sig_line.minutes_id.name if sig_line.minutes_id else ''
        elif active_model == 'vacancy.delegation.team':
            sig_line = self.env['vacancy.delegation.team'].browse(active_id)
            user = sig_line.employee_name or sig_line.alternate_committee_member
            res['minute_type'] = 'vacancy_delegation'
            res['delegation_line_id'] = sig_line.id
            res['signatory_user_id'] = user.id if user else False
            res['signatory_role'] = getattr(sig_line, 'role', 'Committee Member')
            res['minute_reference'] = sig_line.vac_del_id.reference if sig_line.vac_del_id else ''

        # STRICT SECURITY ENFORCEMENT:
        # Only the designated signatory user can view or sign this slot
        signatory_uid = res.get('signatory_user_id')
        if signatory_uid and signatory_uid != self.env.user.id and not self.env.is_superuser():
            designated = self.env['res.users'].browse(signatory_uid)
            raise UserError(_(
                "Unauthorized Signature Access: The signature line for '%(role)s' is strictly designated for '%(user)s'. "
                "You are currently logged in as '%(current)s'. You cannot access or sign on behalf of another user."
            ) % {
                'role': res.get('signatory_role') or 'Committee Member',
                'user': designated.name,
                'current': self.env.user.name,
            })

        user = self.env.user
        emp = user.employee_id or (user.employee_ids and user.employee_ids[0])
        res['signatory_employee_id'] = emp.id if emp else False
        has_sig = bool(emp and emp.digital_signature)
        res['signature_mode'] = 'saved' if has_sig else 'new'
        res['update_master_signature'] = True
        return res

    def action_confirm_sign(self):
        self.ensure_one()
        # 1. Security Check
        if self.signatory_user_id != self.env.user and not self.env.is_superuser():
            raise UserError(_(
                "Unauthorized Signature Error: You are logged in as '%(current)s', but this signature slot is designated for '%(owner)s'."
            ) % {
                'current': self.env.user.name,
                'owner': self.signatory_user_id.name,
            })

        user = self.env.user
        emp = user.employee_id or (user.employee_ids and user.employee_ids[0])
        final_sig = False

        if self.signature_mode == 'saved':
            if not emp or not emp.digital_signature:
                raise UserError(_(
                    "No saved signature found in your Employee Master record. "
                    "Please switch to 'Draw / Upload New Signature' to create your signature."
                ))
            final_sig = emp.digital_signature
        else:
            if not self.new_signature:
                raise UserError(_("Please draw or upload your digital signature in the canvas before confirming."))
            final_sig = self.new_signature

            # Store / update in employee master as Base64 if option is selected or if first time
            if self.update_master_signature or not (emp and emp.digital_signature):
                target_emps = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)])
                if not target_emps and emp:
                    target_emps = emp
                if target_emps:
                    target_emps.sudo().write({
                        'digital_signature': final_sig,
                        'digital_signature_updated_on': fields.Datetime.now(),
                    })

        now_dt = fields.Datetime.now()

        # 1. Recruitment Digital Selection Minute
        if self.minute_type == 'recruitment' and self.recruitment_signature_id:
            sig = self.recruitment_signature_id
            vals = {
                'digital_signature': final_sig,
                'signature_img': final_sig,
                'state': 'signed',
                'signed_on': now_dt,
                'signed_date': now_dt,
            }
            if self.comments:
                vals['comments'] = self.comments
            sig.sudo().write(vals)
            sig._sync_signature_to_recruitment_delegation()
            if sig.minute_id:
                sig.minute_id.sudo().message_post(
                    body=_("Digital signature recorded for <b>%s</b> (%s).") % (sig.role_label or sig.role or 'Committee Member', user.name)
                )
                sig.minute_id._check_auto_approval()

        # 2. Transfer Committee Minute
        elif self.minute_type == 'transfer' and self.transfer_signature_id:
            sig = self.transfer_signature_id
            vals = {
                'digital_signature': final_sig,
                'state': 'signed',
                'signed_on': now_dt,
            }
            if self.comments:
                vals['comments'] = self.comments
            sig.sudo().write(vals)

            # Close mail activity for signer
            activities = self.env['mail.activity'].sudo().search([
                ('res_model', '=', 'transfer.committee.minutes'),
                ('res_id', '=', sig.minutes_id.id),
                ('user_id', '=', user.id),
            ])
            for act in activities:
                try:
                    act.sudo().action_feedback(feedback=_("Digitally signed as %s") % (sig.role_label or 'Member'))
                except Exception:
                    pass

            if sig.minutes_id:
                sig.minutes_id.sudo().message_post(
                    body=_("Digital signature recorded for <b>%s</b> (%s).") % (sig.role_label or 'Member', user.name)
                )
                sig.minutes_id._compute_is_fully_signed()

        # 3. Vacancy Delegation Team
        elif self.minute_type == 'vacancy_delegation' and self.delegation_line_id:
            line = self.delegation_line_id
            vals = {
                'approve': True,
                'digital_signature': final_sig,
            }
            if hasattr(line, 'signed_on'):
                vals['signed_on'] = now_dt
            line.sudo().write(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Digital Signature Recorded'),
                'message': _('Your signature has been successfully applied to the committee minute.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
