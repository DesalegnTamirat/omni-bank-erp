# -*- coding: utf-8 -*-
"""Unified Planning Categories logic - Enhanced for Manpower & Fixed Asset."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression

from .pbms_plan_line_mixin import MONTH_FIELDS, QUARTERS
from .pbms_access import PBMS_BRANCH_EDITABLE_STATES, PBMS_CONTENT_FIELDS


# Manpower headcount months (Jul-Jun) — integers, separate from Monetary m01-m12.
HC_MONTH_FIELDS = [f"hc_{m}" for m in MONTH_FIELDS]
HC_QUARTERS = {
    "q1": HC_MONTH_FIELDS[0:3],   # Jul-Sep
    "q2": HC_MONTH_FIELDS[3:6],   # Oct-Dec
    "q3": HC_MONTH_FIELDS[6:9],   # Jan-Mar
    "q4": HC_MONTH_FIELDS[9:12],  # Apr-Jun
}


# Category-specific fields that must be set for a given category (now stored on lines).
CATEGORY_REQUIRED_FIELDS = {
    "deposit": [],
    "customer_base": [],
    "fx": [],
    "digital_banking": [],
    "general_expense": [],
    "manpower": [],
    "fixed_asset": [],
}

# All planning categories support itemized lines within a single plan submission.
ITEMIZED_CATEGORIES = (
    "deposit",
    "customer_base",
    "fx",
    "digital_banking",
    "general_expense",
    "manpower",
    "fixed_asset",
)

# Work Unit Type options (mirrors operating.unit.work_unit_type).
WORK_UNIT_TYPES = [
    ("branch", "Branch"),
    ("sub_branch", "Sub-Branch"),
    ("head_office", "Head Office"),
    ("regional_office", "Regional Office"),
    ("district_office", "District Office"),
    ("service_center", "Service Center"),
    ("other", "Other"),
]

# Quarter fields for itemized categories
QUARTER_FIELDS = ['q1', 'q2', 'q3', 'q4']
QUARTER_LABELS = {
    'q1': 'Q1 (Jul-Sep)',
    'q2': 'Q2 (Oct-Dec)',
    'q3': 'Q3 (Jan-Mar)',
    'q4': 'Q4 (Apr-Jun)',
}


class HrEmployeeGrade(models.Model):
    _inherit = "employee.grade"

    @api.depends("grade_code", "grade_name")
    def _compute_display_name(self):
        for rec in self:
            if rec.grade_code and rec.grade_name:
                rec.display_name = f"{rec.grade_code} - {rec.grade_name}"
            elif rec.grade_code:
                rec.display_name = rec.grade_code
            elif rec.grade_name:
                rec.display_name = rec.grade_name
            else:
                rec.display_name = _("Grade #%s") % rec.id

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=100, order=None):
        domain = domain or []
        if name:
            domain = ['|', ('grade_code', operator, name), ('grade_name', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)


class PbmsDepositType(models.Model):
    _name = "pbms.deposit.type"
    _description = "Deposit Product Type"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_ifb = fields.Boolean(string="Interest-Free Banking", default=False)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Deposit type code must be unique.")


class PbmsDigitalChannel(models.Model):
    _name = "pbms.digital.channel"
    _description = "Digital Banking Channel"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    unit_of_measure = fields.Selection(
        [("count", "Count"), ("amount", "Amount")], required=True, default="count",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Digital channel code must be unique.")


class PbmsExpenseAccount(models.Model):
    _name = "pbms.expense.account"
    _description = "General Expense Account"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Expense account code must be unique.")


class PbmsFixedAssetCategory(models.Model):
    _name = "pbms.fixed.asset.category"
    _description = "Fixed Asset Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    reference_unit_price = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Fixed asset category code must be unique.")


class PbmsFxSourceType(models.Model):
    """Configurable FX Source / Channel for FX Mobilization planning."""
    _name = "pbms.fx.source.type"
    _description = "FX Source Type"
    _order = "sequence, name"

    name = fields.Char(string="FX Source", required=True)
    code = fields.Char(string="Code", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)

    _code_uniq = models.Constraint("unique(code)", "FX source code must be unique.")


class PbmsJustificationCategory(models.Model):
    """Configurable Business Justification Category for Workforce / Manpower and other planning."""
    _name = "pbms.justification.category"
    _description = "Business Justification Category"
    _order = "sequence, name"

    name = fields.Char(string="Category Name", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    requires_remarks = fields.Boolean(
        string="Requires Remarks",
        default=False,
        help="If ticked, requestors must provide additional remarks/specifications when selecting this category."
    )
    description = fields.Text(string="Guidance / Description")
    active = fields.Boolean(string="Active", default=True)

    _code_uniq = models.Constraint("unique(code)", "Justification category code must be unique.")


class PbmsPositionType(models.Model):
    """Configurable Request Types / Position Types for Manpower planning."""
    _name = "pbms.position.type"
    _description = "Manpower Position / Request Type"
    _order = "sequence, name"

    name = fields.Char(string="Request Type", required=True, translate=True)
    code = fields.Char(string="Code", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    is_new_position = fields.Boolean(
        string="Is New Position (Custom Title/Grade)",
        default=False,
        help="If ticked, this request type requires specifying a new job title and grade instead of selecting an existing job position."
    )
    active = fields.Boolean(string="Active", default=True)

    _code_uniq = models.Constraint("unique(code)", "Position type code must be unique.")

    def init(self):
        """Auto-seed only 'New Position' and 'Additional Position', clean up deprecated types, and ensure XML ID binding."""
        super().init()
        default_types = [
            ("New Position", "new", 10, True),
            ("Additional Position", "additional", 20, False),
        ]
        IrModelData = self.env["ir.model.data"]
        for name, code, seq, is_new in default_types:
            xml_id = f"pos_type_{code}"
            data_rec = IrModelData.search([
                ("module", "=", "bunna_pbms"),
                ("name", "=", xml_id),
            ], limit=1)

            # Find all existing records with this code
            all_recs = self.search([("code", "=", code)], order="id asc")
            if all_recs:
                # Pick the record referenced by ir.model.data, or the first record
                if data_rec and data_rec.res_id in all_recs.ids:
                    primary = self.browse(data_rec.res_id)
                else:
                    primary = all_recs[0]

                # Merge any duplicates into the primary record
                dups = all_recs - primary
                if dups:
                    self.env["pbms.plan.category.line"].search([
                        ("position_type_id", "in", dups.ids)
                    ]).write({"position_type_id": primary.id})
                    for cfg in self.env["pbms.planning.config"].search([]):
                        if any(d in cfg.position_type_ids for d in dups):
                            cfg.position_type_ids = [(3, d.id) for d in dups] + [(4, primary.id)]
                    dups.unlink()

                # Ensure ir.model.data points to the primary record
                if not data_rec:
                    IrModelData.create({
                        "module": "bunna_pbms",
                        "name": xml_id,
                        "model": "pbms.position.type",
                        "res_id": primary.id,
                        "noupdate": True,
                    })
                elif data_rec.res_id != primary.id:
                    data_rec.write({"res_id": primary.id})
            else:
                new_rec = self.create({
                    "name": name,
                    "code": code,
                    "sequence": seq,
                    "is_new_position": is_new,
                    "active": True,
                })
                if not data_rec:
                    IrModelData.create({
                        "module": "bunna_pbms",
                        "name": xml_id,
                        "model": "pbms.position.type",
                        "res_id": new_rec.id,
                        "noupdate": True,
                    })
                elif data_rec.res_id != new_rec.id:
                    data_rec.write({"res_id": new_rec.id})

        # Remove deprecated position types: replacement, transfer, upgrade
        deprecated_codes = ["replacement", "transfer", "upgrade"]
        dep_recs = self.search([("code", "in", deprecated_codes)])
        if dep_recs:
            additional = self.search([("code", "=", "additional")], limit=1)
            target_id = additional.id if additional else False
            if target_id:
                self.env["pbms.plan.category.line"].search([
                    ("position_type_id", "in", dep_recs.ids)
                ]).write({"position_type_id": target_id, "position_type": "additional"})
                for cfg in self.env["pbms.planning.config"].search([]):
                    if any(d in cfg.position_type_ids for d in dep_recs):
                        cfg.position_type_ids = [(3, d.id) for d in dep_recs] + [(4, target_id)]
            for code in deprecated_codes:
                IrModelData.search([
                    ("module", "=", "bunna_pbms"),
                    ("name", "=", f"pos_type_{code}"),
                ]).unlink()
            dep_recs.unlink()


class PbmsExistingManpowerSummary(models.Model):
    """Position-level establishment & salary summary for Existing Manpower tab."""
    _name = "pbms.existing.manpower.summary"
    _description = "Existing Work Force Position Summary"
    _order = "job_id, grade_id"

    plan_id = fields.Many2one(
        "pbms.planning.category",
        string="Planning Record",
        required=False,
        ondelete="cascade",
        index=True,
    )
    job_id = fields.Many2one("hr.job", string="Eligible Job Position", required=True)
    grade_id = fields.Many2one("employee.grade", string="Job Grade")
    approved_plan_count = fields.Integer(string="Authorized Baseline", default=0)
    active_employee_count = fields.Integer(string="Active Staff Count", default=0)
    vacant_position_count = fields.Integer(string="Vacant Positions", default=0)
    monthly_salary = fields.Monetary(string="Monthly Gross Salary", currency_field="currency_id", default=0.0)
    annual_salary = fields.Monetary(string="Fiscal Year Salary (Annual)", currency_field="currency_id", default=0.0)
    currency_id = fields.Many2one("res.currency", related="plan_id.currency_id", store=True, readonly=True)


class PbmsExistingEmployeeLine(models.Model):
    """Itemized active employee & contract record for Existing Manpower tab."""
    _name = "pbms.existing.employee.line"
    _description = "Existing Active Employee & Salary Roster"
    _order = "job_id, employee_id"

    plan_id = fields.Many2one(
        "pbms.planning.category",
        string="Planning Record",
        required=False,
        ondelete="cascade",
        index=True,
    )
    employee_id = fields.Many2one("hr.employee", string="Employee Name", required=True)
    employee_code = fields.Char(string="Staff ID / Code")
    job_id = fields.Many2one("hr.job", string="Job Position")
    grade_id = fields.Many2one("employee.grade", string="Job Grade")
    contract_id = fields.Many2one("hr.version", string="Contract / Version")
    wage = fields.Monetary(string="Monthly Gross Wage", currency_field="currency_id", default=0.0)
    annual_salary = fields.Monetary(string="Fiscal Year Salary (Annual)", currency_field="currency_id", default=0.0)
    contract_state = fields.Selection([
        ('draft', 'New'),
        ('probation', 'Probation'),
        ('open', 'Running'),
        ('close', 'Expired'),
        ('cancel', 'Cancelled'),
    ], string="Contract Status", default="open")
    currency_id = fields.Many2one("res.currency", related="plan_id.currency_id", store=True, readonly=True)


class PbmsReviewComment(models.Model):
    """Permanent Audit Log and Review Comments for Planning Categories."""
    _name = "pbms.review.comment"
    _description = "PBMS Review Comment & Audit Trail"
    _order = "date desc, id desc"

    plan_id = fields.Many2one(
        "pbms.planning.category",
        string="Planning Record",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User / Reviewer",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    date = fields.Datetime(
        string="Date & Time",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    stage_from = fields.Char(string="From Stage", readonly=True)
    stage_to = fields.Char(string="To Stage", readonly=True)
    action_type = fields.Selection(
        [
            ("submit", "Submission"),
            ("review_comment", "Review Comment"),
            ("request_info", "Requested Info"),
            ("return", "Returned for Revision"),
            ("recommend_rejection", "Recommended Rejection"),
            ("reject", "Rejection"),
            ("district_approve", "District Approval"),
            ("district_approve_workforce", "District Workforce Review & Escalation"),
            ("chief_approve_escalate", "Respective Chief Approval & Escalation"),
            ("chief_reject", "Respective Chief Rejection"),
            ("people_solutions_escalate", "People Solutions Assessment & Escalation"),
            ("cpco_submit_committee", "CPCO Submit to Committee"),
            ("cpco_reject", "CPCO Rejection"),
            ("cpco_submit_board_ceo", "CPCO Board / CEO Submission"),
            ("record_board_ceo_approval", "CEO / Board Approval Recorded"),
            ("record_board_ceo_rejection", "CEO / Board Rejection Recorded"),
            ("ho_review", "Head Office Review"),
            ("ho_endorse_cpco", "HO Functional Reviewer Endorsement to CPCO"),
            ("cpco_endorse_solutions", "CPCO Final Endorsement to People Solutions"),
            ("ho_approve", "Head Office Final Approval"),
            ("hr_submit_committee", "Submitted to Committee"),
            ("submit_committee", "Submitted to Review Committee"),
            ("committee_approve", "Committee Approval"),
            ("committee_reject", "Committee Rejection"),
            ("hr_submit_sourcing", "Sourcing Plan Submitted"),
            ("cpco_submit_sourcing", "CPCO Sourcing Submitted"),
            ("ceo_approve", "CEO Approval"),
            ("ceo_reject", "CEO Rejection"),
            ("approve", "Final Approval"),
            ("reset_draft", "Reopened / Reset to Draft"),
        ],
        string="Action",
        required=True,
        default="review_comment",
        readonly=True,
    )
    comment = fields.Text(string="Comment / Justification", required=True)


class PbmsPlanCategoryLine(models.Model):
    _name = "pbms.plan.category.line"
    _description = "Planning Category Requirement Line"
    _order = "id"

    plan_id = fields.Many2one(
        "pbms.planning.category", required=False, ondelete="cascade", index=True,
    )
    org_unit_id = fields.Many2one(
        "operating.unit", related="plan_id.org_unit_id", store=True, string="Operating Unit", index=True,
    )
    source_unit_id = fields.Many2one(
        "operating.unit",
        string="Branch / Work Unit",
        index=True,
        compute="_compute_source_unit_id",
        store=True,
        readonly=False,
    )
    source_line_id = fields.Many2one(
        "pbms.plan.category.line",
        string="Source Branch Line",
        index=True,
        ondelete="set null",
        help="Points to the original branch plan line when this line was consolidated into a District Overview Plan.",
    )

    @api.depends("plan_id.org_unit_id")
    def _compute_source_unit_id(self):
        for line in self:
            if not line.source_unit_id:
                line.source_unit_id = line.plan_id.org_unit_id

    sol_id = fields.Integer(
        string="Sol ID",
        compute="_compute_sol_id",
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends("source_unit_id", "source_unit_id.sol_id", "plan_id.org_unit_id", "plan_id.org_unit_id.sol_id")
    def _compute_sol_id(self):
        for line in self:
            unit = line.source_unit_id or (line.plan_id.org_unit_id if line.plan_id else False)
            line.sol_id = unit.sol_id if unit and hasattr(unit, "sol_id") else 0

    org_unit_type = fields.Selection(
        related="plan_id.org_unit_type", store=True, string="Unit Type", index=True,
    )
    available_job_ids = fields.Many2many(
        "hr.job", related="plan_id.available_job_ids", readonly=True,
    )
    district_id = fields.Many2one(
        "operating.unit",
        string="District",
        store=True,
        index=True,
        compute="_compute_district_id",
        readonly=False,
    )

    @api.depends("source_unit_id", "source_unit_id.parent_unit", "source_unit_id.work_unit_type", "plan_id.district_id", "plan_id.org_unit_id")
    def _compute_district_id(self):
        for line in self:
            unit = line.source_unit_id or (line.plan_id.org_unit_id if line.plan_id else False)
            found_dist = False
            curr = unit
            while curr:
                if curr.work_unit_type in ("district_office", "regional_office"):
                    found_dist = curr
                    break
                curr = curr.parent_unit
            if found_dist:
                line.district_id = found_dist
            elif line.plan_id and line.plan_id.district_id:
                line.district_id = line.plan_id.district_id
            elif unit and unit.work_unit_type == "head_office":
                line.district_id = unit.parent_unit or unit
            else:
                line.district_id = False

    broad_category = fields.Char(
        string="Broad Category",
        compute="_compute_broad_category",
        store=True,
        index=True,
    )

    @api.depends("source_unit_id", "source_unit_id.work_unit_type", "org_unit_type", "plan_id.org_unit_type")
    def _compute_broad_category(self):
        for line in self:
            unit = line.source_unit_id or line.org_unit_id or (line.plan_id.org_unit_id if line.plan_id else False)
            wtype = (unit.work_unit_type if unit else False) or line.org_unit_type or (line.plan_id.org_unit_type if line.plan_id else False)
            if wtype in ("branch", "sub_branch", "service_center"):
                line.broad_category = "1.Branches"
            elif wtype in ("district_office", "regional_office"):
                line.broad_category = "2.District Office"
            elif wtype == "head_office":
                line.broad_category = "3.Head Office"
            else:
                line.broad_category = "1.Branches"

    cycle_id = fields.Many2one(
        "pbms.planning.cycle", related="plan_id.cycle_id", store=True, string="Cycle", index=True,
    )
    plan_state = fields.Selection(
        related="plan_id.state", store=True, string="Plan Status", index=True,
    )
    planner_id = fields.Many2one(
        "res.users", string="Planner", compute="_compute_line_workflow_stakeholders", store=True, index=True,
    )
    submitted_by = fields.Many2one(
        "res.users", related="plan_id.submitted_by", string="Submitted By", store=True, readonly=True,
    )
    district_reviewer_id = fields.Many2one(
        "res.users", related="plan_id.district_reviewer_id", string="District Reviewer", store=True, readonly=True,
    )
    ho_reviewer_id = fields.Many2one(
        "res.users", related="plan_id.ho_reviewer_id", string="Head Office Reviewer", store=True, readonly=True,
    )
    approver_id = fields.Many2one(
        "res.users", related="plan_id.approver_id", string="SPPMD Approver", store=True, readonly=True,
    )

    @api.depends("plan_id.submitted_by", "plan_id.create_uid", "create_uid")
    def _compute_line_workflow_stakeholders(self):
        for line in self:
            line.planner_id = (
                (line.plan_id and line.plan_id.submitted_by)
                or (line.plan_id and line.plan_id.create_uid)
                or line.create_uid
                or self.env.user
            )

    quantity = fields.Integer(
        string="Quantity", compute="_compute_quantity", store=True, readonly=False,
    )

    line_type = fields.Selection(
        [
            ("deposit", "Deposit Mobilization"),
            ("customer_base", "Customer Base"),
            ("fx", "FX Mobilization"),
            ("digital_banking", "Digital Banking"),
            ("general_expense", "General Expense"),
            ("manpower", "Work Force"),
            ("fixed_asset", "Fixed Asset"),
        ],
        string="Line Type",
        compute="_compute_line_type",
        store=True,
        readonly=False,
    )

    # ---- Configurable dropdown domains (from planning config) ----
    deposit_type_domain = fields.Char(compute="_compute_deposit_type_domain", store=False)
    channel_domain = fields.Char(compute="_compute_channel_domain", store=False)
    expense_account_domain = fields.Char(compute="_compute_expense_account_domain", store=False)
    fa_category_domain = fields.Char(compute="_compute_fa_category_domain", store=False)
    justification_category_domain = fields.Char(compute="_compute_justification_category_domain", store=False)
    fx_source_type_domain = fields.Char(compute="_compute_fx_source_type_domain", store=False)

    # ---- Deposit ----
    deposit_type_id = fields.Many2one("pbms.deposit.type", string="Deposit Type", index=True)
    plan_category = fields.Selection(
        [("amount", "Amount")],
        string="Plan Basis", default="amount",
    )
    measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Measurement Type",
        compute="_compute_line_measurement",
        store=True,
    )
    is_monetary = fields.Boolean(compute="_compute_line_measurement", store=True)

    @api.depends("line_type", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
                 "plan_id.deposit_measurement_type", "plan_id.digital_banking_measurement_type",
                 "plan_id.customer_base_measurement_type", "plan_id.fx_measurement_type",
                 "plan_id.expense_measurement_type")
    def _compute_line_measurement(self):
        Config = self.env["pbms.planning.config"]
        for line in self:
            cat = line.line_type or "deposit"
            org_unit = line.plan_id.org_unit_id if line.plan_id else False
            mtype = Config.get_measurement_type(cat, org_unit=org_unit)
            line.measurement_type = mtype
            line.is_monetary = (mtype == "monetary")

    # ---- Customer Base ----
    base_type = fields.Selection(
        [
            ("new_acquisition", "New Customer Acquisition"),
            ("dormant_reduction", "Dormant Account Reduction"),
        ],
        string="Base Type", default="new_acquisition",
    )

    # ---- FX ----
    fx_source_type = fields.Many2one(
        "pbms.fx.source.type", string="FX Source", index=True,
    )
    fx_currency_id = fields.Many2one(
        "res.currency", string="FX Currency",
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False) or self.env.company.currency_id,
        help="FX Mobilization is planned in USD.",
    )

    # ---- Digital Banking ----
    channel_id = fields.Many2one("pbms.digital.channel", string="Digital Channel", index=True)

    # ---- General Expense ----
    expense_account_id = fields.Many2one("pbms.expense.account", string="Expense Account", index=True)
    prior_year_actual = fields.Monetary(string="Prior Year Actual", currency_field="currency_id")
    is_office_rent = fields.Boolean(string="Office Rent")

    # ---- Monthly targets (Float allows seamless integer/number or monetary formatting) ----
    opening_balance = fields.Float(string="Opening / Current Balance")
    m01 = fields.Float(string="Jul")
    m02 = fields.Float(string="Aug")
    m03 = fields.Float(string="Sep")
    m04 = fields.Float(string="Oct")
    m05 = fields.Float(string="Nov")
    m06 = fields.Float(string="Dec")
    m07 = fields.Float(string="Jan")
    m08 = fields.Float(string="Feb")
    m09 = fields.Float(string="Mar")
    m10 = fields.Float(string="Apr")
    m11 = fields.Float(string="May")
    m12 = fields.Float(string="Jun")

    quarter1_total = fields.Float(
        string="Q1 (Jul - Sep)",
        compute="_compute_quarter_targets", store=True, readonly=False,
    )
    quarter2_total = fields.Float(
        string="Q2 (Oct - Dec)",
        compute="_compute_quarter_targets", store=True, readonly=False,
    )
    quarter3_total = fields.Float(
        string="Q3 (Jan - Mar)",
        compute="_compute_quarter_targets", store=True, readonly=False,
    )
    quarter4_total = fields.Float(
        string="Q4 (Apr - Jun)",
        compute="_compute_quarter_targets", store=True, readonly=False,
    )
    annual_total = fields.Float(
        string="Annual Total",
        compute="_compute_annual_total",
        inverse="_inverse_annual_total",
        store=True,
        readonly=False,
    )
    outstanding_year_end = fields.Float(
        string="Projected Year-End",
        compute="_compute_outstanding_year_end", store=True,
    )

    # ---- DUAL-LAYER TARGET TRACKING: Proposed Plan vs Approved (Cascaded) Target ----
    is_cascaded = fields.Boolean(
        string="Is Cascaded Target", default=False, copy=False,
    )
    proposed_opening_balance = fields.Float(string="Proposed Opening Balance")
    proposed_m01 = fields.Float(string="Proposed Jul")
    proposed_m02 = fields.Float(string="Proposed Aug")
    proposed_m03 = fields.Float(string="Proposed Sep")
    proposed_m04 = fields.Float(string="Proposed Oct")
    proposed_m05 = fields.Float(string="Proposed Nov")
    proposed_m06 = fields.Float(string="Proposed Dec")
    proposed_m07 = fields.Float(string="Proposed Jan")
    proposed_m08 = fields.Float(string="Proposed Feb")
    proposed_m09 = fields.Float(string="Proposed Mar")
    proposed_m10 = fields.Float(string="Proposed Apr")
    proposed_m11 = fields.Float(string="Proposed May")
    proposed_m12 = fields.Float(string="Proposed Jun")
    proposed_annual_total = fields.Float(
        string="Proposed / Planned Total",
        compute="_compute_proposed_annual_total", store=True, readonly=False,
    )

    approved_opening_balance = fields.Float(string="Approved Opening Balance")
    approved_m01 = fields.Float(string="Approved Jul")
    approved_m02 = fields.Float(string="Approved Aug")
    approved_m03 = fields.Float(string="Approved Sep")
    approved_m04 = fields.Float(string="Approved Oct")
    approved_m05 = fields.Float(string="Approved Nov")
    approved_m06 = fields.Float(string="Approved Dec")
    approved_m07 = fields.Float(string="Approved Jan")
    approved_m08 = fields.Float(string="Approved Feb")
    approved_m09 = fields.Float(string="Approved Mar")
    approved_m10 = fields.Float(string="Approved Apr")
    approved_m11 = fields.Float(string="Approved May")
    approved_m12 = fields.Float(string="Approved Jun")
    approved_annual_total = fields.Float(
        string="Approved / Cascaded Total",
        compute="_compute_approved_annual_total", store=True, readonly=False,
    )
    display_approved_annual_total = fields.Float(
        string="Approved Target",
        compute="_compute_display_approved_annual_total",
        compute_sudo=False,
    )
    approved_quantity = fields.Integer(
        string="Approved Quantity / Items",
        compute="_compute_approved_quantity", store=True, readonly=False,
    )
    fa_approved_total_cost = fields.Monetary(
        string="Approved Total Cost",
        compute="_compute_fa_approved_total_cost", store=True, readonly=False,
        currency_field="currency_id",
    )

    variance_amount = fields.Float(
        string="Target Variance (+/-)",
        compute="_compute_target_variance", store=True,
    )
    variance_percentage = fields.Float(
        string="Target Variance (%)",
        compute="_compute_target_variance", store=True, digits=(16, 2),
    )

    request_number = fields.Char(
        related="plan_id.request_number", store=True, readonly=True, string="Request No.",
    )

    @api.depends(
        "position_type_id", "position_type", "job_id", "new_job_title",
        "deposit_type_id", "base_type",
        "fx_source_type",
        "channel_id",
        "expense_account_id",
        "category_id", "item_description",
    )
    def _compute_line_type(self):
        for line in self:
            # Preserve existing line_type if already set and valid
            if line.line_type in ("manpower", "fx", "digital_banking", "general_expense", "fixed_asset", "customer_base", "deposit"):
                continue

            if line.position_type_id or line.position_type or line.job_id or line.new_job_title:
                line.line_type = "manpower"
            elif line.fx_source_type:
                line.line_type = "fx"
            elif line.channel_id:
                line.line_type = "digital_banking"
            elif line.expense_account_id:
                line.line_type = "general_expense"
            elif line.category_id or line.item_description:
                line.line_type = "fixed_asset"
            elif line.deposit_type_id and line.base_type:
                line.line_type = "customer_base"
            elif line.deposit_type_id:
                line.line_type = "deposit"
            else:
                ctx_type = self.env.context.get("default_line_type")
                if ctx_type:
                    line.line_type = ctx_type
                elif line.plan_id and line.plan_id.category:
                    line.line_type = line.plan_id.category
                else:
                    line.line_type = "deposit"


    def _is_same_line(self, other_line):
        """Check if self and other_line represent the same logical record (handling in-memory NewId vs persisted IDs)."""
        if not other_line:
            return False
        if self == other_line:
            return True
        self_orig = getattr(self, "_origin", self) or self
        other_orig = getattr(other_line, "_origin", other_line) or other_line
        if self_orig == other_orig or self == other_orig or self_orig == other_line:
            return True
        id_self = self_orig.id if isinstance(self_orig.id, int) else (self.id if isinstance(self.id, int) else False)
        id_other = other_orig.id if isinstance(other_orig.id, int) else (other_line.id if isinstance(other_line.id, int) else False)
        if id_self and id_other and id_self == id_other:
            return True
        return False

    # -------------------------------------------------------------------------
    # DYNAMIC DROPDOWN DOMAINS & EXCLUSION (Hide already-planned items)
    # -------------------------------------------------------------------------

    # 1. Deposit Mobilization & Customer Base
    @api.depends(
        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
        "plan_id.deposit_line_ids.deposit_type_id",
        "plan_id.customer_base_line_ids.deposit_type_id",
    )
    def _compute_deposit_type_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.deposit_type_ids:
                domain.append(("id", "in", config.deposit_type_ids.ids))
            else:
                domain.append(("active", "=", True))

            if plan:
                if line.line_type == "deposit":
                    other_lines = plan.deposit_line_ids.filtered(
                        lambda l: not line._is_same_line(l) and l.deposit_type_id
                    )
                    used_ids = other_lines.mapped("deposit_type_id.id")
                    if used_ids:
                        domain.append(("id", "not in", used_ids))
                elif line.line_type == "customer_base":
                    other_lines = plan.customer_base_line_ids.filtered(
                        lambda l: not line._is_same_line(l) and l.deposit_type_id
                    )
                    used_ids = other_lines.mapped("deposit_type_id.id")
                    if used_ids:
                        domain.append(("id", "not in", used_ids))

            line.deposit_type_domain = json.dumps(domain)

    @api.onchange("deposit_type_id", "line_type", "plan_id")
    def _onchange_deposit_type_update_domain(self):
        Config = self.env["pbms.planning.config"]
        plan = self.plan_id
        config = False
        if plan and plan.org_unit_id:
            config = Config.get_config_for_unit(plan.org_unit_id)
        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []
        if config and config.deposit_type_ids:
            domain.append(("id", "in", config.deposit_type_ids.ids))
        else:
            domain.append(("active", "=", True))

        if plan:
            if self.line_type == "deposit":
                other_lines = plan.deposit_line_ids.filtered(
                    lambda l: not self._is_same_line(l) and l.deposit_type_id
                )
                used_ids = other_lines.mapped("deposit_type_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))
            elif self.line_type == "customer_base":
                other_lines = plan.customer_base_line_ids.filtered(
                    lambda l: not self._is_same_line(l) and l.deposit_type_id
                )
                used_ids = other_lines.mapped("deposit_type_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

        return {"domain": {"deposit_type_id": domain}}

    # 2. Digital Banking Channels
    @api.depends(
        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
        "plan_id.digital_banking_line_ids.channel_id",
    )
    def _compute_channel_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.digital_channel_ids:
                domain.append(("id", "in", config.digital_channel_ids.ids))
            else:
                domain.append(("active", "=", True))

            if plan and line.line_type == "digital_banking":
                other_lines = plan.digital_banking_line_ids.filtered(
                    lambda l: not line._is_same_line(l) and l.channel_id
                )
                used_ids = other_lines.mapped("channel_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

            line.channel_domain = json.dumps(domain)

    @api.onchange("channel_id", "line_type", "plan_id")
    def _onchange_channel_update_domain(self):
        Config = self.env["pbms.planning.config"]
        plan = self.plan_id
        config = False
        if plan and plan.org_unit_id:
            config = Config.get_config_for_unit(plan.org_unit_id)
        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []
        if config and config.digital_channel_ids:
            domain.append(("id", "in", config.digital_channel_ids.ids))
        else:
            domain.append(("active", "=", True))

        if plan and self.line_type == "digital_banking":
            other_lines = plan.digital_banking_line_ids.filtered(
                lambda l: not self._is_same_line(l) and l.channel_id
            )
            used_ids = other_lines.mapped("channel_id.id")
            if used_ids:
                domain.append(("id", "not in", used_ids))

        return {"domain": {"channel_id": domain}}

    # 3. FX Source Types
    @api.depends(
        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
        "plan_id.fx_line_ids.fx_source_type",
    )
    def _compute_fx_source_type_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.fx_source_type_ids:
                domain.append(("id", "in", config.fx_source_type_ids.ids))
            else:
                domain.append(("active", "=", True))

            if plan and line.line_type == "fx":
                other_lines = plan.fx_line_ids.filtered(
                    lambda l: not line._is_same_line(l) and l.fx_source_type
                )
                used_ids = other_lines.mapped("fx_source_type.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

            line.fx_source_type_domain = json.dumps(domain)

    @api.onchange("fx_source_type", "line_type", "plan_id")
    def _onchange_fx_source_type_update_domain(self):
        Config = self.env["pbms.planning.config"]
        plan = self.plan_id
        config = False
        if plan and plan.org_unit_id:
            config = Config.get_config_for_unit(plan.org_unit_id)
        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []
        if config and config.fx_source_type_ids:
            domain.append(("id", "in", config.fx_source_type_ids.ids))
        else:
            domain.append(("active", "=", True))

        if plan and self.line_type == "fx":
            other_lines = plan.fx_line_ids.filtered(
                lambda l: not self._is_same_line(l) and l.fx_source_type
            )
            used_ids = other_lines.mapped("fx_source_type.id")
            if used_ids:
                domain.append(("id", "not in", used_ids))

        return {"domain": {"fx_source_type": domain}}

    # 4. Expense Accounts
    @api.depends(
        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
        "plan_id.expense_line_ids.expense_account_id",
    )
    def _compute_expense_account_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.expense_account_ids:
                domain.append(("id", "in", config.expense_account_ids.ids))
            else:
                domain.append(("active", "=", True))

            if plan and line.line_type == "general_expense":
                other_lines = plan.expense_line_ids.filtered(
                    lambda l: not line._is_same_line(l) and l.expense_account_id
                )
                used_ids = other_lines.mapped("expense_account_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

            line.expense_account_domain = json.dumps(domain)

    @api.onchange("expense_account_id", "line_type", "plan_id")
    def _onchange_expense_account_update_domain(self):
        Config = self.env["pbms.planning.config"]
        plan = self.plan_id
        config = False
        if plan and plan.org_unit_id:
            config = Config.get_config_for_unit(plan.org_unit_id)
        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []
        if config and config.expense_account_ids:
            domain.append(("id", "in", config.expense_account_ids.ids))
        else:
            domain.append(("active", "=", True))

        if plan and self.line_type == "general_expense":
            other_lines = plan.expense_line_ids.filtered(
                lambda l: not self._is_same_line(l) and l.expense_account_id
            )
            used_ids = other_lines.mapped("expense_account_id.id")
            if used_ids:
                domain.append(("id", "not in", used_ids))

        return {"domain": {"expense_account_id": domain}}

    # 5. Fixed Asset Categories
    @api.depends(
        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",
        "plan_id.fixed_asset_line_ids.category_id",
    )
    def _compute_fa_category_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.fixed_asset_category_ids:
                domain.append(("id", "in", config.fixed_asset_category_ids.ids))
            else:
                domain.append(("active", "=", True))

            if plan and line.line_type == "fixed_asset":
                other_lines = plan.fixed_asset_line_ids.filtered(
                    lambda l: not line._is_same_line(l) and l.category_id
                )
                used_ids = other_lines.mapped("category_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

            line.fa_category_domain = json.dumps(domain)

    @api.onchange("category_id", "nature", "line_type", "plan_id")
    def _onchange_fa_category_update_domain(self):
        Config = self.env["pbms.planning.config"]
        plan = self.plan_id
        config = False
        if plan and plan.org_unit_id:
            config = Config.get_config_for_unit(plan.org_unit_id)
        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []
        if config and config.fixed_asset_category_ids:
            domain.append(("id", "in", config.fixed_asset_category_ids.ids))
        else:
            domain.append(("active", "=", True))

        if plan and self.line_type == "fixed_asset":
            other_lines = plan.fixed_asset_line_ids.filtered(
                lambda l: not self._is_same_line(l) and l.category_id
            )
            used_ids = other_lines.mapped("category_id.id")
            if used_ids:
                domain.append(("id", "not in", used_ids))

        return {"domain": {"category_id": domain}}

    # 6. Justification Categories
    @api.depends("plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type")
    def _compute_justification_category_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for line in self:
            domain = []
            plan = line.plan_id
            config = False
            if plan and plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            if config and config.justification_category_ids:
                domain.append(("id", "in", config.justification_category_ids.ids))
            else:
                domain.append(("active", "=", True))
            line.justification_category_domain = json.dumps(domain)

    # ---- Manpower (Configurable Request / Position Type) ----
    position_type_id = fields.Many2one(
        "pbms.position.type",
        string="Request Type",
        index=True,
        default=lambda self: self._default_position_type_id(),
    )
    is_new_position = fields.Boolean(
        related="position_type_id.is_new_position",
        string="Is New Position",
        readonly=True,
    )
    position_type = fields.Selection(
        [
            ("new", "New Position"),
            ("additional", "Additional Position"),
            ("additional position", "Additional Position"),
        ],
        string="Position Type Code",
        compute="_compute_position_type_code",
        inverse="_inverse_position_type_code",
        store=True,
    )

    @api.model
    def _default_position_type_id(self):
        return self.env["pbms.position.type"].search([("code", "=", "new")], limit=1)

    @api.depends("position_type_id", "position_type_id.code", "position_type_id.is_new_position")
    def _compute_position_type_code(self):
        for line in self:
            if line.position_type_id:
                if line.position_type_id.is_new_position or line.position_type_id.code in ("new", "new_position"):
                    line.position_type = "new"
                else:
                    line.position_type = "additional"
            elif not line.position_type:
                line.position_type = "new"

    def _inverse_position_type_code(self):
        for line in self:
            if line.position_type:
                is_new = (line.position_type == "new")
                if line.position_type_id and (line.position_type_id.is_new_position == is_new):
                    continue
                p_type = self.env["pbms.position.type"].search([
                    ("is_new_position", "=", is_new)
                ], limit=1)
                if not p_type:
                    p_type = self.env["pbms.position.type"].search([
                        ("code", "=", "new" if is_new else "additional")
                    ], limit=1)
                if p_type:
                    line.position_type_id = p_type

    @api.onchange("position_type_id")
    def _onchange_position_type_id_sync(self):
        if self.position_type_id:
            if self.position_type_id.is_new_position or self.position_type_id.code in ("new", "new_position"):
                self.position_type = "new"
            else:
                self.position_type = "additional"
            if self.position_type_id.is_new_position or self.position_type == "new":
                self.job_id = False
                self.job_grade_id = False
                self.base_salary = 0.0
            else:
                self.new_job_title = False
                self.new_job_grade = False
                self.new_job_grade_id = False
    employment_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("contract", "Contract"),
            ("temporary", "Temporary"),
        ],
        string="Employment Type",
        default="permanent",
    )
    job_id = fields.Many2one("hr.job", string="Job Position / Title", index=True)
    job_id_domain = fields.Char(compute="_compute_job_id_domain", store=False)
    job_grade_id = fields.Many2one("employee.grade", string="Job Grade", index=True)
    employee_category_id = fields.Many2one("employee.category", string="Employee Category", index=True)
    new_job_title = fields.Char(string="New Job Title")
    new_job_grade = fields.Char(string="New Job Grade", compute="_compute_new_job_grade", store=True, readonly=False)
    new_job_grade_id = fields.Many2one("employee.grade", string="New Job Grade")
    new_employee_category_id = fields.Many2one("employee.category", string="New Employee Category")
    date_needed = fields.Date(string="Date Needed")
    reason = fields.Text(string="Reason for the Proposed Position")

    justification_category_id = fields.Many2one("pbms.justification.category", string="Business Justification", index=True)
    requires_remarks = fields.Boolean(related="justification_category_id.requires_remarks", readonly=True)
    other_justification = fields.Char(string="Justification Remarks")
    business_justification = fields.Text(string="Detailed Business Justification")

    existing_establishment = fields.Integer(compute="_compute_workforce_establishment", store=True, readonly=True, string="Approved (Baseline)")
    active_staff_count = fields.Integer(compute="_compute_workforce_establishment", store=True, readonly=True, string="Active Staff")
    vacant_count = fields.Integer(compute="_compute_workforce_establishment", store=True, readonly=True, string="Vacancies")
    total_establishment = fields.Integer(compute="_compute_total_establishment", store=True, readonly=True, string="Total Establishment")

    hc_m01 = fields.Integer(string="Jul", default=0)
    hc_m02 = fields.Integer(string="Aug", default=0)
    hc_m03 = fields.Integer(string="Sep", default=0)
    hc_m04 = fields.Integer(string="Oct", default=0)
    hc_m05 = fields.Integer(string="Nov", default=0)
    hc_m06 = fields.Integer(string="Dec", default=0)
    hc_m07 = fields.Integer(string="Jan", default=0)
    hc_m08 = fields.Integer(string="Feb", default=0)
    hc_m09 = fields.Integer(string="Mar", default=0)
    hc_m10 = fields.Integer(string="Apr", default=0)
    hc_m11 = fields.Integer(string="May", default=0)
    hc_m12 = fields.Integer(string="Jun", default=0)

    q1 = fields.Integer(string="Q1 (Jul-Sep)", compute="_compute_manpower_quarters", store=True, readonly=False)
    q2 = fields.Integer(string="Q2 (Oct-Dec)", compute="_compute_manpower_quarters", store=True, readonly=False)
    q3 = fields.Integer(string="Q3 (Jan-Mar)", compute="_compute_manpower_quarters", store=True, readonly=False)
    q4 = fields.Integer(string="Q4 (Apr-Jun)", compute="_compute_manpower_quarters", store=True, readonly=False)

    base_salary = fields.Monetary(compute="_compute_base_salary", store=True, readonly=False, currency_field="currency_id")
    pension_rate = fields.Float(string="Employer Pension (%)", default=11.0)
    monthly_pension = fields.Monetary(compute="_compute_compensation_breakdown", store=True, currency_field="currency_id")
    annual_pension = fields.Monetary(compute="_compute_compensation_breakdown", store=True, currency_field="currency_id")
    monthly_total_compensation = fields.Monetary(compute="_compute_compensation_breakdown", store=True, currency_field="currency_id")
    unit_cost = fields.Monetary(compute="_compute_compensation_breakdown", store=True, currency_field="currency_id")
    q1_cost = fields.Monetary(compute="_compute_quarter_costs", store=True, currency_field="currency_id")
    q2_cost = fields.Monetary(compute="_compute_quarter_costs", store=True, currency_field="currency_id")
    q3_cost = fields.Monetary(compute="_compute_quarter_costs", store=True, currency_field="currency_id")
    q4_cost = fields.Monetary(compute="_compute_quarter_costs", store=True, currency_field="currency_id")
    annual_total_cost = fields.Monetary(compute="_compute_annual_total_cost", store=True, currency_field="currency_id")

    # ---- Manpower Sourcing & Fulfillment Strategy ----
    fulfillment_promotion = fields.Integer(string="Promotion", default=0)
    fulfillment_transfer = fields.Integer(string="Transfer", default=0)
    fulfillment_lateral = fields.Integer(string="Lateral", default=0)
    fulfillment_external = fields.Integer(string="External Vacancy", default=0)
    fulfillment_total = fields.Integer(
        string="Total Sourced",
        compute="_compute_manpower_fulfillment",
        store=True,
    )
    fulfillment_balance = fields.Integer(
        string="Sourcing Balance",
        compute="_compute_manpower_fulfillment",
        store=True,
        help="Difference between Committee Approved Headcount and Total Sourced. Must be zero.",
    )

    @api.depends("fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external", "approved_annual_total", "annual_total")
    def _compute_manpower_fulfillment(self):
        for line in self:
            if line.line_type == "manpower":
                tot = (line.fulfillment_promotion or 0) + (line.fulfillment_transfer or 0) + (line.fulfillment_lateral or 0) + (line.fulfillment_external or 0)
                line.fulfillment_total = tot
                appr = int(line.approved_annual_total or line.annual_total or 0)
                line.fulfillment_balance = appr - tot
            else:
                line.fulfillment_total = 0
                line.fulfillment_balance = 0

    def _auto_balance_manpower_sourcing(self):
        """Auto-adjust sourcing strategy when Budget Hiring Committee or CEO adds or minuses headcount:
        - If headcount increases (+): add diff directly to External Vacancy (fulfillment_external).
        - If headcount decreases (-): first subtract from External Vacancy (fulfillment_external).
          When External Vacancy reaches 0 (or is already 0), randomly subtract from whichever
          remaining sourcing field(s) (promotion, transfer, lateral) have the highest value.
        This guarantees requested and sourced are equal at all times without manual arithmetic errors.
        """
        import random
        for line in self:
            if line.line_type != "manpower":
                continue
            # Calculate target headcount from monthly fields or annual_total
            target = int(round(
                (line.m01 or 0) + (line.m02 or 0) + (line.m03 or 0) +
                (line.m04 or 0) + (line.m05 or 0) + (line.m06 or 0) +
                (line.m07 or 0) + (line.m08 or 0) + (line.m09 or 0) +
                (line.m10 or 0) + (line.m11 or 0) + (line.m12 or 0)
            ))
            if target <= 0 and line.annual_total:
                target = int(round(line.annual_total))
            if target < 0:
                target = 0

            ext = int(line.fulfillment_external or 0)
            prom = int(line.fulfillment_promotion or 0)
            trans = int(line.fulfillment_transfer or 0)
            lat = int(line.fulfillment_lateral or 0)
            current_sourced = ext + prom + trans + lat

            diff = target - current_sourced
            if diff == 0:
                continue

            if diff > 0:
                # Add: firstly to external vacancy
                ext += diff
            else:
                # Minus: firstly from external vacancy, then when external is 0 randomly from higher value
                rem = abs(diff)
                deduct_ext = min(ext, rem)
                ext -= deduct_ext
                rem -= deduct_ext

                while rem > 0:
                    sources = [
                        ("fulfillment_promotion", prom),
                        ("fulfillment_transfer", trans),
                        ("fulfillment_lateral", lat),
                    ]
                    pos_sources = [s for s in sources if s[1] > 0]
                    if not pos_sources:
                        break
                    max_val = max(s[1] for s in pos_sources)
                    highest_candidates = [s[0] for s in pos_sources if s[1] == max_val]
                    chosen_field = random.choice(highest_candidates)

                    if chosen_field == "fulfillment_promotion":
                        prom -= 1
                    elif chosen_field == "fulfillment_transfer":
                        trans -= 1
                    elif chosen_field == "fulfillment_lateral":
                        lat -= 1
                    rem -= 1

            update_vals = {
                "fulfillment_external": ext,
                "fulfillment_promotion": prom,
                "fulfillment_transfer": trans,
                "fulfillment_lateral": lat,
            }
            if not isinstance(line.id, int):
                for k, v in update_vals.items():
                    setattr(line, k, v)
                line.fulfillment_total = prom + trans + lat + ext
                appr = int(line.approved_annual_total or line.annual_total or 0)
                line.fulfillment_balance = appr - line.fulfillment_total
            else:
                line.with_context(bypass_plan_lock=True, auto_balancing_sourcing=True).sudo().write(update_vals)


    # ---- Fixed Asset ----
    nature = fields.Selection([("new", "New"), ("replacement", "Replacement")], string="Nature", default="new")
    category_id = fields.Many2one("pbms.fixed.asset.category", string="Asset Category", index=True)
    item_description = fields.Char(string="Item Description")
    purpose = fields.Many2one(
        "hr.job",
        string="Position / Purpose of Item",
        index=True,
        help="Select the eligible job position for this operating unit that requires this item.",
    )
    estimated_unit_price = fields.Monetary(currency_field="currency_id")
    fa_q1 = fields.Integer(string="Q1 (Jul-Sep)", default=0)
    fa_q2 = fields.Integer(string="Q2 (Oct-Dec)", default=0)
    fa_q3 = fields.Integer(string="Q3 (Jan-Mar)", default=0)
    fa_q4 = fields.Integer(string="Q4 (Apr-Jun)", default=0)
    fa_q1_cost = fields.Monetary(compute="_compute_fa_quarter_costs", store=True, currency_field="currency_id")
    fa_q2_cost = fields.Monetary(compute="_compute_fa_quarter_costs", store=True, currency_field="currency_id")
    fa_q3_cost = fields.Monetary(compute="_compute_fa_quarter_costs", store=True, currency_field="currency_id")
    fa_q4_cost = fields.Monetary(compute="_compute_fa_quarter_costs", store=True, currency_field="currency_id")
    fa_annual_total_cost = fields.Monetary(compute="_compute_fa_annual_total_cost", store=True, currency_field="currency_id")

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_currency_id",
        store=True,
        readonly=False,
        help="Currency for this requirement line.",
    )
    plan_org_unit_id = fields.Many2one("operating.unit", related="plan_id.org_unit_id", store=True)

    @api.depends("line_type", "plan_id.org_unit_id", "plan_id.currency_id")
    def _compute_currency_id(self):
        Config = self.env["pbms.planning.config"]
        for line in self:
            if line.line_type == "fx":
                line.currency_id = Config.get_category_currency("fx", org_unit=line.plan_id.org_unit_id if line.plan_id else False)
            else:
                line.currency_id = line.plan_id.currency_id if line.plan_id and line.plan_id.currency_id else self.env.company.currency_id
    # ------------------------------------------------------------------
    # AUTOMATED VALIDATION RULES (per line_type only)
    # ------------------------------------------------------------------

    @api.constrains("fx_source_type", "line_type")
    def _check_fx_fields(self):
        for line in self:
            if line.line_type != "fx":
                continue
            if not line.fx_source_type:
                raise ValidationError(_("FX Source is required for FX Mobilization lines."))

    @api.constrains("deposit_type_id", "line_type")
    def _check_deposit_fields(self):
        for line in self:
            if line.line_type != "deposit":
                continue
            if not line.deposit_type_id:
                raise ValidationError(_("Deposit Type is required for Deposit Mobilization lines."))

    @api.constrains("deposit_type_id", "base_type", "line_type")
    def _check_customer_base_fields(self):
        for line in self:
            if line.line_type != "customer_base":
                continue
            if not line.deposit_type_id:
                raise ValidationError(_("Product / Account Type is required for Customer Base lines."))
            if not line.base_type:
                raise ValidationError(_("Base Type is required for Customer Base lines."))

    @api.constrains("channel_id", "line_type")
    def _check_digital_banking_fields(self):
        for line in self:
            if line.line_type != "digital_banking":
                continue
            if not line.channel_id:
                raise ValidationError(_("Digital Channel is required for Digital Banking lines."))

    @api.constrains("expense_account_id", "line_type")
    def _check_general_expense_fields(self):
        for line in self:
            if line.line_type != "general_expense":
                continue
            if not line.expense_account_id:
                raise ValidationError(_("Expense Account is required for General Expense lines."))

    @api.constrains(
        "position_type_id", "position_type", "job_id", "new_job_title", "new_job_grade", "job_grade_id",
        "new_job_grade_id", "new_employee_category_id", "line_type",
    )
    def _check_manpower_fields(self):
        for line in self:
            if line.line_type != "manpower":
                continue
            if not line.position_type_id and not line.position_type:
                raise ValidationError(_("Request Type (Position Type) is required for each requested position in Manpower."))
            p_code = line.position_type_id.code if line.position_type_id else line.position_type
            if p_code != "new":
                if not line.job_id:
                    p_name = line.position_type_id.name if line.position_type_id else p_code
                    raise ValidationError(_("Job Position is required for '%s' positions.") % p_name)
                if not line.job_grade_id and line.job_id:
                    # Auto-fallback from hr.job if available
                    job = line.job_id
                    g = getattr(job, "job_grade_id", False) or getattr(job, "grade_id", False) or getattr(job, "job_grade", False) or getattr(job, "grade", False)
                    if g:
                        line.job_grade_id = g
                if not line.job_grade_id and line.plan_id and line.plan_id.org_unit_type not in ("district_office", "head_office"):
                    p_name = line.position_type_id.name if line.position_type_id else p_code
                    raise ValidationError(_("Job Grade is required for '%s' positions.") % p_name)
            elif p_code == "new":
                if not line.new_job_title:
                    raise ValidationError(_("New Job Title is required for New positions."))
                if not line.new_job_grade and (line.new_job_grade_id or line.job_grade_id):
                    g_rec = line.new_job_grade_id or line.job_grade_id
                    line.new_job_grade = (
                        getattr(g_rec, "grade_code", False)
                        or getattr(g_rec, "grade_name", False)
                        or getattr(g_rec, "name", False)
                    )
                if not (line.new_job_grade or line.new_job_grade_id or line.job_grade_id):
                    raise ValidationError(_("New Job Grade is required for New positions."))


    @api.constrains("hc_m01", "hc_m02", "hc_m03", "hc_m04", "hc_m05", "hc_m06",
                     "hc_m07", "hc_m08", "hc_m09", "hc_m10", "hc_m11", "hc_m12",
                     "m01", "m02", "m03", "m04", "m05", "m06",
                     "m07", "m08", "m09", "m10", "m11", "m12",
                     "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
                     "q1", "q2", "q3", "q4", "quantity", "line_type")
    def _check_manpower_numbers(self):
        for line in self:
            if line.line_type != "manpower":
                continue
            for m_name in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"):
                if (getattr(line, m_name) or 0) < 0:
                    raise ValidationError(_("Workforce requests cannot be negative."))
            for m_name in HC_MONTH_FIELDS:
                if (getattr(line, m_name) or 0) < 0:
                    raise ValidationError(_("Workforce requests cannot be negative."))
            for q_name in ("q1", "q2", "q3", "q4"):
                if (getattr(line, q_name) or 0) < 0:
                    raise ValidationError(_("Additional requests for %s must be positive integers.") % q_name.upper())

            total_m = sum(getattr(line, m) or 0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
            total_hc = sum(getattr(line, m) or 0 for m in HC_MONTH_FIELDS)
            total_quarterly = (line.quarter1_total or 0) + (line.quarter2_total or 0) + (line.quarter3_total or 0) + (line.quarter4_total or 0) + (line.q1 or 0) + (line.q2 or 0) + (line.q3 or 0) + (line.q4 or 0)

            if total_m <= 0 and total_hc <= 0 and total_quarterly <= 0 and (line.quantity or 0) <= 0:
                raise ValidationError(_("Total additional workforce request must be greater than zero."))

    @api.constrains("justification_category_id", "other_justification", "line_type")
    def _check_manpower_justification(self):
        for line in self:
            if line.line_type != "manpower":
                continue
            if (
                line.justification_category_id
                and line.justification_category_id.requires_remarks
                and not line.other_justification
            ):
                raise ValidationError(_(
                    "Please provide additional remarks for justification category '%s'."
                ) % line.justification_category_id.name)

    @api.constrains("job_id", "new_job_title", "position_type_id", "position_type", "line_type", "plan_id")
    def _check_duplicate_position_in_budget_year(self):
        for line in self:
            if line.line_type != "manpower" or not line.plan_id or not line.plan_id.cycle_id or not line.plan_id.org_unit_id:
                continue

            plan = line.plan_id
            plan_orig = getattr(plan, "_origin", plan) or plan
            plan_real_id = plan_orig.id if isinstance(plan_orig.id, int) else (plan.id if isinstance(plan.id, int) else False)

            line_orig = getattr(line, "_origin", line) or line
            line_real_id = line_orig.id if isinstance(line_orig.id, int) else (line.id if isinstance(line.id, int) else False)

            p_code = line.position_type_id.code if line.position_type_id else line.position_type
            p_type = line.position_type_id
            p_name = p_type.name if p_type else (p_code or _("Position"))

            # 1. In-memory check for duplicates within the same plan
            same_plan_lines = [
                l for l in plan.line_ids
                if l.line_type == "manpower" and not line._is_same_line(l)
            ]
            if p_code != "new" and line.job_id:
                dups_in_plan = [
                    l for l in same_plan_lines
                    if (l.position_type_id == p_type if (p_type and l.position_type_id) else (l.position_type or (l.position_type_id.code if l.position_type_id else False)) == p_code)
                    and l.job_id == line.job_id
                ]
                if dups_in_plan:
                    raise ValidationError(_(
                        "Duplicate position request: Job Position '%(job)s' with Request Type '%(ptype)s' is already included in this manpower plan.",
                        job=line.job_id.name,
                        ptype=p_name,
                    ))

                # 2. Database check across other active, non-rejected plans
                domain = [
                    ("line_type", "=", "manpower"),
                    ("plan_id.cycle_id", "=", plan.cycle_id.id),
                    ("plan_id.org_unit_id", "=", plan.org_unit_id.id),
                    ("plan_id.active", "=", True),
                    ("plan_id.state", "!=", "rejected"),
                    ("job_id", "=", line.job_id.id),
                ]
                if line_real_id:
                    domain.append(("id", "!=", line_real_id))
                if plan_real_id:
                    domain.append(("plan_id", "!=", plan_real_id))

                if p_type:
                    domain.append(("position_type_id", "=", p_type.id))
                elif p_code:
                    domain.append(("position_type", "=", p_code))

                other_matches = self.search(domain)
                # Filter out lines belonging to plans that are not independent manpower plans
                real_dups = other_matches.filtered(
                    lambda ol: ol.plan_id and ol.plan_id.active and ol.plan_id.state != "rejected" and ol.plan_id.category == "manpower" and (ol.plan_id.id != plan_real_id if plan_real_id else ol.plan_id != plan)
                )
                if real_dups and plan.category == "manpower":
                    raise ValidationError(_(
                        "A request for Job Position '%(job)s' with Request Type '%(ptype)s' already exists for %(unit)s in budget year %(cycle)s.",
                        job=line.job_id.name,
                        ptype=p_name,
                        unit=plan.org_unit_id.display_name,
                        cycle=plan.cycle_id.name,
                    ))

            elif p_code == "new" and line.new_job_title:
                norm_title = line.new_job_title.strip().lower()
                dups_in_plan = [
                    l for l in same_plan_lines
                    if (l.position_type_id == p_type if (p_type and l.position_type_id) else (l.position_type or (l.position_type_id.code if l.position_type_id else False)) == "new")
                    and l.new_job_title and l.new_job_title.strip().lower() == norm_title
                ]
                if dups_in_plan:
                    raise ValidationError(_(
                        "Duplicate position request: New Position '%(title)s' with Request Type '%(ptype)s' is already included in this manpower plan.",
                        title=line.new_job_title,
                        ptype=p_name,
                    ))

                domain = [
                    ("line_type", "=", "manpower"),
                    ("plan_id.cycle_id", "=", plan.cycle_id.id),
                    ("plan_id.org_unit_id", "=", plan.org_unit_id.id),
                    ("plan_id.active", "=", True),
                    ("plan_id.state", "!=", "rejected"),
                    ("new_job_title", "=ilike", line.new_job_title.strip()),
                ]
                if line_real_id:
                    domain.append(("id", "!=", line_real_id))
                if plan_real_id:
                    domain.append(("plan_id", "!=", plan_real_id))

                if p_type:
                    domain.append(("position_type_id", "=", p_type.id))
                elif p_code:
                    domain.append(("position_type", "=", p_code))

                other_matches = self.search(domain)
                real_dups = other_matches.filtered(
                    lambda ol: ol.plan_id and ol.plan_id.active and ol.plan_id.state != "rejected" and ol.plan_id.category == "manpower" and (ol.plan_id.id != plan_real_id if plan_real_id else ol.plan_id != plan)
                )
                if real_dups and plan.category == "manpower":
                    raise ValidationError(_(
                        "A request for New Position '%(title)s' with Request Type '%(ptype)s' already exists for %(unit)s in budget year %(cycle)s.",
                        title=line.new_job_title,
                        ptype=p_name,
                        unit=plan.org_unit_id.display_name,
                        cycle=plan.cycle_id.name,
                    ))




    @api.constrains("category_id", "item_description", "line_type")
    def _check_fixed_asset_fields(self):
        for line in self:
            if line.line_type != "fixed_asset":
                continue
            if not line.category_id:
                raise ValidationError(_("Asset Category is required for Fixed Asset lines."))
            if not line.item_description:
                raise ValidationError(_("Item Description is required for Fixed Asset lines."))

    @api.constrains("fa_q1", "fa_q2", "fa_q3", "fa_q4", "line_type")
    def _check_fixed_asset_quantities(self):
        for line in self:
            if line.line_type != "fixed_asset":
                continue
            total = (line.fa_q1 or 0) + (line.fa_q2 or 0) + (line.fa_q3 or 0) + (line.fa_q4 or 0)
            if total <= 0:
                raise ValidationError(_("At least one quarter must have a quantity greater than zero for Fixed Asset lines."))

    @api.depends("position_type_id", "position_type", "plan_id", "plan_id.org_unit_id", "plan_id.manpower_line_ids.job_id", "plan_id.manpower_line_ids.position_type_id")
    def _compute_job_id_domain(self):
        import json
        for line in self:
            domain = [("active", "=", True)]
            if line.line_type == "manpower" and line.plan_id:
                plan = line.plan_id
                unit_job_ids = set()
                if plan.org_unit_id:
                    if "operating.unit.job.position" in self.env:
                        ou_positions = self.env["operating.unit.job.position"].search([
                            ("operating_unit_id", "=", plan.org_unit_id.id),
                            ("active", "=", True),
                        ])
                        unit_job_ids.update(ou_positions.mapped("job_position_id.id"))
                    if "hr.employee" in self.env:
                        emp_domain = [
                            ("active", "=", True),
                            "|",
                            ("operating_unit_ids", "in", [plan.org_unit_id.id]),
                            ("default_operating_unit_id", "=", plan.org_unit_id.id),
                        ]
                        employees = self.env["hr.employee"].search(emp_domain)
                        for emp in employees:
                            j = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
                            if j:
                                unit_job_ids.add(j.id)

                if unit_job_ids:
                    domain.append(("id", "in", list(unit_job_ids)))

                other_lines = plan.manpower_line_ids.filtered(
                    lambda l: not line._is_same_line(l) and l.job_id and (
                        (l.position_type_id and line.position_type_id and l.position_type_id == line.position_type_id)
                        or (l.position_type == line.position_type)
                    )
                )
                used_ids = other_lines.mapped("job_id.id")
                if used_ids:
                    domain.append(("id", "not in", used_ids))

            line.job_id_domain = json.dumps(domain)

    @api.onchange("position_type_id", "position_type", "plan_id")
    def _onchange_position_type_update_job_domain(self):
        domain = [("active", "=", True)]
        if self.line_type == "manpower" and self.plan_id:
            plan = self.plan_id
            unit_job_ids = set()
            if plan.org_unit_id:
                if "operating.unit.job.position" in self.env:
                    ou_positions = self.env["operating.unit.job.position"].search([
                        ("operating_unit_id", "=", plan.org_unit_id.id),
                        ("active", "=", True),
                    ])
                    unit_job_ids.update(ou_positions.mapped("job_position_id.id"))
                if "hr.employee" in self.env:
                    emp_domain = [
                        ("active", "=", True),
                        "|",
                        ("operating_unit_ids", "in", [plan.org_unit_id.id]),
                        ("default_operating_unit_id", "=", plan.org_unit_id.id),
                    ]
                    employees = self.env["hr.employee"].search(emp_domain)
                    for emp in employees:
                        j = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
                        if j:
                            unit_job_ids.add(j.id)

            if unit_job_ids:
                domain.append(("id", "in", list(unit_job_ids)))

            other_lines = self.plan_id.manpower_line_ids.filtered(
                lambda l: not self._is_same_line(l) and l.job_id and (
                    (l.position_type_id and self.position_type_id and l.position_type_id == self.position_type_id)
                    or (l.position_type == self.position_type)
                )
            )
            used_ids = other_lines.mapped("job_id.id")
            if used_ids:
                domain.append(("id", "not in", used_ids))

        return {"domain": {"job_id": domain}}

    @api.onchange("job_id", "position_type_id", "position_type")
    def _onchange_job_id_populate_grade(self):
        for line in self:
            p_code = line.position_type_id.code if line.position_type_id else line.position_type
            if p_code != "new" and line.job_id:
                grade = False
                for g_attr in ("grade", "grade_id", "job_grade_id", "job_grade"):
                    if hasattr(line.job_id, g_attr) and getattr(line.job_id, g_attr):
                        grade = getattr(line.job_id, g_attr)
                        break

                if not grade:
                    Employee = self.env["hr.employee"] if "hr.employee" in self.env else False
                    if Employee:
                        domain = [("active", "=", True)]
                        if "job_id" in Employee._fields:
                            domain.append(("job_id", "=", line.job_id.id))
                        elif "job_position" in Employee._fields:
                            domain.append(("job_position", "=", line.job_id.id))
                        emp = Employee.search(domain, limit=1)
                        if emp:
                            for g_attr in ("grade", "job_grade", "grade_id", "job_grade_id"):
                                if hasattr(emp, g_attr) and getattr(emp, g_attr):
                                    grade = getattr(emp, g_attr)
                                    break

                if not grade:
                    Contract = (
                        (self.env["hr.version"] if "hr.version" in self.env else False)
                        or (self.env["hr.contract"] if "hr.contract" in self.env else False)
                    )
                    if Contract and "job_id" in Contract._fields:
                        cnt = Contract.search([("job_id", "=", line.job_id.id)], limit=1)
                        if cnt:
                            for g_attr in ("grade", "grade_id", "job_grade", "job_grade_id"):
                                if hasattr(cnt, g_attr) and getattr(cnt, g_attr):
                                    grade = getattr(cnt, g_attr)
                                    break

                if grade:
                    line.job_grade_id = grade
                    if hasattr(grade, "base_salary") and grade.base_salary:
                        line.base_salary = grade.base_salary
            if line.line_type == "manpower":
                line._compute_workforce_establishment()

    @api.depends("new_job_grade_id", "job_grade_id", "position_type")
    def _compute_new_job_grade(self):
        for line in self:
            if line.position_type == "new":
                g_rec = line.new_job_grade_id or line.job_grade_id
                if g_rec:
                    line.new_job_grade = (
                        getattr(g_rec, "grade_code", False)
                        or getattr(g_rec, "grade_name", False)
                        or getattr(g_rec, "name", False)
                    )

    @api.onchange("new_job_grade_id")
    def _onchange_new_job_grade_id(self):
        for line in self:
            if line.position_type == "new" and line.new_job_grade_id:
                line.job_grade_id = line.new_job_grade_id
                line.base_salary = line.new_job_grade_id.base_salary or 0.0
                line.new_job_grade = (
                    line.new_job_grade_id.grade_code
                    or line.new_job_grade_id.grade_name
                )
                if hasattr(line.new_job_grade_id, "category") and line.new_job_grade_id.category:
                    line.new_employee_category_id = line.new_job_grade_id.category

    @api.onchange("new_job_grade", "job_grade_id", "position_type")
    def _onchange_new_job_grade(self):
        for line in self:
            if line.position_type == "new":
                if not line.new_job_grade and line.new_job_grade_id:
                    line.new_job_grade = line.new_job_grade_id.grade_code or line.new_job_grade_id.grade_name
                elif line.new_job_grade and not line.new_job_grade_id:
                    search_str = line.new_job_grade.strip()
                    GradeModel = self.env["employee.grade"] if "employee.grade" in self.env else False
                    if GradeModel:
                        fields_to_check = [f for f in ("grade_code", "grade_name", "name", "code") if f in GradeModel._fields]
                        domain = []
                        for f in fields_to_check:
                            domain.append((f, "=ilike", search_str))
                        if len(domain) > 1:
                            domain = ["|"] * (len(domain) - 1) + domain
                        g = GradeModel.search(domain, limit=1)
                        if g:
                            line.new_job_grade_id = g
                            line.job_grade_id = g
                            if g.base_salary:
                                line.base_salary = g.base_salary

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------

    def _manpower_month_values(self):
        self.ensure_one()
        res = {}
        for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"):
            val_m = getattr(self, m, 0) or 0
            val_hc = getattr(self, f"hc_{m}", 0) or 0
            res[m] = int(val_m or val_hc or 0)
        return res

    def _apply_manpower_quarter_rollups(self):
        """Roll Jul-Jun monthly headcount into fiscal quarters."""
        if self.line_type != "manpower":
            return
        values = self._manpower_month_values()
        q1_calc = sum(values[m] for m in ("m01", "m02", "m03"))
        q2_calc = sum(values[m] for m in ("m04", "m05", "m06"))
        q3_calc = sum(values[m] for m in ("m07", "m08", "m09"))
        q4_calc = sum(values[m] for m in ("m10", "m11", "m12"))

        self.q1 = int(q1_calc if q1_calc else (self.quarter1_total or self.q1 or 0))
        self.q2 = int(q2_calc if q2_calc else (self.quarter2_total or self.q2 or 0))
        self.q3 = int(q3_calc if q3_calc else (self.quarter3_total or self.q3 or 0))
        self.q4 = int(q4_calc if q4_calc else (self.quarter4_total or self.q4 or 0))

        self.quarter1_total = float(self.q1)
        self.quarter2_total = float(self.q2)
        self.quarter3_total = float(self.q3)
        self.quarter4_total = float(self.q4)

    @api.depends(
        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",
        "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
        *HC_MONTH_FIELDS
    )
    def _compute_manpower_quarters(self):
        for line in self:
            if line.line_type == "manpower":
                line._apply_manpower_quarter_rollups()

    @api.onchange(
        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",
        "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
        *HC_MONTH_FIELDS
    )
    def _onchange_hc_months(self):
        if self.line_type == "manpower":
            self._apply_manpower_quarter_rollups()

    @api.onchange("q1")
    def _onchange_q1(self):
        if self.q1 and not (self.m01 or self.m02 or self.m03 or self.hc_m01 or self.hc_m02 or self.hc_m03):
            self.m03 = self.q1
            self.hc_m03 = self.q1
        self._apply_manpower_quarter_rollups()

    @api.onchange("q2")
    def _onchange_q2(self):
        if self.q2 and not (self.m04 or self.m05 or self.m06 or self.hc_m04 or self.hc_m05 or self.hc_m06):
            self.m06 = self.q2
            self.hc_m06 = self.q2
        self._apply_manpower_quarter_rollups()

    @api.onchange("q3")
    def _onchange_q3(self):
        if self.q3 and not (self.m07 or self.m08 or self.m09 or self.hc_m07 or self.hc_m08 or self.hc_m09):
            self.m09 = self.q3
            self.hc_m09 = self.q3
        self._apply_manpower_quarter_rollups()

    @api.onchange("q4")
    def _onchange_q4(self):
        if self.q4 and not (self.m10 or self.m11 or self.m12 or self.hc_m10 or self.hc_m11 or self.hc_m12):
            self.m12 = self.q4
            self.hc_m12 = self.q4
        self._apply_manpower_quarter_rollups()

    @api.depends(
        "line_type", "q1", "q2", "q3", "q4", "fa_q1", "fa_q2", "fa_q3", "fa_q4",
        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",
        *HC_MONTH_FIELDS,
    )
    def _compute_quantity(self):
        for line in self:
            is_fa = (line.line_type == "fixed_asset") or (line.plan_id and line.plan_id.category == "fixed_asset")
            if is_fa:
                line.quantity = int((line.fa_q1 or 0) + (line.fa_q2 or 0) + (line.fa_q3 or 0) + (line.fa_q4 or 0))
            elif line.line_type == "manpower":
                m_total = sum(getattr(line, m) or 0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
                hc_total = sum(getattr(line, m) or 0 for m in HC_MONTH_FIELDS)
                q_total = (line.q1 or 0) + (line.q2 or 0) + (line.q3 or 0) + (line.q4 or 0)
                line.quantity = int(m_total or hc_total or q_total or 0)
            else:
                m_total = sum(getattr(line, m) or 0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
                q_total = (line.q1 or 0) + (line.q2 or 0) + (line.q3 or 0) + (line.q4 or 0)
                line.quantity = int(m_total or q_total or 0)

    @api.onchange("quantity")
    def _onchange_quantity(self):
        for line in self:
            if line.line_type == "fixed_asset":
                q_sum = int((line.fa_q1 or 0) + (line.fa_q2 or 0) + (line.fa_q3 or 0) + (line.fa_q4 or 0))
                if (line.quantity or 0) > 0 and q_sum == 0:
                    line.fa_q1 = line.quantity
                price = line.estimated_unit_price or 0.0
                line.fa_q1_cost = (line.fa_q1 or 0) * price
                line.fa_q2_cost = (line.fa_q2 or 0) * price
                line.fa_q3_cost = (line.fa_q3 or 0) * price
                line.fa_q4_cost = (line.fa_q4 or 0) * price
                line.fa_annual_total_cost = (line.quantity or 0) * price
                line.annual_total = line.fa_annual_total_cost
                if line.plan_id and line.plan_id.state == "approved":
                    line.approved_quantity = line.quantity
                    line.fa_approved_total_cost = line.fa_annual_total_cost

    @api.depends("job_id", "plan_id.org_unit_id", "line_type", "plan_id.state")
    def _compute_workforce_establishment(self):
        has_ou_job_pos = "operating.unit.job.position" in self.env
        has_employee = "hr.employee" in self.env
        for line in self:
            if line.line_type == "manpower" and line.job_id and line.plan_id and line.plan_id.org_unit_id:
                pos = False
                if has_ou_job_pos:
                    pos = self.env["operating.unit.job.position"].search([
                        ("job_position_id", "=", line.job_id.id),
                        ("operating_unit_id", "=", line.plan_id.org_unit_id.id),
                    ], limit=1)
                if pos:
                    if hasattr(pos, "_compute_baseline_count") and not pos.baseline_count:
                        pos._compute_baseline_count()
                    b_count = getattr(pos, "baseline_count", 0) or 0
                    if not b_count:
                        b_count = getattr(pos, "total_headcount", 0) or getattr(pos, "approved_plan_count", 0) or 0
                    line.existing_establishment = b_count
                    line.active_staff_count = getattr(pos, "active_employee_count", 0) or 0
                    line.vacant_count = getattr(pos, "vacant_position_count", 0) or 0
                else:
                    emp_count = 0
                    if "hr.version" in self.env:
                        HrVersion = self.env["hr.version"]
                        emp_count = HrVersion.search_count([
                            ("state", "in", ["open", "probation"]),
                            ("operating_unit_id", "=", line.plan_id.org_unit_id.id),
                            ("employee_id.active", "=", True),
                            ("employee_id.job_position", "=", line.job_id.id),
                            ("employee_id.default_operating_unit_id", "=", line.plan_id.org_unit_id.id),
                        ])
                    if not emp_count and has_employee:
                        Employee = self.env["hr.employee"]
                        domain = [("active", "=", True)]
                        if "job_position" in Employee._fields:
                            domain.append(("job_position", "=", line.job_id.id))
                        elif "job_id" in Employee._fields:
                            domain.append(("job_id", "=", line.job_id.id))
                        if "operating_unit_ids" in Employee._fields:
                            domain.append(("operating_unit_ids", "in", [line.plan_id.org_unit_id.id]))
                        emp_count = Employee.search_count(domain)
                    line.existing_establishment = emp_count
                    line.active_staff_count = emp_count
                    line.vacant_count = 0
            else:
                line.existing_establishment = 0
                line.active_staff_count = 0
                line.vacant_count = 0

    @api.depends("existing_establishment", "quantity", "line_type", "plan_id.state")
    def _compute_total_establishment(self):
        for line in self:
            if line.line_type == "manpower":
                if line.plan_id and line.plan_id.state == "approved":
                    line.total_establishment = (line.existing_establishment or 0) + (line.quantity or 0)
                else:
                    line.total_establishment = 0
            else:
                line.total_establishment = (line.quantity or 0) if (line.plan_id and line.plan_id.state == "approved") else 0

    @api.depends("job_id", "job_grade_id.base_salary", "new_job_grade", "new_job_grade_id.base_salary", "position_type")
    def _compute_base_salary(self):
        GradeModel = self.env["employee.grade"] if "employee.grade" in self.env else False
        for line in self:
            if line.position_type == "new":
                salary = False
                if line.new_job_grade_id:
                    salary = line.new_job_grade_id.base_salary or 0.0
                elif line.new_job_grade and GradeModel:
                    search_str = line.new_job_grade.strip()
                    fields_to_check = [f for f in ("grade_code", "grade_name", "name", "code") if f in GradeModel._fields]
                    if fields_to_check:
                        domain = []
                        for f in fields_to_check:
                            domain.append((f, "=ilike", search_str))
                        if len(domain) > 1:
                            domain = ["|"] * (len(domain) - 1) + domain
                        g = GradeModel.search(domain, limit=1)
                        if g and g.base_salary:
                            salary = g.base_salary
                if salary is not False:
                    line.base_salary = salary
                elif not line.base_salary:
                    line.base_salary = 0.0
            elif line.job_grade_id:
                line.base_salary = line.job_grade_id.base_salary or 0.0
            elif line.job_id:
                g = getattr(line.job_id, "grade", False) or getattr(line.job_id, "job_grade", False) or getattr(line.job_id, "job_grade_id", False)
                if g and hasattr(g, "base_salary"):
                    line.base_salary = g.base_salary or 0.0
                elif not line.base_salary:
                    line.base_salary = 0.0
            else:
                if not line.base_salary:
                    line.base_salary = 0.0

    @api.depends("base_salary", "pension_rate")
    def _compute_compensation_breakdown(self):
        for line in self:
            salary = line.base_salary or 0.0
            p_rate = line.pension_rate or 0.0

            monthly_pen = salary * (p_rate / 100.0)
            monthly_total = salary + monthly_pen

            line.monthly_pension = monthly_pen
            line.annual_pension = monthly_pen * 12.0
            line.monthly_total_compensation = monthly_total
            line.unit_cost = monthly_total * 12.0

    @api.depends(
        "unit_cost", "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
        "q1", "q2", "q3", "q4",
        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",
        "quantity", *HC_MONTH_FIELDS,
    )
    def _compute_quarter_costs(self):
        for line in self:
            unit = line.unit_cost or 0.0
            q1_qty = line.quarter1_total if line.quarter1_total else (line.q1 or 0)
            q2_qty = line.quarter2_total if line.quarter2_total else (line.q2 or 0)
            q3_qty = line.quarter3_total if line.quarter3_total else (line.q3 or 0)
            q4_qty = line.quarter4_total if line.quarter4_total else (line.q4 or 0)
            line.q1_cost = q1_qty * unit
            line.q2_cost = q2_qty * unit
            line.q3_cost = q3_qty * unit
            line.q4_cost = q4_qty * unit

    @api.depends(
        "q1_cost", "q2_cost", "q3_cost", "q4_cost", "unit_cost", "quantity",
        "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",
        *HC_MONTH_FIELDS,
    )
    def _compute_annual_total_cost(self):
        for line in self:
            if line.line_type == "manpower":
                unit = line.unit_cost or 0.0
                q_cost = (line.q1_cost or 0.0) + (line.q2_cost or 0.0) + (line.q3_cost or 0.0) + (line.q4_cost or 0.0)
                if q_cost:
                    line.annual_total_cost = q_cost
                else:
                    qty = line.quantity or sum(getattr(line, m) or 0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
                    line.annual_total_cost = qty * unit
            else:
                line.annual_total_cost = (
                    (line.q1_cost or 0.0)
                    + (line.q2_cost or 0.0)
                    + (line.q3_cost or 0.0)
                    + (line.q4_cost or 0.0)
                )

    @api.depends("estimated_unit_price", "fa_q1", "fa_q2", "fa_q3", "fa_q4")
    def _compute_fa_quarter_costs(self):
        for line in self:
            price = line.estimated_unit_price or 0.0
            line.fa_q1_cost = (line.fa_q1 or 0) * price
            line.fa_q2_cost = (line.fa_q2 or 0) * price
            line.fa_q3_cost = (line.fa_q3 or 0) * price
            line.fa_q4_cost = (line.fa_q4 or 0) * price

    @api.onchange("fa_q1", "fa_q2", "fa_q3", "fa_q4", "estimated_unit_price")
    def _onchange_fa_quarters(self):
        for line in self:
            is_fa = (line.line_type == "fixed_asset") or (line.plan_id and line.plan_id.category == "fixed_asset") or (self.env.context.get("default_line_type") == "fixed_asset")
            if is_fa:
                line.quantity = int((line.fa_q1 or 0) + (line.fa_q2 or 0) + (line.fa_q3 or 0) + (line.fa_q4 or 0))
                price = line.estimated_unit_price or 0.0
                line.fa_q1_cost = (line.fa_q1 or 0) * price
                line.fa_q2_cost = (line.fa_q2 or 0) * price
                line.fa_q3_cost = (line.fa_q3 or 0) * price
                line.fa_q4_cost = (line.fa_q4 or 0) * price
                line.fa_annual_total_cost = line.fa_q1_cost + line.fa_q2_cost + line.fa_q3_cost + line.fa_q4_cost
                line.annual_total = line.fa_annual_total_cost
                if line.plan_id and line.plan_id.state == "approved":
                    line.approved_quantity = line.quantity
                    line.fa_approved_total_cost = line.fa_annual_total_cost

    @api.depends("quantity", "line_type", "plan_id.state")
    def _compute_approved_quantity(self):
        for line in self:
            if line.line_type == "fixed_asset":
                if line.plan_id and line.plan_id.state == "approved":
                    line.approved_quantity = line.quantity or 0
                elif not line.approved_quantity:
                    line.approved_quantity = 0
            else:
                line.approved_quantity = line.quantity if (line.plan_id and line.plan_id.state == "approved") else 0

    @api.depends("fa_annual_total_cost", "approved_quantity", "quantity", "estimated_unit_price", "line_type", "plan_id.state")
    def _compute_fa_approved_total_cost(self):
        for line in self:
            if line.line_type == "fixed_asset":
                if line.plan_id and line.plan_id.state == "approved":
                    qty = line.approved_quantity if line.approved_quantity is not False else (line.quantity or 0)
                    line.fa_approved_total_cost = (qty or line.quantity or 0) * (line.estimated_unit_price or 0.0)
                elif not line.fa_approved_total_cost:
                    line.fa_approved_total_cost = 0.0
            else:
                line.fa_approved_total_cost = 0.0

    @api.depends("fa_q1_cost", "fa_q2_cost", "fa_q3_cost", "fa_q4_cost", "fa_q1", "fa_q2", "fa_q3", "fa_q4", "quantity", "estimated_unit_price")
    def _compute_fa_annual_total_cost(self):
        for line in self:
            quarter_cost = (
                (line.fa_q1_cost or 0.0)
                + (line.fa_q2_cost or 0.0)
                + (line.fa_q3_cost or 0.0)
                + (line.fa_q4_cost or 0.0)
            )
            line.fa_annual_total_cost = quarter_cost if quarter_cost > 0 else ((line.quantity or 0) * (line.estimated_unit_price or 0.0))

    @api.depends(
        "m01", "m02", "m03", "m04", "m05", "m06",
        "m07", "m08", "m09", "m10", "m11", "m12",
    )
    def _compute_quarter_targets(self):
        for line in self:
            line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)
            line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)
            line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)
            line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)

    @api.onchange(
        "m01", "m02", "m03", "m04", "m05", "m06",
        "m07", "m08", "m09", "m10", "m11", "m12",
    )
    def _onchange_months_update_quarters(self):
        for line in self:
            line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)
            line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)
            line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)
            line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)
            if line.line_type not in ("manpower", "fixed_asset"):
                line.annual_total = line.quarter1_total + line.quarter2_total + line.quarter3_total + line.quarter4_total
                line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

    @api.onchange("opening_balance")
    def _onchange_opening_balance(self):
        for line in self:
            line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

    @api.onchange("quarter1_total")
    def _onchange_quarter1_total(self):
        if self.quarter1_total and not (self.m01 or self.m02 or self.m03):
            self.m03 = self.quarter1_total
        self.quarter1_total = (self.m01 or 0.0) + (self.m02 or 0.0) + (self.m03 or 0.0)

    @api.onchange("quarter2_total")
    def _onchange_quarter2_total(self):
        if self.quarter2_total and not (self.m04 or self.m05 or self.m06):
            self.m06 = self.quarter2_total
        self.quarter2_total = (self.m04 or 0.0) + (self.m05 or 0.0) + (self.m06 or 0.0)

    @api.onchange("quarter3_total")
    def _onchange_quarter3_total(self):
        if self.quarter3_total and not (self.m07 or self.m08 or self.m09):
            self.m09 = self.quarter3_total
        self.quarter3_total = (self.m07 or 0.0) + (self.m08 or 0.0) + (self.m09 or 0.0)

    @api.onchange("quarter4_total")
    def _onchange_quarter4_total(self):
        if self.quarter4_total and not (self.m10 or self.m11 or self.m12):
            self.m12 = self.quarter4_total
        self.quarter4_total = (self.m10 or 0.0) + (self.m11 or 0.0) + (self.m12 or 0.0)

    @api.onchange(
        "m01", "m02", "m03", "m04", "m05", "m06",
        "m07", "m08", "m09", "m10", "m11", "m12",
    )
    def _onchange_manpower_monthly_headcount(self):
        for line in self:
            if line.line_type != "manpower":
                continue
            line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)
            line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)
            line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)
            line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)
            line.annual_total = (
                line.quarter1_total + line.quarter2_total + line.quarter3_total + line.quarter4_total
            )
            plan_state = line.plan_id.state if line.plan_id else self.env.context.get("default_state")
            if plan_state in ("committee_review", "ceo_approval") or (
                self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_ceo() or self.env.is_admin()
            ):
                line._auto_balance_manpower_sourcing()

    @api.depends(
        "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",
        "m01", "m02", "m03", "m04", "m05", "m06",
        "m07", "m08", "m09", "m10", "m11", "m12",
        "fa_annual_total_cost", "line_type",
    )
    def _compute_annual_total(self):
        for line in self:
            if line.line_type == "fixed_asset":
                line.annual_total = line.fa_annual_total_cost or 0.0
            elif line.line_type == "manpower":
                line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)
                line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)
                line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)
                line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)
                line.annual_total = (
                    line.quarter1_total + line.quarter2_total + line.quarter3_total + line.quarter4_total
                )
            else:
                line.annual_total = (
                    (line.quarter1_total or 0.0)
                    + (line.quarter2_total or 0.0)
                    + (line.quarter3_total or 0.0)
                    + (line.quarter4_total or 0.0)
                )

    def _distribute_annual_total_proportionally(self):
        """Distribute modified annual_total proportionally across m01..m12 and quarters."""
        Config = self.env["pbms.planning.config"] if "pbms.planning.config" in self.env else False
        for line in self:
            if line.line_type in ("manpower", "fixed_asset"):
                continue
            new_total = line.annual_total or 0.0
            old_months = [(getattr(line, m) or 0.0) for m in MONTH_FIELDS]
            old_total = sum(old_months)

            # Determine whether this line category is monetary or integer
            is_monetary = True
            if Config and line.plan_id and line.plan_id.org_unit_id:
                m_type = Config.get_measurement_type(line.line_type, org_unit=line.plan_id.org_unit_id)
                is_monetary = (m_type == "monetary")

            new_months = [0.0] * 12
            if abs(old_total) > 1e-6:
                # Proportional distribution according to each month's share of previous total
                for i, m_val in enumerate(old_months):
                    new_months[i] = new_total * (m_val / old_total)
            else:
                # If existing total was 0, distribute equally across 12 months
                equal_share = new_total / 12.0
                new_months = [equal_share] * 12

            if is_monetary:
                rounded_months = [round(val, 2) for val in new_months]
                diff = round(new_total - sum(rounded_months), 2)
                if abs(diff) > 0.0001:
                    last_idx = 11
                    for idx in reversed(range(12)):
                        if abs(old_months[idx]) > 1e-6:
                            last_idx = idx
                            break
                    rounded_months[last_idx] = round(rounded_months[last_idx] + diff, 2)
            else:
                rounded_months = [int(round(val)) for val in new_months]
                diff = int(round(new_total)) - sum(rounded_months)
                if diff != 0:
                    last_idx = 11
                    for idx in reversed(range(12)):
                        if abs(old_months[idx]) > 1e-6:
                            last_idx = idx
                            break
                    rounded_months[last_idx] += diff

            for i, m in enumerate(MONTH_FIELDS):
                setattr(line, m, rounded_months[i])

            line.quarter1_total = sum(rounded_months[0:3])
            line.quarter2_total = sum(rounded_months[3:6])
            line.quarter3_total = sum(rounded_months[6:9])
            line.quarter4_total = sum(rounded_months[9:12])
            line.outstanding_year_end = (line.opening_balance or 0.0) + new_total

            # Differentiate review levels: Head Office Reviewer vs District Reviewer / Branch Submitter
            user = self.env.user
            if user._pbms_is_ho_reviewer() or bool(self.env.context.get("is_ho_review")):
                is_ho_review = True
            elif user._pbms_is_district_reviewer():
                is_ho_review = False
            else:
                is_ho_review = (
                    (line.plan_id and line.plan_id.state in ("ho_reviewed", "approved", "committee_review", "ceo_approval"))
                    or (line.plan_id and line.plan_id.org_unit_type == "head_office")
                )

            line_vals = {
                "quarter1_total": line.quarter1_total,
                "quarter2_total": line.quarter2_total,
                "quarter3_total": line.quarter3_total,
                "quarter4_total": line.quarter4_total,
                "outstanding_year_end": line.outstanding_year_end,
            }
            for i, m in enumerate(MONTH_FIELDS):
                line_vals[m] = rounded_months[i]

            if not is_ho_review:
                # District Reviewer or Branch Submitter: update proposed plan so the branch views the updated plan
                line.proposed_annual_total = new_total
                line_vals["proposed_annual_total"] = new_total
                for i, m in enumerate(MONTH_FIELDS):
                    setattr(line, f"proposed_{m}", rounded_months[i])
                    line_vals[f"proposed_{m}"] = rounded_months[i]
                line.proposed_opening_balance = line.opening_balance or 0.0
                line_vals["proposed_opening_balance"] = line.opening_balance or 0.0

            if line.id and not self.env.context.get("in_distribute_sync"):
                line.with_context(in_distribute_sync=True, bypass_plan_lock=True, skip_reviewer_check=True).write(line_vals)

            if not is_ho_review:
                # If this line was edited on a District Overview Plan, sync it back to the branch's plan
                if line.plan_id and line.plan_id.org_unit_type == "district_office" and line.source_unit_id:
                    if not self.env.context.get("skip_branch_sync"):
                        branch_line = line.source_line_id
                        if not branch_line:
                            domain = [
                                ("plan_id.cycle_id", "=", line.cycle_id.id),
                                ("plan_id.org_unit_id", "=", line.source_unit_id.id),
                                ("line_type", "=", line.line_type),
                            ]
                            if line.deposit_type_id:
                                domain.append(("deposit_type_id", "=", line.deposit_type_id.id))
                            if line.base_type:
                                domain.append(("base_type", "=", line.base_type))
                            if line.channel_id:
                                domain.append(("channel_id", "=", line.channel_id.id))
                            if line.fx_source_type:
                                domain.append(("fx_source_type", "=", line.fx_source_type.id))
                            if line.expense_account_id:
                                domain.append(("expense_account_id", "=", line.expense_account_id.id))
                            branch_line = self.search(domain, limit=1)
                        if branch_line and branch_line != line:
                            b_vals = {
                                "annual_total": new_total,
                                "proposed_annual_total": new_total,
                                "opening_balance": line.opening_balance or 0.0,
                                "proposed_opening_balance": line.opening_balance or 0.0,
                                "quarter1_total": line.quarter1_total,
                                "quarter2_total": line.quarter2_total,
                                "quarter3_total": line.quarter3_total,
                                "quarter4_total": line.quarter4_total,
                                "outstanding_year_end": line.outstanding_year_end,
                            }
                            for i, m in enumerate(MONTH_FIELDS):
                                b_vals[m] = rounded_months[i]
                                b_vals[f"proposed_{m}"] = rounded_months[i]
                            branch_line.with_context(skip_branch_sync=True, bypass_plan_lock=True).write(b_vals)
                            if branch_line.plan_id and hasattr(branch_line.plan_id, "_compute_category_summaries"):
                                branch_line.plan_id._compute_category_summaries()

                # If this line was edited directly on a Branch Plan, sync forward to District Overview Plan if it exists
                elif line.plan_id and line.plan_id.org_unit_type in ("branch", "sub_branch"):
                    district = line.district_id or (line.plan_id and line.plan_id._find_district_ancestor(line.plan_id.org_unit_id))
                    if district and not self.env.context.get("skip_branch_sync"):
                        dist_domain = [
                            ("plan_id.cycle_id", "=", line.cycle_id.id),
                            ("plan_id.org_unit_id", "=", district.id),
                            ("line_type", "=", line.line_type),
                            ("source_unit_id", "=", line.plan_id.org_unit_id.id),
                        ]
                        if line.deposit_type_id:
                            dist_domain.append(("deposit_type_id", "=", line.deposit_type_id.id))
                        if line.base_type:
                            dist_domain.append(("base_type", "=", line.base_type))
                        if line.channel_id:
                            dist_domain.append(("channel_id", "=", line.channel_id.id))
                        if line.fx_source_type:
                            dist_domain.append(("fx_source_type", "=", line.fx_source_type.id))
                        if line.expense_account_id:
                            dist_domain.append(("expense_account_id", "=", line.expense_account_id.id))
                        dist_line = self.search(dist_domain, limit=1)
                        if dist_line and dist_line != line:
                            d_vals = {
                                "annual_total": new_total,
                                "proposed_annual_total": new_total,
                                "opening_balance": line.opening_balance or 0.0,
                                "proposed_opening_balance": line.opening_balance or 0.0,
                                "quarter1_total": line.quarter1_total,
                                "quarter2_total": line.quarter2_total,
                                "quarter3_total": line.quarter3_total,
                                "quarter4_total": line.quarter4_total,
                                "outstanding_year_end": line.outstanding_year_end,
                            }
                            for i, m in enumerate(MONTH_FIELDS):
                                d_vals[m] = rounded_months[i]
                                d_vals[f"proposed_{m}"] = rounded_months[i]
                            dist_line.with_context(skip_branch_sync=True, bypass_plan_lock=True).write(d_vals)
                            if dist_line.plan_id and hasattr(dist_line.plan_id, "_compute_category_summaries"):
                                dist_line.plan_id._compute_category_summaries()
            else:
                # Head Office review: changes annual_total proportionally without altering District's proposed plan ("as it is")
                pass

    @api.onchange("annual_total")
    def _onchange_annual_total(self):
        self._distribute_annual_total_proportionally()

    def _inverse_annual_total(self):
        self._distribute_annual_total_proportionally()
        for line in self:
            if line.plan_id and hasattr(line.plan_id, "_compute_category_summaries"):
                line.plan_id._compute_category_summaries()

    @api.depends("opening_balance", "annual_total")
    def _compute_outstanding_year_end(self):
        for line in self:
            line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

    @api.depends(
        "proposed_m01", "proposed_m02", "proposed_m03", "proposed_m04", "proposed_m05", "proposed_m06",
        "proposed_m07", "proposed_m08", "proposed_m09", "proposed_m10", "proposed_m11", "proposed_m12",
        "annual_total", "is_cascaded", "plan_id.state", "plan_id.org_unit_type",
    )
    def _compute_proposed_annual_total(self):
        user = self.env.user
        is_ho_context = (
            user._pbms_is_ho_reviewer()
            or bool(self.env.context.get("is_ho_review"))
        )
        for line in self:
            tot = sum(getattr(line, f"proposed_m{i:02d}") or 0.0 for i in range(1, 13))
            is_ho_stage = (
                is_ho_context
                or (line.plan_id and line.plan_id.state in ("ho_reviewed", "approved", "committee_review", "ceo_approval"))
                or (line.plan_id and line.plan_id.org_unit_type == "head_office")
            )
            if user._pbms_is_district_reviewer():
                is_ho_stage = False
            if tot > 0:
                line.proposed_annual_total = tot
            elif is_ho_stage:
                # Head office review stage / approved: preserve proposed_annual_total as-is
                if not line.proposed_annual_total:
                    line.proposed_annual_total = line.annual_total
            elif not line.is_cascaded:
                line.proposed_annual_total = line.annual_total
            elif not line.proposed_annual_total:
                line.proposed_annual_total = line.annual_total

    @api.depends(
        "approved_m01", "approved_m02", "approved_m03", "approved_m04", "approved_m05", "approved_m06",
        "approved_m07", "approved_m08", "approved_m09", "approved_m10", "approved_m11", "approved_m12",
        "is_cascaded", "annual_total", "plan_id.state", "plan_id.org_unit_id.work_unit_type",
        "line_type", "plan_id.category",
    )
    def _compute_approved_annual_total(self):
        for line in self:
            tot = sum(getattr(line, f"approved_m{i:02d}") or 0.0 for i in range(1, 13))
            is_expense = (line.line_type == "general_expense") or (line.plan_id and line.plan_id.category == "general_expense")
            is_manpower = (line.line_type == "manpower") or (line.plan_id and line.plan_id.category == "manpower")
            if is_manpower:
                state = line.plan_id.state if line.plan_id else "draft"
                if state in ("ho_endorse", "cpco_endorse", "approved"):
                    line.approved_annual_total = line.approved_annual_total if line.approved_annual_total else (tot if tot > 0 else 0.0)
                else:
                    line.approved_annual_total = 0.0
            elif is_expense:
                if line.plan_id and line.plan_id.state == "approved":
                    line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)
                else:
                    line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or 0.0)
            elif line.is_cascaded:
                line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)
            elif line.plan_id and line.plan_id.org_unit_type == "head_office" and line.plan_id.state == "approved":
                line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)
            else:
                line.approved_annual_total = 0.0

    @api.depends("plan_id.state", "approved_annual_total", "fulfillment_total", "annual_total", "line_type")
    def _compute_display_approved_annual_total(self):
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user.has_group("base.group_system")
        is_comm = user._pbms_is_budget_hiring_committee()
        is_ceo = user._pbms_is_ceo()
        is_ho = user._pbms_is_ho_reviewer()
        is_cpco = user._pbms_is_cpco()

        for line in self:
            if line.line_type != "manpower":
                line.display_approved_annual_total = line.approved_annual_total or 0.0
                continue

            state = line.plan_id.state if line.plan_id else "draft"
            target = float(line.approved_annual_total or line.fulfillment_total or line.annual_total or 0.0)

            # 1. State 'approved': CPCO has endorsed to People Solutions Directorate.
            # Valued for all: Branch Users, Districts, Chiefs, People Solutions, CPCO, Committee, CEO, HO Reviewer.
            if state == "approved":
                line.display_approved_annual_total = target

            # 2. State 'cpco_endorse': Head Office functional reviewer has endorsed to CPCO.
            # Valued for CPCO, Committee, CEO, HO Reviewer, Admin.
            # For Branch Users, Districts, Chiefs, People Solutions: 0.0!
            elif state == "cpco_endorse":
                if is_cpco or is_comm or is_ceo or is_ho or is_admin:
                    line.display_approved_annual_total = target
                else:
                    line.display_approved_annual_total = 0.0

            # 3. State 'ho_endorse': CEO has approved.
            # Valued for Budget Hiring Committee, CEO, HO Reviewer, Admin.
            # For CPCO: not valued before HO reviewer endorses (0.0)!
            # For Branch Users, Districts, Chiefs, People Solutions: 0.0!
            elif state == "ho_endorse":
                if is_comm or is_ceo or is_ho or is_admin:
                    line.display_approved_annual_total = target
                else:
                    line.display_approved_annual_total = 0.0

            # 4. In all other states (draft, submitted, chief_review, people_solutions_review, cpco_review, committee_review, ceo_approval):
            # No valued! In ceo_approval, Approved Target must NOT be valued before CEO final approval takes action!
            else:
                line.display_approved_annual_total = 0.0

    @api.depends("proposed_annual_total", "approved_annual_total", "annual_total", "is_cascaded")
    def _compute_target_variance(self):
        for line in self:
            if not line.is_cascaded:
                line.variance_amount = 0.0
                line.variance_percentage = 0.0
                continue
            prop = line.proposed_annual_total or line.annual_total or 0.0
            appr = line.approved_annual_total or 0.0
            diff = appr - prop
            line.variance_amount = diff
            if prop != 0.0:
                line.variance_percentage = round((diff / prop) * 100.0, 2)
            else:
                line.variance_percentage = 0.0

    def _snapshot_proposed_targets(self):
        """Freeze current monthly values into proposed_m01..m12 and proposed_annual_total in batch."""
        if not self:
            return
        self.env.cr.execute("""
            UPDATE pbms_plan_category_line
            SET
                proposed_opening_balance = COALESCE(opening_balance, 0.0),
                proposed_annual_total = COALESCE(annual_total, 0.0),
                proposed_m01 = COALESCE(m01, 0.0),
                proposed_m02 = COALESCE(m02, 0.0),
                proposed_m03 = COALESCE(m03, 0.0),
                proposed_m04 = COALESCE(m04, 0.0),
                proposed_m05 = COALESCE(m05, 0.0),
                proposed_m06 = COALESCE(m06, 0.0),
                proposed_m07 = COALESCE(m07, 0.0),
                proposed_m08 = COALESCE(m08, 0.0),
                proposed_m09 = COALESCE(m09, 0.0),
                proposed_m10 = COALESCE(m10, 0.0),
                proposed_m11 = COALESCE(m11, 0.0),
                proposed_m12 = COALESCE(m12, 0.0)
            WHERE id IN %s;
        """, (tuple(self.ids),))
        self.invalidate_recordset([
            "proposed_opening_balance", "proposed_annual_total",
            "proposed_m01", "proposed_m02", "proposed_m03", "proposed_m04",
            "proposed_m05", "proposed_m06", "proposed_m07", "proposed_m08",
            "proposed_m09", "proposed_m10", "proposed_m11", "proposed_m12",
        ])


    def _pbms_check_parent_plan_editable(self):
        if (
            self.env.is_admin()
            or self.env.user._pbms_is_sppmd_admin()
            or self.env.user._pbms_is_sppmd_approver()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
        ):
            return
        for line in self:
            if line.plan_id:
                if line.plan_id.cycle_id and line.plan_id.cycle_id.state != "open":
                    cycle_label = dict(line.plan_id.cycle_id._fields["state"].selection).get(line.plan_id.cycle_id.state, line.plan_id.cycle_id.state)
                    raise AccessError(_(
                        "Planning cycle '%s' is currently '%s' and is not open for unit input. "
                        "You cannot modify plan data until the cycle is officially opened by SPPMD."
                    ) % (line.plan_id.cycle_id.name, cycle_label))
                if not line.plan_id._pbms_can_edit_plan_content():
                    raise AccessError(_(
                        "You do not have permission to edit this plan at its current workflow stage."
                    ))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "plan_id" in fields_list and not res.get("plan_id"):
            plan_id = (
                self.env.context.get("default_plan_id")
                or self.env.context.get("plan_id")
                or (self.env.context.get("active_id") if self.env.context.get("active_model") == "pbms.planning.category" else False)
            )
            if not plan_id and self.env.context.get("params", {}).get("id") and self.env.context.get("params", {}).get("model") == "pbms.planning.category":
                plan_id = self.env.context.get("params", {}).get("id")
            if plan_id:
                res["plan_id"] = plan_id
            else:
                org_unit_id = res.get("org_unit_id") or self.env.context.get("default_org_unit_id") or self.env.context.get("org_unit_id")
                cycle_id = res.get("cycle_id") or self.env.context.get("default_cycle_id") or self.env.context.get("cycle_id")
                if org_unit_id and cycle_id:
                    plan = self.env["pbms.planning.category"].search([
                        ("org_unit_id", "=", org_unit_id),
                        ("cycle_id", "=", cycle_id),
                        ("active", "=", True),
                    ], limit=1)
                    if plan:
                        res["plan_id"] = plan.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        Plan = self.env["pbms.planning.category"]
        user = self.env.user
        is_bypass = (
            self.env.is_admin()
            or user._pbms_is_sppmd_admin()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
            or self.env.context.get("skip_reviewer_check")
        )
        if not is_bypass and (user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer()):
            raise UserError(_(
                "District Reviewers and Head Office Reviewers cannot add new lines. "
                "You can only edit lines created by the branch."
            ))

        is_admin = (
            self.env.is_admin()
            or user._pbms_is_sppmd_admin()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
        )
        for vals in vals_list:
            if not vals.get("plan_id"):
                plan_id = (
                    self.env.context.get("default_plan_id")
                    or self.env.context.get("plan_id")
                    or (self.env.context.get("active_id") if self.env.context.get("active_model") == "pbms.planning.category" else False)
                )
                if not plan_id and self.env.context.get("params", {}).get("id") and self.env.context.get("params", {}).get("model") == "pbms.planning.category":
                    plan_id = self.env.context.get("params", {}).get("id")
                if not plan_id:
                    Config = self.env["pbms.planning.config"] if "pbms.planning.config" in self.env else False
                    default_type = Config.get_default_category_for_unit(org_unit_id) if (Config and org_unit_id) else "deposit"
                    line_type = vals.get("line_type") or self.env.context.get("default_line_type") or default_type
                    if org_unit_id and cycle_id:
                        found_plan = Plan.search([
                            ("org_unit_id", "=", org_unit_id),
                            ("cycle_id", "=", cycle_id),
                            ("active", "=", True),
                        ], limit=1)
                        if found_plan:
                            plan_id = found_plan.id
                        else:
                            new_plan = Plan.sudo().create({
                                "org_unit_id": org_unit_id,
                                "cycle_id": cycle_id,
                                "category": line_type,
                            })
                            plan_id = new_plan.id
                if plan_id:
                    vals["plan_id"] = plan_id

            plan_id = vals.get("plan_id")
            if plan_id and not is_admin:
                plan = Plan.browse(plan_id)
                if plan.cycle_id and plan.cycle_id.state != "open":
                    cycle_label = dict(plan.cycle_id._fields["state"].selection).get(plan.cycle_id.state, plan.cycle_id.state)
                    raise AccessError(_(
                        "Planning cycle '%s' is currently '%s' and is not open for unit input. "
                        "You cannot add requirement lines until the cycle is officially opened by SPPMD."
                    ) % (plan.cycle_id.name, cycle_label))
                if plan and not plan._pbms_can_edit_plan_content():
                    raise AccessError(_(
                        "You cannot add requirement lines while the parent plan is view-only "
                        "at its current workflow stage."
                    ))
        return super().create(vals_list)

    SYSTEM_AUTOMATED_LINE_FIELDS = {
        "existing_establishment",
        "active_staff_count",
        "vacant_count",
        "total_establishment",
        "is_cascaded",
        "approved_quantity",
        "approved_annual_total",
        "fa_approved_total_cost",
        "monthly_pension",
        "annual_pension",
        "quarter1_total",
        "quarter2_total",
        "quarter3_total",
        "quarter4_total",
        "q1", "q2", "q3", "q4",
        "fulfillment_total",
        "fulfillment_balance",
    }

    def write(self, vals):
        if "plan_id" in vals and not vals["plan_id"]:
            vals = dict(vals)
            del vals["plan_id"]
            if not vals:
                return True
        if not set(vals.keys()).issubset(self.SYSTEM_AUTOMATED_LINE_FIELDS):
            self._pbms_check_parent_plan_editable()
        res = super().write(vals)

        # For manpower lines, ensure quarters, annual_total, and sourcing are synchronized
        hc_fields = {"m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12", "annual_total"}
        sourcing_fields = {"fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external"}
        if (hc_fields & set(vals.keys())) and not self.env.context.get("auto_balancing_sourcing"):
            for line in self:
                if line.line_type == "manpower":
                    q1 = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)
                    q2 = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)
                    q3 = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)
                    q4 = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)
                    tot = q1 + q2 + q3 + q4
                    line.with_context(bypass_plan_lock=True, auto_balancing_sourcing=True).sudo().write({
                        "quarter1_total": q1,
                        "quarter2_total": q2,
                        "quarter3_total": q3,
                        "quarter4_total": q4,
                        "annual_total": tot,
                    })
                    plan_state = line.plan_id.state if line.plan_id else False
                    if not (sourcing_fields & set(vals.keys())):
                        if plan_state in ("people_solutions_review", "cpco_review", "committee_review", "ceo_approval") or (
                            self.env.user._pbms_is_people_solutions() or self.env.user._pbms_is_cpco() or self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_ceo() or self.env.is_admin()
                        ):
                            line._auto_balance_manpower_sourcing()
        return res

    def unlink(self):
        user = self.env.user
        is_bypass = (
            self.env.is_admin()
            or user._pbms_is_sppmd_admin()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
            or self.env.context.get("skip_reviewer_check")
        )
        if not is_bypass and (user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer()):
            raise UserError(_(
                "District Reviewers and Head Office Reviewers cannot delete lines. "
                "You can only edit lines created by the branch."
            ))
        self._pbms_check_parent_plan_editable()
        return super().unlink()

    def action_export_excel(self):
        """Export selected plan requirement lines using official Bunna Bank form templates."""
        records = self or self.browse(self.env.context.get("active_ids", []))
        plans = records.mapped("plan_id")
        if plans:
            return plans.action_export_excel()
        raise UserError(_("No planning records associated with the selected lines."))

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        NON_EXPORTABLE_LINE_FIELDS = {
            "deposit_type_domain", "channel_domain", "expense_account_domain",
            "fa_category_domain", "justification_category_domain", "fx_source_type_domain",
            "is_monetary", "new_job_grade",
        }
        for fname in NON_EXPORTABLE_LINE_FIELDS:
            if fname in res:
                res[fname]["exportable"] = False
        return res

    _unit_price_non_negative = models.Constraint("CHECK(estimated_unit_price IS NULL OR estimated_unit_price >= 0)", "Unit price cannot be negative.")
    _q1_non_negative = models.Constraint("CHECK(q1 >= 0)", "Q1 quantity cannot be negative.")
    _q2_non_negative = models.Constraint("CHECK(q2 >= 0)", "Q2 quantity cannot be negative.")
    _q3_non_negative = models.Constraint("CHECK(q3 >= 0)", "Q3 quantity cannot be negative.")
    _q4_non_negative = models.Constraint("CHECK(q4 >= 0)", "Q4 quantity cannot be negative.")
    _fa_q1_non_negative = models.Constraint("CHECK(fa_q1 >= 0)", "FA Q1 quantity cannot be negative.")
    _fa_q2_non_negative = models.Constraint("CHECK(fa_q2 >= 0)", "FA Q2 quantity cannot be negative.")
    _fa_q3_non_negative = models.Constraint("CHECK(fa_q3 >= 0)", "FA Q3 quantity cannot be negative.")
    _fa_q4_non_negative = models.Constraint("CHECK(fa_q4 >= 0)", "FA Q4 quantity cannot be negative.")
    _hc_m01_non_negative = models.Constraint("CHECK(hc_m01 >= 0)", "Jul headcount cannot be negative.")
    _hc_m02_non_negative = models.Constraint("CHECK(hc_m02 >= 0)", "Aug headcount cannot be negative.")
    _hc_m03_non_negative = models.Constraint("CHECK(hc_m03 >= 0)", "Sep headcount cannot be negative.")
    _hc_m04_non_negative = models.Constraint("CHECK(hc_m04 >= 0)", "Oct headcount cannot be negative.")
    _hc_m05_non_negative = models.Constraint("CHECK(hc_m05 >= 0)", "Nov headcount cannot be negative.")
    _hc_m06_non_negative = models.Constraint("CHECK(hc_m06 >= 0)", "Dec headcount cannot be negative.")
    _hc_m07_non_negative = models.Constraint("CHECK(hc_m07 >= 0)", "Jan headcount cannot be negative.")
    _hc_m08_non_negative = models.Constraint("CHECK(hc_m08 >= 0)", "Feb headcount cannot be negative.")
    _hc_m09_non_negative = models.Constraint("CHECK(hc_m09 >= 0)", "Mar headcount cannot be negative.")
    _hc_m10_non_negative = models.Constraint("CHECK(hc_m10 >= 0)", "Apr headcount cannot be negative.")
    _hc_m11_non_negative = models.Constraint("CHECK(hc_m11 >= 0)", "May headcount cannot be negative.")
    _hc_m12_non_negative = models.Constraint("CHECK(hc_m12 >= 0)", "Jun headcount cannot be negative.")
class PbmsPlanningCategory(models.Model):
    _name = "pbms.planning.category"
    _description = "Plan & Budget Category"
    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"
    _order = "category, org_unit_id, id"

    # Active field for archive functionality
    active = fields.Boolean(
        default=True,
        string="Active",
        help="Uncheck to archive this planning category line"
    )

    request_number = fields.Char(
        string="Request Number",
        readonly=True,
        copy=False,
        default="New",
        index=True,
        tracking=True,
        help="Auto-generated unique request tracking number",
    )
    # If not already present, add this to PbmsPlanningCategory
    work_unit_type = fields.Selection(
        WORK_UNIT_TYPES,
        related="org_unit_id.work_unit_type",
        store=True,
        readonly=True
    )
    sol_id = fields.Integer(
        string="Sol ID",
        related="org_unit_id.sol_id",
        store=True,
        readonly=True,
        index=True,
    )
    # Configurable Business Justification
    justification_category_id = fields.Many2one(
        "pbms.justification.category",
        string="Business Justification Category",
        index=True,
        tracking=True,
        compute="_compute_category_specific_fields",
        store=True,
        readonly=False,
        help="Primary business justification category",
    )
    other_justification = fields.Char(
        string="Justification Remarks",
        help="Additional remarks when 'Other' or special justification is selected.",
    )
    business_justification = fields.Text(
        string="Business Justification Summary",
        tracking=True,
        help="Executive summary of the business justification for this plan.",
    )
    # Add these fields to your PbmsPlanningCategory class
    enable_deposit = fields.Boolean(compute="_compute_eligibility")
    enable_customer_base = fields.Boolean(compute="_compute_eligibility")
    enable_fx = fields.Boolean(compute="_compute_eligibility")
    enable_digital_banking = fields.Boolean(compute="_compute_eligibility")
    enable_expense = fields.Boolean(compute="_compute_eligibility")
    enable_manpower = fields.Boolean(compute="_compute_eligibility")
    enable_fixed_asset = fields.Boolean(compute="_compute_eligibility")

    # Measurement Types per category (monetary, integer, count)
    deposit_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Deposit Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    customer_base_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Customer Base Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    fx_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="FX Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    digital_banking_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Digital Banking Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    expense_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Expense Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    manpower_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Manpower Measurement",
        compute="_compute_measurement_types",
        store=True,
    )
    fixed_asset_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Fixed Asset Measurement",
        compute="_compute_measurement_types",
        store=True,
    )

    is_deposit_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_customer_base_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_fx_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_digital_banking_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_expense_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_manpower_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_fixed_asset_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)

    can_edit_content = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_delete_plan = fields.Boolean(compute="_compute_access_flags")
    can_submit_plan = fields.Boolean(compute="_compute_access_flags")
    can_district_review = fields.Boolean(compute="_compute_access_flags")
    can_ho_review = fields.Boolean(compute="_compute_access_flags")
    can_sppmd_review = fields.Boolean(compute="_compute_access_flags")
    can_use_reviewer_wizards = fields.Boolean(compute="_compute_access_flags")
    can_committee_review = fields.Boolean(compute="_compute_access_flags")
    can_hr_fulfill = fields.Boolean(compute="_compute_access_flags")
    can_ceo_approve = fields.Boolean(compute="_compute_access_flags")
    can_chief_review = fields.Boolean(compute="_compute_access_flags")
    can_cpco_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_people_solutions_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_ho_endorse = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_cpco_endorse = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_view_sourcing_fields = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_edit_sourcing_fields = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_add_lines = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    @api.depends("state", "org_unit_id", "org_unit_id.parent_unit", "org_unit_type", "category", "cycle_id", "cycle_id.state")
    def _compute_access_flags(self):
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user.has_group("base.group_system")
        for rec in self:
            rec.can_edit_content = rec._pbms_can_edit_plan_content()
            rec.can_delete_plan = rec._pbms_can_delete_plan()
            rec.can_submit_plan = rec._pbms_can_submit_plan()
            rec.can_district_review = rec._pbms_can_district_review_plan()
            rec.can_ho_review = rec._pbms_can_ho_review_plan()
            rec.can_sppmd_review = rec._pbms_can_sppmd_review_plan()
            rec.can_use_reviewer_wizards = rec._pbms_can_use_reviewer_wizards()
            rec.can_committee_review = (
                rec.category in ("manpower", "general_expense", "fixed_asset")
                and rec.state == "committee_review"
                and (user._pbms_is_budget_hiring_committee() or is_admin)
            )
            rec.can_hr_fulfill = (
                rec.category == "manpower"
                and rec.state in ("people_solutions_review", "cpco_review", "hr_fulfillment")
                and (user._pbms_is_people_solutions() or user._pbms_is_cpco() or rec._pbms_can_ho_review_plan() or is_admin)
            )
            rec.can_ceo_approve = (
                rec.category == "manpower"
                and rec.state == "ceo_approval"
                and (user._pbms_is_ceo() or is_admin)
            )
            rec.can_chief_review = (
                rec.category == "manpower"
                and rec.state == "chief_review"
                and (user._pbms_is_respective_chief() or is_admin)
            )
            rec.can_cpco_review = (
                rec.category == "manpower"
                and rec.state == "cpco_review"
                and (user._pbms_is_cpco() or is_admin)
            )
            rec.can_people_solutions_review = (
                rec.category == "manpower"
                and rec.state == "people_solutions_review"
                and (user._pbms_is_people_solutions() or is_admin)
            )
            rec.can_ho_endorse = (
                rec.category == "manpower"
                and rec.state == "ho_endorse"
                and (user._pbms_is_ho_reviewer() or rec._pbms_can_ho_review_plan() or is_admin)
            )
            rec.can_cpco_endorse = (
                rec.category == "manpower"
                and rec.state == "cpco_endorse"
                and (user._pbms_is_cpco() or is_admin)
            )

            # Sourcing fields visibility:
            # Sourcing fulfillment is made by People Solutions Directorate.
            # Visible to: People Solutions Directorate, CPCO, Budget Hiring Committee, CEO, HO Functional Reviewer, Admin.
            # Hidden from: branch/HO user, district reviewer, respective chief.
            is_sourcing_privileged = (
                user._pbms_is_people_solutions()
                or user._pbms_is_cpco()
                or user._pbms_is_budget_hiring_committee()
                or user._pbms_is_ceo()
                or user._pbms_is_ho_reviewer()
                or rec._pbms_can_ho_review_plan()
                or is_admin
            )
            rec.can_view_sourcing_fields = (
                rec.category == "manpower"
                and is_sourcing_privileged
                and rec.state in (
                    "people_solutions_review",
                    "cpco_review",
                    "committee_review",
                    "hr_fulfillment",
                    "ceo_approval",
                    "ho_endorse",
                    "cpco_endorse",
                    "approved",
                )
            )

            # Sourcing fields editability:
            # - Sourcing fulfillment is made by People Solutions Directorate in people_solutions_review.
            # - CPCO is able to View and Edit in cpco_review (and perform all other CPCO actions).
            # - Budget Hiring Committee in committee_review.
            # - CEO in ceo_approval.
            rec.can_edit_sourcing_fields = (
                rec.category == "manpower"
                and (
                    (rec.state == "people_solutions_review" and (user._pbms_is_people_solutions() or is_admin))
                    or (rec.state in ("cpco_review", "hr_fulfillment") and (user._pbms_is_cpco() or is_admin))
                    or (rec.state == "committee_review" and (user._pbms_is_budget_hiring_committee() or is_admin))
                    or (rec.state == "ceo_approval" and (user._pbms_is_ceo() or is_admin))
                )
            )

            # Administrator has permission to add lines in editable states
            if is_admin:
                rec.can_add_lines = rec.state in PBMS_BRANCH_EDITABLE_STATES
            # District Reviewer and Head Office Reviewer CANNOT add lines (they can only edit lines created by branch)
            elif user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer():
                rec.can_add_lines = False
            elif rec.org_unit_type == "district_office" and rec.category in ("deposit", "customer_base", "fx", "digital_banking"):
                rec.can_add_lines = False
            elif rec.org_unit_type == "head_office" and rec.category in ("deposit", "customer_base", "fx", "digital_banking"):
                rec.can_add_lines = False
            elif user._pbms_is_sppmd_approver() and not is_admin:
                rec.can_add_lines = False
            elif rec.state in PBMS_BRANCH_EDITABLE_STATES and rec._is_own_operating_unit_plan():
                rec.can_add_lines = bool(rec.cycle_id and rec.cycle_id.state == "open")
            else:
                rec.can_add_lines = False

    @api.depends("org_unit_id", "org_unit_id.work_unit_type", "category", "org_unit_type", "is_planning_request")
    def _compute_eligibility(self):
        Config = self.env["pbms.planning.config"]
        MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking"}
        RESOURCE_CATS = {"manpower", "general_expense", "fixed_asset"}

        CATEGORY_TOGGLE_MAP = [
            ("deposit", "enable_deposit"),
            ("customer_base", "enable_customer_base"),
            ("fx", "enable_fx"),
            ("digital_banking", "enable_digital_banking"),
            ("general_expense", "enable_expense"),
            ("manpower", "enable_manpower"),
            ("fixed_asset", "enable_fixed_asset"),
        ]

        user = self.env.user
        is_branch_user = (
            user._pbms_is_branch_user()
            and not user._pbms_is_district_reviewer()
            and not user._pbms_is_ho_reviewer()
            and not user._pbms_is_sppmd_approver()
            and not user._pbms_is_sppmd_admin()
        )

        for rec in self:
            if rec.is_planning_request:
                # In Planning Request workspace: all configured categories enabled for this work unit are displayed (unified form)
                if rec.org_unit_id:
                    for cat, toggle in CATEGORY_TOGGLE_MAP:
                        rec[toggle] = Config.is_category_enabled(cat, rec.org_unit_id)
                else:
                    for _cat, toggle in CATEGORY_TOGGLE_MAP:
                        rec[toggle] = True
            elif rec.category:
                # Dedicated category card (branch, district office, head office): STRICT isolation to this category only,
                # but ONLY if this category is actually enabled in Planning Configuration for this operating unit!
                is_enabled = Config.is_category_enabled(rec.category, rec.org_unit_id) if (Config and rec.org_unit_id) else True
                for cat, toggle in CATEGORY_TOGGLE_MAP:
                    rec[toggle] = (cat == rec.category) and is_enabled
            elif rec.org_unit_id:
                for cat, toggle in CATEGORY_TOGGLE_MAP:
                    rec[toggle] = Config.is_category_enabled(cat, rec.org_unit_id)
            else:
                for _cat, toggle in CATEGORY_TOGGLE_MAP:
                    rec[toggle] = True

    @api.depends("org_unit_id", "org_unit_id.work_unit_type")
    def _compute_measurement_types(self):
        Config = self.env["pbms.planning.config"]
        for rec in self:
            rec.deposit_measurement_type = Config.get_measurement_type("deposit", org_unit=rec.org_unit_id)
            rec.customer_base_measurement_type = Config.get_measurement_type("customer_base", org_unit=rec.org_unit_id)
            rec.fx_measurement_type = Config.get_measurement_type("fx", org_unit=rec.org_unit_id)
            rec.digital_banking_measurement_type = Config.get_measurement_type("digital_banking", org_unit=rec.org_unit_id)
            rec.expense_measurement_type = Config.get_measurement_type("general_expense", org_unit=rec.org_unit_id)
            rec.manpower_measurement_type = Config.get_measurement_type("manpower", org_unit=rec.org_unit_id)
            rec.fixed_asset_measurement_type = Config.get_measurement_type("fixed_asset", org_unit=rec.org_unit_id)

            rec.is_deposit_monetary = (rec.deposit_measurement_type == "monetary")
            rec.is_customer_base_monetary = (rec.customer_base_measurement_type == "monetary")
            rec.is_fx_monetary = (rec.fx_measurement_type == "monetary")
            rec.is_digital_banking_monetary = (rec.digital_banking_measurement_type == "monetary")
            rec.is_fixed_asset_monetary = (rec.fixed_asset_measurement_type == "monetary")

            if rec.category == "customer_base":
                rec.is_category_monetary = rec.is_customer_base_monetary
            elif rec.category == "digital_banking":
                rec.is_category_monetary = rec.is_digital_banking_monetary
            elif rec.category == "fx":
                rec.is_category_monetary = rec.is_fx_monetary
            else:
                rec.is_category_monetary = True

    is_category_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)
    is_planning_request = fields.Boolean(
        string="Is Planning Request Context",
        compute="_compute_is_planning_request",
        store=False,
    )

    def _compute_is_planning_request(self):
        is_req = bool(self.env.context.get("is_planning_request"))
        for rec in self:
            rec.is_planning_request = is_req

    # Consolidation Stat Counts
    branch_plan_count = fields.Integer(
        string="Branch Plans", compute="_compute_consolidation_counts",
    )
    district_plan_count = fields.Integer(
        string="District Plans", compute="_compute_consolidation_counts",
    )

    def _compute_consolidation_counts(self):
        for rec in self:
            if rec.org_unit_type in ("district_office", "head_office"):
                rec.district_plan_count = self.search_count([
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("org_unit_type", "=", "district_office"),
                    ("active", "=", True),
                ])
            else:
                rec.district_plan_count = 0

            if rec.org_unit_type == "district_office":
                rec.branch_plan_count = self.search_count([
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("district_id", "=", rec.org_unit_id.id),
                    ("org_unit_id", "!=", rec.org_unit_id.id),
                    ("active", "=", True),
                ])
            else:
                rec.branch_plan_count = 0

    # Permanent Review Comments and Audit Trail
    review_comment_ids = fields.One2many(
        "pbms.review.comment",
        "plan_id",
        string="Review History & Audit Trail",
        readonly=True,
    )

    category = fields.Selection(
        [
            ("deposit", "Deposit Mobilization"),
            ("customer_base", "Customer Base"),
            ("fx", "FX Mobilization"),
            ("digital_banking", "Digital Banking"),
            ("general_expense", "General Expense"),
            ("manpower", "work Force"),
            ("fixed_asset", "Fixed Asset Requirement"),
        ],
        string="Planning Category",
        compute="_compute_category",
        store=True,
        readonly=False,
        index=True,
        tracking=True,
        help="The planning category this line belongs to.",
    )

    @api.depends("line_ids.line_type", "manpower_line_ids", "deposit_line_ids", "customer_base_line_ids", "fx_line_ids", "digital_banking_line_ids", "expense_line_ids", "fixed_asset_line_ids", "org_unit_id")
    def _compute_category(self):
        Config = self.env.get("pbms.planning.config")
        for rec in self:
            is_valid_category = False
            if rec.category and rec.org_unit_id and Config is not None:
                is_valid_category = Config.is_category_enabled(rec.category, rec.org_unit_id)
            elif rec.category:
                is_valid_category = True

            present_line_types = []
            if rec.line_ids:
                for l in rec.line_ids:
                    lt = l.line_type
                    if lt and lt not in present_line_types:
                        present_line_types.append(lt)

            if present_line_types:
                if not rec.category or rec.category not in present_line_types or not is_valid_category:
                    rec.category = present_line_types[0]
            elif not rec.category or not is_valid_category:
                if Config is not None and rec.org_unit_id:
                    rec.category = Config.get_default_category_for_unit(rec.org_unit_id)
                else:
                    rec.category = "deposit"

            if rec.category == "manpower" and rec.request_number and not rec.request_number.startswith("WFP/"):
                rec.request_number = (
                    rec.env["ir.sequence"].next_by_code("pbms.workforce.request")
                    or f"WFP/{fields.Date.today().year}/{rec.id:05d}"
                )
            elif rec.category and rec.category != "manpower" and rec.request_number and rec.request_number.startswith("WFP/"):
                rec.request_number = (
                    rec.env["ir.sequence"].next_by_code("pbms.planning.request")
                    or f"REQ/{fields.Date.today().year}/{rec.id:05d}"
                )

    def _realign_lines_to_matching_cards(self, plans=None):
        """Ensure each requirement line is attached directly to the specific plan card matching its category."""
        try:
            CategoryPlan = self.env["pbms.planning.category"].sudo()
            Line = self.env["pbms.plan.category.line"].sudo()

            target_plans = plans or (self if self else CategoryPlan.search([("active", "=", True)]))
            affected_plans = CategoryPlan

            for plan in target_plans:
                if not plan.line_ids:
                    continue
                org_unit_id = plan.org_unit_id.id if plan.org_unit_id else False
                cycle_id = plan.cycle_id.id if plan.cycle_id else False
                if not org_unit_id or not cycle_id:
                    continue

                affected_plans |= plan
                present_types = list(dict.fromkeys(l.line_type for l in plan.line_ids if l.line_type))

                # If the plan has NO lines matching its own category, but has lines of another single category,
                # update this plan's category directly rather than creating a new card and leaving an empty one.
                if plan.category not in present_types and len(present_types) == 1:
                    new_cat = present_types[0]
                    write_vals = {"category": new_cat}
                    if new_cat == "manpower" and (not plan.request_number or not plan.request_number.startswith("WFP/")):
                        seq = (
                            self.env["ir.sequence"].next_by_code("pbms.workforce.request")
                            or f"WFP/{fields.Date.today().year}/{plan.id:05d}"
                        )
                        write_vals["request_number"] = seq
                    elif new_cat != "manpower" and plan.request_number and plan.request_number.startswith("WFP/"):
                        seq = (
                            self.env["ir.sequence"].next_by_code("pbms.planning.request")
                            or f"REQ/{fields.Date.today().year}/{plan.id:05d}"
                        )
                        write_vals["request_number"] = seq
                    plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write(write_vals)
                    continue

                # For lines that don't match the plan's category:
                for line in plan.line_ids:
                    if not line.line_type or line.line_type == plan.category:
                        continue

                    target_card = CategoryPlan.search([
                        ("org_unit_id", "=", org_unit_id),
                        ("cycle_id", "=", cycle_id),
                        ("category", "=", line.line_type),
                        ("active", "=", True),
                    ], limit=1)
                    if not target_card:
                        vals = {
                            "org_unit_id": org_unit_id,
                            "cycle_id": cycle_id,
                            "company_id": plan.company_id.id if plan.company_id else self.env.company.id,
                            "category": line.line_type,
                            "state": plan.state,
                            "submitted_by": plan.submitted_by.id if plan.submitted_by else self.env.uid,
                            "submitted_date": plan.submitted_date or fields.Datetime.now(),
                        }
                        target_card = CategoryPlan.with_context(skip_sync_category_records=True, bypass_plan_lock=True).create(vals)
                    affected_plans |= target_card
                    line.with_context(bypass_plan_lock=True).write({"plan_id": target_card.id})

            # If re-aligning lines leaves behind an empty plan whose category is disabled in config, unlink or archive it
            target_plans.invalidate_recordset(["line_ids"])
            Config = self.env.get("pbms.planning.config")
            for p in target_plans:
                p_lines = p.line_ids
                if not p_lines and p.org_unit_id and p.category:
                    if Config is not None and not Config.is_category_enabled(p.category, p.org_unit_id) and p.state in ("draft", "returned", "info_requested"):
                        try:
                            p.with_context(bypass_plan_lock=True).unlink()
                        except Exception:
                            p.with_context(bypass_plan_lock=True).write({"active": False})

            for p in affected_plans:
                if hasattr(p, "_compute_totals"):
                    p._compute_totals()
                if hasattr(p, "_compute_category_summaries"):
                    p._compute_category_summaries()
                if hasattr(p, "_compute_kanban_breakdown_html"):
                    p._compute_kanban_breakdown_html()
                if hasattr(p, "_compute_plan_notification_details"):
                    p._compute_plan_notification_details()
        except Exception:
            pass

    @api.model
    def _realign_lines_to_category_cards(self):
        """Ensure each requirement line is attached directly to the specific plan card matching its category."""
        return self._realign_lines_to_matching_cards()




    @api.model
    @api.model
    def _cleanup_duplicate_district_cards(self):
        """Clean up redundant duplicate category cards for the exact same operating unit and category."""
        CategoryPlan = self.sudo()
        Line = self.env["pbms.plan.category.line"].sudo()

        plans = CategoryPlan.search([("active", "=", True)])
        grouped = {}
        for p in plans:
            if not p.org_unit_id or not p.cycle_id or not p.category:
                continue
            key = (p.org_unit_id.id, p.cycle_id.id, p.category)
            grouped.setdefault(key, self.env["pbms.planning.category"])
            grouped[key] |= p

        for (unit_id, cycle_id, cat), cat_plans in grouped.items():
            if len(cat_plans) > 1:
                # Prefer plan with submitted or approved state, or most lines
                primary_card = cat_plans.sorted(key=lambda p: (1 if p.state not in ('draft', 'returned') else 0, len(p.line_ids)), reverse=True)[:1]
                redundant = cat_plans - primary_card
                for r in redundant:
                    r_lines = Line.search([("plan_id", "=", r.id)])
                    if r_lines:
                        # Only transfer lines matching this category
                        match_lines = r_lines.filtered(lambda l: l.line_type == cat)
                        if match_lines:
                            match_lines.with_context(bypass_plan_lock=True).write({"plan_id": primary_card.id})
                    r.with_context(bypass_plan_lock=True).write({"active": False})
                primary_card._compute_totals()
                primary_card._compute_category_summaries()
                primary_card._compute_kanban_breakdown_html()

    def _sync_category_records(self):
        """Ensure each line is attached to the card matching its specific category."""
        if self.env.context.get("skip_sync_category_records"):
            return

        Line = self.env["pbms.plan.category.line"].sudo()
        CategoryPlan = self.sudo()

        for rec in self:
            if not rec.cycle_id or not rec.org_unit_id or not rec.category:
                continue

            # Ensure any lines of this category for this unit & cycle are attached to this card
            detached = Line.search([
                ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                ("plan_id.cycle_id", "=", rec.cycle_id.id),
                ("line_type", "=", rec.category),
                ("plan_id", "!=", rec.id),
            ])
            if detached:
                detached = detached.filtered(lambda l: getattr(l.plan_id, "is_planning_request", False) or l.plan_id.category != rec.category)
                if detached:
                    detached.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": rec.id})









    @api.model
    def _cleanup_duplicate_copied_lines(self):
        """Clean up any orphan/duplicate lines created by prior sync runs."""

        try:
            mp_lines = self.env["pbms.plan.category.line"].search([("line_type", "=", "manpower")])
            seen = {}
            to_delete = self.env["pbms.plan.category.line"]
            for l in mp_lines:
                if not l.plan_id:
                    to_delete |= l
                    continue
                key = (
                    l.plan_id.org_unit_id.id,
                    l.plan_id.cycle_id.id,
                    l.job_id.id if l.job_id else l.new_job_title,
                    l.position_type_id.id if l.position_type_id else l.position_type,
                )
                if key in seen:
                    existing = seen[key]
                    if l.plan_id.category == "manpower" and existing.plan_id.category != "manpower":
                        to_delete |= existing
                        seen[key] = l
                    else:
                        to_delete |= l
                else:
                    seen[key] = l
            if to_delete:
                to_delete.sudo().unlink()
        except Exception:
            pass

    @api.model
    def _sync_all_category_records(self):
        """Scan active plans and synchronize category plan cards."""
        self._cleanup_duplicate_copied_lines()
        all_plans = self.search([("active", "=", True)])
        for p in all_plans:
            p._sync_category_records()

    # Backwards compatibility alias
    def _split_mixed_lines(self):
        return self._sync_category_records()

    @api.model
    def _split_all_mixed_records(self):
        return self._sync_all_category_records()








    # ---- Category-specific identifiers ----
    deposit_type_id = fields.Many2one(
        "pbms.deposit.type", string="Deposit Type", index=True, tracking=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )
    plan_category = fields.Selection(
        [("amount", "Amount")],
        string="Plan Basis", index=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )
    base_type = fields.Selection(
        [("new_acquisition", "New Customer Acquisition"),
         ("dormant_reduction", "Dormant Account Reduction"),
         ("both", "New Acquisition & Dormant Reduction")],
        string="Base Type", index=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )
    fx_source_type = fields.Many2one(
        "pbms.fx.source.type", string="FX Source", index=True, tracking=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )
    channel_id = fields.Many2one(
        "pbms.digital.channel", string="Digital Channel", index=True, tracking=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )
    expense_account_id = fields.Many2one(
        "pbms.expense.account", string="Expense Account", index=True, tracking=True,
        compute="_compute_category_specific_fields", store=True, readonly=False,
    )

    @api.depends(
        "category",
        "deposit_line_ids.deposit_type_id",
        "customer_base_line_ids.deposit_type_id",
        "customer_base_line_ids.base_type",
        "fx_line_ids.fx_source_type",
        "digital_banking_line_ids.channel_id",
        "expense_line_ids.expense_account_id",
        "manpower_line_ids.justification_category_id",
        "line_ids.deposit_type_id",
        "line_ids.base_type",
        "line_ids.fx_source_type",
        "line_ids.channel_id",
        "line_ids.expense_account_id",
        "line_ids.justification_category_id",
    )
    def _compute_category_specific_fields(self):
        for rec in self:
            cat = rec.category
            lines = rec.line_ids

            # 1. Customer Base
            if cat == "customer_base":
                cb_lines = rec.customer_base_line_ids or lines.filtered(lambda l: l.line_type == "customer_base")
                btypes = [b for b in cb_lines.mapped("base_type") if b]
                unique_btypes = sorted(set(btypes))
                if len(unique_btypes) == 1:
                    rec.base_type = unique_btypes[0]
                elif len(unique_btypes) > 1:
                    rec.base_type = "both"
                elif not rec.base_type:
                    rec.base_type = "new_acquisition"

                dep_types = cb_lines.mapped("deposit_type_id").filtered(lambda d: d.exists())
                rec.deposit_type_id = dep_types[:1].id if dep_types else False
                rec.plan_category = False
            else:
                rec.base_type = False

            # 2. FX
            if cat == "fx":
                fx_lines = rec.fx_line_ids or lines.filtered(lambda l: l.line_type == "fx")
                fx_sources = fx_lines.mapped("fx_source_type").filtered(lambda s: s.exists())
                rec.fx_source_type = fx_sources[:1].id if fx_sources else False
            else:
                rec.fx_source_type = False

            # 3. Deposit
            if cat == "deposit":
                dep_lines = rec.deposit_line_ids or lines.filtered(lambda l: l.line_type == "deposit")
                dep_types = dep_lines.mapped("deposit_type_id").filtered(lambda d: d.exists())
                rec.deposit_type_id = dep_types[:1].id if dep_types else False
                rec.plan_category = "amount"
            elif cat != "customer_base":
                rec.deposit_type_id = False
                rec.plan_category = False

            # 4. Digital Banking
            if cat == "digital_banking":
                db_lines = rec.digital_banking_line_ids or lines.filtered(lambda l: l.line_type == "digital_banking")
                channels = db_lines.mapped("channel_id").filtered(lambda c: c.exists())
                rec.channel_id = channels[:1].id if channels else False
            else:
                rec.channel_id = False

            # 5. General Expense
            if cat == "general_expense":
                exp_lines = rec.expense_line_ids or lines.filtered(lambda l: l.line_type == "general_expense")
                accounts = exp_lines.mapped("expense_account_id").filtered(lambda a: a.exists())
                rec.expense_account_id = accounts[:1].id if accounts else False
            else:
                rec.expense_account_id = False

            # 6. Manpower Justification
            if cat == "manpower":
                mp_lines = rec.manpower_line_ids or lines.filtered(lambda l: l.line_type == "manpower")
                jcats = mp_lines.mapped("justification_category_id").filtered(lambda j: j.exists())
                if jcats:
                    rec.justification_category_id = jcats[:1].id
                elif mp_lines:
                    rec.justification_category_id = False
                elif not rec.justification_category_id:
                    rec.justification_category_id = False
            else:
                rec.justification_category_id = False

    fx_source_type_domain = fields.Char(compute="_compute_fx_source_type_domain", store=False)

    @api.depends("org_unit_id")
    def _compute_fx_source_type_domain(self):
        import json
        Config = self.env["pbms.planning.config"]
        for plan in self:
            config = Config.get_config_for_unit(plan.org_unit_id) if plan.org_unit_id else False
            if config and config.fx_source_type_ids:
                plan.fx_source_type_domain = json.dumps([("id", "in", config.fx_source_type_ids.ids)])
            else:
                plan.fx_source_type_domain = json.dumps([("active", "=", True)])
    fx_currency_id = fields.Many2one(
        "res.currency", string="FX Planning Currency",
        compute="_compute_fx_currency", store=True, readonly=False,
        help="Currency for Foreign Exchange (FX) Mobilization targets.",
    )

    @api.depends("org_unit_id", "category")
    def _compute_fx_currency(self):
        Config = self.env["pbms.planning.config"]
        for rec in self:
            rec.fx_currency_id = Config.get_category_currency("fx", org_unit=rec.org_unit_id)
            if rec.category == "fx" and rec.fx_currency_id:
                rec.currency_id = rec.fx_currency_id
    prior_year_actual = fields.Monetary(
        string="End Period Actual Performance",
        currency_field="currency_id",
        help="Prior period actual expense.",
    )
    is_office_rent = fields.Boolean(
        string="Office Rent",
        help="Flags office-rent lines.",
    )

    # ---- Outstanding Balance ----
    outstanding_balance_end_period = fields.Monetary(
        string="Outstanding Balance (End Period)",
        currency_field="currency_id",
        compute="_compute_outstanding_balance",
        store=True,
        help="Cumulative outstanding balance at the end of the period.",
    )
    position_type = fields.Selection(
        [
            ("new", "New Position"),
            ("existing", "Existing Position"),
            ("replacement", "Replacement")
        ],
        string="Position Type",
        default="new",
    )
    employment_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("contract", "Contract"),
            ("temporary", "Temporary")
        ],
        string="Employment Type",
        default="permanent",
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        index=True,
    )
    @api.depends("opening_balance", "line_ids.opening_balance", "line_ids.outstanding_year_end", *MONTH_FIELDS)
    def _compute_outstanding_balance(self):
        for rec in self:
            if rec.line_ids and rec.category not in ('manpower', 'fixed_asset'):
                rec.opening_balance = sum(rec.line_ids.mapped('opening_balance'))
                rec.outstanding_balance_end_period = sum(rec.line_ids.mapped('outstanding_year_end'))
            else:
                balance = rec.opening_balance or 0.0
                for month in MONTH_FIELDS:
                    balance += (getattr(rec, month) or 0.0)
                rec.outstanding_balance_end_period = balance

    # ---- Itemized categories ----
    line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id", string="Requirement Lines",
    )
    line_count = fields.Integer(compute="_compute_line_count", store=True)

    broad_category = fields.Char(
        string="Broad Category",
        compute="_compute_broad_category",
        store=True,
        index=True,
    )

    @api.depends("org_unit_id", "org_unit_id.work_unit_type", "org_unit_type")
    def _compute_broad_category(self):
        for rec in self:
            wtype = rec.org_unit_type or (rec.org_unit_id.work_unit_type if rec.org_unit_id else False)
            if wtype in ("branch", "sub_branch", "service_center"):
                rec.broad_category = "1.Branches"
            elif wtype in ("district_office", "regional_office"):
                rec.broad_category = "2.District Office"
            elif wtype == "head_office":
                rec.broad_category = "3.Head Office"
            else:
                rec.broad_category = "1.Branches"

    # Dedicated category line relations for tabbed planning request view
    deposit_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="Deposit Lines",
        domain=[("line_type", "=", "deposit")],
        context={"default_line_type": "deposit"},
    )
    customer_base_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="Customer Base Lines",
        domain=[("line_type", "=", "customer_base")],
        context={"default_line_type": "customer_base"},
    )
    fx_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="FX Mobilization Lines",
        domain=[("line_type", "=", "fx")],
        context={"default_line_type": "fx"},
    )
    digital_banking_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="Digital Banking Lines",
        domain=[("line_type", "=", "digital_banking")],
        context={"default_line_type": "digital_banking"},
    )
    expense_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="General Expense Lines",
        domain=[("line_type", "=", "general_expense")],
        context={"default_line_type": "general_expense"},
    )
    manpower_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="Manpower Lines",
        domain=[("line_type", "=", "manpower")],
        context={"default_line_type": "manpower"},
    )
    fixed_asset_line_ids = fields.One2many(
        "pbms.plan.category.line", "plan_id",
        string="Fixed Asset Lines",
        domain=[("line_type", "=", "fixed_asset")],
        context={"default_line_type": "fixed_asset"},
    )

    # Dynamic dropdown exclusion fields (evaluated real-time on client before saving)
    available_deposit_type_ids = fields.Many2many(
        "pbms.deposit.type", compute="_compute_available_dropdown_options", store=False,
    )
    used_deposit_type_ids = fields.Many2many(
        "pbms.deposit.type", compute="_compute_used_dropdown_options", store=False,
    )
    used_customer_base_deposit_type_ids = fields.Many2many(
        "pbms.deposit.type", compute="_compute_used_dropdown_options", store=False,
    )

    available_channel_ids = fields.Many2many(
        "pbms.digital.channel", compute="_compute_available_dropdown_options", store=False,
    )
    used_channel_ids = fields.Many2many(
        "pbms.digital.channel", compute="_compute_used_dropdown_options", store=False,
    )

    available_fx_source_type_ids = fields.Many2many(
        "pbms.fx.source.type", compute="_compute_available_dropdown_options", store=False,
    )
    used_fx_source_type_ids = fields.Many2many(
        "pbms.fx.source.type", compute="_compute_used_dropdown_options", store=False,
    )

    available_expense_account_ids = fields.Many2many(
        "pbms.expense.account", compute="_compute_available_dropdown_options", store=False,
    )
    used_expense_account_ids = fields.Many2many(
        "pbms.expense.account", compute="_compute_used_dropdown_options", store=False,
    )

    available_fa_category_ids = fields.Many2many(
        "pbms.fixed.asset.category", compute="_compute_available_dropdown_options", store=False,
    )
    used_fa_category_ids = fields.Many2many(
        "pbms.fixed.asset.category", compute="_compute_used_dropdown_options", store=False,
    )

    available_position_type_ids = fields.Many2many(
        "pbms.position.type", compute="_compute_available_dropdown_options", store=False,
    )
    available_job_ids = fields.Many2many(
        "hr.job", compute="_compute_available_dropdown_options", store=False,
    )

    @api.depends("org_unit_id", "org_unit_id.work_unit_type")
    def _compute_available_dropdown_options(self):
        Config = self.env["pbms.planning.config"]
        for plan in self:
            config = False
            if plan.org_unit_id:
                config = Config.get_config_for_unit(plan.org_unit_id)
            elif plan.org_unit_id and plan.org_unit_id.work_unit_type:
                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            # Deposit / Customer Base
            if config and config.deposit_type_ids:
                plan.available_deposit_type_ids = config.deposit_type_ids
            else:
                plan.available_deposit_type_ids = self.env["pbms.deposit.type"].search([("active", "=", True)])

            # Digital Banking
            if config and config.digital_channel_ids:
                plan.available_channel_ids = config.digital_channel_ids
            else:
                plan.available_channel_ids = self.env["pbms.digital.channel"].search([("active", "=", True)])

            # FX
            if config and config.fx_source_type_ids:
                plan.available_fx_source_type_ids = config.fx_source_type_ids
            else:
                plan.available_fx_source_type_ids = self.env["pbms.fx.source.type"].search([("active", "=", True)])

            # General Expense
            if config and config.expense_account_ids:
                plan.available_expense_account_ids = config.expense_account_ids
            else:
                plan.available_expense_account_ids = self.env["pbms.expense.account"].search([("active", "=", True)])

            # Fixed Asset
            if config and config.fixed_asset_category_ids:
                plan.available_fa_category_ids = config.fixed_asset_category_ids
            else:
                plan.available_fa_category_ids = self.env["pbms.fixed.asset.category"].search([("active", "=", True)])

            # Manpower Position Types
            if config and config.position_type_ids:
                plan.available_position_type_ids = config.position_type_ids
            else:
                plan.available_position_type_ids = self.env["pbms.position.type"].search([("active", "=", True)])

            # Active Job Positions for Operating Unit
            job_ids = set()
            if plan.org_unit_id:
                if "operating.unit.job.position" in self.env:
                    ou_positions = self.env["operating.unit.job.position"].search([
                        ("operating_unit_id", "=", plan.org_unit_id.id),
                        ("active", "=", True),
                    ])
                    job_ids.update(ou_positions.mapped("job_position_id.id"))
                if "hr.employee" in self.env:
                    emp_domain = [
                        ("active", "=", True),
                        "|",
                        ("operating_unit_ids", "in", [plan.org_unit_id.id]),
                        ("default_operating_unit_id", "=", plan.org_unit_id.id),
                    ]
                    employees = self.env["hr.employee"].search(emp_domain)
                    for emp in employees:
                        j = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
                        if j:
                            job_ids.add(j.id)

            if job_ids:
                plan.available_job_ids = self.env["hr.job"].browse(list(job_ids))
            else:
                plan.available_job_ids = self.env["hr.job"].search([("active", "=", True)])

    @api.depends(
        "deposit_line_ids.deposit_type_id",
        "customer_base_line_ids.deposit_type_id",
        "digital_banking_line_ids.channel_id",
        "fx_line_ids.fx_source_type",
        "expense_line_ids.expense_account_id",
        "fixed_asset_line_ids.category_id",
    )
    def _compute_used_dropdown_options(self):
        for plan in self:
            if plan.org_unit_type in ("district_office", "head_office"):
                plan.used_deposit_type_ids = False
                plan.used_customer_base_deposit_type_ids = False
                plan.used_channel_ids = False
                plan.used_fx_source_type_ids = False
                plan.used_expense_account_ids = False
                plan.used_fa_category_ids = False
            else:
                plan.used_deposit_type_ids = plan.deposit_line_ids.mapped("deposit_type_id")
                plan.used_customer_base_deposit_type_ids = plan.customer_base_line_ids.mapped("deposit_type_id")
                plan.used_channel_ids = plan.digital_banking_line_ids.mapped("channel_id")
                plan.used_fx_source_type_ids = plan.fx_line_ids.mapped("fx_source_type")
                plan.used_expense_account_ids = plan.expense_line_ids.mapped("expense_account_id")
                plan.used_fa_category_ids = plan.fixed_asset_line_ids.mapped("category_id")

    @api.onchange("deposit_line_ids", "customer_base_line_ids", "digital_banking_line_ids", "fx_line_ids", "expense_line_ids", "fixed_asset_line_ids")
    def _onchange_lines_update_used_options(self):
        if self.org_unit_type in ("district_office", "head_office"):
            self.used_deposit_type_ids = False
            self.used_customer_base_deposit_type_ids = False
            self.used_channel_ids = False
            self.used_fx_source_type_ids = False
            self.used_expense_account_ids = False
            self.used_fa_category_ids = False
        else:
            self.used_deposit_type_ids = self.deposit_line_ids.mapped("deposit_type_id")
            self.used_customer_base_deposit_type_ids = self.customer_base_line_ids.mapped("deposit_type_id")
            self.used_channel_ids = self.digital_banking_line_ids.mapped("channel_id")
            self.used_fx_source_type_ids = self.fx_line_ids.mapped("fx_source_type")
            self.used_expense_account_ids = self.expense_line_ids.mapped("expense_account_id")
            self.used_fa_category_ids = self.fixed_asset_line_ids.mapped("category_id")

    @api.onchange("category", "org_unit_id", "enable_manpower")
    def _onchange_category_and_unit(self):
        Config = self.env.get("pbms.planning.config")
        for rec in self:
            if rec.org_unit_id and Config is not None:
                if not rec.category or not Config.is_category_enabled(rec.category, rec.org_unit_id):
                    rec.category = Config.get_default_category_for_unit(rec.org_unit_id)
            if (rec.category == "manpower" or rec.enable_manpower) and rec.org_unit_id and not rec.existing_manpower_summary_ids:
                rec._sync_existing_manpower_lines()

    # Category summaries per tab (Plan Overview & Quarterly Rollup)
    has_cascaded_targets = fields.Boolean(
        compute="_compute_has_cascaded_targets", store=True, string="Has Cascaded Targets",
    )
    deposit_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    deposit_annual_total = fields.Float(compute="_compute_category_summaries", store=True)
    deposit_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Deposit Target")
    deposit_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Deposit Target")
    deposit_q1_total = fields.Float(compute="_compute_category_summaries", store=True)
    deposit_q2_total = fields.Float(compute="_compute_category_summaries", store=True)
    deposit_q3_total = fields.Float(compute="_compute_category_summaries", store=True)
    deposit_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    customer_base_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    customer_base_annual_total = fields.Float(compute="_compute_category_summaries", store=True)
    customer_base_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Customer Base")
    customer_base_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Customer Base")
    customer_base_q1_total = fields.Float(compute="_compute_category_summaries", store=True)
    customer_base_q2_total = fields.Float(compute="_compute_category_summaries", store=True)
    customer_base_q3_total = fields.Float(compute="_compute_category_summaries", store=True)
    customer_base_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    fx_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    fx_annual_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")
    fx_proposed_total = fields.Monetary(compute="_compute_category_summaries", store=True, string="Proposed FX Target", currency_field="fx_currency_id")
    fx_approved_total = fields.Monetary(compute="_compute_category_summaries", store=True, string="Approved FX Target", currency_field="fx_currency_id")
    fx_q1_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")
    fx_q2_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")
    fx_q3_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")
    fx_q4_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")

    digital_banking_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    digital_banking_annual_total = fields.Float(compute="_compute_category_summaries", store=True)
    digital_banking_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Digital Target")
    digital_banking_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Digital Target")
    digital_banking_q1_total = fields.Float(compute="_compute_category_summaries", store=True)
    digital_banking_q2_total = fields.Float(compute="_compute_category_summaries", store=True)
    digital_banking_q3_total = fields.Float(compute="_compute_category_summaries", store=True)
    digital_banking_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    expense_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    expense_annual_total = fields.Float(compute="_compute_category_summaries", store=True)
    expense_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Expense Budget")
    expense_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Expense Budget")
    expense_q1_total = fields.Float(compute="_compute_category_summaries", store=True)
    expense_q2_total = fields.Float(compute="_compute_category_summaries", store=True)
    expense_q3_total = fields.Float(compute="_compute_category_summaries", store=True)
    expense_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    manpower_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    manpower_total_headcount = fields.Integer(compute="_compute_category_summaries", store=True, string="Total Requested Headcount")
    manpower_approved_headcount = fields.Integer(compute="_compute_category_summaries", store=True, string="Committee Approved Headcount")
    manpower_total_promotion = fields.Integer(compute="_compute_category_summaries", store=True, string="Sourced via Promotion")
    manpower_total_transfer = fields.Integer(compute="_compute_category_summaries", store=True, string="Sourced via Transfer")
    manpower_total_lateral = fields.Integer(compute="_compute_category_summaries", store=True, string="Sourced via Lateral")
    manpower_total_external = fields.Integer(compute="_compute_category_summaries", store=True, string="Sourced via External Vacancy")
    manpower_total_fulfillment = fields.Integer(compute="_compute_category_summaries", store=True, string="Total Headcount Sourced")
    manpower_fulfillment_balance = fields.Integer(compute="_compute_category_summaries", store=True, string="Sourcing Balance")
    manpower_needs_ceo_approval = fields.Boolean(compute="_compute_category_summaries", store=True, string="Needs CEO Approval")
    fixed_asset_line_count = fields.Integer(compute="_compute_category_summaries", store=True)
    fixed_asset_total_quantity = fields.Integer(compute="_compute_category_summaries", store=True, string="Total Fixed Asset Quantity")
    fixed_asset_approved_total = fields.Monetary(compute="_compute_category_summaries", store=True, string="Total Approved Fixed Asset Cost", currency_field="currency_id")
    fixed_asset_approved_quantity = fields.Integer(compute="_compute_category_summaries", store=True, string="Total Approved Fixed Asset Items")

    # Fixed Asset total - using fa_annual_total_cost instead of estimated_total_price
    total_estimated_amount = fields.Monetary(
        compute="_compute_total_estimated_amount",
        store=True,
        index=True,
        currency_field="currency_id",
        help="Fixed Asset estimated total across request lines.",
    )

    total_manpower_cost = fields.Monetary(
        compute="_compute_total_manpower_cost",
        store=True,
        currency_field="currency_id",
        help="Total manpower cost across all lines.",
    )
    current_staff_salary_budget = fields.Monetary(
        compute="_compute_operating_unit_manpower_budget",
        store=True,
        currency_field="currency_id",
        string="Current Staff Salary Budget",
        help="Total current annual salary from active employee contracts (hr.version / hr.contract) for this operating unit.",
    )
    new_planned_salary_budget = fields.Monetary(
        compute="_compute_operating_unit_manpower_budget",
        store=True,
        currency_field="currency_id",
        string="New Planned Salary Budget",
        help="Total annual salary cost for new planned positions based on hr_employee_grade.",
    )
    total_operating_unit_manpower_budget = fields.Monetary(
        compute="_compute_operating_unit_manpower_budget",
        store=True,
        currency_field="currency_id",
        string="Total Operating Unit Workforce Budget",
        help="Combined total annual workforce budget (Current Staff Salary + New Planned Employees Salary).",
    )
    total_fixed_asset_cost = fields.Monetary(
        compute="_compute_total_fixed_asset_cost",
        store=True,
        currency_field="currency_id",
        help="Total fixed asset cost across all lines.",
    )

    # ── Existing Manpower Tab Fields ───────────────────────────────────────
    existing_manpower_summary_ids = fields.One2many(
        "pbms.existing.manpower.summary",
        "plan_id",
        string="Existing Positions Summary",
    )
    existing_employee_line_ids = fields.One2many(
        "pbms.existing.employee.line",
        "plan_id",
        string="Active Employee Roster",
    )
    existing_total_authorized = fields.Integer(
        string="Total Authorized Baseline",
        compute="_compute_existing_manpower_data",
        store=True,
    )
    existing_total_active = fields.Integer(
        string="Total Active Employees",
        compute="_compute_existing_manpower_data",
        store=True,
    )
    existing_total_vacancies = fields.Integer(
        string="Total Vacant Positions",
        compute="_compute_existing_manpower_data",
        store=True,
    )
    existing_total_monthly_salary = fields.Monetary(
        string="Total Existing Monthly Salary",
        currency_field="currency_id",
        compute="_compute_existing_manpower_data",
        store=True,
    )
    existing_total_annual_salary = fields.Monetary(
        string="Total Existing Manpower Salary in Fiscal Year",
        currency_field="currency_id",
        compute="_compute_existing_manpower_data",
        store=True,
    )

    # Manpower quarter totals
    q1_total_cost = fields.Monetary(
        compute="_compute_manpower_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q1 manpower cost",
    )
    q2_total_cost = fields.Monetary(
        compute="_compute_manpower_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q2 manpower cost",
    )
    q3_total_cost = fields.Monetary(
        compute="_compute_manpower_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q3 manpower cost",
    )
    q4_total_cost = fields.Monetary(
        compute="_compute_manpower_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q4 manpower cost",
    )

    # Fixed Asset quarter totals
    fa_q1_total_cost = fields.Monetary(
        compute="_compute_fa_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q1 fixed asset cost",
    )
    fa_q2_total_cost = fields.Monetary(
        compute="_compute_fa_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q2 fixed asset cost",
    )
    fa_q3_total_cost = fields.Monetary(
        compute="_compute_fa_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q3 fixed asset cost",
    )
    fa_q4_total_cost = fields.Monetary(
        compute="_compute_fa_quarter_totals",
        store=True,
        currency_field="currency_id",
        help="Total Q4 fixed asset cost",
    )

    # ---- Workspace back-links ----
    workspace_deposit_id = fields.Many2one("pbms.planning.workspace", string="Workspace (Deposit)", ondelete="set null")
    workspace_customer_base_id = fields.Many2one("pbms.planning.workspace", string="Workspace (Customer Base)",
                                                 ondelete="set null")
    workspace_fx_id = fields.Many2one("pbms.planning.workspace", string="Workspace (FX)", ondelete="set null")
    workspace_digital_banking_id = fields.Many2one("pbms.planning.workspace", string="Workspace (Digital Banking)",
                                                   ondelete="set null")
    workspace_expense_id = fields.Many2one("pbms.planning.workspace", string="Workspace (General Expense)",
                                           ondelete="set null")
    workspace_manpower_id = fields.Many2one("pbms.planning.workspace", string="Workspace (Manpower)",
                                            ondelete="set null")
    workspace_fixed_asset_id = fields.Many2one("pbms.planning.workspace", string="Workspace (Fixed Asset)",
                                               ondelete="set null")
    _workspace_link_field = {
        "deposit": "workspace_deposit_id",
        "customer_base": "workspace_customer_base_id",
        "fx": "workspace_fx_id",
        "digital_banking": "workspace_digital_banking_id",
        "general_expense": "workspace_expense_id",
        "manpower": "workspace_manpower_id",
        "fixed_asset": "workspace_fixed_asset_id",
    }
    _tab_line_fields = {
        "deposit": "deposit_line_ids",
        "customer_base": "customer_base_line_ids",
        "fx": "fx_line_ids",
        "digital_banking": "digital_banking_line_ids",
        "general_expense": "expense_line_ids",
        "manpower": "manpower_line_ids",
        "fixed_asset": "fixed_asset_line_ids",
    }

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    kanban_breakdown_html = fields.Html(
        string="Kanban Breakdown HTML",
        compute="_compute_kanban_breakdown_html",
        store=False,
        exportable=False,
    )

    plan_category_badge_html = fields.Html(
        string="Category Badge",
        compute="_compute_plan_category_badge_html",
        store=False,
        exportable=False,
    )

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        NON_EXPORTABLE_FIELDS = {
            # HTML and Badges
            "kanban_breakdown_html", "plan_category_badge_html",
            # Activities & Chatter technical metadata
            "activity_ids", "activity_state", "activity_user_id", "activity_type_id",
            "activity_date_deadline", "activity_summary", "activity_exception_decoration",
            "activity_exception_icon", "activity_type_icon",
            "message_ids", "message_follower_ids", "message_partner_ids", "message_channel_ids",
            "message_needaction", "message_has_error", "message_has_sms_error",
            "message_attachment_count", "message_main_attachment_id", "website_message_ids", "has_message",
            # UI Domains & Dynamic Dropdowns
            "deposit_type_domain", "channel_domain", "expense_account_domain",
            "fa_category_domain", "justification_category_domain", "fx_source_type_domain",
            "available_deposit_type_ids", "used_deposit_type_ids", "used_customer_base_deposit_type_ids",
            "available_channel_ids", "used_channel_ids", "available_fx_source_type_ids",
            "used_fx_source_type_ids", "available_expense_account_ids", "used_expense_account_ids",
            "available_fa_category_ids", "used_fa_category_ids", "available_position_type_ids",
            # UI Permissions & Measurement Flags
            "can_edit_content", "can_delete_plan", "can_submit_plan", "can_district_review",
            "can_ho_review", "can_sppmd_review", "can_use_reviewer_wizards",
            "is_planning_request", "is_category_monetary", "is_deposit_monetary",
            "is_customer_base_monetary", "is_fx_monetary", "is_digital_banking_monetary",
            "is_expense_monetary", "is_manpower_monetary", "is_fixed_asset_monetary",
            "has_cascaded_targets",
            "enable_deposit", "enable_customer_base", "enable_fx", "enable_digital_banking",
            "enable_expense", "enable_manpower", "enable_fixed_asset",
            # Workspace Links
            "workspace_deposit_id", "workspace_customer_base_id", "workspace_fx_id",
            "workspace_digital_banking_id", "workspace_expense_id", "workspace_manpower_id",
            "workspace_fixed_asset_id",
        }
        for fname in NON_EXPORTABLE_FIELDS:
            if fname in res:
                res[fname]["exportable"] = False
        return res

    def export_data(self, fields_to_export):
        """Prevent raw HTML badge, breakdown markup, and technical icon metadata from being exported to Excel/CSV."""
        res = super().export_data(fields_to_export)
        non_exportable = {
            "plan_category_badge_html", "kanban_breakdown_html",
            "activity_exception_decoration", "activity_exception_icon", "activity_type_icon",
        }
        for fname in non_exportable:
            if fname in fields_to_export:
                idx = fields_to_export.index(fname)
                for row in res.get("datas", []):
                    if idx < len(row):
                        row[idx] = ""
        return res


    display_quarter = fields.Selection(
        [
            ('all', 'All Quarters'),
            ('q1', 'Q1 (Jul - Sep)'),
            ('q2', 'Q2 (Oct - Dec)'),
            ('q3', 'Q3 (Jan - Mar)'),
            ('q4', 'Q4 (Apr - Jun)'),
        ],
        string="Display Quarter",
        default='all',
    )

    quarter1_total = fields.Float(
        compute='_compute_totals',
        string="Q1 Total",
        store=True
    )
    quarter2_total = fields.Float(
        compute='_compute_totals',
        string="Q2 Total",
        store=True
    )
    quarter3_total = fields.Float(
        compute='_compute_totals',
        string="Q3 Total",
        store=True
    )
    quarter4_total = fields.Float(
        compute='_compute_totals',
        string="Q4 Total",
        store=True
    )
    annual_total = fields.Float(
        compute='_compute_totals',
        inverse='_inverse_annual_total',
        string="Annual Total",
        store=True,
        readonly=False,
        index=True,
    )
    @api.depends(
        'category',
        'line_ids.annual_total',
        'line_ids.quarter1_total', 'line_ids.quarter2_total',
        'line_ids.quarter3_total', 'line_ids.quarter4_total',
        'line_ids.annual_total_cost', 'line_ids.fa_annual_total_cost',
        'line_ids.q1_cost', 'line_ids.q2_cost', 'line_ids.q3_cost', 'line_ids.q4_cost',
        'line_ids.fa_q1_cost', 'line_ids.fa_q2_cost', 'line_ids.fa_q3_cost', 'line_ids.fa_q4_cost',
        'line_ids.m01', 'line_ids.m02', 'line_ids.m03', 'line_ids.m04',
        'line_ids.m05', 'line_ids.m06', 'line_ids.m07', 'line_ids.m08',
        'line_ids.m09', 'line_ids.m10', 'line_ids.m11', 'line_ids.m12',
        'm01', 'm02', 'm03', 'm04', 'm05', 'm06',
        'm07', 'm08', 'm09', 'm10', 'm11', 'm12'
    )
    def _compute_totals(self):
        for rec in self:
            target_cat = rec.category or (rec.line_ids[0].line_type if rec.line_ids else "deposit")
            cat_lines = rec.line_ids.filtered(lambda l: l.line_type == target_cat) if rec.line_ids else rec.env["pbms.plan.category.line"]
            if not cat_lines and rec.org_unit_id and rec.cycle_id:
                cat_lines = self.env["pbms.plan.category.line"].search([
                    ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                    ("plan_id.cycle_id", "=", rec.cycle_id.id),
                    ("plan_id.active", "=", True),
                    ("line_type", "=", target_cat),
                ])

            if target_cat == "manpower":
                rec.annual_total = sum(cat_lines.mapped("annual_total_cost"))
                rec.quarter1_total = sum(cat_lines.mapped("q1_cost"))
                rec.quarter2_total = sum(cat_lines.mapped("q2_cost"))
                rec.quarter3_total = sum(cat_lines.mapped("q3_cost"))
                rec.quarter4_total = sum(cat_lines.mapped("q4_cost"))
            elif target_cat == "fixed_asset":
                rec.annual_total = sum(cat_lines.mapped("fa_annual_total_cost"))
                rec.quarter1_total = sum(cat_lines.mapped("fa_q1_cost"))
                rec.quarter2_total = sum(cat_lines.mapped("fa_q2_cost"))
                rec.quarter3_total = sum(cat_lines.mapped("fa_q3_cost"))
                rec.quarter4_total = sum(cat_lines.mapped("fa_q4_cost"))
            elif cat_lines:
                rec.annual_total = sum(cat_lines.mapped("annual_total"))
                rec.quarter1_total = sum(cat_lines.mapped("quarter1_total"))
                rec.quarter2_total = sum(cat_lines.mapped("quarter2_total"))
                rec.quarter3_total = sum(cat_lines.mapped("quarter3_total"))
                rec.quarter4_total = sum(cat_lines.mapped("quarter4_total"))
                for m in MONTH_FIELDS:
                    setattr(rec, m, sum(cat_lines.mapped(m)))
            else:
                values = {f: (getattr(rec, f) or 0.0) for f in MONTH_FIELDS}
                rec.quarter1_total = sum(values[f] for f in QUARTERS["q1"])
                rec.quarter2_total = sum(values[f] for f in QUARTERS["q2"])
                rec.quarter3_total = sum(values[f] for f in QUARTERS["q3"])
                rec.quarter4_total = sum(values[f] for f in QUARTERS["q4"])
                rec.annual_total = sum(values.values())

    def _distribute_plan_annual_total_proportionally(self):
        """When annual_total on plan is edited, distribute proportionally to lines or months."""
        for rec in self:
            if rec.category in ("manpower", "fixed_asset"):
                continue
            cat_lines = rec.line_ids.filtered(lambda l: l.line_type == rec.category) if rec.line_ids else rec.env["pbms.plan.category.line"]
            new_total = rec.annual_total or 0.0
            if cat_lines:
                old_line_totals = [(l.annual_total or 0.0) for l in cat_lines]
                old_sum = sum(old_line_totals)
                if abs(old_sum) > 1e-6:
                    for l in cat_lines:
                        l.annual_total = new_total * ((l.annual_total or 0.0) / old_sum)
                        l._distribute_annual_total_proportionally()
                else:
                    equal_share = new_total / len(cat_lines)
                    for l in cat_lines:
                        l.annual_total = equal_share
                        l._distribute_annual_total_proportionally()
            else:
                old_months = [(getattr(rec, m) or 0.0) for m in MONTH_FIELDS]
                old_sum = sum(old_months)
                if abs(old_sum) > 1e-6:
                    for i, m in enumerate(MONTH_FIELDS):
                        setattr(rec, m, round(new_total * (old_months[i] / old_sum), 2))
                else:
                    for m in MONTH_FIELDS:
                        setattr(rec, m, round(new_total / 12.0, 2))
                rec._compute_totals()

    @api.onchange("annual_total")
    def _onchange_annual_total(self):
        self._distribute_plan_annual_total_proportionally()

    def _inverse_annual_total(self):
        self._distribute_plan_annual_total_proportionally()


    @api.depends("org_unit_id", "cycle_id", "request_number", "category", "plan_category_title")
    def _compute_display_name(self):
        MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking"}
        RESOURCE_CATS = {"manpower", "general_expense", "fixed_asset"}

        for rec in self:
            if not rec.request_number or rec.request_number == "New" or (rec.category == "manpower" and not rec.request_number.startswith("WFP/")) or (rec.category != "manpower" and rec.request_number.startswith("WFP/")):
                if rec.category == "manpower":
                    seq = (
                        rec.env["ir.sequence"].next_by_code("pbms.workforce.request")
                        or f"WFP/{fields.Date.today().year}/{rec.id:05d}"
                    )
                else:
                    seq = (
                        rec.env["ir.sequence"].next_by_code("pbms.planning.request")
                        or rec.env["ir.sequence"].next_by_code("pbms.planning.category")
                        or f"REQ/{fields.Date.today().year}/{rec.id:05d}"
                    )
                rec.request_number = seq

            cat_dict = dict(rec._fields["category"].selection) if hasattr(rec, "_fields") and "category" in rec._fields else {}
            cat_title = cat_dict.get(rec.category, rec.plan_category_title or "")

            parts = [
                rec.org_unit_id.display_name if rec.org_unit_id else "",
                rec.cycle_id.name if rec.cycle_id else "",
                cat_title,
            ]
            rec.display_name = " / ".join(filter(None, parts))

    @api.depends("line_ids", "org_unit_id", "cycle_id", "category")
    def _compute_line_count(self):
        for rec in self:
            target_cat = rec.category or (rec.line_ids[0].line_type if rec.line_ids else "deposit")
            cat_lines = rec.line_ids.filtered(lambda l: l.line_type == target_cat) if rec.line_ids else rec.env["pbms.plan.category.line"]
            if not cat_lines and rec.org_unit_id and rec.cycle_id:
                rec.line_count = self.env["pbms.plan.category.line"].search_count([
                    ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                    ("plan_id.cycle_id", "=", rec.cycle_id.id),
                    ("plan_id.active", "=", True),
                    ("line_type", "=", target_cat),
                ])
            else:
                rec.line_count = len(cat_lines)


    # FIXED: Using fa_annual_total_cost instead of estimated_total_price
    @api.depends("line_ids.fa_annual_total_cost", "line_ids.line_type", "category", "fixed_asset_line_ids.fa_annual_total_cost")
    def _compute_total_estimated_amount(self):
        for rec in self:
            if rec.category != "fixed_asset":
                rec.total_estimated_amount = 0.0
            else:
                fa_lines = rec.line_ids.filtered(lambda l: l.line_type == "fixed_asset") or rec.fixed_asset_line_ids
                rec.total_estimated_amount = sum(fa_lines.mapped("fa_annual_total_cost"))

    @api.depends("line_ids.annual_total_cost", "line_ids.line_type", "category", "manpower_line_ids.annual_total_cost")
    def _compute_total_manpower_cost(self):
        for rec in self:
            if rec.category != "manpower" and not getattr(rec, "enable_manpower", False):
                rec.total_manpower_cost = 0.0
            else:
                mp_lines = rec.line_ids.filtered(lambda l: l.line_type == "manpower") or rec.manpower_line_ids
                rec.total_manpower_cost = sum(mp_lines.mapped("annual_total_cost"))

    @api.depends(
        "existing_manpower_summary_ids.approved_plan_count",
        "existing_manpower_summary_ids.active_employee_count",
        "existing_manpower_summary_ids.vacant_position_count",
        "existing_manpower_summary_ids.monthly_salary",
        "existing_manpower_summary_ids.annual_salary",
        "org_unit_id",
        "category",
        "enable_manpower",
    )
    def _compute_existing_manpower_data(self):
        for rec in self:
            mp_lines = rec._get_category_lines("manpower")
            is_manpower_applicable = (
                rec.category == "manpower"
                or rec.enable_manpower
                or bool(mp_lines)
            )
            if is_manpower_applicable:
                rec.existing_total_authorized = sum(rec.existing_manpower_summary_ids.mapped("approved_plan_count"))
                rec.existing_total_active = sum(rec.existing_manpower_summary_ids.mapped("active_employee_count"))
                rec.existing_total_vacancies = sum(rec.existing_manpower_summary_ids.mapped("vacant_position_count"))
                rec.existing_total_monthly_salary = sum(rec.existing_manpower_summary_ids.mapped("monthly_salary"))
                rec.existing_total_annual_salary = sum(rec.existing_manpower_summary_ids.mapped("annual_salary"))
            else:
                rec.existing_total_authorized = 0
                rec.existing_total_active = 0
                rec.existing_total_vacancies = 0
                rec.existing_total_monthly_salary = 0.0
                rec.existing_total_annual_salary = 0.0


    def action_refresh_existing_manpower(self):
        """Action button to re-fetch and synchronize existing manpower from HR contracts and operating unit."""
        self._sync_existing_manpower_lines()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Existing Manpower Refreshed"),
                "message": _("Existing workforce establishment and active contract salaries have been updated."),
                "type": "success",
                "sticky": False,
            }
        }

    def _sync_existing_manpower_lines(self):
        """Populate eligible job positions and active employees from operating.unit and hr.version/hr.contract."""
        has_summary_model = "pbms.existing.manpower.summary" in self.env
        has_emp_line_model = "pbms.existing.employee.line" in self.env
        has_ou_job_pos = "operating.unit.job.position" in self.env
        has_employee_model = "hr.employee" in self.env
        ContractModel = (
            self.env["hr.version"] if "hr.version" in self.env else (
                self.env["hr.contract"] if "hr.contract" in self.env else False
            )
        )

        for plan in self:
            is_manpower_applicable = (
                plan.category == "manpower"
                or plan.enable_manpower
                or bool(plan.line_ids.filtered(lambda l: l.line_type == "manpower"))
            )
            if not is_manpower_applicable or not plan.org_unit_id:
                continue

            # Clear existing lines
            plan.existing_manpower_summary_ids.unlink()
            plan.existing_employee_line_ids.unlink()

            unit_id = plan.org_unit_id.id

            # 1. Gather all active employees in this work unit
            emp_domain = [("active", "=", True)]
            if has_employee_model:
                emp_domain += [
                    "|",
                    ("operating_unit_ids", "in", [unit_id]),
                    ("default_operating_unit_id", "=", unit_id),
                ]
                employees = self.env["hr.employee"].search(emp_domain)
            else:
                employees = self.env["hr.employee"]

            # 2. Gather eligible positions from operating.unit.job.position
            ou_positions = self.env["operating.unit.job.position"].search([
                ("operating_unit_id", "=", unit_id),
                ("active", "=", True),
            ]) if has_ou_job_pos else self.env["operating.unit.job.position"]

            # Map positions: job_id -> position info
            pos_dict = {}
            for pos in ou_positions:
                job = pos.job_position_id
                if job:
                    grade = False
                    for g_attr in ("grade", "grade_id", "job_grade_id", "job_grade"):
                        if hasattr(job, g_attr) and getattr(job, g_attr):
                            grade = getattr(job, g_attr)
                            break
                    if pos and hasattr(pos, "_compute_baseline_count") and not pos.baseline_count:
                        pos._compute_baseline_count()
                    approved_cnt = getattr(pos, "baseline_count", 0) or 0
                    if not approved_cnt:
                        approved_cnt = getattr(pos, "total_headcount", 0) or getattr(pos, "approved_plan_count", 0) or 0
                    pos_dict[job.id] = {
                        "job": job,
                        "ou_pos": pos,
                        "approved_count": approved_cnt,
                        "employees": [],
                        "grade": grade,
                    }

            # Map each active employee to their position
            emp_records_to_create = []
            for emp in employees:
                job = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
                if not job:
                    continue
                if job.id not in pos_dict:
                    grade = getattr(emp, "job_grade", False) or getattr(emp, "grade_id", False) or getattr(emp, "grade", False)
                    if not grade:
                        grade = getattr(job, "grade", False) or getattr(job, "job_grade", False)
                    pos_dict[job.id] = {
                        "job": job,
                        "ou_pos": False,
                        "approved_count": 0,
                        "employees": [],
                        "grade": grade,
                    }

                pos_dict[job.id]["employees"].append(emp)

                # Find employee's active contract in hr_employee_custom (hr.version / hr.contract)
                contract = False
                if hasattr(emp, "contract_id") and emp.contract_id:
                    contract = emp.contract_id
                elif ContractModel:
                    contract = ContractModel.search([
                        ("employee_id", "=", emp.id),
                        ("state", "in", ("open", "probation", "draft")),
                    ], limit=1)

                emp_grade = getattr(emp, "job_grade", False) or getattr(emp, "grade_id", False) or getattr(emp, "grade", False)
                if contract and not emp_grade and hasattr(contract, "job_grade"):
                    emp_grade = getattr(contract, "job_grade", False)
                if contract and not emp_grade and hasattr(contract, "grade_id"):
                    emp_grade = getattr(contract, "grade_id", False)
                if not emp_grade:
                    emp_grade = pos_dict[job.id]["grade"]

                wage = 0.0
                if contract:
                    wage = getattr(contract, "wage", 0.0) or getattr(contract, "base_salary", 0.0) or 0.0
                if not wage and hasattr(emp, "wage") and emp.wage:
                    wage = emp.wage
                if not wage and emp_grade and hasattr(emp_grade, "base_salary"):
                    wage = emp_grade.base_salary or 0.0

                annual = wage * 12.0
                c_state = getattr(contract, "state", "open") if contract else "open"
                emp_code = getattr(emp, "emp_code", False) or getattr(emp, "barcode", False) or getattr(emp, "identification_id", False) or ""

                emp_records_to_create.append({
                    "plan_id": plan.id,
                    "employee_id": emp.id,
                    "employee_code": emp_code,
                    "job_id": job.id,
                    "grade_id": emp_grade.id if emp_grade else False,
                    "contract_id": contract.id if contract else False,
                    "wage": wage,
                    "annual_salary": annual,
                    "contract_state": c_state if c_state in ('draft', 'probation', 'open', 'close', 'cancel') else 'open',
                })

            if emp_records_to_create and has_emp_line_model:
                self.env["pbms.existing.employee.line"].create(emp_records_to_create)

            # Build position summary records
            pos_records_to_create = []
            for job_id, p_info in pos_dict.items():
                job_emps = p_info["employees"]
                active_count = len(job_emps)
                ou_pos = p_info.get("ou_pos")
                approved_count = p_info.get("approved_count", 0)
                vacant_count = getattr(ou_pos, "vacant_position_count", False) if ou_pos else max(0, approved_count - active_count)
                if vacant_count is False:
                    vacant_count = max(0, approved_count - active_count)

                # Total salary for this position from created employee lines
                matching_lines = [r for r in emp_records_to_create if r["job_id"] == job_id]
                if matching_lines:
                    pos_monthly = sum(r["wage"] for r in matching_lines)
                else:
                    pos_monthly = 0.0
                pos_annual = pos_monthly * 12.0

                pos_records_to_create.append({
                    "plan_id": plan.id,
                    "job_id": job_id,
                    "grade_id": p_info["grade"].id if p_info["grade"] else False,
                    "approved_plan_count": approved_count,
                    "active_employee_count": active_count,
                    "vacant_position_count": vacant_count,
                    "monthly_salary": pos_monthly,
                    "annual_salary": pos_annual,
                })

            if pos_records_to_create and has_summary_model:
                self.env["pbms.existing.manpower.summary"].create(pos_records_to_create)

    def _get_category_lines(self, cat):
        self.ensure_one()
        cat_field_map = {
            "deposit": "deposit_line_ids",
            "customer_base": "customer_base_line_ids",
            "fx": "fx_line_ids",
            "digital_banking": "digital_banking_line_ids",
            "general_expense": "expense_line_ids",
            "manpower": "manpower_line_ids",
            "fixed_asset": "fixed_asset_line_ids",
        }
        fname = cat_field_map.get(cat)
        if fname and hasattr(self, fname):
            field_lines = getattr(self, fname)
            if field_lines:
                return field_lines

        if self.line_ids:
            direct_lines = self.line_ids.filtered(lambda l: l.line_type == cat)
            if direct_lines:
                return direct_lines

        if self.org_unit_id and self.cycle_id:
            real_unit_id = self.org_unit_id._origin.id if (hasattr(self.org_unit_id, "_origin") and self.org_unit_id._origin) else (self.org_unit_id.id if isinstance(self.org_unit_id.id, int) else False)
            real_cycle_id = self.cycle_id._origin.id if (hasattr(self.cycle_id, "_origin") and self.cycle_id._origin) else (self.cycle_id.id if isinstance(self.cycle_id.id, int) else False)
            if real_unit_id and real_cycle_id:
                if self.org_unit_type == "district_office":
                    return self.env["pbms.plan.category.line"].search([
                        "|",
                        ("district_id", "=", real_unit_id),
                        ("plan_id.org_unit_id", "=", real_unit_id),
                        ("cycle_id", "=", real_cycle_id),
                        ("plan_id.active", "=", True),
                        ("line_type", "=", cat),
                    ])
                return self.env["pbms.plan.category.line"].search([
                    ("plan_id.org_unit_id", "=", real_unit_id),
                    ("plan_id.cycle_id", "=", real_cycle_id),
                    ("plan_id.active", "=", True),
                    ("line_type", "=", cat),
                ])
        return self.env["pbms.plan.category.line"]

    @api.depends(
        "org_unit_id",
        "category",
        "line_ids.annual_total_cost",
        "line_ids.line_type",
        "line_ids.position_type",
        "line_ids.quantity",
        "existing_total_annual_salary",
        "existing_manpower_summary_ids.annual_salary",
    )
    def _compute_operating_unit_manpower_budget(self):
        for rec in self:
            if rec.category != "manpower":
                rec.current_staff_salary_budget = 0.0
                rec.new_planned_salary_budget = 0.0
                rec.total_operating_unit_manpower_budget = 0.0
                continue

            mp_lines = rec._get_category_lines("manpower")
            current_salary_total = rec.existing_total_annual_salary or 0.0
            if not current_salary_total and rec.org_unit_id:
                EmployeeModel = self.env["hr.employee"] if "hr.employee" in self.env else False
                if EmployeeModel:
                    emps = EmployeeModel.search([
                        ("active", "=", True),
                        "|",
                        ("operating_unit_ids", "in", [rec.org_unit_id.id]),
                        ("default_operating_unit_id", "=", rec.org_unit_id.id),
                    ])
                    for emp in emps:
                        w = 0.0
                        if hasattr(emp, "contract_id") and emp.contract_id:
                            w = getattr(emp.contract_id, "wage", 0.0) or getattr(emp.contract_id, "base_salary", 0.0) or 0.0
                        if not w and hasattr(emp, "wage") and emp.wage:
                            w = emp.wage
                        if not w:
                            g = getattr(emp, "job_grade", False) or getattr(emp, "grade_id", False) or getattr(emp, "grade", False)
                            if not g and getattr(emp, "job_position", False):
                                g = getattr(emp.job_position, "grade", False) or getattr(emp.job_position, "job_grade", False)
                            if g and hasattr(g, "base_salary"):
                                w = g.base_salary or 0.0
                        current_salary_total += (w or 0.0) * 12.0

            rec.current_staff_salary_budget = current_salary_total
            new_planned_cost = sum(mp_lines.mapped("annual_total_cost"))
            rec.new_planned_salary_budget = new_planned_cost
            rec.total_operating_unit_manpower_budget = current_salary_total + new_planned_cost

    @api.depends("line_ids.fa_annual_total_cost", "line_ids.line_type")
    def _compute_total_fixed_asset_cost(self):
        for rec in self:
            fa_lines = rec._get_category_lines("fixed_asset")
            rec.total_fixed_asset_cost = sum(fa_lines.mapped("fa_annual_total_cost"))

    @api.depends("line_ids.q1_cost", "line_ids.q2_cost", "line_ids.q3_cost", "line_ids.q4_cost", "line_ids.line_type")
    def _compute_manpower_quarter_totals(self):
        for rec in self:
            mp_lines = rec._get_category_lines("manpower")
            rec.q1_total_cost = sum(mp_lines.mapped("q1_cost"))
            rec.q2_total_cost = sum(mp_lines.mapped("q2_cost"))
            rec.q3_total_cost = sum(mp_lines.mapped("q3_cost"))
            rec.q4_total_cost = sum(mp_lines.mapped("q4_cost"))

    @api.depends("line_ids.fa_q1_cost", "line_ids.fa_q2_cost", "line_ids.fa_q3_cost", "line_ids.fa_q4_cost")
    def _compute_fa_quarter_totals(self):
        for rec in self:
            fa_lines = rec._get_category_lines("fixed_asset")
            rec.fa_q1_total_cost = sum(fa_lines.mapped("fa_q1_cost"))
            rec.fa_q2_total_cost = sum(fa_lines.mapped("fa_q2_cost"))
            rec.fa_q3_total_cost = sum(fa_lines.mapped("fa_q3_cost"))
            rec.fa_q4_total_cost = sum(fa_lines.mapped("fa_q4_cost"))

    @api.depends("line_ids.is_cascaded")
    def _compute_has_cascaded_targets(self):
        for rec in self:
            rec.has_cascaded_targets = any(l.is_cascaded for l in rec.line_ids)

    @api.depends(
        "line_ids",
        "line_ids.line_type",
        "line_ids.quantity",
        "line_ids.fa_q1", "line_ids.fa_q2", "line_ids.fa_q3", "line_ids.fa_q4",
        "line_ids.fa_annual_total_cost", "line_ids.approved_quantity", "line_ids.fa_approved_total_cost",
        "line_ids.annual_total",
        "line_ids.proposed_annual_total",
        "line_ids.approved_annual_total",
        "line_ids.quarter1_total", "line_ids.quarter2_total",
        "line_ids.quarter3_total", "line_ids.quarter4_total",
        "line_ids.fulfillment_promotion", "line_ids.fulfillment_transfer",
        "line_ids.fulfillment_lateral", "line_ids.fulfillment_external",
    )
    def _compute_category_summaries(self):
        for rec in self:
            dep_lines = rec._get_category_lines("deposit")
            rec.deposit_line_count = len(dep_lines)
            rec.deposit_annual_total = sum(dep_lines.mapped("annual_total"))
            rec.deposit_proposed_total = sum(dep_lines.mapped("proposed_annual_total"))
            rec.deposit_approved_total = sum(dep_lines.mapped("approved_annual_total"))
            rec.deposit_q1_total = sum(dep_lines.mapped("quarter1_total"))
            rec.deposit_q2_total = sum(dep_lines.mapped("quarter2_total"))
            rec.deposit_q3_total = sum(dep_lines.mapped("quarter3_total"))
            rec.deposit_q4_total = sum(dep_lines.mapped("quarter4_total"))

            cb_lines = rec._get_category_lines("customer_base")
            rec.customer_base_line_count = len(cb_lines)
            rec.customer_base_annual_total = sum(cb_lines.mapped("annual_total"))
            rec.customer_base_proposed_total = sum(cb_lines.mapped("proposed_annual_total"))
            rec.customer_base_approved_total = sum(cb_lines.mapped("approved_annual_total"))
            rec.customer_base_q1_total = sum(cb_lines.mapped("quarter1_total"))
            rec.customer_base_q2_total = sum(cb_lines.mapped("quarter2_total"))
            rec.customer_base_q3_total = sum(cb_lines.mapped("quarter3_total"))
            rec.customer_base_q4_total = sum(cb_lines.mapped("quarter4_total"))

            fx_lines = rec._get_category_lines("fx")
            rec.fx_line_count = len(fx_lines)
            rec.fx_annual_total = sum(fx_lines.mapped("annual_total"))
            rec.fx_proposed_total = sum(fx_lines.mapped("proposed_annual_total"))
            rec.fx_approved_total = sum(fx_lines.mapped("approved_annual_total"))
            rec.fx_q1_total = sum(fx_lines.mapped("quarter1_total"))
            rec.fx_q2_total = sum(fx_lines.mapped("quarter2_total"))
            rec.fx_q3_total = sum(fx_lines.mapped("quarter3_total"))
            rec.fx_q4_total = sum(fx_lines.mapped("quarter4_total"))

            db_lines = rec._get_category_lines("digital_banking")
            rec.digital_banking_line_count = len(db_lines)
            rec.digital_banking_annual_total = sum(db_lines.mapped("annual_total"))
            rec.digital_banking_proposed_total = sum(db_lines.mapped("proposed_annual_total"))
            rec.digital_banking_approved_total = sum(db_lines.mapped("approved_annual_total"))
            rec.digital_banking_q1_total = sum(db_lines.mapped("quarter1_total"))
            rec.digital_banking_q2_total = sum(db_lines.mapped("quarter2_total"))
            rec.digital_banking_q3_total = sum(db_lines.mapped("quarter3_total"))
            rec.digital_banking_q4_total = sum(db_lines.mapped("quarter4_total"))

            exp_lines = rec._get_category_lines("general_expense")
            rec.expense_line_count = len(exp_lines)
            rec.expense_annual_total = sum(exp_lines.mapped("annual_total"))
            rec.expense_proposed_total = sum(exp_lines.mapped("proposed_annual_total"))
            rec.expense_approved_total = sum(exp_lines.mapped("approved_annual_total"))
            rec.expense_q1_total = sum(exp_lines.mapped("quarter1_total"))
            rec.expense_q2_total = sum(exp_lines.mapped("quarter2_total"))
            rec.expense_q3_total = sum(exp_lines.mapped("quarter3_total"))
            rec.expense_q4_total = sum(exp_lines.mapped("quarter4_total"))

            mp_lines = rec._get_category_lines("manpower")
            rec.manpower_line_count = len(mp_lines)
            rec.manpower_total_headcount = int(sum(mp_lines.mapped("quantity")) or sum(mp_lines.mapped("annual_total")) or 0)
            appr_hc = int(sum(mp_lines.mapped("display_approved_annual_total")) or 0)
            rec.manpower_approved_headcount = appr_hc
            prom = int(sum(mp_lines.mapped("fulfillment_promotion")) or 0)
            trans = int(sum(mp_lines.mapped("fulfillment_transfer")) or 0)
            lat = int(sum(mp_lines.mapped("fulfillment_lateral")) or 0)
            ext = int(sum(mp_lines.mapped("fulfillment_external")) or 0)
            rec.manpower_total_promotion = prom
            rec.manpower_total_transfer = trans
            rec.manpower_total_lateral = lat
            rec.manpower_total_external = ext
            tot_fulfill = prom + trans + lat + ext
            rec.manpower_total_fulfillment = tot_fulfill
            target_for_bal = appr_hc if appr_hc > 0 else rec.manpower_total_headcount
            rec.manpower_fulfillment_balance = target_for_bal - tot_fulfill
            rec.manpower_needs_ceo_approval = ext > 0

            fa_lines = rec._get_category_lines("fixed_asset")
            rec.fixed_asset_line_count = len(fa_lines)
            rec.fixed_asset_total_quantity = sum(fa_lines.mapped("quantity"))
            rec.fixed_asset_approved_quantity = sum(fa_lines.mapped("approved_quantity"))
            rec.fixed_asset_approved_total = sum(fa_lines.mapped("fa_approved_total_cost"))


    @api.depends(
        "category",
        "state",
        "currency_id",
        "currency_id.symbol",
        "line_ids",
        "line_ids.line_type",
        "line_ids.quantity",
        "line_ids.annual_total_cost",
        "line_ids.position_type_id",
        "line_ids.position_type_id.name",
        "line_ids.position_type",
        "line_ids.deposit_type_id",
        "line_ids.deposit_type_id.name",
        "line_ids.base_type",
        "line_ids.fx_source_type",
        "line_ids.fx_source_type.name",
        "line_ids.channel_id",
        "line_ids.channel_id.name",
        "line_ids.channel_id.unit_of_measure",
        "line_ids.expense_account_id",
        "line_ids.expense_account_id.name",
        "line_ids.category_id",
        "line_ids.category_id.name",
        "line_ids.fa_annual_total_cost",
        "line_ids.annual_total",
        "line_ids.proposed_annual_total",
        "line_ids.approved_annual_total",
        "line_ids.is_cascaded",
        "is_deposit_monetary",
        "is_customer_base_monetary",
        "is_fx_monetary",
        "is_digital_banking_monetary",
        "is_expense_monetary",
        "is_manpower_monetary",
        "is_fixed_asset_monetary",
    )
    def _compute_kanban_breakdown_html(self):
        category_titles = {
            "deposit": _("Deposit Mobilization Plan"),
            "customer_base": _("Customer Base Plan"),
            "fx": _("FX Mobilization Plan"),
            "digital_banking": _("Digital Banking Plan"),
            "general_expense": _("General Expense Budget Plan"),
            "manpower": _("Workforce / Manpower Plan"),
            "fixed_asset": _("Fixed Asset Requirement Plan"),
        }
        base_type_labels = {
            "new_acquisition": _("New Acq."),
            "dormant_reduction": _("Dormant Red."),
        }
        position_type_labels = {
            "new": _("New Position"),
            "additional": _("Additional Position"),
            "replacement": _("Replacement"),
            "transfer": _("Position Transfer"),
            "upgrade": _("Position Upgrade"),
            "existing": _("Existing Position"),
        }
        cat_order = ["deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"]

        for rec in self:
            curr_sym = (rec.currency_id.symbol if rec.currency_id and rec.currency_id.symbol else (rec.currency_id.name if rec.currency_id else "Br")) or "Br"
            is_approved = (rec.state == "approved")

            all_lines = rec.line_ids if rec.line_ids else rec.env["pbms.plan.category.line"]
            if not all_lines and rec.org_unit_id and rec.cycle_id:
                all_lines = self.env["pbms.plan.category.line"].search([
                    ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                    ("plan_id.cycle_id", "=", rec.cycle_id.id),
                    ("plan_id.active", "=", True),
                ])

            if not all_lines:
                rec.kanban_breakdown_html = False
                continue

            # Isolate card breakdown strictly to this plan's category
            target_cat = rec.category or "deposit"
            used_cats = [target_cat]
            is_multi_category = False
            html_sections = []

            for cat in used_cats:
                cat_lines = all_lines.filtered(lambda l: l.line_type == cat)
                if not cat_lines:
                    continue



                items = []

                if cat == "manpower":
                    # Group by position_type_id / position_type
                    mp_groups = {}
                    for l in cat_lines:
                        p_id = l.position_type_id.id if l.position_type_id else (l.position_type or "new")
                        if p_id not in mp_groups:
                            p_name = l.position_type_id.name if l.position_type_id else position_type_labels.get(l.position_type, l.position_type or _("Position"))
                            if p_name:
                                p_name = p_name.strip().title()
                            mp_groups[p_id] = {
                                "name": p_name,
                                "quantity": 0,
                                "cost": 0.0,
                            }
                        mp_groups[p_id]["quantity"] += (l.quantity or 0)
                        mp_groups[p_id]["cost"] += (l.annual_total_cost or 0.0)

                    for g in mp_groups.values():
                        qty = g["quantity"]
                        cost = g["cost"]
                        badge_text = _("%s Approved") % qty if is_approved else _("%s Requested") % qty
                        badge_cls = "bg-success-subtle text-success border border-success-subtle" if is_approved else "bg-light text-dark border"
                        items.append({
                            "label": g["name"],
                            "badge_text": badge_text,
                            "badge_cls": badge_cls,
                            "value": f"{cost:,.2f} {curr_sym}",
                            "value_cls": "text-dark",
                        })

                elif cat == "deposit":
                    # Group by deposit_type_id
                    dep_groups = {}
                    for l in cat_lines:
                        d_id = l.deposit_type_id.id if l.deposit_type_id else False
                        if d_id not in dep_groups:
                            d_name = l.deposit_type_id.name if l.deposit_type_id else _("Deposit Product")
                            if d_name:
                                d_name = d_name.strip()
                            dep_groups[d_id] = {
                                "name": d_name,
                                "amount": 0.0,
                            }
                        val = l.approved_annual_total if (is_approved and l.is_cascaded and l.approved_annual_total) else (l.annual_total or 0.0)
                        dep_groups[d_id]["amount"] += val

                    is_mon = rec.is_deposit_monetary
                    for g in dep_groups.values():
                        amt = g["amount"]
                        val_str = f"{amt:,.2f} {curr_sym}" if is_mon else f"{int(amt):,} Accts"
                        items.append({
                            "label": g["name"],
                            "badge_text": False,
                            "badge_cls": False,
                            "value": val_str,
                            "value_cls": "text-primary",
                        })

                elif cat == "customer_base":
                    # Group by deposit_type_id + base_type
                    cb_groups = {}
                    for l in cat_lines:
                        d_id = l.deposit_type_id.id if l.deposit_type_id else False
                        b_type = l.base_type or "new_acquisition"
                        key = (d_id, b_type)
                        if key not in cb_groups:
                            d_name = l.deposit_type_id.name if l.deposit_type_id else _("Customer Base")
                            if d_name:
                                d_name = d_name.strip()
                            cb_groups[key] = {
                                "name": d_name,
                                "base_type": b_type,
                                "amount": 0.0,
                            }
                        val = l.approved_annual_total if (is_approved and l.is_cascaded and l.approved_annual_total) else (l.annual_total or 0.0)
                        cb_groups[key]["amount"] += val

                    for g in cb_groups.values():
                        amt = g["amount"]
                        b_label = base_type_labels.get(g["base_type"], g["base_type"])
                        sign = "+" if amt > 0 else ""
                        items.append({
                            "label": g["name"],
                            "badge_text": b_label,
                            "badge_cls": "bg-light text-secondary border",
                            "value": f"{sign}{int(amt):,} Accts",
                            "value_cls": "text-success",
                        })

                elif cat == "fx":
                    # Group by fx_source_type
                    fx_groups = {}
                    for l in cat_lines:
                        s_id = l.fx_source_type.id if l.fx_source_type else False
                        if s_id not in fx_groups:
                            s_name = l.fx_source_type.name if l.fx_source_type else _("FX Source")
                            if s_name:
                                s_name = s_name.strip()
                            fx_groups[s_id] = {
                                "name": s_name,
                                "amount": 0.0,
                            }
                        val = l.approved_annual_total if (is_approved and l.is_cascaded and l.approved_annual_total) else (l.annual_total or 0.0)
                        fx_groups[s_id]["amount"] += val

                    fx_curr = rec.fx_currency_id or self.env["res.currency"].search([("name", "=", "USD")], limit=1) or rec.currency_id
                    fx_sym = fx_curr.symbol if fx_curr and fx_curr.symbol else (fx_curr.name if fx_curr else "$")
                    fx_name = fx_curr.name if fx_curr else "USD"
                    for g in fx_groups.values():
                        amt = g["amount"]
                        items.append({
                            "label": g["name"],
                            "badge_text": False,
                            "badge_cls": False,
                            "value": f"{fx_sym}{amt:,.2f} {fx_name}",
                            "value_cls": "text-info",
                        })

                elif cat == "digital_banking":
                    # Group by channel_id
                    db_groups = {}
                    for l in cat_lines:
                        ch_id = l.channel_id.id if l.channel_id else False
                        if ch_id not in db_groups:
                            ch_name = l.channel_id.name if l.channel_id else _("Digital Channel")
                            if ch_name:
                                ch_name = ch_name.strip()
                            uom = l.channel_id.unit_of_measure if l.channel_id else "count"
                            db_groups[ch_id] = {
                                "name": ch_name,
                                "uom": uom,
                                "amount": 0.0,
                            }
                        val = l.approved_annual_total if (is_approved and l.is_cascaded and l.approved_annual_total) else (l.annual_total or 0.0)
                        db_groups[ch_id]["amount"] += val

                    for g in db_groups.values():
                        amt = g["amount"]
                        val_str = f"{amt:,.2f} {curr_sym}" if g["uom"] == "amount" else f"{int(amt):,}"
                        items.append({
                            "label": g["name"],
                            "badge_text": False,
                            "badge_cls": False,
                            "value": val_str,
                            "value_cls": "text-warning-emphasis",
                        })

                elif cat == "general_expense":
                    # Group by expense_account_id
                    exp_groups = {}
                    for l in cat_lines:
                        e_id = l.expense_account_id.id if l.expense_account_id else False
                        if e_id not in exp_groups:
                            e_name = l.expense_account_id.name if l.expense_account_id else _("Expense Account")
                            if e_name:
                                e_name = e_name.strip()
                            exp_groups[e_id] = {
                                "name": e_name,
                                "amount": 0.0,
                            }
                        val = l.approved_annual_total if (is_approved and l.is_cascaded and l.approved_annual_total) else (l.annual_total or 0.0)
                        exp_groups[e_id]["amount"] += val

                    for g in exp_groups.values():
                        amt = g["amount"]
                        items.append({
                            "label": g["name"],
                            "badge_text": False,
                            "badge_cls": False,
                            "value": f"{amt:,.2f} {curr_sym}",
                            "value_cls": "text-danger",
                        })

                elif cat == "fixed_asset":
                    # Group by category_id
                    fa_groups = {}
                    for l in cat_lines:
                        c_id = l.category_id.id if l.category_id else (l.item_description or "other")
                        if c_id not in fa_groups:
                            c_name = l.category_id.name if l.category_id else (l.item_description or _("Fixed Asset"))
                            if c_name:
                                c_name = c_name.strip()
                            fa_groups[c_id] = {
                                "name": c_name,
                                "quantity": 0,
                                "cost": 0.0,
                            }
                        fa_groups[c_id]["quantity"] += (l.quantity or 0)
                        fa_groups[c_id]["cost"] += (l.fa_annual_total_cost or 0.0)

                    for g in fa_groups.values():
                        qty = g["quantity"]
                        cost = g["cost"]
                        badge_text = _("%s Approved") % qty if is_approved else _("%s Requested") % qty
                        badge_cls = "bg-success-subtle text-success border border-success-subtle" if is_approved else "bg-light text-dark border"
                        items.append({
                            "label": g["name"],
                            "badge_text": badge_text,
                            "badge_cls": badge_cls,
                            "value": f"{cost:,.2f} {curr_sym}",
                            "value_cls": "text-dark",
                        })

                if not items:
                    continue

                section_rows = []
                col_headers = {
                    "manpower": (_("Request Type"), _("Annual Cost")),
                    "deposit": (_("Deposit Product"), _("Annual Total")),
                    "customer_base": (_("Account Type"), _("Target Accounts")),
                    "fx": (_("FX Source"), _("Annual Target")),
                    "digital_banking": (_("Digital Channel"), _("Target")),
                    "general_expense": (_("Expense Account"), _("Annual Budget")),
                    "fixed_asset": (_("Asset Category"), _("Total Cost")),
                }
                col_left, col_right = col_headers.get(cat, (_("Item"), _("Total")))

                if is_multi_category:
                    cat_title = category_titles.get(cat, cat.title())
                    section_rows.append(
                        f'<div class="d-flex justify-content-between align-items-center text-muted fw-bold text-uppercase mt-2 mb-1" style="font-size: 0.68rem; letter-spacing: 0.5px; border-bottom: 1px solid #e9ecef; padding-bottom: 2px;">'
                        f'  <span>{cat_title} ({col_left})</span>'
                        f'  <span>{col_right}</span>'
                        f'</div>'
                    )
                else:
                    section_rows.append(
                        f'<div class="d-flex justify-content-between align-items-center text-muted fw-bold text-uppercase mb-1" style="font-size: 0.68rem; letter-spacing: 0.5px; border-bottom: 1px solid #e9ecef; padding-bottom: 2px;">'
                        f'  <span>{col_left}</span>'
                        f'  <span>{col_right}</span>'
                        f'</div>'
                    )

                items_to_render = items
                overflow_count = 0
                if len(items) > 4 and not is_multi_category:
                    items_to_render = items[:3]
                    overflow_count = len(items) - 3
                elif len(items) > 2 and is_multi_category:
                    items_to_render = items[:2]
                    overflow_count = len(items) - 2

                for item in items_to_render:
                    badge_html = ""
                    if item.get("badge_text"):
                        badge_html = f'<span class="badge {item["badge_cls"]} ms-1" style="font-size: 0.68rem; padding: 2px 5px;">{item["badge_text"]}</span>'

                    val_cls = item.get("value_cls", "text-dark")
                    section_rows.append(
                        f'<div class="d-flex justify-content-between align-items-center py-1" style="font-size: 0.78rem; line-height: 1.3; border-bottom: 1px dashed #f0f0f0;">'
                        f'  <div class="text-truncate me-2" title="{item["label"]}">'
                        f'    <span class="fw-bold text-dark">{item["label"]}</span>{badge_html}'
                        f'  </div>'
                        f'  <div class="text-end fw-bold text-nowrap {val_cls}" style="font-size: 0.78rem;">{item["value"]}</div>'
                        f'</div>'
                    )

                if overflow_count > 0:
                    section_rows.append(
                        f'<div class="text-muted text-end fst-italic" style="font-size: 0.70rem;">+{overflow_count} more...</div>'
                    )

                html_sections.extend(section_rows)


            if html_sections:
                rec.kanban_breakdown_html = (
                    f'<div class="o_pbms_kanban_breakdown my-2 pt-1 border-top" style="max-height: 180px; overflow-y: auto;">'
                    + "".join(html_sections)
                    + '</div>'
                )
            else:
                rec.kanban_breakdown_html = False

    @api.depends("category", "line_ids.line_type", "plan_category_title", "org_unit_type")
    def _compute_plan_category_badge_html(self):
        badge_config = {
            "deposit": {"color": "#425727", "bg": "#EDF3E8", "border": "#C8DCB8", "icon": "fa-bank", "label": _("Deposit Mobilization")},
            "customer_base": {"color": "#726732", "bg": "#F7F5EB", "border": "#DDD5B8", "icon": "fa-users", "label": _("Customer Base Expansion")},
            "fx": {"color": "#C17540", "bg": "#FCF6F0", "border": "#F0D5C0", "icon": "fa-money", "label": _("FX Mobilization")},
            "digital_banking": {"color": "#541718", "bg": "#FBF2F2", "border": "#E5C5C5", "icon": "fa-mobile", "label": _("Digital Banking")},
            "general_expense": {"color": "#541718", "bg": "#FBF2F2", "border": "#E5C5C5", "icon": "fa-calculator", "label": _("General Expense")},
            "manpower": {"color": "#1E2917", "bg": "#EAECE8", "border": "#CCD3C5", "icon": "fa-id-badge", "label": _("Work Force")},
            "fixed_asset": {"color": "#726732", "bg": "#F7F5EB", "border": "#DDD5B8", "icon": "fa-building", "label": _("Fixed Asset Acquisition")},
        }

        for rec in self:
            cfg = badge_config.get(rec.category)
            if cfg:
                rec.plan_category_badge_html = (
                    f'<span class="badge rounded-pill px-2 py-1" style="background-color: {cfg["bg"]}; color: {cfg["color"]}; border: 1.5px solid {cfg["border"]}; font-size: 0.76rem; font-weight: 600;">'
                    f'<i class="fa {cfg["icon"]} me-1"/>{cfg["label"]}'
                    f'</span>'
                )
            else:
                title = rec.plan_category_title or _("Planning Category")
                rec.plan_category_badge_html = (
                    f'<span class="badge rounded-pill px-2 py-1 bg-light border" style="color: #541718; border-color: #CBD5E1 !important; font-size: 0.76rem; font-weight: 600;">'
                    f'<i class="fa fa-folder-open-o me-1"/>{title}'
                    f'</span>'
                )



    # ------------------------------------------------------------------
    # Archive/Unarchive methods
    # ------------------------------------------------------------------
    def action_archive(self):
        """Archive the planning category line"""
        user_unit_ids = self.env.user._pbms_operating_unit_ids()
        for rec in self:
            if not rec._pbms_can_delete_plan():
                if rec.org_unit_id and user_unit_ids and rec.org_unit_id.id not in user_unit_ids:
                    raise AccessError(_("You can only archive your own plans while they are still in draft or returned status."))
                if rec.state not in ('draft', 'returned'):
                    raise UserError(_(
                        "You can only archive plans in draft or returned state."
                    ))
        self.write({'active': False})

    def action_unarchive(self):
        """Unarchive the planning category line"""
        if not (self.env.is_admin() or self.env.user._pbms_is_sppmd_admin() or self.env.su):
            raise AccessError(_("Only SPPMD Administrators can restore archived plans."))
        self.write({'active': True})

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        org_unit_id = res.get("org_unit_id") or self.env.context.get("default_org_unit_id")
        ou = self.env["operating.unit"].browse(org_unit_id) if org_unit_id else self.env.user.default_operating_unit_id
        Config = self.env.get("pbms.planning.config")
        if "category" in fields_list:
            cur_cat = res.get("category")
            if not cur_cat or (Config is not None and ou and not Config.is_category_enabled(cur_cat, ou)):
                if Config is not None and ou:
                    res["category"] = Config.get_default_category_for_unit(ou)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        user_unit_ids = self.env.user._pbms_operating_unit_ids()
        for vals in vals_list:
            org_unit_id = vals.get("org_unit_id")
            if org_unit_id and user_unit_ids and org_unit_id not in user_unit_ids:
                if not (self.env.user._pbms_is_sppmd_admin() or self.env.user._pbms_is_sppmd_approver() or self.env.user._pbms_is_ho_reviewer() or self.env.user._pbms_is_district_reviewer()):
                    raise AccessError(_("You can only create plans for your own work unit(s)."))
            if not vals.get("category"):
                if self.env.context.get("default_category"):
                    vals["category"] = self.env.context["default_category"]
                elif self.env.context.get("category"):
                    vals["category"] = self.env.context["category"]
                elif self.env.context.get("default_line_type"):
                    vals["category"] = self.env.context["default_line_type"]
                elif self.env.context.get("line_type"):
                    vals["category"] = self.env.context["line_type"]

            # Extract category from notebook tab line fields in vals
            if not vals.get("category") or vals.get("category") == "deposit":
                for cat, fname in self._tab_line_fields.items():
                    if cat != "deposit" and vals.get(fname):
                        if not vals.get("deposit_line_ids"):
                            vals["category"] = cat
                            break

            # Extract category from line_ids commands in vals
            if not vals.get("category") and vals.get("line_ids"):
                for cmd in vals["line_ids"]:
                    if isinstance(cmd, (list, tuple)) and len(cmd) > 2 and isinstance(cmd[2], dict):
                        ltype = cmd[2].get("line_type")
                        if ltype:
                            vals["category"] = ltype
                            break

            # Extract category from workspace link fields
            if not vals.get("category"):
                for cat, fname in self._workspace_link_field.items():
                    if vals.get(fname):
                        vals["category"] = cat
                        break

            # Infer from category-specific fields
            if not vals.get("category"):
                if vals.get("base_type"):
                    vals["category"] = "customer_base"
                elif vals.get("fx_source_type"):
                    vals["category"] = "fx"
                elif vals.get("channel_id"):
                    vals["category"] = "digital_banking"
                elif vals.get("expense_account_id") or vals.get("is_office_rent"):
                    vals["category"] = "general_expense"
                elif vals.get("deposit_type_id") or vals.get("plan_category"):
                    vals["category"] = "deposit"

            # If category is disabled for this unit, re-assign to default enabled category or lines category
            Config = self.env.get("pbms.planning.config")
            ou = self.env["operating.unit"].browse(org_unit_id) if org_unit_id else self.env.user.default_operating_unit_id
            if Config is not None and ou and vals.get("category") and not Config.is_category_enabled(vals["category"], ou):
                found_cat = False
                for cat, fname in self._tab_line_fields.items():
                    if vals.get(fname) and Config.is_category_enabled(cat, ou):
                        found_cat = cat
                        break
                vals["category"] = found_cat or Config.get_default_category_for_unit(ou)

            # Default fallback if still not determined
            if not vals.get("category"):
                vals["category"] = Config.get_default_category_for_unit(ou) if (Config is not None and ou) else "deposit"

            # 1. Submitted Plan Check: Prevent creating another plan for the same category if already submitted or approved
            if org_unit_id and vals.get("cycle_id") and not self.env.context.get("skip_sync_category_records"):
                submitted_existing = self.search([
                    ("org_unit_id", "=", org_unit_id),
                    ("cycle_id", "=", vals.get("cycle_id")),
                    ("category", "=", vals.get("category")),
                    ("active", "=", True),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),
                ], limit=1)
                if submitted_existing:
                    unit_name = self.env["operating.unit"].browse(org_unit_id).display_name
                    cycle_name = self.env["pbms.planning.cycle"].browse(vals.get("cycle_id")).name
                    cat_name = dict(self._fields["category"].selection).get(vals.get("category"), vals.get("category"))
                    state_label = dict(self._fields["state"].selection).get(submitted_existing.state, submitted_existing.state)
                    raise ValidationError(_(
                        "A %(cat)s plan for %(unit)s in budget year '%(cycle)s' has already been submitted and is currently in '%(state)s' status.\n"
                        "Each operating unit can only have one plan per category per fiscal year. You cannot create a second plan while a plan is already submitted or approved.\n"
                        "If you need to make changes, request the reviewer to return the plan for revision or reset it to draft.",
                        cat=cat_name,
                        unit=unit_name,
                        cycle=cycle_name,
                        state=state_label,
                    ))

                # 2. Duplicate Plan Check: Ensure an operating unit creates only ONE plan per category per cycle
                existing = self.search([
                    ("org_unit_id", "=", org_unit_id),
                    ("cycle_id", "=", vals.get("cycle_id")),
                    ("category", "=", vals.get("category")),
                    ("active", "=", True),
                ], limit=1)
                if existing:
                    unit_name = self.env["operating.unit"].browse(org_unit_id).display_name
                    cycle_name = self.env["pbms.planning.cycle"].browse(vals.get("cycle_id")).name
                    cat_name = dict(self._fields["category"].selection).get(vals.get("category"), vals.get("category"))
                    raise ValidationError(_(
                        "A %(cat)s plan already exists for %(unit)s in budget year '%(cycle)s' (Request No: %(req)s).\n"
                        "Each work unit can only create one plan per category per fiscal year.\n"
                        "Please open and edit the existing %(cat)s plan instead of creating a duplicate.\n"
                        "(If you wish to create a new plan, please archive or delete the existing plan first).",
                        cat=cat_name,
                        unit=unit_name,
                        cycle=cycle_name,
                        req=existing.request_number or "N/A",
                    ))


            if "active" not in vals:
                vals["active"] = True


            if vals.get("request_number", "New") == "New" or not vals.get("request_number"):
                seq = False
                if vals.get("category") == "manpower":
                    seq = (
                        self.env["ir.sequence"].next_by_code("pbms.workforce.request")
                        or f"WFP/{fields.Date.today().year}/{self.search_count([('category', '=', 'manpower')]) + 1:05d}"
                    )
                else:
                    seq = (
                        self.env["ir.sequence"].next_by_code("pbms.planning.request")
                        or self.env["ir.sequence"].next_by_code("pbms.planning.category")
                        or f"REQ/{fields.Date.today().year}/{self.search_count([('category', '!=', 'manpower')]) + 1:05d}"
                    )
                vals["request_number"] = seq
        records = super().create(vals_list)
        for rec in records:
            if not rec.request_number or rec.request_number == "New":
                prefix = "WFP" if rec.category == "manpower" else "REQ"
                rec.request_number = f"{prefix}/{fields.Date.today().year}/{rec.id:05d}"
            elif rec.category == "manpower" and not rec.request_number.startswith("WFP/"):
                rec.request_number = (
                    self.env["ir.sequence"].next_by_code("pbms.workforce.request")
                    or f"WFP/{fields.Date.today().year}/{rec.id:05d}"
                )
            elif rec.category != "manpower" and rec.request_number.startswith("WFP/"):
                rec.request_number = (
                    self.env["ir.sequence"].next_by_code("pbms.planning.request")
                    or self.env["ir.sequence"].next_by_code("pbms.planning.category")
                    or f"REQ/{fields.Date.today().year}/{rec.id:05d}"
                )
            if (rec.category == "manpower" or rec.enable_manpower) and rec.org_unit_id:
                rec._sync_existing_manpower_lines()
        return records

    def write(self, vals):
        if "category" in vals and not self.env.context.get("bypass_plan_lock"):
            target_cat = vals["category"]
            for rec in self:
                if target_cat == "manpower" and rec.request_number and not rec.request_number.startswith("WFP/"):
                    vals["request_number"] = (
                        self.env["ir.sequence"].next_by_code("pbms.workforce.request")
                        or f"WFP/{fields.Date.today().year}/{rec.id:05d}"
                    )
                elif target_cat != "manpower" and rec.request_number and rec.request_number.startswith("WFP/"):
                    vals["request_number"] = (
                        self.env["ir.sequence"].next_by_code("pbms.planning.request")
                        or self.env["ir.sequence"].next_by_code("pbms.planning.category")
                        or f"REQ/{fields.Date.today().year}/{rec.id:05d}"
                    )

        if ("org_unit_id" in vals or "cycle_id" in vals or "category" in vals) and not self.env.context.get("skip_sync_category_records") and not self.env.context.get("bypass_plan_lock"):
            for rec in self:
                target_unit_id = vals.get("org_unit_id", rec.org_unit_id.id if rec.org_unit_id else False)
                target_cycle_id = vals.get("cycle_id", rec.cycle_id.id if rec.cycle_id else False)
                target_category = vals.get("category", rec.category)

                if target_unit_id and target_cycle_id and (target_unit_id != (rec.org_unit_id.id if rec.org_unit_id else False) or target_cycle_id != (rec.cycle_id.id if rec.cycle_id else False) or target_category != rec.category):
                    submitted_existing = self.search([
                        ("org_unit_id", "=", target_unit_id),
                        ("cycle_id", "=", target_cycle_id),
                        ("id", "not in", self.ids),
                        ("active", "=", True),
                        ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),
                    ], limit=1)
                    if submitted_existing and rec.state in ("draft", "returned", "info_requested"):
                        unit_name = self.env["operating.unit"].browse(target_unit_id).display_name
                        cycle_name = self.env["pbms.planning.cycle"].browse(target_cycle_id).name
                        state_label = dict(self._fields["state"].selection).get(submitted_existing.state, submitted_existing.state)
                        raise ValidationError(_(
                            "Cannot assign plan to %(unit)s in budget year '%(cycle)s' because a plan has already been submitted (Status: '%(state)s').",
                            unit=unit_name,
                            cycle=cycle_name,
                            state=state_label,
                        ))

                    category_existing = self.search([
                        ("org_unit_id", "=", target_unit_id),
                        ("cycle_id", "=", target_cycle_id),
                        ("category", "=", target_category),
                        ("id", "not in", self.ids),
                        ("active", "=", True),
                    ], limit=1)
                    if category_existing:
                        unit_name = self.env["operating.unit"].browse(target_unit_id).display_name
                        cycle_name = self.env["pbms.planning.cycle"].browse(target_cycle_id).name
                        cat_name = dict(self._fields["category"].selection).get(target_category, target_category)
                        raise ValidationError(_(
                            "A %(cat)s plan already exists for %(unit)s in budget year '%(cycle)s'.",
                            cat=cat_name,
                            unit=unit_name,
                            cycle=cycle_name,
                        ))

        res = super().write(vals)
        if "org_unit_id" in vals or "category" in vals:
            for rec in self:
                if (rec.category == "manpower" or rec.enable_manpower) and rec.org_unit_id and not rec.existing_manpower_summary_ids:
                    rec._sync_existing_manpower_lines()
        return res

    def copy(self, default=None):
        default = dict(default or {})
        for rec in self:
            target_unit_id = default.get("org_unit_id", rec.org_unit_id.id if rec.org_unit_id else False)
            target_cycle_id = default.get("cycle_id", rec.cycle_id.id if rec.cycle_id else False)
            if target_unit_id == (rec.org_unit_id.id if rec.org_unit_id else False) and target_cycle_id == (rec.cycle_id.id if rec.cycle_id else False):
                unit_name = rec.org_unit_id.display_name if rec.org_unit_id else ""
                cycle_name = rec.cycle_id.name if rec.cycle_id else ""
                raise ValidationError(_(
                    "Duplicating a plan for %(unit)s in the same budget year '%(cycle)s' is not allowed.\n"
                    "Each operating unit can only maintain one plan per fiscal year.",
                    unit=unit_name,
                    cycle=cycle_name,
                ))
        return super().copy(default=default)


    def unlink(self):
        user = self.env.user
        is_admin = self.env.is_admin() or user._pbms_is_sppmd_admin() or self.env.su
        user_unit_ids = user._pbms_operating_unit_ids()

        for rec in self:
            if not is_admin:
                if not rec._pbms_can_delete_plan():
                    if rec.org_unit_id and user_unit_ids and rec.org_unit_id.id not in user_unit_ids:
                        raise AccessError(_("You can only delete plans for your own work unit(s)."))
                    if rec.state != "draft":
                        raise UserError(_(
                            "Cannot delete a %s plan in state '%s'. Regular users can only delete plans while in Draft.",
                            rec.category, rec.state,
                        ))
        return super().unlink()

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not self.env.context.get("skip_cleanup_district_cards"):
            try:
                self.with_context(skip_cleanup_district_cards=True, skip_sync_category_records=True, bypass_plan_lock=True)._cleanup_duplicate_district_cards()
            except Exception:
                pass

        user = self.env.user
        # Scope filters for non-admin users
        if (
            not self.env.su
            and not bypass_access
            and not self.env.context.get("bypass_approver_branch_filter")
            and not user._pbms_is_sppmd_admin()
            and not self.env.is_admin()
        ):
            if user.has_group("bunna_pbms.group_pbms_approver"):
                approver_domain = [
                    "|",
                    ("category", "not in", ("deposit", "customer_base", "fx", "digital_banking")),
                    ("org_unit_type", "=", "head_office"),
                ]
                domain = expression.AND([domain, approver_domain])
            elif user.has_group("bunna_pbms.group_pbms_ho_reviewer"):
                # Head Office Functional Reviewers:
                # 1. Mobilization categories (Deposit, Customer Base, FX, Digital):
                #    view District Consolidated / HO plans (not individual branch plans).
                # 2. General Expense and Fixed Asset:
                #    branch plans must be approved by District Reviewer first before HO Reviewer can view.
                # 3. Head Office units are directly visible to HO Reviewers.
                ho_domain = [
                    "|",
                    ("org_unit_type", "=", "head_office"),
                    "|",
                    "&",
                    ("category", "in", ("deposit", "customer_base", "fx", "digital_banking")),
                    ("org_unit_type", "in", ("district_office", "regional_office")),
                    "|",
                    "&",
                    ("category", "=", "manpower"),
                    ("state", "in", ("ho_endorse", "cpco_endorse", "approved")),
                    "&",
                    ("category", "in", ("general_expense", "fixed_asset")),
                    ("state", "in", ("district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed", "approved")),
                ]
                domain = expression.AND([domain, ho_domain])

        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    # ------------------------------------------------------------------
    # Workflow methods
    # ------------------------------------------------------------------
    def _get_duplicate_domain(self):
        self.ensure_one()
        return super()._get_duplicate_domain() + [("category", "=", self.category), ("active", "=", True)]

    def _allow_negative_targets(self):
        return any(rec.category == "customer_base" and rec.base_type == "dormant_reduction" for rec in self)

    def _protected_write_fields(self):
        protected = list(MONTH_FIELDS)
        if any(c in ITEMIZED_CATEGORIES for c in self.mapped("category") if c):
            protected.append("line_ids")
        return protected

    def _ident_fields(self):
        cat = self.category if len(self) == 1 else (self.mapped("category")[0] if self else "deposit")
        return {
            "deposit": ["deposit_type_id", "plan_category"],
            "customer_base": ["deposit_type_id", "base_type"],
            "fx": ["fx_source_type"],
            "digital_banking": ["channel_id"],
            "general_expense": ["expense_account_id"],
        }.get(cat or "deposit", [])

    def _consolidation_search_domain(self):
        cats = [c for c in self.mapped("category") if c]
        base = [("active", "=", True), ("org_unit_type", "in", ("district_office", "head_office", "regional_office"))]
        if cats:
            return [("category", "in", cats)] + base
        return base
    @api.model
    def action_open_planning_request(self):
        """Open or create the active planning request for the current user's operating unit,
        opening the dedicated multi-tab Planning Request form with all category tabs."""
        user = self.env.user
        unit_ids = user._pbms_operating_unit_ids()
        org_unit = False
        if unit_ids:
            org_unit = self.env["operating.unit"].browse(unit_ids[0])
        elif hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
            org_unit = user.default_operating_unit_id
        else:
            org_unit = self.env["operating.unit"].search([], limit=1)

        cycle = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)
        if not cycle:
            pending_cycle = self.env["pbms.planning.cycle"].search([], order="date_start desc", limit=1)
            if pending_cycle:
                state_label = dict(pending_cycle._fields['state'].selection).get(pending_cycle.state, pending_cycle.state)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Planning Cycle Not Open for Input'),
                        'message': _(
                            "Planning cycle '%(name)s' is currently '%(state)s' and is not open for unit input. "
                            "Branch users cannot input or submit plan data until SPPMD officially opens the cycle for unit input."
                        ) % {'name': pending_cycle.name, 'state': state_label},
                        'type': 'warning',
                        'sticky': True,
                    }
                }
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Planning Cycle Open'),
                    'message': _('There is currently no active planning cycle open for plan and budget input.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        plan = False
        if org_unit and cycle:
            Config = self.env.get("pbms.planning.config")
            default_cat = Config.get_default_category_for_unit(org_unit) if Config is not None else "deposit"

            existing_plans = self.search([
                ("org_unit_id", "=", org_unit.id),
                ("cycle_id", "=", cycle.id),
                ("active", "=", True),
            ], order="id asc")

            # Clean up / archive any active plans that belong to a disabled category and have NO lines or data
            for ep in existing_plans:
                if Config is not None and not Config.is_category_enabled(ep.category, org_unit):
                    has_ep_data = bool(ep.line_ids) or bool(getattr(ep, "_get_category_lines", lambda c: False)(ep.category)) or (getattr(ep, "annual_total", 0.0) or 0.0) > 0.0
                    if not has_ep_data and ep.state in ("draft", "returned", "info_requested"):
                        try:
                            ep.sudo().with_context(bypass_plan_lock=True).unlink()
                        except Exception:
                            ep.sudo().with_context(bypass_plan_lock=True).write({"active": False})

            # Re-fetch active plans that are actually enabled in configuration
            enabled_plans = self.search([
                ("org_unit_id", "=", org_unit.id),
                ("cycle_id", "=", cycle.id),
                ("active", "=", True),
            ], order="id asc")
            if Config is not None:
                enabled_plans = enabled_plans.filtered(lambda p: Config.is_category_enabled(p.category, org_unit))

            # Select plan: prefer matching default_cat, or first enabled plan
            for p in enabled_plans:
                if p.category == default_cat:
                    plan = p
                    break
            if not plan and enabled_plans:
                plan = enabled_plans[0]

            if not plan:
                plan = self.sudo().create({
                    "org_unit_id": org_unit.id,
                    "cycle_id": cycle.id,
                    "company_id": org_unit.company_id.id if hasattr(org_unit, "company_id") and org_unit.company_id else self.env.company.id,
                    "category": default_cat,
                })
            else:
                # Consolidate any lines from sibling plan records for the same unit & cycle matching this category
                sibling_lines = self.env["pbms.plan.category.line"].search([
                    ("plan_id.org_unit_id", "=", org_unit.id),
                    ("plan_id.cycle_id", "=", cycle.id),
                    ("line_type", "=", plan.category),
                    ("plan_id", "!=", plan.id),
                ])
                if sibling_lines:
                    sibling_lines.write({"plan_id": plan.id})

        view = self.env.ref("bunna_pbms.view_pbms_planning_request_form", raise_if_not_found=False)
        view_id = view.id if view else False
        res = {
            "name": _("Planning Request"),
            "type": "ir.actions.act_window",
            "res_model": "pbms.planning.category",
            "view_mode": "form",
            "views": [(view_id, "form")],
            "target": "current",
            "context": dict(self.env.context, is_planning_request=True),
        }
        if plan:
            res["res_id"] = plan.id
        return res



    def get_formview_id(self, access_uid=None):
        """Return category-specific form view which sets the matching category tab as default."""
        Config = self.env.get("pbms.planning.config")
        default_cat = Config.get_default_category_for_unit(self.org_unit_id) if (Config is not None and self.org_unit_id) else "deposit"
        cat = self.category or self.env.context.get("default_category") or default_cat
        view_name = f"bunna_pbms.view_pbms_plan_form_{cat}"
        view = self.env.ref(view_name, raise_if_not_found=False)
        if view:
            return view.id
        base_view = self.env.ref("bunna_pbms.view_pbms_planning_category_form", raise_if_not_found=False)
        if base_view:
            return base_view.id
        return super().get_formview_id(access_uid=access_uid)

    def read(self, fields=None, load="_classic_read"):
        """Ensure all lines matching this card's category are attached to this card before reading for list/form views."""
        if not self.env.context.get("skip_read_line_attach"):
            Line = self.env["pbms.plan.category.line"].sudo()
            for rec in self:
                if rec.org_unit_id and rec.cycle_id and rec.category:
                    detached = Line.search([
                        ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                        ("plan_id.cycle_id", "=", rec.cycle_id.id),
                        ("line_type", "=", rec.category),
                        ("plan_id", "!=", rec.id),
                    ])
                    if detached:
                        detached = detached.filtered(lambda l: getattr(l.plan_id, "is_planning_request", False) or l.plan_id.category != rec.category)
                        if detached:
                            detached.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": rec.id})

        res = super().read(fields=fields, load=load)
        cat_field_map = {
            "deposit_line_ids": "deposit",
            "customer_base_line_ids": "customer_base",
            "fx_line_ids": "fx",
            "digital_banking_line_ids": "digital_banking",
            "expense_line_ids": "general_expense",
            "manpower_line_ids": "manpower",
            "fixed_asset_line_ids": "fixed_asset",
        }
        for rec, r_dict in zip(self, res):
            if not rec.org_unit_id or not rec.cycle_id:
                continue
            is_req = getattr(rec, "is_planning_request", False) or self.env.context.get("is_planning_request")
            for fname, cat in cat_field_map.items():
                if fname in r_dict and not r_dict[fname]:
                    if rec.category and rec.category != cat and not is_req:
                        continue
                    try:
                        sibling_lines = self.env["pbms.plan.category.line"].search([
                            ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                            ("plan_id.cycle_id", "=", rec.cycle_id.id),
                            ("line_type", "=", cat),
                            ("plan_id.active", "=", True),
                        ])
                        if sibling_lines:
                            r_dict[fname] = sibling_lines.ids
                    except Exception:
                        pass
        return res

    def get_formview_action(self, access_uid=None):
        """Return action to open the exact plan form clicked."""
        self.ensure_one()
        Config = self.env.get("pbms.planning.config")
        default_cat = Config.get_default_category_for_unit(self.org_unit_id) if (Config is not None and self.org_unit_id) else "deposit"
        cat = self.category or self.env.context.get("default_category") or default_cat
        view_id = self.get_formview_id(access_uid=access_uid)

        if self.org_unit_id and self.cycle_id and cat:
            detached = self.env["pbms.plan.category.line"].sudo().search([
                ("plan_id.org_unit_id", "=", self.org_unit_id.id),
                ("plan_id.cycle_id", "=", self.cycle_id.id),
                ("line_type", "=", cat),
                ("plan_id", "!=", self.id),
            ])
            if detached:
                detached = detached.filtered(lambda l: getattr(l.plan_id, "is_planning_request", False) or l.plan_id.category != cat)
                if detached:
                    detached.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": self.id})

        return {
            "name": self.display_name or _("Planning Category"),
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "views": [(view_id, "form")],
            "target": "current",
            "res_id": self.id,
            "context": dict(self.env.context, is_planning_request=False, default_category=cat),
        }















    def action_open_import_wizard(self):
        """Open the Excel import wizard pre-filled with this plan card's details."""
        self.ensure_one()
        return {
            "name": _("Import from Excel"),
            "type": "ir.actions.act_window",
            "res_model": "pbms.excel.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_plan_id": self.id,
                "default_cycle_id": self.cycle_id.id,
                "default_org_unit_id": self.org_unit_id.id,
                "default_format_type": self.category or "deposit",
            },
        }

    def action_export_excel(self):
        """Export active planning category card(s) and their detailed lines to Excel (.xlsx)
        using official Bunna Bank form templates (BB-APF-27, BB-APF-21, BB-APF-19, and District Consolidations).
        """
        records = self
        if not records:
            active_ids = self.env.context.get("active_ids")
            if active_ids:
                records = self.browse(active_ids)
            else:
                active_id = self.env.context.get("active_id")
                if active_id:
                    records = self.browse([active_id])
        if not records:
            raise UserError(_("No planning records selected for export."))

        import base64
        import io
        import re
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        # Base formatting
        fmt_bank_title = wb.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#541718', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_doc_title = wb.add_format({
            'bold': True, 'font_size': 12, 'font_color': '#541718', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_fy_title = wb.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#541718', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_work_units_title = wb.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#541718', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_form_code = wb.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#541718', 'font_name': 'Segoe UI',
            'align': 'left', 'valign': 'vcenter'
        })
        fmt_banner_sage = wb.add_format({
            'bold': True, 'font_size': 13, 'font_color': '#FFFFFF', 'font_name': 'Segoe UI',
            'bg_color': '#541718', 'align': 'left', 'valign': 'vcenter'
        })
        fmt_th = wb.add_format({
            'bold': True, 'bg_color': '#541718', 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True, 'border': 1, 'border_color': '#3D1011'
        })
        fmt_cell_text = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter',
            'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_text_indent = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter',
            'indent': 2, 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_int = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0', 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_num = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0.00', 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_num_acc = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)',
            'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_num_no_dec = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0', 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_date = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'center',
            'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_tot_label = wb.add_format({
            'bold': True, 'bg_color': '#541718', 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'left',
            'border': 1, 'border_color': '#3D1011'
        })
        fmt_tot_int = wb.add_format({
            'bold': True, 'bg_color': '#541718', 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0', 'border': 1, 'border_color': '#3D1011'
        })
        fmt_tot_num = wb.add_format({
            'bold': True, 'bg_color': '#541718', 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0.00', 'border': 1, 'border_color': '#3D1011'
        })
        fmt_dist_subtotal_label = wb.add_format({
            'bold': True, 'font_size': 9, 'font_name': 'Segoe UI',
            'valign': 'vcenter', 'border': 1, 'border_color': '#B0B0B0', 'top': 1, 'bottom': 1
        })
        fmt_dist_subtotal_num = wb.add_format({
            'bold': True, 'font_size': 9, 'font_name': 'Segoe UI',
            'valign': 'vcenter', 'align': 'right', 'num_format': '#,##0.00',
            'border': 1, 'border_color': '#B0B0B0', 'top': 1, 'bottom': 1
        })
        fmt_dist_subtotal_int = wb.add_format({
            'bold': True, 'font_size': 9, 'font_name': 'Segoe UI',
            'valign': 'vcenter', 'align': 'right', 'num_format': '#,##0',
            'border': 1, 'border_color': '#B0B0B0', 'top': 1, 'bottom': 1
        })

        # Determine fiscal cycle name
        primary_cycle = records[0].cycle_id if records else False
        cycle_name = primary_cycle.name if primary_cycle and primary_cycle.name else "2026/27"

        # Determine dynamic month names e.g. Jul-26 .. Jun-27
        y1, y2 = "26", "27"
        nums = re.findall(r"\d+", cycle_name)
        if len(nums) >= 2:
            y1 = nums[0][-2:]
            y2 = nums[1][-2:]
            clean_fy = f"{nums[0]}/{nums[1]}" if len(nums[0]) == 4 else f"20{y1}/{y2}"
        elif len(nums) == 1 and len(nums[0]) == 4:
            start_y = int(nums[0])
            y1 = str(start_y)[-2:]
            y2 = str(start_y + 1)[-2:]
            clean_fy = f"{start_y}/{y2}"
        else:
            y1 = "26"
            y2 = "27"
            clean_fy = "2026/27"
        month_headers = [
            f"Jul-{y1}", f"Aug-{y1}", f"Sep-{y1}",
            f"Oct-{y1}", f"Nov-{y1}", f"Dec-{y1}",
            f"Jan-{y2}", f"Feb-{y2}", f"Mar-{y2}",
            f"Apr-{y2}", f"May-{y2}", f"Jun-{y2}",
        ]

        def get_meta(line, rec):
            unit = line.source_unit_id or line.org_unit_id or (rec.org_unit_id if rec else False)
            unit_name = unit.name if unit else ""
            sol_id = line.sol_id or (unit.sol_id if unit and hasattr(unit, "sol_id") else 0)

            district_name = ""
            if line.district_id:
                district_name = line.district_id.name
            elif rec and rec.district_id:
                district_name = rec.district_id.name
            elif unit and unit.parent_unit:
                district_name = unit.parent_unit.name

            wtype = (unit.work_unit_type if unit else False) or line.org_unit_type or (rec.org_unit_type if rec else "")
            if wtype == "head_office" and not district_name:
                district_name = unit.parent_unit.name if unit and unit.parent_unit else "Head Office"

            if line.broad_category:
                broad_cat = line.broad_category
            elif wtype in ("branch", "sub_branch", "service_center"):
                broad_cat = "1.Branches"
            elif wtype in ("district_office", "regional_office"):
                broad_cat = "2.District Office"
            elif wtype == "head_office":
                broad_cat = "3.Head Office"
            else:
                broad_cat = "1.Branches"

            return sol_id, unit_name, district_name, broad_cat

        def get_banner_unit_title(plans, default_text="District and Head Office"):
            if len(plans) == 1 and plans[0].org_unit_type in ("branch", "sub_branch", "service_center"):
                return plans[0].org_unit_id.name or "Branch Plan"
            return default_text

        # Target records: prioritize district/HO records if selected, otherwise export all selected plans (including branch plans)
        consolidated_records = records.filtered(lambda p: p.org_unit_type in ("district_office", "head_office", "regional_office"))
        target_records = consolidated_records if consolidated_records else records

        # Group plans by category
        plans_by_cat = {}
        for rec in target_records:
            cat = rec.category or "deposit"
            if cat not in plans_by_cat:
                plans_by_cat[cat] = self.env["pbms.planning.category"]
            plans_by_cat[cat] |= rec

        for cat, cat_plans in plans_by_cat.items():
            if cat == "fixed_asset":
                ws = wb.add_worksheet("Fixed Asset (BB-APF-27)")
                ws.freeze_panes(6, 4)
                ws.merge_range(0, 0, 0, 10, "Bunna Bank", fmt_bank_title)
                ws.merge_range(1, 0, 1, 10, "Property and Equipment", fmt_doc_title)
                ws.merge_range(2, 0, 2, 10, f"For the FY {clean_fy}", fmt_fy_title)
                ws.merge_range(3, 0, 3, 10, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)
                ws.write(4, 0, "BB-APF-27", fmt_form_code)

                headers = [
                    "SOL ID", "Work Unit Name", "Districts", "Broad Category", "Nature of the Request",
                    "Fixed Asset Category*", "Item Description*", "Users Position or Purpose of the Item",
                    "Qty", "Estimated Unit Price", "Estimated Total Price"
                ]
                for ci, h in enumerate(headers):
                    ws.write(5, ci, h, fmt_th)

                row_cur = 6
                for p in cat_plans:
                    lines = p.fixed_asset_line_ids or p.line_ids.filtered(lambda l: l.line_type == "fixed_asset")
                    for l in lines:
                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)
                        nat = "New" if (l.nature or "new") == "new" else "Replacement"
                        cat_name = l.category_id.name or ""
                        item_desc = l.item_description or ""
                        purpose_str = l.purpose.name if l.purpose else (l.other_justification or "")
                        qty = int(round(l.quantity or (l.fa_q1 or 0) + (l.fa_q2 or 0) + (l.fa_q3 or 0) + (l.fa_q4 or 0)))
                        unit_price = l.estimated_unit_price or 0.0
                        tot_price = l.fa_annual_total_cost or (qty * unit_price)

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)
                        ws.write(row_cur, 1, unit_name, fmt_cell_text)
                        ws.write(row_cur, 2, district_name, fmt_cell_text)
                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)
                        ws.write(row_cur, 4, nat, fmt_cell_text)
                        ws.write(row_cur, 5, cat_name, fmt_cell_text)
                        ws.write(row_cur, 6, item_desc, fmt_cell_text)
                        ws.write(row_cur, 7, purpose_str, fmt_cell_text)
                        ws.write(row_cur, 8, qty, fmt_cell_int)
                        ws.write(row_cur, 9, unit_price, fmt_cell_num_no_dec)
                        ws.write(row_cur, 10, tot_price, fmt_cell_num_no_dec)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                for ci in range(1, 8):
                    ws.write(row_cur, ci, "", fmt_tot_label)
                if row_cur > 6:
                    ws.write_formula(row_cur, 8, f"=SUM(I7:I{row_cur})", fmt_tot_int)
                    ws.write(row_cur, 9, "", fmt_tot_label)
                    ws.write_formula(row_cur, 10, f"=SUM(K7:K{row_cur})", fmt_tot_num)
                else:
                    ws.write(row_cur, 8, 0, fmt_tot_int)
                    ws.write(row_cur, 9, "", fmt_tot_label)
                    ws.write(row_cur, 10, 0.0, fmt_tot_num)

                ws.set_column(0, 0, 10)
                ws.set_column(1, 1, 26)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 16)
                ws.set_column(4, 4, 20)
                ws.set_column(5, 5, 26)
                ws.set_column(6, 6, 28)
                ws.set_column(7, 7, 30)
                ws.set_column(8, 8, 10)
                ws.set_column(9, 9, 18)
                ws.set_column(10, 10, 20)

            elif cat == "general_expense":
                ws = wb.add_worksheet("Expense (BB-APF-21)")
                ws.freeze_panes(6, 5)
                ws.merge_range(0, 0, 0, 18, "Bunna Bank", fmt_bank_title)
                ws.merge_range(1, 0, 1, 18, "General Expense Budget", fmt_doc_title)
                ws.merge_range(2, 0, 2, 18, f"for the FY {clean_fy}", fmt_fy_title)
                ws.merge_range(3, 0, 3, 18, get_banner_unit_title(cat_plans, "District and Head Office (HO-DO)"), fmt_work_units_title)
                ws.write(4, 0, "BB-APF-21", fmt_form_code)

                headers = ["Sol ID", "Work Units Name", "Districts Name", "Broad Category", "Description"] + month_headers + ["Annual", "Remark"]
                for ci, h in enumerate(headers):
                    ws.write(5, ci, h, fmt_th)

                row_cur = 6
                for p in cat_plans:
                    lines = p.expense_line_ids or p.line_ids.filtered(lambda l: l.line_type == "general_expense")
                    for l in lines:
                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)
                        desc = l.expense_account_id.name or ""
                        m_vals = [l.m01 or 0.0, l.m02 or 0.0, l.m03 or 0.0, l.m04 or 0.0, l.m05 or 0.0, l.m06 or 0.0,
                                  l.m07 or 0.0, l.m08 or 0.0, l.m09 or 0.0, l.m10 or 0.0, l.m11 or 0.0, l.m12 or 0.0]
                        ann = l.proposed_annual_total or l.annual_total or sum(m_vals)
                        rem = l.other_justification or getattr(l, "reason", "") or ""

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)
                        ws.write(row_cur, 1, unit_name, fmt_cell_text)
                        ws.write(row_cur, 2, district_name, fmt_cell_text)
                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)
                        ws.write(row_cur, 4, desc, fmt_cell_text)
                        for mi, mv in enumerate(m_vals):
                            ws.write(row_cur, 5 + mi, mv, fmt_cell_num_acc)
                        ws.write(row_cur, 17, ann, fmt_tot_num if ann > 0 else fmt_cell_num_acc)
                        ws.write(row_cur, 18, rem, fmt_cell_text)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                for ci in range(1, 5):
                    ws.write(row_cur, ci, "", fmt_tot_label)
                if row_cur > 6:
                    for ci in range(5, 18):
                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)
                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)
                else:
                    for ci in range(5, 18):
                        ws.write(row_cur, ci, 0.0, fmt_tot_num)
                ws.write(row_cur, 18, "", fmt_tot_label)

                ws.set_column(0, 0, 10)
                ws.set_column(1, 1, 24)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 16)
                ws.set_column(4, 4, 26)
                for ci in range(5, 17):
                    ws.set_column(ci, ci, 13)
                ws.set_column(17, 17, 16)
                ws.set_column(18, 18, 22)

            elif cat == "manpower":
                ws = wb.add_worksheet("Manpower (BB-APF-19)")
                ws.freeze_panes(6, 4)
                ws.merge_range(0, 0, 0, 10, "Bunna Bank", fmt_bank_title)
                ws.merge_range(1, 0, 1, 10, "Proposed New or Vacant Post", fmt_doc_title)
                ws.merge_range(2, 0, 2, 10, f"for the FY {clean_fy}", fmt_fy_title)
                ws.merge_range(3, 0, 3, 10, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)
                ws.write(4, 0, "BB-APF-19", fmt_form_code)

                headers = [
                    "SOL ID", "Work Unit Name", "Districts Name", "Broad Category", "Type of Position",
                    "Type of Employment", "Job Title", "Job Grade", "Qty", "Date Needed", "Reason for the Proposed"
                ]
                for ci, h in enumerate(headers):
                    ws.write(5, ci, h, fmt_th)

                row_cur = 6
                for p in cat_plans:
                    lines = p.manpower_line_ids or p.line_ids.filtered(lambda l: l.line_type == "manpower")
                    for l in lines:
                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)
                        pos_type = (l.employee_category_id.display_name if l.employee_category_id else (l.position_type_id.name if l.position_type_id else (dict(l._fields['position_type'].selection).get(l.position_type, 'Non-Managerial'))))
                        emp_type = (dict(l._fields['employment_type'].selection).get(l.employment_type, l.employment_type)) if l.employment_type else 'Permanent'
                        job_title = l.job_id.name if l.job_id else (l.new_job_title or "")
                        grade_str = (l.job_grade_id.grade_code or l.job_grade_id.display_name) if l.job_grade_id else (l.new_job_grade_id.grade_code or l.new_job_grade_id.display_name or l.new_job_grade or "")
                        qty = int(round(l.annual_total or l.quantity or 0))
                        date_str = l.date_needed.strftime('%d-%b-%y') if l.date_needed else f"1-Jul-{y1}"
                        reason_str = l.other_justification or (l.justification_category_id.display_name if l.justification_category_id else getattr(l, "reason", "")) or (dict(l._fields['position_type'].selection).get(l.position_type, 'New'))

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)
                        ws.write(row_cur, 1, unit_name, fmt_cell_text)
                        ws.write(row_cur, 2, district_name, fmt_cell_text)
                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)
                        ws.write(row_cur, 4, pos_type, fmt_cell_text)
                        ws.write(row_cur, 5, emp_type, fmt_cell_text)
                        ws.write(row_cur, 6, job_title, fmt_cell_text)
                        ws.write(row_cur, 7, grade_str, fmt_cell_text)
                        ws.write(row_cur, 8, qty, fmt_cell_int)
                        ws.write(row_cur, 9, date_str, fmt_cell_date)
                        ws.write(row_cur, 10, reason_str, fmt_cell_text)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                for ci in range(1, 8):
                    ws.write(row_cur, ci, "", fmt_tot_label)
                if row_cur > 6:
                    ws.write_formula(row_cur, 8, f"=SUM(I7:I{row_cur})", fmt_tot_int)
                else:
                    ws.write(row_cur, 8, 0, fmt_tot_int)
                ws.write(row_cur, 9, "", fmt_tot_label)
                ws.write(row_cur, 10, "", fmt_tot_label)

                ws.set_column(0, 0, 10)
                ws.set_column(1, 1, 22)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 16)
                ws.set_column(4, 4, 18)
                ws.set_column(5, 5, 18)
                ws.set_column(6, 6, 26)
                ws.set_column(7, 7, 12)
                ws.set_column(8, 8, 10)
                ws.set_column(9, 9, 16)
                ws.set_column(10, 10, 26)

            elif cat in ("deposit", "customer_base"):
                title = f"Deposit Plan by District and Deposit Type for the FY {clean_fy}" if cat == "deposit" else f"Customer Base Plan by District and Customer Type for the FY {clean_fy}"
                sheet_name = "Deposit by District" if cat == "deposit" else "Customer Base by District"
                ws = wb.add_worksheet(sheet_name)
                ws.freeze_panes(2, 1)
                ws.merge_range(0, 0, 0, 13, title, fmt_banner_sage)

                headers = ["Row Labels"] + month_headers + ["Annual Target"]
                for ci, h in enumerate(headers):
                    ws.write(1, ci, h, fmt_th)

                is_int = (cat == "customer_base")
                val_fmt = fmt_cell_int if is_int else fmt_cell_num_no_dec
                dist_val_fmt = fmt_dist_subtotal_int if is_int else fmt_dist_subtotal_num
                tot_val_fmt = fmt_tot_int if is_int else fmt_tot_num

                all_lines = cat_plans.mapped("deposit_line_ids" if cat == "deposit" else "customer_base_line_ids")
                if not all_lines:
                    all_lines = cat_plans.mapped("line_ids").filtered(lambda l: l.line_type == cat)

                dist_dict = {}
                for l in all_lines:
                    dist = l.district_id or l.plan_id.district_id or (l.source_unit_id.parent_unit if l.source_unit_id else False) or l.org_unit_id
                    dist_sol = dist.sol_id if dist and hasattr(dist, "sol_id") and dist.sol_id else (l.sol_id or 900)
                    dist_name = dist.name if dist else "General District"
                    dist_key = (dist_sol, dist_name)
                    if dist_key not in dist_dict:
                        dist_dict[dist_key] = {}

                    dtype = l.deposit_type_id
                    raw_name = dtype.name or ""
                    if (dtype and dtype.is_ifb) or "IFB" in raw_name.upper():
                        prod = "IFB"
                    elif "DEMAND" in raw_name.upper() or (dtype and dtype.code == "DEM"):
                        prod = "Demand"
                    elif "SAVING" in raw_name.upper() or (dtype and dtype.code == "SAV"):
                        prod = "Saving"
                    else:
                        prod = raw_name or "Demand"

                    if prod not in dist_dict[dist_key]:
                        dist_dict[dist_key][prod] = [0.0] * 12

                    dist_dict[dist_key][prod][0] += (l.m01 or 0.0)
                    dist_dict[dist_key][prod][1] += (l.m02 or 0.0)
                    dist_dict[dist_key][prod][2] += (l.m03 or 0.0)
                    dist_dict[dist_key][prod][3] += (l.m04 or 0.0)
                    dist_dict[dist_key][prod][4] += (l.m05 or 0.0)
                    dist_dict[dist_key][prod][5] += (l.m06 or 0.0)
                    dist_dict[dist_key][prod][6] += (l.m07 or 0.0)
                    dist_dict[dist_key][prod][7] += (l.m08 or 0.0)
                    dist_dict[dist_key][prod][8] += (l.m09 or 0.0)
                    dist_dict[dist_key][prod][9] += (l.m10 or 0.0)
                    dist_dict[dist_key][prod][10] += (l.m11 or 0.0)
                    dist_dict[dist_key][prod][11] += (l.m12 or 0.0)

                row_cur = 2
                std_prods = ["Demand", "IFB", "Saving"]
                grand_months = [0.0] * 12
                grand_annual = 0.0

                for (dsol, dname) in sorted(dist_dict.keys(), key=lambda x: (x[0], x[1])):
                    prod_data = dist_dict[(dsol, dname)]
                    dist_months = [0.0] * 12
                    for p_name, p_vals in prod_data.items():
                        for mi in range(12):
                            dist_months[mi] += p_vals[mi]
                    dist_annual = sum(dist_months)

                    ws.write(row_cur, 0, f"[-] {dsol} {dname.upper()}", fmt_dist_subtotal_label)
                    for mi in range(12):
                        ws.write(row_cur, 1 + mi, dist_months[mi], dist_val_fmt)
                        grand_months[mi] += dist_months[mi]
                    ws.write(row_cur, 13, dist_annual, dist_val_fmt)
                    grand_annual += dist_annual
                    row_cur += 1

                    sorted_prods = [p for p in std_prods if p in prod_data] + [p for p in prod_data if p not in std_prods]
                    for p in sorted_prods:
                        p_vals = prod_data[p]
                        p_annual = sum(p_vals)
                        ws.write(row_cur, 0, f"    {p}", fmt_cell_text_indent)
                        for mi in range(12):
                            ws.write(row_cur, 1 + mi, p_vals[mi], val_fmt)
                        ws.write(row_cur, 13, p_annual, val_fmt)
                        row_cur += 1

                ws.write(row_cur, 0, "Total", fmt_tot_label)
                for mi in range(12):
                    ws.write(row_cur, 1 + mi, grand_months[mi], tot_val_fmt)
                ws.write(row_cur, 13, grand_annual, tot_val_fmt)

                ws.set_column(0, 0, 32)
                for ci in range(1, 13):
                    ws.set_column(ci, ci, 14 if cat == "deposit" else 12)
                ws.set_column(13, 13, 18 if cat == "deposit" else 16)

            else:
                # FX or Digital Banking
                cat_title = "FX Mobilization" if cat == "fx" else "Digital Banking"
                ws = wb.add_worksheet(cat_title)
                ws.freeze_panes(6, 4)
                ws.merge_range(0, 0, 0, 16, "Bunna Bank", fmt_bank_title)
                ws.merge_range(1, 0, 1, 16, cat_title, fmt_doc_title)
                ws.merge_range(2, 0, 2, 16, f"For the FY {clean_fy}", fmt_fy_title)
                ws.merge_range(3, 0, 3, 16, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                item_label = "FX Source" if cat == "fx" else "Digital Channel"
                headers = ["Sol ID", "Work Unit Name", "Districts Name", "Broad Category", item_label] + month_headers + ["Annual Target"]
                for ci, h in enumerate(headers):
                    ws.write(5, ci, h, fmt_th)

                row_cur = 6
                for p in cat_plans:
                    lines = p.fx_line_ids if cat == "fx" else p.digital_banking_line_ids
                    for l in lines:
                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)
                        item_val = (l.fx_source_type.name if cat == "fx" else l.channel_id.name) or ""
                        m_vals = [l.m01 or 0.0, l.m02 or 0.0, l.m03 or 0.0, l.m04 or 0.0, l.m05 or 0.0, l.m06 or 0.0,
                                  l.m07 or 0.0, l.m08 or 0.0, l.m09 or 0.0, l.m10 or 0.0, l.m11 or 0.0, l.m12 or 0.0]
                        ann = l.proposed_annual_total or l.annual_total or sum(m_vals)

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)
                        ws.write(row_cur, 1, unit_name, fmt_cell_text)
                        ws.write(row_cur, 2, district_name, fmt_cell_text)
                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)
                        ws.write(row_cur, 4, item_val, fmt_cell_text)
                        for mi, mv in enumerate(m_vals):
                            ws.write(row_cur, 5 + mi, mv, fmt_cell_num)
                        ws.write(row_cur, 17, ann, fmt_tot_num)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                for ci in range(1, 5):
                    ws.write(row_cur, ci, "", fmt_tot_label)
                if row_cur > 6:
                    for ci in range(5, 18):
                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)
                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)
                else:
                    for ci in range(5, 18):
                        ws.write(row_cur, ci, 0.0, fmt_tot_num)

                ws.set_column(0, 0, 10)
                ws.set_column(1, 1, 24)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 16)
                ws.set_column(4, 4, 24)
                for ci in range(5, 17):
                    ws.set_column(ci, ci, 13)
                ws.set_column(17, 17, 16)

        wb.close()
        output.seek(0)
        file_data = output.getvalue()

        if len(records) == 1:
            rec = records[0]
            cat_name = (rec.category or "Plan").replace("_", " ").title().replace(" ", "_")
            unit_name = (rec.org_unit_id.name or "Unit").replace(" ", "_")
            cycle_str = (rec.cycle_id.name or "Cycle").replace(" ", "_").replace("/", "-")
            file_name = f"PBMS_{cat_name}_{unit_name}_{cycle_str}.xlsx"
        else:
            file_name = f"PBMS_Consolidated_Planning_Export_{cycle_name.replace('/', '-')}.xlsx"

        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(file_data),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def action_open_plan_form(self):
        """Action invoked when clicking on a plan card in Kanban or a record link."""
        self.ensure_one()
        return self.get_formview_action()

    def action_view_attached_branch_plans(self):
        """Smart button action to view all branch plans attached to this district."""
        self.ensure_one()
        district = self.org_unit_id if self.org_unit_type == "district_office" else self.district_id
        return {
            "name": _("Branch Plans - %s") % (district.display_name if district else ""),
            "type": "ir.actions.act_window",
            "res_model": "pbms.planning.category",
            "view_mode": "list,kanban,form,pivot",
            "domain": [
                ("cycle_id", "=", self.cycle_id.id),
                ("district_id", "=", district.id if district else False),
                ("org_unit_id", "!=", district.id if district else False),
                ("active", "=", True),
            ],
            "context": dict(self.env.context, default_cycle_id=self.cycle_id.id, default_district_id=district.id if district else False),
        }

    def action_view_district_overview_plans(self):
        """Smart button action to view all 5 district overview plans at Bank level."""
        self.ensure_one()
        return {
            "name": _("District Overview Plans"),
            "type": "ir.actions.act_window",
            "res_model": "pbms.planning.category",
            "view_mode": "list,kanban,form,pivot",
            "domain": [
                ("cycle_id", "=", self.cycle_id.id),
                ("org_unit_type", "=", "district_office"),
                ("active", "=", True),
            ],
            "context": dict(self.env.context, default_cycle_id=self.cycle_id.id),
        }

    def action_view_branch_details(self):
        """Action for Head Office Reviewer / District to inspect branch-by-branch details of a category in this district."""
        self.ensure_one()
        target_category = self.env.context.get("target_category") or "deposit"
        district = self.org_unit_id if self.org_unit_type == "district_office" else (self.district_id or self.org_unit_id)
        category_titles = {
            "deposit": _("Deposit Mobilization"),
            "customer_base": _("Customer Base"),
            "fx": _("FX Mobilization"),
            "digital_banking": _("Digital Banking"),
            "general_expense": _("General Expense Budget"),
            "manpower": _("Workforce / Manpower Plan"),
            "fixed_asset": _("Fixed Asset Requirement"),
        }
        title = _("Branch Details - %s (%s)") % (category_titles.get(target_category, target_category), district.display_name if district else "")
        list_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_list", raise_if_not_found=False)
        pivot_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_pivot", raise_if_not_found=False)
        views = []
        if list_view:
            views.append((list_view.id, "list"))
        if pivot_view:
            views.append((pivot_view.id, "pivot"))

        return {
            "name": title,
            "type": "ir.actions.act_window",
            "res_model": "pbms.plan.category.line",
            "view_mode": "list,pivot,graph",
            "views": views if views else False,
            "domain": [
                ("cycle_id", "=", self.cycle_id.id),
                ("district_id", "=", district.id if district else False),
                ("org_unit_type", "in", ("branch", "sub_branch")),
                ("line_type", "=", target_category),
            ],
            "context": {
                "search_default_group_by_org_unit": 1,
                "group_by": ["org_unit_id"],
            },
        }

    def action_view_district_details(self):
        """Action for Final Approver / Head Office Reviewers to inspect district-by-district breakdown across all districts."""
        self.ensure_one()
        target_category = self.env.context.get("target_category") or "deposit"
        category_titles = {
            "deposit": _("Deposit Mobilization"),
            "customer_base": _("Customer Base"),
            "fx": _("FX Mobilization"),
            "digital_banking": _("Digital Banking"),
            "general_expense": _("General Expense Budget"),
            "manpower": _("Workforce / Manpower Plan"),
            "fixed_asset": _("Fixed Asset Requirement"),
        }
        title = _("District Breakdown - %s") % category_titles.get(target_category, target_category)
        list_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_list", raise_if_not_found=False)
        pivot_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_pivot", raise_if_not_found=False)
        views = []
        if list_view:
            views.append((list_view.id, "list"))
        if pivot_view:
            views.append((pivot_view.id, "pivot"))

        return {
            "name": title,
            "type": "ir.actions.act_window",
            "res_model": "pbms.plan.category.line",
            "view_mode": "list,pivot,graph",
            "views": views if views else False,
            "domain": [
                ("cycle_id", "=", self.cycle_id.id),
                ("org_unit_type", "=", "district_office"),
                ("line_type", "=", target_category),
            ],
            "context": {
                "search_default_group_by_org_unit": 1,
                "group_by": ["org_unit_id"],
            },
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @api.constrains("category")
    def _check_required_identifiers(self):
        for rec in self:
            category_label = dict(self._fields["category"].selection)
            for fname in CATEGORY_REQUIRED_FIELDS.get(rec.category, []):
                if not getattr(rec, fname):
                    raise ValidationError(_(
                        "'%(field)s' is required for %(category)s plans.",
                        field=rec._fields[fname].string,
                        category=category_label.get(rec.category),
                    ))

    @api.constrains("fx_source_type", "org_unit_id")
    def _check_swift_head_office_only(self):
        for rec in self:
            if (rec.category == "fx" and rec.fx_source_type
                    and rec.fx_source_type.code == "SWIFT"
                    and rec.org_unit_id.work_unit_type != "head_office"):
                raise ValidationError(_(
                    "Remittance-SWIFT targets are planned at Head Office / "
                    "corporate level only, not per branch or district."))

    @api.constrains("plan_category", *MONTH_FIELDS)
    def _check_account_category_is_whole_number(self):
        for rec in self:
            if rec.category == "deposit" and rec.plan_category == "account":
                for fname in MONTH_FIELDS:
                    val = getattr(rec, fname) or 0.0
                    if val != int(val):
                        raise ValidationError(_(
                            "Account/customer-base targets must be whole numbers "
                            "(got %(val)s for %(month)s).",
                            val=val, month=fname))



    @api.constrains("cycle_id", "org_unit_id", "category", "active", "state")
    def _check_unique_plan_per_unit_cycle(self):
        for rec in self:
            if not rec.active or not rec.org_unit_id or not rec.cycle_id:
                continue

            # 1. No two active cards of the exact same category for the same unit & cycle
            rec_id = rec._origin.id if (hasattr(rec, "_origin") and rec._origin) else (rec.id if isinstance(rec.id, int) else False)
            domain = [
                ("org_unit_id", "=", rec.org_unit_id.id),
                ("cycle_id", "=", rec.cycle_id.id),
                ("category", "=", rec.category),
                ("active", "=", True),
            ]
            if rec_id:
                domain.append(("id", "!=", rec_id))
            duplicate_cat = self.sudo().search(domain, limit=1)
            if duplicate_cat:
                unit_name = rec.org_unit_id.display_name
                cycle_name = rec.cycle_id.name
                cat_name = dict(self._fields["category"].selection).get(rec.category, rec.category)
                raise ValidationError(_(
                    "A %(cat)s plan already exists for %(unit)s in budget year '%(cycle)s' (Request: %(req)s). "
                    "Each work unit can only have one plan per category per fiscal year.",
                    cat=cat_name,
                    unit=unit_name,
                    cycle=cycle_name,
                    req=duplicate_cat.request_number or "N/A",
                ))

            # 2. If this record is in draft, check if another record for this unit & cycle & category is already submitted/approved
            if rec.state in ("draft", "returned", "info_requested") and rec.category:
                sub_domain = [
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("category", "=", rec.category),
                    ("active", "=", True),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),
                ]
                if rec_id:
                    sub_domain.append(("id", "!=", rec_id))
                submitted_plan = self.sudo().search(sub_domain, limit=1)
                if submitted_plan:
                    unit_name = rec.org_unit_id.display_name
                    cycle_name = rec.cycle_id.name
                    state_label = dict(self._fields["state"].selection).get(submitted_plan.state, submitted_plan.state)
                    raise ValidationError(_(
                        "A plan for %(unit)s in budget year '%(cycle)s' has already been submitted (Status: '%(state)s'). "
                        "You cannot maintain a second draft plan for the same fiscal year.",
                        unit=unit_name,
                        cycle=cycle_name,
                        state=state_label,
                    ))


    # ------------------------------------------------------------------
    # Consolidation helpers
    # ------------------------------------------------------------------
    @api.model
    def _line_vals(self, line, org_unit):
        """Create values for consolidating a line"""
        vals = {
            "source_unit_id": org_unit.id if org_unit else False,
            "quantity": line.quantity,
            "position_type": line.position_type,
            "employment_type": line.employment_type,
            "job_id": line.job_id.id if line.job_id else False,
            "job_grade_id": line.job_grade_id.id if line.job_grade_id else False,
            "employee_category_id": line.employee_category_id.id if line.employee_category_id else False,
            "date_needed": line.date_needed,
            "nature": line.nature,
            "category_id": line.category_id.id if line.category_id else False,
            "purpose": line.purpose.id if line.purpose else False,
            "estimated_unit_price": line.estimated_unit_price,
            # Manpower quarterly quantities
            "q1": line.q1,
            "q2": line.q2,
            "q3": line.q3,
            "q4": line.q4,
            # Manpower unit cost & compensation
            "unit_cost": line.unit_cost,
            "base_salary": line.base_salary,
            "pension_rate": line.pension_rate,
            # Business Justification
            "justification_category_id": line.justification_category_id.id if line.justification_category_id else False,
            "other_justification": line.other_justification,
            "business_justification": line.business_justification,
            # Existing Establishment
            "existing_establishment": line.existing_establishment,
            "active_staff_count": line.active_staff_count,
            "vacant_count": line.vacant_count,
            # Fixed asset quarterly quantities
            "fa_q1": line.fa_q1,
            "fa_q2": line.fa_q2,
            "fa_q3": line.fa_q3,
            "fa_q4": line.fa_q4,
            # New position fields
            "new_job_title": line.new_job_title,
            "new_job_grade": line.new_job_grade,
            "new_job_grade_id": line.new_job_grade_id.id if line.new_job_grade_id else False,
            "new_employee_category_id": line.new_employee_category_id.id if line.new_employee_category_id else False,
            # Category multi-line targets
            "deposit_type_id": line.deposit_type_id.id if line.deposit_type_id else False,
            "plan_category": line.plan_category,
            "base_type": line.base_type,
            "fx_source_type": line.fx_source_type,
            "channel_id": line.channel_id.id if line.channel_id else False,
            "expense_account_id": line.expense_account_id.id if line.expense_account_id else False,
            "prior_year_actual": line.prior_year_actual,
            "is_office_rent": line.is_office_rent,
            "source_line_id": line.id,
            "opening_balance": line.opening_balance,
            "proposed_opening_balance": line.proposed_opening_balance or line.opening_balance or 0.0,
            "m01": line.m01, "m02": line.m02, "m03": line.m03,
            "m04": line.m04, "m05": line.m05, "m06": line.m06,
            "m07": line.m07, "m08": line.m08, "m09": line.m09,
            "m10": line.m10, "m11": line.m11, "m12": line.m12,
            "proposed_m01": line.proposed_m01 or line.m01 or 0.0,
            "proposed_m02": line.proposed_m02 or line.m02 or 0.0,
            "proposed_m03": line.proposed_m03 or line.m03 or 0.0,
            "proposed_m04": line.proposed_m04 or line.m04 or 0.0,
            "proposed_m05": line.proposed_m05 or line.m05 or 0.0,
            "proposed_m06": line.proposed_m06 or line.m06 or 0.0,
            "proposed_m07": line.proposed_m07 or line.m07 or 0.0,
            "proposed_m08": line.proposed_m08 or line.m08 or 0.0,
            "proposed_m09": line.proposed_m09 or line.m09 or 0.0,
            "proposed_m10": line.proposed_m10 or line.m10 or 0.0,
            "proposed_m11": line.proposed_m11 or line.m11 or 0.0,
            "proposed_m12": line.proposed_m12 or line.m12 or 0.0,
            "quarter1_total": line.quarter1_total,
            "quarter2_total": line.quarter2_total,
            "quarter3_total": line.quarter3_total,
            "quarter4_total": line.quarter4_total,
            "annual_total": line.annual_total,
            "proposed_annual_total": line.proposed_annual_total or line.annual_total or 0.0,
            "outstanding_year_end": line.outstanding_year_end,
        }

        if self.category == "manpower":
            vals["reason"] = f"[{org_unit.display_name}] {line.reason or ''}"
            vals["item_description"] = line.item_description or line.new_job_title or (line.job_id.name if line.job_id else '')
        elif self.category == "fixed_asset":
            vals["item_description"] = f"[{org_unit.display_name}] {line.item_description or ''}"

        return vals

    @api.model
    def _consolidate_grid(self, branch_plans, cycle_id, dist_unit):
        """Aggregate monthly-grid category figures from approved branch plans
        into the district / head-office overview plan."""
        category = self.category
        ident_fields = self._ident_fields()
        grouped = {}
        for p in branch_plans:
            key = tuple(getattr(p, f) for f in ident_fields)
            if key not in grouped:
                base = {"opening_balance": 0.0}
                if category == "general_expense":
                    base["prior_year_actual"] = 0.0
                grouped[key] = {**base, **{f: 0.0 for f in MONTH_FIELDS}}
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            if category == "general_expense":
                grouped[key]["prior_year_actual"] += (p.prior_year_actual or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for key, vals in grouped.items():
            domain = [
                ("category", "=", category),
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", dist_unit.id),
                ("active", "=", True),
            ]
            for f, v in zip(ident_fields, key):
                if hasattr(v, 'id'):
                    domain.append((f, "=", v.id))
                else:
                    domain.append((f, "=", v))

            target = self.search(domain, limit=1)
            vals_to_write = {
                "opening_balance": vals["opening_balance"],
                **{f: vals[f] for f in MONTH_FIELDS},
                "active": True,
            }
            if category == "general_expense":
                vals_to_write["prior_year_actual"] = vals["prior_year_actual"]
            if target:
                target.write(vals_to_write)
            else:
                create_vals = {
                    "category": category,
                    "cycle_id": cycle_id.id,
                    "org_unit_id": dist_unit.id,
                    "state": "draft",
                    "active": True,
                }
                for f, v in zip(ident_fields, key):
                    if hasattr(v, 'id'):
                        create_vals[f] = v.id
                    else:
                        create_vals[f] = v
                create_vals.update(vals_to_write)
                self.create(create_vals)

    @api.model
    def _consolidate_itemized(self, branch_plans, cycle_id, dist_unit):
        """Merge requirement lines of itemized categories into the district /
        head-office overview plan."""
        target = self.search([
            ("category", "=", self.category),
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", dist_unit.id),
            ("active", "=", True),
        ], limit=1)
        if not target:
            target = self.create({
                "category": self.category,
                "cycle_id": cycle_id.id,
                "org_unit_id": dist_unit.id,
                "state": "draft",
                "active": True,
            })
        if target.state == "draft":
            target.line_ids.unlink()
            lines_to_create = []
            for bp in branch_plans:
                for line in bp.line_ids:
                    lines_to_create.append((0, 0, self._line_vals(line, bp.org_unit_id)))
            if lines_to_create:
                target.write({"line_ids": lines_to_create})

    @api.model
    def _consolidate_district_plan_data(self, cycle_id, district):
        """Consolidate approved branch plans into the District Overview Plan strictly for
        the Mobilization Group: Deposit, Customer Base, FX, and Digital Banking.
        Direct pass categories (Manpower, General Expense, Fixed Asset) pass through
        directly to final approvers and do NOT pool into district plans."""
        target_cat = getattr(self, "category", False) or "deposit"
        if target_cat not in ("deposit", "customer_base", "fx", "digital_banking"):
            # Direct pass group: no district consolidation
            return False

        district_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", district.id),
            ("category", "=", target_cat),
            ("active", "=", True),
        ], limit=1)
        if not district_plan:
            district_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": district.id,
                "category": target_cat,
                "state": "submitted",
                "active": True,
            })
        elif district_plan.state in ("draft", "returned", "info_requested"):
            district_plan.with_context(bypass_plan_lock=True).write({"state": "submitted"})

        # Fetch approved/submitted branch plans strictly for THIS category in this district
        branch_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("district_id", "=", district.id),
            ("org_unit_id", "!=", district.id),
            ("category", "=", target_cat),
            ("active", "=", True),
            ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),
        ])
        if not branch_plans:
            return district_plan

        # Consolidate branch requirement lines grouped by line type / product type
        lines_to_create = []
        district_sol_id = district.sol_id if hasattr(district, "sol_id") else 0
        all_bp_lines = self.env["pbms.plan.category.line"].search([
            ("plan_id", "in", branch_plans.ids),
            ("line_type", "=", target_cat),
        ])

        if target_cat == "deposit":
            dep_grouped = {}
            for line in all_bp_lines:
                key = (line.deposit_type_id.id if line.deposit_type_id else False, line.plan_category or "amount")
                if not key[0]:
                    continue
                if key not in dep_grouped:
                    dep_grouped[key] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                dep_grouped[key]["opening_balance"] += (line.opening_balance or 0.0)
                dep_grouped[key]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    dep_grouped[key][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    dep_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for (dep_type_id, plan_cat), vals in dep_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                lines_to_create.append((0, 0, {
                    "line_type": "deposit",
                    "deposit_type_id": dep_type_id,
                    "plan_category": plan_cat,
                    "source_unit_id": district.id,
                    "sol_id": district_sol_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    "approved_annual_total": 0.0,
                    "is_cascaded": False,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))

        elif target_cat == "customer_base":
            cb_grouped = {}
            for line in all_bp_lines:
                dep_id = line.deposit_type_id.id if line.deposit_type_id else False
                b_type = line.base_type or "new_acquisition"
                key = (dep_id, b_type)
                if not dep_id:
                    continue
                if key not in cb_grouped:
                    cb_grouped[key] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                cb_grouped[key]["opening_balance"] += (line.opening_balance or 0.0)
                cb_grouped[key]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    cb_grouped[key][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    cb_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for (dep_type_id, b_type), vals in cb_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                lines_to_create.append((0, 0, {
                    "line_type": "customer_base",
                    "deposit_type_id": dep_type_id,
                    "base_type": b_type,
                    "source_unit_id": district.id,
                    "sol_id": district_sol_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    "approved_annual_total": 0.0,
                    "is_cascaded": False,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))

        elif target_cat == "fx":
            fx_grouped = {}
            for line in all_bp_lines:
                src_id = line.fx_source_type.id if line.fx_source_type else False
                if not src_id:
                    continue
                if src_id not in fx_grouped:
                    fx_grouped[src_id] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                fx_grouped[src_id]["opening_balance"] += (line.opening_balance or 0.0)
                fx_grouped[src_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    fx_grouped[src_id][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    fx_grouped[src_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for src_id, vals in fx_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                lines_to_create.append((0, 0, {
                    "line_type": "fx",
                    "fx_source_type": src_id,
                    "source_unit_id": district.id,
                    "sol_id": district_sol_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    "approved_annual_total": 0.0,
                    "is_cascaded": False,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))

        elif target_cat == "digital_banking":
            db_grouped = {}
            for line in all_bp_lines:
                chan_id = line.channel_id.id if line.channel_id else False
                if not chan_id:
                    continue
                if chan_id not in db_grouped:
                    db_grouped[chan_id] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                db_grouped[chan_id]["opening_balance"] += (line.opening_balance or 0.0)
                db_grouped[chan_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    db_grouped[chan_id][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    db_grouped[chan_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for chan_id, vals in db_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                lines_to_create.append((0, 0, {
                    "line_type": "digital_banking",
                    "channel_id": chan_id,
                    "source_unit_id": district.id,
                    "sol_id": district_sol_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    "approved_annual_total": 0.0,
                    "is_cascaded": False,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))

        # Unlink only the lines for this specific category on the district plan
        dp_ctx = district_plan.with_context(bypass_plan_lock=True, skip_reviewer_check=True)
        if target_cat == "deposit":
            dp_ctx.deposit_line_ids.unlink()
            if lines_to_create:
                dp_ctx.write({"deposit_line_ids": lines_to_create})
        elif target_cat == "customer_base":
            dp_ctx.customer_base_line_ids.unlink()
            if lines_to_create:
                dp_ctx.write({"customer_base_line_ids": lines_to_create})
        elif target_cat == "fx":
            dp_ctx.fx_line_ids.unlink()
            if lines_to_create:
                dp_ctx.write({"fx_line_ids": lines_to_create})
        elif target_cat == "digital_banking":
            dp_ctx.digital_banking_line_ids.unlink()
            if lines_to_create:
                dp_ctx.write({"digital_banking_line_ids": lines_to_create})

        # Ensure district plan is in 'submitted' state so district approver can endorse to HO
        if district_plan.state in ("draft", "returned", "info_requested"):
            dp_ctx.write({"state": "submitted"})

        if hasattr(district_plan, "_compute_category_summaries"):
            district_plan._compute_category_summaries()

        return district_plan

    @api.model
    def _consolidate_ho_plan_data(self, cycle_id, ho_unit):
        """Consolidate District Overview plans into the Bank-Wide Head Office Plan strictly for
        the Mobilization Group (Deposit, Customer Base, FX, Digital Banking).
        Direct pass categories (Expense, Fixed Asset, Manpower) are unit-specific requests
        sent directly to final approvers."""
        target_cat = getattr(self, "category", False) or "deposit"
        if target_cat not in ("deposit", "customer_base", "fx", "digital_banking"):
            return False

        ho_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", ho_unit.id),
            ("category", "=", target_cat),
            ("active", "=", True),
        ], limit=1)
        if not ho_plan:
            ho_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": ho_unit.id,
                "category": target_cat,
                "state": "draft",
                "active": True,
            })

        # Fetch all active non-HO plans across the bank for THIS category
        source_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "!=", ho_unit.id),
            ("category", "=", target_cat),
            ("active", "=", True),
            ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),
        ])
        if not source_plans:
            return ho_plan

        dist_plans = source_plans.filtered(lambda p: p.org_unit_type == "district_office")
        branch_plans = source_plans.filtered(lambda p: p.org_unit_type not in ("district_office", "head_office"))

        def get_source_lines(line_type):
            dist_lines = self.env["pbms.plan.category.line"].search([
                ("plan_id", "in", dist_plans.ids),
                ("line_type", "=", line_type),
            ])
            if dist_lines:
                dist_ids_with_lines = dist_lines.mapped("plan_id.org_unit_id").ids
                orphan_branch_lines = self.env["pbms.plan.category.line"].search([
                    ("plan_id", "in", branch_plans.ids),
                    ("line_type", "=", line_type),
                    ("district_id", "not in", dist_ids_with_lines),
                ])
                return dist_lines | orphan_branch_lines
            return self.env["pbms.plan.category.line"].search([
                ("plan_id", "in", source_plans.ids),
                ("line_type", "=", line_type),
            ])

        ho_ctx = ho_plan.with_context(bypass_plan_lock=True, skip_reviewer_check=True)
        if target_cat == "deposit":
            dep_lines = get_source_lines("deposit")
            dep_grouped = {}
            for line in dep_lines:
                key = line.deposit_type_id.id if line.deposit_type_id else False
                if not key:
                    continue
                if key not in dep_grouped:
                    dep_grouped[key] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                dep_grouped[key]["opening_balance"] += (line.opening_balance or 0.0)
                dep_grouped[key]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    dep_grouped[key][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    dep_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.deposit_line_ids.unlink()
            dep_create_vals = []
            for dep_type_id, vals in dep_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                dep_create_vals.append((0, 0, {
                    "line_type": "deposit",
                    "deposit_type_id": dep_type_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))
            if dep_create_vals:
                ho_ctx.write({"deposit_line_ids": dep_create_vals})

        elif target_cat == "customer_base":
            cb_lines = get_source_lines("customer_base")
            cb_grouped = {}
            for line in cb_lines:
                dep_id = line.deposit_type_id.id if line.deposit_type_id else False
                b_type = line.base_type or "new_acquisition"
                key = (dep_id, b_type)
                if not dep_id:
                    continue
                if key not in cb_grouped:
                    cb_grouped[key] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                cb_grouped[key]["opening_balance"] += (line.opening_balance or 0.0)
                cb_grouped[key]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    cb_grouped[key][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    cb_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.customer_base_line_ids.unlink()
            cb_create_vals = []
            for (dep_type_id, b_type), vals in cb_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                cb_create_vals.append((0, 0, {
                    "line_type": "customer_base",
                    "deposit_type_id": dep_type_id,
                    "base_type": b_type,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))
            if cb_create_vals:
                ho_ctx.write({"customer_base_line_ids": cb_create_vals})

        elif target_cat == "fx":
            fx_lines = get_source_lines("fx")
            fx_grouped = {}
            for line in fx_lines:
                source_id = line.fx_source_type.id if line.fx_source_type else False
                if not source_id:
                    continue
                if source_id not in fx_grouped:
                    fx_grouped[source_id] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                fx_grouped[source_id]["opening_balance"] += (line.opening_balance or 0.0)
                fx_grouped[source_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    fx_grouped[source_id][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    fx_grouped[source_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.fx_line_ids.unlink()
            fx_create_vals = []
            for src_id, vals in fx_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                fx_create_vals.append((0, 0, {
                    "line_type": "fx",
                    "fx_source_type": src_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))
            if fx_create_vals:
                ho_ctx.write({"fx_line_ids": fx_create_vals})

        elif target_cat == "digital_banking":
            db_lines = get_source_lines("digital_banking")
            db_grouped = {}
            for line in db_lines:
                ch_id = line.channel_id.id if line.channel_id else False
                if not ch_id:
                    continue
                if ch_id not in db_grouped:
                    db_grouped[ch_id] = {
                        "opening_balance": 0.0,
                        "proposed_opening_balance": 0.0,
                        **{m: 0.0 for m in MONTH_FIELDS},
                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},
                    }
                db_grouped[ch_id]["opening_balance"] += (line.opening_balance or 0.0)
                db_grouped[ch_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)
                for m in MONTH_FIELDS:
                    db_grouped[ch_id][m] += (getattr(line, m) or 0.0)
                    prop_m = getattr(line, f"proposed_{m}")
                    db_grouped[ch_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.digital_banking_line_ids.unlink()
            db_create_vals = []
            for ch_id, vals in db_grouped.items():
                tot_m = sum(vals[m] for m in MONTH_FIELDS)
                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)
                db_create_vals.append((0, 0, {
                    "line_type": "digital_banking",
                    "channel_id": ch_id,
                    "opening_balance": vals["opening_balance"],
                    "proposed_opening_balance": vals["proposed_opening_balance"],
                    "annual_total": tot_m,
                    "proposed_annual_total": tot_prop if tot_prop else tot_m,
                    **{m: vals[m] for m in MONTH_FIELDS},
                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},
                }))
            if db_create_vals:
                ho_ctx.write({"digital_banking_line_ids": db_create_vals})

        if hasattr(ho_plan, "_compute_category_summaries"):
            ho_plan._compute_category_summaries()

        return ho_plan