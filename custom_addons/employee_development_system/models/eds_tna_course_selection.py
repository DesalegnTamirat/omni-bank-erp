# -*- coding: utf-8 -*-
from odoo import models


class EdsTnaCycleCourseSelection(models.Model):
    _inherit = 'eds.tna.cycle'

    def _set_all_course_plan_selections(self, selected):
        self.ensure_one()
        self._require_cycle_staff()
        self.check_access('write')

        # A dirty summary can create new course rows; include those in the bulk choice.
        if self.course_demand_dirty or not self.course_demand_last_sync:
            self._sync_course_demand()
        self.course_summary_ids.write({'selected_for_planning': selected})
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_select_all_course_demand(self):
        return self._set_all_course_plan_selections(True)

    def action_deselect_all_course_demand(self):
        return self._set_all_course_plan_selections(False)
