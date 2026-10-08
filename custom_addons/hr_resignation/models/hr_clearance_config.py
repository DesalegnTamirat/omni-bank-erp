from odoo import api, fields, models, _
from odoo.exceptions import UserError

# ─────────────────────────────────────────────────────────────────────────────
#  TEMPLATE — Checklist Sub-Item (CONFIGURATION)
# ─────────────────────────────────────────────────────────────────────────────
# Defines specific tasks (e.g., "Return Laptop", "Handover ID") that must be
# completed as part of a larger clearance work unit.
# ─────────────────────────────────────────────────────────────────────────────

class HrClearanceTemplateItem(models.Model):
    """
    Clearance Template Checklist Item
    Represents an individual sub-task that belongs to a clearance work unit.
    These tasks are generated for the responsible user during the clearance process.
    """

    _name        = 'hr.clearance.template.item'
    _description = 'Clearance Template Checklist Item'
    _order       = 'sequence asc'

    template_id  = fields.Many2one(
        'hr.resignation.clearance.template',
        required=True, ondelete='cascade', index=True)
    sequence     = fields.Integer(default=10)
    name         = fields.Char(required=True, string='Task / Item')
    is_mandatory = fields.Boolean(
        default=True,
        help='If checked, this sub-item must be completed before the parent '
             'clearance line can be approved.')
    active = fields.Boolean(default=True, string="Active")
    note         = fields.Text(string='Guidance Note')

    def unlink(self):
        for rec in self:
            rec.active = False
        return True

# ─────────────────────────────────────────────────────────────────────────────
#  TEMPLATE — Work Unit (CONFIGURATION)
# ─────────────────────────────────────────────────────────────────────────────
# Master configuration for a clearance work unit (e.g., IT Dept, Finance Dept).
# Defines which department needs to sign off on a resignation, who is responsible,
# and what SLA (Standard Delivery Time) applies. Set up once by HR/POMD.
# ─────────────────────────────────────────────────────────────────────────────

class HrResignationClearanceTemplate(models.Model):
    """
    Clearance Work Unit Template
    Defines a clearance step required during the employee separation process.
    When a resignation is approved, records from this model are instantiated
    """

    _name        = 'hr.resignation.clearance.template'
    _description = 'Clearance Work Unit Template'
    _order       = 'sequence asc'
    _rec_name    = 'work_unit_id'   # work_unit_id is required=True, always set.

    def action_view_archived_items(self):
        self.ensure_one()
        return {
            'name': _('Archived Tasks'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.clearance.template.item',
            'view_mode': 'list,form',
            'domain': [('template_id', '=', self.id), ('active', '=', False)],
            'context': {'default_template_id': self.id, 'active_test': False},
        }

    # ── Identity ─────────────────────────────────────────────────────────────
    sequence     = fields.Integer(default=10)
    name         = fields.Char(
        string='Work Unit Name',
        help='Override display name. Defaults to the department name if blank.')
    work_unit_id = fields.Many2one(
        'operating.unit', required=True, string='Operating Unit',
        index=True)
    active       = fields.Boolean(default=True)

    # ── Responsible / Manager ───────────────────────────────────────────────
    # We compute the allowed users based on the selected operating unit.
    # Users whose default or assigned operating unit matches the selected one
    # will be available in the dropdown.
    allowed_user_ids = fields.Many2many(
        'res.users', compute='_compute_allowed_users', string='Allowed Users')

    @api.depends('work_unit_id')
    def _compute_allowed_users(self):
        for rec in self:
            if rec.work_unit_id:
                domain = [
                    '|',
                    ('default_operating_unit_id', '=', rec.work_unit_id.id),
                    ('assigned_operating_unit_ids', 'in', rec.work_unit_id.id)
                ]
                
                user_ids = set()
                
                # Add users whose employee record is in this operating unit
                if 'operating_unit_id' in self.env['hr.employee']._fields:
                    emps = self.env['hr.employee'].sudo().search([('operating_unit_id', '=', rec.work_unit_id.id)])
                    user_ids.update(emps.mapped('user_id').ids)
                
                if 'department_id' in self.env['hr.employee']._fields and 'operating_unit_id' in self.env['hr.department']._fields:
                    emps = self.env['hr.employee'].sudo().search([('department_id.operating_unit_id', '=', rec.work_unit_id.id)])
                    user_ids.update(emps.mapped('user_id').ids)
                
                if user_ids:
                    domain = ['|', ('id', 'in', list(user_ids))] + domain
                    
                rec.allowed_user_ids = self.env['res.users'].search(domain)
            else:
                rec.allowed_user_ids = False

    responsible_user = fields.Many2one(
        'res.users', required=True, string='Responsible User',
        domain="[('id', 'in', allowed_user_ids)]",
        help='The user who receives clearance tasks for this work unit.')
    # ── SLA & Mandate ─────────────────────────────────────────────────────────

    is_mandatory = fields.Boolean(
        default=True,
        help='Mandatory: case cannot progress until this line is Cleared or '
             'force-overridden by POMD.  Optional: informational only.')

    sdt_days = fields.Integer(
        string='Standard Delivery Time (Days)', default=3,
        help='Number of days before this clearance is considered overdue.')



    # ── Checklist sub-items ───────────────────────────────────────────────────
    checklist_item_ids = fields.One2many(
        'hr.clearance.template.item', 'template_id',
        string='Checklist Items')

    checklist_count = fields.Integer(
        compute='_compute_checklist_count', store=True, string='# Checklist Items')

    _uniq_work_unit = models.Constraint(
        'unique(work_unit_id)',
        'Each operating unit can appear only once in the clearance template.'
    )

    @api.depends('checklist_item_ids')
    def _compute_checklist_count(self):
        for rec in self:
            rec.checklist_count = len(rec.checklist_item_ids)