# -*- coding: utf-8 -*-

from odoo import models, fields


class HrQualificationInfoEmployee(models.Model):
    _name = "hr.qualification.info.employee"
    _description = "Employee Qualification Profile"
    _rec_name = "qualification"

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    qualification = fields.Char(string="Qualification")
    requirement = fields.Char(string="Requirement(CGPA)")
    response = fields.Char(string="Response")


class HrExperienceInfoEmployee(models.Model):
    _name = "hr.experience.info.employee"
    _description = "Employee Experience Profile"
    _rec_name = "experience"

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    experience = fields.Char(string="Experience")
    requirement = fields.Float(string="Requirement(Years)")
    response = fields.Float(string="Response")


class HrCompetenciesInfoEmployee(models.Model):
    _name = "hr.competencies.info.employee"
    _description = "Employee Competencies Profile"
    _rec_name = "competencies"

    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    competencies = fields.Char(string="Competencies")
    requirement = fields.Char(string="Requirement")
    response = fields.Char(string="Response")
