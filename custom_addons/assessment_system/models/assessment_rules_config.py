# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AssessmentWeightProfile(models.Model):

    _name = "assessment.weight.profile"
    _description = "Assessment Weight Distribution Profile"
    _order = "candidate_type asc, role_level asc, id desc"

    name = fields.Char(string="Profile Name", compute="_compute_name", store=True, readonly=False, default="Weight Profile")
    active = fields.Boolean(default=True)
    
    candidate_type = fields.Selection([
        ("external", "External Applicant"),
        ("internal", "Internal Applicant"),
        ("transfer", "Transfer Applicant"),
    ], string="Candidate Type", required=True, default="external")

    role_level = fields.Selection([
        ("managerial", "Managerial"),
        ("non_managerial", "Non-Managerial"),
        ("junior", "Junior"),
        ("all", "All Levels"),
    ], string="Role Level", required=True, default="non_managerial")

    line_ids = fields.One2many(
        "assessment.weight.profile.line",
        "profile_id",
        string="Component Weights",
        copy=True
    )

    total_weight = fields.Float(
        string="Total Weight (%)",
        compute="_compute_total_weight",
        store=True,
        help="Invariant: Must always equal 100.0%"
    )

    notes = fields.Text(string="Description / Policy Reference")

    @api.depends("candidate_type", "role_level")
    def _compute_name(self):
        for rec in self:
            c_type = dict(self._fields["candidate_type"].selection).get(rec.candidate_type, "")
            r_level = dict(self._fields["role_level"].selection).get(rec.role_level, "")
            rec.name = f"{c_type} - {r_level} Weight Profile" if c_type and r_level else "New Weight Profile"

    @api.depends("line_ids.weight_percentage")
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = round(sum(line.weight_percentage for line in rec.line_ids), 2)
            if rec.notes and "BR-AMS" in rec.notes:
                rec.notes = rec.notes.replace(" ", "").replace(" ", "").strip()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("notes") and "BR-AMS" in vals["notes"]:
                vals["notes"] = vals["notes"].replace(" ", "").replace(" ", "").strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("notes") and "BR-AMS" in vals["notes"]:
            vals["notes"] = vals["notes"].replace(" ", "").replace("", "").strip()
        return super().write(vals)

    @api.constrains("line_ids", "total_weight")
    def _check_total_weight(self):
        for rec in self:
            if rec.line_ids and round(rec.total_weight, 2) != 100.0:
                raise ValidationError(_(
                    "Validation Error: Total weight for profile '%(profile)s' must sum to exactly 100.0%% (Current Total: %(total)s%%).",
                    profile=rec.name,
                    total=rec.total_weight
                ))

    @api.model
    def get_profile_for_candidate(self, candidate_type, role_level="non_managerial"):
        """
        Lookup the matching active weight profile for a given candidate type & role level.
        Falls back to 'all' role levels if exact match is not found.
        """
        profile = self.search([
            ("candidate_type", "=", candidate_type),
            ("role_level", "=", role_level),
            ("active", "=", True)
        ], limit=1)
        if not profile:
            profile = self.search([
                ("candidate_type", "=", candidate_type),
                ("role_level", "=", "all"),
                ("active", "=", True)
            ], limit=1)
        return profile


class AssessmentWeightProfileLine(models.Model):
    """
    Assessment Weight Profile Line
    ==============================
    Defines the individual assessment component and its weight percentage.
    """
    _name = "assessment.weight.profile.line"
    _description = "Assessment Weight Profile Component Line"
    _order = "sequence asc, id asc"

    profile_id = fields.Many2one(
        "assessment.weight.profile",
        string="Weight Profile",
        required=True,
        ondelete="cascade"
    )
    sequence = fields.Integer(string="Sequence", default=10)
    
    component = fields.Selection([
        ("exam", "Written Exam Score"),
        ("interview", "Competency Interview Score"),
        ("pms", "PMS / Performance Rating Score"),
        ("app_date", "Application Date Seniority"),
        ("experience", "Total Experience Score"),
        ("service_location", "Service in Current Location"),
        ("recommendation", "Managerial Recommendation"),
    ], string="Assessment Component", required=True)

    weight_percentage = fields.Float(
        string="Weight (%)",
        required=True,
        default=0.0,
        help="Weight percentage contribution of this component to final score"
    )

    minimum_pass_score = fields.Float(
        string="Minimum Pass Score (%)",
        default=50.0,
        help="Floor requirement. Score below this disqualifies candidate."
    )

    @api.constrains("weight_percentage")
    def _check_weight_percentage(self):
        for line in self:
            if line.weight_percentage < 0 or line.weight_percentage > 100:
                raise ValidationError(_("Weight percentage must be between 0.0% and 100.0%."))


class AssessmentSystemParameter(models.Model):

    _name = "assessment.system.parameter"
    _description = "Assessment Global System Parameters"
    _order = "key asc"

    key = fields.Char(string="Parameter Key", required=True, index=True)
    name = fields.Char(string="Parameter Label", required=True)
    value_type = fields.Selection([
        ("integer", "Integer / Number"),
        ("float", "Float / Decimal"),
        ("char", "Text / String"),
        ("boolean", "Boolean (Yes/No)"),
    ], string="Data Type", required=True, default="integer")

    value_integer = fields.Integer(string="Integer Value")
    value_float = fields.Float(string="Float Value")
    value_char = fields.Char(string="String Value")
    value_boolean = fields.Boolean(string="Boolean Value")
    description = fields.Text(string="Description / Policy Rule")

    @api.model
    def get_param(self, key, default=None):
        param = self.search([("key", "=", key)], limit=1)
        if not param:
            return default
        if param.value_type == "integer":
            return param.value_integer
        elif param.value_type == "float":
            return param.value_float
        elif param.value_type == "boolean":
            return param.value_boolean
        return param.value_char
