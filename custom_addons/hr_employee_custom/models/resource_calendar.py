# -*- coding:utf-8 -*-
# Migrated from the standalone hr_contract module (models/resource.py)
# so that hr_employee_custom no longer depends on the hr_contract module.
# Fields and logic are unchanged.

from odoo import models, fields
from odoo.fields import Domain


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    def transfer_leaves_to(self, other_calendar, resources=None, from_date=None):
        """
            Transfer some resource.calendar.leaves from 'self' to another calendar 'other_calendar'.
            Transfered leaves linked to `resources` (or all if `resources` is None) and starting
            after 'from_date' (or today if None).
        """
        from_date = from_date or fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        domain = [
            ('calendar_id', 'in', self.ids),
            ('date_from', '>=', from_date),
        ]
        domain = (Domain(domain) & Domain([('resource_id', 'in', resources.ids)])) if resources else Domain(domain)

        self.env['resource.calendar.leaves'].search(domain).write({
            'calendar_id': other_calendar.id,
        })
