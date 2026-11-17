from odoo import api, models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _dms_grant_viewer_to_internal_users(self):
        """Make every internal user a Documents Viewer, explicitly.

        base.group_user already implies Viewer, but on databases that ran an older version
        (which removed that link) existing users may not have picked it up. Adding the
        membership directly guarantees the Documents menu and read access for all employees.
        Admins are untouched, and new users still get Viewer through the implied link.
        """
        viewer = self.env.ref('documents_lite.group_dms_user')
        users = self.env['res.users'].with_context(active_test=False).search(
            [('share', '=', False), ('group_ids', 'not in', viewer.id)])
        if users:
            viewer.write({'user_ids': [(4, uid) for uid in users.ids]})
