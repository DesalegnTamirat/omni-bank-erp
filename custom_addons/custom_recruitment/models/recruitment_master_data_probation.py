# -*- coding: utf-8 -*-
"""
Recruitment criteria and Probation Assessment models — fully owned by custom_recruitment.

Migrated from hr_employee_custom:
  - recruitment.competency
  - recruitment.experience
  - recruitment.qualification
  - vacancy.workunit  (SQL view)
  - emp.probation.criteria
  - probation.assessment.form + criteria + delegation team

hr_employee_custom now depends on custom_recruitment so these models are
available when hr_employee_hrMaster.py references them.
"""
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError




# ── Probation Criteria (lookup) ───────────────────────────────────────────────

class EmployeeProbationCriteria(models.Model):
    _name = "emp.probation.criteria"
    _rec_name = "emp_evaluation_criteria"

    emp_evaluation_criteria = fields.Char(string="Evaluation Criteria")
    coefficient = fields.Integer(string="Coefficient")


# ── Probation Assessment Form ─────────────────────────────────────────────────

class ProbationAssessmentForm(models.Model):
    _name = "probation.assessment.form"
    _rec_name = "name_of_probationer"

    prob_sequence = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New')
    )
    name_of_probationer = fields.Many2one(
        "hr.version", string="Name of Probationer",
        domain=[('state', '=', 'probation')]
    )
    position_title = fields.Char(string="Position Title", readonly=True)
    place_of_assessment = fields.Char(string="Place of Assessment")
    employment_date = fields.Date(
        string="Employment Date", related="name_of_probationer.first_contract_date"
    )
    from_date = fields.Date(string="From", related="name_of_probationer.date_start")
    to_date = fields.Date(string="To", related="name_of_probationer.date_end")
    pro_assess_form = fields.One2many(
        "probation.assessment.form.criteria", "prob_cri", string="Probation Criteria"
    )
    evaluation_period = fields.Char(
        string="Evaluation Period", compute="_compute_evaluation_period", store=True
    )
    in_charge = fields.Many2one("hr.employee", string="TDD In-charge Officer")
    sender = fields.Char(string="Sender")
    state = fields.Selection([
        ("draft", "Draft"),
        ("notify", "Notified HR"),
        ("evaluate", "Evaluated"),
        ("confirm_permenancy", "Confirmed"),
        ("reject", "Rejected"),
        ('terminate_contract', 'Terminated'),
        ("inform_in_charge", "Informed"),
    ], string="State", default="draft")
    status = fields.Selection([
        ("draft", "Draft"),
        ("notify_deligation", "Notify"),
        ("assess_evaluate", "Evaluate"),
    ], string="Status", default="draft")
    total = fields.Integer(string="Total", compute="_compute_total")
    emp_prob_delig_team_id = fields.One2many(
        "emp.probation.delegation.team", 'new_emp_prob_del_id',
        string="Probation Assessment Delegation Team"
    )
    assessment_comments = fields.Text(string="Comments")

    def _compute_total(self):
        for rec in self:
            rec.total = sum(val.score for val in rec.pro_assess_form)

    def notify_deligation(self):
        for com in self.emp_prob_delig_team_id:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                self.mail_channel_msgs(usr.id, self.prob_sequence, self.position_title)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                self.mail_channel_msgs(usr.id, self.prob_sequence, self.position_title)
        self.status = "notify_deligation"
        self.state = "notify"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Sent'),
                'message': _('Delegation team notified successfully.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = (
            "Dear Committee<br>Please approve the Probation Assessment of following details<br>"
            "Reference number is <b>%s</b><br>Position: <b>%s</b><br><br>Kindly approve."
        ) % (ref, arg1)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def assess_evaluate(self):
        n = 0
        usr = self.env.user.name
        for val in self.emp_prob_delig_team_id:
            if val.status == "unavailable":
                if usr == val.employee_name.name:
                    raise ValidationError("Sorry!! you can not evaluate this bid")
                n += 1
                val.approve = True
                break
            else:
                if val.employee_name.name == usr:
                    n += 1
                    val.approve = True
                    break
        if n == 0:
            raise ValidationError("Sorry!! You are not assigned for this Evaluation")
        cnt = sum(1 for v in self.emp_prob_delig_team_id if v.approve)
        if cnt == len(self.emp_prob_delig_team_id):
            self.status = "assess_evaluate"
            self.state = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Evaluation Recorded'),
                'message': _('Evaluation recorded.'),
                'type': 'success',
                'sticky': False,
            },
        }

    @api.constrains('name_of_probationer')
    def set_position_title(self):
        for record in self:
            if record.name_of_probationer:
                record.position_title = record.name_of_probationer.job_id.name
            else:
                record.position_title = False

    @api.constrains('name_of_probationer')
    def set_position_place(self):
        for record in self:
            if record.name_of_probationer:
                record.place_of_assessment = record.name_of_probationer.operating_unit_id.name
            else:
                record.place_of_assessment = False

    @api.depends('from_date', 'to_date')
    def _compute_evaluation_period(self):
        for record in self:
            if record.from_date and record.to_date:
                record.evaluation_period = (
                    f"from {record.from_date.strftime('%Y-%m-%d')} "
                    f"to {record.to_date.strftime('%Y-%m-%d')}"
                )
            else:
                record.evaluation_period = False

    def inform_in_charge(self):
        for rec in self:
            usr = self.env["res.partner"].search([("name", "=", rec.in_charge.name)])
            msg = (
                "Dear Sir<br>Here are the details of Probation Assessment of<br>"
                "Employee: <b>%s</b><br>Position: <b>%s</b><br>Work Unit: <b>%s</b><br>"
                "Please look into it."
            ) % (
                rec.name_of_probationer.employee_id.name if rec.name_of_probationer else '',
                rec.position_title or '',
                rec.place_of_assessment or '',
            )
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[usr.id])
            channel.message_post(body=msg, message_type='comment', subtype_xmlid='mail.mt_comment')
        self.state = "inform_in_charge"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('In-charge Informed'),
                'message': _('TDD In-charge Officer has been informed.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def confirm_permenancy(self):
        val = self.env["hr.version"].search([
            ("employee_id", "=", self.name_of_probationer.employee_id.id)
        ])
        val.write({"approval_status": "approved", "state": "open"})
        self.state = "confirm_permenancy"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Permanency Confirmed'),
                'message': _('Employee confirmed as permanent.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def reject(self):
        self.state = "reject"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Rejected'),
                'message': _('Probation rejected.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    def terminate_contract(self):
        self.state = "terminate_contract"
        val = self.env["hr.version"].search([
            ("employee_id", "=", self.name_of_probationer.employee_id.id)
        ])
        val.write({"state": "cancel"})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contract Terminated'),
                'message': _('Contract terminated.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('prob_sequence') or vals.get('prob_sequence') == _('New'):
                vals['prob_sequence'] = (
                    self.env['ir.sequence'].next_by_code('probation.assessment.form') or _('New')
                )
        return super().create(vals_list)


# ── Probation Assessment Criteria Line ────────────────────────────────────────

class ProbationAssessmentCriteriaForm(models.Model):
    _name = "probation.assessment.form.criteria"

    evaluation_criteria = fields.Many2one("emp.probation.criteria", string="Evaluation Criteria")
    rating = fields.Selection([
        ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")
    ], string="Rating")
    coefficient = fields.Integer(string="Coefficient", related="evaluation_criteria.coefficient")
    score = fields.Integer(string="Score", readonly=True, compute="_compute_score")
    prob_cri = fields.Many2one("probation.assessment.form", string="Probation Criteria")

    def _compute_score(self):
        for det in self:
            if det.rating and det.coefficient:
                det.score = int(det.rating) * det.coefficient
            else:
                det.score = 0


# ── Probation Delegation Team ─────────────────────────────────────────────────

class EmpProbationDelegation(models.Model):
    _name = "emp.probation.delegation.team"

    role = fields.Selection([
        ("chair_person", "Chair Person"),
        ("member", "Member"),
        ("secretary", "Secretary"),
        ("member_secretary", "Member & Secretary"),
    ], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(
        string="Operating Unit",
        related="employee_name.employee_id.default_operating_unit_id.name"
    )
    status = fields.Selection([
        ("active", "Active"), ("unavailable", "Unavailable")
    ], string="Status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(
        string="Alt. Operating Unit",
        related="alternate_committee_member.employee_id.default_operating_unit_id.name"
    )
    approve = fields.Boolean(string="Approve", readonly=True)
    new_emp_prob_del_id = fields.Many2one(
        "probation.assessment.form", string="Probation Assessment"
    )
