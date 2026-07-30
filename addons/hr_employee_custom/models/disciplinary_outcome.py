from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
from odoo.exceptions import UserError

class DisciplinaryOutcome(models.Model):
    _name = 'discipline.outcome'
    _description = 'Disciplinary Outcome'
    _rec_name = "disciplinary_action"
    disciplinary_action=fields.Many2one("discipline.category",string="Disciplinary Action")
    start_date=fields.Date(string="Start Date")
    end_date=fields.Date(string="End Date")
    status = fields.Char(string="Status", help="Status")
    outcome_details=fields.One2many("discipline.outcome.count","outcome_id","Disciplinary Outcome")


class Ourcome(models.Model):
    _name = "discipline.outcome.count"
    outcome_id=fields.Many2one("discipline.outcome",string="Disciplinary Outcome Count",help="Disciplinary Outcome count")
    action_count = fields.Integer(string="Action Count",help="Action Count")
    action_name = fields.Many2one("discipline.category",string="Action Name")
    salary_impact=fields.Float(string="Salary Impact-in Days",help="Salary Impact")
    salary_impact_percent=fields.Float(string="Salary Impact-in %",help="Salary Impact")
    fine_imposed=fields.Float(string="Additional Fine",help="Additional Fine")
    comments =fields.Char(string="Comments",help="Comments")
    status = fields.Char(string="Status", help="Status")
