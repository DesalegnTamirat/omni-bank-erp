
from collections import defaultdict
from datetime import datetime, date

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import format_date
import logging
_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_refuse(self):

        # Run standard Odoo behavior first
        res = super(HrLeave, self).action_refuse()

        for leave in self:
            if leave.holiday_status_id.id in(80,5):
                self.env.cr.execute(
                    'SELECT update_scheduled_balance_refused(%s)',
                    (leave.id,)
                )

        return res
