# -*- coding: utf-8 -*-

from odoo import models


class HrEmployeeNoTrack(models.Model):
    _inherit = 'hr.employee'

    def _track_subtype(self, init_values):
        """Disable all automatic tracking notifications on hr.employee."""
        return False

    def _message_track(self, fields_iter, initial_values_dict):
        """Disable field change tracking messages."""
        return  {}


class HrVersionNoTrack(models.Model):
    """Silence hr.version tracking — it is written during every stored-field
    recomputation of hr.employee.current_version_id, which runs for all
    3800+ employees during module upgrades, causing a self-deadlock."""
    _inherit = 'hr.version'

    def _track_subtype(self, init_values):
        return False

    def _message_track(self, fields_iter, initial_values_dict):
        return  {}
