# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class InterviewRateSheet(models.Model):
    _name = "interview.rate.sheet"
    _description = "Interview Rate Sheet"
    _order = "name asc"

    name = fields.Char(string="Rate Sheet Name", required=True)
    recruiting_position_id = fields.Many2one("hr.job", string="Recruiting Position")
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("interview.rate.sheet.line", "rate_sheet_id", string="Assessment Criteria", copy=True)
    total_max_marks = fields.Float(string="Total Max Marks", compute="_compute_total_max_marks", store=True)

    @api.depends("line_ids.max_marks")
    def _compute_total_max_marks(self):
        for rec in self:
            rec.total_max_marks = sum(line.max_marks for line in rec.line_ids)

    def unlink(self):
        for rec in self:
            rec.write({"active": False})
        return True


class InterviewRateSheetLine(models.Model):
    _name = "interview.rate.sheet.line"
    _description = "Interview Rate Sheet Line"
    _order = "sequence asc, id asc"

    rate_sheet_id = fields.Many2one("interview.rate.sheet", string="Rate Sheet", ondelete="cascade", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Area of Assessment / Criterion", required=True)
    max_marks = fields.Float(string="Max Marks", required=True, default=10.0)
    description = fields.Text(string="Description / Scoring Guidelines")

    @api.constrains("max_marks")
    def _check_max_marks(self):
        for line in self:
            if line.max_marks <= 0:
                raise ValidationError(_("Max Marks for criterion '%s' must be greater than zero.") % line.name)
