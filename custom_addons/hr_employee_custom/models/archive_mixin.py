# -*- coding: utf-8 -*-
"""
ArchiveMixin
============
Mixin for Soft Delete (Archiving instead of Hard Delete).

Usage:
    class MyModel(models.Model):
        _name = 'my.model'
        _inherit = ['archive.mixin']

        active = fields.Boolean(default=True)
"""
from odoo import models, fields, _


class ArchiveMixin(models.AbstractModel):
    _name = 'archive.mixin'
    _description = 'Archive Instead of Delete (Soft Delete Mixin)'

    active = fields.Boolean(
        string='Active',
        default=True,
        help="Set to false to soft delete / archive the record.",
    )

    def unlink(self):
        """Soft delete: Set active=False for all records instead of removing from DB."""
        records_to_archive = self.filtered(lambda r: 'active' in r._fields)
        if records_to_archive:
            records_to_archive.write({'active': False})
        return True

    def action_archive(self):
        """Set active=False for all records in self."""
        return self.write({'active': False})

    def action_unarchive(self):
        """Set active=True for all records in self."""
        return self.write({'active': True})
