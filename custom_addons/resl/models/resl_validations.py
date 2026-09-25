# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging
import re

_logger = logging.getLogger(__name__)

# Words that mark a contract-type name as "permanent" (FR-RESL-007) ...
_PERMANENT_TERMS = {'permanent', 'regular', 'indefinite', 'confirmed'}
# ... unless the same name also carries a negation / non-permanent marker,
# e.g. "Non-Permanent", "Not Permanent", "Temporary (Regular Hours)".
_NON_PERMANENT_TERMS = {
    'non', 'not', 'un', 'temporary', 'temp', 'probation', 'probationary', 'fixed',
}


class ReslValidations(models.AbstractModel):
    _name = 'resl.validations'
    _description = 'Shared validations for RESL Staff Loan flows (BRD 18.2 & 18.3)'

    @api.model
    def check_employee_disciplinary_status(self, employee):
        """
        FR-RESL-003 & 18.2: Employees under probation, suspension, investigation,
        or active disciplinary actions shall not be eligible.
        Returns (is_eligible: bool, reason: str).
        """
        if not employee:
            return False, _("No employee specified.")

        emp_id = employee.id

        # 1. Check disciplinary.action model
        try:
            DisciplinaryAction = self.env['disciplinary.action'].sudo()
            active_actions = DisciplinaryAction.search([
                ('employee_name', '=', emp_id),
                ('state', 'in', ['explain', 'submitted', 'action'])
            ], limit=1)
            if active_actions:
                return False, _(
                    "Employee has an active disciplinary action (%s) under review or validated."
                ) % (active_actions.name or active_actions.id)
        except Exception as e:
            _logger.debug("Could not check disciplinary.action: %s", e)

        # 2. Check discipline.action model
        try:
            DisciplineAction = self.env['discipline.action'].sudo()
            today = fields.Date.context_today(self)
            domain = [
                ('employee_name', '=', emp_id),
                '|',
                ('status', 'in', ['in_progress', 'appeal']),
                '&',
                ('status', '=', 'approved'),
                ('end_date', '>=', today)
            ]
            active_penalties = DisciplineAction.search(domain, limit=1)
            if active_penalties:
                return False, _(
                    "Employee has an active or unexpired disciplinary penalty/investigation (%s)."
                ) % (active_penalties.reference or active_penalties.id)
        except Exception as e:
            _logger.debug("Could not check discipline.action: %s", e)

        return True, ""

    @api.model
    def check_employee_suspension_leave(self, employee):
        """
        FR-RESL-003 & 18.2: An employee currently on an approved "Suspense" /
        "Suspension" leave (administrative suspension recorded via Time Off,
        as opposed to a disciplinary.action/discipline.action record) shall
        not be eligible to request an RSSA loan.
        Returns (is_eligible: bool, reason: str).
        """
        if not employee:
            return False, _("No employee specified.")

        emp_id = employee.id
        today = fields.Date.context_today(self)

        try:
            Leave = self.env['hr.leave'].sudo()
        except KeyError:
            # hr_holidays (Time Off) not installed on this database.
            return True, ""

        try:
            domain = [
                ('employee_id', '=', emp_id),
                ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
                ('holiday_status_id.name', 'ilike', 'suspen'),
            ]
            state_field = 'state' if 'state' in Leave._fields else None
            if state_field:
                domain.append(('state', 'in', ['validate', 'validate1']))
            active_suspension = Leave.search(domain, limit=1)
            if active_suspension:
                return False, _(
                    "Employee is currently on an active suspension (%s)."
                ) % (active_suspension.holiday_status_id.name or _("Suspense Leave"))
        except Exception as e:
            _logger.debug("Could not check hr.leave for suspension: %s", e)

        return True, ""

    @api.model
    def _is_contract_active(self, contract):
        """
        Odoo 19: hr.contract was merged into hr.version, which exposes a
        purpose-built 'is_in_contract' boolean (True when contract_date_start
        is set and today falls within [date_start, date_end or open-ended]).
        That is the authoritative *date* check on this version. Older Odoo
        (or a plain hr.contract-like record) falls back to 'state', then
        'active'.

        IMPORTANT: the 'active' boolean — not the human-workflow 'state'
        selection — is the authoritative signal of whether a contract/
        version record is the current, valid one. 'state' has been
        observed to be unreliable here: a record can be left in 'draft'
        while still being the one actually in force, and 'state' values
        like 'active' can appear on records that have since been archived
        (superseded). 'active' is therefore checked FIRST, as a hard gate:
        an archived (active=False) contract/version is never treated as
        active/in force, no matter what its state or dates say.
        """
        if not contract:
            return False

        if hasattr(contract, 'active') and not contract.active:
            return False

        if hasattr(contract, 'is_in_contract'):
            return bool(contract.is_in_contract)
        if hasattr(contract, 'state'):
            return contract.state in ('open', 'running', 'active')
        if hasattr(contract, 'active'):
            return bool(contract.active)
        end_field = 'contract_date_end' if hasattr(contract, 'contract_date_end') else (
            'date_end' if hasattr(contract, 'date_end') else None
        )
        if end_field:
            end_date = getattr(contract, end_field, False)
            if end_date:
                today = fields.Date.context_today(self)
                return end_date >= today
        return True

    @api.model
    def _describe_contract_type(self, employee, loan=None):
        """Best-effort human-readable summary of what is_permanent_employee
        actually saw for this employee, purely for error messages so an
        admin can see exactly which value caused a rejection.
        """
        if not employee:
            return _("no employee")
        emp = employee.sudo()
        if 'is_permanent' in emp._fields:
            return _("is_permanent=%s") % bool(emp.is_permanent)
        if 'employee_type' in emp._fields and emp.employee_type:
            type_desc = emp.employee_type
        else:
            type_desc = None
        contract = False
        if loan and hasattr(loan, '_get_latest_contract'):
            contract = loan._get_latest_contract(emp, sudo=True)
        if not contract:
            return _("employee_type=%s, no contract on file") % (type_desc or _("not set"))
        contract_type = getattr(contract, 'contract_type_id', False)
        if contract_type:
            contract_type_name = "%s (code: %s)" % (contract_type.name, getattr(contract_type, 'code', False) or '-')
        else:
            contract_type_name = _("not set")
        desc = _("employee_type=%s, contract type=%s") % (type_desc or _("not set"), contract_type_name)
        trial_end = getattr(contract, 'trial_date_end', False) or getattr(contract, 'probation_end_date', False)
        if trial_end and trial_end >= fields.Date.context_today(self):
            desc += _(", still in trial/probation until %s") % trial_end
        return desc

    @api.model
    def _label_says_permanent(self, label):
        """True only when a contract-type name explicitly says permanent.

        Matches WHOLE WORDS, not substrings. The old `term in name` test
        wrongly treated "Non-Permanent", "Not Permanent", "Unconfirmed" and
        "Irregular" as permanent (they literally contain 'permanent',
        'confirmed' and 'regular'), so those guarantors were never rejected.
        """
        tokens = set(re.findall(r'[a-z]+', (label or '').lower()))
        return bool(tokens & _PERMANENT_TERMS) and not (tokens & _NON_PERMANENT_TERMS)

    @api.model
    def _contract_type_says_permanent(self, contract_type):
        """Judge a hr.contract.type record by its `code` AND its `name`.

        On this database the permanent type is stored as name='P' and
        code='Permanent' (the full word lives in `code`, `name` is only an
        abbreviation), so reading `name` alone can never recognise it. Both
        labels are read together: the type counts as permanent when at least
        one of them says permanent AND neither carries a non-permanent /
        negating word (e.g. code 'Non-Permanent' or name 'Probation').
        A bare abbreviation such as 'P' is deliberately NOT guessed at.
        """
        if not contract_type:
            return False
        labels = ' '.join(
            str(getattr(contract_type, fld, '') or '') for fld in ('code', 'name')
        )
        return self._label_says_permanent(labels)

    @api.model
    def _permanent_problem(self, g_emp, loan=None):
        """Return the error text when the employee is NOT permanent staff,
        otherwise None. Read entirely through sudo (see
        ensure_guarantor_is_permanent)."""
        g_emp = g_emp.sudo()
        if self.is_permanent_employee(g_emp, loan):
            return None
        return (
            _("⚠️ Guarantor Ineligible:\n\n"
              "• Employment Status: Guarantor '%(name)s' must be permanent staff. "
              "Employees under probation, contract employment, or any other "
              "non-permanent terms cannot serve as guarantors "
              "(detected: %(detail)s).")
            % {'name': g_emp.name, 'detail': self._describe_contract_type(g_emp, loan)}
        )

    @api.model
    def ensure_guarantor_is_permanent(self, guarantor_employee, loan=None):
        """FR-RESL-007: raise a ValidationError unless the guarantor is
        permanent staff. Single source of truth used by every guarantor entry
        point (guarantee create/write constraint, Find Guarantor wizard,
        replacement flows, request/submit/approve actions).

        Everything is read through sudo(), so the check gives the same result
        for HR and for an ordinary employee — group-restricted fields such as
        employee_type / contract_type_id / trial_date_end must not make the
        check (or its error message) fail for the borrower.
        """
        if not guarantor_employee:
            raise ValidationError(_("Invalid guarantor specified."))
        message = self._permanent_problem(guarantor_employee, loan)
        if message:
            raise ValidationError(message)
        return True

    @api.model
    def is_permanent_employee(self, employee, loan=None):
        """
        FR-RESL-002, FR-RESL-003, FR-RESL-007:
        RSSA loans and guarantees are for PERMANENT staff ONLY. This is a
        strict ALLOW-LIST: an employee only passes when there is an
        explicit "permanent" signal (an is_permanent flag, or a contract
        type whose name says permanent/regular/indefinite/confirmed).
        EVERY other contract type — recognised as non-permanent (probation,
        contract, temporary, casual, intern, fixed-term, trainee) or simply
        unrecognised/blank — is rejected. Nothing falls through to a
        default "assume permanent". Employees under probation, contract
        employment, temporary, casual, internship, freelance, trainee, or
        student status must not pass.

        This check is intentionally independent of whether the contract is
        currently active/in force (that is FR-RESL-009, checked separately
        via _is_contract_active in check_borrower_eligibility /
        ensure_guarantor_is_eligible). An employee's contract TYPE can say
        "Permanent" even while that specific contract record fails the
        active/in-force check (e.g. an expired or not-yet-effective
        record); that must surface as a contract-status problem only, not
        also as a false "not permanent staff" rejection.
        """
        if not employee:
            return False

        emp = employee.sudo()

        # 1. Most authoritative: an explicit is_permanent boolean, if the
        # employee model provides one. Trust it either way.
        if 'is_permanent' in emp._fields:
            return bool(emp.is_permanent)

        # 2. Standard Odoo employee_type: anything other than 'employee'
        # (student, trainee, contractor, freelance) disqualifies outright,
        # before even looking at the contract.
        has_employee_type = 'employee_type' in emp._fields and bool(emp.employee_type)
        if has_employee_type and emp.employee_type != 'employee':
            return False

        # Resolve the employee's current/latest contract (or hr.version in
        # Odoo 19).
        contract = False
        if loan and hasattr(loan, '_get_latest_contract'):
            contract = loan._get_latest_contract(emp, sudo=True)
        else:
            # Fallback when called without a loan record: mirror
            # loan._get_latest_contract's Odoo 19 (hr.version) logic.
            for fld in ('version_id', 'current_version_id'):
                version = getattr(emp, fld, False)
                if version:
                    contract = version
                    break
            if not contract:
                for fld in ('version_ids', 'contract_ids'):
                    versions = getattr(emp, fld, False)
                    if versions:
                        contract = versions.sorted('date_start', reverse=True)[:1] if hasattr(versions, 'date_start') else versions[:1]
                        break
            if not contract and getattr(emp, 'contract_id', False):
                contract = emp.contract_id

        # No contract on file at all -> cannot confirm permanence.
        if not contract:
            return False

        # 3. Currently within a probation/trial period -> not eligible, no
        # matter what the contract type or employee_type says (Odoo 19:
        # hr.version uses 'trial_date_end'; older hr.contract used
        # 'probation_end_date').
        trial_end = getattr(contract, 'trial_date_end', False) or getattr(contract, 'probation_end_date', False)
        if trial_end:
            today = fields.Date.context_today(self)
            if trial_end >= today:
                return False

        # NOTE: whether the contract is currently active/in force is
        # deliberately NOT re-checked here. That is a separate concern
        # (FR-RESL-009, enforced independently in check_borrower_eligibility
        # / ensure_guarantor_is_eligible via _is_contract_active). Folding it
        # in here caused a genuinely permanent employee (contract type says
        # "Permanent") whose contract happened to fail the active check to
        # ALSO be reported as "not permanent staff" — a second, misleading
        # error for the same single root cause. Employment status
        # (permanent vs. not) must be judged only on the contract-type /
        # employee_type signals below; both validations are still run and
        # still enforced, they simply no longer cascade into one another.

        # 4. Contract type name, if set, is the ONLY thing consulted from
        # here on — and it is a strict allow-list: the type must
        # explicitly say "permanent" (or an accepted equivalent) to pass.
        # Any other named type — whether it matches a known non-permanent
        # keyword or is simply unrecognised — is rejected outright. There
        # is deliberately no fallback to employee_type here: once a
        # contract type is on file, it is authoritative and must not be
        # overridden by the more generic employee_type field.
        if hasattr(contract, 'contract_type_id') and contract.contract_type_id:
            return self._contract_type_says_permanent(contract.contract_type_id)

        # 5. No contract type recorded at all: there is now no explicit
        # "permanent" signal left to check. Being merely an active,
        # non-probationary employee with employee_type == 'employee' is
        # NOT sufficient — that is the generic default for virtually every
        # member of staff, permanent or not, and treating it as a "yes"
        # silently let any ordinary active employee pass as a permanent
        # guarantor whenever their contract type field was left blank.
        # Per the strict allow-list rule this method documents, an absent
        # signal must reject, not default to permanent.
        return False

    @api.model
    def check_borrower_eligibility(self, loan, employee=None, raise_exception=True):
        """
        Full Business Rules (18.2) & Functional Requirements (18.3) Borrower Validation:
        - FR-RESL-002: Permanent employment status & minimum 3 months continuous service.
        - FR-RESL-003: Not under probation, contract employment, suspension (disciplinary
          record or active "Suspense" leave), or investigation.
        - FR-RESL-004: Retirement eligibility (Age < 58 / > 2 years to retirement; no outstanding balance if >= 58).
        - FR-RESL-009: Active employment contract verified from Employee Module.
        - FR-RESL-010: Returns descriptive reasons for any failure.
        """
        emp = (employee or loan.employee_id).sudo()
        if not emp:
            if raise_exception:
                raise ValidationError(_("Borrower employee record is missing."))
            return False, [_("Borrower employee record is missing.")]

        reasons = []

        # 1. Employment Contract: Must be Active (18.2, FR-RESL-009)
        contract = loan._get_latest_contract(emp, sudo=True) if hasattr(loan, '_get_latest_contract') else False
        if not self._is_contract_active(contract):
            reasons.append(
                _("Employment Contract: Borrower does not have an active employment contract.")
            )

        # 2. Employment Status: Must be Permanent (18.2, FR-RESL-002, FR-RESL-003)
        if not self.is_permanent_employee(emp, loan):
            reasons.append(
                _("Employment Status: Borrower must be permanent staff. Employees under probation, "
                  "contract employment, or any other non-permanent terms are not eligible "
                  "(detected contract type: %s).")
                % self._describe_contract_type(emp, loan)
            )

        # 3. Minimum Service: At least 3 months continuous service (18.2, FR-RESL-002)
        months_service = loan._months_of_service(emp) if hasattr(loan, '_months_of_service') else 0
        if months_service < 3:
            reasons.append(
                _("Minimum Service: Borrower has %s month(s) of continuous service. "
                  "At least 3 months continuous service is required before applying.")
                % months_service
            )

        # 4. Retirement Eligibility (18.2, FR-RESL-004)
        years_left = loan._years_to_retirement(emp, retirement_age=60) if hasattr(loan, '_years_to_retirement') else None
        if years_left is not None and years_left <= 2:
            reasons.append(
                _("Retirement Eligibility: Employee is within two years of mandatory retirement "
                  "(age 58 or older) and is not eligible to apply for a new RSSA loan.")
            )

        # Check existing outstanding balance if near retirement or general
        outstanding_loans = self.env['resl.loan'].sudo().search([
            ('employee_id', '=', emp.id),
            ('status', '=', 'approved'),
            ('id', '!=', loan.id if loan else 0),
        ])
        if outstanding_loans:
            total_unsettled = sum(float(l.approved_amount or 0.0) for l in outstanding_loans)
            if years_left is not None and years_left <= 2 and total_unsettled > 0:
                reasons.append(
                    _("Retirement Eligibility: Employees aged 58 or older with an outstanding RSSA "
                      "balance cannot be granted a new loan until existing loans are fully settled.")
                )

        # 5. Employee Disciplinary Status: Must be Eligible (18.2, FR-RESL-003)
        disp_eligible, disp_reason = self.check_employee_disciplinary_status(emp)
        if not disp_eligible:
            reasons.append(
                _("Disciplinary Status: %s") % disp_reason
            )

        # 6. Suspense Leave: Must not be on an active administrative
        # suspension recorded via Time Off (18.2, FR-RESL-003)
        susp_eligible, susp_reason = self.check_employee_suspension_leave(emp)
        if not susp_eligible:
            reasons.append(
                _("Suspension: %s") % susp_reason
            )

        if reasons:
            if raise_exception:
                formatted_reasons = "\n• " + "\n• ".join(reasons)
                raise ValidationError(
                    _("Ineligible RSSA Request:\n%s") % formatted_reasons
                )
            return False, reasons

        return True, []

    @api.model
    def borrower_guarantor_employees(self, loan, exclude_loan_id=None):
        """Distinct guarantors the borrower of `loan` already has on their
        OTHER requests (the request being edited is excluded, so changing or
        replacing its guarantor is judged against the remaining history).

        Not counted: lines that are rejected / replaced / separated, and
        requests that were rejected.
        """
        borrower = loan.employee_id
        if not borrower:
            return self.env['hr.employee']
        exclude = set()
        if loan.id and isinstance(loan.id, int):
            exclude.add(loan.id)
        if exclude_loan_id:
            exclude.add(int(exclude_loan_id))
        domain = [
            ('loan_id.employee_id', '=', borrower.id),
            ('loan_id.status', '!=', 'rejected'),
            ('state', 'not in', ('replaced', 'separated', 'rejected')),
            ('guarantor_id', '!=', False),
        ]
        if exclude:
            domain.append(('loan_id', 'not in', list(exclude)))
        lines = self.env['resl.loan.guarantee'].sudo().search(domain)
        return lines.mapped('guarantor_id')

    @api.model
    def _guarantor_problems(self, loan, guarantor_employee, exclude_loan_id=None):
        """Lazily yield (short_reason, full_message) for the FIRST rule the
        guarantor fails, in the fixed rule order below, then stop. Yields
        nothing when the guarantor is eligible.

        This is the single place the guarantor rules live. It feeds both:
          - ensure_guarantor_is_eligible(): raises the full message, and
          - guarantor_eligibility(): returns the short reason without raising
            (used by the Find Guarantor list to flag people BEFORE selection).
        Rules (BRD 18.2 / 18.3): not the borrower, permanent staff (FR-RESL-007),
        active contract (FR-RESL-009), >= 3 months service, not within 2 years
        of retirement (FR-RESL-004), no active disciplinary action or suspension
        (FR-RESL-003), salary not lower than the borrower's (FR-RESL-007),
        at most 2 active guarantees (FR-RESL-008), and the
        borrower may have at most 2 DISTINCT guarantors across all of their
        requests (each request itself has a single guarantor).
        """
        if not guarantor_employee:
            yield (_("Invalid guarantor"), _("Invalid guarantor specified."))
            return

        g_emp = guarantor_employee.sudo()

        # 0. Cannot guarantee oneself
        if loan.employee_id and loan.employee_id.id == g_emp.id:
            yield (_("This is the borrower"),
                   _("Borrower cannot act as their own guarantor."))
            return

        # 1. Permanent staff — checked FIRST so a non-permanent guarantor
        # always gets this error, never a misleading contract message.
        message = self._permanent_problem(g_emp, loan)
        if message:
            yield (_("Not permanent staff (%s)") % self._describe_contract_type(g_emp, loan), message)
            return

        # 2. Active employment contract (FR-RESL-007, FR-RESL-009)
        contract = loan._get_latest_contract(g_emp, sudo=True) if hasattr(loan, '_get_latest_contract') else False
        if not self._is_contract_active(contract):
            yield (_("No active employment contract"),
                   _("Guarantor '%s' does not have an active employment contract.") % g_emp.name)
            return

        # 3. Minimum service: 3 months continuous (18.2)
        months = loan._months_of_service(g_emp) if hasattr(loan, '_months_of_service') else 0
        if months < 3:
            yield (_("Only %s month(s) of service (3 required)") % months,
                   _("Guarantor '%s' has only %s month(s) of continuous service. "
                     "At least 3 months continuous service is required (18.2).") % (g_emp.name, months))
            return

        # 4. Retirement (FR-RESL-004)
        years_left = loan._years_to_retirement(g_emp, retirement_age=60) if hasattr(loan, '_years_to_retirement') else None
        if years_left is not None and years_left <= 2:
            yield (_("Within 2 years of retirement"),
                   _("Guarantor '%s' is within two years of mandatory retirement (age 58 or older) "
                     "and is not eligible to serve as a guarantor.") % g_emp.name)
            return

        # 5. Disciplinary status (FR-RESL-003)
        disp_eligible, disp_reason = self.check_employee_disciplinary_status(g_emp)
        if not disp_eligible:
            yield (_("Disciplinary: %s") % disp_reason,
                   _("Guarantor '%s' is not eligible due to disciplinary status: %s.")
                   % (g_emp.name, disp_reason))
            return

        # 5b. Suspension leave (FR-RESL-003)
        susp_eligible, susp_reason = self.check_employee_suspension_leave(g_emp)
        if not susp_eligible:
            yield (susp_reason,
                   _("Guarantor '%s' is not eligible: %s.") % (g_emp.name, susp_reason))
            return

        # 5c. Salary (FR-RESL-007): the guarantor's basic salary must be equal
        # to or greater than the borrower's. Checked here so it is raised the
        # moment the guarantor is selected (and flagged in the Find Guarantor
        # list) instead of only later when the request is submitted.
        if loan.employee_id and hasattr(loan, '_employee_current_wage'):
            borrower_salary = float(loan._employee_current_wage(loan.employee_id.sudo()) or 0.0)
            if borrower_salary:
                g_wage = float(loan._employee_current_wage(g_emp) or 0.0)
                if g_wage < borrower_salary:
                    yield (_("Salary (%s) is lower than the borrower's (%s)") % (g_wage, borrower_salary),
                           _("Guarantor salary (%s) must be equal to or greater than the "
                             "borrower's basic salary (%s).") % (g_wage, borrower_salary))
                    return

        # 6. Guarantee limit: max 2 active borrowers (FR-RESL-008)
        Guarantee = self.env['resl.loan.guarantee'].sudo()
        domain = [
            ('guarantor_id', '=', g_emp.id),
            ('state', '=', 'accepted'),
            ('loan_id.status', '=', 'approved'),
        ]
        if exclude_loan_id:
            domain.append(('loan_id', '!=', int(exclude_loan_id)))
        guarantees = Guarantee.search(domain)
        unique_borrowers = set(guarantees.mapped('loan_id.employee_id.id'))
        current_borrower = loan.employee_id.id if loan.employee_id else None
        if current_borrower in unique_borrowers:
            unique_borrowers.remove(current_borrower)
        if len(unique_borrowers) >= 2:
            yield (_("Already guarantees 2 borrowers (maximum)"),
                   _("Guarantor '%s' already guarantees the maximum allowed number of active "
                     "borrowers (2).") % g_emp.name)
            return

        # 7. Borrower-side limit: an employee can have at most 2 DISTINCT
        # guarantors across all of their requests. A guarantor the borrower
        # already used before is always fine; a NEW one is refused once the
        # borrower has 2 already (they must pick one of those two).
        if loan.employee_id:
            known = self.borrower_guarantor_employees(loan, exclude_loan_id)
            if g_emp.id not in known.ids and len(known) >= 2:
                names = ", ".join(known.mapped('name'))
                yield (_("Borrower already has 2 guarantors (%s)") % names,
                       _("This employee already has 2 guarantors (%s) on previous requests. "
                         "Please choose one of them for this request.") % names)
                return

    @api.model
    def ensure_guarantor_is_eligible(self, loan, guarantor_employee, exclude_loan_id=None, strict=True):
        """Raise a ValidationError (full message) for the first rule the
        guarantor fails; return True when eligible. See _guarantor_problems."""
        problem = next(self._guarantor_problems(loan, guarantor_employee, exclude_loan_id), None)
        if problem:
            raise ValidationError(problem[1])
        return True

    @api.model
    def guarantor_eligibility(self, loan, guarantor_employee, exclude_loan_id=None):
        """Non-raising twin of ensure_guarantor_is_eligible.
        Returns (True, '') or (False, short_reason)."""
        problem = next(self._guarantor_problems(loan, guarantor_employee, exclude_loan_id), None)
        return (False, problem[0]) if problem else (True, "")

    @api.model
    def validate_guarantor_salaries(self, loans, consider_states=('accepted', 'pending'), strict=False):
        """
        18.2 & FR-RESL-007: Guarantor salary must be equal to or greater than borrower salary.
        """
        if not loans:
            return True
        for loan in loans:
            borrower_salary = float(loan._employee_current_wage(loan.employee_id.sudo()) or 0.0)
            if not borrower_salary:
                continue
            lines = loan.guarantor_line_ids.filtered(
                lambda line: line.guarantor_id and line.state in consider_states
            )
            unique_guarantors = list(dict.fromkeys(lines.mapped('guarantor_id')))
            if not unique_guarantors:
                continue

            wages = [
                float(loan._employee_current_wage(g.sudo()) or 0.0)
                for g in unique_guarantors
            ]
            if len(unique_guarantors) == 1:
                if wages[0] < borrower_salary:
                    raise ValidationError(
                        _("Guarantor salary (%s) must be equal to or greater than the borrower's basic salary (%s).")
                        % (wages[0], borrower_salary)
                    )
            else:
                if sum(wages) < borrower_salary:
                    raise ValidationError(
                        _("Combined guarantor salaries (%s) do not cover the borrower's basic salary (%s).")
                        % (sum(wages), borrower_salary)
                    )
            if strict:
                for g_emp in unique_guarantors:
                    g_wage = float(loan._employee_current_wage(g_emp.sudo()) or 0.0)
                    if g_wage < borrower_salary:
                        raise ValidationError(
                            _("Guarantor '%s' salary (%s) is lower than borrower's basic salary (%s).")
                            % (g_emp.name, g_wage, borrower_salary)
                        )
        return True