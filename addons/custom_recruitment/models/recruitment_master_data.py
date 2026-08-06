# -*- coding: utf-8 -*-
from odoo import fields, models


class RecruitmentSkill(models.Model):
    _name = 'recruitment.skill'
    _description = 'Recruitment Skill'

    name = fields.Char(string='Skill Name')
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


class RecruitmentCertification(models.Model):
    _name = 'recruitment.certification'
    _description = 'Recruitment Certification'

    name = fields.Char(string='Certification Name')
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
