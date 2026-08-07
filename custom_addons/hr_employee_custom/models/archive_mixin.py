# -*- coding: utf-8 -*-
"""
ArchiveMixin
============
Drop this mixin on any model to:
  - Block unlink() — raises ValidationError instead of deleting
  - Provide action_archive / action_unarchive convenience methods
  - Require an `active` field on the model (Boolean, default=True)

Usage:
    class MyModel(models.Model):
        _name = 'my.model'
        _inherit = ['archive.mixin']

        active = fields.Boolean(default=True)
"""
from odoo import models, _
from odoo.exceptions import ValidationError


class ArchiveMixin(models.AbstractModel):
    _name = 'archive.mixin'
    _description = 'Archive Instead of Delete Mixin'

    def unlink(self):
        """Block all deletion — archive instead."""
        raise ValidationError(_(
            'Deleting records is not allowed. '
            'Please use the Archive option to deactivate records.'
        ))

    def action_archive(self):
        """Set active=False for all records in self."""
        return self.write({'active': False})

    def action_unarchive(self):
        """Set active=True for all records in self."""
        return self.write({'active': True})
