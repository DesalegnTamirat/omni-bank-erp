# -*- coding: utf-8 -*-
from odoo import fields, models


class RecruitmentSkill(models.Model):
    _name = 'recruitment.skill'
    _description = 'Recruitment Skill'

    name = fields.Char(string='Skill Name', required=True)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


class RecruitmentCertification(models.Model):
    _name = 'recruitment.certification'
    _description = 'Recruitment Certification'

    name = fields.Char(string='Certification Name', required=True)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


class RecruitmentFieldOfStudy(models.Model):
    _name = 'recruitment.field.of.study'
    _description = 'Recruitment Field of Study'

    name = fields.Char(string='Field of Study', required=True)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


class RecruitmentInstitution(models.Model):
    _name = 'recruitment.institution'
    _description = 'Recruitment University / Institution'

    name = fields.Char(string='University / Institution', required=True)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

