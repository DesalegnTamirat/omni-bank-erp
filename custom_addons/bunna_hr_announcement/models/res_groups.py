# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

ANNOUNCEMENT_ROLES = [
    'group_announcement_drafter',
    'group_announcement_publisher',
    'group_announcement_manager',
]


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _bunna_announcement_setup_privileges(self):
        """Odoo 19 lists a group on the user form only if it belongs to a privilege.

        All three announcement roles share ONE privilege, which the user form shows
        as a single dropdown: No / Drafter / Publisher / Administrator.
        Safe to run again, and it tidies up the one-row-per-role privileges
        created by the previous version.
        """
        if 'res.groups.privilege' not in self.env or 'privilege_id' not in self._fields:
            _logger.warning("bunna privilege: this Odoo has no group privileges, nothing to do")
            return
        Privilege = self.env['res.groups.privilege']
        category = self.env.ref(
            'bunna_hr_announcement.module_category_bunna_announcement', raise_if_not_found=False)

        privilege = self.env.ref('bunna_hr_announcement.privilege_announcement_role', raise_if_not_found=False)
        if not privilege:
            vals = {'name': 'Announcement Role'}
            if category and 'category_id' in Privilege._fields:
                vals['category_id'] = category.id
            if 'sequence' in Privilege._fields:
                vals['sequence'] = 10
            privilege = Privilege.create(vals)
            self.env['ir.model.data'].create({
                'module': 'bunna_hr_announcement',
                'name': 'privilege_announcement_role',
                'model': Privilege._name,
                'res_id': privilege.id,
                'noupdate': True,
            })
            _logger.info("bunna privilege: created the 'Announcement Role' dropdown")

        old_privileges = Privilege
        for xmlid in ANNOUNCEMENT_ROLES:
            group = self.env.ref('bunna_hr_announcement.%s' % xmlid, raise_if_not_found=False)
            if not group:
                continue
            if group.privilege_id and group.privilege_id != privilege:
                old_privileges |= group.privilege_id
            if group.privilege_id != privilege:
                group.privilege_id = privilege.id
                _logger.info("bunna privilege: %s moved into the single dropdown", xmlid)

        # remove the earlier one-role privileges once they are empty
        for old in old_privileges:
            if not old.group_ids:
                old.unlink()
