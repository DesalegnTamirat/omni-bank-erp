# -*- coding: utf-8 -*-
"""Loan agreement (ውል) – Part A (borrower) and Part B (guarantor).

Extends resl.loan and resl.loan.guarantee WITHOUT touching their own files:
  * stores what each person typed and the drawn signatures,
  * builds the data the agreement page needs (/resl/agreement/<loan_id>),
  * blocks the three workflow steps until the matching part is done:
        guarantor  -> Accept           needs Part B filled + signed
        borrower   -> Submit to Mgr    needs Part A filled + signed
        approver   -> Approve          needs the bank signature
    (switch all three off with system parameter  resl.agreement_required = 0).
"""
import base64
import json
import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

BRANCH_TYPES = ('branch', 'sub_branch', 'service_center')
_BM_LEVEL = {'i': 1, '1': 1, 'ii': 2, '2': 2, 'iii': 3, '3': 3}

ETH = re.compile(r'[ሀ-፿]')
DATE_RE = re.compile(r'^[ሀ-፿]+\s+\d{1,2}\s*(ቀን|,)?\s*\d{4}\s*ዓ\.ም$')
PHONE_RE = re.compile(r'^[0-9+\-\s()]{7,}$')
TAX_DASH_RE = re.compile(r'^-{1,3}$')
TAX_ID_RE = re.compile(r'^[0-9A-Za-z\-]{6,}$')
PNG_PREFIX = 'data:image/png;base64,'
MAX_SIG_BYTES = 400 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
ALLOWED_MIME = ('image/png', 'image/jpeg', 'application/pdf')
FILE_TAG = 'resl_agreement'

# field id used by the page -> rule.  Every one of these is mandatory.
# Part A (borrower): name is typed in Amharic; city / sub-city / woreda / house
# no. / tax ID / ID no. accept ANY value (the borrower types "-" or anything if
# he or she does not have it) - they only have to be non-empty.
REQUESTER_RULES = {
    'a_date': 'date', 'a_name': 'am', 'a_city': 'any', 'a_subcity': 'any',
    'a_woreda': 'any', 'a_house': 'any', 'a_phone': 'phone', 'a_tax': 'any',
    'a_emp': 'any', 'a_amtw': 'am', 'a_start': 'date', 'a_instw': 'am',
}
GUARANTOR_RULES = {
    'b_date': 'date', 'b_name': 'am', 'b_address': 'am', 'b_house': 'any',
    'b_tax': 'tax', 'b_emp': 'any', 'b_phone': 'phone', 'b_bdate': 'date',
    'b_amtw': 'am', 'b_branch1': 'am', 'b_branch2': 'am',
}


def _check(values, rules):
    errs = {}
    for key, rule in rules.items():
        v = (values.get(key) or '').strip()
        if not v:
            errs[key] = 'required'
        elif rule == 'am' and not ETH.search(v):
            errs[key] = 'amharic'
        elif rule == 'date' and not DATE_RE.match(v):
            errs[key] = 'date'
        elif rule == 'phone' and not PHONE_RE.match(v):
            errs[key] = 'phone'
        elif rule == 'tax' and not (TAX_DASH_RE.match(v) or TAX_ID_RE.match(v)):
            errs[key] = 'tax'
    return errs


def _loads(text):
    try:
        data = json.loads(text or '{}')
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _clean_sig(data_url):
    """data URL -> base64 bytes for a Binary field. None = not supplied."""
    if not data_url:
        return None
    if not isinstance(data_url, str) or not data_url.startswith(PNG_PREFIX):
        raise UserError(_("The signature must be a PNG image."))
    raw = base64.b64decode(data_url[len(PNG_PREFIX):])
    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > MAX_SIG_BYTES:
        raise UserError(_("Invalid signature image."))
    return base64.b64encode(raw)


def _to_url(binary):
    return (PNG_PREFIX + binary.decode()) if binary else ''


class ReslLoan(models.Model):
    _inherit = 'resl.loan'

    agr_data = fields.Text(string="Agreement – Part A data", copy=False)
    agr_sig_borrower = fields.Binary(string="Borrower signature", attachment=True, copy=False)
    agr_borrower_signed_on = fields.Datetime(copy=False)
    agr_sig_bank = fields.Binary(string="Bank approver signature", attachment=True, copy=False)
    agr_bank_signed_by = fields.Many2one('res.users', string="Bank signed by", copy=False)
    agr_bank_signed_on = fields.Datetime(copy=False)

    agr_borrower_complete = fields.Boolean(compute='_compute_agr_flags')
    agr_bank_signed = fields.Boolean(compute='_compute_agr_flags')
    agr_can_open = fields.Boolean(compute='_compute_agr_can_open')
    # What the CURRENT user has to do on the agreement (drives the buttons /
    # banners on the loan form): requester | guarantor | approver | viewer,
    # and whether his / her own part is still open.
    agr_role = fields.Selection(
        [('requester', 'Requester'), ('guarantor', 'Guarantor'),
         ('approver', 'Approver'), ('viewer', 'Viewer')],
        compute='_compute_agr_role')
    agr_todo = fields.Boolean(compute='_compute_agr_role')

    # Users (disbursement officer / HR Auditor ...) who have opened the agreement
    # on this loan AFTER it was approved. Mandatory before requesting or doing
    # the disbursement.
    agr_viewer_ids = fields.Many2many(
        'res.users', 'resl_loan_agr_viewer_rel', 'loan_id', 'user_id',
        string="Agreement viewed by", copy=False)
    # True when the current user has to open the agreement before acting.
    agr_view_pending = fields.Boolean(compute='_compute_agr_view_pending')

    # ── computes ────────────────────────────────────────────────────────
    @api.depends('agr_data', 'agr_sig_borrower', 'agr_sig_bank')
    def _compute_agr_flags(self):
        for loan in self:
            loan.agr_borrower_complete = bool(
                loan.agr_sig_borrower and not _check(_loads(loan.agr_data), REQUESTER_RULES))
            loan.agr_bank_signed = bool(loan.agr_sig_bank)

    @api.depends('name', 'custom_saved')
    def _compute_agr_can_open(self):
        for loan in self:
            loan.agr_can_open = bool(loan.id and loan.custom_saved and loan.name != 'New')

    @api.depends_context('uid')
    @api.depends('status', 'employee_id.user_id', 'designated_approver_id',
                 'agr_data', 'agr_sig_borrower', 'agr_sig_bank',
                 'guarantor_line_ids.state', 'guarantor_line_ids.active',
                 'guarantor_line_ids.agr_data', 'guarantor_line_ids.agr_sig_guarantor')
    def _compute_agr_role(self):
        required = self._agr_required()
        user = self.env.user
        for loan in self:
            role, todo = 'viewer', False
            if not loan.id:
                # brand-new, unsaved request: only the requester sees it
                if loan.employee_id and loan.employee_id.user_id == user:
                    role, todo = 'requester', True
            else:
                role, line = loan._agr_resolve()
                status = loan.sudo().status
                if role == 'requester':
                    todo = (status in ('draft', 'guarantor_pending', 'rejected')
                            and not loan.agr_borrower_complete)
                elif role == 'guarantor':
                    todo = bool(line and line.state == 'pending' and not line.agr_complete)
                elif role == 'approver':
                    todo = status == 'manager_review' and not loan.agr_bank_signed
            loan.agr_role = role
            loan.agr_todo = bool(todo and required)

    # ── mandatory viewing before requesting / doing the disbursement ─────
    def _agr_can_request_disb(self, user):
        return bool(user._resl_has_group('resl.group_resl_hr_auditor')
                    or user._resl_has_group('resl.group_resl_hr')
                    or user.has_group('base.group_system'))

    def _agr_view_needed(self, user=None, step=None):
        """Must `user` still open the agreement before `step`
        ('request' = Request Disbursement, 'disburse' = disburse, None = either)?"""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        if (not loan.id or not self._agr_required() or loan.status != 'approved'
                or loan.core_banking_status == 'disbursed'
                or user in loan.agr_viewer_ids):
            return False
        acts = []
        if not loan.disbursement_requested and self._agr_can_request_disb(user):
            acts.append('request')
        if (loan.disbursement_requested or loan._live_disbursement_officer()) \
                and loan._user_can_disburse(user):
            acts.append('disburse')
        return bool(acts) if step is None else step in acts

    def _agr_check_viewed(self, step):
        for loan in self:
            if loan._agr_view_needed(step=step):
                raise ValidationError(_(
                    "You must open and review the loan agreement before %s.\n\n"
                    "Press the 'Agreement' button on the loan form, read it, then try again."
                ) % (_("requesting the disbursement") if step == 'request' else _("disbursing this loan")))

    def _agr_mark_viewed(self):
        """Called when the agreement page is opened. Only counts once the loan
        is approved, so what is reviewed is the final, bank-signed agreement."""
        self.ensure_one()
        loan = self.sudo()
        user = self.env.user
        if loan.status == 'approved' and user not in loan.agr_viewer_ids:
            loan.write({'agr_viewer_ids': [(4, user.id)]})
            loan.message_post(body=_("%s reviewed the loan agreement.") % user.name)

    @api.depends_context('uid')
    @api.depends('status', 'core_banking_status', 'disbursement_requested', 'agr_viewer_ids')
    def _compute_agr_view_pending(self):
        for loan in self:
            loan.agr_view_pending = bool(loan.id and loan._agr_view_needed())

    def _agr_required(self):
        return self.env['ir.config_parameter'].sudo().get_param('resl.agreement_required', '1') == '1'

    # ── who is the current user on this agreement? ──────────────────────
    def _agr_resolve(self, line_id=None, user=None):
        """-> (role, guarantee line). role: requester | guarantor | approver | viewer."""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        lines = loan.guarantor_line_ids.filtered(
            lambda l: l.active and l.state in ('draft', 'pending', 'accepted'))
        if loan.employee_id.user_id == user:
            line = lines.filtered(lambda l: l.id == line_id) or lines[:1]
            return 'requester', line[:1]
        mine = lines.filtered(lambda l: l.guarantor_id.user_id == user)
        if mine:
            # A guarantor who is ALSO the bank approver of this request: while
            # his / her own Part B is still open (pending) they act as the
            # guarantor; once that is done they must be able to sign as the bank.
            if not mine.filtered(lambda l: l.state == 'pending') and loan._agr_can_sign_bank(user):
                return 'approver', (mine[:1] if not line_id else (mine.filtered(lambda l: l.id == line_id) or mine[:1]))
            return 'guarantor', mine[:1]
        line = lines.filtered(lambda l: l.id == line_id) or lines[:1]
        if loan._agr_can_sign_bank(user):
            return 'approver', line[:1]
        return 'viewer', line[:1]

    def _agr_is_admin(self, user=None):
        """RESL Admin role or Odoo Administrator (own role or a delegated one)."""
        user = user or self.env.user
        try:
            return bool(user.has_group('base.group_system') or user._resl_is_admin())
        except Exception:
            return bool(user.has_group('base.group_system'))

    def _agr_is_designated(self, user):
        """Is `user` the approver this loan is routed to (or a delegate of them)?"""
        loan = self.sudo()
        target = loan.designated_approver_id or loan.manager_user_id
        return bool(target and target.id in user._resl_effective_user_ids())

    def _agr_can_sign_bank(self, user):
        """May `user` sign the BANK part of the agreement (both signature boxes)?

        Strictly the person this request is routed to - nobody else:
          * the designated approver (Branch Manager / District Director /
            Accountant / RESL District / HO Approver / HR Approver, whichever
            the routing picked for THIS loan) or someone they delegated to,
          * RESL Admin / Odoo Administrator, at any stage.
        Holding a RESL role is not enough: a Branch Manager cannot sign a
        district or head-office request, an HO/HR approver cannot sign a branch
        request, a District Director cannot sign another unit's request.
        The borrower never signs for the bank.
        The stored approver may be stale, so it is re-resolved live before
        saying no.
        """
        self.ensure_one()
        loan = self.sudo()
        borrower_user = loan.employee_id.user_id
        if borrower_user and borrower_user.id == user.id:
            return False
        if loan._agr_is_admin(user):
            return True
        if loan.status != 'manager_review':
            return False
        if loan._agr_is_designated(user):
            return True
        try:
            with self.env.cr.savepoint():
                loan._compute_designated_approver()
        except Exception:
            _logger.exception("Agreement: could not refresh the approver of loan %s", loan.id)
        return loan._agr_is_designated(user)

    def _agr_why_not_approver(self, user=None):
        """Plain-language reason shown on the page to someone who expected to
        sign as the bank approver but is only a viewer."""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        if loan.status != 'manager_review':
            return ''
        target = loan.designated_approver_id or loan.manager_user_id
        who = target.name if target else _("nobody could be found")
        return _("This request is waiting for %(who)s (%(role)s). Only that approver, "
                 "someone they delegated to, or an Admin can sign here. If you should be "
                 "the approver, check your user's Staff Loan (RESL) role, job title and operating "
                 "unit, then ask the borrower's HR to re-save the borrower's employee record.") % {
            'who': who, 'role': loan.designated_approver_role or _("approver")}

    def _agr_editable(self, role, line):
        loan = self.sudo()
        if role == 'requester':
            return loan.status in ('draft', 'guarantor_pending', 'rejected')
        if role == 'guarantor':
            return bool(line) and line.state == 'pending'
        if role == 'approver':
            return loan.status == 'manager_review' or self._agr_is_admin(self.env.user)
        return False

    # ── values filled by the system ─────────────────────────────────────
    def _agr_system_values(self):
        self.ensure_one()
        loan = self.sudo()
        emp = loan.employee_id
        amount = loan.approved_amount or loan.requested_amount or 0.0
        term = int(loan.loan_term_months or 0) or 1
        # ADJUST: use whichever field holds your "employee ID" (መታወቂያ ቁጥር)
        code = ''
        for fname in ('employee_code', 'employee_number', 'identification_id', 'barcode'):
            if fname in emp._fields and emp[fname]:
                code = str(emp[fname])
                break
        return {
            'borrower': emp.name or '',
            'empId': code,
            'amount': '{:,.2f}'.format(amount),
            'installment': '{:,.2f}'.format(amount / term),
        }

    def _agr_files(self):
        self.ensure_one()
        atts = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'resl.loan'), ('res_id', '=', self.id),
            ('description', '=', FILE_TAG)], order='id')
        return [{
            'id': a.id, 'name': a.name, 'type': a.mimetype,
            'url': '/web/content/%d?filename=%s' % (a.id, a.name),
            'by': a.create_uid.name, 'at': fields.Datetime.to_string(a.create_date),
        } for a in atts]

    def _agr_config(self, line_id=None):
        """Everything the agreement page needs, as a JSON-able dict."""
        self.ensure_one()
        loan = self.sudo()
        role, line = self._agr_resolve(line_id)
        values = dict(_loads(loan.agr_data))
        values.update(_loads(line.agr_data) if line else {})
        sigs = {
            'sig_borrower': _to_url(loan.agr_sig_borrower),
            'sig_bank_a': _to_url(loan.agr_sig_bank),
            'sig_bank_b': _to_url(loan.agr_sig_bank),
            'sig_guarantor': _to_url(line.agr_sig_guarantor) if line else '',
        }
        all_lines = loan.guarantor_line_ids.filtered(
            lambda l: l.active and l.state in ('draft', 'pending', 'accepted')).sorted('id')
        # One copy of Part B (guarantee pages) per guarantor.  A guarantor only
        # ever receives his / her own copy; everybody else gets all of them.
        part_lines = (line if role == 'guarantor' else all_lines)
        editable = self._agr_editable(role, line)
        parts = [{
            'lineId': l.id,
            'name': l.guarantor_id.name or '',
            'state': l.state,
            'values': {k: v for k, v in _loads(l.agr_data).items() if v},
            'sig': _to_url(l.agr_sig_guarantor),
            'complete': bool(l.agr_complete),
            'editable': bool(role == 'guarantor' and editable and l.id == line.id),
        } for l in part_lines]
        # Dynamic PDF & text layout from admin configuration
        pdf_cfg = self.env['resl.pdf.config'].get_active_config()
        return {
            'loanId': loan.id,
            'ref': loan.name,
            'role': role,
            'lineId': line.id if line else 0,
            'lines': [{'id': l.id, 'name': l.guarantor_id.name, 'state': l.state} for l in all_lines],
            'parts': parts,
            'editable': editable,
            'system': self._agr_system_values(),
            'values': {k: v for k, v in values.items() if v},
            'sigs': {k: v for k, v in sigs.items() if v},
            'files': self._agr_files(),
            'status': {
                'requester': loan.agr_borrower_complete,
                'guarantor': bool(line and line.agr_complete),
                'approver': loan.agr_bank_signed,
            },
            'pdf': pdf_cfg,
            'why': self._agr_why_not_approver() if role == 'viewer' else '',
        }

    # ── save (called by the controller) ─────────────────────────────────
    def agr_save(self, role_claimed, values, sigs, line_id=None):
        self.ensure_one()
        role, line = self._agr_resolve(line_id)
        if role != role_claimed or not self._agr_editable(role, line):
            raise UserError(_("You cannot edit this part of the agreement now."))
        loan = self.sudo()
        values = values if isinstance(values, dict) else {}
        sigs = sigs if isinstance(sigs, dict) else {}
        now = fields.Datetime.now()
        if role == 'requester':
            clean = {k: str(values.get(k) or '')[:300] for k in REQUESTER_RULES}
            vals = {'agr_data': json.dumps(clean, ensure_ascii=False)}
            sig = _clean_sig(sigs.get('sig_borrower'))
            if sig:
                vals.update(agr_sig_borrower=sig, agr_borrower_signed_on=now)
            loan.write(vals)
            errors = _check(clean, REQUESTER_RULES)
            if not (loan.agr_sig_borrower):
                errors['sig_borrower'] = 'required'
            who = _("Part A (borrower)")
        elif role == 'guarantor':
            clean = {k: str(values.get(k) or '')[:300] for k in GUARANTOR_RULES}
            vals = {'agr_data': json.dumps(clean, ensure_ascii=False)}
            sig = _clean_sig(sigs.get('sig_guarantor'))
            if sig:
                vals.update(agr_sig_guarantor=sig, agr_signed_on=now)
            line.write(vals)
            errors = _check(clean, GUARANTOR_RULES)
            if not line.agr_sig_guarantor:
                errors['sig_guarantor'] = 'required'
            who = _("Part B (guarantor %s)") % line.guarantor_id.name
        else:  # approver
            sig = _clean_sig(sigs.get('sig_bank'))
            if sig:
                loan.write({'agr_sig_bank': sig, 'agr_bank_signed_by': self.env.user.id,
                            'agr_bank_signed_on': now})
            errors = {} if loan.agr_sig_bank else {'sig_bank': 'required'}
            who = _("bank approver signature")
        if not errors:
            loan.message_post(body=_("Agreement %s completed by %s.") % (who, self.env.user.name))
        return errors

    def _notify_guarantors_agreement_ready(self, lines, replacement=False):
        """Tell the guarantors whose request was JUST sent that the borrower's
        Part A is done and that they must fill + sign Part B before accepting."""
        self.ensure_one()
        loan = self.sudo()
        for line in lines:
            g_user = line.guarantor_id.user_id
            if not g_user:
                continue
            agr_url = "/resl/agreement/%d?g=%d" % (loan.id, line.id)
            if replacement:
                note_text = _(
                    "You have been nominated as a REPLACEMENT guarantor for loan %(loan)s of %(borrower)s. "
                    "Please open the agreement, fill in your details in Part B, sign it, and then accept."
                ) % {'borrower': loan.employee_id.name, 'loan': loan.name}
            else:
                note_text = _(
                    "%(borrower)s has filled and signed Part A of the loan agreement for %(loan)s. "
                    "Please open the agreement, fill in your details in Part B, sign it, and then accept."
                ) % {'borrower': loan.employee_id.name, 'loan': loan.name}
            try:
                loan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=g_user.id,
                    summary=_("Sign Loan Agreement (Part B): %s") % loan.name,
                    note="%s<br/><a href='%s' target='_blank'>%s</a>" % (
                        note_text, agr_url, _("Open Loan Agreement")),
                )
            except Exception:
                _logger.exception("Agreement: could not schedule Part B activity for user %s", g_user.id)
            if g_user.partner_id:
                try:
                    loan.message_notify(
                        partner_ids=[g_user.partner_id.id],
                        subject=_("Loan Agreement Ready for Guarantee: %s") % loan.name,
                        body="%s<br/><p><a href='%s' style='display:inline-block;padding:8px 14px;"
                             "background:#7a1f2b;color:#fff;border-radius:6px;text-decoration:none;'>%s</a></p>" % (
                                 note_text, agr_url, _("Open Agreement")),
                    )
                except Exception:
                    _logger.exception("Agreement: could not notify guarantor partner %s", g_user.partner_id.id)

    def agr_add_file(self, filename, mimetype, content):
        self.ensure_one()
        role, _line = self._agr_resolve()
        if role == 'viewer':
            raise UserError(_("Only people in this request can upload documents."))
        if mimetype not in ALLOWED_MIME:
            raise UserError(_("Only PNG, JPEG or PDF files are allowed."))
        if len(content) > MAX_FILE_BYTES:
            raise UserError(_("The file is larger than 5 MB."))
        head = content[:8]
        ok = (mimetype == 'application/pdf' and head.startswith(b'%PDF')) or \
             (mimetype == 'image/png' and head.startswith(b'\x89PNG')) or \
             (mimetype == 'image/jpeg' and head[:2] == b'\xff\xd8')
        if not ok:
            raise UserError(_("The file content does not match its type."))
        att = self.env['ir.attachment'].sudo().create({
            'name': filename[:200], 'datas': base64.b64encode(content), 'mimetype': mimetype,
            'res_model': 'resl.loan', 'res_id': self.id, 'description': FILE_TAG,
        })
        self.sudo().message_post(body=_("%s uploaded %s to the agreement.") % (self.env.user.name, att.name))
        return att

    # ── button ──────────────────────────────────────────────────────────
    def action_open_agreement(self):
        self.ensure_one()
        # From a brand-new request the form is saved by the button click;
        # flag it as a real request so it gets its reference (LOANxxxxx) and
        # the agreement page can open it.
        if not self.custom_saved:
            self.sudo().write({'custom_saved': True})
        # Opens the agreement as a popup on the current page (see
        # static/src/js/agreement_popup.js); the page is refreshed when it closes.
        return {
            'type': 'ir.actions.client',
            'tag': 'resl_agreement_popup',
            'params': {
                'url': '/resl/agreement/%d' % self.id,
                'title': _("Loan Agreement – %s") % (self.name or ''),
            },
        }

    # ── workflow gates (call the original method afterwards) ────────────
    def action_request_guarantors(self):
        """Run the original send, then tell each guarantor whose request was
        just sent (draft -> pending) to fill + sign Part B."""
        before = {l.id: l.state for l in self.sudo().mapped('guarantor_line_ids')}
        res = super().action_request_guarantors()
        for loan in self:
            sent = loan.sudo().guarantor_line_ids.filtered(
                lambda l: l.state == 'pending' and before.get(l.id) == 'draft')
            if sent:
                loan._notify_guarantors_agreement_ready(sent)
        return res

    def _send_draft_guarantor_requests(self):
        """Replacement guarantor(s) (any stage of the loan, even after
        approval / disbursement): once their request is sent they must fill
        and sign Part B before they can accept - tell them so."""
        self.ensure_one()
        before = {l.id: l.state for l in self.sudo().guarantor_line_ids}
        res = super()._send_draft_guarantor_requests()
        sent = self.sudo().guarantor_line_ids.filtered(
            lambda l: l.state == 'pending' and before.get(l.id) == 'draft')
        if sent:
            self._notify_guarantors_agreement_ready(sent, replacement=True)
        return res

    # ── approver routing: Branch Manager-I -> II -> III, stable fallback ─
    def _agr_branch_manager_level(self, emp):
        """1 / 2 / 3 for a 'Branch Manager-I / -II / -III' (any spacing or
        hyphenation, Roman or Arabic numeral), else 0."""
        names = [emp.job_id.name or '']
        if 'job_title' in emp._fields:
            names.append(emp.job_title or '')
        for raw in names:
            key = re.sub(r'[\s\-_.]+', '', raw.lower())
            m = re.fullmatch(r'branchmanager(iii|ii|i|3|2|1)', key)
            if m:
                return _BM_LEVEL[m.group(1)]
        return 0

    def _agr_branch_manager_by_level(self, ou):
        """The Branch Manager of `ou` with the LOWEST level present
        (I, else II, else III). Only employees with a user count."""
        Employee = self.env['hr.employee'].sudo()
        domain = [('user_id', '!=', False), ('default_operating_unit_id', '=', ou.id)]
        if 'job_title' in Employee._fields:
            domain += ['|', ('job_id.name', 'ilike', 'manager'), ('job_title', 'ilike', 'manager')]
        else:
            domain += [('job_id.name', 'ilike', 'manager')]
        best, best_lvl = Employee.browse(), 99
        for e in Employee.search(domain, order='id'):
            lvl = self._agr_branch_manager_level(e)
            if lvl and lvl < best_lvl:
                best, best_lvl = e, lvl
        return best

    def _agr_fallback_approver(self, emp):
        """Last resort when the unit-level role holder cannot be found, so a
        submitted request never sits with nobody: HO Approver, else HR Approver."""
        exclude = [emp.id] if emp else []
        for xmlid, role in (('resl.group_resl_ho_approver', _("HO Approver (fallback)")),
                            ('resl.group_resl_hr_senior', _("HR Approver (fallback)"))):
            found = self._find_role_employee_by_group(xmlid, exclude_employee_ids=exclude)
            if found and found.user_id:
                return found.user_id, role
        return self.env['res.users'], False

    def _compute_designated_approver(self):
        super()._compute_designated_approver()
        fallback_on = self.env['ir.config_parameter'].sudo().get_param(
            'resl.approver_fallback', '1') == '1'
        for loan in self:
            emp = loan.employee_id.sudo()
            if not emp:
                continue
            ou = loan.sudo().operating_unit_id
            wut = getattr(ou, 'work_unit_type', False) if ou else False
            # Branch / Sub-branch / Service Center: Branch Manager-I first,
            # then -II, then -III.
            if ou and wut in BRANCH_TYPES:
                mgr = loan._agr_branch_manager_by_level(ou)
                if mgr:
                    if mgr.id == emp.id:
                        # the borrower IS the top branch manager: the
                        # Accountant (Disbursement) approves for him / her
                        acct = loan._find_branch_accountant(ou, exclude_employee_ids=[emp.id])
                        user, role = (acct.user_id, _("Accountant (Disbursement)")) if acct else (False, False)
                    else:
                        user, role = mgr.user_id, _("Manager")
                    if user and not (emp.user_id and user.id == emp.user_id.id):
                        loan.designated_approver_id = user.id
                        loan.manager_user_id = user.id
                        loan.designated_approver_role = role
            # Nobody found at all: route to Head Office instead of nobody.
            # Done HERE (not only at submit) because this field is recomputed
            # every time the form is opened.
            if fallback_on and not loan.designated_approver_id:
                user, role = loan._agr_fallback_approver(emp)
                if user:
                    loan.designated_approver_id = user.id
                    loan.manager_user_id = user.id
                    loan.designated_approver_role = role

    def action_submit_manager(self):
        for loan in self:
            if loan._agr_required() and not loan.agr_borrower_complete:
                raise ValidationError(_(
                    "Open 'Agreement' and fill in and sign Part A before submitting to the manager."))
        return super().action_submit_manager()

    def action_request_disbursement(self):
        """HR Auditor must have viewed the agreement before requesting."""
        self._agr_check_viewed('request')
        return super().action_request_disbursement()

    def action_disburse_core_banking(self):
        """The disbursement officer must have viewed the agreement first."""
        self._agr_check_viewed('disburse')
        return super().action_disburse_core_banking()

    def action_manager_approve(self):
        for loan in self:
            if loan._agr_required() and not loan.agr_bank_signed:
                raise ValidationError(_(
                    "Open 'Agreement' and sign it as the bank approver before approving."))
        return super().action_manager_approve()


class ReslLoanGuarantee(models.Model):
    _inherit = 'resl.loan.guarantee'

    agr_data = fields.Text(string="Agreement – Part B data", copy=False)
    agr_sig_guarantor = fields.Binary(string="Guarantor signature", attachment=True, copy=False)
    agr_signed_on = fields.Datetime(copy=False)
    agr_complete = fields.Boolean(compute='_compute_agr_complete')

    @api.depends('agr_data', 'agr_sig_guarantor')
    def _compute_agr_complete(self):
        for line in self:
            line.agr_complete = bool(
                line.agr_sig_guarantor and not _check(_loads(line.agr_data), GUARANTOR_RULES))

    def action_accept(self):
        for g in self:
            if g.loan_id._agr_required() and not g.agr_complete:
                agr_url = f"/resl/agreement/{g.loan_id.id}?g={g.id}"
                raise ValidationError(_(
                    "You cannot accept this guarantee yet.\n\n"
                    "You must first open the agreement, fill in all required Part B fields, and draw your signature.\n\n"
                    "Agreement Link: %s\n\n"
                    "Once you save and complete Part B, you can return here and click Accept."
                ) % agr_url)
        return super().action_accept()