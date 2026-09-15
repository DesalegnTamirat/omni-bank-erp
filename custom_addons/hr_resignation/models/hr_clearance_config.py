from odoo import api, fields, models


# ─────────────────────────────────────────────────────────────────────────────
#  CATEGORY (lookup / configuration)
# ─────────────────────────────────────────────────────────────────────────────

class HrClearanceCategory(models.Model):

    _name        = 'hr.clearance.category'
    _description = 'Clearance Category'
    _order       = 'sequence asc, name asc'

    name     = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color    = fields.Integer(string='Color Index', default=0)
    active   = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)', 'Clearance category name must be unique.'
    )


# ─────────────────────────────────────────────────────────────────────────────
#  TEMPLATE — Checklist Sub-Item (CONFIGURATION)
# ─────────────────────────────────────────────────────────────────────────────

class HrClearanceTemplateItem(models.Model):

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
    note         = fields.Text(string='Guidance Note')


# ─────────────────────────────────────────────────────────────────────────────
#  TEMPLATE — Work Unit (CONFIGURATION — master rule, set up once by HR/POMD)
# ─────────────────────────────────────────────────────────────────────────────

class HrResignationClearanceTemplate(models.Model):

    _name        = 'hr.resignation.clearance.template'
    _description = 'Clearance Work Unit Template'
    _order       = 'category_id, sequence asc'
    _rec_name    = 'work_unit_id'   # work_unit_id is required=True, always set.

    # ── Identity ─────────────────────────────────────────────────────────────
    sequence     = fields.Integer(default=10)
    name         = fields.Char(
        string='Work Unit Name',
        help='Override display name. Defaults to the department name if blank.')
    work_unit_id = fields.Many2one(
        'operating.unit', required=True, string='Operating Unit',
        index=True)
    category_id  = fields.Many2one(
        'hr.clearance.category', string='Category',
        help='Functional grouping (Finance, IT, HR, etc.).')
    active       = fields.Boolean(default=True)

    # ── Responsible / Manager ───────────────────────────────────────────────
    # NOTE: previously defined twice in this class (once with no domain,
    # once with a domain on 'default_operating_unit_id'). The second
    # definition silently overrode the first, and 'default_operating_unit_id'
    # is just the user's personal default OU (single-valued, usually blank),
    # not "which OUs this user belongs to" - hence the empty dropdown.
    # Fixed to use 'operating_unit_ids' (the user's allowed/assigned
    # ── Responsible ──────────────────────────────────────────────────────────
    allowed_user_ids = fields.Many2many(
        'res.users', compute='_compute_allowed_users', string='Allowed Users')

    @api.depends('work_unit_id')
    def _compute_allowed_users(self):
        for rec in self:
            if rec.work_unit_id:
                rec.allowed_user_ids = self.env['res.users'].search([
                    '|',
                    ('default_operating_unit_id', '=', rec.work_unit_id.id),
                    ('assigned_operating_unit_ids', 'in', rec.work_unit_id.id)
                ])
            else:
                rec.allowed_user_ids = False

    responsible_user = fields.Many2one(
        'res.users', required=True, string='Responsible User',
        domain="[('id', 'in', allowed_user_ids)]",
        help='The user who receives clearance tasks for this work unit.')
    manager_user = fields.Many2one(
        'res.users', string='Manager / Escalation Contact',
        domain="[('id', 'in', allowed_user_ids)]",
        help='The manager of this work unit. They will receive notifications '
             'along with the responsible user and receive escalations if overdue.')

    # ── SLA & Mandate ─────────────────────────────────────────────────────────

    is_mandatory = fields.Boolean(
        default=True,
        help='Mandatory: case cannot progress until this line is Cleared or '
             'force-overridden by POMD.  Optional: informational only.')

    sdt_days = fields.Integer(
        string='Standard Delivery Time (Days)', default=3,
        help='Number of days before this clearance is considered overdue.')

    applicable_type_ids = fields.Many2many(
        'hr.separation.type',
        'clearance_template_sep_type_rel',
        'template_id',
        'sep_type_id',
        string='Applies To Separation Types',
        help='Leave empty to apply to ALL separation types.\n'
             'Select one or more types to restrict this work unit to only '
             'those separation scenarios.')

    # ── Checklist sub-items ───────────────────────────────────────────────────
    # NOTE: previously pointed at a nonexistent comodel/inverse pair
    # ('hr.resignation.clearance.template.line' / 'work_unit_id'), which
    # crashed registry setup with "unknown comodel_name". The real
    # checklist model is 'hr.clearance.template.item', whose parent
    # link field is 'template_id'.
    checklist_item_ids = fields.One2many(
        'hr.clearance.template.item', 'template_id',
        string='Checklist Items')

    checklist_count = fields.Integer(
        compute='_compute_checklist_count', store=True, string='# Checklist Items')

    _uniq_work_unit = models.Constraint(
        'unique(work_unit_id)',
        'Each operating unit can appear only once in the clearance template.'
    )

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        if self.work_unit_id and self.work_unit_id.manager_id and self.work_unit_id.manager_id.user_id:
            self.manager_user = self.work_unit_id.manager_id.user_id
        else:
            self.manager_user = False

    @api.depends('checklist_item_ids')
    def _compute_checklist_count(self):
        for rec in self:
            rec.checklist_count = len(rec.checklist_item_ids)