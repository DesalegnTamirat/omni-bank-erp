# -*- coding: utf-8 -*-

"""Unified Planning Categories logic - Enhanced for Manpower & Fixed Asset."""

import base64

import re

from odoo import Command, api, fields, models, _

from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.fields import Domain

from odoo.tools.float_utils import float_is_zero

from .pbms_plan_line_mixin import MONTH_FIELDS, QUARTERS

from .pbms_access import PBMS_BRANCH_EDITABLE_STATES, PBMS_CONTENT_FIELDS, _safe_table_exists

def _process_workforce_document_vals(vals):

    """Ensure workforce document is converted to Base64 and stored in database,

    and prevent child line commands from wiping out the parent document."""

    if not isinstance(vals, dict):

        return

    # Inspect child one2many commands (manpower_line_ids / line_ids) for uploaded workforce documents

    for o2m_field in ("manpower_line_ids", "line_ids"):

        cmds = vals.get(o2m_field)

        if isinstance(cmds, (list, tuple)):

            for cmd in cmds:

                if isinstance(cmd, (list, tuple)) and len(cmd) > 2 and isinstance(cmd[2], dict):

                    lvals = cmd[2]

                    line_doc = lvals.get("plan_workforce_document") or lvals.get("workforce_document")

                    line_fname = lvals.get("plan_workforce_document_filename") or lvals.get("workforce_document_filename")

                    if line_doc and not vals.get("workforce_document"):

                        vals["workforce_document"] = line_doc

                        if line_fname and not vals.get("workforce_document_filename"):

                            vals["workforce_document_filename"] = line_fname

                    # Never allow falsy related fields on line commands to overwrite the parent plan's document

                    for doc_f in ("plan_workforce_document", "plan_workforce_document_filename", "workforce_document", "workforce_document_filename"):

                        if doc_f in lvals and not lvals[doc_f]:

                            lvals.pop(doc_f, None)

    if "workforce_document" in vals:

        doc = vals.get("workforce_document")

        if doc:

            if isinstance(doc, bytes):

                base64_str = base64.b64encode(doc).decode("ascii")

            elif isinstance(doc, str):

                if "," in doc and doc.startswith("data:"):

                    base64_str = doc.split(",", 1)[1]

                else:

                    base64_str = doc

            else:

                base64_str = str(doc)

            vals["workforce_document_base64"] = base64_str

            vals["workforce_document"] = base64_str

        else:

            vals["workforce_document_base64"] = False

    elif "workforce_document_base64" in vals and not vals.get("workforce_document"):

        b64 = vals.get("workforce_document_base64")

        if b64:

            vals["workforce_document"] = b64

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

    "loan_disbursement_collection": [],

    "loan_outstanding": [],

    "credit_portfolio": [],

    "initiative_budget": [],

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

    "loan_disbursement_collection",

    "loan_outstanding",

    "credit_portfolio",

    "initiative_budget",

)

# Work Unit Type options (mirrors operating.unit.work_unit_type).

WORK_UNIT_TYPES = [

    ("branch", "Branch"),

    ("sub_branch", "Sub-Branch"),

    ("head_office", "Head Office"),

    ("regional_office", "Regional Office"),

    ("district_office", "District Office"),

    ("area_office", "Area Office"),

    ("service_center", "Service Center"),

    ("other", "Other"),

]

# Quarter fields for itemized categories

QUARTER_FIELDS = ['q1', 'q2', 'q3', 'q4']

QUARTER_LABELS = {

    'q1': 'QI',

    'q2': 'QII',

    'q3': 'QIII',

    'q4': 'QIV',

}

def _validate_month_values_not_text(vals):

    """Validate that monthly/numeric target inputs do not contain non-numeric characters or text."""

    if not isinstance(vals, dict):

        return

    month_fields = (

        "m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12",

        "proposed_m01", "proposed_m02", "proposed_m03", "proposed_m04", "proposed_m05", "proposed_m06",

        "proposed_m07", "proposed_m08", "proposed_m09", "proposed_m10", "proposed_m11", "proposed_m12",

        "approved_m01", "approved_m02", "approved_m03", "approved_m04", "approved_m05", "approved_m06",

        "approved_m07", "approved_m08", "approved_m09", "approved_m10", "approved_m11", "approved_m12",

        "hc_m01", "hc_m02", "hc_m03", "hc_m04", "hc_m05", "hc_m06", "hc_m07", "hc_m08", "hc_m09", "hc_m10", "hc_m11", "hc_m12",

        "opening_balance", "proposed_opening_balance", "approved_opening_balance",

        "annual_total", "proposed_annual_total", "approved_annual_total",

    )

    for fname in month_fields:

        if fname in vals and vals[fname] is not None and vals[fname] is not False:

            val = vals[fname]

            if isinstance(val, str):

                s = val.strip().replace(",", "")

                if not s:

                    continue

                try:

                    float(s)

                except (ValueError, TypeError):

                    raise ValidationError(_("Monthly target field '%s' cannot accept text or character values ('%s'). Please enter a valid number.") % (fname, val))

    # Recursively check one2many lines

    for k, v in vals.items():

        if isinstance(v, (list, tuple)):

            for cmd in v:

                if isinstance(cmd, (list, tuple)) and len(cmd) > 2 and isinstance(cmd[2], dict):

                    _validate_month_values_not_text(cmd[2])

class HrEmployeeGrade(models.Model):

    _inherit = "employee.grade"

    _rec_name = "grade_code"

    @api.depends("grade_code", "grade_name")

    def _compute_display_name(self):

        for rec in self:

            if rec.grade_code:

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

def _generate_dropdown_code_for_vals(env, model_name, prefix, vals_list):
    """Auto-generate sequential codes like DT_001, DT_002 for dropdown models if not provided."""
    records = env[model_name].sudo().search([("code", "=like", f"{prefix}_%")])
    max_idx = 0
    for r in records:
        if r.code and r.code.startswith(f"{prefix}_"):
            suffix = r.code[len(prefix) + 1:]
            if suffix.isdigit():
                max_idx = max(max_idx, int(suffix))
    for vals in vals_list:
        if not vals.get("code") or vals.get("code") in ("/", "New", ""):
            max_idx += 1
            vals["code"] = f"{prefix}_{max_idx:03d}"

def _get_dropdown_next_code(self_model, prefix):
    """Return next sequential code like DT_001, DT_002 for dropdown models."""
    records = self_model.sudo().search([("code", "=like", f"{prefix}_%")])
    max_idx = 0
    for r in records:
        if r.code and r.code.startswith(f"{prefix}_"):
            suffix = r.code[len(prefix) + 1:]
            if suffix.isdigit():
                max_idx = max(max_idx, int(suffix))
    return f"{prefix}_{max_idx + 1:03d}"

class PbmsDepositType(models.Model):

    _name = "pbms.deposit.type"

    _description = "Deposit Product Type"

    _order = "sequence, name"

    name = fields.Char(required=True)

    code = fields.Char(required=True, copy=False, default="/")

    sequence = fields.Integer(default=10)

    is_ifb = fields.Boolean(string="Interest-Free Banking", default=False)

    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Deposit type code must be unique.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "DT")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.deposit.type", "DT", vals_list)
        return super().create(vals_list)

    def _load_records_create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            code = vals.get("code")
            name = vals.get("name")
            existing = self.search([
                "|", ("code", "=", code), ("name", "=", name)
            ], limit=1) if (code or name) else self.browse()
            if existing:
                existing.write(vals)
                records |= existing
            else:
                records |= super()._load_records_create([vals])
        return records

class PbmsCustomerType(models.Model):

    """Customer Account Type specifically for Customer Base planning (Savings, Demand, Time, IFB)."""

    _name = "pbms.customer.type"

    _description = "Customer Account Type"

    _order = "sequence, name"

    name = fields.Char(required=True)

    code = fields.Char(required=True, copy=False, default="/")

    sequence = fields.Integer(default=10)

    is_ifb = fields.Boolean(string="Interest-Free Banking", default=False)

    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Customer type code must be unique.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "CT")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.customer.type", "CT", vals_list)
        return super().create(vals_list)

    def _load_records_create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            code = vals.get("code")
            name = vals.get("name")
            existing = self.search([
                "|", ("code", "=", code), ("name", "=", name)
            ], limit=1) if (code or name) else self.browse()
            if existing:
                existing.write(vals)
                records |= existing
            else:
                records |= super()._load_records_create([vals])
        return records


class PbmsLoanProduct(models.Model):

    _name = "pbms.loan.product"

    _description = "Conventional Loan Product"

    _order = "sequence, name"

    name = fields.Char(string="Loan Product", required=True)

    code = fields.Char(string="Code", required=True)

    sequence = fields.Integer(string="Sequence", default=10)

    category_type = fields.Selection([

        ("term_loan", "Term Loan"),

        ("overdraft", "Overdraft"),

        ("advances", "Advances"),

        ("provisions", "Provisions"),

        ("other", "Other"),

    ], string="Product Category", default="term_loan")

    applies_to = fields.Selection([

        ("disbursement_collection", "Disbursement & Collection (BB-APF-8)"),

        ("outstanding", "Outstanding (BB-APF-7)"),

        ("both", "Both"),

    ], string="Applies To", default="both")

    product_type = fields.Selection([

        ("disbursement_collection", "Disbursement & Collection (BB-APF-8)"),

        ("outstanding", "Outstanding (BB-APF-7)"),

        ("both", "Both"),

    ], string="Product Type", compute="_compute_product_type", store=True, readonly=True)

    active = fields.Boolean(string="Active", default=True)

    @api.depends("applies_to")

    def _compute_product_type(self):

        for rec in self:

            rec.product_type = rec.applies_to or "both"

    _code_uniq = models.Constraint("unique(code)", "Loan product code must be unique.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "LP")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.loan.product", "LP", vals_list)
        return super().create(vals_list)

class PbmsCreditPortfolioItem(models.Model):

    _name = "pbms.credit.portfolio.item"

    _description = "Credit Portfolio Planning Item (BB-APF-15)"

    _order = "sequence, name"

    name = fields.Char(string="Source of Income", required=True, translate=True)

    code = fields.Char(string="Code", required=True)

    sequence = fields.Integer(string="Sequence", default=10)

    section = fields.Selection([

        ("balance_sheet", "Balance Sheet"),

        ("income_statement", "Income Statement"),

    ], string="Section", default="balance_sheet", required=True)

    totals_basis = fields.Selection([

        ("sum_of_months", "Sum of Months (Default)"),

        ("last_month", "Last Month (Balance Sheet)"),

    ], string="Totals Basis", default="sum_of_months", required=True)

    description = fields.Text(string="Description / Guidance")

    active = fields.Boolean(string="Active", default=True)

    _code_uniq = models.Constraint("unique(code)", "Credit portfolio item code must be unique.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "CP")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.credit.portfolio.item", "CP", vals_list)
        return super().create(vals_list)

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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "DC")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.digital.channel", "DC", vals_list)
        return super().create(vals_list)

class PbmsExpenseAccount(models.Model):

    _name = "pbms.expense.account"

    _description = "General Expense Account"

    _order = "sequence, name"

    name = fields.Char(required=True)

    code = fields.Char(required=True)

    sequence = fields.Integer(default=10)

    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Expense account code must be unique.")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "EA")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.expense.account", "EA", vals_list)
        return super().create(vals_list)

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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "FA")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.fixed.asset.category", "FA", vals_list)
        return super().create(vals_list)

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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "FS")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.fx.source.type", "FS", vals_list)
        return super().create(vals_list)

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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "JC")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.justification.category", "JC", vals_list)
        return super().create(vals_list)

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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "code" in fields_list and (not res.get("code") or res.get("code") == "/"):
            res["code"] = _get_dropdown_next_code(self, "PT")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        _generate_dropdown_code_for_vals(self.env, "pbms.position.type", "PT", vals_list)
        return super().create(vals_list)

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

            ("cpco_endorse_operations", "CPCO Final Endorsement to People Operations & Management"),

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

    active = fields.Boolean(

        related="plan_id.active", store=True, index=True,

    )

    is_consolidated = fields.Boolean(

        related="plan_id.is_consolidated", store=True, index=True, string="Is Consolidated Line",

    )

    is_consolidated_district_plan = fields.Boolean(

        related="plan_id.is_consolidated_district_plan", store=True, index=True, string="Is District Consolidated Line",

    )

    is_consolidated_ho_plan = fields.Boolean(

        related="plan_id.is_consolidated_ho_plan", store=True, index=True, string="Is Bank-Wide Consolidated Line",

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

        aggregator=None,

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
            visited_units = set()
            while curr and curr.id not in visited_units:
                visited_units.add(curr.id)
                if curr.work_unit_type in ("district_office", "regional_office", "area_office"):
                    found_dist = curr
                    break
                curr = curr.parent_unit

            if found_dist:

                line.district_id = found_dist

            elif line.plan_id and line.plan_id.district_id:

                line.district_id = line.plan_id.district_id

            elif unit and unit.work_unit_type == "head_office":

                line.district_id = unit

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

        "pbms.planning.cycle", related="plan_id.cycle_id", store=True, string="FY(the Planning year)", index=True,

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

            ("loan_disbursement_collection", "Loan Disbursement & Collection "),

            ("loan_outstanding", "Loan & Advances Outstanding "),

            ("credit_portfolio", "Income Plan"),

            ("initiative_budget", "Initiative Budget"),

        ],

        string="Line Type",

        compute="_compute_line_type",

        store=True,

        readonly=False,

        index=True,

    )

    # ---- Conventional Loan Planning (BB-APF-7 & BB-APF-8) ----

    loan_product_id = fields.Many2one("pbms.loan.product", string="Loan Product", index=True)

    loan_flow_type = fields.Selection(

        [

            ("disbursement", "Disbursement"),

            ("collection", "Collection"),

        ],

        string="Loan Disbursement & Collection",

    )

    # ---- Credit Portfolio (BB-APF-15) ----

    credit_portfolio_item_id = fields.Many2one("pbms.credit.portfolio.item", string="Source of Income", index=True)

    credit_portfolio_section = fields.Selection(

        related="credit_portfolio_item_id.section", string="Section", store=True, readonly=True,

    )

    totals_basis = fields.Selection([

        ("sum_of_months", "Sum of Months (Default)"),

        ("last_month", "Last Month (Balance Sheet)"),

    ], string="Totals Basis", default="sum_of_months")

    # ---- Initiative Budget ----

    initiative_name = fields.Char(string="Initiative Name")

    initiative_cost = fields.Monetary(string="Initiative Cost", currency_field="currency_id")

    initiative_description = fields.Text(string="Initiative Description")

    # ---- Configurable dropdown domains (from planning config) ----

    deposit_type_domain = fields.Char(compute="_compute_deposit_type_domain", store=False)

    channel_domain = fields.Char(compute="_compute_channel_domain", store=False)

    expense_account_domain = fields.Char(compute="_compute_expense_account_domain", store=False)

    fa_category_domain = fields.Char(compute="_compute_fa_category_domain", store=False)

    justification_category_domain = fields.Char(compute="_compute_justification_category_domain", store=False)

    fx_source_type_domain = fields.Char(compute="_compute_fx_source_type_domain", store=False)

    loan_product_domain = fields.Char(compute="_compute_loan_product_domain", store=False)

    credit_portfolio_item_domain = fields.Char(compute="_compute_credit_portfolio_item_domain", store=False)

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_loan_product_domain(self):

        import json

        Config = self.env["pbms.planning.config"]

        for line in self:

            domain = []

            plan = line.plan_id

            config = False

            if plan and plan.org_unit_id:

                config = Config.get_config_for_unit(plan.org_unit_id)

            if config and config.loan_product_ids:

                domain.append(("id", "in", config.loan_product_ids.ids))

            else:

                domain.append(("active", "=", True))

            line.loan_product_domain = json.dumps(domain)

    # ---- Deposit ----

    deposit_type_id = fields.Many2one("pbms.deposit.type", string="Deposit Type", index=True)

    customer_type_id = fields.Many2one("pbms.customer.type", string="Customer Type", index=True)

    plan_category = fields.Selection(

        [("amount", "Amount"), ("customer", "Number of Customer")],

        string="Measurement", default="amount",

    )

    measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

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

    @api.onchange("customer_type_id")

    def _onchange_customer_type_id_sync_deposit_type(self):

        if self.customer_type_id:

            dep_type = self.env["pbms.deposit.type"].search([("code", "=", self.customer_type_id.code)], limit=1)

            if dep_type:

                self.deposit_type_id = dep_type.id

    # ---- Customer Base ----

    base_type = fields.Selection(

        [

            ("new_acquisition", "New Customer Acquisition"),

            ("dormant_reduction", "Quality Customer"),

        ],

        string="Customer Category", default="new_acquisition",

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

    measurement = fields.Selection(

        [

            ("amount", "Amount"),

            ("percent", "Percent"),

            ("number", "Number"),

        ],

        string="Measurements",

        default="amount",

        help="Measurement basis for digital banking channel (Amount, Percent, Number).",

    )

    # ---- General Expense ----

    expense_account_id = fields.Many2one("pbms.expense.account", string="Expense Account", index=True)

    prior_year_actual = fields.Monetary(string="Prior Year Actual", currency_field="currency_id")

    is_office_rent = fields.Boolean(string="Office Rent")

    # ---- Monthly targets (Float allows seamless integer/number or monetary formatting) ----

    opening_balance = fields.Float(string="Estimate")

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

        string="QI",

        compute="_compute_quarter_targets", store=True, readonly=False,

    )

    quarter2_total = fields.Float(

        string="QII",

        compute="_compute_quarter_targets", store=True, readonly=False,

    )

    quarter3_total = fields.Float(

        string="QIII",

        compute="_compute_quarter_targets", store=True, readonly=False,

    )

    quarter4_total = fields.Float(

        string="QIV",

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

    proposed_plan = fields.Integer(
        string="Proposed Plan",
        compute="_compute_proposed_plan",
        store=True,
        readonly=False,
        help="Planner's original proposed headcount or quantity for workforce and fixed asset before review adjustments."
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

    fulfilled_quantity = fields.Integer(

        string="Fulfilled Quantity / Hires",

        default=0,

        help="Number of filled/hired candidates linked to this plan line."

    )

    remaining_approved_annual_total = fields.Integer(

        string="Remaining Approved Plan",

        compute="_compute_remaining_approved_annual_total",

        store=True,

        help="Remaining unfulfilled approved plan (Approved Plan - Fulfilled Quantity)."

    )

    @api.depends("approved_annual_total", "display_approved_annual_total", "fulfilled_quantity")

    def _compute_remaining_approved_annual_total(self):

        for line in self:

            base_val = line.display_approved_annual_total or line.approved_annual_total or line.quantity or 0.0

            line.remaining_approved_annual_total = int(round(max(0.0, float(base_val) - float(line.fulfilled_quantity or 0))))

    display_approved_annual_total = fields.Integer(

        string="Approved Plan",

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

        "loan_product_id", "loan_flow_type",

        "credit_portfolio_item_id", "initiative_name", "initiative_cost",

    )

    def _compute_line_type(self):

        for line in self:

            # Preserve existing line_type if already set and valid

            if line.line_type in ("manpower", "fx", "digital_banking", "general_expense", "fixed_asset", "customer_base", "deposit", "loan_disbursement_collection", "loan_outstanding", "credit_portfolio", "initiative_budget"):

                continue

            if line.position_type_id or line.position_type or line.job_id or line.new_job_title:

                line.line_type = "manpower"

            elif line.credit_portfolio_item_id:

                line.line_type = "credit_portfolio"

            elif line.initiative_name or line.initiative_cost:

                line.line_type = "initiative_budget"

            elif line.fx_source_type:

                line.line_type = "fx"

            elif line.channel_id:

                line.line_type = "digital_banking"

            elif line.expense_account_id:

                line.line_type = "general_expense"

            elif line.category_id or line.item_description:

                line.line_type = "fixed_asset"

            elif line.loan_product_id:

                line.line_type = "loan_outstanding"

            elif line.deposit_type_id and line.base_type:

                line.line_type = "customer_base"

            elif line.deposit_type_id:

                line.line_type = "deposit"

            elif line.loan_flow_type in ("disbursement", "collection"):

                line.line_type = "loan_disbursement_collection"

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

    def _get_cached_config_for_plan(self, plan, config_cache):

        if not plan or not plan.org_unit_id:

            return False

        ou_id = plan.org_unit_id.id

        if ou_id not in config_cache:

            Config = self.env["pbms.planning.config"]

            config = Config.get_config_for_unit(plan.org_unit_id)

            if not config and plan.org_unit_id.work_unit_type:

                config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

            config_cache[ou_id] = config

        return config_cache[ou_id]

    # 1. Deposit Mobilization & Customer Base

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_deposit_type_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("deposit", "customer_base", False):

                line.deposit_type_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

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

        if self.deposit_type_id and config and config.deposit_type_ids and self.deposit_type_id not in config.deposit_type_ids:
            val_name = self.deposit_type_id.display_name or self.deposit_type_id.name
            self.deposit_type_id = False
            cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
            return {
                "domain": {"deposit_type_id": domain},
                "warning": {
                    "title": _("Unplanned Dropdown Selection"),
                    "message": _("Deposit Type '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                        "val": val_name,
                        "cycle": cycle_name,
                    }
                }
            }

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

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_channel_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("digital_banking", False):

                line.channel_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

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

        if self.channel_id and config and config.digital_channel_ids and self.channel_id not in config.digital_channel_ids:
            val_name = self.channel_id.display_name or self.channel_id.name
            self.channel_id = False
            cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
            return {
                "domain": {"channel_id": domain},
                "warning": {
                    "title": _("Unplanned Dropdown Selection"),
                    "message": _("Digital Channel '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                        "val": val_name,
                        "cycle": cycle_name,
                    }
                }
            }

        if plan and self.line_type == "digital_banking":

            other_lines = plan.digital_banking_line_ids.filtered(

                lambda l: not self._is_same_line(l) and l.channel_id

            )

            used_ids = other_lines.mapped("channel_id.id")

            if used_ids:

                domain.append(("id", "not in", used_ids))

        return {"domain": {"channel_id": domain}}

    # 3. FX Source Types

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_fx_source_type_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("fx", False):

                line.fx_source_type_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

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

        if self.fx_source_type and config and config.fx_source_type_ids and self.fx_source_type not in config.fx_source_type_ids:
            val_name = self.fx_source_type.display_name or self.fx_source_type.name
            self.fx_source_type = False
            cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
            return {
                "domain": {"fx_source_type": domain},
                "warning": {
                    "title": _("Unplanned Dropdown Selection"),
                    "message": _("FX Source '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                        "val": val_name,
                        "cycle": cycle_name,
                    }
                }
            }

        if plan and self.line_type == "fx":

            other_lines = plan.fx_line_ids.filtered(

                lambda l: not self._is_same_line(l) and l.fx_source_type

            )

            used_ids = other_lines.mapped("fx_source_type.id")

            if used_ids:

                domain.append(("id", "not in", used_ids))

        return {"domain": {"fx_source_type": domain}}

    # 4. Expense Accounts

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_expense_account_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("general_expense", False):

                line.expense_account_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

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

    @api.depends("line_type", "plan_id.org_unit_id")

    def _compute_fa_category_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("fixed_asset", False):

                line.fa_category_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

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

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("manpower", False):

                line.justification_category_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

            if config and config.justification_category_ids:

                domain.append(("id", "in", config.justification_category_ids.ids))

            else:

                domain.append(("active", "=", True))

            line.justification_category_domain = json.dumps(domain)

    # 7. Credit Portfolio Items (BB-APF-15)

    @api.depends(

        "line_type", "plan_id", "plan_id.org_unit_id", "plan_id.org_unit_id.work_unit_type",

        "plan_id.credit_portfolio_line_ids.credit_portfolio_item_id",

    )

    def _compute_credit_portfolio_item_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        config_cache = {}

        for line in self:

            if line.line_type not in ("credit_portfolio", False):

                line.credit_portfolio_item_domain = default_domain_json

                continue

            domain = []

            plan = line.plan_id

            config = self._get_cached_config_for_plan(plan, config_cache)

            if config and config.credit_portfolio_item_ids:

                domain.append(("id", "in", config.credit_portfolio_item_ids.ids))

            else:

                domain.append(("active", "=", True))

            if plan and line.line_type == "credit_portfolio":

                other_lines = plan.credit_portfolio_line_ids.filtered(

                    lambda l: not line._is_same_line(l) and l.credit_portfolio_item_id

                )

                used_ids = other_lines.mapped("credit_portfolio_item_id.id")

                if used_ids:

                    domain.append(("id", "not in", used_ids))

            line.credit_portfolio_item_domain = json.dumps(domain)

    @api.onchange("credit_portfolio_item_id", "line_type", "plan_id")

    def _onchange_credit_portfolio_item_update_domain(self):

        if self.credit_portfolio_item_id:

            self.totals_basis = self.credit_portfolio_item_id.totals_basis or "sum_of_months"

        Config = self.env["pbms.planning.config"]

        plan = self.plan_id

        config = False

        if plan and plan.org_unit_id:

            config = Config.get_config_for_unit(plan.org_unit_id)

        elif plan and plan.org_unit_id and plan.org_unit_id.work_unit_type:

            config = Config.get_config_for_type(plan.org_unit_id.work_unit_type)

        domain = []

        if config and config.credit_portfolio_item_ids:

            domain.append(("id", "in", config.credit_portfolio_item_ids.ids))

        else:

            domain.append(("active", "=", True))

        if plan and self.line_type == "credit_portfolio":

            other_lines = plan.credit_portfolio_line_ids.filtered(

                lambda l: not self._is_same_line(l) and l.credit_portfolio_item_id

            )

            used_ids = other_lines.mapped("credit_portfolio_item_id.id")

            if used_ids:

                domain.append(("id", "not in", used_ids))

        return {"domain": {"credit_portfolio_item_id": domain}}

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

    @api.depends("position_type_id", "position_type_id.code", "position_type_id.name", "position_type_id.is_new_position")

    def _compute_position_type_code(self):

        for line in self:

            if line.position_type_id:

                if line.position_type_id.is_new_position or line.position_type_id.code in ("new", "new_position"):

                    line.position_type = "new"

                elif line.position_type_id.code == "additional" or (line.position_type_id.name and line.position_type_id.name.strip().lower() == "additional position"):

                    line.position_type = "additional"

                elif line.position_type_id.code in dict(self._fields["position_type"].selection):

                    line.position_type = line.position_type_id.code

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

            elif self.position_type_id.code == "additional" or (self.position_type_id.name and self.position_type_id.name.strip().lower() == "additional position"):

                self.position_type = "additional"

            elif self.position_type_id.code in dict(self._fields["position_type"].selection):

                self.position_type = self.position_type_id.code

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

            ("contract", "Contract")

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

    hc_m01 = fields.Integer(string="Jul Headcount", default=0)

    hc_m02 = fields.Integer(string="Aug Headcount", default=0)

    hc_m03 = fields.Integer(string="Sep Headcount", default=0)

    hc_m04 = fields.Integer(string="Oct Headcount", default=0)

    hc_m05 = fields.Integer(string="Nov Headcount", default=0)

    hc_m06 = fields.Integer(string="Dec Headcount", default=0)

    hc_m07 = fields.Integer(string="Jan Headcount", default=0)

    hc_m08 = fields.Integer(string="Feb Headcount", default=0)

    hc_m09 = fields.Integer(string="Mar Headcount", default=0)

    hc_m10 = fields.Integer(string="Apr Headcount", default=0)

    hc_m11 = fields.Integer(string="May Headcount", default=0)

    hc_m12 = fields.Integer(string="Jun Headcount", default=0)

    q1 = fields.Integer(string="QI Headcount", compute="_compute_manpower_quarters", store=True, readonly=False)

    q2 = fields.Integer(string="QII Headcount", compute="_compute_manpower_quarters", store=True, readonly=False)

    q3 = fields.Integer(string="QIII Headcount", compute="_compute_manpower_quarters", store=True, readonly=False)

    q4 = fields.Integer(string="QIV Headcount", compute="_compute_manpower_quarters", store=True, readonly=False)

    base_salary = fields.Float(compute="_compute_base_salary", store=True, readonly=False, digits=(16, 2))

    monthly_allowance = fields.Float(
        string="Monthly Allowance",
        compute="_compute_monthly_allowance",
        store=True,
        readonly=False,
        digits=(16, 2),
        help="Monthly allowances per headcount, auto-computed from payroll salary rules and structures."
    )

    allowance_breakdown = fields.Char(
        string="Allowance Breakdown",
        compute="_compute_monthly_allowance",
        store=True,
        readonly=True,
        help="Detailed breakdown of matched allowance rules."
    )

    pension_rate = fields.Float(string="Employer Pension (%)", default=11.0)

    monthly_pension = fields.Float(compute="_compute_compensation_breakdown", store=True, digits=(16, 2))

    annual_pension = fields.Float(compute="_compute_compensation_breakdown", store=True, digits=(16, 2))

    monthly_total_compensation = fields.Float(compute="_compute_compensation_breakdown", store=True, digits=(16, 2))

    unit_cost = fields.Float(compute="_compute_compensation_breakdown", store=True, digits=(16, 2))

    q1_cost = fields.Float(compute="_compute_quarter_costs", store=True, digits=(16, 2))

    q2_cost = fields.Float(compute="_compute_quarter_costs", store=True, digits=(16, 2))

    q3_cost = fields.Float(compute="_compute_quarter_costs", store=True, digits=(16, 2))

    q4_cost = fields.Float(compute="_compute_quarter_costs", store=True, digits=(16, 2))

    annual_total_cost = fields.Float(compute="_compute_annual_total_cost", store=True, digits=(16, 2))

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

    @api.onchange("fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external")

    def _onchange_manpower_sourcing(self):

        for line in self:

            if line.line_type != "manpower":

                continue

            target = int(round(line.annual_total or line.quantity or 0))

            prom = max(0, int(line.fulfillment_promotion or 0))

            trans = max(0, int(line.fulfillment_transfer or 0))

            lat = max(0, int(line.fulfillment_lateral or 0))

            ext = max(0, int(line.fulfillment_external or 0))

            line.fulfillment_promotion = prom

            line.fulfillment_transfer = trans

            line.fulfillment_lateral = lat

            line.fulfillment_external = ext

            tot = prom + trans + lat + ext

            if tot > target:

                excess = tot - target

                if ext > 0:

                    deduct = min(ext, excess)

                    ext -= deduct

                    excess -= deduct

                    line.fulfillment_external = ext

                if excess > 0 and lat > 0:

                    deduct = min(lat, excess)

                    lat -= deduct

                    excess -= deduct

                    line.fulfillment_lateral = lat

                if excess > 0 and trans > 0:

                    deduct = min(trans, excess)

                    trans -= deduct

                    excess -= deduct

                    line.fulfillment_transfer = trans

                if excess > 0 and prom > 0:

                    deduct = min(prom, excess)

                    prom -= deduct

                    excess -= deduct

                    line.fulfillment_promotion = prom

                line.fulfillment_total = prom + trans + lat + ext

                appr = int(line.approved_annual_total or line.annual_total or 0)

                line.fulfillment_balance = appr - line.fulfillment_total

                pos_name = line.job_id.name or line.new_job_title or (line.position_type_id.name if line.position_type_id else _("Position"))

                return {

                    "warning": {

                        "title": _("Sourcing Allocation Limit"),

                        "message": _(

                            "Total sourcing for '%s' cannot be greater than the requested headcount (%d).\n\n"

                            "In People Solutions Directorate, sourcing allocations must equal the requested headcount and cannot exceed it."

                        ) % (pos_name, target),

                    }

                }

            elif tot < target:

                diff = target - tot

                line.fulfillment_external = ext + diff

                line.fulfillment_total = target

                appr = int(line.approved_annual_total or line.annual_total or 0)

                line.fulfillment_balance = appr - target

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

    estimated_unit_price = fields.Float(digits=(16, 2))

    fa_q1 = fields.Integer(string="QI Fixed Asset", default=0)

    fa_q2 = fields.Integer(string="QII Fixed Asset", default=0)

    fa_q3 = fields.Integer(string="QIII Fixed Asset", default=0)

    fa_q4 = fields.Integer(string="QIV Fixed Asset", default=0)

    fa_q1_cost = fields.Float(compute="_compute_fa_quarter_costs", store=True, digits=(16, 2))

    fa_q2_cost = fields.Float(compute="_compute_fa_quarter_costs", store=True, digits=(16, 2))

    fa_q3_cost = fields.Float(compute="_compute_fa_quarter_costs", store=True, digits=(16, 2))

    fa_q4_cost = fields.Float(compute="_compute_fa_quarter_costs", store=True, digits=(16, 2))

    fa_annual_total_cost = fields.Float(compute="_compute_fa_annual_total_cost", store=True, digits=(16, 2))

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
        etb = self.env.ref("base.ETB", raise_if_not_found=False)
        default_curr = etb or self.env.company.currency_id
        for line in self:
            if line.line_type == "fx":
                line.currency_id = Config.get_category_currency("fx", org_unit=line.plan_id.org_unit_id if line.plan_id else False)
            elif line.line_type == "initiative_budget":
                # Support both USD and ETB for initiative budget; preserve existing selection
                if not line.currency_id:
                    line.currency_id = (line.plan_id and line.plan_id.currency_id) or default_curr
            else:
                line.currency_id = etb or (line.plan_id and line.plan_id.currency_id) or default_curr

    @api.constrains("line_type", "currency_id")

    def _check_initiative_currency(self):

        for line in self:

            if line.line_type == "initiative_budget" and line.currency_id:

                if line.currency_id.name not in ("ETB", "USD"):

                    raise ValidationError(_("Initiative Budget currency must be either ETB or USD."))

    # Four consolidable planning categories that require mandatory monthly planning

    _CONSOLIDABLE_LINE_TYPES = ("deposit", "customer_base", "fx", "digital_banking")

    # Ordered fiscal-year month sequence: (field_name, display_label)

    _FISCAL_MONTH_SEQUENCE = [

        ("m01", "July"), ("m02", "August"), ("m03", "September"),

        ("m04", "October"), ("m05", "November"), ("m06", "December"),

        ("m07", "January"), ("m08", "February"), ("m09", "March"),

        ("m10", "April"), ("m11", "May"), ("m12", "June"),

    ]

    def _allow_negative_targets(self):

        return any(line.line_type in ("deposit",) or (line.line_type == "customer_base" and line.base_type == "dormant_reduction") for line in self)

    @api.constrains(

        "line_type",

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

    )

    def _check_consolidable_monthly_positive(self):

        """Enforce that monthly values cannot be negative (< 0) for the

        four consolidable planning categories: Deposit Mobilization, Customer

        Base, FX Mobilization, and Digital Banking.

        In draft/input mode, unfilled (0.0) months are allowed while entering data.

        All 12 months must be strictly non-zero upon submission (action_submit)."""

        category_labels = dict(self._fields["line_type"].selection)

        for line in self:

            if line.line_type not in self._CONSOLIDABLE_LINE_TYPES:

                continue

            cat_label = category_labels.get(line.line_type, line.line_type)

            plan_state = line.plan_id.state if line.plan_id else False

            is_draft = not plan_state or plan_state in ("draft", "returned", "info_requested")

            if is_draft:

                if line.line_type == "deposit":

                    # Deposit allows positive and negative targets; zero-check is enforced on submit

                    continue

                if line.line_type == "customer_base" and line.base_type == "dormant_reduction":

                    continue

                # For customer_base, digital_banking, fx: reject negative numbers only during draft

                for fname, month_label in self._FISCAL_MONTH_SEQUENCE:

                    val = getattr(line, fname, 0.0) or 0.0

                    if val < 0.0:

                        raise ValidationError(_(

                            "%(category)s — %(month)s: Monthly plan cannot be negative.",

                            category=cat_label,

                            month=month_label,

                        ))

                continue

            if line.line_type == "deposit":

                for fname, month_label in self._FISCAL_MONTH_SEQUENCE:

                    val = getattr(line, fname, 0.0) or 0.0

                    if float_is_zero(val, precision_digits=2):

                        raise ValidationError(_(

                            "%(category)s - %(month)s: Monthly plan cannot be zero. Each month must have a positive or negative target.",

                            category=cat_label,

                            month=month_label,

                        ))

                continue

            if line.line_type == "customer_base" and line.base_type == "dormant_reduction":

                continue

            for fname, month_label in self._FISCAL_MONTH_SEQUENCE:

                val = getattr(line, fname, 0.0) or 0.0

                if val <= 0:

                    raise ValidationError(_(

                        "%(category)s — %(month)s: Each month must have a value greater than zero.",

                        category=cat_label,

                        month=month_label,

                    ))

    @api.constrains(

        "line_type",

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

    )

    def _check_consolidable_monthly_nondecreasing(self):

        """Enforce a non-decreasing monthly planning hierarchy for the four

        consolidable categories. Each month's plan must be >= the previous

        month's plan (July through June). Equal values are allowed; decreasing

        values are rejected.

        In draft/input mode, trailing unfilled (0.0) months are ignored so that

        users are not blocked while entering data cell-by-cell. Full validation

        (all 12 months non-zero and non-decreasing) is enforced upon submission."""

        category_labels = dict(self._fields["line_type"].selection)

        for line in self:

            if line.line_type not in self._CONSOLIDABLE_LINE_TYPES:

                continue

            if line.line_type == "customer_base" and line.base_type == "dormant_reduction":

                continue

            cat_label = category_labels.get(line.line_type, line.line_type)

            month_vals = [(fname, m_label, getattr(line, fname, 0.0) or 0.0) for fname, m_label in self._FISCAL_MONTH_SEQUENCE]

            is_draft = not line.plan_id or line.plan_id.state in ("draft", "returned", "info_requested")

            if is_draft:

                last_non_zero_idx = -1

                for idx, (fname, m_label, val) in enumerate(month_vals):

                    if not float_is_zero(val, precision_digits=2):

                        last_non_zero_idx = idx

                if last_non_zero_idx <= 0:

                    continue

                active_sequence = month_vals[:last_non_zero_idx + 1]

            else:

                active_sequence = month_vals

            prev_val = None

            prev_label = None

            for fname, month_label, val in active_sequence:

                if prev_val is not None and float(val) < float(prev_val):

                    raise ValidationError(_(

                        "%(curr_month)s plan must not be below %(prev_month)s plan. Each month's plan must be greater than or equal to the previous month (%(curr_month)s: %(val)s, %(prev_month)s: %(prev_val)s).",

                        curr_month=month_label,

                        prev_month=prev_label,

                        val=val,

                        prev_val=prev_val,

                    ))

                prev_val = val

                prev_label = month_label

    @api.constrains("fx_source_type", "line_type")

    def _check_fx_fields(self):

        # FX Source dropdown is optional for FX Mobilization lines
        pass

    @api.constrains("deposit_type_id", "line_type")

    def _check_deposit_fields(self):

        # Deposit Type dropdown is optional for Deposit Mobilization lines
        pass

    @api.constrains("deposit_type_id", "line_type", "plan_id")

    def _check_deposit_type_unique_per_plan(self):

        """Prevent the same Deposit Type or Customer Base Product from being planned

        more than once per plan for branch units. District/HO units consolidate lines

        from multiple branches so duplicates are allowed there."""

        for line in self:

            if line.line_type not in ("deposit", "customer_base"):

                continue

            if not line.deposit_type_id or not line.plan_id:

                continue

            plan = line.plan_id

            # Only consolidation overview and merged plans aggregate multiple branches/units

            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):

                continue

            # Check for sibling lines with the same deposit_type_id (excluding self)

            if line.line_type == "deposit":

                siblings = plan.deposit_line_ids.filtered(

                    lambda l: l.id != line.id and l.deposit_type_id == line.deposit_type_id

                )

            else:

                siblings = plan.customer_base_line_ids.filtered(

                    lambda l: l.id != line.id and (

                        (line.customer_type_id and l.customer_type_id and l.customer_type_id == line.customer_type_id) or

                        (line.deposit_type_id and l.deposit_type_id and l.deposit_type_id == line.deposit_type_id) or

                        (line.customer_type_id and l.deposit_type_id and (line.customer_type_id.code == l.deposit_type_id.code or line.customer_type_id.name == l.deposit_type_id.name)) or

                        (line.deposit_type_id and l.customer_type_id and (line.deposit_type_id.code == l.customer_type_id.code or line.deposit_type_id.name == l.customer_type_id.name))

                    ) and l.base_type == line.base_type

                )

            if siblings:

                type_label = "Deposit Type" if line.line_type == "deposit" else "Product / Account Type"

                raise ValidationError(_(

                    "%(type_label)s '%(name)s' is already planned on this form. "

                    "Each %(type_label_lower)s can only be planned once per plan. "

                    "Please update the existing line instead of adding a duplicate.",

                    type_label=type_label,

                    type_label_lower=type_label.lower(),

                    name=line.deposit_type_id.display_name or line.deposit_type_id.name,

                ))

    @api.constrains("customer_type_id", "deposit_type_id", "base_type", "line_type")

    def _check_customer_base_fields(self):

        # Customer Type and Base Type dropdowns are optional for Customer Base lines
        pass

    @api.onchange("customer_type_id")
    def _onchange_customer_type_id_validate_plan(self):
        if not self.customer_type_id:
            return
        Config = self.env["pbms.planning.config"]
        org_unit = self.source_unit_id or self.org_unit_id or (self.plan_id.org_unit_id if self.plan_id else False)
        config = Config.get_config_for_unit(org_unit) if org_unit else False
        if config and config.customer_type_ids:
            if self.customer_type_id not in config.customer_type_ids:
                val_name = self.customer_type_id.display_name or self.customer_type_id.name
                self.customer_type_id = False
                cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
                return {
                    "warning": {
                        "title": _("Unplanned Dropdown Selection"),
                        "message": _("Customer Type '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                            "val": val_name,
                            "cycle": cycle_name,
                        }
                    }
                }

    @api.onchange("loan_product_id")
    def _onchange_loan_product_id_validate_plan(self):
        if not self.loan_product_id:
            return
        Config = self.env["pbms.planning.config"]
        org_unit = self.source_unit_id or self.org_unit_id or (self.plan_id.org_unit_id if self.plan_id else False)
        config = Config.get_config_for_unit(org_unit) if org_unit else False
        if config and config.loan_product_ids:
            allowed = config.loan_product_ids.filtered(lambda p: p.applies_to in ("outstanding", "both") and p.active)
            if self.loan_product_id not in allowed:
                val_name = self.loan_product_id.display_name or self.loan_product_id.name
                self.loan_product_id = False
                cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
                return {
                    "warning": {
                        "title": _("Unplanned Dropdown Selection"),
                        "message": _("Loan Product '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                            "val": val_name,
                            "cycle": cycle_name,
                        }
                    }
                }

    @api.onchange("loan_flow_type")
    def _onchange_loan_flow_type_validate_plan(self):
        if not self.loan_flow_type:
            return
        if self.loan_flow_type not in ("disbursement", "collection"):
            val_name = dict(self._fields["loan_flow_type"].selection).get(self.loan_flow_type, self.loan_flow_type)
            self.loan_flow_type = False
            cycle_name = (self.plan_id.cycle_id.name if self.plan_id and self.plan_id.cycle_id else False) or (self.cycle_id.name if self.cycle_id else False) or _("the selected planning period")
            return {
                "warning": {
                    "title": _("Unplanned Dropdown Selection"),
                    "message": _("Loan Disbursement & Collection '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {
                        "val": val_name,
                        "cycle": cycle_name,
                    }
                }
            }

    @api.constrains(
        "line_type",
        "plan_id",
        "deposit_type_id",
        "customer_type_id",
        "fx_source_type",
        "channel_id",
        "loan_flow_type",
        "loan_product_id",
    )
    def _check_dropdown_planned_for_period(self):
        """Enforce validation for all dropdown fields under the 6 planning categories:
        Customer Base, Deposit Mobilization, FX Mobilization, Digital Banking,
        Loan Disbursement and Collection, and Loan and Advance Outstanding.
        Ensures a dropdown selection has a corresponding plan configured for the selected planning period."""
        if self.env.context.get("bypass_plan_lock") or self.env.context.get("pbms_target_cascade"):
            return
        Config = self.env["pbms.planning.config"]
        for line in self:
            cat = line.line_type
            if cat not in (
                "customer_base",
                "deposit",
                "fx",
                "digital_banking",
                "loan_disbursement_collection",
                "loan_outstanding",
            ):
                continue
            plan = line.plan_id
            if not plan:
                continue
            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):
                continue
            unit_type = plan.org_unit_type or (plan.org_unit_id.work_unit_type if plan.org_unit_id else False)
            if unit_type in ("district_office", "head_office", "regional_office") and not self.env.context.get("force_validate_dropdowns"):
                continue

            cycle_name = line.cycle_id.name or plan.cycle_id.name or _("the selected planning period")
            org_unit = line.source_unit_id or line.org_unit_id or plan.org_unit_id
            config = Config.get_config_for_unit(org_unit) if org_unit else False

            if cat == "deposit":
                val = line.deposit_type_id
                if not val:
                    continue
                field_name = _("Deposit Type")
                available = config.deposit_type_ids if (config and config.deposit_type_ids) else self.env["pbms.deposit.type"].search([("active", "=", True)])
                if val not in available:
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val.display_name or val.name, "cycle": cycle_name}
                    )

            elif cat == "customer_base":
                val = line.customer_type_id
                if not val and line.deposit_type_id:
                    val = self.env["pbms.customer.type"].search([("code", "=", line.deposit_type_id.code)], limit=1)
                if not val:
                    continue
                field_name = _("Customer Type")
                available = config.customer_type_ids if (config and config.customer_type_ids) else self.env["pbms.customer.type"].search([("active", "=", True)])
                avail_codes = set(available.mapped("code"))
                if val not in available and val.code not in avail_codes:
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val.display_name or val.name, "cycle": cycle_name}
                    )

            elif cat == "fx":
                val = line.fx_source_type
                if not val:
                    continue
                field_name = _("FX Source")
                available = config.fx_source_type_ids if (config and config.fx_source_type_ids) else self.env["pbms.fx.source.type"].search([("active", "=", True)])
                if val not in available:
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val.display_name or val.name, "cycle": cycle_name}
                    )

            elif cat == "digital_banking":
                val = line.channel_id
                if not val:
                    continue
                field_name = _("Digital Channel")
                available = config.digital_channel_ids if (config and config.digital_channel_ids) else self.env["pbms.digital.channel"].search([("active", "=", True)])
                if val not in available:
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val.display_name or val.name, "cycle": cycle_name}
                    )

            elif cat == "loan_disbursement_collection":
                val = line.loan_flow_type
                if not val:
                    continue
                field_name = _("Loan Disbursement & Collection")
                if val not in ("disbursement", "collection"):
                    val_str = dict(line._fields["loan_flow_type"].selection).get(val, val or _("Empty"))
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val_str, "cycle": cycle_name}
                    )

            elif cat == "loan_outstanding":
                val = line.loan_product_id
                if not val:
                    continue
                field_name = _("Loan Product")
                if config and config.loan_product_ids:
                    available = config.loan_product_ids.filtered(lambda p: p.applies_to in ("outstanding", "both") and p.active)
                else:
                    available = self.env["pbms.loan.product"].search([("active", "=", True), ("applies_to", "in", ("outstanding", "both"))])
                if val not in available:
                    raise ValidationError(
                        _("%(field)s '%(val)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.")
                        % {"field": field_name, "val": val.display_name or val.name, "cycle": cycle_name}
                    )

    @api.constrains("channel_id", "line_type")

    def _check_digital_banking_fields(self):

        # Digital Channel dropdown is optional for Digital Banking lines
        pass

    @api.constrains("channel_id", "line_type", "plan_id")

    def _check_channel_unique_per_plan(self):

        """Prevent the same Digital Channel from being planned more than once per plan."""

        for line in self:

            if line.line_type != "digital_banking":

                continue

            if not line.channel_id or not line.plan_id:

                continue

            plan = line.plan_id

            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):

                continue

            siblings = plan.digital_banking_line_ids.filtered(

                lambda l: l.id != line.id and l.channel_id == line.channel_id and l.measurement == line.measurement

            )

            if siblings:

                raise ValidationError(_(

                    "Digital Channel '%(name)s' is already planned on this form. "

                    "Each channel can only be planned once per plan. "

                    "Please update the existing line instead of adding a duplicate.",

                    name=line.channel_id.display_name or line.channel_id.name,

                ))

    @api.constrains("fx_source_type", "line_type", "plan_id")

    def _check_fx_source_unique_per_plan(self):

        """Prevent the same FX Source from being planned more than once per plan."""

        for line in self:

            if line.line_type != "fx":

                continue

            if not line.fx_source_type or not line.plan_id:

                continue

            plan = line.plan_id

            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):

                continue

            siblings = plan.fx_line_ids.filtered(

                lambda l: l.id != line.id and l.fx_source_type == line.fx_source_type

            )

            if siblings:

                raise ValidationError(_(

                    "FX Source '%(name)s' is already planned on this form. "

                    "Each FX source can only be planned once per plan. "

                    "Please update the existing line instead of adding a duplicate.",

                    name=line.fx_source_type.display_name or line.fx_source_type.name,

                ))

    @api.constrains("expense_account_id", "line_type")

    def _check_general_expense_fields(self):

        for line in self:

            if line.line_type != "general_expense":

                continue

            if not line.expense_account_id:

                raise ValidationError(_("Expense Account is required for General Expense lines."))

    @api.constrains("credit_portfolio_item_id", "line_type")

    def _check_credit_portfolio_fields(self):

        for line in self:

            if line.line_type != "credit_portfolio":

                continue

            if not line.credit_portfolio_item_id:

                raise ValidationError(_("Portfolio Item is required for Income Plan lines."))

    @api.constrains("credit_portfolio_item_id", "line_type", "plan_id")

    def _check_credit_portfolio_item_unique(self):

        for line in self:

            if line.line_type != "credit_portfolio" or not line.credit_portfolio_item_id or not line.plan_id:

                continue

            plan = line.plan_id

            same_plan_lines = [

                l for l in plan.line_ids

                if l.line_type == "credit_portfolio" and not line._is_same_line(l)

            ]

            dups = [

                l for l in same_plan_lines

                if l.credit_portfolio_item_id == line.credit_portfolio_item_id

            ]

            if dups:

                raise ValidationError(_(

                    "Credit portfolio item '%(item)s' is already included in this plan.",

                    item=line.credit_portfolio_item_id.name,

                ))

    @api.constrains("initiative_name", "initiative_cost", "line_type")

    def _check_initiative_budget_fields(self):

        for line in self:

            if line.line_type != "initiative_budget":

                continue

            if not line.initiative_name:

                raise ValidationError(_("Initiative Name is required for Initiative Budget lines."))

            if (line.initiative_cost or 0.0) < 0:

                raise ValidationError(_("Initiative cost cannot be negative."))

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

                v = getattr(line, m_name)

                if v is not None:

                    if v < 0:

                        raise ValidationError(_("Workforce requests cannot be negative."))

                    if v != int(v):

                        raise ValidationError(_("Workforce requests must be whole numbers (integers), not decimal numbers."))

            for m_name in HC_MONTH_FIELDS:

                v = getattr(line, m_name)

                if v is not None:

                    if v < 0:

                        raise ValidationError(_("Workforce requests cannot be negative."))

                    if v != int(v):

                        raise ValidationError(_("Workforce requests must be whole numbers (integers), not decimal numbers."))

            for q_name in ("q1", "q2", "q3", "q4"):

                v = getattr(line, q_name)

                if v is not None:

                    if v < 0:

                        raise ValidationError(_("Additional requests for %s must be positive integers.") % q_name.upper())

                    if v != int(v):

                        raise ValidationError(_("Additional requests for %s must be whole numbers (integers).") % q_name.upper())

            if line.quantity is not None and line.quantity != int(line.quantity):

                raise ValidationError(_("Workforce quantity must be a whole number (integer)."))

            total_m = sum(getattr(line, m) or 0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))

            total_hc = sum(getattr(line, m) or 0 for m in HC_MONTH_FIELDS)

            total_quarterly = (line.quarter1_total or 0) + (line.quarter2_total or 0) + (line.quarter3_total or 0) + (line.quarter4_total or 0) + (line.q1 or 0) + (line.q2 or 0) + (line.q3 or 0) + (line.q4 or 0)

            if total_m <= 0 and total_hc <= 0 and total_quarterly <= 0 and (line.quantity or 0) <= 0:

                raise ValidationError(_("Total additional workforce request must be greater than zero."))

    @api.constrains("fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external", "annual_total", "quantity", "line_type")

    def _check_manpower_sourcing_not_greater_than_requested(self):

        for line in self:

            if line.line_type != "manpower":

                continue

            for f_name in ("fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external"):

                v = getattr(line, f_name) or 0

                if v < 0:

                    raise ValidationError(_("Sourcing allocations cannot be negative."))

                if v != int(v):

                    raise ValidationError(_("Sourcing allocations must be whole numbers (integers)."))

            target = int(round(line.annual_total or line.quantity or 0))

            tot_sourced = int((line.fulfillment_promotion or 0) + (line.fulfillment_transfer or 0) + (line.fulfillment_lateral or 0) + (line.fulfillment_external or 0))

            if tot_sourced > target:

                pos_name = line.job_id.name or line.new_job_title or (line.position_type_id.name if line.position_type_id else _("Position"))

                raise ValidationError(_(

                    "Sourcing Total Exceeds Request for '%s':\n"

                    "• Requested Headcount: %d\n"

                    "• Total Sourced: %d (Promotion: %d, Transfer: %d, Lateral: %d, External Vacancy: %d)\n\n"

                    "Total sourced (%d) cannot be greater than the requested headcount (%d). "

                    "In People Solutions Directorate, sourcing allocations must equal the requested headcount and cannot exceed it."

                ) % (pos_name, target, tot_sourced, line.fulfillment_promotion or 0, line.fulfillment_transfer or 0, line.fulfillment_lateral or 0, line.fulfillment_external or 0, tot_sourced, target))

    @api.constrains("other_justification", "item_description")

    def _check_line_no_special_characters(self):

        PROHIBITED_CHARS = set("@#$%&*!^()+={}[]|\\/<>?~")

        for line in self:

            for fname in ("other_justification", "item_description"):

                val = getattr(line, fname, False)

                if val and isinstance(val, str):

                    found = set(c for c in val if c in PROHIBITED_CHARS)

                    if found:

                        chars_str = " ".join(sorted(found))

                        raise ValidationError(

                            _("Special characters '%(chars)s' are not allowed in %(field)s. Prohibited characters: @ # $ % & * ! ^ ( ) + = { } [ ] | \\ / < > ? ~")

                            % {"chars": chars_str, "field": line._fields[fname].string or fname}

                        )


    @api.constrains("new_job_title", "reason", "other_justification", "business_justification", "item_description")

    def _check_text_field_not_pure_numbers(self):

        text_fields = {

            "new_job_title": _("New Job Title"),

            "reason": _("Reason"),

            "other_justification": _("Justification Remarks"),

            "business_justification": _("Business Justification"),

            "item_description": _("Item Description"),

        }

        for line in self:

            for fname, label in text_fields.items():

                val = getattr(line, fname, False)

                if val:

                    s = str(val).strip()

                    cleaned = s.replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")

                    if cleaned and cleaned.isdigit():

                        raise ValidationError(_("Field '%s' cannot be purely numbers. Please enter a meaningful text description.") % label)

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

    @api.constrains("fa_q1", "fa_q2", "fa_q3", "fa_q4", "quantity", "estimated_unit_price", "unit_cost", "line_type")

    def _check_fixed_asset_quantities(self):

        for line in self:

            if line.line_type != "fixed_asset":

                continue

            for q_name in ("fa_q1", "fa_q2", "fa_q3", "fa_q4", "quantity"):

                v = getattr(line, q_name, 0) or 0

                if v < 0:

                    raise ValidationError(_("Fixed Asset quantities cannot be negative."))

                if v != int(v):

                    raise ValidationError(_("Fixed Asset quantities must be whole numbers (integers), not decimal numbers."))

            for p_name in ("estimated_unit_price", "unit_cost"):

                p = getattr(line, p_name, 0.0) or 0.0

                if p < 0:

                    raise ValidationError(_("Fixed Asset unit price/cost cannot be negative."))

            total = (line.fa_q1 or 0) + (line.fa_q2 or 0) + (line.fa_q3 or 0) + (line.fa_q4 or 0)

            if total <= 0:

                raise ValidationError(_("At least one quarter must have a quantity greater than zero for Fixed Asset lines."))

    def _is_additional_position_type(self):

        """Returns True only when the position type is strictly code 'additional'

        or request type 'Additional Position', requiring operating unit eligible positions."""

        self.ensure_one()

        p_code = (self.position_type_id.code or "").strip().lower() if self.position_type_id else (self.position_type or "").strip().lower()

        p_name = (self.position_type_id.name or "").strip().lower() if self.position_type_id else ""

        return p_code == "additional" or p_name == "additional position"

    def _get_operating_unit_job_ids(self, org_unit):

        """Returns set of hr.job IDs eligible in the given operating unit."""

        if not org_unit:

            return set()

        ou_id = org_unit.id if isinstance(org_unit.id, int) else (org_unit._origin.id if getattr(org_unit, "_origin", False) else False)

        if not ou_id:

            return set()

        cache = getattr(self.env.cr, "cache", None)

        cache_key = f"_pbms_ou_job_ids_{ou_id}"

        if cache is not None and cache_key in cache:

            return set(cache[cache_key])

        unit_job_ids = set()

        if "operating.unit.job.position" in self.env:

            ou_positions = self.env["operating.unit.job.position"].search([

                ("operating_unit_id", "=", ou_id),

                ("active", "=", True),

            ])

            unit_job_ids.update(ou_positions.mapped("job_position_id.id"))

        if "hr.employee" in self.env:

            Employee = self.env["hr.employee"]

            emp_domain = [

                ("active", "=", True),

                "|",

                ("operating_unit_ids", "in", [ou_id]),

                ("default_operating_unit_id", "=", ou_id),

            ]

            job_field = "job_position" if "job_position" in Employee._fields else ("job_id" if "job_id" in Employee._fields else False)

            if job_field:

                employees = Employee.search_fetch(emp_domain, [job_field])

                for emp in employees:

                    j = getattr(emp, job_field, False)

                    if j:

                        unit_job_ids.add(j.id)

        if cache is not None:

            cache[cache_key] = tuple(unit_job_ids)

        return unit_job_ids

    @api.depends(

        "position_type_id",

        "position_type",

        "plan_id.org_unit_id",

    )

    def _compute_job_id_domain(self):

        import json

        default_domain_json = json.dumps([("active", "=", True)])

        for line in self:

            if line.line_type not in ("manpower", False):

                line.job_id_domain = default_domain_json

                continue

            domain = [("active", "=", True)]

            if line.line_type == "manpower" and line.plan_id:

                plan = line.plan_id

                if line._is_additional_position_type() and plan.org_unit_id:

                    unit_job_ids = line._get_operating_unit_job_ids(plan.org_unit_id)

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

            if self._is_additional_position_type() and plan.org_unit_id:

                unit_job_ids = self._get_operating_unit_job_ids(plan.org_unit_id)

                domain.append(("id", "in", list(unit_job_ids)))

                if self.job_id and unit_job_ids and self.job_id.id not in unit_job_ids:

                    self.job_id = False

                    self.job_grade_id = False

                    self.base_salary = 0.0

            other_lines = plan.manpower_line_ids.filtered(

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

        """Roll Jul-Jun monthly headcount into fiscal quarters and annual totals."""

        if self.line_type != "manpower":

            return

        month_keys = ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12")

        for m in month_keys:

            val_m = getattr(self, m, 0) or 0

            val_hc = getattr(self, f"hc_{m}", 0) or 0

            if val_m != val_hc:

                if val_m:

                    setattr(self, f"hc_{m}", int(round(val_m)))

                elif val_hc:

                    setattr(self, m, float(val_hc))

                else:

                    setattr(self, f"hc_{m}", 0)

                    setattr(self, m, 0.0)

        values = {m: int(round(getattr(self, m, 0) or 0)) for m in month_keys}

        q1_calc = sum(values[m] for m in ("m01", "m02", "m03"))

        q2_calc = sum(values[m] for m in ("m04", "m05", "m06"))

        q3_calc = sum(values[m] for m in ("m07", "m08", "m09"))

        q4_calc = sum(values[m] for m in ("m10", "m11", "m12"))

        self.q1 = int(round(q1_calc))

        self.q2 = int(round(q2_calc))

        self.q3 = int(round(q3_calc))

        self.q4 = int(round(q4_calc))

        self.quarter1_total = float(self.q1)

        self.quarter2_total = float(self.q2)

        self.quarter3_total = float(self.q3)

        self.quarter4_total = float(self.q4)

        self.annual_total = float(self.q1 + self.q2 + self.q3 + self.q4)

        self.quantity = int(round(self.annual_total))

        if not self.is_cascaded and (not self.plan_id or self.plan_id.state in ("draft", "returned", "info_requested")):

            self.proposed_annual_total = self.annual_total

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

        for line in self:

            if line.line_type == "manpower":

                line._apply_manpower_quarter_rollups()

                line._compute_quarter_costs()

                line._compute_annual_total_cost()

                plan_state = line.plan_id.state if line.plan_id else self.env.context.get("default_state")

                if plan_state in ("committee_review", "ceo_approval") or (

                    self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_ceo() or self.env.is_admin()

                ):

                    line._auto_balance_manpower_sourcing()

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

    @api.depends("line_type", "job_id", "job_grade_id", "position_type", "new_job_grade_id")
    def _compute_monthly_allowance(self):
        has_rule = "hr.salary.rule" in self.env
        has_grade_rule = "grade.salary.rule" in self.env
        has_pos_rule = "position.salary.rule" in self.env

        RuleModel = self.env["hr.salary.rule"] if has_rule else False
        GradeRuleModel = self.env["grade.salary.rule"] if has_grade_rule else False
        PosRuleModel = self.env["position.salary.rule"] if has_pos_rule else False

        for line in self:
            if line.line_type != "manpower":
                line.monthly_allowance = 0.0
                line.allowance_breakdown = ""
                continue

            grade = line.new_job_grade_id if line.position_type == "new" else line.job_grade_id
            job = line.job_id

            if not has_rule or (not grade and not job):
                if not line.monthly_allowance:
                    line.monthly_allowance = 0.0
                line.allowance_breakdown = line.allowance_breakdown or ""
                continue

            structure = getattr(grade, "salary_structure", False)
            base_rule_domain = [("active", "=", True), ("category_id.code", "=", "ALW")]
            if structure and structure.rule_ids:
                base_rule_domain.append(("id", "in", structure.rule_ids.ids))

            eligible_rules = RuleModel.search(base_rule_domain)
            if not eligible_rules:
                eligible_rules = RuleModel.search([("active", "=", True), ("category_id.code", "=", "ALW")])

            total_alw = 0.0
            breakdown_parts = []
            applied_rule_ids = set()

            # Direction 3: Both Position AND Grade
            if job and grade and has_pos_rule and "grade_id" in PosRuleModel._fields:
                both_matches = PosRuleModel.search([
                    ("salary_rule_id", "in", eligible_rules.ids),
                    ("position", "=", job.id),
                    ("grade_id", "=", grade.id),
                ])
                for m in both_matches:
                    if m.value and m.salary_rule_id.id not in applied_rule_ids:
                        total_alw += m.value
                        applied_rule_ids.add(m.salary_rule_id.id)
                        rule_name = m.salary_rule_id.code or m.salary_rule_id.name
                        breakdown_parts.append(f"{rule_name} (Pos+Grade): {m.value:,.2f}")

            # Direction 2: Position only
            if job and has_pos_rule:
                pos_domain = [
                    ("salary_rule_id", "in", eligible_rules.ids),
                    ("position", "=", job.id),
                ]
                if "grade_id" in PosRuleModel._fields:
                    pos_domain.append(("grade_id", "=", False))
                pos_matches = PosRuleModel.search(pos_domain)
                for m in pos_matches:
                    if m.value and m.salary_rule_id.id not in applied_rule_ids:
                        total_alw += m.value
                        applied_rule_ids.add(m.salary_rule_id.id)
                        rule_name = m.salary_rule_id.code or m.salary_rule_id.name
                        breakdown_parts.append(f"{rule_name} (Pos): {m.value:,.2f}")

            # Direction 1: Grade only
            if grade and has_grade_rule:
                grade_matches = GradeRuleModel.search([
                    ("salary_rule_id", "in", eligible_rules.ids),
                    ("grade2", "=", grade.id),
                ])
                for m in grade_matches:
                    if m.value and m.salary_rule_id.id not in applied_rule_ids:
                        total_alw += m.value
                        applied_rule_ids.add(m.salary_rule_id.id)
                        rule_name = m.salary_rule_id.code or m.salary_rule_id.name
                        breakdown_parts.append(f"{rule_name} (Grade): {m.value:,.2f}")

            line.monthly_allowance = total_alw
            line.allowance_breakdown = " | ".join(breakdown_parts) if breakdown_parts else ""

    @api.depends("base_salary", "monthly_allowance", "pension_rate")
    def _compute_compensation_breakdown(self):
        for line in self:
            salary = line.base_salary or 0.0
            allowance = line.monthly_allowance or 0.0
            p_rate = line.pension_rate or 0.0
            monthly_pen = salary * (p_rate / 100.0)
            monthly_total = salary + allowance + monthly_pen
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

        "line_type", "totals_basis",

    )

    def _compute_quarter_targets(self):

        for line in self:

            if line.line_type == "credit_portfolio" and line.totals_basis == "last_month":

                line.quarter1_total = line.m03 or 0.0

                line.quarter2_total = line.m06 or 0.0

                line.quarter3_total = line.m09 or 0.0

                line.quarter4_total = line.m12 or 0.0

            else:

                line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)

                line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)

                line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)

                line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)

    @api.onchange(

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

        "totals_basis", "initiative_cost",

    )

    def _onchange_months_update_quarters(self):

        for line in self:

            if line.line_type == "credit_portfolio" and line.totals_basis == "last_month":

                line.quarter1_total = line.m03 or 0.0

                line.quarter2_total = line.m06 or 0.0

                line.quarter3_total = line.m09 or 0.0

                line.quarter4_total = line.m12 or 0.0

                line.annual_total = line.m12 or 0.0

                line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

            elif line.line_type == "initiative_budget":

                line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)

                line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)

                line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)

                line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)

                line.annual_total = line.initiative_cost or 0.0

                line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

            else:

                line.quarter1_total = (line.m01 or 0.0) + (line.m02 or 0.0) + (line.m03 or 0.0)

                line.quarter2_total = (line.m04 or 0.0) + (line.m05 or 0.0) + (line.m06 or 0.0)

                line.quarter3_total = (line.m07 or 0.0) + (line.m08 or 0.0) + (line.m09 or 0.0)

                line.quarter4_total = (line.m10 or 0.0) + (line.m11 or 0.0) + (line.m12 or 0.0)

                if line.line_type not in ("manpower", "fixed_asset"):

                    line.annual_total = line.quarter1_total + line.quarter2_total + line.quarter3_total + line.quarter4_total

                    line.outstanding_year_end = (line.opening_balance or 0.0) + (line.annual_total or 0.0)

    @api.onchange("initiative_cost")

    def _onchange_initiative_cost(self):

        for line in self:

            if line.line_type == "initiative_budget":

                line.annual_total = line.initiative_cost or 0.0

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

    @api.depends(

        "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total",

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

        "fa_annual_total_cost", "line_type", "totals_basis", "initiative_cost",

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

            elif line.line_type == "initiative_budget":

                line.annual_total = line.initiative_cost or 0.0

            elif line.line_type == "credit_portfolio":

                if line.totals_basis == "last_month":

                    line.annual_total = line.m12 or 0.0

                else:

                    line.annual_total = (

                        (line.quarter1_total or 0.0)

                        + (line.quarter2_total or 0.0)

                        + (line.quarter3_total or 0.0)

                        + (line.quarter4_total or 0.0)

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

            if line.line_type in ("manpower", "fixed_asset", "initiative_budget"):

                continue

            if line.line_type == "credit_portfolio" and line.totals_basis == "last_month":

                line.m12 = line.annual_total

                line.quarter4_total = line.m12

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

                    if diff > 0:

                        last_idx = 11

                        for idx in reversed(range(12)):

                            if abs(old_months[idx]) > 1e-6:

                                last_idx = idx

                                break

                        rounded_months[last_idx] = round(rounded_months[last_idx] + diff, 2)

                    else:

                        first_idx = 0

                        for idx in range(12):

                            if abs(old_months[idx]) > 1e-6:

                                first_idx = idx

                                break

                        rounded_months[first_idx] = round(rounded_months[first_idx] + diff, 2)

            else:

                rounded_months = [int(round(val)) for val in new_months]

                diff = int(round(new_total)) - sum(rounded_months)

                if diff != 0:

                    if diff > 0:

                        last_idx = 11

                        for idx in reversed(range(12)):

                            if abs(old_months[idx]) > 1e-6:

                                last_idx = idx

                                break

                        rounded_months[last_idx] += diff

                    else:

                        first_idx = 0

                        for idx in range(12):

                            if abs(old_months[idx]) > 1e-6:

                                first_idx = idx

                                break

                        rounded_months[first_idx] += diff

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

            is_line_draft = not line.plan_id or line.plan_id.state in ("draft", "returned", "info_requested")

            if is_line_draft and not is_ho_review:

                # Only update proposed plan during draft/returned stage so planner submission is preserved

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

                            is_b_draft = not branch_line.plan_id or branch_line.plan_id.state in ("draft", "returned", "info_requested")

                            b_vals = {

                                "annual_total": new_total,

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

                            if is_b_draft:

                                b_vals["proposed_annual_total"] = new_total

                                b_vals["proposed_opening_balance"] = line.opening_balance or 0.0

                                for i, m in enumerate(MONTH_FIELDS):

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

                            is_d_draft = not dist_line.plan_id or dist_line.plan_id.state in ("draft", "returned", "info_requested")

                            d_vals = {

                                "annual_total": new_total,

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

                            if is_d_draft:

                                d_vals["proposed_annual_total"] = new_total

                                d_vals["proposed_opening_balance"] = line.opening_balance or 0.0

                                for i, m in enumerate(MONTH_FIELDS):

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
        for line in self:
            tot = sum(getattr(line, f"proposed_m{i:02d}") or 0.0 for i in range(1, 13))
            if tot > 0:
                line.proposed_annual_total = tot
            elif line.proposed_annual_total and (line.plan_id and line.plan_id.state not in ("draft", "returned", "info_requested")):
                # Preserve existing planner's proposed_annual_total once past draft!
                pass
            elif not line.plan_id or line.plan_id.state in ("draft", "returned", "info_requested"):
                line.proposed_annual_total = line.annual_total or 0.0
            else:
                line.proposed_annual_total = line.proposed_annual_total or line.annual_total or 0.0

    @api.depends("quantity", "line_type", "plan_id.state")
    def _compute_proposed_plan(self):
        for line in self:
            if line.line_type not in ("manpower", "fixed_asset"):
                line.proposed_plan = 0
                continue
            is_draft = not line.plan_id or line.plan_id.state in ("draft", "returned", "info_requested")
            if is_draft:
                line.proposed_plan = int(line.quantity or 0)
            elif line.proposed_plan:
                # Past draft with existing proposed_plan: PRESERVE planner's history!
                line.proposed_plan = line.proposed_plan
            else:
                line.proposed_plan = int(line.quantity or 0)
    @api.depends(

        "approved_m01", "approved_m02", "approved_m03", "approved_m04", "approved_m05", "approved_m06",

        "approved_m07", "approved_m08", "approved_m09", "approved_m10", "approved_m11", "approved_m12",

        "is_cascaded", "annual_total", "plan_id.state", "plan_id.org_unit_id.work_unit_type",

        "line_type", "plan_id.category", "totals_basis",

    )

    def _compute_approved_annual_total(self):

        CONSOLIDABLE_MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking"}

        for line in self:

            tot = sum(getattr(line, f"approved_m{i:02d}") or 0.0 for i in range(1, 13))

            is_expense = (line.line_type == "general_expense") or (line.plan_id and line.plan_id.category == "general_expense")

            is_manpower = (line.line_type == "manpower") or (line.plan_id and line.plan_id.category == "manpower")

            is_income = (line.line_type == "credit_portfolio") or (line.plan_id and line.plan_id.category == "credit_portfolio")

            is_loan = (line.line_type in ("loan_disbursement_collection", "loan_outstanding")) or (line.plan_id and line.plan_id.category in ("loan_disbursement_collection", "loan_outstanding"))

            is_consolidable = (line.line_type in CONSOLIDABLE_MOBILIZATION_CATS) or (line.plan_id and line.plan_id.category in CONSOLIDABLE_MOBILIZATION_CATS)

            if is_manpower:

                state = line.plan_id.state if line.plan_id else "draft"

                if state in ("ho_endorse", "cpco_endorse", "approved"):

                    line.approved_annual_total = line.approved_annual_total if line.approved_annual_total else (tot if tot > 0 else 0.0)

                else:

                    line.approved_annual_total = 0

            elif is_expense or is_income or is_loan:

                if line.plan_id and line.plan_id.state == "approved":

                    if is_income and line.totals_basis == "last_month":

                        line.approved_annual_total = getattr(line, "approved_m12", 0.0) or line.annual_total or 0.0

                    else:

                        line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)

                else:

                    line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or 0.0)

            elif is_consolidable:

                plan = line.plan_id

                ou = plan.org_unit_id if plan else line.org_unit_id

                is_ho = bool(

                    (plan and (plan.is_head_office_unit or plan._is_head_office_plan() or plan.org_unit_type == "head_office"))

                    or (ou and ou.work_unit_type == "head_office")

                )

                if is_ho:

                    if plan and plan.state == "approved":

                        line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)

                    else:

                        line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or 0.0)

                elif line.is_cascaded:

                    line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or 0.0)

                else:

                    # Branch (and un-cascaded District) mobilization lines must NEVER receive or display premature approved values!

                    line.approved_annual_total = 0.0

            elif line.is_cascaded:

                line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)

            elif line.plan_id and line.plan_id.state == "approved":

                line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or line.annual_total or 0.0)

            else:

                line.approved_annual_total = tot if tot > 0 else (line.approved_annual_total or 0.0)

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

                    line.display_approved_annual_total = 0

            # 3. State 'ho_endorse': CEO has approved.

            # Valued for Budget Hiring Committee, CEO, HO Reviewer, Admin.

            # For CPCO: not valued before HO reviewer endorses (0.0)!

            # For Branch Users, Districts, Chiefs, People Solutions: 0.0!

            elif state == "ho_endorse":

                if is_comm or is_ceo or is_ho or is_admin:

                    line.display_approved_annual_total = target

                else:

                    line.display_approved_annual_total = 0

            # 4. In all other states (draft, submitted, chief_review, people_solutions_review, cpco_review, committee_review, ceo_approval):

            # No valued! In ceo_approval, Approved Target must NOT be valued before CEO final approval takes action!

            else:

                line.display_approved_annual_total = 0

    @api.depends(

        "proposed_annual_total", "approved_annual_total", "annual_total",

        "is_cascaded", "plan_id.state", "plan_id.category", "line_type",

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

        "approved_m01", "approved_m02", "approved_m03", "approved_m04", "approved_m05", "approved_m06",

        "approved_m07", "approved_m08", "approved_m09", "approved_m10", "approved_m11", "approved_m12",

        "proposed_m01", "proposed_m02", "proposed_m03", "proposed_m04", "proposed_m05", "proposed_m06",

        "proposed_m07", "proposed_m08", "proposed_m09", "proposed_m10", "proposed_m11", "proposed_m12",

    )

    def _compute_target_variance(self):

        CONSOLIDABLE_MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking"}

        for line in self:

            is_consolidable = (line.line_type in CONSOLIDABLE_MOBILIZATION_CATS) or (line.plan_id and line.plan_id.category in CONSOLIDABLE_MOBILIZATION_CATS)

            plan = line.plan_id

            ou = plan.org_unit_id if plan else line.org_unit_id

            is_ho = bool(

                (plan and (plan.is_head_office_unit or plan._is_head_office_plan() or plan.org_unit_type == "head_office"))

                or (ou and ou.work_unit_type == "head_office")

            )

            # For consolidable mobilization categories: District and Branch plans MUST NOT show variance before cascade!

            if is_consolidable and not is_ho and not line.is_cascaded:

                line.variance_amount = 0.0

                line.variance_percentage = 0.0

                continue

            prop = line.proposed_annual_total or 0.0

            appr = line.approved_annual_total or 0.0

            active_tot = line.annual_total or 0.0

            if appr != 0.0:

                base = prop if prop != 0.0 else active_tot

                diff = appr - base

            elif not is_consolidable and prop != 0.0 and active_tot != 0.0 and abs(active_tot - prop) > 1e-4:

                diff = active_tot - prop

                base = prop

            else:

                diff = 0.0

                base = 0.0

            line.variance_amount = diff

            if base != 0.0:

                line.variance_percentage = round((diff / abs(base)) * 100.0, 2)

            else:

                line.variance_percentage = 0.0

    def _snapshot_proposed_targets(self, force=False):
        """Freeze current monthly values into proposed_m01..m12 and proposed_annual_total in batch.
        Preserves original planner history unless force=True."""
        if not self:
            return
        if force:
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
                    proposed_m12 = COALESCE(m12, 0.0),
                    proposed_plan = CASE
                        WHEN line_type IN ('manpower', 'fixed_asset') THEN
                            CASE WHEN COALESCE(proposed_plan, 0) != 0 AND (SELECT state FROM pbms_planning_category WHERE id = pbms_plan_category_line.plan_id) NOT IN ('draft', 'returned', 'info_requested')
                                 THEN proposed_plan
                                 ELSE COALESCE(quantity, 0)
                            END
                        ELSE 0
                    END
                WHERE id IN %s;
            """, (tuple(self.ids),))
        else:
            self.env.cr.execute("""
                UPDATE pbms_plan_category_line
                SET
                    proposed_opening_balance = CASE WHEN COALESCE(proposed_opening_balance, 0.0) != 0.0 THEN proposed_opening_balance ELSE COALESCE(opening_balance, 0.0) END,
                    proposed_annual_total = CASE WHEN COALESCE(proposed_annual_total, 0.0) != 0.0 THEN proposed_annual_total ELSE COALESCE(annual_total, 0.0) END,
                    proposed_m01 = CASE WHEN COALESCE(proposed_m01, 0.0) != 0.0 THEN proposed_m01 ELSE COALESCE(m01, 0.0) END,
                    proposed_m02 = CASE WHEN COALESCE(proposed_m02, 0.0) != 0.0 THEN proposed_m02 ELSE COALESCE(m02, 0.0) END,
                    proposed_m03 = CASE WHEN COALESCE(proposed_m03, 0.0) != 0.0 THEN proposed_m03 ELSE COALESCE(m03, 0.0) END,
                    proposed_m04 = CASE WHEN COALESCE(proposed_m04, 0.0) != 0.0 THEN proposed_m04 ELSE COALESCE(m04, 0.0) END,
                    proposed_m05 = CASE WHEN COALESCE(proposed_m05, 0.0) != 0.0 THEN proposed_m05 ELSE COALESCE(m05, 0.0) END,
                    proposed_m06 = CASE WHEN COALESCE(proposed_m06, 0.0) != 0.0 THEN proposed_m06 ELSE COALESCE(m06, 0.0) END,
                    proposed_m07 = CASE WHEN COALESCE(proposed_m07, 0.0) != 0.0 THEN proposed_m07 ELSE COALESCE(m07, 0.0) END,
                    proposed_m08 = CASE WHEN COALESCE(proposed_m08, 0.0) != 0.0 THEN proposed_m08 ELSE COALESCE(m08, 0.0) END,
                    proposed_m09 = CASE WHEN COALESCE(proposed_m09, 0.0) != 0.0 THEN proposed_m09 ELSE COALESCE(m09, 0.0) END,
                    proposed_m10 = CASE WHEN COALESCE(proposed_m10, 0.0) != 0.0 THEN proposed_m10 ELSE COALESCE(m10, 0.0) END,
                    proposed_m11 = CASE WHEN COALESCE(proposed_m11, 0.0) != 0.0 THEN proposed_m11 ELSE COALESCE(m11, 0.0) END,
                    proposed_m12 = CASE WHEN COALESCE(proposed_m12, 0.0) != 0.0 THEN proposed_m12 ELSE COALESCE(m12, 0.0) END,
                    proposed_plan = CASE
                        WHEN line_type IN ('manpower', 'fixed_asset') THEN
                            CASE WHEN COALESCE(proposed_plan, 0) != 0 THEN proposed_plan ELSE COALESCE(quantity, 0) END
                        ELSE 0
                    END
                WHERE id IN %s;
            """, (tuple(self.ids),))
        self.invalidate_recordset([
            "proposed_opening_balance", "proposed_annual_total", "proposed_plan",
            "proposed_m01", "proposed_m02", "proposed_m03", "proposed_m04",
            "proposed_m05", "proposed_m06", "proposed_m07", "proposed_m08",
            "proposed_m09", "proposed_m10", "proposed_m11", "proposed_m12",
        ])
    def _populate_approved_targets_batch(self):

        """Populate approved targets from existing values or actual values in batch SQL."""

        if not self:

            return

        self.env.cr.execute("""

            UPDATE pbms_plan_category_line

            SET

                approved_opening_balance = COALESCE(NULLIF(approved_opening_balance, 0.0), opening_balance, 0.0),

                approved_annual_total = COALESCE(NULLIF(approved_annual_total, 0.0), annual_total, 0.0),

                approved_m01 = COALESCE(NULLIF(approved_m01, 0.0), m01, 0.0),

                approved_m02 = COALESCE(NULLIF(approved_m02, 0.0), m02, 0.0),

                approved_m03 = COALESCE(NULLIF(approved_m03, 0.0), m03, 0.0),

                approved_m04 = COALESCE(NULLIF(approved_m04, 0.0), m04, 0.0),

                approved_m05 = COALESCE(NULLIF(approved_m05, 0.0), m05, 0.0),

                approved_m06 = COALESCE(NULLIF(approved_m06, 0.0), m06, 0.0),

                approved_m07 = COALESCE(NULLIF(approved_m07, 0.0), m07, 0.0),

                approved_m08 = COALESCE(NULLIF(approved_m08, 0.0), m08, 0.0),

                approved_m09 = COALESCE(NULLIF(approved_m09, 0.0), m09, 0.0),

                approved_m10 = COALESCE(NULLIF(approved_m10, 0.0), m10, 0.0),

                approved_m11 = COALESCE(NULLIF(approved_m11, 0.0), m11, 0.0),

                approved_m12 = COALESCE(NULLIF(approved_m12, 0.0), m12, 0.0)

            WHERE id IN %s;

        """, (tuple(self.ids),))

        self.invalidate_recordset([

            "approved_opening_balance", "approved_annual_total",

            "approved_m01", "approved_m02", "approved_m03", "approved_m04",

            "approved_m05", "approved_m06", "approved_m07", "approved_m08",

            "approved_m09", "approved_m10", "approved_m11", "approved_m12",

        ])

    def _populate_approved_from_annual_total_batch(self):

        """Populate approved targets directly from annual_total and m01..m12 in batch SQL."""

        if not self:

            return

        self.env.cr.execute("""

            UPDATE pbms_plan_category_line

            SET

                approved_opening_balance = COALESCE(opening_balance, 0.0),

                approved_annual_total = COALESCE(annual_total, 0.0),

                approved_m01 = COALESCE(m01, 0.0),

                approved_m02 = COALESCE(m02, 0.0),

                approved_m03 = COALESCE(m03, 0.0),

                approved_m04 = COALESCE(m04, 0.0),

                approved_m05 = COALESCE(m05, 0.0),

                approved_m06 = COALESCE(m06, 0.0),

                approved_m07 = COALESCE(m07, 0.0),

                approved_m08 = COALESCE(m08, 0.0),

                approved_m09 = COALESCE(m09, 0.0),

                approved_m10 = COALESCE(m10, 0.0),

                approved_m11 = COALESCE(m11, 0.0),

                approved_m12 = COALESCE(m12, 0.0)

            WHERE id IN %s;

        """, (tuple(self.ids),))

        self.invalidate_recordset([

            "approved_opening_balance", "approved_annual_total",

            "approved_m01", "approved_m02", "approved_m03", "approved_m04",

            "approved_m05", "approved_m06", "approved_m07", "approved_m08",

            "approved_m09", "approved_m10", "approved_m11", "approved_m12",

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

                is_authorized_review_edit = (
                    (line.line_type == "manpower" and line.plan_id.state == "people_solutions_review" and self.env.user._pbms_is_people_solutions())
                    or (line.plan_id.state == "committee_review" and self.env.user._pbms_is_budget_hiring_committee())
                    or (line.plan_id.state in ("ceo_approval", "board_ceo_approval") and (self.env.user._pbms_is_ceo() or self.env.user._pbms_is_sppmd_admin()))
                )
                if is_authorized_review_edit:
                    continue

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

        is_admin = (

            self.env.is_admin()

            or user._pbms_is_sppmd_admin()

            or self.env.su

            or self.env.context.get("pbms_target_cascade")

            or self.env.context.get("bypass_plan_lock")

        )

        for vals in vals_list:

            _validate_month_values_not_text(vals)

            for doc_f in ("plan_workforce_document", "plan_workforce_document_filename", "workforce_document", "workforce_document_filename"):

                if doc_f in vals and not vals[doc_f]:

                    vals.pop(doc_f, None)

            target_line_type = vals.get("line_type") or self.env.context.get("default_line_type")

            plan_id = vals.get("plan_id")

            if not plan_id:

                plan_id = (

                    self.env.context.get("default_plan_id")

                    or self.env.context.get("plan_id")

                    or (self.env.context.get("active_id") if self.env.context.get("active_model") == "pbms.planning.category" else False)

                )

                if not plan_id and self.env.context.get("params", {}).get("id") and self.env.context.get("params", {}).get("model") == "pbms.planning.category":

                    plan_id = self.env.context.get("params", {}).get("id")

            if not target_line_type and plan_id:

                curr_p = Plan.browse(plan_id)

                if curr_p.exists() and curr_p.category:

                    target_line_type = curr_p.category

                    vals["line_type"] = target_line_type

            if vals.get("quantity") and not any(vals.get(m) for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12", "q1", "q2", "q3", "q4")):

                q_val = vals["quantity"]

                if target_line_type == "fixed_asset" and not any(vals.get(f) for f in ("fa_q1", "fa_q2", "fa_q3", "fa_q4")):

                    vals["fa_q1"] = q_val

                else:

                    vals["m01"] = float(q_val)

            if target_line_type == "customer_base":
                if vals.get("customer_type_id") and not vals.get("deposit_type_id"):
                    ct = self.env["pbms.customer.type"].browse(vals["customer_type_id"])
                    if ct and ct.exists():
                        dt = self.env["pbms.deposit.type"].search([("code", "=", ct.code)], limit=1)
                        if dt:
                            vals["deposit_type_id"] = dt.id
                elif vals.get("deposit_type_id") and not vals.get("customer_type_id"):
                    dt = self.env["pbms.deposit.type"].browse(vals["deposit_type_id"])
                    if dt and dt.exists():
                        ct = self.env["pbms.customer.type"].search([("code", "=", dt.code)], limit=1)
                        if ct:
                            vals["customer_type_id"] = ct.id

            if vals.get("position_type") and not vals.get("position_type_id"):

                is_new = (vals["position_type"] == "new")

                p_type = self.env["pbms.position.type"].search([

                    ("code", "=", "new" if is_new else "additional")

                ], limit=1)

                if not p_type and not is_new:

                    p_type = self.env["pbms.position.type"].search([

                        ("is_new_position", "=", False)

                    ], limit=1)

                if p_type:

                    vals["position_type_id"] = p_type.id

            # Validate plan_id matches target_line_type to avoid saving across different categories

            if plan_id and target_line_type and not self.env.context.get("is_planning_request"):

                curr_plan = Plan.browse(plan_id)

                if curr_plan.exists() and curr_plan.category and curr_plan.category != target_line_type:

                    found_plan = Plan.search([

                        ("org_unit_id", "=", curr_plan.org_unit_id.id),

                        ("cycle_id", "=", curr_plan.cycle_id.id),

                        ("category", "=", target_line_type),

                        ("active", "=", True),

                    ], limit=1)

                    if not found_plan:

                        create_p_vals = {

                            "org_unit_id": curr_plan.org_unit_id.id,

                            "cycle_id": curr_plan.cycle_id.id,

                            "company_id": curr_plan.company_id.id if curr_plan.company_id else self.env.company.id,

                            "category": target_line_type,

                            "state": curr_plan.state if curr_plan.state else "draft",

                        }

                        if curr_plan.workforce_document or curr_plan.workforce_document_base64:

                            doc_b64 = curr_plan.workforce_document_base64 or curr_plan.workforce_document

                            create_p_vals.update({

                                "workforce_document": doc_b64,

                                "workforce_document_filename": curr_plan.workforce_document_filename,

                                "workforce_document_base64": doc_b64,

                            })

                        found_plan = Plan.sudo().create(create_p_vals)

                    elif (curr_plan.workforce_document or curr_plan.workforce_document_base64) and not found_plan.workforce_document:

                        doc_b64 = curr_plan.workforce_document_base64 or curr_plan.workforce_document

                        found_plan.sudo().with_context(bypass_plan_lock=True, in_workforce_doc_sync=True, skip_sync_category_records=True).write({

                            "workforce_document": doc_b64,

                            "workforce_document_filename": curr_plan.workforce_document_filename,

                            "workforce_document_base64": doc_b64,

                        })

                    plan_id = found_plan.id

                    vals["plan_id"] = plan_id

            if not plan_id:

                org_unit_id = vals.get("org_unit_id") or self.env.context.get("default_org_unit_id") or (self.env.user.default_operating_unit_id.id if self.env.user.default_operating_unit_id else False)

                cycle_id = vals.get("cycle_id") or self.env.context.get("default_cycle_id")

                if not cycle_id:

                    open_c = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)

                    cycle_id = open_c.id if open_c else False

                Config = self.env["pbms.planning.config"] if "pbms.planning.config" in self.env else False

                default_type = Config.get_default_category_for_unit(org_unit_id) if (Config and org_unit_id) else "deposit"

                line_type = target_line_type or default_type

                if org_unit_id and cycle_id:

                    found_plan = Plan.search([

                        ("org_unit_id", "=", org_unit_id),

                        ("cycle_id", "=", cycle_id),

                        ("category", "=", line_type),

                        ("active", "=", True),

                    ], limit=1)

                    if found_plan:

                        plan_id = found_plan.id

                    else:

                        new_plan = Plan.sudo().create({

                            "org_unit_id": org_unit_id,

                            "cycle_id": cycle_id,

                            "category": line_type,

                            "state": "draft",

                        })

                        plan_id = new_plan.id

            if plan_id:

                vals["plan_id"] = plan_id

            if plan_id and not is_admin:

                plan = Plan.browse(plan_id)

                if not is_bypass and (user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer() or user._pbms_is_respective_chief()):

                    if not plan._is_own_operating_unit_plan():

                        raise UserError(_(

                            "Reviewers and Chiefs cannot add new lines to subordinate operating unit plans. "

                            "You can only edit lines submitted by the operating unit, or add lines to your own operating unit's plan."

                        ))

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

        vals_list = [self._pbms_mirror_manpower_months(v) for v in vals_list]

        records = super().create(vals_list)

        plans_with_doc = records.mapped("plan_id").filtered(lambda p: p.workforce_document or p.workforce_document_base64)

        if plans_with_doc and hasattr(plans_with_doc, "_sync_workforce_document_to_siblings"):

            plans_with_doc._sync_workforce_document_to_siblings()

        return records

    @api.model

    def _pbms_mirror_manpower_months(self, vals):

        """Workforce months are typed into hc_mNN (integer) in the form, while

        list views, group totals and exports read mNN.  Keep both in step so the

        list shows exactly what the form shows."""

        vals = dict(vals)

        is_manpower = vals.get("line_type") == "manpower" or (

            "line_type" not in vals and self.env.context.get("default_line_type") == "manpower")

        if not is_manpower:

            return vals

        for m in MONTH_FIELDS:

            hc = "hc_%s" % m

            if hc in vals and m not in vals:

                vals[m] = float(vals[hc] or 0)

        return vals

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

        "plan_review_comment",

        "latest_review_comment",

        "plan_people_solutions_comment",

        "people_solutions_comment",

        "plan_cpco_comment",

        "cpco_comment",

        "plan_cpco_attachment_ids",

        "cpco_attachment_ids",

        "plan_workforce_document",

        "plan_workforce_document_filename",

        "workforce_document",

        "workforce_document_filename",

    }

    def write(self, vals):

        _validate_month_values_not_text(vals)

        if "plan_cpco_attachment_ids" in vals and not self.env.context.get("bypass_plan_lock"):

            for line in self:

                if not line.plan_id or line.plan_id.state != "cpco_review" or not line.plan_id.can_cpco_review:

                    raise UserError(_("CPCO Attachments can only be added or modified by a user with CPCO privilege while the plan is in the CPCO Review stage."))

        if any(f in vals for f in ("plan_workforce_document", "plan_workforce_document_filename", "workforce_document", "workforce_document_filename")) and not self.env.context.get("bypass_plan_lock"):

            for line in self:

                if line.plan_id and line.plan_id.state not in ("draft", "returned", "info_requested"):

                    raise UserError(_("You cannot upload or modify the attached document after the plan has been submitted."))

        if "plan_id" in vals and not vals["plan_id"]:

            vals = dict(vals)

            del vals["plan_id"]

            if not vals:

                return True

        if not set(vals.keys()).issubset(self.SYSTEM_AUTOMATED_LINE_FIELDS):

            self._pbms_check_parent_plan_editable()

        if any(("hc_%s" % m) in vals for m in MONTH_FIELDS):

            manpower_lines = self.filtered(lambda l: l.line_type == "manpower")

            if manpower_lines and manpower_lines == self:

                vals = self._pbms_mirror_manpower_months(dict(vals, line_type="manpower"))

                vals.pop("line_type", None)

        if "proposed_plan" in vals and not self.env.context.get("bypass_plan_lock"):
            for line in self:
                if line.plan_id and line.plan_id.state not in ("draft", "returned", "info_requested"):
                    vals = dict(vals)
                    del vals["proposed_plan"]
                    break

        MONTH_OR_QTY_FIELDS = {"m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12", "q1", "q2", "q3", "q4", "quantity", "annual_total"}
        if any(f in vals for f in MONTH_OR_QTY_FIELDS) and "fulfillment_external" not in vals and not self.env.context.get("auto_balancing_sourcing"):
            for line in self:
                if line.line_type == "manpower":
                    target = vals.get("quantity") or vals.get("annual_total")
                    if target is None:
                        target = sum(vals.get(m, getattr(line, m) or 0) for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
                    target = int(round(target or 0))
                    prom = int(vals.get("fulfillment_promotion", line.fulfillment_promotion or 0))
                    trans = int(vals.get("fulfillment_transfer", line.fulfillment_transfer or 0))
                    lat = int(vals.get("fulfillment_lateral", line.fulfillment_lateral or 0))
                    internal = prom + trans + lat
                    vals = dict(vals)
                    vals["fulfillment_external"] = max(0, target - internal)
                    break

        if any(f in vals for f in ("fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral")) and "fulfillment_external" not in vals and not self.env.context.get("auto_balancing_sourcing"):

            for line in self:

                if line.line_type == "manpower":

                    target = int(round(vals.get("annual_total", line.annual_total or line.quantity or 0)))

                    prom = int(vals.get("fulfillment_promotion", line.fulfillment_promotion or 0))

                    trans = int(vals.get("fulfillment_transfer", line.fulfillment_transfer or 0))

                    lat = int(vals.get("fulfillment_lateral", line.fulfillment_lateral or 0))

                    internal = prom + trans + lat

                    vals = dict(vals)

                    vals["fulfillment_external"] = max(0, target - internal)

                    break

        res = super().write(vals)

        if any(f in vals for f in ("plan_workforce_document", "plan_workforce_document_filename", "workforce_document", "workforce_document_filename")):

            plans_with_doc = self.mapped("plan_id").filtered(lambda p: p.workforce_document or p.workforce_document_base64)

            if plans_with_doc and hasattr(plans_with_doc, "_sync_workforce_document_to_siblings"):

                plans_with_doc._sync_workforce_document_to_siblings()

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

        if not is_bypass and (user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer() or user._pbms_is_respective_chief()):

            for line in self:

                if line.plan_id and not line.plan_id._is_own_operating_unit_plan():

                    raise UserError(_(

                        "Reviewers and Chiefs cannot delete lines from subordinate operating unit plans. "

                        "You can only edit lines submitted by the operating unit, or manage lines for your own operating unit's plan."

                    ))

        self._pbms_check_parent_plan_editable()

        parent_plans = self.mapped("plan_id")

        res = super().unlink()

        if (

            parent_plans

            and not self.env.context.get("in_consolidation")

            and not self.env.context.get("skip_empty_plan_cleanup")

            and not self.env.context.get("bypass_plan_lock")

            and not self.env.context.get("skip_reviewer_check")

            and not self.env.context.get("pbms_target_cascade")

        ):

            empty_plans = parent_plans.sudo().exists().filtered(lambda p: not p.line_ids)

            if empty_plans:

                try:

                    empty_plans.sudo().with_context(bypass_plan_lock=True, skip_empty_plan_cleanup=True).unlink()

                except Exception:

                    pass

        return res

    def action_export_excel(self):

        """Export selected plan requirement lines using official Bunna Bank form templates."""

        records = self or self.browse(self.env.context.get("active_ids", []))

        line_types = [t for t in records.mapped("line_type") if t]

        target_category = line_types[0] if len(set(line_types)) == 1 else False

        plans = records.mapped("plan_id")

        if plans:

            ctx = dict(self.env.context)

            if target_category:

                ctx["target_category"] = target_category

            return plans.with_context(ctx).action_export_excel()

        raise UserError(_("No planning records associated with the selected lines."))

    @api.model

    def fields_get(self, allfields=None, attributes=None):

        res = super().fields_get(allfields=allfields, attributes=attributes)

        NON_EXPORTABLE_LINE_FIELDS = {

            "deposit_type_domain", "channel_domain", "expense_account_domain",

            "fa_category_domain", "justification_category_domain", "fx_source_type_domain",

            "credit_portfolio_item_domain", "is_monetary", "new_job_grade",

        }

        for fname in NON_EXPORTABLE_LINE_FIELDS:

            if fname in res:

                res[fname]["exportable"] = False

        return res

    @api.model
    def _extract_line_type_from_domain(self, domain):
        if not domain:
            return False
        line_types = set()
        def _traverse(item):
            if isinstance(item, (list, tuple)):
                if len(item) == 3 and isinstance(item[0], str) and item[0] in ("line_type", "plan_id.category", "category"):
                    op, val = item[1], item[2]
                    if op == "=" and isinstance(val, str):
                        line_types.add(val)
                    elif op in ("in", "=") and isinstance(val, (list, tuple, set)) and len(val) == 1:
                        first = next(iter(val))
                        if isinstance(first, str):
                            line_types.add(first)
                else:
                    for sub in item:
                        _traverse(sub)
        _traverse(domain)
        return next(iter(line_types)) if len(line_types) == 1 else False

    @api.model
    @api.readonly
    def web_read_group(self, domain, groupby, *args, **kwargs):
        if not (self.env.context.get("default_line_type") or self.env.context.get("default_category")):
            lt = self._extract_line_type_from_domain(domain)
            if lt:
                self = self.with_context(default_line_type=lt, default_category=lt)
        return super().web_read_group(domain, groupby, *args, **kwargs)

    @api.model
    def _add_groupby_values(self, groupby_read_specification, groupby, current_groups):
        if not groupby_read_specification or groupby_read_specification.keys().isdisjoint(groupby):
            return

        top_groups = current_groups
        default_lt = self.env.context.get("default_line_type") or self.env.context.get("default_category")

        # Recursively propagate _pbms_line_type to all groups and subgroups so any nested
        # level (district, operating unit, branch) knows its active planning category!
        def _propagate_line_type(groups, current_lt):
            for g in groups:
                lt = g.get("line_type") or current_lt
                if lt:
                    g["_pbms_line_type"] = lt
                subgroups = g.get("__groups", {}).get("groups", [])
                if subgroups:
                    _propagate_line_type(subgroups, lt)

        _propagate_line_type(current_groups, default_lt)

        for groupby_spec in groupby:
            if not current_groups:
                break
            if groupby_spec in groupby_read_specification:
                relational_field = self._fields[groupby_spec.split(":")[0]]
                comodel = self.env[relational_field.comodel_name]
                groups_by_lt = {}
                for group in current_groups:
                    lt = group.get("_pbms_line_type") or default_lt or False
                    groups_by_lt.setdefault(lt, []).append(group)

                for lt, lt_groups in groups_by_lt.items():
                    group_ids = list({
                        id_label[0]
                        for g in lt_groups
                        if (id_label := g.get(groupby_spec))
                    })
                    if not group_ids:
                        for g in lt_groups:
                            g["__values"] = {"id": False}
                        continue
                    if lt:
                        records = comodel.with_context(default_line_type=lt, default_category=lt).browse(group_ids)
                    else:
                        records = comodel.browse(group_ids)
                    records.invalidate_recordset()
                    result_read = records.web_read(groupby_read_specification[groupby_spec])
                    result_read_map = dict(zip(records._ids, result_read, strict=True))
                    for g in lt_groups:
                        id_label = g.get(groupby_spec)
                        g["__values"] = dict(result_read_map[id_label[0]]) if id_label else {"id": False}

            current_groups = [
                subgroup
                for group in current_groups
                for subgroup in group.get("__groups", {}).get("groups", ())
            ]

        def _cleanup_pbms_lt(grp_list):

            for grp in grp_list or ():

                grp.pop("_pbms_line_type", None)

                _cleanup_pbms_lt(grp.get("__groups", {}).get("groups", ()))

        _cleanup_pbms_lt(top_groups)

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

    # ------------------------------------------------------------------

    # Plan-level workflow buttons shown on every line row of the nested

    # lists.  The visibility flags mirror the plan form (non-stored related

    # fields, evaluated for the current user) and the actions are forwarded

    # to the parent plan, so the same permissions/guards as the form apply.

    # ------------------------------------------------------------------

    plan_cat = fields.Selection(related="plan_id.category", string="Plan Category", compute_sudo=False)

    plan_is_cycle_open = fields.Boolean(related="plan_id.is_cycle_open", compute_sudo=False)

    plan_is_district_unit = fields.Boolean(related="plan_id.is_district_unit", compute_sudo=False)

    plan_is_head_office_unit = fields.Boolean(related="plan_id.is_head_office_unit", compute_sudo=False)

    plan_can_chief_review = fields.Boolean(related="plan_id.can_chief_review", compute_sudo=False)

    plan_can_submit_plan = fields.Boolean(related="plan_id.can_submit_plan", compute_sudo=False)

    plan_can_district_review = fields.Boolean(related="plan_id.can_district_review", compute_sudo=False)

    plan_can_ho_review = fields.Boolean(related="plan_id.can_ho_review", compute_sudo=False)

    plan_can_sppmd_review = fields.Boolean(related="plan_id.can_sppmd_review", compute_sudo=False)

    plan_can_people_solutions_review = fields.Boolean(related="plan_id.can_people_solutions_review", compute_sudo=False)

    plan_can_cpco_review = fields.Boolean(related="plan_id.can_cpco_review", compute_sudo=False)

    plan_can_committee_review = fields.Boolean(related="plan_id.can_committee_review", compute_sudo=False)

    plan_can_ceo_approve = fields.Boolean(related="plan_id.can_ceo_approve", compute_sudo=False)

    plan_can_ho_endorse = fields.Boolean(related="plan_id.can_ho_endorse", compute_sudo=False)

    plan_can_cpco_endorse = fields.Boolean(related="plan_id.can_cpco_endorse", compute_sudo=False)

    plan_can_delete_plan = fields.Boolean(related="plan_id.can_delete_plan", compute_sudo=False)

    plan_can_edit_content = fields.Boolean(related="plan_id.can_edit_content", compute_sudo=False)

    plan_can_use_reviewer_actions = fields.Boolean(related="plan_id.can_use_reviewer_actions", compute_sudo=False)

    plan_can_use_reviewer_wizards = fields.Boolean(related="plan_id.can_use_reviewer_wizards", compute_sudo=False)

    plan_has_cascaded_targets = fields.Boolean(related="plan_id.has_cascaded_targets", compute_sudo=False)

    plan_is_targets_cascaded = fields.Boolean(related="plan_id.is_targets_cascaded", compute_sudo=False)

    plan_can_edit_sourcing_fields = fields.Boolean(related="plan_id.can_edit_sourcing_fields", compute_sudo=False)

    plan_can_view_sourcing_fields = fields.Boolean(related="plan_id.can_view_sourcing_fields", compute_sudo=False)

    plan_review_comment = fields.Text(related="plan_id.latest_review_comment", string="Review Comment", readonly=False, compute_sudo=False)

    plan_people_solutions_comment = fields.Text(related="plan_id.people_solutions_comment", string="People Solutions Comment", readonly=False, compute_sudo=False)

    plan_cpco_comment = fields.Text(related="plan_id.cpco_comment", string="CPCO Comment", readonly=False, compute_sudo=False)

    plan_cpco_attachment_ids = fields.Many2many(related="plan_id.cpco_attachment_ids", string="CPCO Attachments", readonly=False)

    plan_workforce_document = fields.Binary(related="plan_id.workforce_document", string="Plan Workforce Document", readonly=False)

    plan_workforce_document_filename = fields.Char(related="plan_id.workforce_document_filename", string="Plan Workforce Document Filename", readonly=False)

    workforce_document = fields.Binary(related="plan_id.workforce_document", string="Attach Document", readonly=False)

    workforce_document_filename = fields.Char(related="plan_id.workforce_document_filename", string="Document Filename", readonly=False)

    _PBMS_PLAN_METHODS = frozenset({

        "action_submit", "action_reset_to_draft", "action_district_approve",

        "action_district_approve_workforce", "action_ho_approve",

        "action_submit_to_committee", "action_committee_approve_resource",

        "action_chief_approve_escalate", "action_people_solutions_escalate_cpco",

        "action_cpco_submit_to_committee", "action_committee_approve",

        "action_ceo_approve", "action_ho_endorse_to_cpco",

        "action_cpco_endorse_to_solutions", "action_approve",

        "action_consolidate_district_overview",

        "action_already_cascaded_notice", "action_open_import_wizard",

        "action_export_excel", "action_refresh_existing_manpower",

    })

    _PBMS_PLAN_WIZARDS = {

        "review_comment": ("bunna_pbms.action_pbms_review_comment_wizard", {}),

        "request_info": ("bunna_pbms.action_pbms_request_info_wizard", {}),

        "return": ("bunna_pbms.action_pbms_return_revision_wizard", {}),

        "reject": ("bunna_pbms.action_pbms_reject_wizard", {}),

        "cascade_district": ("bunna_pbms.action_pbms_target_cascade_district_wizard",

                             {"default_cascade_level": "district_to_branch"}),

        "cascade_ho": ("bunna_pbms.action_pbms_target_cascade_ho_wizard",

                       {"default_cascade_level": "ho_to_district"}),

    }

    def _pbms_plan_for_button(self):

        self.ensure_one()

        if not self.plan_id:

            raise UserError(_("This line is not attached to a plan."))

        return self.plan_id.with_context(

            active_id=self.plan_id.id,

            active_ids=self.plan_id.ids,

            active_model="pbms.planning.category",

        )

    def action_plan_dispatch(self):

        """Forward a workflow button clicked on a line row to its parent plan."""

        method = self.env.context.get("pbms_plan_method")

        if method not in self._PBMS_PLAN_METHODS:

            raise UserError(_("Unsupported plan action."))

        return getattr(self._pbms_plan_for_button(), method)()

    def action_plan_wizard(self):

        """Open a plan wizard (comment / info / return / reject / cascade) for the parent plan."""

        from ast import literal_eval

        key = self.env.context.get("pbms_wizard")

        if key not in self._PBMS_PLAN_WIZARDS:

            raise UserError(_("Unsupported plan wizard."))

        plan = self._pbms_plan_for_button()

        xmlid, extra = self._PBMS_PLAN_WIZARDS[key]

        action = self.env["ir.actions.actions"]._for_xml_id(xmlid)

        ctx = dict(literal_eval(action.get("context") or "{}"))

        ctx.update(extra)

        ctx.update(

            active_id=plan.id, active_ids=plan.ids,

            active_model="pbms.planning.category", default_plan_id=plan.id,

        )

        action["context"] = ctx

        return action

    def action_open_plan(self):

        """Open the parent plan (header) form of this line."""

        self.ensure_one()

        return {

            "type": "ir.actions.act_window",

            "res_model": "pbms.planning.category",

            "res_id": self.plan_id.id,

            "view_mode": "form",

            "target": "current",

        }

    def action_district_approve(self):

        res = False

        for plan in self.mapped("plan_id"):

            if plan.category == "manpower":

                res = plan.action_district_approve_workforce()

            else:

                res = plan.action_district_approve()

        return res

    def action_ho_approve(self):

        res = False

        for plan in self.mapped("plan_id"):

            if plan.category == "fixed_asset":

                res = plan.action_submit_to_committee()

            elif plan.category == "manpower":

                res = plan.action_ho_endorse_to_cpco()

            else:

                res = plan.action_ho_approve()

        return res

    def action_reset_to_draft(self):

        plans = self.mapped("plan_id")

        return plans.action_reset_to_draft()

    def action_bulk_approve(self):

        """Bulk (role-aware) approval for plans of selected lines."""

        return self.mapped("plan_id").action_bulk_approve()

    def action_bulk_ho_approve(self):

        """Bulk HO approval for plans of selected lines."""

        plans = self.mapped("plan_id")

        return plans.action_bulk_ho_approve()

    def action_bulk_district_approve(self):

        """Bulk District approval for plans of selected lines."""

        plans = self.mapped("plan_id")

        return plans.action_bulk_district_approve()

    def action_bulk_submit(self):

        """Bulk submit plans of selected lines."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plans found for selected lines."))

        return plans.action_submit()

    def action_bulk_reset_to_draft(self):

        """Bulk reset plans of selected lines to draft."""

        plans = self.mapped("plan_id")

        return plans.action_reset_to_draft()

    def action_bulk_open_plan(self):

        """Open the plan for the selected line(s)."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan found for selected lines."))

        if len(plans) == 1:

            return {

                "type": "ir.actions.act_window",

                "res_model": "pbms.planning.category",

                "res_id": plans.id,

                "view_mode": "form",

                "target": "current",

            }

        return {

            "type": "ir.actions.act_window",

            "name": _("Selected Plans"),

            "res_model": "pbms.planning.category",

            "domain": [("id", "in", plans.ids)],

            "view_mode": "list,form",

            "target": "current",

        }

    def action_bulk_wizard_return(self):

        """Open Return for Revision wizard for selected plans."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_return_revision_wizard")

        action = dict(action)

        action["context"] = {

            "active_ids": plans.ids,

            "active_id": plans[0].id,

            "active_model": "pbms.planning.category",

            "default_plan_id": plans[0].id,

        }

        return action

    def action_bulk_wizard_reject(self):

        """Open Reject Plan wizard for selected plans."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_reject_wizard")

        action = dict(action)

        action["context"] = {

            "active_ids": plans.ids,

            "active_id": plans[0].id,

            "active_model": "pbms.planning.category",

            "default_plan_id": plans[0].id,

        }

        return action

    def action_bulk_wizard_request_info(self):

        """Open Request Info wizard for selected plans."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_request_info_wizard")

        action = dict(action)

        action["context"] = {

            "active_ids": plans.ids,

            "active_id": plans[0].id,

            "active_model": "pbms.planning.category",

            "default_plan_id": plans[0].id,

        }

        return action

    def action_bulk_wizard_review_comment(self):

        """Open Review Comment wizard for selected plans."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_review_comment_wizard")

        action = dict(action)

        action["context"] = {

            "active_ids": plans.ids,

            "active_id": plans[0].id,

            "active_model": "pbms.planning.category",

            "default_plan_id": plans[0].id,

        }

        return action

    def action_bulk_open_import_wizard(self):

        """Open Import from Excel wizard for selected plan."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        return plans[0].action_open_import_wizard()

    def action_bulk_export_excel(self):

        """Export selected plan to Excel."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        return plans[0].action_export_excel()

    def action_bulk_consolidate_district(self):

        """Consolidate approved branch plans into District overview plan from selected lines."""

        plans = self.mapped("plan_id")

        if not plans:

            raise UserError(_("No plan associated with selected lines."))

        return plans.action_consolidate_district_overview()

    def action_bulk_cascade_ho(self):

        """Open HO-to-District Target Cascade wizard from selected list view lines."""

        plans = self.mapped("plan_id").filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")

        )

        if not plans:

            raise UserError(_("Target cascading is only applicable to Deposit Mobilization, Customer Base, FX Mobilization, and Digital Banking plans."))

        ho_plan = plans.filtered(lambda p: p.org_unit_type == "head_office" or p.is_head_office_unit)[:1]

        if not ho_plan:

            sample = plans[0]

            ho_unit = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")], limit=1)

            if ho_unit:

                ho_plan = self.env["pbms.planning.category"].search([

                    ("cycle_id", "=", sample.cycle_id.id),

                    ("category", "=", sample.category),

                    ("org_unit_id", "=", ho_unit.id),

                ], limit=1)

        if not ho_plan or ho_plan.state != "approved":

            raise UserError(_("The Bank-Wide Head Office consolidated plan must be Final Approved before cascading targets to Districts."))

        if ho_plan.is_targets_cascaded:

            return ho_plan.action_already_cascaded_notice()

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_target_cascade_ho_wizard")

        action = dict(action)

        action["context"] = {

            "default_plan_id": ho_plan.id,

            "default_cascade_level": "ho_to_district",

            "active_id": ho_plan.id,

            "active_ids": [ho_plan.id],

            "active_model": "pbms.planning.category",

        }

        return action

    def action_bulk_cascade_district(self):

        """Open District-to-Branch Target Cascade wizard from selected list view lines."""

        plans = self.mapped("plan_id").filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")

        )

        if not plans:

            raise UserError(_("Target cascading is only applicable to Deposit Mobilization, Customer Base, FX Mobilization, and Digital Banking plans."))

        dist_plan = plans.filtered(lambda p: p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit)[:1]

        if not dist_plan:

            sample = plans[0]

            parent_unit = sample.org_unit_id.parent_id

            if parent_unit:

                dist_plan = self.env["pbms.planning.category"].search([

                    ("cycle_id", "=", sample.cycle_id.id),

                    ("category", "=", sample.category),

                    ("org_unit_id", "=", parent_unit.id),

                ], limit=1)

        if not dist_plan or not dist_plan.has_cascaded_targets:

            raise UserError(_("This District plan has not received cascaded targets from Head Office yet."))

        if dist_plan.is_targets_cascaded:

            return dist_plan.action_already_cascaded_notice()

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_target_cascade_district_wizard")

        action = dict(action)

        action["context"] = {

            "default_plan_id": dist_plan.id,

            "default_cascade_level": "district_to_branch",

            "active_id": dist_plan.id,

            "active_ids": [dist_plan.id],

            "active_model": "pbms.planning.category",

        }

        return action

    def action_bulk_refresh_workforce(self):

        """Re-sync workforce from HR for selected plans."""

        plans = self.mapped("plan_id")

        return plans.action_refresh_existing_manpower()

    def action_bulk_delete(self):

        """Bulk delete selected plan category lines for SPPMD Administrator."""

        user = self.env.user

        if not (self.env.is_admin() or user._pbms_is_sppmd_admin()):

            raise AccessError(_("Only the SPPMD Administrator can delete plan lines in bulk."))

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            return False

        count = len(records)

        parent_plans = records.mapped("plan_id")

        records.unlink()

        if parent_plans:

            empty_plans = parent_plans.sudo().exists().filtered(lambda p: not p.line_ids)

            if empty_plans:

                try:

                    empty_plans.sudo().with_context(bypass_plan_lock=True).unlink()

                except Exception:

                    pass

                parent_plans -= empty_plans

            if parent_plans:

                try:

                    parent_plans.sudo()._compute_totals()

                except Exception:

                    pass

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Deleted"),

                "message": _("%s requirement line(s) deleted successfully.", count),

                "sticky": False,

                "type": "success",

                "next": {"type": "ir.actions.client", "tag": "reload"},

            },

        }

    @api.model

    def action_planning_categories_menu(self):

        """Dynamic dispatch for Planning Categories menu.

        Standard 3-level grouping: Planning Category > District > Branch / Operating Unit

        for all users.

        """

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_planning_category_lines")

        raw_ctx = action.get("context") or {}

        if isinstance(raw_ctx, str):

            from odoo.tools.safe_eval import safe_eval

            try:

                ctx = dict(safe_eval(raw_ctx))

            except Exception:

                ctx = {}

        else:

            ctx = dict(raw_ctx)

        ctx["search_default_group_by_line_type"] = 1

        ctx["search_default_group_district"] = 2

        ctx["search_default_group_by_branch"] = 3

        action["context"] = ctx

        return action

    @api.model

    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):

        has_id_filter = any(isinstance(leaf, (list, tuple)) and len(leaf) >= 2 and leaf[0] == "id" for leaf in (domain or []))

        has_plan_filter = any(isinstance(leaf, (list, tuple)) and len(leaf) >= 2 and leaf[0] == "plan_id" for leaf in (domain or []))

        if active_test and not has_id_filter:

            domain = Domain.AND([domain, [("plan_id.active", "=", True)]])

        if not self.env.su and not bypass_access and not has_id_filter and not has_plan_filter and not self.env.context.get("bypass_category_config_filter"):

            Config = self.env.get("pbms.planning.config")

            if Config is not None:

                target_cats = set()

                for leaf in (domain or []):

                    if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "line_type":

                        if leaf[1] == "=" and leaf[2]:

                            target_cats.add(leaf[2])

                        elif leaf[1] == "in" and isinstance(leaf[2], (list, tuple, set)):

                            target_cats.update(c for c in leaf[2] if c)

                for cat in target_cats:

                    if cat not in ("general_expense", "fixed_asset", "manpower"):

                        disabled_ou_ids = Config.sudo().get_disabled_unit_ids_for_category(cat)

                        if disabled_ou_ids:

                            domain = Domain.AND([

                                domain,

                                [

                                    "|", ("line_type", "!=", cat),

                                    "|", ("plan_state", "!=", "draft"),

                                    "|", ("org_unit_type", "in", ("district_office", "head_office", "regional_office")),

                                    ("org_unit_id", "not in", disabled_ou_ids),

                                ],

                            ])

        user = self.env.user

        if (

            not self.env.su

            and not bypass_access

            and not has_id_filter

            and not self.env.context.get("bypass_approver_branch_filter")

            and not user._pbms_is_sppmd_admin()

            and not self.env.is_admin()

        ):

            user_ou_ids = user._pbms_operating_unit_ids()
            is_ho_reviewer = user.has_group("bunna_pbms.group_pbms_ho_reviewer") or user._pbms_is_ho_reviewer()
            is_chief = user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief()
            if is_ho_reviewer or is_chief:
                role_domains = [[
                    "&",
                    ("org_unit_id", "in", user_ou_ids),
                    ("org_unit_type", "=", "head_office"),
                ]]
            else:
                role_domains = [[("org_unit_id", "in", user_ou_ids)]]

            if user.has_group("bunna_pbms.group_pbms_approver"):
                role_domains.append([
                    "&",
                    ("plan_state", "!=", "draft"),
                    "|", "|",
                    ("line_type", "not in", ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding")),
                    ("org_unit_type", "in", ("head_office", "district_office")),
                    ("plan_id.state", "in", ("district_endorsed", "ho_reviewed", "approved")),
                ])

            if is_ho_reviewer:
                ho_cats = [c for c in user._pbms_ho_review_categories() if c != "manpower"]
                role_domains.append([
                    "|",
                        "&",
                            ("line_type", "=", "manpower"),
                            ("plan_state", "in", ("ho_endorse", "cpco_endorse", "approved")),
                        "&",
                            ("line_type", "in", ho_cats),
                            "|", "|",
                            "&",
                                ("org_unit_type", "=", "head_office"),
                                ("plan_state", "in", ("submitted", "district_endorsed", "ho_reviewed", "committee_review", "board_ceo_approval", "approved", "info_requested", "returned")),
                            "&",
                                ("line_type", "in", ("deposit", "customer_base", "fx", "digital_banking")),
                                ("plan_state", "in", ("district_endorsed", "ho_reviewed", "approved")),
                            "&",
                                "&",
                                    ("line_type", "in", ("general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding")),
                                    ("org_unit_type", "not in", ("head_office",)),
                                ("plan_state", "in", ("submitted", "district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed", "approved")),
                ])

            if user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief():
                chief_wf_states = (
                    "chief_review", "people_solutions_review", "cpco_review", "committee_review",
                    "ceo_approval", "board_ceo_approval", "approved", "rejected", "info_requested",
                )
                chief_ho_history_states = (
                    "chief_review", "submitted", "district_endorsed", "district_approved", "ho_reviewed",
                    "committee_review", "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",
                    "people_solutions_review", "cpco_review", "approved", "rejected", "info_requested", "returned",
                )
                chief_scope_ou_ids = user._pbms_chief_scope_unit_ids()
                sub_user_ids = user._pbms_chief_subordinate_user_ids()
                direct_chief_criteria = [
                    "|",
                    ("plan_id.create_uid", "in", sub_user_ids),
                    "|",
                    ("plan_id.submitted_by", "in", sub_user_ids),
                    "|",
                    ("district_id", "in", chief_scope_ou_ids),
                    ("org_unit_id", "in", chief_scope_ou_ids),
                ]
                chief_line_domain = [
                    "|",
                    "&",
                    ("org_unit_id", "in", user_ou_ids),
                    ("org_unit_type", "=", "head_office"),
                    "|",
                    "&",
                    ("line_type", "=", "manpower"),
                    "&",
                    ("plan_state", "in", chief_wf_states),
                    *direct_chief_criteria,
                    "&",
                    ("org_unit_type", "=", "head_office"),
                    "&",
                    ("plan_state", "in", chief_ho_history_states),
                    *direct_chief_criteria,
                ]
                role_domains.append(chief_line_domain)

            if user.has_group("bunna_pbms.group_pbms_district_reviewer"):

                child_unit_ids = user._pbms_child_operating_unit_ids()

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                        ("plan_state", "!=", "draft"),

                        "|",

                        ("district_id", "in", user_ou_ids),

                        "|",

                        ("org_unit_id", "in", child_unit_ids),

                        ("org_unit_id.parent_unit", "in", user_ou_ids),

                ])

            if user.has_group("bunna_pbms.group_pbms_people_solutions"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("line_type", "=", "manpower"),

                    ("plan_state", "in", (

                        "people_solutions_review", "cpco_review", "committee_review",

                        "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",

                        "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_cpco"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("line_type", "=", "manpower"),

                    ("plan_state", "in", (

                        "cpco_review", "committee_review",

                        "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",

                        "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_people_operations"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("line_type", "=", "manpower"),

                    ("plan_state", "=", "approved"),

                ])

            if user.has_group("bunna_pbms.group_pbms_budget_hiring_committee"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("line_type", "in", ("manpower", "fixed_asset", "initiative_budget")),

                    ("plan_state", "in", (

                        "committee_review", "ceo_approval", "board_ceo_approval",

                        "ho_endorse", "cpco_endorse", "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_ceo") or user._pbms_is_ceo():

                role_domains.append([

                    "|",

                    ("plan_state", "in", ("ceo_approval", "board_ceo_approval")),

                    "|",

                    ("plan_id.ceo_approver_id", "=", user.id),

                    "&",

                    ("line_type", "=", "manpower"),

                    ("plan_state", "in", ("ho_endorse", "cpco_endorse", "approved", "rejected")),

                ])

            if _safe_table_exists(self.env, "pbms.privilege.assignment"):
                try:
                    Assignment = self.env["pbms.privilege.assignment"].sudo()
                    user_group_ids = user.all_group_ids.ids if hasattr(user, "all_group_ids") else getattr(user, "group_ids", getattr(user, "groups_id", self.env["res.groups"])).ids
                    u_domain = ["|", ("user_id", "=", user.id), ("group_id", "in", user_group_ids)]
                    if hasattr(user, "employee_id") and user.employee_id and user.employee_id.job_id:
                        u_domain = ["|", ("job_id", "=", user.employee_id.job_id.id)] + u_domain
                    dyn_assigns = Assignment.search([
                        ("active", "=", True),
                        ("grant_type", "=", "allow"),
                    ] + u_domain)
                    for da in dyn_assigns:
                        da_dom = []
                        if da.category_ids:
                            da_dom.append(("line_type", "in", da.category_ids.mapped("code")))
                        if da.org_unit_id:
                            da_dom.append(("org_unit_id", "=", da.org_unit_id.id))
                        elif da.org_level == "branch":
                            da_dom.append(("org_unit_type", "in", ("branch", "sub_branch")))
                        elif da.org_level == "district":
                            da_dom.append(("org_unit_type", "in", ("district_office", "regional_office")))
                        elif da.org_level in ("head_office", "ho"):
                            da_dom.append(("org_unit_type", "=", "head_office"))
                        if not da_dom:
                            role_domains.append([(1, "=", 1)])
                        elif len(da_dom) == 1:
                            role_domains.append(da_dom)
                        else:
                            role_domains.append(["&"] + da_dom)
                except Exception as e:
                    _logger.warning("Error evaluating dynamic privilege search domains: %s", e)

            if role_domains:

                domain = Domain.AND([domain, Domain.OR(role_domains)])

        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def init(self):

        super().init()

        cr = self.env.cr
        cr.execute("""SELECT to_regclass('pbms_planning_category') IS NOT NULL
                              AND to_regclass('pbms_plan_category_line') IS NOT NULL""")
        if not cr.fetchone()[0]:
            return  # fresh install: tables not created yet, nothing to clean up

        with cr.savepoint():
            cr.execute("""

            CREATE INDEX IF NOT EXISTS pbms_plan_line_plan_type_idx

            ON pbms_plan_category_line (plan_id, line_type);

            CREATE INDEX IF NOT EXISTS pbms_plan_line_source_type_idx

            ON pbms_plan_category_line (source_unit_id, line_type);

            CREATE INDEX IF NOT EXISTS pbms_plan_line_cycle_type_ou_idx

            ON pbms_plan_category_line (cycle_id, line_type, org_unit_id);

            CREATE INDEX IF NOT EXISTS pbms_plan_line_ou_type_state_idx
            ON pbms_plan_category_line (org_unit_id, line_type, plan_state);

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_plan_idx
            ON pbms_plan_category_line (plan_id, line_type, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_ou_cycle_idx
            ON pbms_plan_category_line (cycle_id, org_unit_id, line_type, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_dist_cycle_idx
            ON pbms_plan_category_line (cycle_id, district_id, line_type, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_plan_idx
            ON pbms_plan_category_line (plan_id, line_type, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_ou_cycle_idx
            ON pbms_plan_category_line (cycle_id, org_unit_id, line_type, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_line_grp_dist_cycle_idx
            ON pbms_plan_category_line (cycle_id, district_id, line_type, id) WHERE active = true;

            -- Ensure uncascaded District/Branch mobilization lines strictly have 0 approved values and 0 variance
            UPDATE pbms_plan_category_line l
            SET
                approved_annual_total = 0.0,
                approved_opening_balance = 0.0,
                approved_m01 = 0.0, approved_m02 = 0.0, approved_m03 = 0.0,
                approved_m04 = 0.0, approved_m05 = 0.0, approved_m06 = 0.0,
                approved_m07 = 0.0, approved_m08 = 0.0, approved_m09 = 0.0,
                approved_m10 = 0.0, approved_m11 = 0.0, approved_m12 = 0.0,
                variance_amount = 0.0,
                variance_percentage = 0.0
            FROM pbms_planning_category p
            WHERE l.plan_id = p.id
              AND (l.is_cascaded IS NOT TRUE)
              AND l.line_type IN ('deposit', 'customer_base', 'fx', 'digital_banking')
              AND (p.work_unit_type != 'head_office' OR p.work_unit_type IS NULL);

            UPDATE pbms_planning_category
            SET approved_annual_total = 0.0,
                variance_amount = 0.0,
                variance_percentage = 0.0,
                deposit_approved_total = 0.0,
                customer_base_approved_total = 0.0,
                fx_approved_total = 0.0,
                digital_banking_approved_total = 0.0
            WHERE (has_cascaded_targets IS NOT TRUE)
              AND category IN ('deposit', 'customer_base', 'fx', 'digital_banking')
              AND (work_unit_type != 'head_office' OR work_unit_type IS NULL)
              AND (org_unit_type != 'head_office' OR org_unit_type IS NULL);

            -- Clean up obsolete selection options for loan_flow_type

            UPDATE pbms_plan_category_line

            SET loan_flow_type = 'disbursement'

            WHERE loan_flow_type IN ('outstanding', 'provision');

            DELETE FROM ir_model_fields_selection

            WHERE field_id IN (

                SELECT id FROM ir_model_fields

                WHERE model = 'pbms.plan.category.line' AND name = 'loan_flow_type'

            )

            AND value IN ('outstanding', 'provision');

        """)

    @api.model

    def pbms_group_plan_info_batch(self, domains, field_names):

        """Ultra-fast batch loader for grouped-list plan headers.

        Resolves plan_id via direct indexed SQL, batches ORM reads on pbms.planning.category,

        and computes all permission flags in a single pass (<5ms).

        """

        if not domains:

            return []

        domain_plan_ids = []

        unique_plan_ids = set()

        for dom in domains:

            plan_id = None

            source_unit_id = None

            line_type = None

            cycle_id = None

            for leaf in (dom or []):

                if isinstance(leaf, (list, tuple)) and len(leaf) == 3:

                    field, op, val = leaf[0], leaf[1], leaf[2]

                    if op == "=":

                        if field == "plan_id":

                            plan_id = val

                        elif field in ("source_unit_id", "org_unit_id"):

                            source_unit_id = val

                        elif field in ("line_type", "category"):

                            line_type = val

                        elif field == "cycle_id":

                            cycle_id = val

            if not plan_id and source_unit_id and line_type:

                if cycle_id:

                    self.env.cr.execute("""

                        SELECT id FROM pbms_planning_category

                        WHERE org_unit_id = %s AND category = %s AND cycle_id = %s AND active = true

                        LIMIT 1

                    """, (source_unit_id, line_type, cycle_id))

                else:

                    self.env.cr.execute("""

                        SELECT id FROM pbms_planning_category

                        WHERE org_unit_id = %s AND category = %s AND active = true

                        ORDER BY id DESC LIMIT 1

                    """, (source_unit_id, line_type))

                row = self.env.cr.fetchone()

                if row:

                    plan_id = row[0]

                else:

                    self.env.cr.execute("""

                        SELECT plan_id FROM pbms_plan_category_line

                        WHERE source_unit_id = %s AND line_type = %s AND plan_id IS NOT NULL

                        LIMIT 1

                    """, (source_unit_id, line_type))

                    row = self.env.cr.fetchone()

                    if row:

                        plan_id = row[0]

            domain_plan_ids.append(plan_id)

            if plan_id:

                unique_plan_ids.add(plan_id)

        plan_map = {}

        if unique_plan_ids:

            plans = self.env["pbms.planning.category"].browse(list(unique_plan_ids))

            for p in plans:

                try:

                    plan_map[p.id] = {

                        "id": p.id,

                        "plan_id": (p.id, p.display_name),

                        "request_number": p.request_number,

                        "plan_state": p.state,

                        "plan_cat": p.category,

                        "plan_can_use_reviewer_actions": bool(p.can_use_reviewer_actions),

                        "plan_can_use_reviewer_wizards": bool(p.can_use_reviewer_wizards),

                        "plan_can_chief_review": bool(p.can_chief_review),

                        "plan_can_submit_plan": bool(p.can_submit_plan),

                        "plan_can_district_review": bool(p.can_district_review),

                        "plan_can_ho_review": bool(p.can_ho_review),

                        "plan_can_people_solutions_review": bool(p.can_people_solutions_review),

                        "plan_can_cpco_review": bool(p.can_cpco_review),

                        "plan_can_committee_review": bool(p.can_committee_review),

                        "plan_can_ceo_approve": bool(p.can_ceo_approve),

                        "plan_can_ho_endorse": bool(p.can_ho_endorse),

                        "plan_can_cpco_endorse": bool(p.can_cpco_endorse),

                        "plan_can_delete_plan": bool(p.can_delete_plan),

                        "plan_is_cycle_open": bool(p.is_cycle_open),

                        "plan_is_district_unit": bool(p.is_district_unit),

                        "plan_is_head_office_unit": bool(p.is_head_office_unit),

                        "plan_has_cascaded_targets": bool(p.has_cascaded_targets),

                        "plan_is_targets_cascaded": bool(p.is_targets_cascaded),

                        "org_unit_type": p.org_unit_id.work_unit_type,

                    }

                except Exception:

                    pass

        results = []

        for pid in domain_plan_ids:

            if pid and pid in plan_map:

                results.append([plan_map[pid]])

            else:

                results.append([])

        return results

class PbmsPlanningCategory(models.Model):


    _name = "pbms.planning.category"

    _description = "Plan & Budget Category"

    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]

    _rec_name = "display_name"

    _order = "category, org_unit_id, id"

    def init(self):

        super().init()

        self.env.cr.execute("""

            CREATE INDEX IF NOT EXISTS pbms_planning_category_lookup_idx

            ON pbms_planning_category (cycle_id, category, state);

            CREATE INDEX IF NOT EXISTS pbms_planning_category_ou_cycle_idx

            ON pbms_planning_category (org_unit_id, cycle_id);

            CREATE INDEX IF NOT EXISTS pbms_planning_category_dist_cycle_idx

            ON pbms_planning_category (district_id, cycle_id, category);

            CREATE INDEX IF NOT EXISTS pbms_planning_category_cycle_ou_cat_idx

            ON pbms_planning_category (cycle_id, org_unit_id, category);

            CREATE INDEX IF NOT EXISTS pbms_planning_category_state_cycle_idx

            ON pbms_planning_category (state, cycle_id);

            -- Compound indexes tailored for high-speed grouping and group expansion in list views
            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_cat_idx
            ON pbms_planning_category (cycle_id, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_ou_idx
            ON pbms_planning_category (cycle_id, org_unit_id, category, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_dist_idx
            ON pbms_planning_category (cycle_id, district_id, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_sol_idx
            ON pbms_planning_category (cycle_id, sol_id, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_outype_idx
            ON pbms_planning_category (cycle_id, org_unit_type, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_cycle_state_idx
            ON pbms_planning_category (cycle_id, state, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_cat_idx
            ON pbms_planning_category (category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_ou_idx
            ON pbms_planning_category (org_unit_id, category, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_dist_idx
            ON pbms_planning_category (district_id, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_sol_idx
            ON pbms_planning_category (sol_id, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_outype_idx
            ON pbms_planning_category (org_unit_type, category, org_unit_id, id) WHERE active = true;

            CREATE INDEX IF NOT EXISTS pbms_plan_cat_grp_act_state_idx
            ON pbms_planning_category (state, category, org_unit_id, id) WHERE active = true;

        """)

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

        related="org_unit_id.work_unit_type",

        store=True,

        readonly=True,

        index=True,

    )

    sol_id = fields.Integer(

        string="Sol ID",

        related="org_unit_id.sol_id",

        store=True,

        readonly=True,

        index=True,

        aggregator=None,

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

    enable_loan_disbursement_collection = fields.Boolean(compute="_compute_eligibility")

    enable_loan_outstanding = fields.Boolean(compute="_compute_eligibility")

    enable_credit_portfolio = fields.Boolean(compute="_compute_eligibility")

    enable_initiative_budget = fields.Boolean(compute="_compute_eligibility")

    # Measurement Types per category (monetary, integer, count)

    deposit_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Deposit Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    customer_base_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Customer Base Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    fx_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="FX Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    digital_banking_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Digital Banking Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    expense_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Expense Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    manpower_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Manpower Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    fixed_asset_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Fixed Asset Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    loan_disbursement_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Loan Disbursement Measurement",

        compute="_compute_measurement_types",

        store=True,

    )

    loan_outstanding_measurement_type = fields.Selection(

        [("monetary", "Amount"), ("integer", "Number"), ("count", "Count")],

        string="Loan Outstanding Measurement",

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

    is_loan_disbursement_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)

    is_loan_outstanding_monetary = fields.Boolean(compute="_compute_measurement_types", store=True)

    can_edit_content = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_delete_plan = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_submit_plan = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_district_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_ho_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_sppmd_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_use_reviewer_wizards = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_committee_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_hr_fulfill = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_ceo_approve = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_chief_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_cpco_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_people_solutions_review = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_ho_endorse = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_cpco_endorse = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_view_sourcing_fields = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_edit_sourcing_fields = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_add_lines = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_add_expense_lines = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_edit_expense = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_add_fixed_asset_lines = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_edit_fixed_asset = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_add_manpower_lines = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    can_edit_manpower = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    PBMS_PLAN_ACCESS_FLAG_FIELDS = (
        "can_edit_content", "can_delete_plan", "can_submit_plan",
        "can_district_review", "can_ho_review", "can_sppmd_review",
        "can_use_reviewer_wizards", "can_committee_review", "can_hr_fulfill",
        "can_ceo_approve", "can_chief_review", "can_cpco_review",
        "can_people_solutions_review", "can_ho_endorse", "can_cpco_endorse",
        "can_view_sourcing_fields", "can_edit_sourcing_fields", "can_add_lines",
        "can_add_expense_lines", "can_edit_expense", "can_add_fixed_asset_lines",
        "can_edit_fixed_asset", "can_add_manpower_lines", "can_edit_manpower",
    )

    @api.depends("state", "org_unit_id", "org_unit_id.parent_unit", "org_unit_type", "category", "cycle_id", "cycle_id.state")

    def _compute_access_flags(self):

        fields_to_protect = [self._fields[f] for f in self.PBMS_PLAN_ACCESS_FLAG_FIELDS if f in self._fields]

        with self._pbms_chief_memo_scope(), self.env.protecting(fields_to_protect, self):

            self._compute_access_flags_impl()

    def _compute_access_flags_impl(self):

        user = self.env.user

        is_admin = user._pbms_is_sppmd_admin() or user.has_group("base.group_system")

        is_bhc = user._pbms_is_budget_hiring_committee()

        is_ps = user._pbms_is_people_solutions()

        is_cpco = user._pbms_is_cpco()

        is_ceo = user._pbms_is_ceo()

        is_chief = user._pbms_is_respective_chief()

        is_ho_user = user._pbms_is_ho_reviewer()

        is_dist_user = user._pbms_is_district_reviewer()

        is_appr = user._pbms_is_sppmd_approver()

        is_people_ops = user._pbms_is_people_operations()

        child_ou_ids = set(user._pbms_child_operating_unit_ids()) if is_chief else set()

        is_sourcing_privileged_base = user._pbms_can_view_sourcing()

        # Pre-fetch sibling resource plans across the batch in a single indexed query to eliminate N*3 searches

        ou_ids = [ou.id for ou in self.sudo().mapped("org_unit_id") if ou]

        cycle_ids = [cy.id for cy in self.sudo().mapped("cycle_id") if cy]

        sibling_plans_map = {}

        if ou_ids and cycle_ids:

            sibling_plans = self.sudo().search([

                ("org_unit_id", "in", ou_ids),

                ("cycle_id", "in", cycle_ids),

                ("category", "in", ("general_expense", "fixed_asset", "manpower")),

                ("active", "=", True),

            ])

            for sp in sibling_plans:

                key = (sp.org_unit_id.id, sp.cycle_id.id, sp.category)

                if key not in sibling_plans_map:

                    sibling_plans_map[key] = sp

        for rec in self:

            rec.can_edit_content = rec._pbms_can_edit_plan_content()

            rec.can_delete_plan = rec._pbms_can_delete_plan()

            rec.can_submit_plan = rec._pbms_can_submit_plan()

            rec.can_district_review = rec._pbms_can_district_review_plan()

            rec.can_ho_review = rec._pbms_can_ho_review_plan()

            rec.can_sppmd_review = rec._pbms_can_sppmd_review_plan()

            rec.can_use_reviewer_wizards = rec._pbms_can_use_reviewer_wizards()

            rec.can_committee_review = (

                rec.category in ("manpower", "fixed_asset", "initiative_budget")

                and rec.state == "committee_review"

                and (is_bhc or is_admin)

            )

            rec.can_hr_fulfill = (

                rec.category == "manpower"

                and rec.state in ("people_solutions_review", "cpco_review", "hr_fulfillment")

                and (is_ps or is_cpco or rec._pbms_can_ho_review_plan() or is_admin)

            )

            rec.can_ceo_approve = (

                rec.category == "manpower"

                and rec.state == "ceo_approval"

                and (is_ceo or is_admin)

            )

            is_ho = rec._is_head_office_plan() or rec.org_unit_type == "head_office"

            is_dist = rec._is_district_plan() or rec.org_unit_type in ("district_office", "regional_office")

            if (

                rec.state == "chief_review"

                and rec.category in (

                    "manpower", "general_expense", "fixed_asset", "credit_portfolio",

                    "initiative_budget", "loan_disbursement_collection", "loan_outstanding",

                    "deposit", "customer_base", "fx", "digital_banking"

                )

            ):

                is_self = rec._is_plan_self_submitted(user)

                chief_user = rec.sudo()._get_plan_chief_user()

                is_branch_plan = rec.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (rec.org_unit_type not in ("head_office", "district_office"))

                is_chief_or_manager = False

                if chief_user:

                    if chief_user.id == user.id:

                        is_chief_or_manager = True

                    else:

                        chief_emp = chief_user.employee_id or (chief_user.employee_ids and chief_user.employee_ids[0])
                        curr_mgr = chief_emp.parent_id if chief_emp else None
                        visited_cm = {chief_emp.id} if chief_emp else set()
                        while curr_mgr and curr_mgr.id not in visited_cm:
                            visited_cm.add(curr_mgr.id)
                            if curr_mgr.user_id and curr_mgr.user_id.id == user.id:
                                is_chief_or_manager = True
                                break
                            curr_mgr = curr_mgr.parent_id

                if is_branch_plan and rec.category == "manpower":

                    is_designated_chief = is_chief_or_manager or is_ceo

                else:

                    is_designated_chief = is_chief_or_manager or not chief_user or is_ceo

                rec.can_chief_review = (

                    is_admin

                    or (

                        (is_chief or is_ceo or rec._is_plan_manager_user(user))

                        and is_designated_chief

                        and not is_self

                    )

                )

            else:

                rec.can_chief_review = False

            if rec.category == "manpower":

                is_manpower_applicable = True

            elif rec.category:

                is_manpower_applicable = False

            else:

                is_manpower_applicable = (

                    getattr(rec, "enable_manpower", False)

                    or bool(rec.line_ids.filtered(lambda l: l.line_type == "manpower"))

                )

            rec.can_cpco_review = (

                is_manpower_applicable

                and rec.state == "cpco_review"

                and (is_cpco or is_admin)

            )

            rec.can_people_solutions_review = (

                is_manpower_applicable

                and rec.state == "people_solutions_review"

                and (is_ps or is_admin)

            )

            rec.can_ho_endorse = (

                is_manpower_applicable

                and rec.state == "ho_endorse"

                and (is_ho or rec._pbms_can_ho_review_plan() or is_admin)

            )

            rec.can_cpco_endorse = (

                is_manpower_applicable

                and rec.state == "cpco_endorse"

                and (is_cpco or is_admin)

            )

            # Sourcing fields visibility:

            # Sourcing fulfillment is made by People Solutions Directorate.

            # Visible to: People Solutions Directorate, CPCO, Budget Hiring Committee, CEO, Admin, People Solutions Management Directorate,

            # and Head Office Functional Reviewer during endorsement into CPCO (ho_endorse, cpco_endorse, approved), NOT during request.

            is_sourcing_privileged = is_sourcing_privileged_base

            is_editable_state = (not rec.state) or (rec.state in PBMS_BRANCH_EDITABLE_STATES)

            is_ps_actor = (

                is_ps

                or is_admin

                or (rec.org_unit_id and (

                    (rec.org_unit_id.name or "").lower() in ("hr", "people solutions", "people solutions directorate", "human resources", "people & culture")

                    or ("people" in (rec.org_unit_id.name or "").lower() and "solution" in (rec.org_unit_id.name or "").lower())

                ))

            )

            is_sourcing_core = is_ps or is_cpco or is_bhc or is_ceo or is_people_ops or is_admin

            is_ho_reviewer_only = is_ho_user and not is_sourcing_core

            if is_manpower_applicable:

                if is_sourcing_core:

                    # People Solutions Directorate, CPCO, BHC, CEO, People Operations, and Admin can ALWAYS view sourcing fields

                    rec.can_view_sourcing_fields = True

                elif is_ho_reviewer_only:

                    rec.can_view_sourcing_fields = rec.state in ("ho_endorse", "cpco_endorse", "approved")

                else:

                    rec.can_view_sourcing_fields = False

            else:

                rec.can_view_sourcing_fields = False

            # Sourcing fields editability:

            # - Sourcing fulfillment is made by People Solutions Directorate in people_solutions_review, OR during draft/creation of its own plan!

            # - CPCO is able to View and Edit in cpco_review (and perform all other CPCO actions).

            # - Budget Hiring Committee in committee_review.

            # - CEO in ceo_approval.

            rec.can_edit_sourcing_fields = (

                is_manpower_applicable

                and (

                    (rec.state == "people_solutions_review" and (is_ps or is_admin))

                    or (is_editable_state and is_ps_actor)

                    or (rec.state in ("cpco_review", "hr_fulfillment") and (is_cpco or is_admin))

                    or (rec.state == "committee_review" and (is_bhc or is_admin))

                    or (rec.state == "ceo_approval" and (is_ceo or is_admin))

                )

            )

            # Administrator has permission to add lines in editable states

            if is_admin:

                rec.can_add_lines = rec.state in PBMS_BRANCH_EDITABLE_STATES

            # Planners managing their own operating unit plan in editable states (draft, returned, info_requested)

            elif rec.state in PBMS_BRANCH_EDITABLE_STATES and rec._is_own_operating_unit_plan():

                # Dedicated overview cards for mobilization aggregate from subordinates (no manual lines on consolidated records)

                if (rec.is_consolidated_district_plan or rec.is_consolidated_ho_plan):

                    rec.can_add_lines = False

                else:

                    rec.can_add_lines = bool(rec.cycle_id and rec.cycle_id.state == "open")

            # District Reviewer and Head Office Reviewer reviewing child unit plans CANNOT add lines (they can only edit lines created by branch)

            elif is_dist or is_ho:

                rec.can_add_lines = False

            elif rec.can_chief_review and rec.state == "chief_review":

                rec.can_add_lines = rec._is_own_operating_unit_plan()

            elif is_appr and not is_admin:

                rec.can_add_lines = False

            else:

                rec.can_add_lines = False

            # Category-specific flags for Expense, Fixed Asset, and Manpower

            is_own = rec._is_own_operating_unit_plan()

            cycle_open = bool(rec.cycle_id and rec.cycle_id.state == "open")

            default_addable = (is_own and cycle_open) or is_admin

            def _sibling_flags(sib):

                if not sib:

                    return default_addable, default_addable

                sib_user = sib.with_user(user).sudo(False)

                sib_state = sib.state

                sib_editable = sib_user._pbms_can_edit_plan_content()

                if is_admin:

                    sib_addable = sib_state in PBMS_BRANCH_EDITABLE_STATES

                elif sib_state in PBMS_BRANCH_EDITABLE_STATES and is_own:

                    sib_addable = cycle_open

                elif is_dist or is_ho:

                    sib_addable = False

                elif sib_state == "chief_review" and is_own and sib_editable:

                    sib_addable = True

                else:

                    sib_addable = False

                return sib_addable, sib_editable

            # 1. General Expense

            if rec.category == "general_expense":

                rec.can_add_expense_lines = rec.can_add_lines

                rec.can_edit_expense = rec.can_edit_content

            else:

                expense_plan = sibling_plans_map.get((rec.org_unit_id.id, rec.cycle_id.id, "general_expense")) if (rec.org_unit_id and rec.cycle_id) else False

                rec.can_add_expense_lines, rec.can_edit_expense = _sibling_flags(expense_plan)

            # 2. Fixed Asset

            if rec.category == "fixed_asset":

                rec.can_add_fixed_asset_lines = rec.can_add_lines

                rec.can_edit_fixed_asset = rec.can_edit_content

            else:

                fa_plan = sibling_plans_map.get((rec.org_unit_id.id, rec.cycle_id.id, "fixed_asset")) if (rec.org_unit_id and rec.cycle_id) else False

                rec.can_add_fixed_asset_lines, rec.can_edit_fixed_asset = _sibling_flags(fa_plan)

            # 3. Manpower

            if rec.category == "manpower":

                rec.can_add_manpower_lines = rec.can_add_lines

                rec.can_edit_manpower = rec.can_edit_content

            else:

                mp_plan = sibling_plans_map.get((rec.org_unit_id.id, rec.cycle_id.id, "manpower")) if (rec.org_unit_id and rec.cycle_id) else False

                rec.can_add_manpower_lines, rec.can_edit_manpower = _sibling_flags(mp_plan)

    @api.depends("org_unit_id", "org_unit_id.work_unit_type", "category", "org_unit_type", "is_planning_request")

    def _compute_eligibility(self):

        Config = self.env["pbms.planning.config"]

        CATEGORY_TOGGLE_MAP = [

            ("deposit", "enable_deposit"),

            ("customer_base", "enable_customer_base"),

            ("fx", "enable_fx"),

            ("digital_banking", "enable_digital_banking"),

            ("loan_disbursement_collection", "enable_loan_disbursement_collection"),

            ("loan_outstanding", "enable_loan_outstanding"),

            ("general_expense", "enable_expense"),

            ("manpower", "enable_manpower"),

            ("fixed_asset", "enable_fixed_asset"),

            ("credit_portfolio", "enable_credit_portfolio"),

            ("initiative_budget", "enable_initiative_budget"),

        ]

        for rec in self:

            is_req = rec.is_planning_request or bool(self.env.context.get("is_planning_request"))

            ou = rec.org_unit_id or self.env.user.default_operating_unit_id

            if is_req:

                # Unified Planning Request across any work unit (including People Solutions Directorate):

                # Display all planning categories enabled in Planning Configuration for this work unit in tabs!

                if ou:

                    for cat, toggle in CATEGORY_TOGGLE_MAP:

                        rec[toggle] = Config.is_category_enabled(cat, ou)

                else:

                    for _cat, toggle in CATEGORY_TOGGLE_MAP:

                        rec[toggle] = True

            elif rec.category:

                # Dedicated category card (e.g. Deposit Plan, Manpower Plan, Fixed Asset Plan, Expense Plan):

                # ALWAYS display its own category tab so records are visible on form view!

                for cat, toggle in CATEGORY_TOGGLE_MAP:

                    if cat == rec.category:

                        rec[toggle] = True

                    else:

                        rec[toggle] = False

            elif ou:

                for cat, toggle in CATEGORY_TOGGLE_MAP:

                    rec[toggle] = Config.is_category_enabled(cat, ou)

            else:

                for cat, toggle in CATEGORY_TOGGLE_MAP:

                    rec[toggle] = False

    @api.depends("org_unit_id", "org_unit_id.work_unit_type")

    def _compute_measurement_types(self):

        Config = self.env["pbms.planning.config"]

        for rec in self:

            rec.deposit_measurement_type = Config.get_measurement_type("deposit", org_unit=rec.org_unit_id)

            rec.customer_base_measurement_type = Config.get_measurement_type("customer_base", org_unit=rec.org_unit_id)

            rec.fx_measurement_type = Config.get_measurement_type("fx", org_unit=rec.org_unit_id)

            rec.digital_banking_measurement_type = Config.get_measurement_type("digital_banking", org_unit=rec.org_unit_id)

            rec.loan_disbursement_measurement_type = Config.get_measurement_type("loan_disbursement_collection", org_unit=rec.org_unit_id)

            rec.loan_outstanding_measurement_type = Config.get_measurement_type("loan_outstanding", org_unit=rec.org_unit_id)

            rec.expense_measurement_type = Config.get_measurement_type("general_expense", org_unit=rec.org_unit_id)

            rec.manpower_measurement_type = Config.get_measurement_type("manpower", org_unit=rec.org_unit_id)

            rec.fixed_asset_measurement_type = Config.get_measurement_type("fixed_asset", org_unit=rec.org_unit_id)

            rec.is_deposit_monetary = (rec.deposit_measurement_type == "monetary")

            rec.is_customer_base_monetary = (rec.customer_base_measurement_type == "monetary")

            rec.is_fx_monetary = (rec.fx_measurement_type == "monetary")

            rec.is_digital_banking_monetary = (rec.digital_banking_measurement_type == "monetary")

            rec.is_loan_disbursement_monetary = (rec.loan_disbursement_measurement_type == "monetary")

            rec.is_loan_outstanding_monetary = (rec.loan_outstanding_measurement_type == "monetary")

            rec.is_fixed_asset_monetary = (rec.fixed_asset_measurement_type == "monetary")

            if rec.category == "customer_base":

                rec.is_category_monetary = rec.is_customer_base_monetary

            elif rec.category == "digital_banking":

                rec.is_category_monetary = rec.is_digital_banking_monetary

            elif rec.category == "fx":

                rec.is_category_monetary = rec.is_fx_monetary

            elif rec.category == "loan_disbursement_collection":

                rec.is_category_monetary = rec.is_loan_disbursement_monetary

            elif rec.category == "loan_outstanding":

                rec.is_category_monetary = rec.is_loan_outstanding_monetary

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

            ("loan_disbursement_collection", "Loan Disbursement & Collection"),

            ("loan_outstanding", "Loan & Advances Outstanding"),

            ("general_expense", "General Expense"),

            ("manpower", "work Force"),

            ("fixed_asset", "Fixed Asset Requirement"),

            ("credit_portfolio", "Income Plan"),

            ("initiative_budget", "Initiative Budget"),

        ],

        string="Planning Category",

        compute="_compute_category",

        store=True,

        readonly=False,

        index=True,

        tracking=True,

        help="The planning category this line belongs to.",

    )

    @api.depends("line_ids.line_type", "org_unit_id")

    def _compute_category(self):

        Config = self.env.get("pbms.planning.config")

        MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding", "credit_portfolio", "initiative_budget"}

        RESOURCE_CATS = ["general_expense", "manpower", "fixed_asset"]

        for rec in self:

            unit_type = rec.org_unit_type or (rec.org_unit_id.work_unit_type if rec.org_unit_id else False)

            is_dist_or_ho = unit_type in ("district_office", "head_office")

            is_valid_category = False

            if rec.category and rec.org_unit_id and Config is not None:

                is_valid_category = Config.is_category_enabled(rec.category, rec.org_unit_id)

                # District overview cards are consolidation summaries

                if not is_valid_category and unit_type == "district_office" and rec.category in MOBILIZATION_CATS:

                    is_valid_category = True

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

                    new_cat = present_line_types[0]

                    rec_id = rec._origin.id if (hasattr(rec, "_origin") and rec._origin) else (rec.id if isinstance(rec.id, int) else False)

                    if rec.org_unit_id and rec.cycle_id and rec_id:

                        dups = self.sudo().search([

                            ("org_unit_id", "=", rec.org_unit_id.id),

                            ("cycle_id", "=", rec.cycle_id.id),

                            ("category", "=", new_cat),

                            ("active", "=", True),

                            ("id", "!=", rec_id),

                        ])

                        blocking_dup = False

                        for d in dups:

                            has_d_data = bool(d.line_ids) or any(getattr(d, m, 0.0) for m in MONTH_FIELDS) or ((getattr(d, "annual_total", 0.0) or 0.0) > 0.0)

                            if d.state == "draft" and not has_d_data:

                                d.sudo().with_context(bypass_plan_lock=True).write({"active": False})

                            else:

                                blocking_dup = d

                        if not blocking_dup:

                            rec.category = new_cat

                    else:

                        rec.category = new_cat

            elif not rec.category or not is_valid_category:

                if Config is not None and rec.org_unit_id:

                    rec.category = Config.get_default_category_for_unit(rec.org_unit_id)

                else:

                    rec.category = "general_expense" if is_dist_or_ho else "deposit"

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

    def _sync_workforce_document_to_siblings(self):

        """Ensure workforce_document, workforce_document_filename, and workforce_document_base64

        are synchronized across all active category cards for the same (org_unit_id, cycle_id)."""

        if self.env.context.get("in_workforce_doc_sync"):

            return

        CategoryPlan = self.env["pbms.planning.category"].sudo()

        for rec in self:

            if not rec.org_unit_id or not rec.cycle_id:

                continue

            doc_val = rec.workforce_document_base64 or rec.workforce_document

            doc_fname = rec.workforce_document_filename

            siblings = CategoryPlan.search([

                ("org_unit_id", "=", rec.org_unit_id.id),

                ("cycle_id", "=", rec.cycle_id.id),

                ("active", "=", True),

                ("id", "!=", rec.id),

            ])

            if not doc_val and siblings:

                donor = siblings.filtered(lambda s: s.workforce_document_base64 or s.workforce_document)[:1]

                if donor:

                    doc_val = donor.workforce_document_base64 or donor.workforce_document

                    doc_fname = donor.workforce_document_filename

            if not doc_val:

                continue

            if isinstance(doc_val, bytes):

                try:

                    doc_b64 = doc_val.decode("ascii")

                except Exception:

                    doc_b64 = base64.b64encode(doc_val).decode("ascii")

            else:

                doc_b64 = str(doc_val)

            sync_vals = {

                "workforce_document": doc_b64,

                "workforce_document_filename": doc_fname or "Workforce_Document",

                "workforce_document_base64": doc_b64,

            }

            if not rec.workforce_document or not rec.workforce_document_base64:

                rec.sudo().with_context(bypass_plan_lock=True, in_workforce_doc_sync=True, skip_sync_category_records=True).write(sync_vals)

            targets = siblings.filtered(lambda s: s.workforce_document_base64 != doc_b64 or not s.workforce_document)

            if targets:

                targets.with_context(bypass_plan_lock=True, in_workforce_doc_sync=True, skip_sync_category_records=True).write(sync_vals)

    def _realign_lines_to_matching_cards(self, plans=None):

        """Ensure each requirement line is attached directly to the specific plan card matching its category."""

        try:

            CategoryPlan = self.env["pbms.planning.category"].sudo()

            Line = self.env["pbms.plan.category.line"].sudo()

            target_plans = plans or (self if self else CategoryPlan.search([("active", "=", True)]))

            affected_plans = CategoryPlan

            for plan in target_plans:

                if (plan.workforce_document or plan.workforce_document_base64) and hasattr(plan, "_sync_workforce_document_to_siblings"):

                    plan._sync_workforce_document_to_siblings()

                if not plan.line_ids:

                    continue

                org_unit_id = plan.org_unit_id.id if plan.org_unit_id else False

                cycle_id = plan.cycle_id.id if plan.cycle_id else False

                if not org_unit_id or not cycle_id:

                    continue

                affected_plans |= plan

                present_types = list(dict.fromkeys(l.line_type for l in plan.line_ids if l.line_type))

                # If the plan has NO lines matching its own category, but has lines of another single category,

                # update this plan's category directly rather than creating a new card and leaving an empty one,

                # unless an active card with data already exists for that category.

                if plan.category not in present_types and len(present_types) == 1:

                    new_cat = present_types[0]

                    existing_dups = CategoryPlan.search([

                        ("org_unit_id", "=", org_unit_id),

                        ("cycle_id", "=", cycle_id),

                        ("category", "=", new_cat),

                        ("is_consolidated_district_plan", "=", bool(plan.is_consolidated_district_plan)),

                        ("is_consolidated_ho_plan", "=", bool(plan.is_consolidated_ho_plan)),

                        ("active", "=", True),

                        ("id", "!=", plan.id),

                    ])

                    blocking_dup = False

                    for d in existing_dups:

                        has_d_data = bool(d.line_ids) or any(getattr(d, m, 0.0) for m in PBMS_MONTH_FIELDS) or ((getattr(d, "annual_total", 0.0) or 0.0) > 0.0)

                        if d.state == "draft" and not has_d_data:

                            d.with_context(bypass_plan_lock=True).write({"active": False})

                        else:

                            blocking_dup = d

                    if not blocking_dup:

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
                # In unified planning request mode, all category lines (expense, fixed asset, workforce, etc.)
                # belong to the same multi-tab planning request card. Never detach lines from actual planning requests.
                if not plan.is_consolidated_district_plan and not plan.is_consolidated_ho_plan:
                    continue

                for line in plan.line_ids:

                    if not line.line_type or line.line_type == plan.category:

                        continue

                    target_card = CategoryPlan.with_context(active_test=False).search([

                        ("org_unit_id", "=", org_unit_id),

                        ("cycle_id", "=", cycle_id),

                        ("category", "=", line.line_type),

                        ("is_consolidated_district_plan", "=", bool(plan.is_consolidated_district_plan)),

                        ("is_consolidated_ho_plan", "=", bool(plan.is_consolidated_ho_plan)),

                    ], limit=1)

                    if target_card and not target_card.active:

                        target_card.with_context(bypass_plan_lock=True).write({"active": True})

                    if not target_card:

                        vals = {

                            "org_unit_id": org_unit_id,

                            "cycle_id": cycle_id,

                            "company_id": plan.company_id.id if plan.company_id else self.env.company.id,

                            "category": line.line_type,

                            "is_consolidated_district_plan": bool(plan.is_consolidated_district_plan),

                            "is_consolidated_ho_plan": bool(plan.is_consolidated_ho_plan),

                            "state": plan.state,

                            "submitted_by": plan.submitted_by.id if plan.submitted_by else self.env.uid,

                            "submitted_date": plan.submitted_date or fields.Datetime.now(),

                        }

                        if plan.workforce_document or plan.workforce_document_base64:

                            doc_b64 = plan.workforce_document_base64 or plan.workforce_document

                            vals.update({

                                "workforce_document": doc_b64,

                                "workforce_document_filename": plan.workforce_document_filename,

                                "workforce_document_base64": doc_b64,

                            })

                        target_card = CategoryPlan.with_context(skip_sync_category_records=True, bypass_plan_lock=True).create(vals)

                    elif (plan.workforce_document or plan.workforce_document_base64) and not target_card.workforce_document:

                        doc_b64 = plan.workforce_document_base64 or plan.workforce_document

                        target_card.with_context(bypass_plan_lock=True, in_workforce_doc_sync=True, skip_sync_category_records=True).write({

                            "workforce_document": doc_b64,

                            "workforce_document_filename": plan.workforce_document_filename,

                            "workforce_document_base64": doc_b64,

                        })

                    affected_plans |= target_card

                    line.with_context(bypass_plan_lock=True).write({"plan_id": target_card.id})

            # If re-aligning lines leaves behind an empty plan whose category is disabled in config, unlink or archive it

            target_plans.invalidate_recordset(["line_ids"])

            Config = self.env.get("pbms.planning.config")

            MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"}

            for p in target_plans:

                if (p.workforce_document or p.workforce_document_base64) and hasattr(p, "_sync_workforce_document_to_siblings"):

                    p._sync_workforce_document_to_siblings()

                unit_type = p.org_unit_type or (p.org_unit_id.work_unit_type if p.org_unit_id else False)

                is_dist_or_ho = unit_type in ("district_office", "head_office", "regional_office")

                if is_dist_or_ho and p.category in MOBILIZATION_CATS:

                    continue

                p_lines = p.line_ids

                has_header_data = any(getattr(p, m, 0.0) for m in PBMS_MONTH_FIELDS) or ((getattr(p, "annual_total", 0.0) or 0.0) > 0.0)

                if not p_lines and not has_header_data and p.org_unit_id and p.category:

                    if Config is not None and not Config.is_category_enabled(p.category, p.org_unit_id) and p.state in ("draft", "returned", "info_requested"):

                        try:

                            p.with_context(bypass_plan_lock=True).unlink()

                        except Exception:

                            p.with_context(bypass_plan_lock=True).write({"active": False})

            for p in affected_plans:

                if hasattr(p, "_sync_workforce_document_to_siblings"):

                    p._sync_workforce_document_to_siblings()

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

            key = (
                p.org_unit_id.id,
                p.cycle_id.id,
                p.category,
                bool(p.is_consolidated_district_plan),
                bool(p.is_consolidated_ho_plan),
            )

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

            rec_real_id = rec._origin.id if isinstance(rec._origin.id, int) else (rec.id if isinstance(rec.id, int) else False)

            if not rec_real_id or not rec.cycle_id or not rec.org_unit_id or not rec.category:

                continue

            # Ensure any lines of this category for this unit & cycle are attached to this card

            detached = Line.search([

                ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                ("plan_id.cycle_id", "=", rec.cycle_id.id),

                ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                ("line_type", "=", rec.category),

                ("plan_id", "!=", rec_real_id),

            ])

            if detached:

                detached = detached.filtered(lambda l: getattr(l.plan_id, "is_planning_request", False) or l.plan_id.category != rec.category)

                if detached:

                    detached.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": rec_real_id})

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

    customer_type_id = fields.Many2one(

        "pbms.customer.type", string="Customer Type", index=True, tracking=True,

        compute="_compute_category_specific_fields", store=True, readonly=False,

    )

    plan_category = fields.Selection(

        [("amount", "Amount"), ("customer", "Number of Customer")],

        string="Measurement", index=True,

        compute="_compute_category_specific_fields", store=True, readonly=False,

    )

    base_type = fields.Selection(

        [("new_acquisition", "New Customer Acquisition"),

         ("dormant_reduction", "Quality Customer"),

         ("both", "New Acquisition & Quality Customer")],

        string="Customer Category", index=True,

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

                cust_types = cb_lines.mapped("customer_type_id").filtered(lambda d: d.exists())

                rec.customer_type_id = cust_types[:1].id if cust_types else False

                dep_types = cb_lines.mapped("deposit_type_id").filtered(lambda d: d.exists())

                rec.deposit_type_id = dep_types[:1].id if dep_types else False

                rec.plan_category = "customer"

            else:

                rec.base_type = False

                rec.customer_type_id = False

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

        compute="_compute_fx_currency", store=True, readonly=True,

        help="Currency for Foreign Exchange (FX) Mobilization targets (fixed to USD).",

    )

    @api.depends("org_unit_id", "category")

    def _compute_fx_currency(self):

        usd = self.env.ref("base.USD", raise_if_not_found=False) or self.env["res.currency"].search([("name", "=", "USD")], limit=1)

        for rec in self:

            rec.fx_currency_id = usd.id if usd else False

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

            ("contract", "Contract")

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

    loan_disbursement_line_ids = fields.One2many(

        "pbms.plan.category.line", "plan_id",

        string="Loan Disbursement & Collection Lines",

        domain=[("line_type", "=", "loan_disbursement_collection")],

        context={"default_line_type": "loan_disbursement_collection", "default_loan_flow_type": "disbursement"},

    )

    loan_outstanding_line_ids = fields.One2many(

        "pbms.plan.category.line", "plan_id",

        string="Loan Outstanding Lines",

        domain=[("line_type", "=", "loan_outstanding")],

        context={"default_line_type": "loan_outstanding"},

    )

    credit_portfolio_line_ids = fields.One2many(

        "pbms.plan.category.line", "plan_id",

        string="Income Plan Lines",

        domain=[("line_type", "=", "credit_portfolio")],

        context={"default_line_type": "credit_portfolio"},

    )

    initiative_budget_line_ids = fields.One2many(

        "pbms.plan.category.line", "plan_id",

        string="Initiative Budget Lines",

        domain=[("line_type", "=", "initiative_budget")],

        context={"default_line_type": "initiative_budget"},

    )

    # Branch records for District Reviewer and Head Office Functional Reviewer

    branch_customer_base_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Customer Base Records",

    )

    branch_deposit_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Deposit Records",

    )

    branch_fx_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch FX Records",

    )

    branch_digital_banking_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Digital Banking Records",

    )

    branch_loan_disbursement_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Loan Disbursement Records",

    )

    branch_loan_outstanding_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Loan Outstanding Records",

    )

    branch_expense_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Expense Records",

    )

    branch_fixed_asset_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Fixed Asset Records",

    )

    branch_manpower_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Manpower Records",

    )

    branch_credit_portfolio_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Income Plan Records",

    )

    branch_initiative_budget_line_ids = fields.Many2many(

        "pbms.plan.category.line",

        compute="_compute_branch_category_lines",

        string="Branch Initiative Budget Records",

    )

    def _compute_branch_category_lines(self):

        for rec in self:

            if rec.org_unit_type == "district_office":

                dist_id = rec.org_unit_id.id

                domain = [

                    ("cycle_id", "=", rec.cycle_id.id),

                    ("district_id", "=", dist_id),

                    ("org_unit_type", "not in", ("district_office", "head_office")),

                ]

            elif rec.org_unit_type == "head_office":

                domain = [

                    ("cycle_id", "=", rec.cycle_id.id),

                    ("org_unit_type", "not in", ("district_office", "head_office")),

                ]

            else:

                domain = [("id", "=", False)]

            all_lines = self.env["pbms.plan.category.line"].search(domain) if domain[0][0] != "id" else self.env["pbms.plan.category.line"]

            rec.branch_customer_base_line_ids = all_lines.filtered(lambda l: l.line_type == "customer_base")

            rec.branch_deposit_line_ids = all_lines.filtered(lambda l: l.line_type == "deposit")

            rec.branch_fx_line_ids = all_lines.filtered(lambda l: l.line_type == "fx")

            rec.branch_digital_banking_line_ids = all_lines.filtered(lambda l: l.line_type == "digital_banking")

            rec.branch_loan_disbursement_line_ids = all_lines.filtered(lambda l: l.line_type == "loan_disbursement_collection")

            rec.branch_loan_outstanding_line_ids = all_lines.filtered(lambda l: l.line_type == "loan_outstanding")

            rec.branch_expense_line_ids = all_lines.filtered(lambda l: l.line_type == "general_expense")

            rec.branch_fixed_asset_line_ids = all_lines.filtered(lambda l: l.line_type == "fixed_asset")

            rec.branch_manpower_line_ids = all_lines.filtered(lambda l: l.line_type == "manpower")

            rec.branch_credit_portfolio_line_ids = all_lines.filtered(lambda l: l.line_type == "credit_portfolio")

            rec.branch_initiative_budget_line_ids = all_lines.filtered(lambda l: l.line_type == "initiative_budget")

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


    available_customer_type_ids = fields.Many2many(

        "pbms.customer.type", compute="_compute_available_dropdown_options", store=False,

    )

    used_customer_type_ids = fields.Many2many(

        "pbms.customer.type", compute="_compute_used_dropdown_options", store=False,

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

    available_loan_product_ids = fields.Many2many(

        "pbms.loan.product", compute="_compute_available_dropdown_options", store=False,

    )

    used_loan_product_ids = fields.Many2many(

        "pbms.loan.product", compute="_compute_used_dropdown_options", store=False,

    )

    available_job_ids = fields.Many2many(

        "hr.job", compute="_compute_available_dropdown_options", store=False,

    )

    @api.depends("org_unit_id", "org_unit_id.work_unit_type")

    def _compute_available_dropdown_options(self):

        Config = self.env["pbms.planning.config"]

        LineModel = self.env["pbms.plan.category.line"]

        defaults = {}

        def _default_all(model_name):

            if model_name not in defaults:

                defaults[model_name] = self.env[model_name].sudo().search([("active", "=", True)])

            return defaults[model_name]

        for plan in self:

            config = Config.get_config_for_unit(plan.org_unit_id) if plan.org_unit_id else False

            # Deposit / Customer Base

            if config and config.deposit_type_ids:

                plan.available_deposit_type_ids = config.deposit_type_ids

            else:

                plan.available_deposit_type_ids = _default_all("pbms.deposit.type")

            if config and config.customer_type_ids:

                plan.available_customer_type_ids = config.customer_type_ids

            else:

                plan.available_customer_type_ids = _default_all("pbms.customer.type")

            # Digital Banking

            if config and config.digital_channel_ids:

                plan.available_channel_ids = config.digital_channel_ids

            else:

                plan.available_channel_ids = _default_all("pbms.digital.channel")

            # FX

            if config and config.fx_source_type_ids:

                plan.available_fx_source_type_ids = config.fx_source_type_ids

            else:

                plan.available_fx_source_type_ids = _default_all("pbms.fx.source.type")

            # General Expense

            if config and config.expense_account_ids:

                plan.available_expense_account_ids = config.expense_account_ids

            else:

                plan.available_expense_account_ids = _default_all("pbms.expense.account")

            # Fixed Asset

            if config and config.fixed_asset_category_ids:

                plan.available_fa_category_ids = config.fixed_asset_category_ids

            else:

                plan.available_fa_category_ids = _default_all("pbms.fixed.asset.category")

            # Manpower Position Types

            if config and config.position_type_ids:

                plan.available_position_type_ids = config.position_type_ids

            else:

                plan.available_position_type_ids = _default_all("pbms.position.type")

            # Loan Outstanding
            if config and config.loan_product_ids:
                plan.available_loan_product_ids = config.loan_product_ids.filtered(
                    lambda p: p.applies_to in ("outstanding", "both") and p.active
                )
            else:
                plan.available_loan_product_ids = self.env["pbms.loan.product"].search([
                    ("active", "=", True), ("applies_to", "in", ("outstanding", "both"))
                ])

            # Active Job Positions for Operating Unit

            job_ids = LineModel._get_operating_unit_job_ids(plan.org_unit_id) if plan.org_unit_id else []

            if job_ids:

                plan.available_job_ids = self.env["hr.job"].browse(job_ids)

            else:

                plan.available_job_ids = _default_all("hr.job")

    @api.depends(

        "line_ids.deposit_type_id",

        "line_ids.channel_id",

        "line_ids.fx_source_type",

        "line_ids.expense_account_id",

        "line_ids.category_id",

        "deposit_line_ids.deposit_type_id",

        "customer_base_line_ids.deposit_type_id",

        "digital_banking_line_ids.channel_id",

        "fx_line_ids.fx_source_type",

        "expense_line_ids.expense_account_id",

        "fixed_asset_line_ids.category_id",

    )

    def _compute_used_dropdown_options(self):
        for plan in self:

            plan.used_deposit_type_ids = plan.deposit_line_ids.mapped("deposit_type_id")

            plan.used_channel_ids = plan.digital_banking_line_ids.mapped("channel_id")

            plan.used_fx_source_type_ids = plan.fx_line_ids.mapped("fx_source_type")

            plan.used_expense_account_ids = plan.expense_line_ids.mapped("expense_account_id")

            plan.used_fa_category_ids = plan.fixed_asset_line_ids.mapped("category_id")

            plan.used_loan_product_ids = plan.loan_outstanding_line_ids.mapped("loan_product_id")

            # Customer Base: Each product (Savings, Demand, Time, IFB) must be planned twice:

            # once for New Customer Acquisition and once for Quality Customer.

            # A customer type is only fully "used" (hidden from dropdown) when BOTH base types are present!

            all_cust_types = self.env["pbms.customer.type"].sudo().search([("active", "=", True)])

            used_ct_ids = []

            for ct in all_cust_types:

                matching = plan.customer_base_line_ids.filtered(

                    lambda l: (l.customer_type_id == ct or (l.deposit_type_id and l.deposit_type_id.code == ct.code)) and l.base_type

                )

                btypes = set(matching.mapped("base_type"))

                if {"new_acquisition", "dormant_reduction"}.issubset(btypes):

                    used_ct_ids.append(ct.id)

            plan.used_customer_type_ids = self.env["pbms.customer.type"].sudo().browse(used_ct_ids)

            plan.used_customer_base_deposit_type_ids = self.env["pbms.deposit.type"].search([("code", "in", [c.code for c in plan.used_customer_type_ids])])

    @api.onchange("deposit_line_ids", "customer_base_line_ids", "digital_banking_line_ids", "fx_line_ids", "loan_outstanding_line_ids", "expense_line_ids", "fixed_asset_line_ids")

    def _onchange_lines_update_used_options(self):

        self.used_loan_product_ids = self.loan_outstanding_line_ids.mapped("loan_product_id")

        self.used_deposit_type_ids = self.deposit_line_ids.mapped("deposit_type_id")

        self.used_customer_base_deposit_type_ids = self.customer_base_line_ids.mapped("deposit_type_id")

        self.used_channel_ids = self.digital_banking_line_ids.mapped("channel_id")

        self.used_fx_source_type_ids = self.fx_line_ids.mapped("fx_source_type")

        self.used_expense_account_ids = self.expense_line_ids.mapped("expense_account_id")

        self.used_fa_category_ids = self.fixed_asset_line_ids.mapped("category_id")

    def onchange(self, values: dict, field_names: list[str], fields_spec: dict):

        result = super().onchange(values, field_names, fields_spec)

        if not isinstance(result, dict):

            result = {}

        val_dict = result.setdefault("value", {})

        # Dynamically inject used IDs for planning lines into the onchange result.

        # Optimized to avoid expensive self.new(values) re-instantiations on every cell edit.

        category_line_map = [

            ("deposit_line_ids", "used_deposit_type_ids", "deposit_type_id"),

            ("customer_base_line_ids", "used_customer_base_deposit_type_ids", "deposit_type_id"),

            ("digital_banking_line_ids", "used_channel_ids", "channel_id"),

            ("fx_line_ids", "used_fx_source_type_ids", "fx_source_type"),

            ("expense_line_ids", "used_expense_account_ids", "expense_account_id"),

            ("fixed_asset_line_ids", "used_fa_category_ids", "category_id"),

        ]

        # Only process if at least one line field or used field is relevant to this onchange

        relevant_line_fields = {m[0] for m in category_line_map}

        relevant_used_fields = {m[1] for m in category_line_map}

        is_relevant = any(f in field_names for f in relevant_line_fields | relevant_used_fields) if field_names else True

        if is_relevant:

            for line_field, used_field, target_rel in category_line_map:

                if used_field in self._fields and (not fields_spec or used_field in fields_spec):

                    used_ids = set()

                    if self and line_field in self._fields:

                        for line in self[line_field]:

                            rel_val = line[target_rel]

                            if rel_val:

                                used_ids.add(rel_val.id if hasattr(rel_val, "id") else rel_val)

                    if line_field in values and isinstance(values[line_field], (list, tuple)):

                        for cmd in values[line_field]:

                            if isinstance(cmd, (list, tuple)) and len(cmd) >= 2:

                                if cmd[0] in (0, 1) and len(cmd) >= 3 and isinstance(cmd[2], dict):

                                    val = cmd[2].get(target_rel)

                                    if val:

                                        tid = val[0] if isinstance(val, (list, tuple)) else val

                                        if tid:

                                            used_ids.add(tid)

                                elif cmd[0] in (2, 3) and self and line_field in self._fields:

                                    line_id = cmd[1]

                                    del_line = self[line_field].filtered(lambda l: l.id == line_id)

                                    if del_line:

                                        for dl in del_line:

                                            rel_val = dl[target_rel]

                                            if rel_val:

                                                used_ids.discard(rel_val.id if hasattr(rel_val, "id") else rel_val)

                                elif cmd[0] == 5:

                                    used_ids.clear()

                    val_dict[used_field] = [(6, 0, sorted(list(used_ids)))]

        return result

    @api.onchange("category", "org_unit_id", "enable_manpower")

    def _onchange_category_and_unit(self):

        Config = self.env.get("pbms.planning.config")

        for rec in self:

            unit_type = rec.org_unit_type or (rec.org_unit_id.work_unit_type if rec.org_unit_id else False)

            is_dist = unit_type == "district_office"

            if rec.category and is_dist and rec.category in ("deposit", "customer_base", "fx", "digital_banking"):

                pass  # Preserve mobilization category for district overview cards

            elif rec.org_unit_id and Config is not None:

                if not rec.category or not Config.is_category_enabled(rec.category, rec.org_unit_id):

                    rec.category = Config.get_default_category_for_unit(rec.org_unit_id)

            is_manpower = rec.category == "manpower" or rec.enable_manpower

            unit_changed = bool(rec._origin.org_unit_id and rec.org_unit_id != rec._origin.org_unit_id)

            if is_manpower and rec.org_unit_id and (not rec.existing_manpower_summary_ids or unit_changed):

                rec._sync_existing_manpower_lines()

    # Category summaries per tab (Plan Overview & Quarterly Rollup)

    has_cascaded_targets = fields.Boolean(

        compute="_compute_has_cascaded_targets", store=True, string="Has Cascaded Targets",

    )

    is_targets_cascaded = fields.Boolean(

        string="Targets Cascaded",

        compute="_compute_is_targets_cascaded",

        inverse="_inverse_is_targets_cascaded",

        store=True,

        readonly=False,

        copy=False,

        tracking=True,

        help="Indicates whether targets from this plan have already been cascaded to subordinate units to prevent double cascade.",

    )

    deposit_line_count = fields.Integer(compute="_compute_category_summaries", store=True)

    deposit_annual_total = fields.Float(compute="_compute_category_summaries", store=True)

    deposit_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Deposit Target")

    deposit_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Deposit Plan")

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

    fx_approved_total = fields.Monetary(compute="_compute_category_summaries", store=True, string="Approved FX Plan", currency_field="fx_currency_id")

    fx_q1_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")

    fx_q2_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")

    fx_q3_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")

    fx_q4_total = fields.Monetary(compute="_compute_category_summaries", store=True, currency_field="fx_currency_id")

    digital_banking_line_count = fields.Integer(compute="_compute_category_summaries", store=True)

    digital_banking_annual_total = fields.Float(compute="_compute_category_summaries", store=True)

    digital_banking_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Digital Target")

    digital_banking_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Digital Plan")

    digital_banking_q1_total = fields.Float(compute="_compute_category_summaries", store=True)

    digital_banking_q2_total = fields.Float(compute="_compute_category_summaries", store=True)

    digital_banking_q3_total = fields.Float(compute="_compute_category_summaries", store=True)

    digital_banking_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_disbursement_line_count = fields.Integer(compute="_compute_category_summaries", store=True)

    loan_disbursement_annual_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_disbursement_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Loan Disbursement Target")

    loan_disbursement_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Loan Disbursement Plan")

    loan_disbursement_q1_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_disbursement_q2_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_disbursement_q3_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_disbursement_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_outstanding_line_count = fields.Integer(compute="_compute_category_summaries", store=True)

    loan_outstanding_annual_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_outstanding_proposed_total = fields.Float(compute="_compute_category_summaries", store=True, string="Proposed Loan Outstanding Target")

    loan_outstanding_approved_total = fields.Float(compute="_compute_category_summaries", store=True, string="Approved Loan Outstanding Plan")

    loan_outstanding_q1_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_outstanding_q2_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_outstanding_q3_total = fields.Float(compute="_compute_category_summaries", store=True)

    loan_outstanding_q4_total = fields.Float(compute="_compute_category_summaries", store=True)

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

    proposed_annual_total = fields.Float(

        string="Proposed Plan",

        compute="_compute_plan_proposed_approved_totals",

        store=True,

    )

    approved_annual_total = fields.Float(

        string="Approved Plan",

        compute="_compute_plan_proposed_approved_totals",

        store=True,

    )

    variance_amount = fields.Float(

        string="Variance (+/-)",

        compute="_compute_plan_proposed_approved_totals",

        store=True,

    )

    variance_percentage = fields.Float(

        string="Var %",

        compute="_compute_plan_proposed_approved_totals",

        store=True,

        digits=(16, 2),

    )

    @api.depends(
        "category", "annual_total",
        "has_cascaded_targets", "is_targets_cascaded", "state", "org_unit_type",
        "line_ids.is_cascaded", "line_ids.proposed_plan",
        "deposit_proposed_total", "deposit_approved_total",
        "customer_base_proposed_total", "customer_base_approved_total",
        "fx_proposed_total", "fx_approved_total",
        "digital_banking_proposed_total", "digital_banking_approved_total",
        "expense_proposed_total", "expense_approved_total",
        "manpower_total_headcount", "manpower_approved_headcount",
        "fixed_asset_total_quantity", "fixed_asset_approved_total",
        "loan_disbursement_proposed_total", "loan_disbursement_approved_total",
        "loan_outstanding_proposed_total", "loan_outstanding_approved_total",
    )
    def _compute_plan_proposed_approved_totals(self):
        for rec in self:
            cat = rec.category
            is_consolidable = cat in ("deposit", "customer_base", "fx", "digital_banking")
            is_ho = bool(rec.is_head_office_unit or rec._is_head_office_plan() or rec.org_unit_type == "head_office")
            is_req = bool(rec.is_planning_request or rec.env.context.get("is_planning_request"))

            is_plan_draft = rec.state in ("draft", "returned", "info_requested")
            if cat == "deposit":
                rec.proposed_annual_total = rec.deposit_proposed_total if is_req else (rec.deposit_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = 0.0 if (is_consolidable and not is_ho and not rec.has_cascaded_targets) else (rec.deposit_approved_total or 0.0)
            elif cat == "customer_base":
                rec.proposed_annual_total = rec.customer_base_proposed_total if is_req else (rec.customer_base_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = 0.0 if (is_consolidable and not is_ho and not rec.has_cascaded_targets) else (rec.customer_base_approved_total or 0.0)
            elif cat == "fx":
                rec.proposed_annual_total = rec.fx_proposed_total if is_req else (rec.fx_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = 0.0 if (is_consolidable and not is_ho and not rec.has_cascaded_targets) else (rec.fx_approved_total or 0.0)
            elif cat == "digital_banking":
                rec.proposed_annual_total = rec.digital_banking_proposed_total if is_req else (rec.digital_banking_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = 0.0 if (is_consolidable and not is_ho and not rec.has_cascaded_targets) else (rec.digital_banking_approved_total or 0.0)
            elif cat == "loan_disbursement_collection":
                rec.proposed_annual_total = rec.loan_disbursement_proposed_total if is_req else (rec.loan_disbursement_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = rec.loan_disbursement_approved_total or 0.0
            elif cat == "loan_outstanding":
                rec.proposed_annual_total = rec.loan_outstanding_proposed_total if is_req else (rec.loan_outstanding_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = rec.loan_outstanding_approved_total or 0.0
            elif cat == "general_expense":
                rec.proposed_annual_total = rec.expense_proposed_total if is_req else (rec.expense_proposed_total or (rec.annual_total if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = rec.expense_approved_total or 0.0
            elif cat == "manpower":
                mp_lines = rec.line_ids.filtered(lambda l: l.line_type == "manpower")
                mp_prop = sum(mp_lines.mapped("proposed_plan"))
                rec.proposed_annual_total = float(mp_prop or (rec.manpower_total_headcount if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = float(rec.manpower_approved_headcount or 0.0)
            elif cat == "fixed_asset":
                fa_lines = rec.line_ids.filtered(lambda l: l.line_type == "fixed_asset")
                fa_prop = sum(fa_lines.mapped("proposed_plan"))
                rec.proposed_annual_total = float(fa_prop or (rec.fixed_asset_total_quantity if is_plan_draft else rec.proposed_annual_total or 0.0))
                rec.approved_annual_total = float(rec.fixed_asset_approved_total or 0.0)
            else:
                rec.proposed_annual_total = rec.annual_total or 0.0
                rec.approved_annual_total = 0.0

            active_tot = rec.annual_total or 0.0
            appr = rec.approved_annual_total or 0.0
            prop = rec.proposed_annual_total or 0.0

            if is_consolidable and not is_ho and not rec.has_cascaded_targets:
                rec.approved_annual_total = 0.0
                rec.variance_amount = 0.0
                rec.variance_percentage = 0.0
                continue

            if appr != 0.0:
                base = prop if prop != 0.0 else active_tot
                diff = appr - base
            elif not is_consolidable and prop != 0.0 and active_tot != 0.0 and abs(active_tot - prop) > 1e-4:
                diff = active_tot - prop
                base = prop
            else:
                diff = 0.0
                base = 0.0

            rec.variance_amount = diff
            if base != 0.0:
                rec.variance_percentage = round((diff / abs(base)) * 100.0, 2)
            else:
                rec.variance_percentage = 0.0

    # Fixed Asset total - using fa_annual_total_cost instead of estimated_total_price

    total_estimated_amount = fields.Float(

        compute="_compute_total_estimated_amount",

        store=True,

        index=True,

        currency_field="currency_id",

        help="Fixed Asset estimated total across request lines.",

    )

    total_manpower_cost = fields.Float(

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

    total_fixed_asset_cost = fields.Float(

        compute="_compute_total_fixed_asset_cost",

        store=True,

        currency_field="currency_id",

        help="Total fixed asset cost across all lines.",

    )

    # ── Workforce Attached Document ──────────────────────────────────────────

    workforce_document = fields.Binary(

        string="Attach Document",

        attachment=False,

        copy=False,

        help="Upload supporting workforce document (converted to Base64 and stored directly in database).",

    )

    workforce_document_filename = fields.Char(

        string="Document Filename",

        copy=False,

    )

    workforce_document_base64 = fields.Text(

        string="Document Base64",

        copy=False,

        help="Base64 encoded string of the attached workforce document stored directly in database.",

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

    fa_q1 = fields.Integer(

        string="FA Q1",

        compute="_compute_fa_quarter_quantities",

        store=True,

        help="Total Q1 fixed asset quantity",

    )

    fa_q2 = fields.Integer(

        string="FA Q2",

        compute="_compute_fa_quarter_quantities",

        store=True,

        help="Total Q2 fixed asset quantity",

    )

    fa_q3 = fields.Integer(

        string="FA Q3 ",

        compute="_compute_fa_quarter_quantities",

        store=True,

        help="Total Q3 fixed asset quantity",

    )

    fa_q4 = fields.Integer(

        string="FA Q4 ",

        compute="_compute_fa_quarter_quantities",

        store=True,

        help="Total Q4 fixed asset quantity",

    )

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

    # Universal quarterly rollup (same 4 fields for EVERY planning category).

    # Each record shows the Q1-Q4 totals of its OWN category only.

    rollup_q1_total = fields.Float(

        string="Rollup QI Total", compute="_compute_rollup_quarter_totals", store=True,

        help="Q1 total of this plan's own planning category",

    )

    rollup_q2_total = fields.Float(

        string="Rollup QII Total", compute="_compute_rollup_quarter_totals", store=True,

        help="Q2 total of this plan's own planning category",

    )

    rollup_q3_total = fields.Float(

        string="Rollup QIII Total", compute="_compute_rollup_quarter_totals", store=True,

        help="Q3 total of this plan's own planning category",

    )

    rollup_q4_total = fields.Float(

        string="Rollup QIV Total", compute="_compute_rollup_quarter_totals", store=True,

        help="Q4 total of this plan's own planning category",

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

        "loan_disbursement_collection": "loan_disbursement_line_ids",

        "loan_outstanding": "loan_outstanding_line_ids",

        "general_expense": "expense_line_ids",

        "manpower": "manpower_line_ids",

        "fixed_asset": "fixed_asset_line_ids",

        "credit_portfolio": "credit_portfolio_line_ids",

        "initiative_budget": "initiative_budget_line_ids",

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

            "is_targets_cascaded",

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

            ('q1', 'QI'),

            ('q2', 'QII'),

            ('q3', 'QIII'),

            ('q4', 'QIV'),

        ],

        string="Display Quarter",

        default='all',

    )

    quarter1_total = fields.Float(

        compute='_compute_totals',

        string="QI Total",

        store=True

    )

    quarter2_total = fields.Float(

        compute='_compute_totals',

        string="QII Total",

        store=True

    )

    quarter3_total = fields.Float(

        compute='_compute_totals',

        string="QIII Total",

        store=True

    )

    quarter4_total = fields.Float(

        compute='_compute_totals',

        string="QIV Total",

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

        'line_ids.hc_m01', 'line_ids.hc_m02', 'line_ids.hc_m03', 'line_ids.hc_m04',

        'line_ids.hc_m05', 'line_ids.hc_m06', 'line_ids.hc_m07', 'line_ids.hc_m08',

        'line_ids.hc_m09', 'line_ids.hc_m10', 'line_ids.hc_m11', 'line_ids.hc_m12',

        'deposit_line_ids.annual_total', 'deposit_line_ids.quarter1_total', 'deposit_line_ids.quarter2_total', 'deposit_line_ids.quarter3_total', 'deposit_line_ids.quarter4_total',

        'deposit_line_ids.m01', 'deposit_line_ids.m02', 'deposit_line_ids.m03', 'deposit_line_ids.m04', 'deposit_line_ids.m05', 'deposit_line_ids.m06', 'deposit_line_ids.m07', 'deposit_line_ids.m08', 'deposit_line_ids.m09', 'deposit_line_ids.m10', 'deposit_line_ids.m11', 'deposit_line_ids.m12',

        'customer_base_line_ids.annual_total', 'customer_base_line_ids.quarter1_total', 'customer_base_line_ids.quarter2_total', 'customer_base_line_ids.quarter3_total', 'customer_base_line_ids.quarter4_total',

        'customer_base_line_ids.m01', 'customer_base_line_ids.m02', 'customer_base_line_ids.m03', 'customer_base_line_ids.m04', 'customer_base_line_ids.m05', 'customer_base_line_ids.m06', 'customer_base_line_ids.m07', 'customer_base_line_ids.m08', 'customer_base_line_ids.m09', 'customer_base_line_ids.m10', 'customer_base_line_ids.m11', 'customer_base_line_ids.m12',

        'fx_line_ids.annual_total', 'fx_line_ids.quarter1_total', 'fx_line_ids.quarter2_total', 'fx_line_ids.quarter3_total', 'fx_line_ids.quarter4_total',

        'digital_banking_line_ids.annual_total', 'digital_banking_line_ids.quarter1_total', 'digital_banking_line_ids.quarter2_total', 'digital_banking_line_ids.quarter3_total', 'digital_banking_line_ids.quarter4_total',

        'expense_line_ids.annual_total', 'expense_line_ids.quarter1_total', 'expense_line_ids.quarter2_total', 'expense_line_ids.quarter3_total', 'expense_line_ids.quarter4_total',

        'loan_disbursement_line_ids.annual_total', 'loan_disbursement_line_ids.quarter1_total', 'loan_disbursement_line_ids.quarter2_total', 'loan_disbursement_line_ids.quarter3_total', 'loan_disbursement_line_ids.quarter4_total',

        'loan_outstanding_line_ids.annual_total', 'loan_outstanding_line_ids.quarter1_total', 'loan_outstanding_line_ids.quarter2_total', 'loan_outstanding_line_ids.quarter3_total', 'loan_outstanding_line_ids.quarter4_total',

        'credit_portfolio_line_ids.annual_total', 'credit_portfolio_line_ids.quarter1_total', 'credit_portfolio_line_ids.quarter2_total', 'credit_portfolio_line_ids.quarter3_total', 'credit_portfolio_line_ids.quarter4_total',

        'credit_portfolio_line_ids.m01', 'credit_portfolio_line_ids.m02', 'credit_portfolio_line_ids.m03', 'credit_portfolio_line_ids.m04', 'credit_portfolio_line_ids.m05', 'credit_portfolio_line_ids.m06', 'credit_portfolio_line_ids.m07', 'credit_portfolio_line_ids.m08', 'credit_portfolio_line_ids.m09', 'credit_portfolio_line_ids.m10', 'credit_portfolio_line_ids.m11', 'credit_portfolio_line_ids.m12',

        'initiative_budget_line_ids.annual_total', 'initiative_budget_line_ids.quarter1_total', 'initiative_budget_line_ids.quarter2_total', 'initiative_budget_line_ids.quarter3_total', 'initiative_budget_line_ids.quarter4_total',

        'initiative_budget_line_ids.initiative_cost',

        'manpower_line_ids.annual_total', 'manpower_line_ids.quantity',

        'manpower_line_ids.quarter1_total', 'manpower_line_ids.quarter2_total',

        'manpower_line_ids.quarter3_total', 'manpower_line_ids.quarter4_total',

        'manpower_line_ids.m01', 'manpower_line_ids.m02', 'manpower_line_ids.m03',

        'manpower_line_ids.m04', 'manpower_line_ids.m05', 'manpower_line_ids.m06',

        'manpower_line_ids.m07', 'manpower_line_ids.m08', 'manpower_line_ids.m09',

        'manpower_line_ids.m10', 'manpower_line_ids.m11', 'manpower_line_ids.m12',

        'manpower_line_ids.annual_total_cost',

        'm01', 'm02', 'm03', 'm04', 'm05', 'm06',

        'm07', 'm08', 'm09', 'm10', 'm11', 'm12'

    )

    def _compute_totals(self):

        for rec in self.with_context(in_distribute_plan_sync=True):

            target_cat = rec.category or (rec.line_ids[0].line_type if rec.line_ids else "deposit")

            cat_lines = rec.line_ids.filtered(lambda l: l.line_type == target_cat) if rec.line_ids else rec.env["pbms.plan.category.line"]

            if target_cat == "manpower" and rec.manpower_line_ids:

                cat_lines = rec.manpower_line_ids

            if target_cat == "manpower":

                rec.annual_total = sum(cat_lines.mapped("annual_total")) or sum(cat_lines.mapped("quantity")) or 0.0

                rec.quarter1_total = sum(cat_lines.mapped("quarter1_total")) or 0.0

                rec.quarter2_total = sum(cat_lines.mapped("quarter2_total")) or 0.0

                rec.quarter3_total = sum(cat_lines.mapped("quarter3_total")) or 0.0

                rec.quarter4_total = sum(cat_lines.mapped("quarter4_total")) or 0.0

                for m in MONTH_FIELDS:

                    setattr(rec, m, sum(

                        (getattr(line, m) or getattr(line, f"hc_{m}") or 0.0)

                        for line in cat_lines

                    ))

            elif target_cat == "fixed_asset":

                rec.annual_total = sum(cat_lines.mapped("quantity")) or 0.0

                rec.quarter1_total = sum(cat_lines.mapped("fa_q1")) or 0.0

                rec.quarter2_total = sum(cat_lines.mapped("fa_q2")) or 0.0

                rec.quarter3_total = sum(cat_lines.mapped("fa_q3")) or 0.0

                rec.quarter4_total = sum(cat_lines.mapped("fa_q4")) or 0.0

                rec.fa_q1 = int(sum(cat_lines.mapped("fa_q1")) or 0)

                rec.fa_q2 = int(sum(cat_lines.mapped("fa_q2")) or 0)

                rec.fa_q3 = int(sum(cat_lines.mapped("fa_q3")) or 0)

                rec.fa_q4 = int(sum(cat_lines.mapped("fa_q4")) or 0)

            elif cat_lines:

                rec.annual_total = sum(cat_lines.mapped("annual_total"))

                rec.quarter1_total = sum(cat_lines.mapped("quarter1_total"))

                rec.quarter2_total = sum(cat_lines.mapped("quarter2_total"))

                rec.quarter3_total = sum(cat_lines.mapped("quarter3_total"))

                rec.quarter4_total = sum(cat_lines.mapped("quarter4_total"))

                for m in MONTH_FIELDS:

                    setattr(rec, m, sum(cat_lines.mapped(m)))

            else:
                is_req = bool(rec.is_planning_request or rec.env.context.get("is_planning_request"))
                if is_req:
                    rec.quarter1_total = 0.0
                    rec.quarter2_total = 0.0
                    rec.quarter3_total = 0.0
                    rec.quarter4_total = 0.0
                    rec.annual_total = 0.0
                    for m in MONTH_FIELDS:
                        setattr(rec, m, 0.0)
                else:
                    values = {f: (getattr(rec, f) or 0.0) for f in MONTH_FIELDS}
                    rec.quarter1_total = sum(values[f] for f in QUARTERS["q1"])
                    rec.quarter2_total = sum(values[f] for f in QUARTERS["q2"])
                    rec.quarter3_total = sum(values[f] for f in QUARTERS["q3"])
                    rec.quarter4_total = sum(values[f] for f in QUARTERS["q4"])
                    rec.annual_total = sum(values.values())

    def _distribute_plan_annual_total_proportionally(self):

        """When annual_total on plan is edited, distribute proportionally to lines or months."""

        if self.env.context.get("in_distribute_plan_sync"):

            return

        for rec in self.with_context(in_distribute_plan_sync=True):

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

                q1 = sum(cat_lines.mapped("quarter1_total"))

                q2 = sum(cat_lines.mapped("quarter2_total"))

                q3 = sum(cat_lines.mapped("quarter3_total"))

                q4 = sum(cat_lines.mapped("quarter4_total"))

                rec.quarter1_total = q1

                rec.quarter2_total = q2

                rec.quarter3_total = q3

                rec.quarter4_total = q4

                for m in MONTH_FIELDS:

                    setattr(rec, m, sum(cat_lines.mapped(m)))

                if rec.id:

                    plan_vals = {

                        "quarter1_total": q1,

                        "quarter2_total": q2,

                        "quarter3_total": q3,

                        "quarter4_total": q4,

                    }

                    for m in MONTH_FIELDS:

                        plan_vals[m] = sum(cat_lines.mapped(m))

                    rec.with_context(in_distribute_plan_sync=True, skip_sync_lines=True, bypass_plan_lock=True).write(plan_vals)

            else:

                old_months = [(getattr(rec, m) or 0.0) for m in MONTH_FIELDS]

                old_sum = sum(old_months)

                plan_vals = {}

                if abs(old_sum) > 1e-6:

                    for i, m in enumerate(MONTH_FIELDS):

                        val = round(new_total * (old_months[i] / old_sum), 2)

                        setattr(rec, m, val)

                        plan_vals[m] = val

                else:

                    for m in MONTH_FIELDS:

                        val = round(new_total / 12.0, 2)

                        setattr(rec, m, val)

                        plan_vals[m] = val

                q1 = sum(getattr(rec, f) or 0.0 for f in QUARTERS["q1"])

                q2 = sum(getattr(rec, f) or 0.0 for f in QUARTERS["q2"])

                q3 = sum(getattr(rec, f) or 0.0 for f in QUARTERS["q3"])

                q4 = sum(getattr(rec, f) or 0.0 for f in QUARTERS["q4"])

                rec.quarter1_total = q1

                rec.quarter2_total = q2

                rec.quarter3_total = q3

                rec.quarter4_total = q4

                plan_vals["quarter1_total"] = q1

                plan_vals["quarter2_total"] = q2

                plan_vals["quarter3_total"] = q3

                plan_vals["quarter4_total"] = q4

                if rec.id:

                    rec.with_context(in_distribute_plan_sync=True, skip_sync_lines=True, bypass_plan_lock=True).write(plan_vals)

    @api.onchange("annual_total")

    def _onchange_annual_total(self):

        self._distribute_plan_annual_total_proportionally()

    def _inverse_annual_total(self):

        if self.env.context.get("in_distribute_plan_sync"):

            return

        self._distribute_plan_annual_total_proportionally()

    @api.onchange(

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

        "opening_balance",

    )

    def _onchange_months_update_quarters(self):

        for rec in self:

            rec.quarter1_total = (rec.m01 or 0.0) + (rec.m02 or 0.0) + (rec.m03 or 0.0)

            rec.quarter2_total = (rec.m04 or 0.0) + (rec.m05 or 0.0) + (rec.m06 or 0.0)

            rec.quarter3_total = (rec.m07 or 0.0) + (rec.m08 or 0.0) + (rec.m09 or 0.0)

            rec.quarter4_total = (rec.m10 or 0.0) + (rec.m11 or 0.0) + (rec.m12 or 0.0)

            if rec.category not in ("manpower", "fixed_asset"):

                rec.annual_total = rec.quarter1_total + rec.quarter2_total + rec.quarter3_total + rec.quarter4_total

                rec.outstanding_balance_end_period = (rec.opening_balance or 0.0) + (rec.annual_total or 0.0)

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

            if rec.org_unit_id:

                rec.display_name = rec.org_unit_id.display_name or rec.org_unit_id.name or _("Work Unit")

            else:

                rec.display_name = rec.request_number or _("Draft Plan")

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

    @api.depends("line_ids.fa_annual_total_cost", "line_ids.line_type", "category")

    def _compute_total_estimated_amount(self):

        for rec in self:

            if rec.category != "fixed_asset":

                rec.total_estimated_amount = 0.0

            else:

                fa_lines = rec.line_ids.filtered(lambda l: l.line_type == "fixed_asset") or rec.fixed_asset_line_ids

                rec.total_estimated_amount = sum(fa_lines.mapped("fa_annual_total_cost"))

    @api.depends("line_ids.annual_total_cost", "line_ids.line_type", "manpower_line_ids.annual_total_cost", "category")

    def _compute_total_manpower_cost(self):

        for rec in self:

            if rec.category != "manpower" and not getattr(rec, "enable_manpower", False):

                rec.total_manpower_cost = 0.0

            else:

                mp_lines = rec.line_ids.filtered(lambda l: l.line_type == "manpower") or rec.manpower_line_ids

                rec.total_manpower_cost = sum(mp_lines.mapped("annual_total_cost"))

    @api.onchange("manpower_line_ids")

    def _onchange_manpower_line_ids(self):

        for rec in self:

            if rec.category == "manpower" or getattr(rec, "enable_manpower", False):

                rec._compute_totals()

                rec._compute_total_manpower_cost()

                rec._compute_operating_unit_manpower_budget()

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

            mp_lines = rec._get_category_lines("manpower") if hasattr(rec, "_get_category_lines") else rec.line_ids.filtered(lambda l: l.line_type == "manpower")

            is_manpower_applicable = (

                rec.category == "manpower"

                or rec.enable_manpower

                or bool(mp_lines)

            )

            if is_manpower_applicable:

                rec.existing_total_authorized = sum(rec.existing_manpower_summary_ids.mapped("approved_plan_count"))

                rec.existing_total_active = sum(rec.existing_manpower_summary_ids.mapped("active_employee_count"))

                rec.existing_total_vacancies = max(0, sum(rec.existing_manpower_summary_ids.mapped("vacant_position_count")))

                rec.existing_total_monthly_salary = sum(rec.existing_manpower_summary_ids.mapped("monthly_salary"))

                annual = sum(rec.existing_manpower_summary_ids.mapped("annual_salary"))

                rec.existing_total_annual_salary = annual

                rec.current_staff_salary_budget = annual

                new_cost = sum(mp_lines.mapped("annual_total_cost"))

                rec.new_planned_salary_budget = new_cost

                rec.total_operating_unit_manpower_budget = annual + new_cost

            else:

                rec.existing_total_authorized = 0

                rec.existing_total_active = 0

                rec.existing_total_vacancies = 0

                rec.existing_total_monthly_salary = 0.0

                rec.existing_total_annual_salary = 0.0

    def action_refresh_existing_manpower(self):

        """Action button to re-fetch and synchronize existing manpower from HR contracts and operating unit."""

        self._sync_existing_manpower_lines()

        self._compute_existing_manpower_data()

        self._compute_operating_unit_manpower_budget()

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

            self.env["hr.version"].sudo() if "hr.version" in self.env else (

                self.env["hr.contract"].sudo() if "hr.contract" in self.env else False

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

            unit_id = plan.org_unit_id.id

            # 1. Gather all active employees in this work unit

            emp_domain = [("active", "=", True)]

            if has_employee_model:

                emp_domain += [

                    "|",

                    ("operating_unit_ids", "in", [unit_id]),

                    ("default_operating_unit_id", "=", unit_id),

                ]

                employees = self.env["hr.employee"].sudo().search(emp_domain)

            else:

                employees = self.env["hr.employee"].sudo()

            # 2. Gather eligible positions from operating.unit.job.position

            ou_positions = self.env["operating.unit.job.position"].sudo().search([

                ("operating_unit_id", "=", unit_id),

                ("active", "=", True),

            ]) if has_ou_job_pos else self.env["operating.unit.job.position"].sudo()

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

                    "employee_id": emp.id,

                    "employee_code": emp_code,

                    "job_id": job.id,

                    "grade_id": emp_grade.id if emp_grade else False,

                    "contract_id": contract.id if contract else False,

                    "wage": wage,

                    "annual_salary": annual,

                    "contract_state": c_state if c_state in ('draft', 'probation', 'open', 'close', 'cancel') else 'open',

                })

            # Build position summary records

            pos_records_to_create = []

            for job_id, p_info in pos_dict.items():

                job_emps = p_info["employees"]

                active_count = len(job_emps)

                ou_pos = p_info.get("ou_pos")

                approved_count = p_info.get("approved_count", 0)

                vacant_count = max(0, getattr(ou_pos, "vacant_position_count", 0) or 0) if ou_pos else max(0, approved_count - active_count)

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

                    "job_id": job_id,

                    "grade_id": p_info["grade"].id if p_info["grade"] else False,

                    "approved_plan_count": approved_count,

                    "active_employee_count": active_count,

                    "vacant_position_count": vacant_count,

                    "monthly_salary": pos_monthly,

                    "annual_salary": pos_annual,

                })

            if has_emp_line_model:

                plan.existing_employee_line_ids = [Command.clear()] + [Command.create(r) for r in emp_records_to_create]

            if has_summary_model:

                plan.existing_manpower_summary_ids = [Command.clear()] + [Command.create(r) for r in pos_records_to_create]

            plan._compute_existing_manpower_data()

            plan._compute_operating_unit_manpower_budget()

    def _get_category_lines(self, cat):

        self.ensure_one()

        cat_field_map = {

            "deposit": "deposit_line_ids",

            "customer_base": "customer_base_line_ids",

            "fx": "fx_line_ids",

            "digital_banking": "digital_banking_line_ids",

            "loan_disbursement_collection": "loan_disbursement_line_ids",

            "loan_outstanding": "loan_outstanding_line_ids",

            "general_expense": "expense_line_ids",

            "manpower": "manpower_line_ids",

            "fixed_asset": "fixed_asset_line_ids",

            "credit_portfolio": "credit_portfolio_line_ids",

            "initiative_budget": "initiative_budget_line_ids",

        }

        # Dedicated category lines directly attached to this plan
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

            sibling_lines = self.env["pbms.plan.category.line"].search([

                ("plan_id.org_unit_id", "=", self.org_unit_id.id),

                ("plan_id.cycle_id", "=", self.cycle_id.id),

                ("plan_id.is_consolidated_district_plan", "=", bool(self.is_consolidated_district_plan)),

                ("plan_id.is_consolidated_ho_plan", "=", bool(self.is_consolidated_ho_plan)),

                ("plan_id.active", "=", True),

                ("line_type", "=", cat),

            ])

            if sibling_lines:

                return sibling_lines

        return self.env["pbms.plan.category.line"]

    @api.depends(

        "org_unit_id",

        "category",

        "enable_manpower",

        "line_ids.annual_total_cost",

        "line_ids.line_type",

        "line_ids.position_type",

        "line_ids.quantity",

        "existing_total_annual_salary",

        "existing_total_monthly_salary",

        "existing_manpower_summary_ids.annual_salary",

        "existing_manpower_summary_ids.monthly_salary",

    )

    def _compute_operating_unit_manpower_budget(self):

        for rec in self:

            mp_lines = rec._get_category_lines("manpower") if hasattr(rec, "_get_category_lines") else rec.line_ids.filtered(lambda l: l.line_type == "manpower")

            is_mp_applicable = (

                rec.category == "manpower"

                or rec.enable_manpower

                or bool(mp_lines)

            )

            if not is_mp_applicable:

                rec.current_staff_salary_budget = 0.0

                rec.new_planned_salary_budget = 0.0

                rec.total_operating_unit_manpower_budget = 0.0

                continue

            current_salary_total = (

                rec.existing_total_annual_salary

                or sum(rec.existing_manpower_summary_ids.mapped("annual_salary"))

                or (rec.existing_total_monthly_salary * 12.0)

                or 0.0

            )

            # Check sibling manpower plan if current card has no existing salary

            if not current_salary_total and rec.org_unit_id and rec.cycle_id:

                mp_plan = self.search([

                    ("org_unit_id", "=", rec.org_unit_id.id),

                    ("cycle_id", "=", rec.cycle_id.id),

                    ("category", "=", "manpower"),

                    ("active", "=", True),

                ], limit=1)

                if mp_plan and mp_plan.id != rec.id:

                    current_salary_total = (

                        mp_plan.existing_total_annual_salary

                        or mp_plan.current_staff_salary_budget

                        or sum(mp_plan.existing_manpower_summary_ids.mapped("annual_salary"))

                        or (mp_plan.existing_total_monthly_salary * 12.0)

                        or 0.0

                    )

            if not current_salary_total and rec.org_unit_id:

                EmployeeModel = self.env["hr.employee"] if "hr.employee" in self.env else False

                if EmployeeModel:

                    emps = EmployeeModel.sudo().search([

                        ("active", "=", True),

                        "|", "|",

                        ("operating_unit_id", "=", rec.org_unit_id.id),

                        ("operating_unit_ids", "in", [rec.org_unit_id.id]),

                        ("default_operating_unit_id", "=", rec.org_unit_id.id),

                    ])

                    ContractModel = (

                        self.env["hr.version"] if "hr.version" in self.env else (

                            self.env["hr.contract"] if "hr.contract" in self.env else False

                        )

                    )

                    emp_contract_map = {}

                    if ContractModel and emps:

                        contracts = ContractModel.sudo().search([

                            ("employee_id", "in", emps.ids),

                            ("state", "in", ("open", "probation", "draft")),

                        ])

                        for c in contracts:

                            if c.employee_id.id not in emp_contract_map:

                                emp_contract_map[c.employee_id.id] = c

                    for emp in emps:

                        w = 0.0

                        if hasattr(emp, "contract_id") and emp.contract_id:

                            w = getattr(emp.contract_id, "wage", 0.0) or getattr(emp.contract_id, "base_salary", 0.0) or 0.0

                        elif emp.id in emp_contract_map:

                            c = emp_contract_map[emp.id]

                            w = getattr(c, "wage", 0.0) or getattr(c, "base_salary", 0.0) or 0.0

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

    @api.onchange("existing_total_annual_salary", "existing_total_monthly_salary", "existing_manpower_summary_ids")

    def _onchange_existing_manpower_salary_budget(self):

        for rec in self:

            rec._compute_operating_unit_manpower_budget()

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

    @api.depends("line_ids.fa_q1", "line_ids.fa_q2", "line_ids.fa_q3", "line_ids.fa_q4", "line_ids.line_type")

    def _compute_fa_quarter_quantities(self):

        for rec in self:

            fa_lines = rec._get_category_lines("fixed_asset")

            rec.fa_q1 = int(sum(fa_lines.mapped("fa_q1")) or 0)

            rec.fa_q2 = int(sum(fa_lines.mapped("fa_q2")) or 0)

            rec.fa_q3 = int(sum(fa_lines.mapped("fa_q3")) or 0)

            rec.fa_q4 = int(sum(fa_lines.mapped("fa_q4")) or 0)

    _ROLLUP_QUARTER_FIELDS = {

        "deposit": ("deposit_q1_total", "deposit_q2_total", "deposit_q3_total", "deposit_q4_total"),

        "customer_base": ("customer_base_q1_total", "customer_base_q2_total", "customer_base_q3_total", "customer_base_q4_total"),

        "fx": ("fx_q1_total", "fx_q2_total", "fx_q3_total", "fx_q4_total"),

        "digital_banking": ("digital_banking_q1_total", "digital_banking_q2_total", "digital_banking_q3_total", "digital_banking_q4_total"),

        "general_expense": ("expense_q1_total", "expense_q2_total", "expense_q3_total", "expense_q4_total"),

        "manpower": ("q1_total_cost", "q2_total_cost", "q3_total_cost", "q4_total_cost"),

        "fixed_asset": ("fa_q1_total_cost", "fa_q2_total_cost", "fa_q3_total_cost", "fa_q4_total_cost"),

    }

    @api.depends(

        "category",

        "deposit_q1_total", "deposit_q2_total", "deposit_q3_total", "deposit_q4_total",

        "customer_base_q1_total", "customer_base_q2_total", "customer_base_q3_total", "customer_base_q4_total",

        "fx_q1_total", "fx_q2_total", "fx_q3_total", "fx_q4_total",

        "digital_banking_q1_total", "digital_banking_q2_total", "digital_banking_q3_total", "digital_banking_q4_total",

        "expense_q1_total", "expense_q2_total", "expense_q3_total", "expense_q4_total",

        "q1_total_cost", "q2_total_cost", "q3_total_cost", "q4_total_cost",

        "fa_q1_total_cost", "fa_q2_total_cost", "fa_q3_total_cost", "fa_q4_total_cost",

    )

    def _compute_rollup_quarter_totals(self):

        for rec in self:

            names = self._ROLLUP_QUARTER_FIELDS.get(rec.category)

            vals = [float(rec[n] or 0.0) for n in names] if names else [0.0] * 4

            rec.rollup_q1_total, rec.rollup_q2_total, rec.rollup_q3_total, rec.rollup_q4_total = vals

    @api.depends("line_ids.is_cascaded")

    def _compute_has_cascaded_targets(self):

        for rec in self:

            rec.has_cascaded_targets = any(l.is_cascaded for l in rec.line_ids)

    @api.depends("state", "line_ids", "line_ids.is_cascaded", "cycle_id")

    def _compute_is_targets_cascaded(self):

        Line = self.env["pbms.plan.category.line"].sudo()

        for rec in self:

            if rec.is_targets_cascaded:

                continue

            if rec.org_unit_type == "head_office" and rec.category != "manpower" and rec.state == "approved":

                has_dist = Line.search_count([

                    ("cycle_id", "=", rec.cycle_id.id),

                    ("line_type", "=", rec.category),

                    ("org_unit_id.work_unit_type", "=", "district_office"),

                    ("is_cascaded", "=", True),

                ]) > 0

                rec.is_targets_cascaded = bool(has_dist)

            elif rec.org_unit_type == "district_office" and rec.category != "manpower" and rec.has_cascaded_targets:

                child_branches = self.env["operating.unit"].sudo().search([

                    ("parent_unit", "=", rec.org_unit_id.id),

                    ("work_unit_type", "in", ("branch", "sub_branch", "service_center")),

                ])

                if child_branches:

                    has_branch = Line.search_count([

                        ("cycle_id", "=", rec.cycle_id.id),

                        ("line_type", "=", rec.category),

                        ("org_unit_id", "in", child_branches.ids),

                        ("is_cascaded", "=", True),

                    ]) > 0

                else:

                    has_branch = False

                rec.is_targets_cascaded = bool(has_branch)

            else:

                rec.is_targets_cascaded = False

    def _inverse_is_targets_cascaded(self):

        """Allow explicit writes to is_targets_cascaded."""

        pass

    def action_already_cascaded_notice(self):

        """Display an informational notification when clicking the 'Cascaded' button."""

        self.ensure_one()

        target_dest = _("districts") if self.org_unit_type == "head_office" else _("child branches")

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Already Cascaded"),

                "message": _("Targets for %s have already been cascaded to %s. Re-cascading is prevented.") % (

                    self.display_name, target_dest

                ),

                "type": "info",

                "sticky": False,

            },

        }

    @api.depends(
        "has_cascaded_targets", "line_ids.is_cascaded",

        "category",

        "line_ids.line_type",

        "line_ids.quantity",

        "line_ids.approved_quantity",

        "line_ids.fa_approved_total_cost",

        "line_ids.annual_total",

        "line_ids.proposed_annual_total",

        "line_ids.approved_annual_total",

        "line_ids.display_approved_annual_total",

        "line_ids.quarter1_total",

        "line_ids.quarter2_total",

        "line_ids.quarter3_total",

        "line_ids.quarter4_total",

        "line_ids.fulfillment_promotion",

        "line_ids.fulfillment_transfer",

        "line_ids.fulfillment_lateral",

        "line_ids.fulfillment_external",

    )

    def _compute_category_summaries(self):
        for rec in self:
            is_ho = bool(rec.is_head_office_unit or rec._is_head_office_plan() or rec.org_unit_type == "head_office")
            is_req = bool(rec.is_planning_request or rec.env.context.get("is_planning_request"))

            dep_lines = rec._get_category_lines("deposit")
            if dep_lines:
                rec.deposit_line_count = len(dep_lines)
                rec.deposit_annual_total = sum(dep_lines.mapped("annual_total"))
                rec.deposit_proposed_total = sum(dep_lines.mapped("proposed_annual_total"))
                rec.deposit_approved_total = 0.0 if (not is_ho and not rec.has_cascaded_targets) else sum(dep_lines.mapped("approved_annual_total"))
                rec.deposit_q1_total = sum(dep_lines.mapped("quarter1_total"))
                rec.deposit_q2_total = sum(dep_lines.mapped("quarter2_total"))
                rec.deposit_q3_total = sum(dep_lines.mapped("quarter3_total"))
                rec.deposit_q4_total = sum(dep_lines.mapped("quarter4_total"))
            elif rec.category == "deposit" and not is_req and rec.annual_total:
                rec.deposit_line_count = 1
                rec.deposit_annual_total = rec.annual_total or 0.0
                rec.deposit_proposed_total = rec.proposed_annual_total or 0.0
                if is_ho:
                    rec.deposit_approved_total = rec.approved_annual_total or 0.0
                elif rec.is_targets_cascaded or rec.has_cascaded_targets:
                    rec.deposit_approved_total = rec.approved_annual_total or 0.0
                else:
                    rec.deposit_approved_total = 0.0
                rec.deposit_q1_total = rec.quarter1_total or 0.0
                rec.deposit_q2_total = rec.quarter2_total or 0.0
                rec.deposit_q3_total = rec.quarter3_total or 0.0
                rec.deposit_q4_total = rec.quarter4_total or 0.0
            else:
                rec.deposit_line_count = 0
                rec.deposit_annual_total = 0.0
                rec.deposit_proposed_total = 0.0
                rec.deposit_approved_total = 0.0
                rec.deposit_q1_total = 0.0
                rec.deposit_q2_total = 0.0
                rec.deposit_q3_total = 0.0
                rec.deposit_q4_total = 0.0

            cb_lines = rec._get_category_lines("customer_base")
            if cb_lines:
                rec.customer_base_line_count = len(cb_lines)
                rec.customer_base_annual_total = sum(cb_lines.mapped("annual_total"))
                rec.customer_base_proposed_total = sum(cb_lines.mapped("proposed_annual_total"))
                rec.customer_base_approved_total = 0.0 if (not is_ho and not rec.has_cascaded_targets) else sum(cb_lines.mapped("approved_annual_total"))
                rec.customer_base_q1_total = sum(cb_lines.mapped("quarter1_total"))
                rec.customer_base_q2_total = sum(cb_lines.mapped("quarter2_total"))
                rec.customer_base_q3_total = sum(cb_lines.mapped("quarter3_total"))
                rec.customer_base_q4_total = sum(cb_lines.mapped("quarter4_total"))
            elif rec.category == "customer_base" and not is_req and rec.annual_total:
                rec.customer_base_line_count = 1
                rec.customer_base_annual_total = rec.annual_total or 0.0
                rec.customer_base_proposed_total = rec.proposed_annual_total or 0.0
                if is_ho:
                    rec.customer_base_approved_total = rec.approved_annual_total or 0.0
                elif rec.is_targets_cascaded or rec.has_cascaded_targets:
                    rec.customer_base_approved_total = rec.approved_annual_total or 0.0
                else:
                    rec.customer_base_approved_total = 0.0
                rec.customer_base_q1_total = rec.quarter1_total or 0.0
                rec.customer_base_q2_total = rec.quarter2_total or 0.0
                rec.customer_base_q3_total = rec.quarter3_total or 0.0
                rec.customer_base_q4_total = rec.quarter4_total or 0.0
            else:
                rec.customer_base_line_count = 0
                rec.customer_base_annual_total = 0.0
                rec.customer_base_proposed_total = 0.0
                rec.customer_base_approved_total = 0.0
                rec.customer_base_q1_total = 0.0
                rec.customer_base_q2_total = 0.0
                rec.customer_base_q3_total = 0.0
                rec.customer_base_q4_total = 0.0

            fx_lines = rec._get_category_lines("fx")
            if fx_lines:
                rec.fx_line_count = len(fx_lines)
                rec.fx_annual_total = sum(fx_lines.mapped("annual_total"))
                rec.fx_proposed_total = sum(fx_lines.mapped("proposed_annual_total"))
                rec.fx_approved_total = 0.0 if (not is_ho and not rec.has_cascaded_targets) else sum(fx_lines.mapped("approved_annual_total"))
                rec.fx_q1_total = sum(fx_lines.mapped("quarter1_total"))
                rec.fx_q2_total = sum(fx_lines.mapped("quarter2_total"))
                rec.fx_q3_total = sum(fx_lines.mapped("quarter3_total"))
                rec.fx_q4_total = sum(fx_lines.mapped("quarter4_total"))
            elif rec.category == "fx" and not is_req and rec.annual_total:
                rec.fx_line_count = 1
                rec.fx_annual_total = rec.annual_total or 0.0
                rec.fx_proposed_total = rec.proposed_annual_total or 0.0
                if is_ho:
                    rec.fx_approved_total = rec.approved_annual_total or 0.0
                elif rec.is_targets_cascaded or rec.has_cascaded_targets:
                    rec.fx_approved_total = rec.approved_annual_total or 0.0
                else:
                    rec.fx_approved_total = 0.0
                rec.fx_q1_total = rec.quarter1_total or 0.0
                rec.fx_q2_total = rec.quarter2_total or 0.0
                rec.fx_q3_total = rec.quarter3_total or 0.0
                rec.fx_q4_total = rec.quarter4_total or 0.0
            else:
                rec.fx_line_count = 0
                rec.fx_annual_total = 0.0
                rec.fx_proposed_total = 0.0
                rec.fx_approved_total = 0.0
                rec.fx_q1_total = 0.0
                rec.fx_q2_total = 0.0
                rec.fx_q3_total = 0.0
                rec.fx_q4_total = 0.0

            db_lines = rec._get_category_lines("digital_banking")
            if db_lines:
                rec.digital_banking_line_count = len(db_lines)
                rec.digital_banking_annual_total = sum(db_lines.mapped("annual_total"))
                rec.digital_banking_proposed_total = sum(db_lines.mapped("proposed_annual_total"))
                rec.digital_banking_approved_total = 0.0 if (not is_ho and not rec.has_cascaded_targets) else sum(db_lines.mapped("approved_annual_total"))
                rec.digital_banking_q1_total = sum(db_lines.mapped("quarter1_total"))
                rec.digital_banking_q2_total = sum(db_lines.mapped("quarter2_total"))
                rec.digital_banking_q3_total = sum(db_lines.mapped("quarter3_total"))
                rec.digital_banking_q4_total = sum(db_lines.mapped("quarter4_total"))
            elif rec.category == "digital_banking" and not is_req and rec.annual_total:
                rec.digital_banking_line_count = 1
                rec.digital_banking_annual_total = rec.annual_total or 0.0
                rec.digital_banking_proposed_total = rec.proposed_annual_total or 0.0
                if is_ho:
                    rec.digital_banking_approved_total = rec.approved_annual_total or 0.0
                elif rec.is_targets_cascaded or rec.has_cascaded_targets:
                    rec.digital_banking_approved_total = rec.approved_annual_total or 0.0
                else:
                    rec.digital_banking_approved_total = 0.0
                rec.digital_banking_q1_total = rec.quarter1_total or 0.0
                rec.digital_banking_q2_total = rec.quarter2_total or 0.0
                rec.digital_banking_q3_total = rec.quarter3_total or 0.0
                rec.digital_banking_q4_total = rec.quarter4_total or 0.0
            else:
                rec.digital_banking_line_count = 0
                rec.digital_banking_annual_total = 0.0
                rec.digital_banking_proposed_total = 0.0
                rec.digital_banking_approved_total = 0.0
                rec.digital_banking_q1_total = 0.0
                rec.digital_banking_q2_total = 0.0
                rec.digital_banking_q3_total = 0.0
                rec.digital_banking_q4_total = 0.0

            ld_lines = rec._get_category_lines("loan_disbursement_collection")
            if ld_lines:
                rec.loan_disbursement_line_count = len(ld_lines)
                rec.loan_disbursement_annual_total = sum(ld_lines.mapped("annual_total"))
                rec.loan_disbursement_proposed_total = sum(ld_lines.mapped("proposed_annual_total"))
                rec.loan_disbursement_approved_total = sum(ld_lines.mapped("approved_annual_total"))
                rec.loan_disbursement_q1_total = sum(ld_lines.mapped("quarter1_total"))
                rec.loan_disbursement_q2_total = sum(ld_lines.mapped("quarter2_total"))
                rec.loan_disbursement_q3_total = sum(ld_lines.mapped("quarter3_total"))
                rec.loan_disbursement_q4_total = sum(ld_lines.mapped("quarter4_total"))
            elif rec.category == "loan_disbursement_collection" and not is_req and rec.annual_total:
                rec.loan_disbursement_line_count = 1
                rec.loan_disbursement_annual_total = rec.annual_total or 0.0
                rec.loan_disbursement_proposed_total = rec.proposed_annual_total or 0.0
                rec.loan_disbursement_approved_total = rec.approved_annual_total or 0.0
                rec.loan_disbursement_q1_total = rec.quarter1_total or 0.0
                rec.loan_disbursement_q2_total = rec.quarter2_total or 0.0
                rec.loan_disbursement_q3_total = rec.quarter3_total or 0.0
                rec.loan_disbursement_q4_total = rec.quarter4_total or 0.0
            else:
                rec.loan_disbursement_line_count = 0
                rec.loan_disbursement_annual_total = 0.0
                rec.loan_disbursement_proposed_total = 0.0
                rec.loan_disbursement_approved_total = 0.0
                rec.loan_disbursement_q1_total = 0.0
                rec.loan_disbursement_q2_total = 0.0
                rec.loan_disbursement_q3_total = 0.0
                rec.loan_disbursement_q4_total = 0.0

            lo_lines = rec._get_category_lines("loan_outstanding")
            if lo_lines:
                rec.loan_outstanding_line_count = len(lo_lines)
                rec.loan_outstanding_annual_total = sum(lo_lines.mapped("annual_total"))
                rec.loan_outstanding_proposed_total = sum(lo_lines.mapped("proposed_annual_total"))
                rec.loan_outstanding_approved_total = sum(lo_lines.mapped("approved_annual_total"))
                rec.loan_outstanding_q1_total = sum(lo_lines.mapped("quarter1_total"))
                rec.loan_outstanding_q2_total = sum(lo_lines.mapped("quarter2_total"))
                rec.loan_outstanding_q3_total = sum(lo_lines.mapped("quarter3_total"))
                rec.loan_outstanding_q4_total = sum(lo_lines.mapped("quarter4_total"))
            elif rec.category == "loan_outstanding" and not is_req and rec.annual_total:
                rec.loan_outstanding_line_count = 1
                rec.loan_outstanding_annual_total = rec.annual_total or 0.0
                rec.loan_outstanding_proposed_total = rec.proposed_annual_total or 0.0
                rec.loan_outstanding_approved_total = rec.approved_annual_total or 0.0
                rec.loan_outstanding_q1_total = rec.quarter1_total or 0.0
                rec.loan_outstanding_q2_total = rec.quarter2_total or 0.0
                rec.loan_outstanding_q3_total = rec.quarter3_total or 0.0
                rec.loan_outstanding_q4_total = rec.quarter4_total or 0.0
            else:
                rec.loan_outstanding_line_count = 0
                rec.loan_outstanding_annual_total = 0.0
                rec.loan_outstanding_proposed_total = 0.0
                rec.loan_outstanding_approved_total = 0.0
                rec.loan_outstanding_q1_total = 0.0
                rec.loan_outstanding_q2_total = 0.0
                rec.loan_outstanding_q3_total = 0.0
                rec.loan_outstanding_q4_total = 0.0

            exp_lines = rec._get_category_lines("general_expense")
            if exp_lines:
                rec.expense_line_count = len(exp_lines)
                rec.expense_annual_total = sum(exp_lines.mapped("annual_total"))
                rec.expense_proposed_total = sum(exp_lines.mapped("proposed_annual_total"))
                rec.expense_approved_total = sum(exp_lines.mapped("approved_annual_total"))
                rec.expense_q1_total = sum(exp_lines.mapped("quarter1_total"))
                rec.expense_q2_total = sum(exp_lines.mapped("quarter2_total"))
                rec.expense_q3_total = sum(exp_lines.mapped("quarter3_total"))
                rec.expense_q4_total = sum(exp_lines.mapped("quarter4_total"))
            elif rec.category == "general_expense" and not is_req and rec.annual_total:
                rec.expense_line_count = 1
                rec.expense_annual_total = rec.annual_total or 0.0
                rec.expense_proposed_total = rec.proposed_annual_total or 0.0
                rec.expense_approved_total = rec.approved_annual_total or 0.0
                rec.expense_q1_total = rec.quarter1_total or 0.0
                rec.expense_q2_total = rec.quarter2_total or 0.0
                rec.expense_q3_total = rec.quarter3_total or 0.0
                rec.expense_q4_total = rec.quarter4_total or 0.0
            else:
                rec.expense_line_count = 0
                rec.expense_annual_total = 0.0
                rec.expense_proposed_total = 0.0
                rec.expense_approved_total = 0.0
                rec.expense_q1_total = 0.0
                rec.expense_q2_total = 0.0
                rec.expense_q3_total = 0.0
                rec.expense_q4_total = 0.0

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

        "line_ids.line_type",

        "line_ids.quantity",

        "line_ids.annual_total",

        "line_ids.annual_total_cost",

        "line_ids.proposed_annual_total",

        "line_ids.approved_annual_total",

        "line_ids.fa_annual_total_cost",

        "line_ids.is_cascaded",

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

        usd_currency = self.env["res.currency"].search([("name", "=", "USD")], limit=1)

        is_req_ctx = bool(self.env.context.get("is_planning_request"))

        for rec in self:

            curr_sym = (rec.currency_id.symbol if rec.currency_id and rec.currency_id.symbol else (rec.currency_id.name if rec.currency_id else "Br")) or "Br"

            is_approved = (rec.state == "approved")

            is_req = is_req_ctx or getattr(rec, "is_planning_request", False)

            all_lines = rec.line_ids if rec.line_ids else rec.env["pbms.plan.category.line"]

            if not all_lines and rec.org_unit_id and rec.cycle_id:

                domain = [

                    ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                    ("plan_id.cycle_id", "=", rec.cycle_id.id),

                    ("plan_id.active", "=", True),

                ]

                if not is_req and rec.category:

                    domain.append(("line_type", "=", rec.category))

                all_lines = self.env["pbms.plan.category.line"].search(domain)

            if not all_lines:

                rec.kanban_breakdown_html = False

                continue

            # Isolate card breakdown strictly to this plan's category, or all categories if in planning request or has multiple line types

            present_line_types = {l.line_type for l in all_lines if l.line_type}

            if is_req or len(present_line_types) > 1:

                used_cats = [c for c in cat_order if c in present_line_types] or cat_order

                is_multi_category = len(used_cats) > 1

            else:

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

                    fx_curr = rec.fx_currency_id or usd_currency or rec.currency_id

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

                    "loan_disbursement_collection": (_("Loan Disbursement & Collection"), _("Annual Total")),

                    "loan_outstanding": (_("Loan Product"), _("Annual Total")),

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

            "loan_disbursement_collection": {"color": "#425727", "bg": "#EDF3E8", "border": "#C8DCB8", "icon": "fa-exchange", "label": _("Loan Disbursement & Collection")},

            "loan_outstanding": {"color": "#726732", "bg": "#F7F5EB", "border": "#DDD5B8", "icon": "fa-credit-card", "label": _("Loan & Advances Outstanding")},

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

            unit_type = ou.work_unit_type if ou else False

            is_dist = unit_type in ("district_office", "regional_office")

            is_ho = unit_type == "head_office"

            is_dist_or_ho = is_dist or is_ho

            if cur_cat and is_dist_or_ho and cur_cat in ("deposit", "customer_base", "fx", "digital_banking"):

                return res  # Preserve explicit mobilization category for district/HO overview cards

            if not cur_cat or (Config is not None and ou and not Config.is_category_enabled(cur_cat, ou)):

                if Config is not None and ou:

                    if is_dist:

                        res["category"] = "deposit"

                    else:

                        res["category"] = Config.get_default_category_for_unit(ou)

        return res

    @api.model_create_multi

    def create(self, vals_list):

        # Return existing overview card if already created for a district/HO unit

        if len(vals_list) == 1:

            vals0 = vals_list[0]

            ou0 = vals0.get("org_unit_id") or self.env.context.get("default_org_unit_id")

            cyc0 = vals0.get("cycle_id") or self.env.context.get("default_cycle_id")

            cat0 = vals0.get("category") or self.env.context.get("default_category")

            if ou0 and cyc0 and cat0 in ("deposit", "customer_base", "fx", "digital_banking"):

                ou_rec = self.env["operating.unit"].browse(ou0)

                if ou_rec.work_unit_type in ("district_office", "head_office"):

                    is_ho_cons = bool(vals0.get("is_consolidated_ho_plan") or self.env.context.get("default_is_consolidated_ho_plan"))
                    is_dist_cons = bool(vals0.get("is_consolidated_district_plan") or self.env.context.get("default_is_consolidated_district_plan"))

                    existing_card = self.search([

                        ("org_unit_id", "=", ou0),

                        ("cycle_id", "=", cyc0),

                        ("category", "=", cat0),

                        ("is_consolidated_ho_plan", "=", is_ho_cons),

                        ("is_consolidated_district_plan", "=", is_dist_cons),

                        ("active", "=", True),

                    ], limit=1)

                    if existing_card:

                        return existing_card

        user_unit_ids = self.env.user._pbms_operating_unit_ids()

        if self.env.user._pbms_is_respective_chief():

            user_unit_ids = list(set(user_unit_ids + (self.env.user._pbms_chief_scope_unit_ids() or [])))

        for vals in vals_list:

            _process_workforce_document_vals(vals)

            _validate_month_values_not_text(vals)

            org_unit_id = vals.get("org_unit_id")

            if org_unit_id and user_unit_ids and org_unit_id not in user_unit_ids:

                if not (self.env.user._pbms_is_sppmd_admin() or self.env.user._pbms_is_sppmd_approver() or self.env.user._pbms_is_ho_reviewer() or self.env.user._pbms_is_district_reviewer() or self.env.user._pbms_is_respective_chief()):

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

            # If category is disabled for this unit, re-assign only if not an explicit category or mobilization category for district/HO

            Config = self.env.get("pbms.planning.config")

            ou = self.env["operating.unit"].browse(org_unit_id) if org_unit_id else self.env.user.default_operating_unit_id

            unit_type = ou.work_unit_type if ou else False

            is_dist = unit_type in ("district_office", "regional_office")

            is_ho = unit_type == "head_office"

            is_dist_or_ho = is_dist or is_ho

            explicit_cat = vals.get("category") or self.env.context.get("default_category")

            if explicit_cat:

                vals["category"] = explicit_cat

            elif Config is not None and ou and vals.get("category") and not Config.is_category_enabled(vals["category"], ou):

                found_cat = False

                for cat, fname in self._tab_line_fields.items():

                    if vals.get(fname) and Config.is_category_enabled(cat, ou):

                        found_cat = cat

                        break

                if found_cat:

                    vals["category"] = found_cat

                elif is_dist:

                    vals["category"] = "deposit"

                else:

                    vals["category"] = Config.get_default_category_for_unit(ou)

            # Default fallback if still not determined

            if not vals.get("category"):

                if is_dist:

                    vals["category"] = "deposit"

                else:

                    vals["category"] = Config.get_default_category_for_unit(ou) if (Config is not None and ou) else "general_expense"

            # 1. Submitted Plan Check: Prevent creating another plan for the same category if already submitted or approved

            if org_unit_id and vals.get("cycle_id") and not self.env.context.get("skip_sync_category_records") and not self.env.context.get("bypass_plan_lock"):

                is_mobilization_card = is_dist_or_ho and vals.get("category") in ("deposit", "customer_base", "fx", "digital_banking")

                if not is_mobilization_card:

                    domain_sub = [

                        ("org_unit_id", "=", org_unit_id),

                        ("cycle_id", "=", vals.get("cycle_id")),

                        ("category", "=", vals.get("category")),

                        ("is_consolidated_district_plan", "=", bool(vals.get("is_consolidated_district_plan"))),

                        ("is_consolidated_ho_plan", "=", bool(vals.get("is_consolidated_ho_plan"))),

                        ("active", "=", True),

                        ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "approved")),

                    ]

                    submitted_existing = self.search(domain_sub, limit=1)

                    if submitted_existing:

                        unit_name = self.env["operating.unit"].browse(org_unit_id).display_name

                        cycle_name = self.env["pbms.planning.cycle"].browse(vals.get("cycle_id")).name

                        cat_name = dict(self._fields["category"].selection).get(vals.get("category"), vals.get("category"))

                        state_label = dict(self._fields["state"].selection).get(submitted_existing.state, submitted_existing.state)

                        req_num = submitted_existing.request_number or "N/A"

                        user = self.env.user

                        is_admin = (

                            user.has_group("bunna_pbms.group_pbms_manager")

                            or user.has_group("base.group_system")

                            or self.env.is_admin()

                            or self.env.su

                        )

                        if is_admin:

                            action_advice = _(

                                "As an SPPMD Administrator, please open the existing plan (Request No: %(req)s) and click 'Reset to Draft' to make modifications, or archive/delete it first if you wish to create a fresh plan from scratch.",

                                req=req_num,

                            )

                        else:

                            action_advice = _("If you need to make changes, request the reviewer to return the plan for revision or reset it to draft.")

                        raise ValidationError(_(

                            "A %(cat)s plan for %(unit)s in budget year '%(cycle)s' has already been submitted and is currently in '%(state)s' status.\n"

                            "Each operating unit can only have one plan per category per fiscal year. You cannot create a second plan while a plan is already submitted or approved.\n"

                            "%(action_advice)s",

                            cat=cat_name,

                            unit=unit_name,

                            cycle=cycle_name,

                            state=state_label,

                            action_advice=action_advice,

                        ))

                    # 2. Duplicate Plan Check: Ensure an operating unit creates only ONE plan per category per cycle

                    is_cons_val = bool(vals.get("is_consolidated_ho_plan"))
                    is_dist_cons_val = bool(vals.get("is_consolidated_district_plan"))
                    existing_dups = self.sudo().search([

                        ("org_unit_id", "=", org_unit_id),

                        ("cycle_id", "=", vals.get("cycle_id")),

                        ("category", "=", vals.get("category")),

                        ("is_consolidated_ho_plan", "=", is_cons_val),

                        ("is_consolidated_district_plan", "=", is_dist_cons_val),

                        ("active", "=", True),

                    ])

                    blocking_existing = False

                    for existing in existing_dups:

                        has_existing_data = bool(existing.line_ids) or any(getattr(existing, m, 0.0) for m in MONTH_FIELDS) or ((getattr(existing, "annual_total", 0.0) or 0.0) > 0.0)

                        if existing.state == "draft" and not has_existing_data:

                            existing.sudo().with_context(bypass_plan_lock=True).write({"active": False})

                        else:

                            blocking_existing = existing

                    if blocking_existing:

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

                            req=blocking_existing.request_number or "N/A",

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

            if rec.org_unit_id and rec.cycle_id:

                rec._sync_workforce_document_to_siblings()

        return records

    def write(self, vals):

        _process_workforce_document_vals(vals)

        _validate_month_values_not_text(vals)

        if "cpco_attachment_ids" in vals and not self.env.context.get("bypass_plan_lock"):

            for rec in self:

                if rec.state != "cpco_review" or not rec.can_cpco_review:

                    raise UserError(_("CPCO Attachments can only be added or modified by a user with CPCO privilege while the plan is in the CPCO Review stage."))

        if any(f in vals for f in ("workforce_document", "workforce_document_filename", "workforce_document_base64")) and not self.env.context.get("bypass_plan_lock"):

            for rec in self:

                if rec.state not in ("draft", "returned", "info_requested"):

                    raise UserError(_("You cannot upload or modify the attached document after the plan has been submitted."))

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

                        ("category", "=", target_category),

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

                    category_existing_dups = self.sudo().search([

                        ("org_unit_id", "=", target_unit_id),

                        ("cycle_id", "=", target_cycle_id),

                        ("category", "=", target_category),

                        ("id", "not in", self.ids),

                        ("active", "=", True),

                    ])

                    blocking_cat_existing = False

                    for cat_ex in category_existing_dups:

                        has_ex_data = bool(cat_ex.line_ids) or any(getattr(cat_ex, m, 0.0) for m in MONTH_FIELDS) or ((getattr(cat_ex, "annual_total", 0.0) or 0.0) > 0.0)

                        if cat_ex.state == "draft" and not has_ex_data:

                            cat_ex.sudo().with_context(bypass_plan_lock=True).write({"active": False})

                        else:

                            blocking_cat_existing = cat_ex

                    if blocking_cat_existing:

                        unit_name = self.env["operating.unit"].browse(target_unit_id).display_name

                        cycle_name = self.env["pbms.planning.cycle"].browse(target_cycle_id).name

                        cat_name = dict(self._fields["category"].selection).get(target_category, target_category)

                        raise ValidationError(_(

                            "A %(cat)s plan already exists for %(unit)s in budget year '%(cycle)s'.",

                            cat=cat_name,

                            unit=unit_name,

                            cycle=cycle_name,

                        ))

        target_keys = {

            "m01", "m02", "m03", "m04", "m05", "m06",

            "m07", "m08", "m09", "m10", "m11", "m12",

            "opening_balance", "annual_total",

            "quarter1_total", "quarter2_total", "quarter3_total", "quarter4_total"

        }

        if (target_keys & set(vals.keys())) and not self.env.context.get("skip_sync_lines") and not self.env.context.get("in_distribute_plan_sync"):

            for rec in self:

                cat_lines = rec.line_ids.filtered(lambda l: l.line_type == rec.category) if rec.line_ids else rec.env["pbms.plan.category.line"]

                if len(cat_lines) == 1:

                    sync_vals = {k: vals[k] for k in target_keys if k in vals}

                    cat_lines.with_context(skip_sync_lines=True, bypass_plan_lock=True).sudo().write(sync_vals)

                elif len(cat_lines) > 1 and "annual_total" in vals:

                    rec.with_context(in_distribute_plan_sync=True)._distribute_plan_annual_total_proportionally()

        res = super().write(vals)

        if not self.env.context.get("in_workforce_doc_sync") and any(f in vals for f in ("workforce_document", "workforce_document_filename", "workforce_document_base64")):

            if "workforce_document" in vals and not vals.get("workforce_document"):

                for rec in self:

                    if rec.org_unit_id and rec.cycle_id:

                        siblings = self.sudo().search([

                            ("org_unit_id", "=", rec.org_unit_id.id),

                            ("cycle_id", "=", rec.cycle_id.id),

                            ("active", "=", True),

                            ("id", "!=", rec.id),

                        ])

                        if siblings:

                            siblings.with_context(bypass_plan_lock=True, in_workforce_doc_sync=True, skip_sync_category_records=True).write({

                                "workforce_document": False,

                                "workforce_document_filename": False,

                                "workforce_document_base64": False,

                            })

            else:

                self._sync_workforce_document_to_siblings()

        if "org_unit_id" in vals or "category" in vals:

            for rec in self:

                if (rec.category == "manpower" or rec.enable_manpower) and rec.org_unit_id and not rec.existing_manpower_summary_ids:

                    rec._sync_existing_manpower_lines()

        if not self.env.context.get("bypass_plan_lock") and not self.env.context.get("skip_dropdown_plan_check"):

            CHECK_CATS = {"deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"}

            for rec in self:

                if rec.category in CHECK_CATS and rec.state in ("draft", "returned", "info_requested"):

                    rec._check_all_dropdowns_planned()

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

        if (

            self.env.context.get("cleanup_duplicate_district_cards")

            and not self.env.context.get("skip_cleanup_district_cards")

        ):

            try:

                self.with_context(skip_cleanup_district_cards=True, skip_sync_category_records=True, bypass_plan_lock=True)._cleanup_duplicate_district_cards()

            except Exception:

                pass

        user = self.env.user

        has_id_filter = any(isinstance(leaf, (list, tuple)) and len(leaf) >= 2 and leaf[0] == "id" for leaf in (domain or []))

        if not self.env.su and not bypass_access and not has_id_filter and not self.env.context.get("bypass_category_config_filter"):

            Config = self.env.get("pbms.planning.config")

            if Config is not None:

                target_cats = set()

                for leaf in (domain or []):

                    if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "category":

                        if leaf[1] == "=" and leaf[2]:

                            target_cats.add(leaf[2])

                        elif leaf[1] == "in" and isinstance(leaf[2], (list, tuple, set)):

                            target_cats.update(c for c in leaf[2] if c)

                if target_cats and not self.env.context.get("is_planning_request") and not self.env.context.get("skip_realign_on_search"):

                    try:

                        misaligned_lines = self.env["pbms.plan.category.line"].sudo().search([
                            ("line_type", "in", list(target_cats)),
                            ("plan_id.active", "=", True),
                            ("plan_id.category", "not in", list(target_cats)),
                            "|",
                            ("plan_id.is_consolidated_district_plan", "=", True),
                            ("plan_id.is_consolidated_ho_plan", "=", True),
                        ])

                        if misaligned_lines:

                            misaligned_plans = misaligned_lines.mapped("plan_id")

                            misaligned_plans.with_context(

                                skip_realign_on_search=True,

                                skip_sync_category_records=True,

                                bypass_plan_lock=True,

                            )._realign_lines_to_matching_cards(plans=misaligned_plans)

                    except Exception:

                        pass

                for cat in target_cats:

                    if cat not in ("general_expense", "fixed_asset", "manpower"):

                        disabled_ou_ids = Config.sudo().get_disabled_unit_ids_for_category(cat)

                        if disabled_ou_ids:

                            domain = Domain.AND([

                                domain,

                                [

                                    "|", ("category", "!=", cat),

                                    "|", ("state", "!=", "draft"),

                                    "|", ("org_unit_type", "in", ("district_office", "head_office", "regional_office")),

                                    ("org_unit_id", "not in", disabled_ou_ids),

                                ],

                            ])

        # Scope filters for non-admin users

        if (

            not self.env.su

            and not bypass_access

            and not has_id_filter

            and not self.env.context.get("bypass_approver_branch_filter")

            and not user._pbms_is_sppmd_admin()

            and not self.env.is_admin()

        ):

            user_ou_ids = user._pbms_operating_unit_ids()
            is_ho_reviewer = user.has_group("bunna_pbms.group_pbms_ho_reviewer") or user._pbms_is_ho_reviewer()
            is_chief = user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief()
            if is_ho_reviewer or is_chief:
                role_domains = [[
                    "&",
                    ("org_unit_id", "in", user_ou_ids),
                    ("org_unit_type", "=", "head_office"),
                ]]
            else:
                role_domains = [[("org_unit_id", "in", user_ou_ids)]]

            if user.has_group("bunna_pbms.group_pbms_approver"):
                role_domains.append([
                    "&",
                    ("state", "!=", "draft"),
                    "|", "|",
                    ("category", "not in", ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding")),
                    ("org_unit_type", "in", ("head_office", "district_office")),
                    ("state", "in", ("district_endorsed", "ho_reviewed", "approved")),
                ])

            if is_ho_reviewer:
                ho_cats = [c for c in user._pbms_ho_review_categories() if c != "manpower"]
                role_domains.append([
                    "|",
                        "&",
                            ("category", "=", "manpower"),
                            ("state", "in", ("ho_endorse", "cpco_endorse", "approved")),
                        "&",
                            ("category", "in", ho_cats),
                            "|", "|",
                            "&",
                                ("org_unit_type", "=", "head_office"),
                                ("state", "in", ("submitted", "district_endorsed", "ho_reviewed", "committee_review", "board_ceo_approval", "approved", "info_requested", "returned")),
                            "&",
                                ("category", "in", ("deposit", "customer_base", "fx", "digital_banking")),
                                ("state", "in", ("district_endorsed", "ho_reviewed", "approved")),
                            "&",
                                "&",
                                    ("category", "in", ("general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding")),
                                    ("org_unit_type", "not in", ("head_office",)),
                                ("state", "in", ("submitted", "district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed", "approved")),
                ])

            if user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief():
                chief_wf_states = (
                    "chief_review", "people_solutions_review", "cpco_review", "committee_review",
                    "ceo_approval", "board_ceo_approval", "approved", "rejected", "info_requested",
                )
                chief_ho_history_states = (
                    "chief_review", "submitted", "district_endorsed", "district_approved", "ho_reviewed",
                    "committee_review", "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",
                    "people_solutions_review", "cpco_review", "approved", "rejected", "info_requested", "returned",
                )
                chief_scope_ou_ids = user._pbms_chief_scope_unit_ids()
                sub_user_ids = user._pbms_chief_subordinate_user_ids()
                direct_chief_criteria = [
                    "|",
                    ("create_uid", "in", sub_user_ids),
                    "|",
                    ("submitted_by", "in", sub_user_ids),
                    "|",
                    ("district_id", "in", chief_scope_ou_ids),
                    ("org_unit_id", "in", chief_scope_ou_ids),
                ]
                chief_domain = [
                    "|",
                    "&",
                    ("org_unit_id", "in", user_ou_ids),
                    ("org_unit_type", "=", "head_office"),
                    "|",
                    "&",
                    ("category", "=", "manpower"),
                    "&",
                    ("state", "in", chief_wf_states),
                    *direct_chief_criteria,
                    "&",
                    ("org_unit_type", "=", "head_office"),
                    "&",
                    ("state", "in", chief_ho_history_states),
                    *direct_chief_criteria,
                ]
                role_domains.append(chief_domain)

            if user.has_group("bunna_pbms.group_pbms_people_solutions"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("category", "=", "manpower"),

                    ("state", "in", (

                        "people_solutions_review", "cpco_review", "committee_review",

                        "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",

                        "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_cpco"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("category", "=", "manpower"),

                    ("state", "in", (

                        "cpco_review", "committee_review",

                        "ceo_approval", "board_ceo_approval", "ho_endorse", "cpco_endorse",

                        "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_people_operations"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("category", "=", "manpower"),

                    ("state", "=", "approved"),

                ])

            if user.has_group("bunna_pbms.group_pbms_budget_hiring_committee"):

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                    ("category", "in", ("manpower", "fixed_asset", "initiative_budget")),

                    ("state", "in", (

                        "committee_review", "ceo_approval", "board_ceo_approval",

                        "ho_endorse", "cpco_endorse", "approved",

                    )),

                ])

            if user.has_group("bunna_pbms.group_pbms_ceo") or user._pbms_is_ceo():

                role_domains.append([

                    "|",

                    ("state", "in", ("ceo_approval", "board_ceo_approval")),

                    "|",

                    ("ceo_approver_id", "=", user.id),

                    "&",

                    ("category", "=", "manpower"),

                    ("state", "in", ("ho_endorse", "cpco_endorse", "approved", "rejected")),

                ])

            if user.has_group("bunna_pbms.group_pbms_district_reviewer"):

                child_unit_ids = user._pbms_child_operating_unit_ids()

                role_domains.append([

                    "|",

                    ("org_unit_id", "in", user_ou_ids),

                    "&",

                        ("state", "!=", "draft"),

                        "|",

                        ("district_id", "in", user_ou_ids),

                        "|",

                        ("org_unit_id", "in", child_unit_ids),

                        ("org_unit_id.parent_unit", "in", user_ou_ids),

                ])

            if _safe_table_exists(self.env, "pbms.privilege.assignment"):
                try:
                    Assignment = self.env["pbms.privilege.assignment"].sudo()
                    user_group_ids = user.all_group_ids.ids if hasattr(user, "all_group_ids") else getattr(user, "group_ids", getattr(user, "groups_id", self.env["res.groups"])).ids
                    u_domain = ["|", ("user_id", "=", user.id), ("group_id", "in", user_group_ids)]
                    if hasattr(user, "employee_id") and user.employee_id and user.employee_id.job_id:
                        u_domain = ["|", ("job_id", "=", user.employee_id.job_id.id)] + u_domain
                    dyn_assigns = Assignment.search([
                        ("active", "=", True),
                        ("grant_type", "=", "allow"),
                    ] + u_domain)
                    for da in dyn_assigns:
                        da_dom = []
                        if da.category_ids:
                            da_dom.append(("category", "in", da.category_ids.mapped("code")))
                        if da.org_unit_id:
                            da_dom.append(("org_unit_id", "=", da.org_unit_id.id))
                        elif da.org_level == "branch":
                            da_dom.append(("org_unit_type", "in", ("branch", "sub_branch")))
                        elif da.org_level == "district":
                            da_dom.append(("org_unit_type", "in", ("district_office", "regional_office")))
                        elif da.org_level in ("head_office", "ho"):
                            da_dom.append(("org_unit_type", "=", "head_office"))
                        if not da_dom:
                            role_domains.append([(1, "=", 1)])
                        elif len(da_dom) == 1:
                            role_domains.append(da_dom)
                        else:
                            role_domains.append(["&"] + da_dom)
                except Exception as e:
                    _logger.warning("Error evaluating dynamic privilege search domains: %s", e)

            if role_domains:

                combined_role_domain = Domain.OR(role_domains)

                domain = Domain.AND([domain, combined_role_domain])

        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    # ------------------------------------------------------------------

    # Workflow methods

    # ------------------------------------------------------------------

    def _get_duplicate_domain(self):

        self.ensure_one()

        return super()._get_duplicate_domain() + [
            ("category", "=", self.category),
            ("is_consolidated_ho_plan", "=", bool(self.is_consolidated_ho_plan)),
            ("is_consolidated_district_plan", "=", bool(self.is_consolidated_district_plan)),
            ("active", "=", True),
        ]

    def _allow_negative_targets(self):

        return any(rec.category in ("deposit",) or (rec.category == "customer_base" and rec.base_type == "dormant_reduction") for rec in self)

    def _protected_write_fields(self):

        protected = list(MONTH_FIELDS)

        if any(c in ITEMIZED_CATEGORIES for c in self.mapped("category") if c):

            protected.append("line_ids")

        return protected

    def _ident_fields(self):

        cat = self.category if len(self) == 1 else (self.mapped("category")[0] if self else "deposit")

        return {

            "deposit": ["deposit_type_id", "plan_category"],

            "customer_base": ["customer_type_id", "deposit_type_id", "base_type"],

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

        org_unit = False

        # 1. User's own default operating unit (primary work unit assigned to user login)

        if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:

            org_unit = user.default_operating_unit_id

        # 2. Employee's own directly-assigned operating unit

        elif hasattr(user, "employee_id") and user.employee_id:

            emp = user.employee_id.sudo()

            if hasattr(emp, "operating_unit_id") and emp.operating_unit_id:

                org_unit = emp.operating_unit_id

            elif hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id:

                org_unit = emp.default_operating_unit_id

        # 3. First entry from the access-permission list (may be shared across HO users)

        if not org_unit:

            unit_ids = user._pbms_operating_unit_ids()

            if unit_ids:

                org_unit = self.env["operating.unit"].browse(unit_ids[0])

        # 4. Last resort: any unit

        if not org_unit:

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

                        'title': _('FY(the Planning year) Not Open for Input'),

                        'message': _(

                            "Planning cycle '%(name)s' is currently '%(state)s' and is not open for unit input. "

                            "Operating unit users (Branch & Head Office) cannot input or submit plan data until SPPMD officially opens the cycle for unit input."

                        ) % {'name': pending_cycle.name, 'state': state_label},

                        'type': 'warning',

                        'sticky': True,

                    }

                }

            return {

                'type': 'ir.actions.client',

                'tag': 'display_notification',

                'params': {

                    'title': _('No FY(the Planning year) Open'),

                    'message': _('There is currently no active planning cycle open for plan and budget input.'),

                    'type': 'warning',

                    'sticky': False,

                }

            }

        plan = False

        if org_unit and cycle:

            Config = self.env.get("pbms.planning.config")

            target_categories = [c for c in ITEMIZED_CATEGORIES if (Config is None or Config.is_category_enabled(c, org_unit))]

            if not target_categories:

                target_categories = ["general_expense", "manpower", "fixed_asset"]

            default_cat = target_categories[0]

            existing_plans = self.sudo().search([

                ("org_unit_id", "=", org_unit.id),

                ("cycle_id", "=", cycle.id),

                ("is_consolidated_ho_plan", "=", False),

                ("is_consolidated_district_plan", "=", False),

                ("active", "=", True),

            ], order="id asc")

            # Clean up / archive any active plans that belong to a disabled category

            MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"}

            for ep in existing_plans:

                unit_type = ep.org_unit_type or (ep.org_unit_id.work_unit_type if ep.org_unit_id else False)

                is_dist_or_ho = unit_type in ("district_office", "head_office", "regional_office")

                # District/HO overview plans for mobilization categories are valid consolidation plans and must not be archived

                if is_dist_or_ho and ep.category in MOBILIZATION_CATS:

                    continue

                # Never archive plans that are already submitted, endorsed, or approved

                if ep.state not in ("draft", "returned", "info_requested"):

                    continue

                is_disabled = (Config is not None and not Config.is_category_enabled(ep.category, org_unit))
                if is_disabled:
                    has_ep_data = bool(ep.line_ids) or any(getattr(ep, m, 0.0) for m in MONTH_FIELDS) or ((getattr(ep, "annual_total", 0.0) or 0.0) > 0.0)
                    if not has_ep_data:
                        try:
                            ep.sudo().with_context(bypass_plan_lock=True).unlink()
                        except Exception:
                            ep.sudo().with_context(bypass_plan_lock=True).write({"active": False})
                    else:
                        ep.sudo().with_context(bypass_plan_lock=True).write({"category": default_cat})

            all_unit_plans = self.sudo().search([

                ("org_unit_id", "=", org_unit.id),

                ("cycle_id", "=", cycle.id),

                ("is_consolidated_ho_plan", "=", False),

                ("is_consolidated_district_plan", "=", False),

                ("active", "=", True),

            ], order="id asc")

            # Re-fetch active plans that are actually enabled in configuration

            enabled_plans = all_unit_plans.filtered(lambda p: p.category in target_categories)

            # Smart Plan Selection:

            # 1. Prefer default_category from context if valid and enabled

            ctx_cat = self.env.context.get("default_category")

            if ctx_cat and ctx_cat in target_categories:

                for p in enabled_plans:

                    if p.category == ctx_cat:

                        plan = p

                        break

            # 2. Prefer an editable draft/returned plan matching default_cat

            if not plan:

                for p in enabled_plans:

                    if p.category == default_cat and p.state in PBMS_BRANCH_EDITABLE_STATES:

                        plan = p

                        break

            # 3. Prefer ANY editable draft/returned plan for this unit

            if not plan:

                for p in enabled_plans:

                    if p.state in PBMS_BRANCH_EDITABLE_STATES:

                        plan = p

                        break

            # 4. Fallback: matching default_cat or first enabled plan

            if not plan:

                for p in enabled_plans:

                    if p.category == default_cat:

                        plan = p

                        break

            if not plan and enabled_plans:

                plan = enabled_plans[0]

            # 5. Fallback: if all target plans are submitted or existing, open the existing plan safely

            if not plan and all_unit_plans:

                resource_plans = all_unit_plans.filtered(lambda p: p.category in target_categories)

                plan = resource_plans[0] if resource_plans else False

            if not plan:

                plan = self.sudo().with_context(bypass_plan_lock=True).create({

                    "org_unit_id": org_unit.id,

                    "cycle_id": cycle.id,

                    "company_id": org_unit.company_id.id if hasattr(org_unit, "company_id") and org_unit.company_id else self.env.company.id,

                    "category": default_cat,

                    "is_consolidated_ho_plan": False,

                    "is_consolidated_district_plan": False,

                    "state": "draft",

                })

            else:

                rec_real_id = plan._origin.id if isinstance(plan._origin.id, int) else (plan.id if isinstance(plan.id, int) else False)

                if rec_real_id and plan.state in PBMS_BRANCH_EDITABLE_STATES:

                    sibling_lines = self.env["pbms.plan.category.line"].sudo().search([

                        ("plan_id.org_unit_id", "=", org_unit.id),

                        ("plan_id.cycle_id", "=", cycle.id),

                        ("plan_id.is_consolidated_district_plan", "=", bool(plan.is_consolidated_district_plan)),

                        ("plan_id.is_consolidated_ho_plan", "=", bool(plan.is_consolidated_ho_plan)),

                        ("plan_id.state", "in", list(PBMS_BRANCH_EDITABLE_STATES)),

                        ("plan_id", "!=", rec_real_id),

                    ])

                    if sibling_lines:

                        sibling_lines.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": rec_real_id})

                    # Archive any other empty draft cards for this unit & cycle so they don't collide on save

                    other_drafts = self.sudo().search([

                        ("org_unit_id", "=", org_unit.id),

                        ("cycle_id", "=", cycle.id),

                        ("is_consolidated_district_plan", "=", bool(plan.is_consolidated_district_plan)),

                        ("is_consolidated_ho_plan", "=", bool(plan.is_consolidated_ho_plan)),

                        ("state", "=", "draft"),

                        ("active", "=", True),

                        ("id", "!=", rec_real_id),

                    ])

                    for od in other_drafts:

                        is_dup_same_cat = (od.category == plan.category)

                        is_disabled = (Config is not None and not Config.is_category_enabled(od.category, org_unit))

                        if is_dup_same_cat or is_disabled:

                            has_od_data = bool(od.line_ids) or any(getattr(od, m, 0.0) for m in MONTH_FIELDS) or ((getattr(od, "annual_total", 0.0) or 0.0) > 0.0)

                            if not has_od_data:

                                od.with_context(bypass_plan_lock=True).write({"active": False})

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

    @api.model

    def get_view(self, view_id=None, view_type='form', **options):

        """Dynamically serve category-specific list view when requested for a category context."""

        if not view_id and view_type == 'list':

            cat = self.env.context.get('default_category')

            if cat:

                cat_list_view_map = {

                    'fixed_asset': 'bunna_pbms.view_pbms_planning_category_list_fixed_asset',

                    'manpower': 'bunna_pbms.view_pbms_planning_category_list_manpower',

                    'general_expense': 'bunna_pbms.view_pbms_planning_category_list_expense',

                    'deposit': 'bunna_pbms.view_pbms_planning_category_list_retail',

                    'customer_base': 'bunna_pbms.view_pbms_planning_category_list_retail',

                    'loan_disbursement_collection': 'bunna_pbms.view_pbms_planning_category_list_retail',

                    'loan_outstanding': 'bunna_pbms.view_pbms_planning_category_list_retail',

                    'fx': 'bunna_pbms.view_pbms_planning_category_list_fx',

                    'digital_banking': 'bunna_pbms.view_pbms_planning_category_list_digital',

                }

                view_name = cat_list_view_map.get(cat)

                if view_name:

                    view = self.env.ref(view_name, raise_if_not_found=False)

                    if view:

                        view_id = view.id

        return super().get_view(view_id=view_id, view_type=view_type, **options)

    def get_formview_id(self, access_uid=None):

        """Return category-specific form view which sets the matching category tab as default."""

        is_req = self.is_planning_request or bool(self.env.context.get("is_planning_request"))

        if is_req:

            base_view = self.env.ref("bunna_pbms.view_pbms_planning_request_form", raise_if_not_found=False) or self.env.ref("bunna_pbms.view_pbms_planning_category_form", raise_if_not_found=False)

            if base_view:

                return base_view.id

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

    CATEGORY_SUMMARY_FIELD_MAP = {
        "deposit": [
            "deposit_line_count", "deposit_proposed_total", "deposit_approved_total",
            "deposit_annual_total", "deposit_q1_total", "deposit_q2_total",
            "deposit_q3_total", "deposit_q4_total",
        ],
        "customer_base": [
            "customer_base_line_count", "customer_base_proposed_total", "customer_base_approved_total",
            "customer_base_annual_total", "customer_base_q1_total", "customer_base_q2_total",
            "customer_base_q3_total", "customer_base_q4_total",
        ],
        "fx": [
            "fx_line_count", "fx_proposed_total", "fx_approved_total",
            "fx_annual_total", "fx_q1_total", "fx_q2_total",
            "fx_q3_total", "fx_q4_total",
        ],
        "digital_banking": [
            "digital_banking_line_count", "digital_banking_proposed_total", "digital_banking_approved_total",
            "digital_banking_annual_total", "digital_banking_q1_total", "digital_banking_q2_total",
            "digital_banking_q3_total", "digital_banking_q4_total",
        ],
        "loan_disbursement_collection": [
            "loan_disbursement_line_count", "loan_disbursement_proposed_total", "loan_disbursement_approved_total",
            "loan_disbursement_annual_total", "loan_disbursement_q1_total", "loan_disbursement_q2_total",
            "loan_disbursement_q3_total", "loan_disbursement_q4_total",
        ],
        "loan_outstanding": [
            "loan_outstanding_line_count", "loan_outstanding_proposed_total", "loan_outstanding_approved_total",
            "loan_outstanding_annual_total", "loan_outstanding_q1_total", "loan_outstanding_q2_total",
            "loan_outstanding_q3_total", "loan_outstanding_q4_total",
        ],
        "general_expense": [
            "expense_line_count", "expense_proposed_total", "expense_approved_total",
            "expense_annual_total", "expense_q1_total", "expense_q2_total",
            "expense_q3_total", "expense_q4_total",
        ],
        "manpower": [
            "manpower_line_count", "current_staff_salary_budget", "new_planned_salary_budget",
            "total_operating_unit_manpower_budget", "q1_total_cost", "q2_total_cost",
            "q3_total_cost", "q4_total_cost", "manpower_total_headcount",
            "manpower_approved_headcount", "manpower_total_promotion", "manpower_total_transfer",
            "manpower_total_lateral", "manpower_total_external", "manpower_total_fulfillment",
            "manpower_fulfillment_balance",
        ],
        "fixed_asset": [
            "fixed_asset_line_count", "fixed_asset_total_quantity", "total_fixed_asset_cost",
            "fixed_asset_approved_total", "fixed_asset_approved_quantity",
            "fa_q1_total_cost", "fa_q2_total_cost", "fa_q3_total_cost", "fa_q4_total_cost",
            "fa_q1", "fa_q2", "fa_q3", "fa_q4",
        ],
    }

    def read(self, fields=None, load="_classic_read"):
        """Fast read without synchronous database mutation."""

        res = super().read(fields=fields, load=load)

        cat_field_map = {

            "deposit_line_ids": "deposit",

            "customer_base_line_ids": "customer_base",

            "fx_line_ids": "fx",

            "digital_banking_line_ids": "digital_banking",

            "loan_disbursement_line_ids": "loan_disbursement_collection",

            "loan_outstanding_line_ids": "loan_outstanding",

            "expense_line_ids": "general_expense",

            "manpower_line_ids": "manpower",

            "fixed_asset_line_ids": "fixed_asset",

            "credit_portfolio_line_ids": "credit_portfolio",

            "initiative_budget_line_ids": "initiative_budget",

        }

        # Check fallback lines if category line fields or existing workforce fields are requested

        requested_cat_fields = [f for f in cat_field_map if (fields is None or f in fields)]

        check_existing_emp = (fields is None or "existing_employee_line_ids" in fields)

        check_existing_summary = (fields is None or "existing_manpower_summary_ids" in fields)

        check_workforce_doc = (fields is None or "workforce_document" in fields or "workforce_document_filename" in fields)

        all_summary_fields = [f for sfs in self.CATEGORY_SUMMARY_FIELD_MAP.values() for f in sfs]

        check_summary = (fields is None or any(f in fields for f in all_summary_fields))

        if requested_cat_fields or check_existing_emp or check_existing_summary or check_workforce_doc or check_summary:

            is_req_ctx = bool(self.env.context.get("is_planning_request"))

            for rec, r_dict in zip(self, res):

                if not rec.org_unit_id or not rec.cycle_id:

                    continue

                is_req = is_req_ctx or getattr(rec, "is_planning_request", False)

                if check_workforce_doc and not r_dict.get("workforce_document"):

                    try:

                        donor = rec if rec.workforce_document_base64 else self.sudo().search([

                            ("org_unit_id", "=", rec.org_unit_id.id),

                            ("cycle_id", "=", rec.cycle_id.id),

                            ("active", "=", True),

                            "|",

                            ("workforce_document", "!=", False),

                            ("workforce_document_base64", "!=", False),

                        ], limit=1)

                        if donor:

                            donor_read = super(PbmsPlanningCategory, donor).read(["workforce_document", "workforce_document_filename"], load=load)

                            if donor_read:

                                if fields is None or "workforce_document" in fields:

                                    r_dict["workforce_document"] = donor_read[0].get("workforce_document") or donor.workforce_document_base64

                                if fields is None or "workforce_document_filename" in fields:

                                    r_dict["workforce_document_filename"] = donor_read[0].get("workforce_document_filename") or donor.workforce_document_filename or "Workforce_Document"

                    except Exception:

                        pass

                target_fnames = [

                    f for f in requested_cat_fields

                    if (is_req or not rec.category or cat_field_map[f] == rec.category) and f in r_dict and not r_dict[f]

                ]

                if target_fnames:

                    target_cats = [cat_field_map[f] for f in target_fnames]

                    try:

                        all_sibling_lines = self.env["pbms.plan.category.line"].search([

                            ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                            ("plan_id.cycle_id", "=", rec.cycle_id.id),

                            ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                            ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                            ("plan_id.active", "=", True),

                            ("line_type", "in", target_cats),

                        ])

                        if all_sibling_lines:

                            lines_by_cat = {}

                            for l in all_sibling_lines:

                                lines_by_cat.setdefault(l.line_type, []).append(l.id)

                            for fname in target_fnames:

                                cat_ids = lines_by_cat.get(cat_field_map[fname])

                                if cat_ids:

                                    r_dict[fname] = cat_ids

                    except Exception:

                        pass

                if check_existing_emp and (is_req or not rec.category or rec.category == "manpower") and "existing_employee_line_ids" in r_dict and not r_dict["existing_employee_line_ids"]:

                    try:

                        emp_lines = self.env["pbms.existing.employee.line"].search([

                            ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                            ("plan_id.cycle_id", "=", rec.cycle_id.id),

                            ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                            ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                            ("plan_id.active", "=", True),

                        ])

                        if emp_lines:

                            r_dict["existing_employee_line_ids"] = emp_lines.ids

                    except Exception:

                        pass

                if check_existing_summary and (is_req or not rec.category or rec.category == "manpower") and "existing_manpower_summary_ids" in r_dict and not r_dict["existing_manpower_summary_ids"]:

                    try:

                        sum_lines = self.env["pbms.existing.manpower.summary"].search([

                            ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                            ("plan_id.cycle_id", "=", rec.cycle_id.id),

                            ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                            ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                            ("plan_id.active", "=", True),

                        ])

                        if sum_lines:

                            r_dict["existing_manpower_summary_ids"] = sum_lines.ids

                    except Exception:

                        pass

                if check_summary and (is_req or not rec.category):

                    try:

                        sibling_plans = self.sudo().search([

                            ("org_unit_id", "=", rec.org_unit_id.id),

                            ("cycle_id", "=", rec.cycle_id.id),

                            ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                            ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                            ("active", "=", True),

                        ])

                        sibling_by_cat = {s.category: s for s in sibling_plans}

                        for cat, s_fields in self.CATEGORY_SUMMARY_FIELD_MAP.items():

                            req_s_fields = [f for f in s_fields if (fields is None or f in fields)]

                            if not req_s_fields:

                                continue

                            if rec.category == cat and any(r_dict.get(f) for f in req_s_fields):

                                continue

                            s_plan = sibling_by_cat.get(cat)

                            if s_plan and s_plan.id != rec.id:

                                s_read = s_plan.read(req_s_fields, load=load)[0]

                                for f in req_s_fields:

                                    if s_read.get(f) is not None:

                                        r_dict[f] = s_read[f]

                            elif not s_plan:

                                s_lines = self.env["pbms.plan.category.line"].search([

                                    ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                                    ("plan_id.cycle_id", "=", rec.cycle_id.id),

                                    ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                                    ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                                    ("plan_id.active", "=", True),

                                    ("line_type", "=", cat),

                                ])

                                if s_lines:

                                    if cat in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding", "general_expense"):

                                        pfx = "expense" if cat == "general_expense" else cat

                                        if f"{pfx}_line_count" in req_s_fields:

                                            r_dict[f"{pfx}_line_count"] = len(s_lines)

                                        if f"{pfx}_annual_total" in req_s_fields:

                                            r_dict[f"{pfx}_annual_total"] = sum(s_lines.mapped("annual_total"))

                                        if f"{pfx}_proposed_total" in req_s_fields:

                                            r_dict[f"{pfx}_proposed_total"] = sum(s_lines.mapped("proposed_annual_total")) or sum(s_lines.mapped("annual_total"))

                                        if f"{pfx}_approved_total" in req_s_fields:

                                            r_dict[f"{pfx}_approved_total"] = sum(s_lines.mapped("approved_annual_total"))

                                        if f"{pfx}_q1_total" in req_s_fields:

                                            r_dict[f"{pfx}_q1_total"] = sum(s_lines.mapped("quarter1_total"))

                                        if f"{pfx}_q2_total" in req_s_fields:

                                            r_dict[f"{pfx}_q2_total"] = sum(s_lines.mapped("quarter2_total"))

                                        if f"{pfx}_q3_total" in req_s_fields:

                                            r_dict[f"{pfx}_q3_total"] = sum(s_lines.mapped("quarter3_total"))

                                        if f"{pfx}_q4_total" in req_s_fields:

                                            r_dict[f"{pfx}_q4_total"] = sum(s_lines.mapped("quarter4_total"))

                                    elif cat == "fixed_asset":

                                        if "fixed_asset_line_count" in req_s_fields:

                                            r_dict["fixed_asset_line_count"] = len(s_lines)

                                        if "fixed_asset_total_quantity" in req_s_fields:

                                            r_dict["fixed_asset_total_quantity"] = sum(s_lines.mapped("quantity"))

                                        if "total_fixed_asset_cost" in req_s_fields:

                                            r_dict["total_fixed_asset_cost"] = sum(s_lines.mapped("fa_annual_total_cost"))

                                        if "fa_q1_total_cost" in req_s_fields:

                                            r_dict["fa_q1_total_cost"] = sum(s_lines.mapped("fa_q1_cost"))

                                        if "fa_q2_total_cost" in req_s_fields:

                                            r_dict["fa_q2_total_cost"] = sum(s_lines.mapped("fa_q2_cost"))

                                        if "fa_q3_total_cost" in req_s_fields:

                                            r_dict["fa_q3_total_cost"] = sum(s_lines.mapped("fa_q3_cost"))

                                        if "fa_q4_total_cost" in req_s_fields:

                                            r_dict["fa_q4_total_cost"] = sum(s_lines.mapped("fa_q4_cost"))

                                        if "fa_q1" in req_s_fields:

                                            r_dict["fa_q1"] = int(sum(s_lines.mapped("fa_q1")) or 0)

                                        if "fa_q2" in req_s_fields:

                                            r_dict["fa_q2"] = int(sum(s_lines.mapped("fa_q2")) or 0)

                                        if "fa_q3" in req_s_fields:

                                            r_dict["fa_q3"] = int(sum(s_lines.mapped("fa_q3")) or 0)

                                        if "fa_q4" in req_s_fields:

                                            r_dict["fa_q4"] = int(sum(s_lines.mapped("fa_q4")) or 0)

                                    elif cat == "manpower":

                                        if "manpower_line_count" in req_s_fields:

                                            r_dict["manpower_line_count"] = len(s_lines)

                                        if "manpower_total_headcount" in req_s_fields:

                                            r_dict["manpower_total_headcount"] = int(sum(s_lines.mapped("quantity")) or sum(s_lines.mapped("annual_total")) or 0)

                                        if "q1_total_cost" in req_s_fields:

                                            r_dict["q1_total_cost"] = sum(s_lines.mapped("q1_cost"))

                                        if "q2_total_cost" in req_s_fields:

                                            r_dict["q2_total_cost"] = sum(s_lines.mapped("q2_cost"))

                                        if "q3_total_cost" in req_s_fields:

                                            r_dict["q3_total_cost"] = sum(s_lines.mapped("q3_cost"))

                                        if "q4_total_cost" in req_s_fields:

                                            r_dict["q4_total_cost"] = sum(s_lines.mapped("q4_cost"))

                    except Exception:

                        pass

        return res

    @api.readonly

    def web_read(self, specification: dict[str, dict]) -> list[dict]:
        """Ensure Odoo 19 web_read populates sibling category lines across tabs in Planning Request."""

        values_list = super().web_read(specification)

        if not values_list or not specification:

            return values_list

        cat_field_map = {

            "deposit_line_ids": "deposit",

            "customer_base_line_ids": "customer_base",

            "fx_line_ids": "fx",

            "digital_banking_line_ids": "digital_banking",

            "loan_disbursement_line_ids": "loan_disbursement_collection",

            "loan_outstanding_line_ids": "loan_outstanding",

            "expense_line_ids": "general_expense",

            "manpower_line_ids": "manpower",

            "fixed_asset_line_ids": "fixed_asset",

            "credit_portfolio_line_ids": "credit_portfolio",

            "initiative_budget_line_ids": "initiative_budget",

        }

        requested_cat_fields = [f for f in cat_field_map if f in specification]

        check_existing_emp = "existing_employee_line_ids" in specification

        check_existing_summary = "existing_manpower_summary_ids" in specification

        check_workforce_doc = "workforce_document" in specification or "workforce_document_filename" in specification

        all_summary_fields = [f for sfs in self.CATEGORY_SUMMARY_FIELD_MAP.values() for f in sfs]

        check_summary = any(f in specification for f in all_summary_fields)

        if not (requested_cat_fields or check_existing_emp or check_existing_summary or check_workforce_doc or check_summary):

            return values_list

        is_req_ctx = bool(self.env.context.get("is_planning_request"))

        for rec, values in zip(self, values_list):

            if not rec.org_unit_id or not rec.cycle_id:

                continue

            is_req = is_req_ctx or getattr(rec, "is_planning_request", False)

            if check_workforce_doc and not values.get("workforce_document"):

                try:

                    donor = rec if rec.workforce_document_base64 else self.sudo().search([

                        ("org_unit_id", "=", rec.org_unit_id.id),

                        ("cycle_id", "=", rec.cycle_id.id),

                        ("active", "=", True),

                        "|",

                        ("workforce_document", "!=", False),

                        ("workforce_document_base64", "!=", False),

                    ], limit=1)

                    if donor:

                        doc_spec = {k: specification[k] for k in ("workforce_document", "workforce_document_filename") if k in specification}

                        donor_vals = super(PbmsPlanningCategory, donor).web_read(doc_spec)

                        if donor_vals:

                            if "workforce_document" in specification:

                                values["workforce_document"] = donor_vals[0].get("workforce_document") or donor.workforce_document_base64

                            if "workforce_document_filename" in specification:

                                values["workforce_document_filename"] = donor_vals[0].get("workforce_document_filename") or donor.workforce_document_filename or "Workforce_Document"

                except Exception:

                    pass

            target_fnames = [

                f for f in requested_cat_fields

                if (is_req or not rec.category or cat_field_map[f] == rec.category) and not rec[f]

            ]

            if target_fnames:

                target_cats = [cat_field_map[f] for f in target_fnames]

                try:

                    all_sibling_lines = self.env["pbms.plan.category.line"].search([

                        ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                        ("plan_id.cycle_id", "=", rec.cycle_id.id),

                        ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                        ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                        ("plan_id.active", "=", True),

                        ("line_type", "in", target_cats),

                    ])

                    if all_sibling_lines:

                        for fname in target_fnames:

                            cat = cat_field_map[fname]

                            sibling_lines = all_sibling_lines.filtered(lambda l, c=cat: l.line_type == c)

                            if sibling_lines:

                                field_spec = specification.get(fname) or {}

                                if "context" in field_spec:

                                    sibling_lines = sibling_lines.with_context(**field_spec["context"])

                                if "fields" in field_spec:

                                    limit = field_spec.get("limit")

                                    lines_to_read = sibling_lines[:limit] if limit is not None else sibling_lines

                                    values[fname] = lines_to_read.web_read(field_spec["fields"])

                                else:

                                    values[fname] = sibling_lines.ids

                except Exception:

                    pass

            if check_existing_emp and (is_req or not rec.category or rec.category == "manpower") and not rec.existing_employee_line_ids:

                try:

                    emp_lines = self.env["pbms.existing.employee.line"].search([

                        ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                        ("plan_id.cycle_id", "=", rec.cycle_id.id),

                        ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                        ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                        ("plan_id.active", "=", True),

                    ])

                    if emp_lines:

                        field_spec = specification.get("existing_employee_line_ids") or {}

                        if "fields" in field_spec:

                            limit = field_spec.get("limit")

                            lines_to_read = emp_lines[:limit] if limit is not None else emp_lines

                            values["existing_employee_line_ids"] = lines_to_read.web_read(field_spec["fields"])

                        else:

                            values["existing_employee_line_ids"] = emp_lines.ids

                except Exception:

                    pass

            if check_existing_summary and (is_req or not rec.category or rec.category == "manpower") and not rec.existing_manpower_summary_ids:

                try:

                    sum_lines = self.env["pbms.existing.manpower.summary"].search([

                        ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                        ("plan_id.cycle_id", "=", rec.cycle_id.id),

                        ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                        ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                        ("plan_id.active", "=", True),

                    ])

                    if sum_lines:

                        field_spec = specification.get("existing_manpower_summary_ids") or {}

                        if "fields" in field_spec:

                            limit = field_spec.get("limit")

                            lines_to_read = sum_lines[:limit] if limit is not None else sum_lines

                            values["existing_manpower_summary_ids"] = lines_to_read.web_read(field_spec["fields"])

                        else:

                            values["existing_manpower_summary_ids"] = sum_lines.ids

                except Exception:

                    pass

            if check_summary and (is_req or not rec.category):

                try:

                    sibling_plans = self.sudo().search([

                        ("org_unit_id", "=", rec.org_unit_id.id),

                        ("cycle_id", "=", rec.cycle_id.id),

                        ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                        ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                        ("active", "=", True),

                    ])

                    sibling_by_cat = {s.category: s for s in sibling_plans}

                    for cat, s_fields in self.CATEGORY_SUMMARY_FIELD_MAP.items():

                        req_s_fields = [f for f in s_fields if f in specification]

                        if not req_s_fields:

                            continue

                        if rec.category == cat and any(values.get(f) for f in req_s_fields):

                            continue

                        s_plan = sibling_by_cat.get(cat)

                        if s_plan and s_plan.id != rec.id:

                            s_vals = s_plan.read(req_s_fields)[0]

                            for f in req_s_fields:

                                if s_vals.get(f) is not None:

                                    values[f] = s_vals[f]

                        elif not s_plan:

                            s_lines = self.env["pbms.plan.category.line"].search([

                                ("plan_id.org_unit_id", "=", rec.org_unit_id.id),

                                ("plan_id.cycle_id", "=", rec.cycle_id.id),

                                ("plan_id.is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                                ("plan_id.is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                                ("plan_id.active", "=", True),

                                ("line_type", "=", cat),

                            ])

                            if s_lines:

                                if cat in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding", "general_expense"):

                                    pfx = "expense" if cat == "general_expense" else cat

                                    if f"{pfx}_line_count" in req_s_fields:

                                        values[f"{pfx}_line_count"] = len(s_lines)

                                    if f"{pfx}_annual_total" in req_s_fields:

                                        values[f"{pfx}_annual_total"] = sum(s_lines.mapped("annual_total"))

                                    if f"{pfx}_proposed_total" in req_s_fields:

                                        values[f"{pfx}_proposed_total"] = sum(s_lines.mapped("proposed_annual_total")) or sum(s_lines.mapped("annual_total"))

                                    if f"{pfx}_approved_total" in req_s_fields:

                                        values[f"{pfx}_approved_total"] = sum(s_lines.mapped("approved_annual_total"))

                                    if f"{pfx}_q1_total" in req_s_fields:

                                        values[f"{pfx}_q1_total"] = sum(s_lines.mapped("quarter1_total"))

                                    if f"{pfx}_q2_total" in req_s_fields:

                                        values[f"{pfx}_q2_total"] = sum(s_lines.mapped("quarter2_total"))

                                    if f"{pfx}_q3_total" in req_s_fields:

                                        values[f"{pfx}_q3_total"] = sum(s_lines.mapped("quarter3_total"))

                                    if f"{pfx}_q4_total" in req_s_fields:

                                        values[f"{pfx}_q4_total"] = sum(s_lines.mapped("quarter4_total"))

                                elif cat == "fixed_asset":

                                    if "fixed_asset_line_count" in req_s_fields:

                                        values["fixed_asset_line_count"] = len(s_lines)

                                    if "fixed_asset_total_quantity" in req_s_fields:

                                        values["fixed_asset_total_quantity"] = sum(s_lines.mapped("quantity"))

                                    if "total_fixed_asset_cost" in req_s_fields:

                                        values["total_fixed_asset_cost"] = sum(s_lines.mapped("fa_annual_total_cost"))

                                    if "fa_q1_total_cost" in req_s_fields:

                                        values["fa_q1_total_cost"] = sum(s_lines.mapped("fa_q1_cost"))

                                    if "fa_q2_total_cost" in req_s_fields:

                                        values["fa_q2_total_cost"] = sum(s_lines.mapped("fa_q2_cost"))

                                    if "fa_q3_total_cost" in req_s_fields:

                                        values["fa_q3_total_cost"] = sum(s_lines.mapped("fa_q3_cost"))

                                    if "fa_q4_total_cost" in req_s_fields:

                                        values["fa_q4_total_cost"] = sum(s_lines.mapped("fa_q4_cost"))

                                    if "fa_q1" in req_s_fields:

                                        values["fa_q1"] = int(sum(s_lines.mapped("fa_q1")) or 0)

                                    if "fa_q2" in req_s_fields:

                                        values["fa_q2"] = int(sum(s_lines.mapped("fa_q2")) or 0)

                                    if "fa_q3" in req_s_fields:

                                        values["fa_q3"] = int(sum(s_lines.mapped("fa_q3")) or 0)

                                    if "fa_q4" in req_s_fields:

                                        values["fa_q4"] = int(sum(s_lines.mapped("fa_q4")) or 0)

                                elif cat == "manpower":

                                    if "manpower_line_count" in req_s_fields:

                                        values["manpower_line_count"] = len(s_lines)

                                    if "manpower_total_headcount" in req_s_fields:

                                        values["manpower_total_headcount"] = int(sum(s_lines.mapped("quantity")) or sum(s_lines.mapped("annual_total")) or 0)

                                    if "q1_total_cost" in req_s_fields:

                                        values["q1_total_cost"] = sum(s_lines.mapped("q1_cost"))

                                    if "q2_total_cost" in req_s_fields:

                                        values["q2_total_cost"] = sum(s_lines.mapped("q2_cost"))

                                    if "q3_total_cost" in req_s_fields:

                                        values["q3_total_cost"] = sum(s_lines.mapped("q3_cost"))

                                    if "q4_total_cost" in req_s_fields:

                                        values["q4_total_cost"] = sum(s_lines.mapped("q4_cost"))

                except Exception:

                    pass

        return values_list

    def get_formview_action(self, access_uid=None):

        """Return action to open the exact plan form clicked."""

        self.ensure_one()

        Config = self.env.get("pbms.planning.config")

        default_cat = Config.get_default_category_for_unit(self.org_unit_id) if (Config is not None and self.org_unit_id) else "deposit"

        cat = self.category or self.env.context.get("default_category") or default_cat

        view_id = self.get_formview_id(access_uid=access_uid)

        self_real_id = self._origin.id if isinstance(self._origin.id, int) else (self.id if isinstance(self.id, int) else False)

        if self_real_id and self.org_unit_id and self.cycle_id and cat:

            detached = self.env["pbms.plan.category.line"].sudo().search([

                ("plan_id.org_unit_id", "=", self.org_unit_id.id),

                ("plan_id.cycle_id", "=", self.cycle_id.id),

                ("plan_id.is_consolidated_district_plan", "=", bool(self.is_consolidated_district_plan)),

                ("plan_id.is_consolidated_ho_plan", "=", bool(self.is_consolidated_ho_plan)),

                ("line_type", "=", cat),

                ("plan_id", "!=", self_real_id),

            ])

            if detached:

                detached = detached.filtered(lambda l: getattr(l.plan_id, "is_planning_request", False) or l.plan_id.category != cat)

                if detached:

                    detached.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"plan_id": self_real_id})

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

        """Open the Excel import wizard pre-filled with this plan card's details and currently active tab category."""

        self.ensure_one()

        ctx_cat = (

            self.env.context.get("target_category")

            or self.env.context.get("active_category")

            or self.env.context.get("active_tab_category")

            or self.env.context.get("default_format_type")

            or self.env.context.get("default_category")

            or self.env.context.get("default_line_type")

            or self.category

            or "deposit"

        )

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

                "default_format_type": ctx_cat,

                "target_category": ctx_cat,

                "active_category": ctx_cat,

                "active_tab_category": ctx_cat,

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

            unit_name = unit.display_name if unit else ""

            sol_id = line.sol_id or (unit.sol_id if unit and hasattr(unit, "sol_id") else 0)

            district_name = ""

            if line.district_id:

                district_name = line.district_id.display_name or ""

            elif rec and rec.district_id:

                district_name = rec.district_id.display_name or ""

            elif unit and unit.parent_unit:

                district_name = unit.parent_unit.display_name or ""

            wtype = (unit.work_unit_type if unit else False) or line.org_unit_type or (rec.org_unit_type if rec else "")

            if wtype == "head_office" and not district_name:

                district_name = unit.parent_unit.display_name if unit and unit.parent_unit else "Head Office"

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

            if len(plans) == 1:

                utype = plans[0].org_unit_type

                uname = plans[0].org_unit_id.display_name or ""

                if utype in ("branch", "sub_branch", "service_center"):

                    return uname or "Branch Plan"

                elif utype == "district_office":

                    return uname or "District Office Plan"

                elif utype in ("head_office", "regional_office"):

                    return uname or "Head Office Plan"

            return default_text

        # Export exactly the selected records — no filtering to district/HO only

        target_records = records

        # Check if a specific category was requested via context (e.g. from active tab or button context)

        ctx_category = (

            self.env.context.get("target_category")

            or self.env.context.get("active_category")

            or self.env.context.get("active_tab_category")

            or self.env.context.get("export_category")

            or self.env.context.get("default_category")

        )

        # Group plans by category

        plans_by_cat = {}

        for rec in target_records:

            cat = ctx_category or rec.category or "deposit"

            if cat not in plans_by_cat:

                plans_by_cat[cat] = self.env["pbms.planning.category"]

            plans_by_cat[cat] |= rec

        for cat, cat_plans in plans_by_cat.items():

            if cat == "fixed_asset":

                is_approved_fa = any(p.state == "approved" for p in cat_plans)

                ws = wb.add_worksheet("Fixed Asset (BB-APF-27)")

                ws.freeze_panes(6, 4)

                fa_last_col = 13 if is_approved_fa else 11

                ws.merge_range(0, 0, 0, fa_last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, fa_last_col, "Property and Equipment", fmt_doc_title)

                ws.merge_range(2, 0, 2, fa_last_col, f"For the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, fa_last_col, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                ws.write(4, 0, "BB-APF-27", fmt_form_code)

                headers = [

                    "SOL ID", "Work Unit Name", "Districts", "Broad Category", "Nature of the Request",

                    "Fixed Asset Category*", "Item Description*", "Users Position or Purpose of the Item",

                    "Proposed Plan", "Qty", "Estimated Unit Price", "Estimated Total Price"

                ]

                if is_approved_fa:

                    headers += ["Approved Qty", "Approved Total Price"]

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                row_cur = 6

                seen_line_ids = set()

                for p in cat_plans:

                    lines = p._get_category_lines("fixed_asset") or p.fixed_asset_line_ids or p.line_ids.filtered(lambda l: l.line_type == "fixed_asset")

                    for l in lines:

                        if l.id in seen_line_ids:

                            continue

                        seen_line_ids.add(l.id)

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        nat = "New" if (l.nature or "new") == "new" else "Replacement"

                        cat_name = l.category_id.name or ""

                        item_desc = l.item_description or ""

                        purpose_str = l.purpose.name if l.purpose else (l.other_justification or "")

                        proposed_qty = int(round(l.proposed_plan or l.quantity or 0))

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

                        ws.write(row_cur, 8, proposed_qty, fmt_cell_int)

                        ws.write(row_cur, 9, qty, fmt_cell_int)

                        ws.write(row_cur, 10, unit_price, fmt_cell_num_no_dec)

                        ws.write(row_cur, 11, tot_price, fmt_cell_num_no_dec)

                        if is_approved_fa:

                            appr_qty = int(round(l.approved_annual_total or 0))

                            appr_price = float(l.approved_annual_total or 0.0) * unit_price

                            ws.write(row_cur, 12, appr_qty, fmt_cell_int)

                            ws.write(row_cur, 13, appr_price, fmt_cell_num_no_dec)

                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, 8):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                if row_cur > 6:

                    ws.write_formula(row_cur, 8, f"=SUM(I7:I{row_cur})", fmt_tot_int)

                    ws.write_formula(row_cur, 9, f"=SUM(J7:J{row_cur})", fmt_tot_int)

                    ws.write(row_cur, 10, "", fmt_tot_label)

                    ws.write_formula(row_cur, 11, f"=SUM(L7:L{row_cur})", fmt_tot_num)

                    if is_approved_fa:

                        ws.write_formula(row_cur, 12, f"=SUM(M7:M{row_cur})", fmt_tot_int)

                        ws.write_formula(row_cur, 13, f"=SUM(N7:N{row_cur})", fmt_tot_num)

                else:

                    ws.write(row_cur, 8, 0, fmt_tot_int)

                    ws.write(row_cur, 9, 0, fmt_tot_int)

                    ws.write(row_cur, 10, "", fmt_tot_label)

                    ws.write(row_cur, 11, 0.0, fmt_tot_num)

                    if is_approved_fa:

                        ws.write(row_cur, 12, 0, fmt_tot_int)

                        ws.write(row_cur, 13, 0.0, fmt_tot_num)

                ws.set_column(0, 0, 10)

                ws.set_column(1, 1, 26)

                ws.set_column(2, 2, 18)

                ws.set_column(3, 3, 16)

                ws.set_column(4, 4, 20)

                ws.set_column(5, 5, 26)

                ws.set_column(6, 6, 28)

                ws.set_column(7, 7, 30)

                ws.set_column(8, 8, 14)

                ws.set_column(9, 9, 10)

                ws.set_column(10, 10, 18)

                ws.set_column(11, 11, 20)

                if is_approved_fa:

                    ws.set_column(12, 12, 14)

                    ws.set_column(13, 13, 20)

            elif cat == "general_expense":

                is_approved_ge = any(p.state == "approved" for p in cat_plans)

                ge_last_col = 21 if is_approved_ge else 20

                ws = wb.add_worksheet("Expense (BB-APF-21)")

                ws.freeze_panes(6, 5)

                ws.merge_range(0, 0, 0, ge_last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, ge_last_col, "General Expense Budget", fmt_doc_title)

                ws.merge_range(2, 0, 2, ge_last_col, f"for the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, ge_last_col, get_banner_unit_title(cat_plans, "District and Head Office (HO-DO)"), fmt_work_units_title)

                ws.write(4, 0, "BB-APF-21", fmt_form_code)

                headers = ["Sol ID", "Work Units Name", "Districts Name", "Broad Category", "Description", "Estimate"] + month_headers + ["Annual", "Proposed Plan"]

                if is_approved_ge:

                    headers += ["Approved Plan"]

                headers += ["Remark"]

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                remark_col = 21 if is_approved_ge else 20

                row_cur = 6

                seen_line_ids = set()

                for p in cat_plans:

                    lines = p._get_category_lines("general_expense") or p.expense_line_ids or p.line_ids.filtered(lambda l: l.line_type == "general_expense")

                    for l in lines:

                        if l.id in seen_line_ids:

                            continue

                        seen_line_ids.add(l.id)

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        desc = l.expense_account_id.name or ""

                        ob_val = l.opening_balance or 0.0

                        m_vals = [l.m01 or 0.0, l.m02 or 0.0, l.m03 or 0.0, l.m04 or 0.0, l.m05 or 0.0, l.m06 or 0.0,

                                  l.m07 or 0.0, l.m08 or 0.0, l.m09 or 0.0, l.m10 or 0.0, l.m11 or 0.0, l.m12 or 0.0]

                        ann = l.annual_total or sum(m_vals)

                        prop_ann = l.proposed_annual_total if getattr(l, "proposed_annual_total", False) else (l.annual_total or sum(m_vals))

                        rem = l.other_justification or getattr(l, "reason", "") or ""

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)

                        ws.write(row_cur, 1, unit_name, fmt_cell_text)

                        ws.write(row_cur, 2, district_name, fmt_cell_text)

                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)

                        ws.write(row_cur, 4, desc, fmt_cell_text)

                        ws.write(row_cur, 5, ob_val, fmt_cell_num_acc)

                        for mi, mv in enumerate(m_vals):

                            ws.write(row_cur, 6 + mi, mv, fmt_cell_num_acc)

                        ws.write(row_cur, 18, ann, fmt_tot_num if ann > 0 else fmt_cell_num_acc)

                        ws.write(row_cur, 19, prop_ann, fmt_tot_num if prop_ann > 0 else fmt_cell_num_acc)

                        if is_approved_ge:

                            appr_ann = l.approved_annual_total or 0.0

                            ws.write(row_cur, 20, appr_ann, fmt_tot_num if appr_ann > 0 else fmt_cell_num_acc)

                        ws.write(row_cur, remark_col, rem, fmt_cell_text)

                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, 5):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                if row_cur > 6:

                    for ci in range(5, 20):

                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)

                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                    if is_approved_ge:

                        c_letter = xlsxwriter.utility.xl_col_to_name(20)

                        ws.write_formula(row_cur, 20, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                else:

                    for ci in range(5, 20):

                        ws.write(row_cur, ci, 0.0, fmt_tot_num)

                    if is_approved_ge:

                        ws.write(row_cur, 20, 0.0, fmt_tot_num)

                ws.write(row_cur, remark_col, "", fmt_tot_label)

                ws.set_column(0, 0, 10)

                ws.set_column(1, 1, 24)

                ws.set_column(2, 2, 18)

                ws.set_column(3, 3, 16)

                ws.set_column(4, 4, 26)

                ws.set_column(5, 5, 20)

                for ci in range(6, 18):

                    ws.set_column(ci, ci, 13)

                ws.set_column(18, 18, 16)

                ws.set_column(19, 19, 16)

                if is_approved_ge:

                    ws.set_column(20, 20, 16)

                    ws.set_column(21, 21, 22)

                else:

                    ws.set_column(20, 20, 22)

            elif cat == "manpower":

                is_approved_mp = any(p.state == "approved" for p in cat_plans)

                is_branch_export = any(p.org_unit_type in ("branch", "sub_branch", "service_center") for p in cat_plans)

                can_export_sourcing = bool(self.env.user._pbms_can_view_sourcing() and not is_branch_export)

                ws = wb.add_worksheet("Manpower (BB-APF-19)")

                ws.freeze_panes(6, 4)

                headers = [

                    "SOL ID", "Work Unit Name", "Districts Name", "Broad Category",

                    "Type of Position", "Type of Employment", "Job Title", "Job Grade", "Employee Category",

                    "Authorized Baseline", "Active Staff", "Vacancies",

                    "Qty", "Date Needed", "Reason for the Proposed", "Remarks / Details",

                    "Jul", "Aug", "Sep", "QI",

                    "Oct", "Nov", "Dec", "QII",

                    "Jan", "Feb", "Mar", "QIII",

                    "Apr", "May", "Jun", "QIV",

                    "Annual Headcount",

                    "Proposed Plan",

                ]

                col_approved = None

                if is_approved_mp:

                    col_approved = len(headers)

                    headers.append("Approved Plan")

                col_sourcing_start = None

                if can_export_sourcing:

                    col_sourcing_start = len(headers)

                    headers.extend(["Promotion", "Transfer", "Lateral", "External Vacancy", "Total Sourced"])

                col_base_sal = len(headers)

                col_allowance = col_base_sal + 1

                col_pension = col_base_sal + 2

                col_unit_cost = col_base_sal + 3

                col_annual_cost = col_base_sal + 4

                headers.extend(["Base Salary", "Monthly Allowance", "Pension (11%)", "Annual Unit Cost", "Annual Total Cost"])

                last_col = len(headers) - 1

                ws.merge_range(0, 0, 0, last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, last_col, "Proposed New or Vacant Post", fmt_doc_title)

                ws.merge_range(2, 0, 2, last_col, f"for the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, last_col, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                ws.write(4, 0, "BB-APF-19", fmt_form_code)

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                row_cur = 6

                seen_line_ids = set()

                for p in cat_plans:

                    lines = p._get_category_lines("manpower") or p.manpower_line_ids or p.line_ids.filtered(lambda l: l.line_type == "manpower")

                    for l in lines:

                        if l.id in seen_line_ids:

                            continue

                        seen_line_ids.add(l.id)

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        pos_type = (l.position_type_id.name if l.position_type_id else (dict(l._fields['position_type'].selection).get(l.position_type, 'New Position')))

                        emp_type = (dict(l._fields['employment_type'].selection).get(l.employment_type, l.employment_type.capitalize() if l.employment_type else 'Permanent')) if l.employment_type else 'Permanent'

                        job_title = l.job_id.name if l.job_id else (l.new_job_title or "")

                        grade_str = (l.job_grade_id.grade_code or l.job_grade_id.display_name) if l.job_grade_id else (l.new_job_grade_id.grade_code or l.new_job_grade_id.display_name or l.new_job_grade or "")

                        emp_cat = (l.employee_category_id.display_name if l.employee_category_id else (l.new_employee_category_id.display_name if l.new_employee_category_id else ""))

                        baseline = int(l.existing_establishment or 0)

                        active_staff = int(l.active_staff_count or 0)

                        vacancies = int(l.vacant_count or 0)

                        qty = int(round(l.annual_total or l.quantity or 0))

                        date_str = l.date_needed.strftime('%d-%b-%y') if l.date_needed else f"1-Jul-{y1}"

                        reason_str = (l.justification_category_id.display_name if l.justification_category_id else (getattr(l, "reason", "") or (dict(l._fields['position_type'].selection).get(l.position_type, 'New'))))

                        remarks_str = l.other_justification or ""

                        m_vals = l._manpower_month_values() if hasattr(l, "_manpower_month_values") else {

                            f"m{i:02d}": int(getattr(l, f"m{i:02d}", 0) or getattr(l, f"hc_m{i:02d}", 0) or 0) for i in range(1, 13)

                        }

                        q1 = int(round(l.quarter1_total or l.q1 or (m_vals["m01"] + m_vals["m02"] + m_vals["m03"])))

                        q2 = int(round(l.quarter2_total or l.q2 or (m_vals["m04"] + m_vals["m05"] + m_vals["m06"])))

                        q3 = int(round(l.quarter3_total or l.q3 or (m_vals["m07"] + m_vals["m08"] + m_vals["m09"])))

                        q4 = int(round(l.quarter4_total or l.q4 or (m_vals["m10"] + m_vals["m11"] + m_vals["m12"])))

                        annual_hc = int(round(l.annual_total or l.quantity or (q1 + q2 + q3 + q4)))

                        appr_target = int(round(l.display_approved_annual_total or l.approved_annual_total or 0))

                        prom = int(l.fulfillment_promotion or 0)

                        trans = int(l.fulfillment_transfer or 0)

                        lat = int(l.fulfillment_lateral or 0)

                        ext = int(l.fulfillment_external or 0)

                        tot_sourced = int(l.fulfillment_total or (prom + trans + lat + ext))

                        base_sal = float(l.base_salary or 0.0)

                        pension = float(l.monthly_pension or 0.0)

                        unit_cost = float(l.unit_cost or 0.0)

                        annual_cost = float(l.annual_total_cost or 0.0)

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)

                        ws.write(row_cur, 1, unit_name, fmt_cell_text)

                        ws.write(row_cur, 2, district_name, fmt_cell_text)

                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)

                        ws.write(row_cur, 4, pos_type, fmt_cell_text)

                        ws.write(row_cur, 5, emp_type, fmt_cell_text)

                        ws.write(row_cur, 6, job_title, fmt_cell_text)

                        ws.write(row_cur, 7, grade_str, fmt_cell_text)

                        ws.write(row_cur, 8, emp_cat, fmt_cell_text)

                        ws.write(row_cur, 9, baseline, fmt_cell_int)

                        ws.write(row_cur, 10, active_staff, fmt_cell_int)

                        ws.write(row_cur, 11, vacancies, fmt_cell_int)

                        ws.write(row_cur, 12, qty, fmt_cell_int)

                        ws.write(row_cur, 13, date_str, fmt_cell_date)

                        ws.write(row_cur, 14, reason_str, fmt_cell_text)

                        ws.write(row_cur, 15, remarks_str, fmt_cell_text)

                        ws.write(row_cur, 16, m_vals["m01"], fmt_cell_int)

                        ws.write(row_cur, 17, m_vals["m02"], fmt_cell_int)

                        ws.write(row_cur, 18, m_vals["m03"], fmt_cell_int)

                        ws.write(row_cur, 19, q1, fmt_cell_int)

                        ws.write(row_cur, 20, m_vals["m04"], fmt_cell_int)

                        ws.write(row_cur, 21, m_vals["m05"], fmt_cell_int)

                        ws.write(row_cur, 22, m_vals["m06"], fmt_cell_int)

                        ws.write(row_cur, 23, q2, fmt_cell_int)

                        ws.write(row_cur, 24, m_vals["m07"], fmt_cell_int)

                        ws.write(row_cur, 25, m_vals["m08"], fmt_cell_int)

                        ws.write(row_cur, 26, m_vals["m09"], fmt_cell_int)

                        ws.write(row_cur, 27, q3, fmt_cell_int)

                        ws.write(row_cur, 28, m_vals["m10"], fmt_cell_int)

                        ws.write(row_cur, 29, m_vals["m11"], fmt_cell_int)

                        ws.write(row_cur, 30, m_vals["m12"], fmt_cell_int)

                        ws.write(row_cur, 31, q4, fmt_cell_int)

                        ws.write(row_cur, 32, annual_hc, fmt_cell_int)

                        ws.write(row_cur, 33, int(round(l.proposed_plan or l.quantity or annual_hc or 0)), fmt_cell_int)

                        if col_approved is not None:

                            ws.write(row_cur, col_approved, appr_target, fmt_cell_int)

                        if can_export_sourcing:

                            ws.write(row_cur, col_sourcing_start, prom, fmt_cell_int)

                            ws.write(row_cur, col_sourcing_start + 1, trans, fmt_cell_int)

                            ws.write(row_cur, col_sourcing_start + 2, lat, fmt_cell_int)

                            ws.write(row_cur, col_sourcing_start + 3, ext, fmt_cell_int)

                            ws.write(row_cur, col_sourcing_start + 4, tot_sourced, fmt_cell_int)

                        ws.write(row_cur, col_base_sal, base_sal, fmt_cell_num_acc)

                        ws.write(row_cur, col_allowance, float(l.monthly_allowance or 0.0), fmt_cell_num_acc)

                        ws.write(row_cur, col_pension, pension, fmt_cell_num_acc)

                        ws.write(row_cur, col_unit_cost, unit_cost, fmt_cell_num_acc)

                        ws.write(row_cur, col_annual_cost, annual_cost, fmt_cell_num_acc)

                        row_cur += 1

                # TOTAL ROW

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, len(headers)):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                int_sum_cols = [

                    9, 10, 11,

                    12,

                    16, 17, 18, 19,

                    20, 21, 22, 23,

                    24, 25, 26, 27,

                    28, 29, 30, 31,

                    32, 33,

                ]

                if col_approved is not None:

                    int_sum_cols.append(col_approved)

                if can_export_sourcing:

                    int_sum_cols.extend([

                        col_sourcing_start,

                        col_sourcing_start + 1,

                        col_sourcing_start + 2,

                        col_sourcing_start + 3,

                        col_sourcing_start + 4,

                    ])

                for ci in int_sum_cols:

                    if row_cur > 6:

                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)

                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_int)

                    else:

                        ws.write(row_cur, ci, 0, fmt_tot_int)

                if row_cur > 6:

                    c_letter = xlsxwriter.utility.xl_col_to_name(col_annual_cost)

                    ws.write_formula(row_cur, col_annual_cost, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                else:

                    ws.write(row_cur, col_annual_cost, 0.0, fmt_tot_num)

                col_widths = [

                    10, 24, 18, 16, 18, 18, 28, 12, 18,

                    18, 14, 14, 10, 14, 26, 24,

                    10, 10, 10, 14,

                    10, 10, 10, 14,

                    10, 10, 10, 14,

                    10, 10, 10, 14,

                    18, 16,

                ]

                if col_approved is not None:

                    col_widths.append(16)

                if can_export_sourcing:

                    col_widths.extend([12, 12, 12, 16, 14])

                col_widths.extend([16, 18, 16, 18, 20])

                for ci, w in enumerate(col_widths):

                    ws.set_column(ci, ci, w)

            elif cat == "deposit":
                is_approved_dc = any(p.state == "approved" for p in cat_plans)
                # Determine title based on unit type of the plans being exported
                if len(cat_plans) == 1:
                    utype = cat_plans[0].org_unit_type
                    if utype in ("branch", "sub_branch", "service_center"):
                        group_label = "Branch"
                    elif utype == "district_office":
                        group_label = "District"
                    else:
                        group_label = "Head Office"
                else:
                    group_label = "District"

                title = f"Deposit Plan by {group_label} and Deposit Type for the FY {clean_fy}"
                sheet_name = "Deposit by District"
                ws = wb.add_worksheet(sheet_name)
                ws.freeze_panes(2, 3)
                dc_last_col = 17 if is_approved_dc else 16
                ws.merge_range(0, 0, 0, dc_last_col, title, fmt_banner_sage)

                type_label = "Deposit Type"
                headers = ["SOL ID", "Work Unit Name", type_label, "Estimate"] + month_headers + ["Annual Target", "Proposed Plan"]
                if is_approved_dc:
                    headers += ["Approved Plan"]
                for ci, h in enumerate(headers):
                    ws.write(1, ci, h, fmt_th)

                val_fmt = fmt_cell_num_no_dec
                dist_val_fmt = fmt_dist_subtotal_num
                tot_val_fmt = fmt_tot_num

                all_lines = cat_plans.mapped("deposit_line_ids")
                if not all_lines:
                    all_lines = self.env["pbms.plan.category.line"].concat(*[p._get_category_lines(cat) for p in cat_plans])
                if not all_lines:
                    all_lines = cat_plans.mapped("line_ids").filtered(lambda l: l.line_type == cat)

                dist_dict = {}
                dist_proposed = {}
                dist_approved = {}
                dist_ob = {}
                for l in all_lines:
                    plan_rec = l.plan_id if hasattr(l, "plan_id") and l.plan_id else False
                    if plan_rec and hasattr(plan_rec, "org_unit_id") and plan_rec.org_unit_id:
                        plan_unit = plan_rec.org_unit_id
                    elif hasattr(l, "source_unit_id") and l.source_unit_id:
                        plan_unit = l.source_unit_id
                    elif hasattr(l, "org_unit_id") and l.org_unit_id:
                        plan_unit = l.org_unit_id
                    else:
                        plan_unit = False

                    if plan_unit:
                        g_sol = plan_unit.sol_id if hasattr(plan_unit, "sol_id") and plan_unit.sol_id else (l.sol_id or 900)
                        g_name = plan_unit.name or "General Unit"
                    else:
                        g_sol = l.sol_id or 900
                        g_name = "General Unit"
                    dist_key = (g_sol, g_name)
                    if dist_key not in dist_dict:
                        dist_dict[dist_key] = {}
                        dist_proposed[dist_key] = {}
                        dist_approved[dist_key] = {}
                        dist_ob[dist_key] = {}

                    dtype = l.deposit_type_id
                    raw_name = dtype.name or "" if dtype else ""
                    if dtype and (dtype.is_ifb if hasattr(dtype, "is_ifb") else False) or "IFB" in raw_name.upper():
                        prod = "IFB"
                    elif "DEMAND" in raw_name.upper() or (dtype and getattr(dtype, "code", "") == "DEM"):
                        prod = "Demand"
                    elif "SAVING" in raw_name.upper() or (dtype and getattr(dtype, "code", "") == "SAV"):
                        prod = "Saving"
                    else:
                        prod = raw_name or "Demand"

                    if prod not in dist_dict[dist_key]:
                        dist_dict[dist_key][prod] = [0.0] * 12
                        dist_proposed[dist_key][prod] = 0.0
                        dist_approved[dist_key][prod] = 0.0
                        dist_ob[dist_key][prod] = 0.0

                    dist_ob[dist_key][prod] += (l.opening_balance or 0.0)
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
                    prop_val = l.proposed_annual_total if getattr(l, "proposed_annual_total", False) else (l.annual_total or 0.0)
                    dist_proposed[dist_key][prod] += prop_val
                    if is_approved_dc:
                        dist_approved[dist_key][prod] += (l.approved_annual_total or 0.0)

                row_cur = 2
                std_prods = ["Demand", "IFB", "Saving"]
                grand_ob = 0.0
                grand_months = [0.0] * 12
                grand_annual = 0.0
                grand_proposed = 0.0
                grand_approved = 0.0

                for (dsol, dname) in sorted(dist_dict.keys(), key=lambda x: (x[0], x[1])):
                    prod_data = dist_dict[(dsol, dname)]
                    prop_data = dist_proposed.get((dsol, dname), {})
                    appr_data = dist_approved.get((dsol, dname), {})
                    ob_data = dist_ob.get((dsol, dname), {})

                    dist_months = [0.0] * 12
                    for p_name, p_vals in prod_data.items():
                        for mi in range(12):
                            dist_months[mi] += p_vals[mi]
                    dist_annual = sum(dist_months)
                    dist_prop_total = sum(prop_data.values())
                    dist_appr_total = sum(appr_data.values())
                    dist_ob_total = sum(ob_data.values())

                    # Subtotal row for work unit without "[-]"
                    ws.write(row_cur, 0, dsol, fmt_dist_subtotal_int)
                    ws.write(row_cur, 1, dname.upper(), fmt_dist_subtotal_label)
                    ws.write(row_cur, 2, "", fmt_dist_subtotal_label)
                    ws.write(row_cur, 3, dist_ob_total, dist_val_fmt)
                    grand_ob += dist_ob_total
                    for mi in range(12):
                        ws.write(row_cur, 4 + mi, dist_months[mi], dist_val_fmt)
                        grand_months[mi] += dist_months[mi]
                    ws.write(row_cur, 16, dist_annual, dist_val_fmt)
                    ws.write(row_cur, 17, dist_prop_total, dist_val_fmt)
                    grand_annual += dist_annual
                    grand_proposed += dist_prop_total
                    if is_approved_dc:
                        ws.write(row_cur, 18, dist_appr_total, dist_val_fmt)
                        grand_approved += dist_appr_total
                    row_cur += 1

                    sorted_prods = [p for p in std_prods if p in prod_data] + [p for p in prod_data if p not in std_prods]
                    for p in sorted_prods:
                        p_vals = prod_data[p]
                        p_annual = sum(p_vals)
                        p_prop = prop_data.get(p, 0.0)
                        p_ob = ob_data.get(p, 0.0)

                        ws.write(row_cur, 0, dsol, fmt_cell_int)
                        ws.write(row_cur, 1, dname.upper(), fmt_cell_text)
                        ws.write(row_cur, 2, p, fmt_cell_text)
                        ws.write(row_cur, 3, p_ob, val_fmt)
                        for mi in range(12):
                            ws.write(row_cur, 4 + mi, p_vals[mi], val_fmt)
                        ws.write(row_cur, 16, p_annual, val_fmt)
                        ws.write(row_cur, 17, p_prop, val_fmt)
                        if is_approved_dc:
                            ws.write(row_cur, 18, appr_data.get(p, 0.0), val_fmt)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                ws.write(row_cur, 1, "", fmt_tot_label)
                ws.write(row_cur, 2, "", fmt_tot_label)
                ws.write(row_cur, 3, grand_ob, tot_val_fmt)
                for mi in range(12):
                    ws.write(row_cur, 4 + mi, grand_months[mi], tot_val_fmt)
                ws.write(row_cur, 16, grand_annual, tot_val_fmt)
                ws.write(row_cur, 17, grand_proposed, tot_val_fmt)
                if is_approved_dc:
                    ws.write(row_cur, 18, grand_approved, tot_val_fmt)

                ws.set_column(0, 0, 12)
                ws.set_column(1, 1, 26)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 18)
                for ci in range(4, 16):
                    ws.set_column(ci, ci, 14)
                ws.set_column(16, 16, 18)
                ws.set_column(17, 17, 18)
                if is_approved_dc:
                    ws.set_column(18, 18, 18)

            elif cat == "customer_base":
                is_approved_dc = any(p.state == "approved" for p in cat_plans)
                # Determine title based on unit type of the plans being exported
                if len(cat_plans) == 1:
                    utype = cat_plans[0].org_unit_type
                    if utype in ("branch", "sub_branch", "service_center"):
                        group_label = "Branch"
                    elif utype == "district_office":
                        group_label = "District"
                    else:
                        group_label = "Head Office"
                else:
                    group_label = "District"

                title = f"Customer Base Plan by {group_label} and Customer Type for the FY {clean_fy}"
                sheet_name = "Customer Base by District"
                ws = wb.add_worksheet(sheet_name)
                ws.freeze_panes(2, 4)

                headers = ["SOL ID", "Work Unit Name", "Customer Type", "Customer Category", "Estimate"] + month_headers + ["Annual Target", "Proposed Plan"]
                if is_approved_dc:
                    headers += ["Approved Plan"]
                ws.merge_range(0, 0, 0, len(headers) - 1, title, fmt_banner_sage)

                for ci, h in enumerate(headers):
                    ws.write(1, ci, h, fmt_th)

                val_fmt = fmt_cell_int
                dist_val_fmt = fmt_dist_subtotal_int
                tot_val_fmt = fmt_tot_int

                all_lines = cat_plans.mapped("customer_base_line_ids")
                if not all_lines:
                    all_lines = self.env["pbms.plan.category.line"].concat(*[p._get_category_lines("customer_base") for p in cat_plans])
                if not all_lines:
                    all_lines = cat_plans.mapped("line_ids").filtered(lambda l: l.line_type == "customer_base")

                BASE_TYPE_MAP = {
                    "new_acquisition": "New Customer Acquisition",
                    "dormant_reduction": "Quality Customer",
                    "both": "New Acquisition & Quality Customer",
                    "New Customer Acquisition": "New Customer Acquisition",
                    "Quality Customer": "Quality Customer",
                }

                dist_dict = {}
                dist_proposed = {}
                dist_approved = {}
                dist_ob = {}
                for l in all_lines:
                    plan_rec = l.plan_id if hasattr(l, "plan_id") and l.plan_id else False
                    if plan_rec and hasattr(plan_rec, "org_unit_id") and plan_rec.org_unit_id:
                        plan_unit = plan_rec.org_unit_id
                    elif hasattr(l, "source_unit_id") and l.source_unit_id:
                        plan_unit = l.source_unit_id
                    elif hasattr(l, "org_unit_id") and l.org_unit_id:
                        plan_unit = l.org_unit_id
                    else:
                        plan_unit = False

                    if plan_unit:
                        g_sol = plan_unit.sol_id if hasattr(plan_unit, "sol_id") and plan_unit.sol_id else (l.sol_id or 900)
                        g_name = plan_unit.name or "General Unit"
                    else:
                        g_sol = l.sol_id or 900
                        g_name = "General Unit"
                    dist_key = (g_sol, g_name)
                    if dist_key not in dist_dict:
                        dist_dict[dist_key] = {}
                        dist_proposed[dist_key] = {}
                        dist_approved[dist_key] = {}
                        dist_ob[dist_key] = {}

                    ctype = l.customer_type_id or l.deposit_type_id
                    raw_name = ctype.name or "" if ctype else ""
                    if ctype and (getattr(ctype, "is_ifb", False) or "IFB" in raw_name.upper()):
                        prod = "IFB"
                    elif "DEMAND" in raw_name.upper() or (ctype and getattr(ctype, "code", "") in ("DEM", "CT_002")):
                        prod = "Demand"
                    elif "SAVING" in raw_name.upper() or (ctype and getattr(ctype, "code", "") in ("SAV", "CT_001")):
                        prod = "Savings"
                    elif "TIME" in raw_name.upper() or (ctype and getattr(ctype, "code", "") in ("TIM", "CT_003")):
                        prod = "Time"
                    else:
                        prod = raw_name or "Savings"

                    cat_label = BASE_TYPE_MAP.get(l.base_type, l.base_type or "")
                    if not cat_label and hasattr(l, "_fields") and "base_type" in l._fields:
                        cat_label = dict(l._fields["base_type"].selection).get(l.base_type, "")
                    if not cat_label:
                        cat_label = "New Customer Acquisition"

                    item_key = (prod, cat_label)

                    if item_key not in dist_dict[dist_key]:
                        dist_dict[dist_key][item_key] = [0.0] * 12
                        dist_proposed[dist_key][item_key] = 0.0
                        dist_approved[dist_key][item_key] = 0.0
                        dist_ob[dist_key][item_key] = 0.0

                    dist_ob[dist_key][item_key] += (l.opening_balance or 0.0)
                    dist_dict[dist_key][item_key][0] += (l.m01 or 0.0)
                    dist_dict[dist_key][item_key][1] += (l.m02 or 0.0)
                    dist_dict[dist_key][item_key][2] += (l.m03 or 0.0)
                    dist_dict[dist_key][item_key][3] += (l.m04 or 0.0)
                    dist_dict[dist_key][item_key][4] += (l.m05 or 0.0)
                    dist_dict[dist_key][item_key][5] += (l.m06 or 0.0)
                    dist_dict[dist_key][item_key][6] += (l.m07 or 0.0)
                    dist_dict[dist_key][item_key][7] += (l.m08 or 0.0)
                    dist_dict[dist_key][item_key][8] += (l.m09 or 0.0)
                    dist_dict[dist_key][item_key][9] += (l.m10 or 0.0)
                    dist_dict[dist_key][item_key][10] += (l.m11 or 0.0)
                    dist_dict[dist_key][item_key][11] += (l.m12 or 0.0)
                    prop_val = l.proposed_annual_total if getattr(l, "proposed_annual_total", False) else (l.annual_total or 0.0)
                    dist_proposed[dist_key][item_key] += prop_val
                    if is_approved_dc:
                        dist_approved[dist_key][item_key] += (l.approved_annual_total or 0.0)

                row_cur = 2
                std_prods = ["Savings", "Demand", "IFB", "Time"]
                std_cats = ["New Customer Acquisition", "Quality Customer"]
                grand_ob = 0.0
                grand_months = [0.0] * 12
                grand_annual = 0.0
                grand_proposed = 0.0
                grand_approved = 0.0

                for (dsol, dname) in sorted(dist_dict.keys(), key=lambda x: (x[0], x[1])):
                    item_data = dist_dict[(dsol, dname)]
                    prop_data = dist_proposed.get((dsol, dname), {})
                    appr_data = dist_approved.get((dsol, dname), {})
                    ob_data = dist_ob.get((dsol, dname), {})

                    dist_months = [0.0] * 12
                    for k, p_vals in item_data.items():
                        for mi in range(12):
                            dist_months[mi] += p_vals[mi]
                    dist_annual = sum(dist_months)
                    dist_prop_total = sum(prop_data.values())
                    dist_appr_total = sum(appr_data.values())
                    dist_ob_total = sum(ob_data.values())

                    # Subtotal row for work unit
                    ws.write(row_cur, 0, dsol, fmt_dist_subtotal_int)
                    ws.write(row_cur, 1, dname.upper(), fmt_dist_subtotal_label)
                    ws.write(row_cur, 2, "", fmt_dist_subtotal_label)
                    ws.write(row_cur, 3, "", fmt_dist_subtotal_label)
                    ws.write(row_cur, 4, dist_ob_total, dist_val_fmt)
                    grand_ob += dist_ob_total
                    for mi in range(12):
                        ws.write(row_cur, 5 + mi, dist_months[mi], dist_val_fmt)
                        grand_months[mi] += dist_months[mi]
                    ws.write(row_cur, 17, dist_annual, dist_val_fmt)
                    ws.write(row_cur, 18, dist_prop_total, dist_val_fmt)
                    grand_annual += dist_annual
                    grand_proposed += dist_prop_total
                    if is_approved_dc:
                        ws.write(row_cur, 19, dist_appr_total, dist_val_fmt)
                        grand_approved += dist_appr_total
                    row_cur += 1

                    def sort_cb_key(k):
                        p, c = k
                        p_idx = std_prods.index(p) if p in std_prods else 99
                        c_idx = std_cats.index(c) if c in std_cats else 99
                        return (p_idx, p, c_idx, c)

                    sorted_items = sorted(item_data.keys(), key=sort_cb_key)
                    for (p, c) in sorted_items:
                        p_vals = item_data[(p, c)]
                        p_annual = sum(p_vals)
                        p_prop = prop_data.get((p, c), 0.0)
                        p_ob = ob_data.get((p, c), 0.0)

                        ws.write(row_cur, 0, dsol, fmt_cell_int)
                        ws.write(row_cur, 1, dname.upper(), fmt_cell_text)
                        ws.write(row_cur, 2, p, fmt_cell_text)
                        ws.write(row_cur, 3, c, fmt_cell_text)
                        ws.write(row_cur, 4, p_ob, val_fmt)
                        for mi in range(12):
                            ws.write(row_cur, 5 + mi, p_vals[mi], val_fmt)
                        ws.write(row_cur, 17, p_annual, val_fmt)
                        ws.write(row_cur, 18, p_prop, val_fmt)
                        if is_approved_dc:
                            ws.write(row_cur, 19, appr_data.get((p, c), 0.0), val_fmt)
                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
                ws.write(row_cur, 1, "", fmt_tot_label)
                ws.write(row_cur, 2, "", fmt_tot_label)
                ws.write(row_cur, 3, "", fmt_tot_label)
                ws.write(row_cur, 4, grand_ob, tot_val_fmt)
                for mi in range(12):
                    ws.write(row_cur, 5 + mi, grand_months[mi], tot_val_fmt)
                ws.write(row_cur, 17, grand_annual, tot_val_fmt)
                ws.write(row_cur, 18, grand_proposed, tot_val_fmt)
                if is_approved_dc:
                    ws.write(row_cur, 19, grand_approved, tot_val_fmt)

                ws.set_column(0, 0, 12)
                ws.set_column(1, 1, 26)
                ws.set_column(2, 2, 18)
                ws.set_column(3, 3, 26)
                ws.set_column(4, 4, 14)
                for ci in range(5, 17):
                    ws.set_column(ci, ci, 12)
                ws.set_column(17, 17, 16)
                ws.set_column(18, 18, 16)
                if is_approved_dc:
                    ws.set_column(19, 19, 16)

            elif cat == "credit_portfolio":

                is_approved_cp = any(p.state == "approved" for p in cat_plans)

                ws = wb.add_worksheet("Income Plan (BB-APF-15)")

                ws.freeze_panes(6, 4)

                cp_last_col = 25 if is_approved_cp else 24

                ws.merge_range(0, 0, 0, cp_last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, cp_last_col, "Income Plan", fmt_doc_title)

                ws.merge_range(2, 0, 2, cp_last_col, f"For the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, cp_last_col, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                ws.write(4, 0, "BB-APF-15", fmt_form_code)

                headers = [

                    "Sol ID", "Work Unit Name", "Districts Name", "Broad Category",

                    "Section", "Portfolio Item", "Totals Basis", "Estimate"

                ] + month_headers + ["Q1", "Q2", "Q3", "Q4", "Annual Target"]

                if is_approved_cp:

                    headers += ["Approved Plan"]

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                row_cur = 6

                seen_line_ids = set()

                for p in cat_plans:

                    lines = p._get_category_lines("credit_portfolio") or p.credit_portfolio_line_ids or p.line_ids.filtered(lambda l: l.line_type == "credit_portfolio")

                    for l in lines:

                        if l.id in seen_line_ids:

                            continue

                        seen_line_ids.add(l.id)

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        sec_label = dict(l._fields["credit_portfolio_section"]._description_selection(l.env)).get(l.credit_portfolio_section, "") if l.credit_portfolio_section else ""

                        item_name = l.credit_portfolio_item_id.name if l.credit_portfolio_item_id else ""

                        basis_label = dict(l._fields["totals_basis"]._description_selection(l.env)).get(l.totals_basis, "") if l.totals_basis else ""

                        ob_val = l.opening_balance or 0.0

                        m_vals = [l.m01 or 0.0, l.m02 or 0.0, l.m03 or 0.0, l.m04 or 0.0, l.m05 or 0.0, l.m06 or 0.0,

                                  l.m07 or 0.0, l.m08 or 0.0, l.m09 or 0.0, l.m10 or 0.0, l.m11 or 0.0, l.m12 or 0.0]

                        q1 = l.quarter1_total or 0.0

                        q2 = l.quarter2_total or 0.0

                        q3 = l.quarter3_total or 0.0

                        q4 = l.quarter4_total or 0.0

                        ann = l.annual_total or 0.0

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)

                        ws.write(row_cur, 1, unit_name, fmt_cell_text)

                        ws.write(row_cur, 2, district_name, fmt_cell_text)

                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)

                        ws.write(row_cur, 4, sec_label, fmt_cell_text)

                        ws.write(row_cur, 5, item_name, fmt_cell_text)

                        ws.write(row_cur, 6, basis_label, fmt_cell_text)

                        ws.write(row_cur, 7, ob_val, fmt_cell_num)

                        for mi, mv in enumerate(m_vals):

                            ws.write(row_cur, 8 + mi, mv, fmt_cell_num)

                        ws.write(row_cur, 20, q1, fmt_cell_num)

                        ws.write(row_cur, 21, q2, fmt_cell_num)

                        ws.write(row_cur, 22, q3, fmt_cell_num)

                        ws.write(row_cur, 23, q4, fmt_cell_num)

                        ws.write(row_cur, 24, ann, fmt_tot_num)

                        if is_approved_cp:

                            appr_val = l.approved_annual_total or 0.0

                            ws.write(row_cur, 25, appr_val, fmt_tot_num)

                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, 7):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                if row_cur > 6:

                    for ci in range(7, 25):

                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)

                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                    if is_approved_cp:

                        c_letter = xlsxwriter.utility.xl_col_to_name(25)

                        ws.write_formula(row_cur, 25, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                else:

                    for ci in range(7, 25):

                        ws.write(row_cur, ci, 0.0, fmt_tot_num)

                    if is_approved_cp:

                        ws.write(row_cur, 25, 0.0, fmt_tot_num)

                ws.set_column(0, 0, 10)

                ws.set_column(1, 1, 24)

                ws.set_column(2, 2, 18)

                ws.set_column(3, 3, 16)

                ws.set_column(4, 4, 18)

                ws.set_column(5, 5, 28)

                ws.set_column(6, 6, 18)

                ws.set_column(7, 7, 18)

                for ci in range(8, 24):

                    ws.set_column(ci, ci, 13)

                ws.set_column(24, 24, 16)

                if is_approved_cp:

                    ws.set_column(25, 25, 16)

            elif cat == "initiative_budget":

                is_approved_ib = any(p.state == "approved" for p in cat_plans)

                ws = wb.add_worksheet("Initiative Budget")

                ws.freeze_panes(6, 4)

                ib_last_col = 7 if is_approved_ib else 6

                ws.merge_range(0, 0, 0, ib_last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, ib_last_col, "Initiative Budget Plan", fmt_doc_title)

                ws.merge_range(2, 0, 2, ib_last_col, f"For the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, ib_last_col, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                headers = [

                    "Sol ID", "Work Unit Name", "Districts Name", "Broad Category",

                    "Initiative Name", "Description / Justification", "Initiative Cost"

                ]

                if is_approved_ib:

                    headers += ["Approved Cost"]

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                row_cur = 6

                seen_line_ids = set()

                for p in cat_plans:

                    lines = p._get_category_lines("initiative_budget") or p.initiative_budget_line_ids or p.line_ids.filtered(lambda l: l.line_type == "initiative_budget")

                    for l in lines:

                        if l.id in seen_line_ids:

                            continue

                        seen_line_ids.add(l.id)

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        iname = l.initiative_name or ""

                        idesc = l.initiative_description or ""

                        cost = l.initiative_cost or l.annual_total or 0.0

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)

                        ws.write(row_cur, 1, unit_name, fmt_cell_text)

                        ws.write(row_cur, 2, district_name, fmt_cell_text)

                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)

                        ws.write(row_cur, 4, iname, fmt_cell_text)

                        ws.write(row_cur, 5, idesc, fmt_cell_text)

                        ws.write(row_cur, 6, cost, fmt_cell_num)

                        if is_approved_ib:

                            appr_cost = l.approved_annual_total or 0.0

                            ws.write(row_cur, 7, appr_cost, fmt_cell_num)

                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, 6):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                if row_cur > 6:

                    c_letter = xlsxwriter.utility.xl_col_to_name(6)

                    ws.write_formula(row_cur, 6, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                    if is_approved_ib:

                        c_letter = xlsxwriter.utility.xl_col_to_name(7)

                        ws.write_formula(row_cur, 7, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)

                else:

                    ws.write(row_cur, 6, 0.0, fmt_tot_num)

                    if is_approved_ib:

                        ws.write(row_cur, 7, 0.0, fmt_tot_num)

                ws.set_column(0, 0, 10)

                ws.set_column(1, 1, 24)

                ws.set_column(2, 2, 18)

                ws.set_column(3, 3, 16)

                ws.set_column(4, 4, 28)

                ws.set_column(5, 5, 36)

                ws.set_column(6, 6, 20)

                if is_approved_ib:

                    ws.set_column(7, 7, 20)

            else:

                # FX, Digital Banking, Loan Disbursement & Collection, Loan & Advances Outstanding

                is_approved_fx = any(p.state == "approved" for p in cat_plans)

                cat_titles = {

                    "fx": "FX Mobilization",

                    "digital_banking": "Digital Banking",

                    "loan_disbursement_collection": "Loan Disbursement & Collection",

                    "loan_outstanding": "Loan & Advances Outstanding",

                }

                cat_title = cat_titles.get(cat, (cat or "plan").replace("_", " ").title())

                ws = wb.add_worksheet(cat_title[:31])

                ws.freeze_panes(6, 4)

                fx_last_col = 20 if is_approved_fx else 19

                ws.merge_range(0, 0, 0, fx_last_col, "Bunna Bank", fmt_bank_title)

                ws.merge_range(1, 0, 1, fx_last_col, cat_title, fmt_doc_title)

                ws.merge_range(2, 0, 2, fx_last_col, f"For the FY {clean_fy}", fmt_fy_title)

                ws.merge_range(3, 0, 3, fx_last_col, get_banner_unit_title(cat_plans, "District and Head Office"), fmt_work_units_title)

                item_labels = {

                    "fx": "FX Source",

                    "digital_banking": "Digital Channel",

                    "loan_disbursement_collection": "Loan Disbursement & Collection",

                    "loan_outstanding": "Loan Product",

                }

                item_label = item_labels.get(cat, "Product / Item")

                headers = ["Sol ID", "Work Unit Name", "Districts Name", "Broad Category", item_label, "Estimate"] + month_headers + ["Annual Target", "Proposed Plan"]

                if is_approved_fx:

                    headers += ["Approved Plan"]

                for ci, h in enumerate(headers):

                    ws.write(5, ci, h, fmt_th)

                is_int_cat = (cat == "digital_banking")

                cell_num_fmt = fmt_cell_int if is_int_cat else fmt_cell_num

                tot_num_fmt = fmt_tot_int if is_int_cat else fmt_tot_num

                row_cur = 6

                for p in cat_plans:

                    lines = p._get_category_lines(cat) or p.line_ids.filtered(lambda l: l.line_type == cat)

                    for l in lines:

                        sol_id, unit_name, district_name, broad_cat = get_meta(l, p)

                        if cat == "fx":

                            item_val = l.fx_source_type.name if l.fx_source_type else ""

                        elif cat == "digital_banking":

                            item_val = l.channel_id.name if l.channel_id else ""

                        elif cat == "loan_disbursement_collection":

                            flow_labels = {"disbursement": "Disbursement", "collection": "Collection"}

                            item_val = flow_labels.get(l.loan_flow_type, (l.loan_flow_type or "").title())

                        elif cat == "loan_outstanding":

                            item_val = l.loan_product_id.name if hasattr(l, "loan_product_id") and l.loan_product_id else (l.other_justification or "Loan Product")

                        else:

                            item_val = getattr(l, "name", "") or ""

                        ob_val = int(round(l.opening_balance or 0.0)) if is_int_cat else (l.opening_balance or 0.0)

                        raw_m_vals = [l.m01 or 0.0, l.m02 or 0.0, l.m03 or 0.0, l.m04 or 0.0, l.m05 or 0.0, l.m06 or 0.0,

                                      l.m07 or 0.0, l.m08 or 0.0, l.m09 or 0.0, l.m10 or 0.0, l.m11 or 0.0, l.m12 or 0.0]

                        m_vals = [int(round(mv)) for mv in raw_m_vals] if is_int_cat else raw_m_vals

                        raw_ann = l.annual_total or sum(raw_m_vals)

                        ann = int(round(raw_ann)) if is_int_cat else raw_ann

                        raw_prop = l.proposed_annual_total if getattr(l, "proposed_annual_total", False) else (l.annual_total or sum(raw_m_vals))

                        prop_val = int(round(raw_prop)) if is_int_cat else raw_prop

                        ws.write(row_cur, 0, sol_id, fmt_cell_int)

                        ws.write(row_cur, 1, unit_name, fmt_cell_text)

                        ws.write(row_cur, 2, district_name, fmt_cell_text)

                        ws.write(row_cur, 3, broad_cat, fmt_cell_text)

                        ws.write(row_cur, 4, item_val, fmt_cell_text)

                        ws.write(row_cur, 5, ob_val, cell_num_fmt)

                        for mi, mv in enumerate(m_vals):

                            ws.write(row_cur, 6 + mi, mv, cell_num_fmt)

                        ws.write(row_cur, 18, ann, tot_num_fmt)

                        ws.write(row_cur, 19, prop_val, tot_num_fmt)

                        if is_approved_fx:

                            raw_appr = l.approved_annual_total or 0.0

                            appr_val = int(round(raw_appr)) if is_int_cat else raw_appr

                            ws.write(row_cur, 20, appr_val, tot_num_fmt)

                        row_cur += 1

                ws.write(row_cur, 0, "TOTAL", fmt_tot_label)

                for ci in range(1, 5):

                    ws.write(row_cur, ci, "", fmt_tot_label)

                if row_cur > 6:

                    for ci in range(5, 20):

                        c_letter = xlsxwriter.utility.xl_col_to_name(ci)

                        ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", tot_num_fmt)

                    if is_approved_fx:

                        c_letter = xlsxwriter.utility.xl_col_to_name(20)

                        ws.write_formula(row_cur, 20, f"=SUM({c_letter}7:{c_letter}{row_cur})", tot_num_fmt)

                else:

                    for ci in range(5, 20):

                        ws.write(row_cur, ci, 0 if is_int_cat else 0.0, tot_num_fmt)

                    if is_approved_fx:

                        ws.write(row_cur, 20, 0 if is_int_cat else 0.0, tot_num_fmt)

                ws.set_column(0, 0, 10)

                ws.set_column(1, 1, 24)

                ws.set_column(2, 2, 18)

                ws.set_column(3, 3, 16)

                ws.set_column(4, 4, 24)

                ws.set_column(5, 5, 20)

                for ci in range(6, 18):

                    ws.set_column(ci, ci, 13)

                ws.set_column(18, 18, 16)

                ws.set_column(19, 19, 16)

                if is_approved_fx:

                    ws.set_column(20, 20, 16)

        wb.close()

        output.seek(0)

        file_data = output.getvalue()

        if len(records) == 1:

            rec = records[0]

            cat_name = (ctx_category or rec.category or "Plan").replace("_", " ").title().replace(" ", "_")

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

        target_category = self.env.context.get("target_category") or getattr(self, "category", False) or "deposit"

        district = self.org_unit_id if self.org_unit_type in ("district_office", "regional_office", "area_office") else (self.district_id or False)

        category_titles = {

            "deposit": _("Deposit Mobilization"),

            "customer_base": _("Customer Base"),

            "fx": _("FX Mobilization"),

            "digital_banking": _("Digital Banking"),

            "general_expense": _("General Expense Budget"),

            "manpower": _("Workforce / Manpower Plan"),

            "fixed_asset": _("Fixed Asset Requirement"),

            "loan_disbursement_collection": _("Loan Disbursement & Collection"),

            "loan_outstanding": _("Loan & Advances Outstanding"),

            "credit_portfolio": _("Income Plan"),

            "initiative_budget": _("Initiative Budget"),

        }

        title = _("Branch Details - %s (%s)") % (category_titles.get(target_category, target_category), district.display_name if district else _("All Branches"))

        category_view_map = {

            "manpower": "bunna_pbms.view_pbms_plan_category_line_review_list_manpower",

            "general_expense": "bunna_pbms.view_pbms_plan_category_line_review_list_expense",

            "fixed_asset": "bunna_pbms.view_pbms_plan_category_line_review_list_fixed_asset",

            "credit_portfolio": "bunna_pbms.view_pbms_plan_category_line_review_list_credit_portfolio",

            "initiative_budget": "bunna_pbms.view_pbms_plan_category_line_review_list_initiative_budget",

        }

        list_view_xmlid = category_view_map.get(target_category, "bunna_pbms.view_pbms_plan_category_line_drilldown_list")

        list_view = self.env.ref(list_view_xmlid, raise_if_not_found=False)

        pivot_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_pivot", raise_if_not_found=False)

        graph_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_graph", raise_if_not_found=False)

        form_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_form", raise_if_not_found=False)

        search_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_review_search", raise_if_not_found=False) or self.env.ref("bunna_pbms.view_pbms_plan_category_line_search", raise_if_not_found=False)

        views = []

        if list_view:

            views.append((list_view.id, "list"))

        if pivot_view:

            views.append((pivot_view.id, "pivot"))

        if graph_view:

            views.append((graph_view.id, "graph"))

        if form_view:

            views.append((form_view.id, "form"))

        domain = [

            ("cycle_id", "=", self.cycle_id.id),

            ("line_type", "=", target_category),

            ("org_unit_type", "in", ("branch", "sub_branch", "service_center")),

        ]

        if district and self.org_unit_type in ("district_office", "regional_office", "area_office"):

            domain.append(("district_id", "=", district.id))

        return {

            "name": title,

            "type": "ir.actions.act_window",

            "res_model": "pbms.plan.category.line",

            "view_mode": "list,pivot,graph,form",

            "views": views if views else False,

            "search_view_id": [search_view.id, search_view.name] if search_view else False,

            "domain": domain,

            "context": {

                "search_default_group_by_org_unit": 1,

                "default_line_type": target_category,

                "target_category": target_category,

                "group_by": ["org_unit_id"],

            },

        }

    def action_view_district_details(self):

        """Action for Final Approver / Head Office Reviewers to inspect district-by-district breakdown across all districts."""

        self.ensure_one()

        target_category = self.env.context.get("target_category") or getattr(self, "category", False) or "deposit"

        category_titles = {

            "deposit": _("Deposit Mobilization"),

            "customer_base": _("Customer Base"),

            "fx": _("FX Mobilization"),

            "digital_banking": _("Digital Banking"),

            "general_expense": _("General Expense Budget"),

            "manpower": _("Workforce / Manpower Plan"),

            "fixed_asset": _("Fixed Asset Requirement"),

            "loan_disbursement_collection": _("Loan Disbursement & Collection"),

            "loan_outstanding": _("Loan & Advances Outstanding"),

            "credit_portfolio": _("Income Plan"),

            "initiative_budget": _("Initiative Budget"),

        }

        title = _("District Breakdown - %s") % category_titles.get(target_category, target_category)

        category_view_map = {

            "manpower": "bunna_pbms.view_pbms_plan_category_line_review_list_manpower",

            "general_expense": "bunna_pbms.view_pbms_plan_category_line_review_list_expense",

            "fixed_asset": "bunna_pbms.view_pbms_plan_category_line_review_list_fixed_asset",

            "credit_portfolio": "bunna_pbms.view_pbms_plan_category_line_review_list_credit_portfolio",

            "initiative_budget": "bunna_pbms.view_pbms_plan_category_line_review_list_initiative_budget",

        }

        list_view_xmlid = category_view_map.get(target_category, "bunna_pbms.view_pbms_plan_category_line_drilldown_list")

        list_view = self.env.ref(list_view_xmlid, raise_if_not_found=False)

        pivot_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_pivot", raise_if_not_found=False)

        graph_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_drilldown_graph", raise_if_not_found=False)

        form_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_form", raise_if_not_found=False)

        search_view = self.env.ref("bunna_pbms.view_pbms_plan_category_line_review_search", raise_if_not_found=False) or self.env.ref("bunna_pbms.view_pbms_plan_category_line_search", raise_if_not_found=False)

        views = []

        if list_view:

            views.append((list_view.id, "list"))

        if pivot_view:

            views.append((pivot_view.id, "pivot"))

        if graph_view:

            views.append((graph_view.id, "graph"))

        if form_view:

            views.append((form_view.id, "form"))

        return {

            "name": title,

            "type": "ir.actions.act_window",

            "res_model": "pbms.plan.category.line",

            "view_mode": "list,pivot,graph,form",

            "views": views if views else False,

            "search_view_id": [search_view.id, search_view.name] if search_view else False,

            "domain": [

                ("cycle_id", "=", self.cycle_id.id),

                ("org_unit_type", "in", ("district_office", "regional_office", "area_office")),

                ("line_type", "=", target_category),

            ],

            "context": {

                "search_default_group_by_org_unit": 1,

                "default_line_type": target_category,

                "target_category": target_category,

                "group_by": ["org_unit_id"],

            },

        }

    # ------------------------------------------------------------------

    # Validation

    # ------------------------------------------------------------------

    @api.constrains(

        "category",

        "deposit_line_ids",

        "customer_base_line_ids",

        "digital_banking_line_ids",

        "fx_line_ids",

        "m01", "m02", "m03", "m04", "m05", "m06",

        "m07", "m08", "m09", "m10", "m11", "m12",

    )

    def _check_consolidable_plan_monthly_positive(self):

        CONSOLIDABLE_CATS = ("deposit", "customer_base", "digital_banking", "fx")

        MONTH_SEQUENCE = [

            ("m01", _("July")), ("m02", _("August")), ("m03", _("September")),

            ("m04", _("October")), ("m05", _("November")), ("m06", _("December")),

            ("m07", _("January")), ("m08", _("February")), ("m09", _("March")),

            ("m10", _("April")), ("m11", _("May")), ("m12", _("June")),

        ]

        CAT_NAMES = {

            "customer_base": _("Customer Base"),

            "deposit": _("Deposit Mobilization"),

            "digital_banking": _("Digital Banking"),

            "fx": _("FX Mobilization"),

        }

        for plan in self:

            if plan.category not in CONSOLIDABLE_CATS:

                continue

            cat_label = CAT_NAMES.get(plan.category, plan.category)

            lines = getattr(plan, f"{plan.category}_line_ids", False)

            if not lines and hasattr(plan, "line_ids"):

                lines = plan.line_ids.filtered(lambda l: l.line_type == plan.category)

            is_draft = not plan.state or plan.state in ("draft", "returned", "info_requested")

            if is_draft:

                # In draft mode, unfilled months (0.0) are allowed during cell-by-cell data entry.

                # Non-zero validation across all 12 months is enforced on submission (action_submit).

                if plan.category == "deposit":

                    continue

                if lines:

                    for line in lines:

                        if plan.category == "customer_base" and getattr(line, "base_type", False) == "dormant_reduction":

                            continue

                        for fname, m_label in MONTH_SEQUENCE:

                            val = getattr(line, fname, 0.0) or 0.0

                            if val < 0.0:

                                raise ValidationError(_(

                                    "%(category)s — %(month)s: Monthly plan cannot be negative.",

                                    category=cat_label,

                                    month=m_label,

                                ))

                continue

            if plan.category == "deposit":

                if lines:

                    for line in lines:

                        for fname, m_label in MONTH_SEQUENCE:

                            val = getattr(line, fname, 0.0) or 0.0

                            if float_is_zero(val, precision_digits=2):

                                raise ValidationError(_(

                                    "%(category)s - %(month)s: Monthly plan cannot be zero. Each month must have a positive or negative target.",

                                    category=cat_label,

                                    month=m_label,

                                ))

                continue

            if lines:

                for line in lines:

                    if plan.category == "customer_base" and getattr(line, "base_type", False) == "dormant_reduction":

                        continue

                    for fname, m_label in MONTH_SEQUENCE:

                        val = getattr(line, fname, 0.0) or 0.0

                        if val <= 0.0:

                            raise ValidationError(_(

                                "%(category)s — %(month)s: Each month must have a value greater than zero.",

                                category=cat_label,

                                month=m_label,

                            ))

    @api.constrains("deposit_line_ids", "customer_base_line_ids", "digital_banking_line_ids", "fx_line_ids", "loan_disbursement_line_ids")

    def _check_unique_lines_in_plan(self):

        for plan in self:

            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):

                continue

            if plan.deposit_line_ids:

                dep_types = plan.deposit_line_ids.filtered(lambda l: l.deposit_type_id).mapped("deposit_type_id")

                if len(dep_types) < len(plan.deposit_line_ids.filtered(lambda l: l.deposit_type_id)):

                    raise ValidationError(_(

                        "Duplicate Deposit Type detected. Each deposit type can only be planned once per plan. "

                        "Please update the existing line instead of adding a duplicate."

                    ))

            if plan.customer_base_line_ids:

                # In customer base, each customer type can be planned for both New Customer Acquisition and Quality Customer

                pairs = []

                for l in plan.customer_base_line_ids:

                    code = (l.customer_type_id.code if l.customer_type_id else (l.deposit_type_id.code if l.deposit_type_id else False))

                    if code and l.base_type:

                        pairs.append((code, l.base_type))

                if len(pairs) != len(set(pairs)):

                    raise ValidationError(_(

                        "Duplicate Customer Type and Base Type detected. "

                        "Each customer type can only be planned once per base type (New Customer Acquisition and Quality Customer)."

                    ))

            if plan.digital_banking_line_ids:

                channels = plan.digital_banking_line_ids.filtered(lambda l: l.channel_id).mapped("channel_id")

                if len(channels) < len(plan.digital_banking_line_ids.filtered(lambda l: l.channel_id)):

                    raise ValidationError(_(

                        "Duplicate Digital Channel detected. Each digital channel can only be planned once per plan. "

                        "Please update the existing line instead of adding a duplicate."

                    ))

            if plan.fx_line_ids:

                fx_sources = plan.fx_line_ids.filtered(lambda l: l.fx_source_type).mapped("fx_source_type")

                if len(fx_sources) < len(plan.fx_line_ids.filtered(lambda l: l.fx_source_type)):

                    raise ValidationError(_(

                        "Duplicate FX Source detected. Each FX source can only be planned once per plan. "

                        "Please update the existing line instead of adding a duplicate."

                    ))

            if plan.loan_disbursement_line_ids:

                flow_types = plan.loan_disbursement_line_ids.filtered(lambda l: l.loan_flow_type).mapped("loan_flow_type")

                if len(flow_types) < len(plan.loan_disbursement_line_ids.filtered(lambda l: l.loan_flow_type)):

                    raise ValidationError(_(

                        "Duplicate Loan Disbursement & Collection type detected. Each type (Disbursement / Collection) can only be planned once per plan. "

                        "Please update the existing line instead of adding a duplicate."

                    ))

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

                    and rec.fx_source_type.code in ("SWIFT", "remittance_swift")

                    and rec.org_unit_id.work_unit_type != "head_office"):

                raise ValidationError(_(

                    "Remittance-SWIFT targets are planned at Head Office / "

                    "corporate level only, not per branch or district."))

    @api.constrains("plan_category", "category", *MONTH_FIELDS)

    def _check_account_category_is_whole_number(self):

        for rec in self:

            if (rec.category == "customer_base" and rec.plan_category == "customer") or rec.category == "manpower":

                for fname in MONTH_FIELDS:

                    val = getattr(rec, fname) or 0.0

                    if val != int(val):

                        raise ValidationError(_(

                            "%(cat)s targets must be whole numbers (integers), got %(val)s for %(month)s.",

                            cat=rec.plan_category_title or _("Plan"),

                            val=val, month=fname))

    @api.constrains("return_reason", "district_comment", "chief_comment", "people_solutions_comment", "cpco_comment", "ho_comment", "committee_comment", "ceo_comment")

    def _check_comments_not_pure_numbers(self):

        fields_to_check = {

            "return_reason": _("Return Reason"),

            "district_comment": _("District Comment"),

            "chief_comment": _("Chief Comment"),

            "people_solutions_comment": _("People Solutions Comment"),

            "cpco_comment": _("CPCO Comment"),

            "ho_comment": _("Head Office Comment"),

            "committee_comment": _("Committee Comment"),

            "ceo_comment": _("CEO Comment"),

        }

        for rec in self:

            for fname, label in fields_to_check.items():

                val = getattr(rec, fname, False)

                if val:

                    s = str(val).strip()

                    cleaned = s.replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")

                    if cleaned and cleaned.isdigit():

                        raise ValidationError(_("Field '%s' cannot be purely numeric digits. Please enter a meaningful text explanation.") % label)

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

                ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

                ("active", "=", True),

            ]

            if rec_id:

                domain.append(("id", "!=", rec_id))

            duplicate_cats = self.sudo().search(domain)

            blocking_dup = False

            for duplicate_cat in duplicate_cats:

                has_dup_data = bool(duplicate_cat.line_ids) or any(getattr(duplicate_cat, m, 0.0) for m in MONTH_FIELDS) or ((getattr(duplicate_cat, "annual_total", 0.0) or 0.0) > 0.0)

                if duplicate_cat.state == "draft" and not has_dup_data:

                    duplicate_cat.sudo().with_context(bypass_plan_lock=True).write({"active": False})

                    continue

                blocking_dup = duplicate_cat

            if blocking_dup:

                has_rec_data = bool(rec.line_ids) or any(getattr(rec, m, 0.0) for m in MONTH_FIELDS) or ((getattr(rec, "annual_total", 0.0) or 0.0) > 0.0)

                if rec.state == "draft" and not has_rec_data and (self.env.context.get("bypass_plan_lock") or self.env.context.get("is_planning_request")):

                    rec.sudo().with_context(bypass_plan_lock=True).write({"active": False})

                    continue

                unit_name = rec.org_unit_id.display_name

                cycle_name = rec.cycle_id.name

                cat_name = dict(self._fields["category"].selection).get(rec.category, rec.category)

                raise ValidationError(_(

                    "A %(cat)s plan already exists for %(unit)s in budget year '%(cycle)s' (Request: %(req)s). "

                    "Each work unit can only have one plan per category per fiscal year.",

                    cat=cat_name,

                    unit=unit_name,

                    cycle=cycle_name,

                    req=blocking_dup.request_number or "N/A",

                ))

            # 2. If this record is in draft, check if another record for this unit & cycle & category is already submitted/approved

            if rec.state in ("draft", "returned", "info_requested") and rec.category and not self.env.context.get("bypass_plan_lock"):

                sub_domain = [

                    ("org_unit_id", "=", rec.org_unit_id.id),

                    ("cycle_id", "=", rec.cycle_id.id),

                    ("category", "=", rec.category),

                    ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),

                    ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),

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

            "loan_product_id": line.loan_product_id.id if line.loan_product_id else False,

            "loan_flow_type": line.loan_flow_type,

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

                initial_state = "submitted" if dist_unit.work_unit_type == "district_office" else ("ho_reviewed" if dist_unit.work_unit_type == "head_office" else "draft")

                create_vals = {

                    "category": category,

                    "cycle_id": cycle_id.id,

                    "org_unit_id": dist_unit.id,

                    "state": initial_state,

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

        target_cat = self.env.context.get("target_category") or self.env.context.get("category") or getattr(self, "category", False) or "deposit"

        if target_cat not in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"):

            # Direct pass group (Manpower, General Expense, Fixed Asset): no district consolidation

            return False

        district_plan = self.with_context(active_test=False).search([

            ("cycle_id", "=", cycle_id.id),

            ("org_unit_id", "=", district.id),

            ("category", "=", target_cat),

            ("is_consolidated_district_plan", "=", True),

        ], limit=1)

        force = self.env.context.get("force_consolidate", False)

        if district_plan and not force and district_plan.line_ids and district_plan.state in ("ho_reviewed", "approved"):

            # District plan is already endorsed/approved; preserve district's edited plan data!

            return district_plan

        if not district_plan:

            district_plan = self.with_context(bypass_plan_lock=True).create({

                "cycle_id": cycle_id.id,

                "org_unit_id": district.id,

                "category": target_cat,

                "is_consolidated_district_plan": True,

                "is_consolidated_ho_plan": False,

                "state": "submitted",

                "active": True,

            })

        else:

            write_vals = {"is_consolidated_district_plan": True}

            if not district_plan.active:

                write_vals["active"] = True

            if district_plan.state in ("draft", "returned", "info_requested"):

                write_vals["state"] = "submitted"

            district_plan.with_context(bypass_plan_lock=True).write(write_vals)

        # Fetch approved branch plans in this district

        branch_plans = self.search([

            ("cycle_id", "=", cycle_id.id),

            ("district_id", "=", district.id),

            ("org_unit_id", "!=", district.id),

            ("active", "=", True),

            ("state", "in", (

                "district_approved", "district_endorsed",

                "chief_review", "people_solutions_review", "cpco_review",

                "committee_review", "ceo_approval", "board_ceo_approval",

                "ho_reviewed", "approved",

            )),

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

                    "proposed_annual_total": tot_m,

                    "approved_annual_total": 0.0,

                    "is_cascaded": False,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

        elif target_cat == "customer_base":

            cust_types_by_code = {c.code: c for c in self.env["pbms.customer.type"].sudo().search([]) if c.code}

            dep_types_by_code = {d.code: d for d in self.env["pbms.deposit.type"].sudo().search([]) if d.code}

            cb_grouped = {}

            for line in all_bp_lines:

                cust_type = line.customer_type_id

                if not cust_type and line.deposit_type_id and line.deposit_type_id.code:

                    cust_type = cust_types_by_code.get(line.deposit_type_id.code)

                cust_id = cust_type.id if cust_type else False

                dep_id = line.deposit_type_id.id if line.deposit_type_id else (

                    dep_types_by_code.get(cust_type.code).id if (cust_type and cust_type.code and cust_type.code in dep_types_by_code) else False

                )

                if not cust_id and not dep_id:

                    continue

                b_type = line.base_type or "new_acquisition"

                key = (cust_id, dep_id, b_type)

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

            for (cust_id, dep_id, b_type), vals in cb_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                payload = {

                    "line_type": "customer_base",

                    "base_type": b_type,

                    "source_unit_id": district.id,

                    "sol_id": district_sol_id,

                    "opening_balance": vals["opening_balance"],

                    "proposed_opening_balance": vals["proposed_opening_balance"],

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    "approved_annual_total": 0.0,

                    "is_cascaded": False,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }

                if cust_id:

                    payload["customer_type_id"] = cust_id

                if dep_id:

                    payload["deposit_type_id"] = dep_id

                lines_to_create.append((0, 0, payload))

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

                    "proposed_annual_total": tot_m,

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

                    "proposed_annual_total": tot_m,

                    "approved_annual_total": 0.0,

                    "is_cascaded": False,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

        elif target_cat == "loan_disbursement_collection":

            ld_grouped = {}

            for line in all_bp_lines:

                flow_type = line.loan_flow_type or "disbursement"

                key = flow_type

                if key not in ld_grouped:

                    ld_grouped[key] = {

                        "opening_balance": 0.0,

                        "proposed_opening_balance": 0.0,

                        **{m: 0.0 for m in MONTH_FIELDS},

                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},

                    }

                for m in MONTH_FIELDS:

                    ld_grouped[key][m] += (getattr(line, m) or 0.0)

                    prop_m = getattr(line, f"proposed_{m}")

                    ld_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for flow_type, vals in ld_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                lines_to_create.append((0, 0, {

                    "line_type": "loan_disbursement_collection",

                    "loan_flow_type": flow_type,

                    "source_unit_id": district.id,

                    "sol_id": district_sol_id,

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    "approved_annual_total": 0.0,

                    "is_cascaded": False,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

        elif target_cat == "loan_outstanding":

            lo_grouped = {}

            for line in all_bp_lines:

                prod_id = line.loan_product_id.id if line.loan_product_id else False

                if not prod_id:

                    continue

                if prod_id not in lo_grouped:

                    lo_grouped[prod_id] = {

                        "opening_balance": 0.0,

                        "proposed_opening_balance": 0.0,

                        **{m: 0.0 for m in MONTH_FIELDS},

                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},

                    }

                lo_grouped[prod_id]["opening_balance"] += (line.opening_balance or 0.0)

                lo_grouped[prod_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)

                for m in MONTH_FIELDS:

                    lo_grouped[prod_id][m] += (getattr(line, m) or 0.0)

                    prop_m = getattr(line, f"proposed_{m}")

                    lo_grouped[prod_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            for prod_id, vals in lo_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                lines_to_create.append((0, 0, {

                    "line_type": "loan_outstanding",

                    "loan_product_id": prod_id,

                    "source_unit_id": district.id,

                    "sol_id": district_sol_id,

                    "opening_balance": vals["opening_balance"],

                    "proposed_opening_balance": vals["proposed_opening_balance"],

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    "approved_annual_total": 0.0,

                    "is_cascaded": False,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

        # Unlink only the lines for this specific category on the district plan

        dp_ctx = district_plan.with_context(
            bypass_plan_lock=True,
            skip_reviewer_check=True,
            skip_sync_category_records=True,
            skip_split_mixed_lines=True,
            skip_cleanup_district_cards=True,
            skip_dropdown_plan_check=True,
        )

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

        elif target_cat == "loan_disbursement_collection":

            dp_ctx.loan_disbursement_line_ids.unlink()

            if lines_to_create:

                dp_ctx.write({"loan_disbursement_line_ids": lines_to_create})

        elif target_cat == "loan_outstanding":

            dp_ctx.loan_outstanding_line_ids.unlink()

            if lines_to_create:

                dp_ctx.write({"loan_outstanding_line_ids": lines_to_create})

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

        if target_cat not in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"):

            return False

        ho_plan = self.search([

            ("cycle_id", "=", cycle_id.id),

            ("org_unit_id", "=", ho_unit.id),

            ("category", "=", target_cat),

            ("is_consolidated_ho_plan", "=", True),

            ("active", "=", True),

        ], limit=1)

        if not ho_plan:

            ho_plan = self.create({

                "cycle_id": cycle_id.id,

                "org_unit_id": ho_unit.id,

                "district_id": ho_unit.id,

                "category": target_cat,

                "is_consolidated_ho_plan": True,

                "state": "district_endorsed",

                "active": True,

            })

        else:

            ho_plan.with_context(bypass_plan_lock=True).write({

                "is_consolidated_ho_plan": True,

                **({"state": "district_endorsed"} if ho_plan.state in ("draft", "returned", "info_requested") else {}),

                "active": True,

            })

        if not ho_plan.district_id:

            ho_plan.with_context(bypass_plan_lock=True).write({"district_id": ho_unit.id})

        # Fetch all active non-HO plans across the bank for THIS category

        # Only district overview plans that have been endorsed to Head Office or already approved are consolidated

        source_plans = self.search([

            ("cycle_id", "=", cycle_id.id),

            ("org_unit_id", "!=", ho_unit.id),

            ("category", "=", target_cat),

            ("active", "=", True),

            ("state", "in", ("district_endorsed", "ho_reviewed", "approved")),

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

        ho_ctx = ho_plan.with_context(
            bypass_plan_lock=True,
            skip_reviewer_check=True,
            skip_sync_category_records=True,
            skip_split_mixed_lines=True,
            skip_cleanup_district_cards=True,
            skip_dropdown_plan_check=True,
        )

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

                    "proposed_annual_total": tot_m,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

            if dep_create_vals:

                ho_ctx.write({"deposit_line_ids": dep_create_vals})

        elif target_cat == "customer_base":

            cb_lines = get_source_lines("customer_base")

            cust_types_by_code = {c.code: c for c in self.env["pbms.customer.type"].sudo().search([]) if c.code}

            dep_types_by_code = {d.code: d for d in self.env["pbms.deposit.type"].sudo().search([]) if d.code}

            cb_grouped = {}

            for line in cb_lines:

                cust_type = line.customer_type_id

                if not cust_type and line.deposit_type_id and line.deposit_type_id.code:

                    cust_type = cust_types_by_code.get(line.deposit_type_id.code)

                cust_id = cust_type.id if cust_type else False

                dep_id = line.deposit_type_id.id if line.deposit_type_id else (

                    dep_types_by_code.get(cust_type.code).id if (cust_type and cust_type.code and cust_type.code in dep_types_by_code) else False

                )

                if not cust_id and not dep_id:

                    continue

                b_type = line.base_type or "new_acquisition"

                key = (cust_id, dep_id, b_type)

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

            for (cust_id, dep_id, b_type), vals in cb_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                payload = {

                    "line_type": "customer_base",

                    "base_type": b_type,

                    "opening_balance": vals["opening_balance"],

                    "proposed_opening_balance": vals["proposed_opening_balance"],

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }

                if cust_id:

                    payload["customer_type_id"] = cust_id

                if dep_id:

                    payload["deposit_type_id"] = dep_id

                cb_create_vals.append((0, 0, payload))

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

                    "proposed_annual_total": tot_m,

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

                    "proposed_annual_total": tot_m,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

            if db_create_vals:

                ho_ctx.write({"digital_banking_line_ids": db_create_vals})

        elif target_cat == "loan_disbursement_collection":

            ld_lines = get_source_lines("loan_disbursement_collection")

            ld_grouped = {}

            for line in ld_lines:

                flow_type = line.loan_flow_type or "disbursement"

                key = flow_type

                if key not in ld_grouped:

                    ld_grouped[key] = {

                        "opening_balance": 0.0,

                        "proposed_opening_balance": 0.0,

                        **{m: 0.0 for m in MONTH_FIELDS},

                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},

                    }

                for m in MONTH_FIELDS:

                    ld_grouped[key][m] += (getattr(line, m) or 0.0)

                    prop_m = getattr(line, f"proposed_{m}")

                    ld_grouped[key][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.loan_disbursement_line_ids.unlink()

            ld_create_vals = []

            for flow_type, vals in ld_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                ld_create_vals.append((0, 0, {

                    "line_type": "loan_disbursement_collection",

                    "loan_flow_type": flow_type,

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

            if ld_create_vals:

                ho_ctx.write({"loan_disbursement_line_ids": ld_create_vals})

        elif target_cat == "loan_outstanding":

            lo_lines = get_source_lines("loan_outstanding")

            lo_grouped = {}

            for line in lo_lines:

                prod_id = line.loan_product_id.id if line.loan_product_id else False

                if not prod_id:

                    continue

                if prod_id not in lo_grouped:

                    lo_grouped[prod_id] = {

                        "opening_balance": 0.0,

                        "proposed_opening_balance": 0.0,

                        **{m: 0.0 for m in MONTH_FIELDS},

                        **{f"proposed_{m}": 0.0 for m in MONTH_FIELDS},

                    }

                lo_grouped[prod_id]["opening_balance"] += (line.opening_balance or 0.0)

                lo_grouped[prod_id]["proposed_opening_balance"] += (line.proposed_opening_balance or line.opening_balance or 0.0)

                for m in MONTH_FIELDS:

                    lo_grouped[prod_id][m] += (getattr(line, m) or 0.0)

                    prop_m = getattr(line, f"proposed_{m}")

                    lo_grouped[prod_id][f"proposed_{m}"] += (prop_m if prop_m else (getattr(line, m) or 0.0))

            ho_ctx.loan_outstanding_line_ids.unlink()

            lo_create_vals = []

            for prod_id, vals in lo_grouped.items():

                tot_m = sum(vals[m] for m in MONTH_FIELDS)

                tot_prop = sum(vals[f"proposed_{m}"] for m in MONTH_FIELDS)

                lo_create_vals.append((0, 0, {

                    "line_type": "loan_outstanding",

                    "loan_product_id": prod_id,

                    "opening_balance": vals["opening_balance"],

                    "proposed_opening_balance": vals["proposed_opening_balance"],

                    "annual_total": tot_m,

                    "proposed_annual_total": tot_m,

                    **{m: vals[m] for m in MONTH_FIELDS},

                    **{f"proposed_{m}": vals[f"proposed_{m}"] for m in MONTH_FIELDS},

                }))

            if lo_create_vals:

                ho_ctx.write({"loan_outstanding_line_ids": lo_create_vals})

        if hasattr(ho_plan, "_compute_category_summaries"):

            ho_plan._compute_category_summaries()

        return ho_plan

    @api.constrains(
        "category",
        "cycle_id",
        "org_unit_id",
        "state",
        "deposit_line_ids",
        "customer_base_line_ids",
        "fx_line_ids",
        "digital_banking_line_ids",
        "loan_disbursement_line_ids",
        "loan_outstanding_line_ids",
    )
    def _check_all_dropdowns_planned(self):
        """Enforce validation for all dropdown fields under the 6 planning categories:
        Deposit Mobilization, Customer Base, FX Mobilization, Digital Banking,
        Loan Disbursement & Collection, and Loan and Advance Outstanding.
        Ensures all dropdown selections have a corresponding plan configured for the
        selected planning period, and prevents users from selecting or submitting
        dropdown values that are not planned."""
        if self.env.context.get("bypass_plan_lock") or self.env.context.get("pbms_target_cascade") or self.env.context.get("skip_dropdown_plan_check"):
            return
        MONTH_FIELDS = [f"m{i:02d}" for i in range(1, 13)]
        Config = self.env.get("pbms.planning.config")

        for plan in self:
            if getattr(plan, "is_consolidation_overview", False) or getattr(plan, "is_merged", False):
                continue
            if plan.state not in ("draft", "returned", "info_requested", False) and not self.env.context.get("force_validate_dropdowns"):
                continue

            unit_type = plan.org_unit_type or (plan.org_unit_id.work_unit_type if plan.org_unit_id else False)
            if unit_type in ("district_office", "head_office", "regional_office") and not self.env.context.get("force_validate_dropdowns"):
                # Consolidations aggregate across branches
                continue

            cat = plan.category
            if cat not in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"):
                continue

            category_lines_map = {
                "deposit": plan.deposit_line_ids,
                "customer_base": plan.customer_base_line_ids,
                "fx": plan.fx_line_ids,
                "digital_banking": plan.digital_banking_line_ids,
                "loan_disbursement_collection": plan.loan_disbursement_line_ids,
                "loan_outstanding": plan.loan_outstanding_line_ids,
            }
            cat_lines = category_lines_map.get(cat, self.env["pbms.plan.category.line"])
            if not cat_lines and not self.env.context.get("force_validate_dropdowns"):
                continue

            cycle_name = plan.cycle_id.name if plan.cycle_id else _("the selected planning period")
            config = Config.get_config_for_unit(plan.org_unit_id) if (Config and plan.org_unit_id) else False
            is_submit_or_forced = bool(self.env.context.get("force_validate_dropdowns") or plan.state not in ("draft", "returned", "info_requested"))

            if cat == "deposit":
                field_name = _("Deposit Type")
                available = plan.available_deposit_type_ids or (config.deposit_type_ids if (config and config.deposit_type_ids) else self.env["pbms.deposit.type"].search([("active", "=", True)]))
                used = plan.deposit_line_ids.filtered(lambda l: bool(l.deposit_type_id)).mapped("deposit_type_id")
                # When dropdown values are selected, check that they are configured/planned
                unplanned_used = used - available
                if unplanned_used:
                    names = ", ".join(unplanned_used.mapped("display_name") or unplanned_used.mapped("name"))
                    raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": names, "cycle": cycle_name})
                # Check that selected lines have actual plan figures configured
                for l in plan.deposit_line_ids.filtered(lambda l: bool(l.deposit_type_id)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = l.deposit_type_id.display_name or l.deposit_type_id.name
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})

            elif cat == "customer_base":
                field_name = _("Customer Type")
                available = plan.available_customer_type_ids or (config.customer_type_ids if (config and config.customer_type_ids) else self.env["pbms.customer.type"].search([("active", "=", True)]))
                avail_codes = set(available.mapped("code"))
                for l in plan.customer_base_line_ids.filtered(lambda l: bool(l.customer_type_id or l.deposit_type_id)):
                    c_code = l.customer_type_id.code if l.customer_type_id else (l.deposit_type_id.code if l.deposit_type_id else False)
                    if c_code and c_code not in avail_codes:
                        l_name = l.customer_type_id.display_name or (l.deposit_type_id.display_name if l.deposit_type_id else c_code)
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})
                for l in plan.customer_base_line_ids.filtered(lambda l: bool(l.customer_type_id or l.deposit_type_id)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = l.customer_type_id.display_name if l.customer_type_id else (l.deposit_type_id.display_name if l.deposit_type_id else _("Customer Type"))
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})

            elif cat == "fx":
                field_name = _("FX Source")
                available = plan.available_fx_source_type_ids or (config.fx_source_type_ids if (config and config.fx_source_type_ids) else self.env["pbms.fx.source.type"].search([("active", "=", True)]))
                used = plan.fx_line_ids.filtered(lambda l: bool(l.fx_source_type)).mapped("fx_source_type")
                unplanned_used = used - available
                if unplanned_used:
                    names = ", ".join(unplanned_used.mapped("display_name") or unplanned_used.mapped("name"))
                    raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": names, "cycle": cycle_name})
                for l in plan.fx_line_ids.filtered(lambda l: bool(l.fx_source_type)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = l.fx_source_type.display_name or l.fx_source_type.name
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})

            elif cat == "digital_banking":
                field_name = _("Digital Channel")
                available = plan.available_channel_ids or (config.digital_channel_ids if (config and config.digital_channel_ids) else self.env["pbms.digital.channel"].search([("active", "=", True)]))
                used = plan.digital_banking_line_ids.filtered(lambda l: bool(l.channel_id)).mapped("channel_id")
                unplanned_used = used - available
                if unplanned_used:
                    names = ", ".join(unplanned_used.mapped("display_name") or unplanned_used.mapped("name"))
                    raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": names, "cycle": cycle_name})
                for l in plan.digital_banking_line_ids.filtered(lambda l: bool(l.channel_id)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = l.channel_id.display_name or l.channel_id.name
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})

            elif cat == "loan_disbursement_collection":
                field_name = _("Loan Disbursement & Collection")
                for l in plan.loan_disbursement_line_ids.filtered(lambda l: bool(l.loan_flow_type)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = dict(l._fields["loan_flow_type"].selection).get(l.loan_flow_type, l.loan_flow_type or _("Flow Type"))
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})

            elif cat == "loan_outstanding":
                field_name = _("Loan Product")
                if config and config.loan_product_ids:
                    available = config.loan_product_ids.filtered(lambda p: p.applies_to in ("outstanding", "both") and p.active)
                else:
                    available = self.env["pbms.loan.product"].search([("active", "=", True), ("applies_to", "in", ("outstanding", "both"))])
                used = plan.loan_outstanding_line_ids.filtered(lambda l: bool(l.loan_product_id)).mapped("loan_product_id")
                unplanned_used = used - available
                if unplanned_used:
                    names = ", ".join(unplanned_used.mapped("display_name") or unplanned_used.mapped("name"))
                    raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": names, "cycle": cycle_name})
                for l in plan.loan_outstanding_line_ids.filtered(lambda l: bool(l.loan_product_id)):
                    if not any(l[m] not in (0.0, 0, False, None) for m in MONTH_FIELDS):
                        l_name = l.loan_product_id.display_name or l.loan_product_id.name
                        raise ValidationError(_("%(field)s '%(names)s' does not have a corresponding plan configured for the selected planning period '%(cycle)s'. A plan must be configured before proceeding.") % {"field": field_name, "names": l_name, "cycle": cycle_name})


    @api.constrains("business_justification", "other_justification")
    def _check_plan_no_special_characters(self):
        PROHIBITED_CHARS = set("@#$%&*!^()+={}[]|\\/<>?~")
        for plan in self:
            for fname in ("business_justification", "other_justification"):
                val = getattr(plan, fname, False)
                if val and isinstance(val, str):
                    found = set(c for c in val if c in PROHIBITED_CHARS)
                    if found:
                        chars_str = " ".join(sorted(found))
                        field_str = plan._fields[fname].string or fname if fname in plan._fields else fname
                        raise ValidationError(
                            _("Special characters '%(chars)s' are not allowed in %(field)s. Prohibited characters: @ # $ % & * ! ^ ( ) + = { } [ ] | \\ / < > ? ~")
                            % {"chars": chars_str, "field": field_str}
                        )


    def action_save_plan(self):

        self.with_context(force_validate_dropdowns=True)._check_all_dropdowns_planned()


        """Explicit Save action to persist draft inputs and workflow edits.

        Clicking this button triggers client-side form validation and save, persists 

        all modified fields and requirement lines to the database, and returns a 

        success notification to confirm the save.

        """

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Plan Saved"),

                "message": _("Your plan changes have been saved successfully."),

                "type": "success",

                "sticky": False,

            },

        }

    def _pbms_write_header_months(self):

        """Persist Jul-Jun header figures (sum of the plan's lines of its own

        category) so list rows and group totals match the form."""

        for plan in self.with_context(in_distribute_plan_sync=True, skip_sync_lines=True, bypass_plan_lock=True):

            lines = plan.line_ids.filtered(lambda l: l.line_type == plan.category)

            if not lines or plan.category == "fixed_asset":

                continue

            vals = {}

            for m in MONTH_FIELDS:

                vals[m] = sum((getattr(l, m) or getattr(l, "hc_%s" % m, 0) or 0.0) for l in lines)

            plan.sudo().write(vals)

    @api.model

    def _pbms_resync_header_totals(self):

        """Recompute the stored monthly / quarterly / annual / roll-up figures of

        every plan from its requirement lines (same data the form view shows).

        Plans saved before these computes existed can hold stale header values,

        which made the list view (and its group / footer totals) disagree with

        the form.  Safe to run repeatedly; called on module upgrade."""

        import logging

        log = logging.getLogger(__name__)

        Line = self.env["pbms.plan.category.line"].sudo().with_context(

            active_test=False, bypass_plan_lock=True, auto_balancing_sourcing=True)

        for line in Line.search([("line_type", "=", "manpower")]):

            vals = {}

            for m in MONTH_FIELDS:

                hc_val = getattr(line, "hc_%s" % m) or 0

                if hc_val and not getattr(line, m):

                    vals[m] = float(hc_val)

            if vals:

                line.write(vals)

        plans = self.sudo().with_context(active_test=False, bypass_plan_lock=True).search([])

        for i in range(0, len(plans), 200):

            batch = plans[i:i + 200]

            try:

                with self.env.cr.savepoint():

                    if hasattr(batch, "_compute_category_summaries"):

                        batch._compute_category_summaries()

                    batch._compute_totals()

                    batch._compute_rollup_quarter_totals()

                    batch._pbms_write_header_months()

            except Exception:

                log.exception("PBMS header resync failed for plans %s", batch.ids[:5])

        return True

    # ------------------------------------------------------------------

    # Generic role-aware Bulk Approve

    # ------------------------------------------------------------------

    _BULK_FINANCIAL_CATEGORIES = (

        "deposit", "customer_base", "fx", "digital_banking",

        "loan_disbursement_collection", "loan_outstanding", "general_expense",

        "credit_portfolio",

    )

    def _bulk_approve_next_action(self):

        """Return the name of the approval method the CURRENT USER may run on

        this plan in its CURRENT state, or False when the plan is not waiting

        for this user.  Mirrors the buttons of the form view header, so bulk

        approval can never do more than the user could do record by record

        (each method still performs its own access checks)."""

        self.ensure_one()

        user = self.env.user

        has = user.has_group

        state, cat = self.state, self.category

        is_admin = bool(has("bunna_pbms.group_pbms_manager") or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su)

        g_district = is_admin or has("bunna_pbms.group_pbms_district_reviewer")

        g_ho = is_admin or has("bunna_pbms.group_pbms_ho_reviewer")

        g_approver = is_admin or has("bunna_pbms.group_pbms_approver")

        g_chief = is_admin or has("bunna_pbms.group_pbms_respective_chief") or has("bunna_pbms.group_pbms_ceo")

        g_ps = is_admin or has("bunna_pbms.group_pbms_people_solutions")

        g_cpco = is_admin or has("bunna_pbms.group_pbms_cpco")

        g_committee = is_admin or has("bunna_pbms.group_pbms_budget_hiring_committee")

        g_ceo = is_admin or has("bunna_pbms.group_pbms_ceo")

        # Respective Chief stage (same for every category)

        if state == "chief_review":

            return "action_chief_approve_escalate" if (g_chief and self.can_chief_review) else False

        if cat == "manpower":

            if state in ("submitted", "info_requested"):

                if g_district and not self.is_district_unit and not self.is_head_office_unit and (self._pbms_can_district_review_plan() or is_admin):

                    return "action_district_approve_workforce"

            elif state == "people_solutions_review" and g_ps:

                return "action_people_solutions_escalate_cpco"

            elif state == "cpco_review" and g_cpco:

                return "action_cpco_submit_to_committee"

            elif state == "committee_review" and g_committee:

                return "action_committee_approve"

            elif state == "ceo_approval" and g_ceo:

                return "action_ceo_approve"

            elif state == "ho_endorse" and g_ho and (self._pbms_can_ho_review_plan() or is_admin):

                return "action_ho_endorse_to_cpco"

            elif state == "cpco_endorse" and g_cpco:

                return "action_cpco_endorse_to_solutions"

            return False

        # District stage (branch plans -> "District Approve", district plans -> "Endorse to HO")

        if g_district and not self.is_head_office_unit and (self._pbms_can_district_review_plan() or is_admin):

            if self.is_district_unit:

                if state in ("submitted", "district_approved", "info_requested"):

                    return "action_district_approve"

            elif state in ("submitted", "info_requested"):

                return "action_district_approve"

        if cat in ("fixed_asset", "initiative_budget"):

            if g_ho and (self._pbms_can_ho_review_plan() or is_admin):

                if self.is_head_office_unit and state in ("submitted", "ho_reviewed", "info_requested"):

                    return "action_submit_to_committee"

                if not self.is_head_office_unit and state in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested"):

                    return "action_submit_to_committee"

            if state == "committee_review" and g_committee:

                return "action_committee_approve_resource"

            return False

        if cat in self._BULK_FINANCIAL_CATEGORIES:

            if g_ho and (self._pbms_can_ho_review_plan() or is_admin):

                if cat in ("deposit", "customer_base", "fx", "digital_banking"):

                    if self.is_district_unit and state in ("district_endorsed", "ho_reviewed"):

                        return "action_ho_approve"

                    if self.is_head_office_unit and state in ("submitted", "district_endorsed", "ho_reviewed", "info_requested"):

                        return "action_ho_approve"

                else:

                    if self.is_head_office_unit and state in ("submitted", "ho_reviewed", "info_requested"):

                        return "action_ho_approve"

                    if not self.is_head_office_unit and state in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested"):

                        return "action_ho_approve"

            if g_approver and state == "ho_reviewed":

                return "action_approve"

        return False

    def action_bulk_approve(self):

        """Approve / advance every selected plan that is waiting for the

        current user's review stage.  Available to every PBMS privilege

        except the plain Branch / Head Office user."""

        user = self.env.user

        allowed = (

            "bunna_pbms.group_pbms_district_reviewer", "bunna_pbms.group_pbms_ho_reviewer",

            "bunna_pbms.group_pbms_approver", "bunna_pbms.group_pbms_respective_chief",

            "bunna_pbms.group_pbms_people_solutions", "bunna_pbms.group_pbms_cpco",

            "bunna_pbms.group_pbms_budget_hiring_committee", "bunna_pbms.group_pbms_ceo",

            "bunna_pbms.group_pbms_manager",

        )

        if not any(user.has_group(g) for g in allowed):

            raise AccessError(_("Bulk approval is not available for Branch / Head Office users."))

        done, skipped, errors = 0, 0, []

        for rec in self:

            method = rec._bulk_approve_next_action()

            if not method:

                skipped += 1

                continue

            try:

                with self.env.cr.savepoint():

                    getattr(rec, method)()

                done += 1

            except (UserError, AccessError, ValidationError) as exc:

                errors.append("%s: %s" % (rec.request_number or rec.display_name, exc.args[0] if exc.args else exc))

        msg = _("%(done)s plan(s) approved / advanced.", done=done)

        if skipped:

            msg += "\n" + _("%(n)s skipped (not waiting for your review).", n=skipped)

        if errors:

            msg += "\n" + _("%(n)s could not be processed:\n%(details)s", n=len(errors), details="\n".join(errors[:5]))

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Bulk Approve"),

                "message": msg,

                "type": "success" if done and not errors else "warning",

                "sticky": bool(errors),

                "next": {"type": "ir.actions.act_window_close"},

            },

        }

    def action_bulk_ho_approve(self):

        """Bulk HO approval for selected planning categories."""

        count = 0

        errors = []

        for rec in self:

            try:

                if rec.category in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding", "general_expense", "credit_portfolio"):

                    if rec.state in ("draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed", "ho_reviewed"):

                        rec.action_ho_approve()

                        count += 1

                elif rec.category == "manpower":

                    if rec.state in ("submitted", "district_approved", "chief_reviewed", "people_solutions_reviewed", "ho_endorse"):

                        rec.action_ho_endorse_to_cpco()

                        count += 1

                elif rec.category in ("fixed_asset", "initiative_budget"):

                    if rec.state in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested"):

                        rec.action_submit_to_committee()

                        count += 1

            except Exception as e:

                errors.append(f"{rec.display_name or rec.request_number}: {str(e)}")

        msg = _("%s plan(s) have been successfully processed/approved.") % count

        if errors:

            msg += "\n" + _("Some records could not be processed:\n%s") % "\n".join(errors[:5])

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Bulk Approval Complete"),

                "message": msg,

                "type": "success" if count > 0 else "warning",

                "sticky": bool(errors),

                "next": {"type": "ir.actions.act_window_close"},

            },

        }

    def action_bulk_district_approve(self):

        """Bulk District approval for selected planning categories."""

        count = 0

        errors = []

        for rec in self:

            try:

                if rec.state in ("submitted", "info_requested", "district_approved"):

                    if rec.category == "manpower":

                        rec.action_district_approve_workforce()

                    else:

                        rec.action_district_approve()

                    count += 1

            except Exception as e:

                errors.append(f"{rec.display_name or rec.request_number}: {str(e)}")

        msg = _("%s plan(s) have been approved by District.") % count

        if errors:

            msg += "\n" + _("Some records could not be processed:\n%s") % "\n".join(errors[:5])

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Bulk District Approval Complete"),

                "message": msg,

                "type": "success" if count > 0 else "warning",

                "sticky": bool(errors),

                "next": {"type": "ir.actions.act_window_close"},

            },

        }

    def _open_plan_wizard_action(self, xml_id, extra_ctx=None):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select at least one plan."))

        action = self.env["ir.actions.actions"]._for_xml_id(xml_id)

        action = dict(action)

        ctx = {

            "active_ids": records.ids,

            "active_id": records[0].id,

            "active_model": "pbms.planning.category",

            "default_plan_id": records[0].id,

        }

        if extra_ctx:

            ctx.update(extra_ctx)

        action["context"] = ctx

        return action

    def action_bulk_wizard_review_comment(self):

        return self._open_plan_wizard_action("bunna_pbms.action_pbms_review_comment_wizard")

    def action_bulk_wizard_request_info(self):

        return self._open_plan_wizard_action("bunna_pbms.action_pbms_request_info_wizard")

    def action_bulk_wizard_return(self):

        return self._open_plan_wizard_action("bunna_pbms.action_pbms_return_revision_wizard")

    def action_bulk_wizard_reject(self):

        return self._open_plan_wizard_action("bunna_pbms.action_pbms_reject_wizard")

    def action_bulk_open_import_wizard(self):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select a plan."))

        return records[0].action_open_import_wizard()

    def action_bulk_export_excel(self):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select a plan."))

        return records[0].action_export_excel()

    def action_bulk_consolidate_district(self):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select a plan."))

        return records.action_consolidate_district_overview()

    def action_bulk_refresh_workforce(self):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select a plan."))

        return records.action_refresh_existing_manpower()

    def action_bulk_reset_to_draft(self):

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            raise UserError(_("Please select a plan."))

        return records.action_reset_to_draft()

    def action_bulk_cascade_ho(self):

        records = (self or self.browse(self.env.context.get("active_ids", []))).filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")

        )

        if not records:

            raise UserError(_("Target cascading is only applicable to Deposit Mobilization, Customer Base, FX Mobilization, and Digital Banking plans."))

        ho_plan = records.filtered(lambda p: p.org_unit_type == "head_office" or p.is_head_office_unit)[:1]

        if not ho_plan:

            sample = records[0]

            ho_unit = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")], limit=1)

            if ho_unit:

                ho_plan = self.env["pbms.planning.category"].search([

                    ("cycle_id", "=", sample.cycle_id.id),

                    ("category", "=", sample.category),

                    ("org_unit_id", "=", ho_unit.id),

                ], limit=1)

        if not ho_plan or ho_plan.state != "approved":

            raise UserError(_("The Bank-Wide Head Office consolidated plan must be Final Approved before cascading targets to Districts."))

        if ho_plan.is_targets_cascaded:

            return ho_plan.action_already_cascaded_notice()

        return ho_plan._open_plan_wizard_action(

            "bunna_pbms.action_pbms_target_cascade_ho_wizard",

            {"default_cascade_level": "ho_to_district"},

        )

    def action_bulk_cascade_district(self):

        records = (self or self.browse(self.env.context.get("active_ids", []))).filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")

        )

        if not records:

            raise UserError(_("Target cascading is only applicable to Deposit Mobilization, Customer Base, FX Mobilization, and Digital Banking plans."))

        dist_plan = records.filtered(lambda p: p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit)[:1]

        if not dist_plan:

            sample = records[0]

            parent_unit = sample.org_unit_id.parent_unit

            if parent_unit:

                dist_plan = self.env["pbms.planning.category"].search([

                    ("cycle_id", "=", sample.cycle_id.id),

                    ("category", "=", sample.category),

                    ("org_unit_id", "=", parent_unit.id),

                ], limit=1)

        if not dist_plan or not dist_plan.has_cascaded_targets:

            raise UserError(_("This District plan has not received cascaded targets from Head Office yet."))

        if dist_plan.is_targets_cascaded:

            return dist_plan.action_already_cascaded_notice()

        return dist_plan._open_plan_wizard_action(

            "bunna_pbms.action_pbms_target_cascade_district_wizard",

            {"default_cascade_level": "district_to_branch"},

        )

    def action_bulk_delete(self):

        """Bulk delete selected planning categories for SPPMD Administrator."""

        user = self.env.user

        if not (self.env.is_admin() or user._pbms_is_sppmd_admin()):

            raise AccessError(_("Only the SPPMD Administrator can delete plans in bulk."))

        records = self or self.browse(self.env.context.get("active_ids", []))

        if not records:

            return False

        count = len(records)

        records.unlink()

        return {

            "type": "ir.actions.client",

            "tag": "display_notification",

            "params": {

                "title": _("Deleted"),

                "message": _("%s plan(s) deleted successfully.", count),

                "sticky": False,

                "type": "success",

                "next": {"type": "ir.actions.client", "tag": "reload"},

            },

        }

    def _register_hook(self):

        super()._register_hook()

        try:

            with self.env.cr.savepoint():

                etb = self.env.ref("base.ETB", raise_if_not_found=False)

                if etb and etb.symbol:

                    etb.sudo().write({"symbol": ""})

        except Exception:

            pass

def _is_transaction_aborted(env):
    try:
        cr_obj = getattr(getattr(env, "cr", None), "_obj", None)
        if cr_obj:
            if getattr(cr_obj, "status", None) == 3:  # psycopg2 STATUS_IN_ERROR
                return True
            if hasattr(cr_obj, "get_transaction_status") and cr_obj.get_transaction_status() == 3:
                return True
    except Exception:
        pass
    return False


def _safe_in_memory_ou_display_name(ou):
    """Safely resolve an operating unit's display name purely from memory/cache
    without triggering SQL queries, even when the database transaction is aborted."""
    try:
        cache = ou.env.cache
        f_name = ou._fields.get("name")
        if f_name and cache.contains(ou, f_name):
            val = cache.get(ou, f_name)
            if val:
                return str(val)
        if hasattr(ou, "_origin") and ou._origin:
            orig = ou._origin
            if f_name and cache.contains(orig, f_name):
                val = cache.get(orig, f_name)
                if val:
                    return str(val)
    except Exception:
        pass
    ou_id = getattr(ou, "id", None) or (getattr(ou, "_origin", None) and getattr(ou._origin, "id", None))
    return f"Operating Unit #{ou_id}" if ou_id else "Operating Unit"


class OperatingUnitPbmsPlanActions(models.Model):

    _inherit = "operating.unit"

    @api.depends("name")

    def _compute_display_name(self):

        import re

        for ou in self:
            if _is_transaction_aborted(self.env):
                ou.display_name = _safe_in_memory_ou_display_name(ou)
                continue
            try:
                raw_name = ou.name or ""
                # Strip any bracketed SOL ID or report code prefix, e.g. "[2003] retaile operation" -> "retaile operation"
                clean_name = re.sub(r"^(\[.*?\]\s*)+", "", raw_name).strip()
                ou.display_name = clean_name or raw_name
            except Exception:
                ou.display_name = _safe_in_memory_ou_display_name(ou)

    pbms_group_line_type = fields.Char(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_has_unit_plan = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_submit = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_refresh_workforce = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_district_approve = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_district_endorse = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_consolidate_district = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_consolidate_ho = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_district_approve_workforce = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_chief_endorse = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_chief_approve = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_ps_escalate = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_submit_committee = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_committee_approve_resource = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_committee_endorse_ceo = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_ceo_approve = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_ho_endorse_cpco = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_cpco_endorse_ops = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_ho_approve = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_approve = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_reviewer_actions = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_reset = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_cascade_ho = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_can_unit_cascade_district = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    pbms_is_unit_targets_cascaded = fields.Boolean(

        compute="_compute_pbms_unit_button_flags",

        compute_sudo=False,

    )

    def _pbms_get_unit_plans(self):

        """Find the planning category record(s) for this operating unit in the active cycle."""

        category = self.env.context.get("default_line_type") or self.env.context.get("default_category")

        base_domain = [("org_unit_id", "in", self.ids), ("line_ids", "!=", False)]

        if category:

            base_domain.append(("category", "=", category))

        cycle_id = self.env.context.get("default_cycle_id")

        if cycle_id:

            domain = base_domain + [("cycle_id", "=", cycle_id)]

        else:

            open_cycles = self.env["pbms.planning.cycle"].sudo().search([("state", "=", "open")])

            if open_cycles:

                domain = base_domain + [("cycle_id", "in", open_cycles.ids)]

            else:

                domain = list(base_domain)

        plans = self.env["pbms.planning.category"].search(domain)

        if not plans:

            plans = self.env["pbms.planning.category"].search(base_domain)

        if not plans:

            domain_no_lines = [c for c in domain if c != ("line_ids", "!=", False)]

            plans = self.env["pbms.planning.category"].search(domain_no_lines)

        return plans

    @api.depends_context("default_line_type", "default_category", "default_cycle_id", "uid")

    def _compute_pbms_unit_button_flags(self):

        """Compute visibility of unit-level <groupby> buttons per privilege and plan state."""

        user = self.env.user
        ho_unit = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")], limit=1)

        is_admin = bool(user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su)

        g_district = user.has_group("bunna_pbms.group_pbms_district_reviewer") or is_admin

        g_ho = user.has_group("bunna_pbms.group_pbms_ho_reviewer") or is_admin

        g_approver = user.has_group("bunna_pbms.group_pbms_approver") or is_admin

        ctx_line_type = self.env.context.get("default_line_type") or self.env.context.get("default_category") or False

        all_plans = self._pbms_get_unit_plans() if self.ids else self.env["pbms.planning.category"]

        plans_by_unit = {}

        for p in all_plans:

            plans_by_unit.setdefault(p.org_unit_id.id, self.env["pbms.planning.category"])

            plans_by_unit[p.org_unit_id.id] |= p

        for unit in self:
            unit.pbms_group_line_type = ctx_line_type
            plans = plans_by_unit.get(unit.id, self.env["pbms.planning.category"])
            if ctx_line_type:
                plans = plans.filtered(lambda p: p.category == ctx_line_type)

            is_consolidation_unit = bool(any(p.is_consolidated_ho_plan for p in plans))

            if not plans:
                unit.pbms_has_unit_plan = False
                unit.pbms_can_unit_submit = False
                unit.pbms_can_unit_refresh_workforce = False
                unit.pbms_can_unit_district_approve = False
                unit.pbms_can_unit_district_endorse = False
                unit.pbms_can_unit_consolidate_district = False
                unit.pbms_can_unit_consolidate_ho = False
                unit.pbms_can_unit_district_approve_workforce = False
                unit.pbms_can_unit_chief_endorse = False
                unit.pbms_can_unit_chief_approve = False
                unit.pbms_can_unit_ps_escalate = False
                unit.pbms_can_unit_submit_committee = False
                unit.pbms_can_unit_committee_approve_resource = False
                unit.pbms_can_unit_committee_endorse_ceo = False
                unit.pbms_can_unit_ceo_approve = False
                unit.pbms_can_unit_ho_endorse_cpco = False
                unit.pbms_can_unit_cpco_endorse_ops = False
                unit.pbms_can_unit_ho_approve = False
                unit.pbms_can_unit_approve = False
                unit.pbms_can_unit_reviewer_actions = False
                unit.pbms_can_unit_reset = False
                unit.pbms_can_unit_cascade_ho = False
                unit.pbms_can_unit_cascade_district = False
                unit.pbms_is_unit_targets_cascaded = False
                continue

            unit.pbms_has_unit_plan = True

            # If all plans for this operating unit in this category are approved or rejected,
            # ALL review/approval/reset/return/reject action buttons MUST BE HIDDEN.
            all_finished = bool(all(p.state in ("approved", "rejected") for p in plans))
            if all_finished:
                unit.pbms_can_unit_submit = False
                unit.pbms_can_unit_refresh_workforce = False
                unit.pbms_can_unit_district_approve = False
                unit.pbms_can_unit_district_endorse = False
                unit.pbms_can_unit_consolidate_district = False
                unit.pbms_can_unit_district_approve_workforce = False
                unit.pbms_can_unit_chief_endorse = False
                unit.pbms_can_unit_chief_approve = False
                unit.pbms_can_unit_ps_escalate = False
                unit.pbms_can_unit_submit_committee = False
                unit.pbms_can_unit_committee_approve_resource = False
                unit.pbms_can_unit_committee_endorse_ceo = False
                unit.pbms_can_unit_ceo_approve = False
                unit.pbms_can_unit_ho_endorse_cpco = False
                unit.pbms_can_unit_cpco_endorse_ops = False
                unit.pbms_can_unit_ho_approve = False
                unit.pbms_can_unit_approve = False
                unit.pbms_can_unit_reviewer_actions = False
                unit.pbms_can_unit_reset = False

                # Head Office operating unit plans do not cascade or consolidate
                unit.pbms_can_unit_consolidate_ho = False

                can_cascade_ho = False
                can_cascade_dist = False
                is_cascaded = False

                if is_consolidation_unit:
                    # Head Office Bank-Wide Consolidated Plan:
                    # Cascade button is enabled after approval if not yet cascaded
                    for p in plans:
                        if p.category not in ("deposit", "customer_base", "fx", "digital_banking"):
                            continue
                        if p.is_targets_cascaded:
                            is_cascaded = True
                        elif (g_ho or g_approver or is_admin) and p.state == "approved":
                            can_cascade_ho = True
                elif unit.work_unit_type in ("district_office", "regional_office") or any(p.is_district_unit for p in plans):
                    # District Offices:
                    for p in plans:
                        if p.category not in ("deposit", "customer_base", "fx", "digital_banking"):
                            continue
                        if p.is_targets_cascaded and p.has_cascaded_targets:
                            is_cascaded = True
                        if g_district and not p.is_targets_cascaded and p.has_cascaded_targets:
                            can_cascade_dist = True

                unit.pbms_can_unit_cascade_ho = can_cascade_ho
                unit.pbms_can_unit_cascade_district = can_cascade_dist
                unit.pbms_is_unit_targets_cascaded = is_cascaded
                continue

            # 1. Submit / Import / Refresh Workforce: only when plan is in draft / returned / info_requested and user owns/can submit
            can_submit = False
            for p in plans:
                if p.state in ("draft", "returned", "info_requested") and p.is_cycle_open:
                    if p._pbms_can_submit_plan() or is_admin:
                        can_submit = True
                        break
            unit.pbms_can_unit_submit = can_submit
            unit.pbms_can_unit_refresh_workforce = bool(
                can_submit and any(p.category == "manpower" for p in plans)
            )

            # 2. Consolidate Branch Plans (for District Office mobilization plans before endorsement/approval)
            can_consolidate_dist = False
            if g_district:
                for p in plans:
                    if (
                        p.category in ("deposit", "customer_base", "fx", "digital_banking")
                        and (p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit)
                        and p.state in ("draft", "submitted", "district_approved", "info_requested", "returned")
                        and (p._pbms_can_district_review_plan() or is_admin)
                    ):
                        can_consolidate_dist = True
                        break
            unit.pbms_can_unit_consolidate_district = can_consolidate_dist

            can_consolidate_ho = False
            if is_consolidation_unit and (g_ho or is_admin):
                for p in plans:
                    if (
                        p.category in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding")
                        and p.state in ("draft", "submitted", "district_endorsed", "ho_reviewed", "info_requested", "returned")
                    ):
                        can_consolidate_ho = True
                        break
            unit.pbms_can_unit_consolidate_ho = can_consolidate_ho

            # 3. Stage-specific Approval / Escalation buttons (matching form view header)
            can_dist = False
            can_dist_endorse = False
            can_dist_wf = False
            can_chief_endorse = False
            can_chief_approve = False
            can_ps_escalate = False
            can_submit_committee = False
            can_committee_resource = False
            can_committee_ceo = False
            can_ceo_approve = False
            can_ho_endorse_cpco = False
            can_cpco_endorse_ops = False
            can_ho = False
            can_approve = False
            can_reviewer_wizards = False

            for p in plans:
                if p.can_use_reviewer_actions and p.state not in ("draft", "approved", "rejected"):
                    if not (p.category == "manpower" and p.state in ("ho_endorse", "cpco_endorse")):
                        can_reviewer_wizards = True
                next_act = p._bulk_approve_next_action()
                if not next_act:
                    continue
                if next_act == "action_district_approve":
                    if p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit or getattr(unit, "work_unit_type", False) in ("district_office", "regional_office"):
                        if p.state in ("submitted", "district_approved", "info_requested"):
                            can_dist_endorse = True
                    else:
                        can_dist = True
                elif next_act == "action_district_approve_workforce":
                    can_dist_wf = True
                elif next_act == "action_chief_approve_escalate":
                    if p.category in (
                        "general_expense", "fixed_asset", "credit_portfolio",
                        "initiative_budget", "loan_disbursement_collection", "loan_outstanding",
                        "deposit", "customer_base", "fx", "digital_banking",
                    ):
                        can_chief_endorse = True
                    else:
                        can_chief_approve = True
                elif next_act == "action_people_solutions_escalate_cpco":
                    can_ps_escalate = True
                elif next_act in ("action_submit_to_committee", "action_cpco_submit_to_committee"):
                    can_submit_committee = True
                elif next_act == "action_committee_approve_resource":
                    can_committee_resource = True
                elif next_act == "action_committee_approve":
                    can_committee_ceo = True
                elif next_act == "action_ceo_approve":
                    can_ceo_approve = True
                elif next_act == "action_ho_endorse_to_cpco":
                    can_ho_endorse_cpco = True
                elif next_act == "action_cpco_endorse_to_solutions":
                    can_cpco_endorse_ops = True
                elif next_act in ("action_ho_approve", "action_approve"):
                    can_ho = True
                else:
                    can_approve = True

            unit.pbms_can_unit_district_approve = can_dist
            unit.pbms_can_unit_district_endorse = can_dist_endorse
            unit.pbms_can_unit_district_approve_workforce = can_dist_wf
            unit.pbms_can_unit_chief_endorse = can_chief_endorse
            unit.pbms_can_unit_chief_approve = can_chief_approve
            unit.pbms_can_unit_ps_escalate = can_ps_escalate
            unit.pbms_can_unit_submit_committee = can_submit_committee
            unit.pbms_can_unit_committee_approve_resource = can_committee_resource
            unit.pbms_can_unit_committee_endorse_ceo = can_committee_ceo
            unit.pbms_can_unit_ceo_approve = can_ceo_approve
            unit.pbms_can_unit_ho_endorse_cpco = can_ho_endorse_cpco
            unit.pbms_can_unit_cpco_endorse_ops = can_cpco_endorse_ops
            unit.pbms_can_unit_ho_approve = can_ho
            unit.pbms_can_unit_approve = can_approve
            unit.pbms_can_unit_reviewer_actions = can_reviewer_wizards

            # 4. Reset to Draft: available if any unit plan can be reset to draft
            can_reset = False
            if is_admin or g_approver:
                can_reset = any(
                    p.state in (
                        "submitted", "district_approved", "district_endorsed", "ho_reviewed",
                        "committee_review", "chief_review", "info_requested", "returned",
                        "people_solutions_review", "cpco_review", "ceo_approval", "ho_endorse", "cpco_endorse"
                    )
                    for p in plans
                )
            else:
                can_reset = any(getattr(p, "can_reset_to_draft", False) for p in plans)
            unit.pbms_can_unit_reset = can_reset

            # 5. Cascade Targets (for District Offices and HO Consolidation Unit)
            can_cascade_ho = False
            can_cascade_dist = False
            is_cascaded = False
            if is_consolidation_unit:
                for p in plans:
                    if p.category not in ("deposit", "customer_base", "fx", "digital_banking"):
                        continue
                    if p.is_targets_cascaded:
                        is_cascaded = True
                    elif (g_ho or g_approver or is_admin) and p.state == "approved":
                        can_cascade_ho = True
            elif unit.work_unit_type in ("district_office", "regional_office") or any(p.is_district_unit for p in plans):
                for p in plans:
                    if p.category not in ("deposit", "customer_base", "fx", "digital_banking"):
                        continue
                    if p.is_targets_cascaded and p.has_cascaded_targets:
                        is_cascaded = True
                    if g_district and not p.is_targets_cascaded and p.has_cascaded_targets:
                        can_cascade_dist = True

            unit.pbms_can_unit_cascade_ho = can_cascade_ho
            unit.pbms_can_unit_cascade_district = can_cascade_dist
            unit.pbms_is_unit_targets_cascaded = is_cascaded

    def action_pbms_unit_consolidate_district(self):
        """Consolidate approved branch plans into this District Office's overview plan."""
        plans = self._pbms_get_unit_plans().filtered(
            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")
        )
        if not plans:
            cat = self.env.context.get("default_line_type") or self.env.context.get("default_category") or "deposit"
            cycle = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)
            if not cycle:
                cycle = self.env["pbms.planning.cycle"].search([], order="id desc", limit=1)
            plan_obj = self.env["pbms.planning.category"]
            dist_plan = plan_obj.with_context(category=cat, default_category=cat, force_consolidate=True)._consolidate_district_plan_data(cycle, self)
            if dist_plan:
                plans = dist_plan
        if not plans:
            raise UserError(_("No mobilization plan found for '%s'.") % (self.name or self.display_name))
        plans.action_consolidate_district_overview()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Consolidation Complete"),
                'message': _("Branch plans consolidated successfully."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_consolidate_ho(self):
        """Consolidate district plans into this Head Office unit's overview plan."""
        plans = self._pbms_get_unit_plans().filtered(
            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding")
        )
        if not plans:
            cat = self.env.context.get("default_category") or self.env.context.get("category") or "deposit"
            cycle = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)
            if not cycle:
                cycle = self.env["pbms.planning.cycle"].search([], order="id desc", limit=1)
            plan_obj = self.env["pbms.planning.category"]
            ho_plan = plan_obj.with_context(category=cat, default_category=cat)._consolidate_ho_plan_data(cycle, self)
            if ho_plan:
                plans = ho_plan
        if not plans:
            raise UserError(_("No mobilization plan found for '%s'.") % (self.name or self.display_name))
        plans.action_consolidate_bank_overview()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Consolidation Complete"),
                'message': _("Bank-wide plan consolidated successfully."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def _pbms_open_unit_reviewer_wizard(self, xml_id):
        """Open a reviewer wizard (Comment, Request Info, Return, Reject) for this unit's active plan(s)."""
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        plans = self._pbms_get_unit_plans()
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        active = plans.filtered(lambda p: p.state not in ("draft", "approved", "rejected") and bool(p.can_use_reviewer_actions or p._bulk_approve_next_action()))
        if not active:
            raise UserError(_("No pending review plans found for '%s'.") % (self.name or self.display_name))
        action = self.env["ir.actions.actions"]._for_xml_id(xml_id)
        action = dict(action)
        action["context"] = {
            "active_ids": active.ids,
            "active_id": active[0].id,
            "active_model": "pbms.planning.category",
            "default_plan_id": active[0].id,
        }
        return action

    def action_pbms_unit_comment(self):

        return self._pbms_open_unit_reviewer_wizard("bunna_pbms.action_pbms_review_comment_wizard")

    def action_pbms_unit_request_info(self):

        return self._pbms_open_unit_reviewer_wizard("bunna_pbms.action_pbms_request_info_wizard")

    def action_pbms_unit_return(self):

        return self._pbms_open_unit_reviewer_wizard("bunna_pbms.action_pbms_return_revision_wizard")

    def action_pbms_unit_reject(self):

        return self._pbms_open_unit_reviewer_wizard("bunna_pbms.action_pbms_reject_wizard")

    def action_pbms_unit_export_excel(self):

        plans = self._pbms_get_unit_plans()

        if not plans:

            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        return plans[0].action_export_excel()

    def action_pbms_unit_import_excel(self):

        target_cat = (

            self.env.context.get("default_line_type")

            or self.env.context.get("target_category")

            or self.env.context.get("active_category")

            or self.env.context.get("active_tab_category")

            or self.env.context.get("default_category")

        )

        all_unit_plans = self._pbms_get_unit_plans()

        editable_plans = all_unit_plans.filtered(lambda p: p.state in ("draft", "returned", "info_requested")) or all_unit_plans

        if not editable_plans:

            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        selected_plan = editable_plans[0]

        if target_cat:

            matching = editable_plans.filtered(lambda p: p.category == target_cat)

            if matching:

                selected_plan = matching[0]

        return selected_plan.with_context(target_category=target_cat, default_format_type=target_cat).action_open_import_wizard()

    def action_pbms_unit_refresh_workforce(self):

        plans = self._pbms_get_unit_plans().filtered(lambda p: p.category == "manpower")

        if not plans:

            raise UserError(_("No workforce plan found for operating unit '%s'.") % (self.name or self.display_name))

        return plans.action_refresh_existing_manpower()

    def action_pbms_unit_cascade_ho(self):

        """Open HO-to-District Target Cascade wizard for this operating unit's plan."""

        plans = self._pbms_get_unit_plans().filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking") and p.state == "approved"

        )

        if not plans:

            raise UserError(_("No approved consolidation plan found for '%s'.") % (self.name or self.display_name))

        target = plans.filtered(lambda p: p.org_unit_type == "head_office" or p.is_head_office_unit)[:1]

        if not target:

            sample = plans[0]

            ho_unit = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")], limit=1)

            if ho_unit:

                target = self.env["pbms.planning.category"].search([

                    ("cycle_id", "=", sample.cycle_id.id),

                    ("category", "=", sample.category),

                    ("org_unit_id", "=", ho_unit.id),

                ], limit=1)

                if not target:

                    sample._consolidate_ho_plan_data(ho_unit)

                    target = self.env["pbms.planning.category"].search([

                        ("cycle_id", "=", sample.cycle_id.id),

                        ("category", "=", sample.category),

                        ("org_unit_id", "=", ho_unit.id),

                    ], limit=1)

                    if target and target.state != "approved":

                        target.sudo().write({"state": "approved"})

        if not target:

            raise UserError(_("No approved Bank-Wide Head Office consolidated plan found to cascade targets."))

        if target.is_targets_cascaded:

            return target.action_already_cascaded_notice()

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_target_cascade_ho_wizard")

        action = dict(action)

        action["context"] = {

            "default_plan_id": target.id,

            "default_cascade_level": "ho_to_district",

            "active_id": target.id,

            "active_ids": [target.id],

            "active_model": "pbms.planning.category",

        }

        return action

    def action_pbms_unit_cascade_district(self):

        """Open District-to-Branch Target Cascade wizard for this district operating unit."""

        plans = self._pbms_get_unit_plans().filtered(

            lambda p: p.category in ("deposit", "customer_base", "fx", "digital_banking")

            and (p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit)

            and p.has_cascaded_targets

        )

        if not plans:

            raise UserError(_("No District plan with cascaded targets found for '%s'.") % (self.name or self.display_name))

        target = plans.filtered(lambda p: not p.is_targets_cascaded)[:1] or plans[:1]

        if target.is_targets_cascaded:

            return target.action_already_cascaded_notice()

        action = self.env["ir.actions.actions"]._for_xml_id("bunna_pbms.action_pbms_target_cascade_district_wizard")

        action = dict(action)

        action["context"] = {

            "default_plan_id": target.id,

            "default_cascade_level": "district_to_branch",

            "active_id": target.id,

            "active_ids": [target.id],

            "active_model": "pbms.planning.category",

        }

        return action

    def action_pbms_unit_already_cascaded_notice(self):

        """Show notice that targets have already been cascaded for this unit's plan."""

        plans = self._pbms_get_unit_plans().filtered(lambda p: p.is_targets_cascaded)

        if plans:

            return plans[0].action_already_cascaded_notice()

        return True

    def _pbms_get_unit_plan_states(self):

        """Return a set of states from all plans for this unit in the current context cycle/category."""

        plans = self._pbms_get_unit_plans()

        return set(plans.mapped("state"))

    def action_pbms_unit_district_approve(self):
        """District Approve plan(s) for this operating unit, approving all child lines."""
        plans = self._pbms_get_unit_plans()
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        if not plans:
            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        target = plans.filtered(
            lambda p: (
                p.state in ("submitted", "district_approved", "info_requested")
                if p.org_unit_type in ("district_office", "regional_office") and p.category != "manpower"
                else p.state in ("submitted", "info_requested")
            )
        )
        if not target:
            if any(p.state in ("approved", "district_endorsed") for p in plans):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Already Processed"),
                        'message': _("The plan for '%s' has already been approved/endorsed.") % (self.name or self.display_name),
                        'type': 'info',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }
            raise UserError(_("No plans pending district approval for '%s'.") % (self.name or self.display_name))

        for p in target:
            if p.category == "manpower":
                p.action_district_approve_workforce()
            else:
                p.action_district_approve()

        is_district_endorse = any(
            p.org_unit_type in ("district_office", "regional_office") or p.is_district_unit or getattr(self, "work_unit_type", False) in ("district_office", "regional_office")
            for p in target
        )
        title = _("District Endorsed Successfully") if is_district_endorse else _("District Approved Successfully")
        msg = (
            _("District Plan has been endorsed and forwarded to Head Office successfully.")
            if is_district_endorse
            else _("Branch plan(s) have been approved at district level.")
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_ho_approve(self):
        """HO / Final Approve plan(s) for this operating unit."""
        plans = self._pbms_get_unit_plans()
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        if not plans:
            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        target = plans.filtered(
            lambda p: (
                p.state in ("district_endorsed", "ho_reviewed")
                if p.org_unit_type in ("district_office", "regional_office") and p.category in ("deposit", "customer_base", "fx", "digital_banking")
                else (
                    p.state in ("submitted", "chief_approved", "ho_reviewed", "info_requested")
                    if p.org_unit_type == "head_office"
                    else p.state in ("district_approved", "district_endorsed", "ho_reviewed")
                )
            )
        )
        if not target:
            if any(p.state == "approved" for p in plans):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Already Approved"),
                        'message': _("The plan for '%s' is already approved.") % (self.name or self.display_name),
                        'type': 'info',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }
            raise UserError(_("No plans pending final approval for '%s'.") % (self.name or self.display_name))

        target.action_ho_approve()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Approved Successfully"),
                'message': _("Plan has been successfully approved at Head Office level."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_approve(self):
        """Execute the current stage approval / escalation action for this operating unit's plan(s)."""
        plans = self._pbms_get_unit_plans()
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        if not plans:
            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        acted = False
        for p in plans:
            method = p._bulk_approve_next_action()
            if method:
                getattr(p, method)()
                acted = True
        if not acted:
            if any(p.state in ("approved", "rejected") for p in plans):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Already Processed"),
                        'message': _("Plan for '%s' has already been approved/processed.") % (self.name or self.display_name),
                        'type': 'info',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }
            raise UserError(_("No plans waiting for your review/approval for '%s'.") % (self.name or self.display_name))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Approved Successfully"),
                'message': _("Plan approval action completed successfully."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_submit(self):
        """Submit plan(s) for this operating unit."""
        plans = self._pbms_get_unit_plans()
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        if not plans:
            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        target = plans.filtered(lambda p: p.state in ("draft", "returned", "info_requested"))
        if not target:
            raise UserError(_("No plans in draft/returned state to submit for '%s'.") % (self.name or self.display_name))

        if ctx_cat:
            target.with_context(submit_single_category=True).action_submit()
        else:
            target.action_submit()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Submitted Successfully"),
                'message': _("Plan has been submitted successfully for review."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_reset(self):
        """Reset plan(s) for this operating unit to draft."""
        plans = self._pbms_get_unit_plans()
        ctx_cat = self.env.context.get("default_line_type") or self.env.context.get("default_category")
        if ctx_cat:
            plans = plans.filtered(lambda p: p.category == ctx_cat)
        if not plans:
            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        is_admin = (
            self.env.user.has_group("bunna_pbms.group_pbms_manager")
            or self.env.user.has_group("base.group_system")
            or self.env.is_admin()
            or self.env.su
            or (hasattr(self.env.user, "_pbms_is_sppmd_admin") and self.env.user._pbms_is_sppmd_admin())
        )
        if is_admin or self.env.user.has_group("bunna_pbms.group_pbms_approver"):
            target = plans.filtered(
                lambda p: p.state in (
                    "submitted", "district_approved", "district_endorsed", "ho_reviewed",
                    "committee_review", "chief_review", "info_requested", "returned",
                    "people_solutions_review", "cpco_review", "ceo_approval", "ho_endorse", "cpco_endorse"
                )
            )
        else:
            target = plans.filtered(lambda p: getattr(p, "can_reset_to_draft", False))

        if not target:
            raise UserError(_("No plans eligible to be reset to draft for '%s'. The reviewer may have already taken action.") % (self.name or self.display_name))

        target.action_reset_to_draft()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Reset to Draft"),
                'message': _("Plan has been reset to draft successfully."),
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_pbms_unit_open_plan(self):

        """Open plan form view for this operating unit."""

        plans = self._pbms_get_unit_plans()

        if not plans:

            raise UserError(_("No plan found for operating unit '%s'.") % (self.name or self.display_name))

        if len(plans) == 1:

            return {

                "type": "ir.actions.act_window",

                "res_model": "pbms.planning.category",

                "res_id": plans.id,

                "view_mode": "form",

                "target": "current",

            }

        return {

            "type": "ir.actions.act_window",

            "name": _("Plans - %s") % (self.name or self.display_name),

            "res_model": "pbms.planning.category",

            "domain": [("id", "in", plans.ids)],

            "view_mode": "list,form",

            "target": "current",

        }

    def action_open_plan(self):

        return self.action_pbms_unit_open_plan()

    def action_plan_dispatch(self):

        method = self.env.context.get("pbms_plan_method")

        if method == "action_district_approve":

            return self.action_pbms_unit_district_approve()

        elif method == "action_district_approve_workforce":

            return self.action_pbms_unit_district_approve()

        elif method == "action_ho_approve":

            return self.action_pbms_unit_ho_approve()

        elif method == "action_submit":

            return self.action_pbms_unit_submit()

        elif method == "action_reset_to_draft":

            return self.action_pbms_unit_reset()

        elif method == "action_export_excel":

            plans = self._pbms_get_unit_plans()

            if plans:

                return plans[0].action_export_excel()

        plans = self._pbms_get_unit_plans()

        if plans and hasattr(plans, method):

            return getattr(plans, method)()

        return False

    def action_plan_wizard(self):

        plans = self._pbms_get_unit_plans()

        if not plans:

            return False

        key = self.env.context.get("pbms_wizard")

        from ast import literal_eval

        wizards = {

            "review_comment": ("bunna_pbms.view_pbms_review_comment_wizard_form", {}),

            "request_info": ("bunna_pbms.view_pbms_request_info_wizard_form", {}),

            "return": ("bunna_pbms.view_pbms_return_plan_wizard_form", {}),

            "reject": ("bunna_pbms.view_pbms_reject_plan_wizard_form", {}),

        }

        if key in wizards:

            xmlid, extra = wizards[key]

            plan = plans[0]

            action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)

            ctx = literal_eval(action.get("context", "{}"))

            ctx.update({

                "default_plan_id": plan.id,

                "active_id": plan.id,

                "active_ids": [plan.id],

                "active_model": "pbms.planning.category",

                **extra,

            })

            action["context"] = ctx

            return action

        return False

