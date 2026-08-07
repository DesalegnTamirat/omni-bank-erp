# Copyright 2018-2019 Brainbean Apps (https://brainbeanapps.com)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models, fields


class HrLeaveAllocationAccruement(models.Model):

    _name = 'hr.leave.allocation.accruement'
    _description = 'Leave Allocation Accruement Entry'
    _order = 'accrued_on ASC, id ASC'
    _log_access = True

    leave_allocation_id = fields.Many2one(
        string='Leave Allocation',
        comodel_name='hr.leave.allocation',
        required=True,
        readonly=True,
        ondelete='cascade',
        help='Reference to the leave allocation record',
    )
    days_accrued = fields.Float(
        string='Number of Days',
        readonly=True,
        required=True,
        help='Number of days accrued (positive) or used (negative)',
    )
    accrued_on = fields.Date(
        string='Accruement Date',
        readonly=True,
        required=True,
        help='Date when this accruement was recorded',
    )
    reason = fields.Char(
        string='Reason',
        readonly=True,
        required=True,
        help='Description of why this accruement occurred',
    )

    def name_get(self):
        """Return a human-readable name for the accruement entry."""
        result = []
        for record in self:
            name = f"{record.accrued_on} - {record.reason} ({record.days_accrued:+.2f} days)"
            result.append((record.id, name))
        return result