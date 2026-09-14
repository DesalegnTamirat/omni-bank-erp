# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'

    @api.model
    def _reflect_fields(self, model_names):
        res = super()._reflect_fields(model_names)
        # Clear ormcache('stable') so newly upserted fields are immediately visible to _reflect_selections
        self.env.registry.clear_cache('stable')
        return res


class IrModelFieldsSelection(models.Model):
    _inherit = 'ir.model.fields.selection'

    @api.model
    def _reflect_selections(self, model_names):
        # Clear ormcache('stable') before reflecting selection options to avoid KeyError on new fields
        self.env.registry.clear_cache('stable')
        try:
            return super()._reflect_selections(model_names)
        except KeyError as e:
            missing_field_name = str(e).strip("'\"")
            _logger.warning(
                "Cache miss in _reflect_selections for field %s. Forcing _reflect_fields and retrying.",
                missing_field_name
            )
            self.env['ir.model.fields']._reflect_fields(model_names)
            self.env.registry.clear_cache('stable')
            return super()._reflect_selections(model_names)
