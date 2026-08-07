# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
from odoo.exceptions import UserError
class InheritEmployee(models.Model):
    _inherit = 'hr.employee'

    discipline_count = fields.Integer(compute="_compute_discipline_count")

    def _compute_discipline_count(self):
        all_actions = self.env['disciplinary.action'].read_group([
            ('employee_name', 'in', self.ids),
            ('state', '=', 'action'),
        ], fields=['employee_name'], groupby=['employee_name'])
        mapping = dict([(action['employee_name'][0], action['employee_name_count']) for action in all_actions])
        for employee in self:
            employee.discipline_count = mapping.get(employee.id, 0)

class class_classification(models.Model):
    _name = "class.classification"
    _description = "Class Classification"
    _rec_name = "classification_name"
    classification_name = fields.Char(string="Classification Name",help="Classification Name")
    classification_code = fields.Char(string="Classification Code",help="Classification Code")
    active = fields.Boolean(string="Active",help="Active")
class CategoryDiscipline(models.Model):
    _name = 'discipline.category'
    _description = 'Reason Category'

    # Discipline Categories

    code = fields.Char(string="Code", required=True, help="Category code")
    name = fields.Char(string="Name", required=True, help="Category name")
    category_type = fields.Selection([('disciplinary', 'Disciplinary Category'), ('action', 'Action Category')],
                                   string="Category Type", help="Choose the category type disciplinary or action")
    description = fields.Text(string="Details", help="Details for this category")


class DisciplinaryAction(models.Model):
    _name = 'disciplinary.action'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Disciplinary Action"

    state = fields.Selection([
        ('draft', 'Draft'),
        ('explain', 'Waiting Explanation'),
        ('submitted', 'Waiting Action'),
        ('action', 'Action Validated'),
        ('cancel', 'Cancelled'),

    ], default='draft', tracking=True)

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    action_date = fields.Date(string="Action Date", help="Action Date")
    action_start_date = fields.Date(string="Action Start Date", help="Action Start Date")
    action_end_date = fields.Date(string="Action End Date", help="Action End Date")

    employee_name = fields.Many2one('hr.employee', string='Employee', required=True, help="Employee name")
    contract_name = fields.Many2one("hr.version",string="contract",help="Contract name")
    department_name = fields.Many2one('hr.department', string='Department', required=True, help="Department name")
    discipline_reason = fields.Many2one('discipline.category', string='Reason', required=True, help="Choose a disciplinary reason")
    explanation = fields.Text(string="Explanation by Employee", help='Employee have to give Explanation'
                                                                     'to manager about the violation of discipline')
    action = fields.Many2one('discipline.category', string="Action", help="Choose an action for this disciplinary action")
    read_only = fields.Boolean(compute="get_user", default=True)
    warning_letter = fields.Html(string="Warning Letter")
    suspension_letter = fields.Html(string="Suspension Letter")
    termination_letter = fields.Html(string="Termination Letter")
    warning = fields.Integer(default=False)
    action_details = fields.Text(string="Action Details", help="Give the details for this action")
    attachment_ids = fields.Many2many('ir.attachment', string="Attachments",
                                      help="Employee can submit any documents which supports their explanation")
    note = fields.Text(string="Internal Note")
    joined_date = fields.Date(string="Joined Date", help="Employee joining date")
    job_grade = fields.Many2one("employee.grade", string='Job Grade', help="Job Grade")
    case_classification = fields.Many2one("class.classification",string="Case Classification",help="Case Classification")
    # assigning the sequence for the record


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('disciplinary.action')
        return super().create(vals_list)
    # @api.depends('employee_name')
    # def get_running_employee(self):
    #     print("self", self)
    #     contract_info = self.env["hr.version"].search([('state', '=', 'open')])
    #     print("contract_info=========================================", contract_info)
    # Check the user is a manager or employee
    @api.depends('read_only')
    def get_user(self):
        if self.env.user.has_group('hr.group_hr_manager'):
            self.read_only = True
        else:
            self.read_only = False

    # Check the Action Selected
    @api.onchange('action')
    def onchange_action(self):
        if self.action.name == 'Written Warning':
            self.warning = 1
        elif self.action.name == 'Suspend the Employee for one Week':
            self.warning = 2
        elif self.action.name == 'Terminate the Employee':
            self.warning = 3
        elif self.action.name == 'No Action':
            self.warning = 4
        elif self.action.name == "Demote":
            self.warning = 5
        else:
            self.warning = 6

    @api.onchange('employee_name')
    @api.depends('employee_name')
    def onchange_employee_name(self):
        department = self.env['hr.employee'].search([('name', '=', self.employee_name.name)])
        self.department_name = department.department_id.id
        self.joined_date = department.contract_id.date_start
        self.contract_name = department.contract_id
        self.job_grade = department.contract_id.job_grade
        if self.state == 'action':
            raise ValidationError(_('You Can not edit a Validated Action !!'))

    # @api.depends('employee_id')
    # def _compute_employee_contract(self):
    #     for contract in self.filtered('employee_id'):
    #         contract.job_id = contract.employee_id.job_id
    #         contract.department_id = contract.employee_id.department_id
    #         contract.resource_calendar_id = contract.employee_id.resource_calendar_id
    #         contract.company_id = contract.employee_id.company_id

    # @api.onchange('contract_name')
    # @api.depends('contract_name')
    # def onchange_contract_name(self):
    #     contract = self.env['hr.version'].search([('name', '=', self.employee_id.name)])
    #     self.contract_name = contract.name.id
    #
    #     if self.state == 'action':
    #         raise ValidationError(_('You Can not edit a Validated Action !!'))

    @api.onchange('discipline_reason')
    @api.depends('discipline_reason')
    def onchange_reason(self):
        if self.state == 'action':
            raise ValidationError(_('You Can not edit a Validated Action !!'))

    def assign_function(self):

        for rec in self:
            rec.state = 'explain'

    def cancel_function(self):
        for rec in self:
            rec.state = 'cancel'

    def set_to_function(self):
        for rec in self:
            rec.state = 'draft'

    def action_function(self):
        for rec in self:
            if not rec.action:
                raise ValidationError(_('You have to select an Action !!'))

            if self.warning == 1:
                if not rec.warning_letter or rec.warning_letter == '<p><br></p>':
                    raise ValidationError(_('You have to fill up the Warning Letter in Action Information !!'))

            elif self.warning == 2:
                if not rec.suspension_letter or rec.suspension_letter == '<p><br></p>':
                    raise ValidationError(_('You have to fill up the Suspension Letter in Action Information !!'))

            elif self.warning == 3:
                if not rec.termination_letter or rec.termination_letter == '<p><br></p>':
                    raise ValidationError(_('You have to fill up the Termination Letter in  Action Information !!'))

            elif self.warning == 4:
                self.action_details = "No Action Proceed"

            elif self.warning == 5:
                salary_contract_list = []
                if not self.job_grade:
                    raise UserError(_("please Enter Job Grade "))
                else:
                    for val in self.job_grade.salary_contract_multi_id:
                        if not val.start_date:
                            raise UserError(_("please Enter Start Date "))
                        elif not val.end_date:
                            raise UserError(_("please Enter end Date "))
                        else:
                            re_instating = self.env["re.instating"].search([("id", "=", self.id)])
                            # print(re_instating)
                            # PAYROLL MODULE NOT INSTALLED — "contract_salary_rule" (hr.contract.salary)
                            # and val.salary_rule are both commented out elsewhere since they depend
                            # on hr.salary.rule. Restore the two commented blocks below (and remove
                            # the placeholders) once the payroll module is installed.
                            if val.internal_name !='wage':
                                # my_json = {"contract_salary_rule": val.salary_rule.id,
                                #            "contract_internal_name": val.internal_name,
                                #            "contract_value": val.value, "contract_start_date": val.start_date,
                                #            "contract_end_date": datetime.today()}
                                my_json = {"contract_value": val.value, "contract_start_date": val.start_date,
                                           "contract_end_date": datetime.today()}
                                salary_contract_list.append((0, 0, my_json))
                            else:
                                # my_json = {"contract_salary_rule": val.salary_rule.id,
                                #            "contract_internal_name": val.internal_name,
                                #            "contract_value": val.value,
                                #            "contract_start_date": val.start_date,
                                #            "contract_end_date": val.end_date
                                #            }
                                my_json = {"contract_value": val.value,
                                           "contract_start_date": val.start_date,
                                           "contract_end_date": val.end_date
                                           }
                                salary_contract_list.append((0, 0, my_json))
                            contract_info = self.env["hr.version"].search([('job_grade', '=', self.job_grade.id)])
                            for job_val in contract_info:
                                # if not job_val.contract_multi_id:
                                for val3 in job_val.contract_multi_id:
                                    val3.unlink()
                                job_val.write({"contract_multi_id": salary_contract_list})

            elif self.warning == 5:
                if not rec.action_details:
                    raise ValidationError(_('You have to fill up the  Action Information !!'))
            rec.state = 'action'

    def explanation_function(self):
        for rec in self:
            if not rec.explanation:
                raise ValidationError(_('You must give an explanation !!'))

        self.write({
            'state': 'submitted'
        })
