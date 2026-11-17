# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class HrVersion(models.Model):
    """
    Employee contract based on the visa, work permits
    allows to configure different Salary structure
    """
    _inherit = 'hr.version'
    _description = 'Employee Contract'


    struct_id = fields.Many2one('hr.payroll.structure', string='Salary Structure')
    schedule_pay = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi-annually', 'Semi-annually'),
        ('annually', 'Annually'),
        ('weekly', 'Weekly'),
        ('bi-weekly', 'Bi-weekly'),
        ('bi-monthly', 'Bi-monthly'),
    ], string='Scheduled Pay', index=True, default='monthly',
    help="Defines the frequency of the wage payment.")
    resource_calendar_id = fields.Many2one(required=True, help="Employee's working schedule.")
    hra = fields.Monetary(string='HRA', help="House rent allowance.")
    travel_allowance = fields.Monetary(string="Travel Allowance", help="Travel allowance")
    da = fields.Monetary(string="DA", help="Dearness allowance")
    meal_allowance = fields.Monetary(string="Meal Allowance", help="Meal allowance")
    medical_allowance = fields.Monetary(string="Medical Allowance", help="Medical allowance")
    other_allowance = fields.Monetary(string="Other Allowance", help="Other allowances")
    type_id = fields.Many2one('hr.contract.type', string="Employee Category",
                              required=True, help="Employee category",
                              default=lambda self: self.env['hr.contract.type'].search([], limit=1))

    # Salary helper / alias
    salary = fields.Float(string='Salary', compute='_compute_salary', inverse='_inverse_salary', store=True)

    # Tax exemptions
    total_tax_exemption = fields.Float(string='Total Tax Exemption', digits=(16, 2), default=0.0)
    fuel_exempted_1 = fields.Integer(string='Fuel Exempted', default=0)

    # Allowances
    housing_allowance = fields.Float(string='Housing Allowance', digits=(16, 2))
    fuel_allowance = fields.Float(string='Fuel Allowance', digits=(16, 2))
    transportation_allowance = fields.Float(string='Transportation Allowance', digits=(16, 2))
    hardship_allowance = fields.Float(string='Hardship Allowance', digits=(16, 2))
    mobile_allowance = fields.Float(string='Mobile Allowance', digits=(16, 2))
    disturbance_allowance = fields.Float(string='Disturbance Allowance', digits=(16, 2))
    special_car_allowance = fields.Float(string='Special Car Allowance', digits=(16, 2))
    cash_indemnity = fields.Float(string='Cash Indemnity Allowance', digits=(16, 2))
    acting_allowance = fields.Float(string='Acting Allowance', digits=(16, 2))
    representation_allowance = fields.Float(string='Representation Allowance', digits=(16, 2))

    # Deductions
    cost_sharing = fields.Float(string='Cost Sharing', digits=(16, 2))
    od_deduction = fields.Float(string='OD Deduction', digits=(16, 2))
    asbeza_deduction = fields.Float(string='ASBEZA Deduction', digits=(16, 2))
    labour_union_contribution = fields.Float(string='Labour Union Contribution', digits=(16, 2))
    other_deductions = fields.Float(string='Other Deductions', digits=(16, 2))
    penalty_amount = fields.Float(string='Penalty Amount', digits=(16, 2))
    cash_indemnity_bank = fields.Float(string='Cash Indemnity Bank', digits=(16, 2))
    court_deductions = fields.Float(string='Court and Other Deductions', digits=(16, 2))

    @api.depends('wage')
    def _compute_salary(self):
        for rec in self:
            rec.salary = rec.wage

    def _inverse_salary(self):
        for rec in self:
            if rec.salary:
                rec.wage = rec.salary

    @api.onchange('employee_id', 'special_car_allowance')
    def _onchange_employee_fuel_allowance(self):
        liters_map = {
            'I': 40, 'II': 40, 'III': 40, 'IV': 40, 'V': 40,
            'VI': 60, 'VII': 60,
            'VIII': 80, 'IX': 80, 'X': 80,
            'XI': 100, 'XII': 100, 'XIII': 100, 'XIV': 100, 'XV': 100, 'XVI': 100,
            'XVII': 100, 'XVIII': 100, 'XIX': 100, 'XX': 100,
            'XXI': 100, 'XXII': 100, 'XXIII': 100, 'XXIV': 100, 'XXV': 100, 'XXVI': 100, 'XXVII': 100,
            '1': 40, '2': 40, '3': 40, '4': 40, '5': 40,
            '6': 60, '7': 60,
            '8': 80, '9': 80, '10': 80,
            '11': 100, '12': 100, '13': 100, '14': 100, '15': 100, '16': 100,
            '17': 100, '18': 100, '19': 100, '20': 100,
            '21': 100, '22': 100, '23': 100, '24': 100, '25': 100, '26': 100, '27': 100,
        }
        rep_map = {
            'XIII': 4342.0, 'XIV': 5052.0, 'XV': 6273.0, 'XVI': 8790.0, 'XVII': 14359.0, 'XVIII': 32717.0,
            '13': 4342.0, '14': 5052.0, '15': 6273.0, '16': 8790.0, '17': 14359.0, '18': 32717.0,
        }
        for rec in self:
            if rec.special_car_allowance:
                rec.fuel_allowance = 0.0
            elif not rec.fuel_allowance and rec.employee_id:
                raw_code = (getattr(rec.employee_id, 'grade_id', None) and rec.employee_id.grade_id.grade_code or '').strip().upper()
                clean_code = raw_code.replace('GRADE', '').strip()
                liters = liters_map.get(clean_code, 0)
                if liters:
                    rec.fuel_allowance = 86.0 * liters
            # Auto-populate representation allowance for senior executive grades if unset
            if not rec.representation_allowance and rec.employee_id:
                raw_code = (getattr(rec.employee_id, 'grade_id', None) and rec.employee_id.grade_id.grade_code or '').strip().upper()
                clean_code = raw_code.replace('GRADE', '').strip()
                if clean_code in rep_map:
                    rec.representation_allowance = rep_map[clean_code]

    @api.model
    def _get_whitelist_fields_from_template(self):
        # Retrieve the list from the parent class
        res = super()._get_whitelist_fields_from_template()

        # Add your custom field to the list
        res.append('struct_id')

        return res
    def get_all_structures(self):
        """
        @return: the structures linked to the given contracts, ordered by hierachy (parent=False first,
                 then first level children and so on) and without duplicata
        """
        structures = self.mapped('struct_id')
        if not structures:
            return []
        # YTI TODO return browse records
        return list(set(structures._get_parent_structure().ids))

    def get_attribute(self, code, attribute):
        return self.env['hr.contract.advantage.template'].search([('code', '=', code)], limit=1)[attribute]

    def set_attribute_value(self, code, active):
        for contract in self:
            if active:
                value = self.env['hr.contract.advantage.template'].search([('code', '=', code)], limit=1).default_value
                contract[code] = value
            else:
                contract[code] = 0.0


class HrContractAdvantageTemplate(models.Model):
    _name = 'hr.contract.advantage.template'
    _description = "Employee's Advantage on Contract"

    name = fields.Char('Name', required=True)
    code = fields.Char('Code', required=True)
    lower_bound = fields.Float('Lower Bound', help="Lower bound authorized by the employer for this advantage")
    upper_bound = fields.Float('Upper Bound', help="Upper bound authorized by the employer for this advantage")
    default_value = fields.Float('Default value for this advantage')
