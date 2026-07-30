import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # ─── Fields ───────────────────────────────────────────────────────────────
    manager_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Manager',
          # ← made mandatory
        tracking=True,
    )

    operating_unit_id = fields.Many2one(
        comodel_name='operating.unit',
        string='Operating Unit',
        required=True,
    )
    active = fields.Boolean(default=True)

    # ─── Name validation ──────────────────────────────────────────────────────

    # Only letters (any language) and spaces allowed
    _NAME_RE = re.compile(r"^[\w\s]+$", re.UNICODE)
    _NAME_ALPHA_RE = re.compile(r"^[^\d_]*$", re.UNICODE)

    def _validate_name(self, name):
        """Raise ValidationError if name contains digits or special characters."""
        if not name:
            return
        # Strip to check non-empty
        stripped = name.strip()
        if not stripped:
            raise ValidationError(_('Department name cannot be blank or spaces only.'))
        # Reject digits
        if re.search(r'\d', stripped):
            raise ValidationError(_(
                'Department name "%s" is invalid.\n'
                'Numbers are not allowed in the department name.'
            ) % stripped)
        # Reject special characters — allow only letters and spaces
        if re.search(r'[^a-zA-Z\u00C0-\u024F\s]', stripped):
            raise ValidationError(_(
                'Department name "%s" is invalid.\n'
                'Special characters are not allowed. Use letters and spaces only.'
            ) % stripped)

    @api.constrains('name')
    def _check_name(self):
        """Server-side constraint — enforced on every save."""
        for rec in self:
            self._validate_name(rec.name)

    @api.onchange('name')
    def _onchange_name(self):
        """Client-side warning — instant feedback while the user types."""
        if not self.name:
            return
        stripped = self.name.strip()
        if re.search(r'\d', stripped):
            return {
                'warning': {
                    'title': _('Invalid Department Name'),
                    'message': _(
                        'Numbers are not allowed in the department name.\n'
                        'Please use letters and spaces only.'
                    ),
                }
            }
        if re.search(r'[^a-zA-Z\u00C0-\u024F\s]', stripped):
            return {
                'warning': {
                    'title': _('Invalid Department Name'),
                    'message': _(
                        'Special characters are not allowed in the department name.\n'
                        'Please use letters and spaces only.'
                    ),
                }
            }

    # ─── Notification helper ──────────────────────────────────────────────────

    def _notify(self, message, notif_type='success', title=None, sticky=False):
        """Return a display_notification client action.

        Args:
            message   (str): Body text shown to the user.
            notif_type (str): 'success' | 'warning' | 'danger' | 'info'
            title     (str): Optional title; defaults to capitalised type.
            sticky   (bool): Keep notification until dismissed.
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title or notif_type.capitalize(),
                'message': message,
                'type': notif_type,
                'sticky': sticky,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ─── ORM overrides ────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Notify on single-record creation (wizard / quick-create path)
        if len(records) == 1:
            return records
        return records

    def write(self, vals):
        """Override write to fire an edit notification after save."""
        result = super().write(vals)
        return result

    def unlink(self):
        """Prevent deletion when employees are still assigned."""
        for rec in self:
            count = self.env['hr.employee'].search_count([
                ('department_id', '=', rec.id)
            ])
            if count:
                raise ValidationError(_(
                    'Cannot delete Department "%(name)s" because '
                    '%(count)s employee(s) are assigned.',
                    name=rec.name,
                    count=count,
                ))
        return super().unlink()

    # ─── Button actions ───────────────────────────────────────────────────────

    def action_save_department(self):
        self.ensure_one()
        # Look up the real action so the client gets the correct views array
        action = self.env['ir.actions.act_window']._for_xml_id('hr.hr_department_tree_action')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Saved Successfully'),
                'message': _('Department "%s" has been saved.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': action,
            },
        }

    def action_toggle_active(self):
        """Toggle the active state of a department.

        Business rule (original logic preserved):
        - Cannot disable a department that still has active employees.
        - Fires a success notification on change.
        - Fires a danger notification (via ValidationError) when blocked.
        """
        for rec in self:

            if rec.active:
                # ── Guard: block disable when active employees exist ──────────
                count = self.env['hr.employee'].search_count([
                    ('department_id', '=', rec.id),
                    ('active', '=', True),
                ])
                if count:
                    raise ValidationError(_(
                        'Cannot disable Department "%(name)s" because '
                        '%(count)s active employee(s) still exist.',
                        name=rec.name,
                        count=count,
                    ))

            rec.active = not rec.active

        # ── Notification ──────────────────────────────────────────────────────
        if len(self) == 1:
            if self.active:
                message = _('Department "%s" has been enabled.') % self.name
            else:
                message = _('Department "%s" has been disabled.') % self.name
        else:
            message = _('%s department(s) updated successfully.') % len(self)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }





