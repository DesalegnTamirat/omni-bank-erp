# -*- coding: utf-8 -*-
from odoo import fields, models, api


class HrSeparationType(models.Model):

    _name = 'hr.separation.type'
    _description = 'Separation Type'
    _order = 'sequence asc, name asc'

    name     = fields.Char(required=True, translate=True)
    code     = fields.Char(
        required=True,
        help='Stable technical key used internally by business logic '
             '(e.g. "termination", "voluntary"). Not shown to end users. '
             'Do not change this once in use — other configuration '
             '(e.g. Clearance Work Unit applicability) may reference it.')
    sequence = fields.Integer(default=10)
    active   = fields.Boolean(default=True)

    is_company_terminated = fields.Boolean(
        string='Company-Initiated Termination',
        help='Flag this type as a company-initiated dismissal/termination. '
             'Used by the Provident Fund eligibility rule (FR-15) to '
             'exclude company-terminated employees regardless of tenure.')

    allow_salary_payment = fields.Boolean(string="Remaining salary", default=True)
    allow_leave_encashment = fields.Boolean(string="Accrued leave pay", default=True)

    default_notice_period = fields.Integer(
        string='Default Notice Period (Days)', default=30,
        help='Default number of days required for notice when submitting a resignation of this type.')

    check_disciplinary = fields.Boolean(
        string='Validate Disciplinary Cases',
        default=False,
        help='If checked, displays a warning if the employee has any active disciplinary cases.'
    )
    check_investigations = fields.Boolean(
        string='Validate Ongoing Investigations', default=True,
        help='If checked, blocks resignation approval if the employee has active investigations.')
    check_commitments = fields.Boolean(
        string='Validate Contractual Commitments', default=True,
        help='If checked, blocks resignation approval if the employee has active training commitments or sponsorships.')
    check_probation = fields.Boolean(
        string='Validate Probation Status', default=True,
        help='If checked, blocks resignation approval if the employee is still on probation.')

    pays_provident_fund = fields.Boolean(
        string='Pays Provident Fund (PF)', default=True,
        help='If disabled, employees separated under this type are never eligible for Provident Fund.'
    )
    pf_min_service_years = fields.Float(
        string='PF Min Service Years', default=2.0,
        help='Minimum service years (joined date to application date) required to be eligible for Provident Fund.')
    pays_severance = fields.Boolean(
        string='Pays Severance', default=True,
        help='If disabled, employees separated under this type are never eligible for Severance.'
    )
    severance_rule_ids = fields.One2many(
        'hr.separation.severance.rule', 'separation_type_id',
        string='Severance Threshold Rules',
        help='Configure minimum service years for severance based on Job Categories.'
    )

    description = fields.Text()
    color       = fields.Integer(string='Color', default=0)
    exit_interview_template_id = fields.Many2one(
        'hr.exit.interview.template',
        string='Default Exit Interview Template',
        help='Template to use when generating an exit interview for this separation type.'
    )

    _code_uniq = models.Constraint(
        'unique(code)', 'Separation Type code must be unique.'
    )
    _name_uniq = models.Constraint(
        'unique(name)', 'Separation Type name must be unique.'
    )


class HrSeparationSeveranceRule(models.Model):
    _name = 'hr.separation.severance.rule'
    _description = 'Severance Threshold Rule by Job Category'

    separation_type_id = fields.Many2one(
        'hr.separation.type', string='Separation Type', required=True, ondelete='cascade'
    )
    def _get_job_categories(self):
        """ Dynamically fetches the selection options from hr.job """
        if 'employee_category' in self.env['hr.job']._fields:
            return self.env['hr.job']._fields['employee_category'].selection
        return []

    employee_category = fields.Selection(
        selection='_get_job_categories',
        string='Job Category', required=True
    )
    min_service_years = fields.Float(
        string='Min Service Years', required=True, default=5.0
    )
    first_year_days = fields.Integer(
        string='First Year (Days)', required=True, default=30,
        help="Number of salary days awarded for the first year of service."
    )
    subsequent_year_days = fields.Integer(
        string='Subsequent Years (Days/Year)', required=True, default=10,
        help="Number of salary days awarded per year after the first year."
    )
    max_severance_months = fields.Integer(
        string='Max Severance (Months)', required=True, default=12,
        help="Maximum total months of salary that can be paid as severance."
    )

    _sql_constraints = [
        ('category_uniq', 'unique(separation_type_id, employee_category)', 'A job category can only have one rule per separation type.')
    ]