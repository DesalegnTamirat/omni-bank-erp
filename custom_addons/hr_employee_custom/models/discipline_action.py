from odoo import api, models, fields, _
from odoo import models, fields
from odoo.http import request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import base64
import mimetypes
from odoo.exceptions import ValidationError


class DisciplinaryAction(models.Model):
    _name = "discipline.action"
    _inherit = "mail.thread"
    _rec_name = "employee_name"

    reference= fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_name = fields.Many2one("hr.employee", string="Employee Name", required=True)
    emp_id =fields.Integer(string="Emp ID")
    operating_unit = fields.Char(string="Work Location", related="employee_name.default_operating_unit_id.name")
    position = fields.Char(string="Job Position", related="employee_name.job_position.name")
    breach = fields.Many2one("discipline.category", string="Breach", required=True)
    appeal_with_in = fields.Integer(string="Appeal With In")
    breach_reference = fields.Text(string="Breach Reference", required=True)
    description = fields.Text(string="Description")
    breach_date = fields.Date(string="Breach Date")
    breach_count = fields.Integer(string="Breach Count")
    disciplinary_measure = fields.Char(string="Disciplinary Measure")
    wage = fields.Char(string="Basic Salary")
    salary_impact = fields.Float(string="Salary Impact-in Days")
    salary_impact_percentage = fields.Float(string="Salary Impact-in %")
    additional_fine= fields.Float(string="Additional Fine")
    fine_imposed = fields.Float(string="Total Fine Imposed")
    additional_comments= fields.Char(string="Additional Comments")
    additional_penalty = fields.Float(string="Additional Penalty")
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    penalty_effective_date = fields.Date(string="Penalty Effective Date")
    state = fields.Selection([("notify", "Notified")], string="State")
    status = fields.Selection(
        [("in_progress", "In Progress"), ("appeal", "Appeal"), ("approved", "Approved"), ("revoked", "Revoked")],
        string="Status", default="in_progress")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('discipline.action') or _('New')
        return super().create(vals_list)
    
    def fetch_data(self):
        p_emp_id = self.employee_name.id
        p_breach_id = self.breach.id
        self.env.cr.execute('SELECT disciplinary_action(%s,%s)', (p_emp_id, p_breach_id))
    
    def mail_channel_msgs1(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Alert!! <br><br>A Discplinary action is raised on you.<br><br>
    		             Disciplinary Action Reference: <b><u>%s</u></b> <br>
                         You can Appeal to this action with in <b><u>%s</u></b> days.<br><br>
                       _________________________""" % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def notify(self):
        usr = self.env["res.partner"].search([("name", "=", self.employee_name.name)])
        self.mail_channel_msgs1(usr.id, self.breach_reference, self.appeal_with_in)

        val = {
		    'disc_action_ref': self.reference,
            'employee_name': self.employee_name.name,
            'operating_unit': self.operating_unit,
            'position': self.position,
            'breach': self.breach.name,
            'breach_reference': self.breach_reference,
            'description': self.description,
            'breach_date': self.breach_date,
            'breach_count': self.breach_count,
            'disciplinary_measure': self.disciplinary_measure
        }
        self.env["discipline.appeal"].create(val)
        my_val = self.env["hr.employee"].search([("name", "=", self.employee_name.name)])
        lst = []
        value = {
		    'reference': self.reference,
			'breach_count': self.breach_count,
			'breach':self.breach.name,
			'penalty_effective_date': self.penalty_effective_date,
			'fine_imposed':self.fine_imposed,
			'status': self.status
		}
        lst.append((0, 0, value))
        my_val.write({
            'emp_disc_records_id': lst
                    })
		
        self.state = "notify"


class DisciplineAppeal(models.Model):
    _name = "discipline.appeal"
    _inherit = "mail.thread"
    _rec_name = "employee_name"
  
    disc_action_ref = fields.Char(string="Reference")
    employee_name = fields.Char(string="Employee Name")
    operating_unit = fields.Char(string="Work Location")
    position = fields.Char(string="Job Position")
    breach = fields.Char(string="Breach")
    breach_reference = fields.Text(string="Breach Reference")
    description = fields.Text(string="Description")
    breach_date = fields.Date(string="Breach Date")
    breach_count = fields.Integer(string="Breach Count")
    disciplinary_measure = fields.Char(string="Disciplinary Measure")
    appeal_date = fields.Date(string="Appeal Date")
    explanation = fields.Text(string="Explanation")
    penalty_effective_date = fields.Date(string="Penalty Effective Date")
    state = fields.Selection([("appeal", "Appeal"), ("approve", "Approved"), ("reject", "Rejected")], string="State")

    def appeal(self):
        parent = self.env["hr.employee"].search([("name", "=", self.employee_name)])
        usr = self.env["res.partner"].search([("name", "=", parent.parent_id.name)])
        msg1 = "I have submitted my appeal to the action imposed on me with following details"
        msg2 = "I request you kindly look in to it"
        self.mail_channel_msgs1(usr.id, parent.parent_id.name, msg1, self.breach_reference, msg2)
        vals = self.env["discipline.action"].search([("breach_reference", "=", self.breach_reference)])
        value = {
            'status': "appeal"
        }
        vals.write(value)
        self.state = "appeal"

    def mail_channel_msgs1(self, rec_id, ref, arg1, arg2,arg3):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear %s<br><br>%s<br><br>
        Breach Reference: <b><u>%s</u></b><br><br>%s<br><br>
                   _________________________""" % (ref, arg1, arg2, arg3)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        vals = self.env["discipline.action"].search([("breach_reference", "=", self.breach_reference)])
        value = {
            'status': "appeal"
        }
        vals.write(value)
        self.state = "appeal"

    def approve(self):
        usr1 = self.env["res.users"].search([("name", "=", self.employee_name)])
        usr = self.env["res.partner"].search([("id", "=", usr1.partner_id.id)])
        msg="Your Appeal for Disciplinary action Imposed on you is accepted, and the action is Revoked"
        self.mail_channel_msgs(usr.id, self.employee_name, msg)
        self.message_post(body="Disciplinary Action Appeal is Accepted")
        vals = self.env["discipline.action"].search([("breach_reference", "=", self.breach_reference)])
        value = {
            'status': "revoked"
        }
        vals.write(value)
        self.state = "approve"

    def reject(self):
        if self.penalty_effective_date:
            val = self.env["discipline.action"].search(
                [('reference', '=', self.disc_action_ref), ('employee_name', "=", self.employee_name), ('breach_reference', "=", self.breach_reference)])
            p_id = val.id
            # f_rate = self.fuel_rate or 0.0
            cr = self.env.cr
            cr.execute("SELECT populate_disciplinary_penalty(%s)", (p_id,))
            cr.commit()

            # self.populate_disciplinary_penalty(self.id)

            usr1 = self.env["res.users"].search([("name", "=", self.employee_name)])
            usr = self.env["res.partner"].search([("name", "=", self.employee_name)])
            msg = "Your Appeal for Disciplinary action Imposed on you is Rejected"
            self.mail_channel_msgs(usr.id, self.employee_name, msg)
            self.message_post(body="Disciplinary Action Appeal is Rejected")
            vals = self.env["discipline.action"].search([("breach_reference", "=", self.breach_reference)])
            value = {
                'penalty_effective_date': self.penalty_effective_date,
                'status': "approved"
            }
            vals.write(value)
            self.state = "reject"
        else:
            raise ValidationError('Please give penalty_effective_date before Rejecting Appeal')

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear %s<br><br>%s<br><br>_________________________""" % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
class DisciplinaryPenalty(models.Model):
    _name = "disciplinary.penalty"

    employee_id = fields.Many2one("hr.employee", string="Employee Id")
    penalty_amount = fields.Float(string="Panalty Amount")
    contract_id = fields.Integer(string="Contract Id")
    structure_id = fields.Integer(string="Structure Id")
    penalty_date = fields.Date(string="Penalty Date")
    discipline_id = fields.Integer(string="Discipline Id")
    status = fields.Selection(
        [("draft", "Draft"), ("transferred", "Transferred")],
        string="Status", default="draft")
#

class BonusPenalty(models.Model):
    _name = "bonus.penalty"
    _description = "Bonus Penalty"
    _rec_name = "disciplinary_measure"
    disciplinary_measure = fields.Many2one("discipline.category", string="Disciplinary Measure")
    penalty_factor = fields.Float(string="Penalty Factor")
    active = fields.Boolean(string="Active", help="Active")



