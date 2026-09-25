# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class RecruitmentQualifications(models.Model):
    _name = "recruitment.qualification"
    _description = "Recruitment Qualifications"
    _rec_name = "display_name"

    name = fields.Char(string="Name", related="display_name", store=False)
    qualification = fields.Char(string="Qualification Level", required=True)
    specialization = fields.Char(string="Specialization / Field of Study")
    status = fields.Selection([('yes', 'Y'), ('no', 'N')],
                              string='Status', default='yes')

    display_name = fields.Char(string="Qualification", compute="_compute_display_name", store=True)

    def _auto_init(self):
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE recruitment_qualification 
                    SET display_name = COALESCE(
                        NULLIF(TRIM(
                            CASE 
                                WHEN qualification IS NOT NULL AND qualification != '' AND specialization IS NOT NULL AND specialization != '' 
                                THEN qualification || ' - ' || specialization
                                WHEN qualification IS NOT NULL AND qualification != '' 
                                THEN qualification
                                WHEN specialization IS NOT NULL AND specialization != '' 
                                THEN specialization
                                ELSE NULL
                            END
                        ), ''), 'Qualification'
                    )
                    WHERE display_name IS NULL OR display_name = '' OR display_name = 'New Qualification';
                """)
        except Exception as e:
            pass
        return res

    @api.depends('qualification', 'specialization')
    def _compute_display_name(self):
        for rec in self:
            q_str = (rec.qualification or "").strip()
            s_str = (rec.specialization or "").strip()
            if q_str and s_str:
                rec.display_name = f"{q_str} - {s_str}"
            elif q_str:
                rec.display_name = q_str
            elif s_str:
                rec.display_name = s_str
            else:
                rec.display_name = _("Qualification")

