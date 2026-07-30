# Copyright 2017 Odoo S.A.
# Copyright 2018 ForgeFlow, S.L.
# License LGPL-3 - See http://www.gnu.org/licenses/lgpl-3.0.html

from odoo import fields, models


class HrAttendanceReason(models.Model):
    _name = "hr.attendance.reason"
    _description = "Attendance Reason"

    active = fields.Boolean(string="Active", default=True, index=True)
    _sql_constraints = [("unique_code", "UNIQUE(code)", "Code must be unique")]

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    # sequence = fields.Integer()
    # company_id = fields.Many2one(
    #     comodel_name="res.company",
    #     string="Company",
    # )
    name = fields.Char(
        string="Reason",
        help="Specifies the reason leaving soon or arriving late",
        required=True,
        index=True,
        translate=True,
    )
    code = fields.Char("Reason Code")
    action_type = fields.Selection([
        ('check_in', 'Check In'),
        ('check_out', 'Check Out'),
        ('both', 'Both'),
    ], string="Action Type", default='both')
    
    show_on_attendance_screen = fields.Boolean(string="Show on attendance screen?")

