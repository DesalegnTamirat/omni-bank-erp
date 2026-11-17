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


# ── Ethiopian date + amount in English words (no external library) ───────
ETH_MONTHS = ['መስከረም', 'ጥቅምት', 'ህዳር', 'ታህሳስ', 'ጥር', 'የካቲት', 'መጋቢት', 'ሚያዝያ',
              'ግንቦት', 'ሰኔ', 'ሀምሌ', 'ነሀሴ', 'ጳጉሜ']


def _eth_text_from_jdn(jdn):
    era = 1723856
    r = (jdn - era) % 1461
    n = r % 365 + 365 * (r // 1460)
    year = 4 * ((jdn - era) // 1461) + r // 365 - r // 1460
    return '%s %d, %d ዓ.ም' % (ETH_MONTHS[n // 30], n % 30 + 1, year)


def eth_date_text(d):
    """Gregorian date -> Ethiopian date text, e.g. 'ጥቅምት 27, 2019 ዓ.ም'."""
    return _eth_text_from_jdn(d.toordinal() + 1721425)


_ETH_TEXT_RE = re.compile(r'^\s*(\S+)\s+(\d{1,2})\s*,?\s*(\d{4})')


def eth_add_month(text):
    """Ethiopian date text + one month, as Ethiopian date text.
    Every Ethiopian month (1-12) has 30 days, so one month = the same day of
    the next month = 30 days. Returns '' when the text cannot be read."""
    m = _ETH_TEXT_RE.match(text or '')
    if not m or m.group(1) not in ETH_MONTHS:
        return ''
    month, day, year = ETH_MONTHS.index(m.group(1)), int(m.group(2)), int(m.group(3))
    era = 1723856
    jdn = era + 365 * year + year // 4 + 30 * month + day - 1
    # the contract writes the start date as 'ነሀሴ 26 ቀን 2018 ዓ.ም' (with ቀን, no comma)
    return _eth_text_from_jdn(jdn + 30).replace(',', ' ቀን', 1)


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
         'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen',
         'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
_SCALES = [(10 ** 9, 'Billion'), (10 ** 6, 'Million'), (10 ** 3, 'Thousand')]


def _below_1000(n):
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + ' Hundred')
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + ('-' + _ONES[n % 10] if n % 10 else ''))
    elif n:
        out.append(_ONES[n])
    return ' '.join(out)


def amount_in_words_en(amount):
    """594618.0 -> 'Five Hundred Ninety-Four Thousand Six Hundred Eighteen Birr'."""
    total = int(round(float(amount or 0) * 100))
    birr, cents = divmod(total, 100)
    parts = []
    for size, name in _SCALES:
        if birr >= size:
            parts.append(_below_1000(birr // size) + ' ' + name)
            birr %= size
    if birr or not parts:
        parts.append(_below_1000(birr) or 'Zero')
    text = ' '.join(parts) + ' Birr'
    if cents:
        text += ' and %s %s' % (_below_1000(cents), 'Cent' if cents == 1 else 'Cents')
    return text


# ── amount in Amharic words, written exactly like the contract ───────────
#   594618.00 -> 'አምስት መቶ ዘጠና አራት ሺህ ስድስት መቶ አስራ ስምንት'
#   24775.75  -> 'ሀያ አራት ሺህ ሰባት መቶ ሰባ አምስት ከ75/100'
_AM_ONES = ['', 'አንድ', 'ሁለት', 'ሶስት', 'አራት', 'አምስት', 'ስድስት', 'ሰባት', 'ስምንት', 'ዘጠኝ']
_AM_TENS = ['', 'አስር', 'ሀያ', 'ሰላሳ', 'አርባ', 'ሀምሳ', 'ስልሳ', 'ሰባ', 'ሰማንያ', 'ዘጠና']
_AM_SCALES = [(10 ** 9, 'ቢሊዮን'), (10 ** 6, 'ሚሊዮን'), (10 ** 3, 'ሺህ')]


def _am_below_1000(n):
    out = []
    if n >= 100:
        out.append(_AM_ONES[n // 100] + ' መቶ')
        n %= 100
    if n >= 20:
        out.append(_AM_TENS[n // 10] + ((' ' + _AM_ONES[n % 10]) if n % 10 else ''))
    elif n >= 11:
        out.append('አስራ ' + _AM_ONES[n - 10])
    elif n == 10:
        out.append('አስር')
    elif n:
        out.append(_AM_ONES[n])
    return ' '.join(out)


def amount_in_words(amount):
    """Amount -> Amharic words (no 'ብር' - the contract already prints it).
    Cents are written as 'ከ75/100'."""
    total = int(round(float(amount or 0) * 100))
    birr, cents = divmod(total, 100)
    parts = []
    for size, name in _AM_SCALES:
        if birr >= size:
            parts.append(_am_below_1000(birr // size) + ' ' + name)
            birr %= size
    if birr or not parts:
        parts.append(_am_below_1000(birr) or 'ዜሮ')
    text = ' '.join(parts)
    if cents:
        text += ' ከ%02d/100' % cents
    return text


# Article 7: the amount is always paid back in 24 monthly instalments
AGR_MONTHS = 24


def _title_for(gender, marital):
    """Mr. / Miss / Mrs. from hr_employee.gender and hr_version.marital.
    male -> Mr.;  female + single -> Miss;  female + married -> Mrs.
    (female + widower / divorced / cohabitant -> Mrs.).  '' when the gender
    is unknown, so no wrong title is ever written."""
    g = (gender or '').strip().lower()
    m = (marital or '').strip().lower()
    if g == 'male':
        return 'Mr.'
    if g == 'female':
        return 'Miss' if m in ('', 'single') else 'Mrs.'
    return ''


# What is stored (snapshot) when a person presses "Agree and continue".
# The amounts and their words are NOT stored: they always follow the loan.
SNAP_A = ('a_date', 'a_name', 'a_city', 'a_subcity', 'a_woreda', 'a_house',
          'a_phone', 'a_tax', 'a_emp')
SNAP_B = ('b_date', 'b_name', 'b_address', 'b_city', 'b_subcity', 'b_woreda', 'b_house', 'b_tax', 'b_emp', 'b_phone',
          'b_bdate', 'b_branch1', 'b_branch2')


def _txt(value):
    """Any hr.employee value -> clean text ('-' when empty)."""
    if hasattr(value, '_name'):
        value = value.display_name if value else ''
    text = str(value).strip() if value not in (None, False) else ''
    return text or '-'


class ReslLoan(models.Model):
    _inherit = 'resl.loan'

    agr_data = fields.Text(string="Agreement – borrower data", copy=False)
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
    # Part A agreed on a NEW request that does not exist in the database yet
    # (client-side only, never stored). The request is only created when the
    # requester presses Save or picks a guarantor; create() then records the
    # agreement on the new request (see create()).
    agr_pre_agreed = fields.Boolean(store=False, copy=False)
    # Approvers (the designated one / their delegate) and admins may print it.
    agr_can_print = fields.Boolean(compute='_compute_agr_can_print')

    # Users (disbursement officer / HR Auditor ...) who have opened the agreement
    # on this loan AFTER it was approved. Mandatory before requesting or doing
    # the disbursement.
    agr_viewer_ids = fields.Many2many(
        'res.users', 'resl_loan_agr_viewer_rel', 'loan_id', 'user_id',
        string="Agreement viewed by", copy=False)
    # True when the current user has to open the agreement before acting.
    agr_view_pending = fields.Boolean(compute='_compute_agr_view_pending')

    # ── computes ────────────────────────────────────────────────────────
    @api.depends('agr_borrower_signed_on', 'agr_bank_signed_on')
    def _compute_agr_flags(self):
        # "Agreed" = the person pressed "Agree and continue" (no drawn signature)
        for loan in self:
            loan.agr_borrower_complete = bool(loan.agr_borrower_signed_on)
            loan.agr_bank_signed = bool(loan.agr_bank_signed_on)

    @api.depends_context('uid')
    @api.depends('name', 'custom_saved', 'status', 'employee_id.user_id',
                 'guarantor_line_ids.state', 'guarantor_line_ids.active',
                 'guarantor_line_ids.guarantor_id')
    def _compute_agr_can_open(self):
        for loan in self:
            ok = bool(loan.id and loan.custom_saved and loan.name != 'New')
            # The requestor cannot open the agreement before the guarantor(s) accepted
            if ok and not loan._agr_requester_unlocked():
                ok = False
            loan.agr_can_open = ok

    def _agr_requester_unlocked(self, user=None):
        """False for the REQUESTOR until all guarantors accepted (before the manager
        stage), and for a GUARANTOR until he / she has accepted."""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        if not loan.id:
            return True
        # GUARANTOR: no agreement before he / she has accepted the request
        # (an approver / admin who is also a guarantor is not locked out).
        if loan.employee_id.user_id != user:
            mine = loan.guarantor_line_ids.filtered(
                lambda l: l.active and l.guarantor_id.user_id == user)
            if mine and not mine.filtered(lambda l: l.state == 'accepted'):
                return bool(loan._agr_is_admin(user) or loan._agr_is_designated(user))
            return True
        if loan.status not in ('draft', 'guarantor_pending', 'rejected'):
            return True
        lines = loan.guarantor_line_ids.filtered(
            lambda l: l.active and l.state in ('draft', 'pending', 'accepted'))
        return bool(lines) and all(l.state == 'accepted' for l in lines)

    @api.depends_context('uid')
    @api.depends('status', 'employee_id.user_id', 'designated_approver_id',
                 'agr_borrower_signed_on', 'agr_bank_signed_on',
                 'guarantor_line_ids.state', 'guarantor_line_ids.active',
                 'guarantor_line_ids.agr_signed_on')
    def _compute_agr_role(self):
        required = self._agr_required()
        user = self.env.user
        for loan in self:
            role, todo = 'viewer', False
            if not loan.id:
                # brand-new, unsaved request: only the requester sees it
                # (the borrower agrees later, after the guarantors accepted)
                if loan.employee_id and loan.employee_id.user_id == user:
                    role, todo = 'requester', False
            else:
                role, line = loan._agr_resolve()
                status = loan.sudo().status
                if role == 'requester':
                    # Requester can only agree AFTER all guarantors
                    # have agreed (the new flow: guarantor first).
                    g_lines = loan.sudo().guarantor_line_ids.filtered(
                        lambda l: l.active and l.state == 'accepted')
                    all_g_signed = bool(g_lines) and all(l.agr_complete for l in g_lines)
                    todo = (status in ('draft', 'guarantor_pending', 'rejected')
                            and not loan.agr_borrower_complete
                            and all_g_signed)
                elif role == 'guarantor':
                    todo = bool(line and line.state == 'accepted' and not line.agr_complete)
                elif role == 'approver':
                    todo = status == 'manager_review' and not loan.agr_bank_signed
            loan.agr_role = role
            loan.agr_todo = bool(todo and required)

    @api.depends_context('uid')
    @api.depends('status', 'designated_approver_id', 'manager_user_id', 'custom_saved', 'name',
                 'employee_id.user_id', 'guarantor_line_ids.guarantor_id')
    def _compute_agr_can_print(self):
        for loan in self:
            loan.agr_can_print = bool(loan.id and loan._agr_can_print())

    def _agr_can_print(self, user=None):
        """Print is for approvers, disbursers, HR staff, auditors, and admins.
        Regular requesters and guarantors who do not have a management/staff role
        cannot print the legal agreement."""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        if not (loan.id and loan.custom_saved and loan.name != 'New'):
            return False
        # Print follows the user's ROLE, not the fact that he / she is the
        # requestor or a guarantor: a plain requestor / guarantor cannot print,
        # but one who is ALSO an approver / admin / HR / disburser / auditor /
        # accountant / manager can.
        if loan._agr_is_admin(user) or loan._agr_is_designated(user):
            return True
        try:
            is_disburser = bool(loan._user_can_disburse(user) or user in (loan.disbursement_officer_ids | loan.disbursement_officer_id))
            is_auditor = bool(user._resl_has_group('resl.group_resl_hr_auditor'))
            is_accountant = bool(user._resl_has_group('resl.group_resl_hr_accountant'))
            is_hr = bool(user._resl_has_group('resl.group_resl_hr'))
            is_manager = bool(user._resl_has_group('resl.group_resl_manager'))
            if is_disburser or is_auditor or is_accountant or is_hr or is_manager:
                return True
        except Exception:
            pass
        return loan._agr_resolve(user=user)[0] == 'approver'

    # ── a request is created ONLY by Save or by picking a guarantor ──────
    @api.model_create_multi
    def create(self, vals_list):
        """New flow: the guarantor agrees first, then the requester agrees
        afterwards. Pre-agreeing is no longer supported — the
        agr_pre_agreed flag is stripped but NOT acted upon."""
        vals_list = [{k: v for k, v in vals.items() if k != 'agr_pre_agreed'} for vals in vals_list]
        loans = super().create(vals_list)
        return loans

    @api.model
    def resl_check_new_allowed(self):
        """Called when the user presses New (list or form): raises the same
        validation message as a blocked request, BEFORE any form is opened and
        nothing is created."""
        emp = self.env.user.employee_id
        if emp:
            self._raise_if_new_request_blocked(emp)
        return True

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
            # A guarantor who is ALSO the approver / an administrator of this
            # request. As long as his / her own guarantor agreement is still
            # open (not accepted yet, or accepted but not agreed) they act as
            # the GUARANTOR - so the guarantor button / banner and the "Agree
            # and continue" of their own copy are available to them (an admin
            # used to be treated as the approver at once and could not agree
            # as the guarantor). The one exception is the approval stage: when
            # the request waits for the approver's agreement they act as the
            # approver first, then as the guarantor.
            open_lines = mine.filtered(
                lambda l: l.state == 'pending' or (l.state == 'accepted' and not l.agr_complete))
            approver_turn = (loan.status == 'manager_review' and not loan.agr_bank_signed_on
                             and loan._agr_can_sign_bank(user))
            if open_lines and not approver_turn:
                pick = (open_lines.filtered(lambda l: l.id == line_id) or open_lines)[:1]
                return 'guarantor', pick
            if loan._agr_can_sign_bank(user):
                return 'approver', (mine.filtered(lambda l: l.id == line_id) or mine)[:1]
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
            # Requester can only agree after ALL guarantors agreed
            g_lines = loan.guarantor_line_ids.filtered(
                lambda l: l.active and l.state == 'accepted')
            all_g_signed = bool(g_lines) and all(l.agr_complete for l in g_lines)
            return loan.status in ('draft', 'guarantor_pending', 'rejected') and all_g_signed
        if role == 'guarantor':
            # The guarantor agrees AFTER having accepted
            return bool(line) and line.state == 'accepted' and not line.agr_complete
        if role == 'approver':
            return loan.status == 'manager_review'
        return False

    # ── values filled by the system ─────────────────────────────────────
    def _agr_system_values(self):
        self.ensure_one()
        loan = self.sudo()
        return self._agr_system_values_for(
            loan.employee_id, loan._agr_amount(), AGR_MONTHS)

    def _agr_amount(self):
        """The amount written in the agreement = the REQUESTED amount."""
        self.ensure_one()
        loan = self.sudo()
        return loan.requested_amount or loan.approved_amount or 0.0

    def _agr_system_values_for(self, emp, amount, term=None):
        """Amount block of the agreement for an employee / amount (works for a
        saved request AND for the not-yet-created request preview). The monthly
        instalment is always the amount / 24."""
        term = AGR_MONTHS
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

    # ── values read from the HR record (nothing is typed on the page) ────
    def _agr_emp_col(self, emp, col):
        """One column of hr_employee as text; '-' when empty. Uses the ORM field
        when it exists, else reads the table column directly."""
        emp = emp.sudo()
        if col in emp._fields:
            return _txt(emp[col])
        cr = self.env.cr
        cr.execute("SELECT 1 FROM information_schema.columns "
                   "WHERE table_name = 'hr_employee' AND column_name = %s", (col,))
        if not cr.fetchone():
            return '-'
        cr.execute('SELECT "%s" FROM hr_employee WHERE id = %%s' % col, (emp.id,))
        row = cr.fetchone()
        return _txt(row[0] if row else '')

    def _agr_marital(self, emp):
        """Marital status straight from hr_version (the version the employee
        points to, else the latest one); falls back to hr_employee.marital on
        databases that have no hr_version table."""
        emp = emp.sudo()
        cr = self.env.cr
        try:
            cr.execute("""SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'hr_version' AND column_name = 'marital'""")
            if cr.fetchone():
                cr.execute("""
                    SELECT v.marital
                      FROM hr_version v
                      JOIN hr_employee e ON e.id = v.employee_id
                     WHERE v.employee_id = %s
                       AND COALESCE(TRIM(v.marital), '') <> ''
                     ORDER BY (v.id = e.current_version_id) DESC,
                              v.date_version DESC NULLS LAST,
                              v.id DESC
                     LIMIT 1""", (emp.id,))
                row = cr.fetchone()
                return (row[0] or '').strip() if row else ''
        except Exception:
            _logger.exception("Agreement: could not read marital status from hr_version")
        val = self._agr_emp_col(emp, 'marital')
        return '' if val == '-' else val

    def _agr_titled_name(self, emp):
        """'Mr. Name' / 'Miss Name' / 'Mrs. Name' (gender from hr_employee,
        marital status from hr_version)."""
        name = self._agr_emp_col(emp, 'name')
        if name == '-':
            return name
        gender = self._agr_emp_col(emp, 'gender')
        title = _title_for('' if gender == '-' else gender, self._agr_marital(emp))
        return ('%s %s' % (title, name)) if title else name

    def _agr_ou_name(self, emp):
        try:
            ou = self.env['resl.validations'].get_employee_operating_unit(emp.sudo())
            return _txt(ou.name if ou else '')
        except Exception:
            return '-'

    def _agr_today_text(self):
        return eth_date_text(fields.Date.context_today(self))

    def _agr_borrower_values(self):
        """Part A values: live from hr_employee; the date is today until the
        borrower agrees, then the stored date."""
        self.ensure_one()
        loan = self.sudo()
        return self._agr_borrower_values_for(
            loan.employee_id, loan._agr_amount(), AGR_MONTHS,
            snapshot=loan.agr_data if loan.agr_borrower_signed_on else None)

    def _agr_borrower_values_for(self, emp, amount, term, snapshot=None):
        """Part A values for an employee. `snapshot` = the stored Part A data
        once the borrower has agreed (None before that)."""
        c = self._agr_emp_col
        term = AGR_MONTHS          # Article 7: amount / 24
        vals = {
            'a_date': self._agr_today_text(),
            'a_name': self._agr_titled_name(emp),
            'a_city': c(emp, 'city'),
            'a_subcity': c(emp, 'sub_city'),
            'a_woreda': c(emp, 'woreda'),
            'a_house': c(emp, 'house_number'),
            'a_phone': c(emp, 'personal_phone'),
            'a_tax': c(emp, 'pension_number'),
            'a_emp': c(emp, 'identification_id'),
        }
        if snapshot:
            vals.update({k: v for k, v in _loads(snapshot).items() if k in SNAP_A and v})
        # Article 7: the payment starts ONE MONTH after the agreement date
        vals['a_start'] = eth_add_month(vals['a_date']) or vals['a_date']
        vals['a_amtw'] = amount_in_words(amount)
        vals['a_instw'] = amount_in_words(amount / term)
        return vals

    def _agr_guarantor_values(self, line):
        """Part B values of one guarantor (live, or the stored snapshot once agreed)."""
        self.ensure_one()
        loan = self.sudo()
        g = line.sudo().guarantor_id
        c = self._agr_emp_col
        borrower = self._agr_borrower_values()
        amount = loan._agr_amount()
        vals = {
            'b_date': self._agr_today_text(),
            'b_name': self._agr_titled_name(g),
            'b_address': ' '.join(x for x in (c(g, 'city'), c(g, 'sub_city'), c(g, 'woreda')) if x != '-') or '-',
            'b_city': c(g, 'city'),
            'b_subcity': c(g, 'sub_city'),
            'b_woreda': c(g, 'woreda'),
            'b_house': c(g, 'house_number'),
            'b_tax': c(g, 'pension_number'),
            'b_emp': c(g, 'identification_id'),
            'b_phone': c(g, 'personal_phone'),
            'b_bdate': borrower['a_date'],
            'b_branch1': self._agr_ou_name(loan.employee_id),
            'b_branch2': self._agr_ou_name(g),
        }
        if line.sudo().agr_signed_on:
            vals.update({k: v for k, v in _loads(line.sudo().agr_data).items() if k in SNAP_B and v})
        # always follow the loan / borrower
        vals['b_borrower'] = borrower['a_name']
        vals['b_amtw'] = amount_in_words(amount)
        return vals

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

    @api.model
    def _agr_config_new(self, amount=0.0, term=1, agreed=False):
        """Agreement page data for a request that does not exist yet (opened
        from the New form). Read-only preview of the borrower's part built from the current
        user's HR record; nothing is created or saved."""
        user = self.env.user
        emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not emp:
            raise UserError(_("Your user is not linked to an employee record."))
        amount = max(float(amount or 0.0), 0.0)
        if not amount:
            # The New form has no requested amount yet: create() will store the
            # net eligible amount, so show exactly that already now.
            try:
                amount = float(self.new({'employee_id': emp.id}).net_eligible_amount or 0.0)
            except Exception:
                _logger.exception("Agreement: could not compute the amount for the new request")
        term = AGR_MONTHS
        values = self._agr_borrower_values_for(emp, amount, term)
        return {
            'loanId': 0,
            'preview': True,
            'ref': _("New request"),
            'role': 'requester',
            'lineId': 0,
            'lines': [],
            'parts': [],
            'editable': True,
            'system': self._agr_system_values_for(emp, amount, term),
            'values': {k: v for k, v in values.items() if v},
            'sigs': {'sig_borrower': 'Agreed'} if agreed else {},
            'files': [],
            'status': {'requester': bool(agreed), 'guarantor': False, 'approver': False},
            'pdf': self.env['resl.pdf.config'].get_active_config(),
            'why': '',
            'canPrint': False,
        }

    def _agr_config(self, line_id=None):
        """Everything the agreement page needs, as a JSON-able dict."""
        self.ensure_one()
        loan = self.sudo()
        role, line = self._agr_resolve(line_id)
        values = self._agr_borrower_values()
        # "Agreed" marks (no drawn signatures any more)
        sigs = {
            'sig_borrower': 'Agreed' if loan.agr_borrower_signed_on else '',
            'sig_bank_a': 'Agreed' if loan.agr_bank_signed_on else '',
            'sig_bank_b': 'Agreed' if loan.agr_bank_signed_on else '',
        }
        all_lines = loan.guarantor_line_ids.filtered(
            lambda l: l.active and l.state in ('draft', 'pending', 'accepted')).sorted('id')
        # One copy of Part B (guarantee pages) per guarantor.  EVERYBODY sees all
        # the copies (requestor, approver, every guarantor); a guarantor can only
        # agree to his / her own copy ('mine' / 'editable').
        part_lines = all_lines
        editable = self._agr_editable(role, line)
        parts = [{
            'lineId': l.id,
            'name': l.guarantor_id.name or '',
            'state': l.state,
            'values': self._agr_guarantor_values(l),
            'sig': 'Agreed' if l.agr_signed_on else '',
            'complete': bool(l.agr_complete),
            'mine': bool(role == 'guarantor' and line and l.id == line.id),
            'editable': bool(role == 'guarantor' and editable and line and l.id == line.id),
        } for l in part_lines]
        # Dynamic PDF & text layout from admin configuration
        pdf_cfg = self.env['resl.pdf.config'].get_active_config()
        signer_names = {
            'sig_borrower': loan.employee_id.name or '',
            'sig_bank_a': (loan.agr_bank_signed_by.name or loan.designated_approver_id.name or self.env.user.name or ''),
            'sig_bank_b': (loan.agr_bank_signed_by.name or loan.designated_approver_id.name or self.env.user.name or ''),
        }
        for k, l in enumerate(part_lines):
            signer_names[f'sig_guarantor@{k}'] = l.guarantor_id.name or ''
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
            'names': signer_names,
            'files': self._agr_files(),
            'status': {
                'requester': loan.agr_borrower_complete,
                'guarantor': bool(line and line.agr_complete),
                'approver': loan.agr_bank_signed,
            },
            'pdf': pdf_cfg,
            'why': self._agr_why_not_approver() if role == 'viewer' else '',
            'canPrint': self._agr_can_print(),
        }

    # ── save (called by the controller) ─────────────────────────────────
    def agr_save(self, role_claimed, values=None, sigs=None, line_id=None):
        """"Agree and continue": records that the current person agreed. Nothing
        is typed: the personal details come from hr_employee and are stored as
        they were at this moment, together with today's date."""
        self.ensure_one()
        role, line = self._agr_resolve(line_id)
        if role != role_claimed or not self._agr_editable(role, line):
            raise UserError(_("You cannot edit this part of the agreement now."))
        loan = self.sudo()
        now = fields.Datetime.now()
        if role == 'requester':
            loan._agr_record_borrower_agreement()
            who = _("%s (Borrower)") % (loan.employee_id.name or '')
        elif role == 'guarantor':
            if not line.sudo().agr_signed_on:
                vals = self._agr_guarantor_values(line)
                line.sudo().write({'agr_data': json.dumps({k: vals[k] for k in SNAP_B}, ensure_ascii=False),
                                   'agr_signed_on': now})
                # Notify the borrower when this guarantor has agreed
                try:
                    all_signed = all(
                        l.agr_complete
                        for l in loan.guarantor_line_ids.filtered(
                            lambda l: l.active and l.state == 'accepted')
                    )
                    borrower_user = loan.employee_id.user_id
                    if borrower_user:
                        if all_signed:
                            note = _(
                                "All guarantors have signed the agreement for loan %(loan)s. "
                                "Please open the agreement, press Agree and continue, and then submit to your manager."
                            ) % {'loan': loan.name}
                            subj = _("All Guarantors Signed – Please Sign and Submit: %s") % loan.name
                        else:
                            note = _(
                                "Guarantor %(guarantor)s has agreed the loan agreement for %(loan)s."
                            ) % {'guarantor': line.guarantor_id.name, 'loan': loan.name}
                            subj = _("Guarantor Signed Agreement: %s") % loan.name
                        loan.activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=borrower_user.id,
                            summary=subj,
                            note=note,
                        )
                        if borrower_user.partner_id:
                            loan.message_notify(
                                partner_ids=[borrower_user.partner_id.id],
                                subject=subj,
                                body=note,
                            )
                except Exception:
                    _logger.exception("Agreement: could not notify borrower after guarantor signed Part B")
            who = _("%s (Guarantor)") % (line.guarantor_id.name or '')
        else:  # approver
            if not loan.agr_bank_signed_on:
                loan.write({'agr_bank_signed_by': self.env.user.id, 'agr_bank_signed_on': now})
            who = _("%s (Approver)") % self.env.user.name
        loan.message_post(body=_("Agreement agreed by %s.") % who)
        # Tell the requestor, the approver and the disbursor(s) (not the person
        # who just agreed; the borrower already got the dedicated note above
        # when a guarantor agreed).
        loan._resl_notify_progress(
            _("Agreement agreed: %s") % loan.name,
            _("%(who)s agreed the loan agreement of loan %(loan)s (%(borrower)s).") % {
                'who': who, 'loan': loan.name, 'borrower': loan.employee_id.name},
            exclude_users=(loan.employee_id.user_id if role == 'guarantor' else None),
        )
        return {}

    def _agr_record_borrower_agreement(self):
        """Store the borrower's agreement (snapshot of the HR data + today's date).
        Used by 'Agree and continue' on a saved request and, for a request that
        was agreed BEFORE it existed, right after it is created."""
        for loan in self.sudo():
            if not loan.agr_borrower_signed_on:
                vals = loan._agr_borrower_values()
                loan.write({'agr_data': json.dumps({k: vals[k] for k in SNAP_A}, ensure_ascii=False),
                            'agr_borrower_signed_on': fields.Datetime.now()})

    def _notify_guarantors_agreement_ready(self, lines, replacement=False):
        """Tell the guarantors whose request was JUST sent that they must
        accept / reject it and then agree the agreement."""
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
                    "Please ACCEPT or REJECT the request first. After you accept, open the agreement and press Agree and continue."
                ) % {'borrower': loan.employee_id.name, 'loan': loan.name}
            else:
                note_text = _(
                    "%(borrower)s has requested you as a guarantor for loan %(loan)s. "
                    "Please ACCEPT or REJECT the request first. After you accept, open the agreement and press Agree and continue."
                ) % {'borrower': loan.employee_id.name, 'loan': loan.name}
            try:
                loan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=g_user.id,
                    summary=_("Guarantee Request – Accept or Reject: %s") % loan.name,
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

    # ── buttons ─────────────────────────────────────────────────────────
    def action_open_agreement(self):
        self.ensure_one()
        # Opening the agreement never creates, saves or blocks anything: a new,
        # unsaved request uses the "Agreement (Part A)" widget on the form
        # instead, and a request is only created by Save / picking a guarantor.
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

    def action_print_agreement(self):
        """Approvers and admins: open the agreement in a new tab and print it."""
        self.ensure_one()
        if not self._agr_can_print():
            raise UserError(_("Only the approver of this request or an administrator can print the agreement."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/resl/agreement/%d?print=1' % self.id,
            'target': 'new',
        }

    # ── one open request at a time, INCLUDING approved-but-not-disbursed ──
    def _request_blockers(self, emp, exclude_loan_id=None):
        blockers = super()._request_blockers(emp, exclude_loan_id=exclude_loan_id)
        if emp:
            domain = [
                ('employee_id', '=', emp.sudo().id),
                ('status', '=', 'approved'),
                ('core_banking_status', '!=', 'disbursed'),
                ('custom_saved', '=', True),
                ('name', '!=', 'New'),
            ]
            if exclude_loan_id and isinstance(exclude_loan_id, int):
                domain.append(('id', '!=', exclude_loan_id))
            approved = self.sudo().search(domain, order='create_date desc', limit=1)
            if approved:
                blockers.append(_(
                    "%(name)s already has an approved RSSA request (%(ref)s) that is waiting for "
                    "disbursement. It must be disbursed or rejected before a new one can be submitted."
                ) % {'name': emp.sudo().name, 'ref': approved.name})
        return blockers

    # ── a guarantor cannot replace guarantors from the guarantor page ───
    def _check_can_replace_guarantor(self):
        self.ensure_one()
        if not self.env.su and self._agr_resolve()[0] == 'guarantor':
            raise ValidationError(_("A guarantor cannot replace guarantors on this request."))
        return super()._check_can_replace_guarantor()

    # ── workflow gates (call the original method afterwards) ────────────
    def action_request_guarantors(self):
        """Run the original send, then tell each guarantor whose request was
        just sent (draft -> pending) to accept / reject and agree."""
        before = {l.id: l.state for l in self.sudo().mapped('guarantor_line_ids')}
        res = super().action_request_guarantors()
        for loan in self:
            sent = loan.sudo().guarantor_line_ids.filtered(
                lambda l: l.state == 'pending' and before.get(l.id) == 'draft')
            if sent:
                loan._notify_guarantors_agreement_ready(sent)
                # requestor / approver / disbursor(s) follow the request too
                loan._resl_notify_progress(
                    _("Guarantor requested: %s") % loan.name,
                    _("%(borrower)s sent loan %(loan)s to the guarantor(s): %(g)s.") % {
                        'borrower': loan.sudo().employee_id.name, 'loan': loan.name,
                        'g': ', '.join(sent.mapped('guarantor_id.name'))},
                )
        return res

    def _send_draft_guarantor_requests(self):
        """Replacement guarantor(s) (any stage of the loan, even after
        approval / disbursement): once their request is sent they must fill
        and agree the agreement - tell them so."""
        self.ensure_one()
        before = {l.id: l.state for l in self.sudo().guarantor_line_ids}
        res = super()._send_draft_guarantor_requests()
        sent = self.sudo().guarantor_line_ids.filtered(
            lambda l: l.state == 'pending' and before.get(l.id) == 'draft')
        if sent:
            self._notify_guarantors_agreement_ready(sent, replacement=True)
            self._resl_notify_progress(
                _("Replacement guarantor requested: %s") % self.name,
                _("Replacement guarantor(s) %(g)s were asked to guarantee loan %(loan)s.") % {
                    'g': ', '.join(sent.mapped('guarantor_id.name')), 'loan': self.name},
            )
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
            # Configuration > Approvers & Disbursors already designated the
            # approver: keep it.
            if loan.approver_routing_source == 'rule' and loan.designated_approver_id:
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
                    "Open 'Agreement' and agree it as the borrower before submitting to the manager."))
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

    agr_data = fields.Text(string="Agreement – guarantor data", copy=False)
    agr_sig_guarantor = fields.Binary(string="Guarantor signature", attachment=True, copy=False)
    agr_signed_on = fields.Datetime(copy=False)
    agr_complete = fields.Boolean(compute='_compute_agr_complete')

    @api.depends('agr_signed_on')
    def _compute_agr_complete(self):
        for line in self:
            line.agr_complete = bool(line.agr_signed_on)

    def action_accept(self):
        """The guarantor accepts FIRST (no agreement needed). The requestor is
        told straight away; the guarantor then agrees Part B, and the requestor
        agrees Part A once every guarantor has done so."""
        pending = self.filtered(lambda l: l.state == 'pending')
        res = super().action_accept()
        for g in pending:
            loan = g.loan_id.sudo()
            borrower_user = loan.employee_id.user_id
            if not borrower_user:
                continue
            subj = _("Guarantor Accepted: %s") % loan.name
            note = _("Guarantor %(g)s has ACCEPTED your guarantee request for loan %(loan)s. "
                     "They will now agree the agreement; you will be notified when "
                     "you can agree it as the borrower.") % {'g': g.guarantor_id.name, 'loan': loan.name}
            try:
                loan.activity_schedule('mail.mail_activity_data_todo',
                                       user_id=borrower_user.id, summary=subj, note=note)
                if borrower_user.partner_id:
                    loan.message_notify(partner_ids=[borrower_user.partner_id.id],
                                        subject=subj, body=note)
            except Exception:
                _logger.exception("Agreement: could not notify borrower after guarantor accepted")
            # the approver and the disbursor(s) are told too (the borrower got
            # the note above, the guarantor just acted)
            loan._resl_notify_progress(
                subj,
                _("Guarantor %(g)s ACCEPTED the guarantee request for loan %(loan)s of %(borrower)s.") % {
                    'g': g.guarantor_id.name, 'loan': loan.name, 'borrower': loan.employee_id.name},
                roles=('approver', 'disbursor'),
            )
        return res
