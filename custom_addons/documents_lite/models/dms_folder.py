from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import sql

# The kinds of target an access rule can have, in the order they appear on the folder form.
ACCESS_TARGET_FIELDS = ('user_id', 'group_id', 'department_id', 'operating_unit_id', 'manager_unit_id')


class DmsFolder(models.Model):
    _name = 'dms.folder'
    _description = 'Document Folder'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(string='Enabled', default=True)
    status = fields.Selection(
        [('enabled', 'Enabled'), ('disabled', 'Disabled')], string='Status',
        compute='_compute_status', store=True, index=True)
    disabled_by_folder = fields.Boolean(
        copy=False, help="Disabled because a parent folder was disabled; enabled again with it.")
    parent_id = fields.Many2one('dms.folder', string='Parent Folder', index=True, ondelete='restrict')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('dms.folder', 'parent_id', string='Sub-folders')
    color = fields.Integer()
    description = fields.Text()
    company_id = fields.Many2one(
        'res.company', string='Company',
        help="Leave empty to share the folder between all companies.")
    access_ids = fields.One2many('dms.folder.access', 'folder_id', string='Access Rules', copy=True)
    inherit_access = fields.Boolean(
        string='Inherit Parent Access', default=True,
        help="Also grant everything granted on the parent folder. Untick to define access from scratch.")
    # Effective access (own rules + inherited ones), used by the record rules.
    restricted = fields.Boolean(compute='_compute_restricted', store=True)
    read_user_ids = fields.Many2many(
        'res.users', 'dms_folder_read_user_rel', 'folder_id', 'user_id',
        compute='_compute_access_users', store=True, recursive=True)
    read_group_ids = fields.Many2many(
        'res.groups', 'dms_folder_read_group_rel', 'folder_id', 'group_id',
        compute='_compute_access_groups', store=True, recursive=True)
    write_user_ids = fields.Many2many(
        'res.users', 'dms_folder_write_user_rel', 'folder_id', 'user_id',
        compute='_compute_access_users', store=True, recursive=True)
    write_group_ids = fields.Many2many(
        'res.groups', 'dms_folder_write_group_rel', 'folder_id', 'group_id',
        compute='_compute_access_groups', store=True, recursive=True)
    read_department_ids = fields.Many2many(
        'hr.department', 'dms_folder_read_dept_rel', 'folder_id', 'department_id',
        compute='_compute_access_departments', store=True, recursive=True)
    write_department_ids = fields.Many2many(
        'hr.department', 'dms_folder_write_dept_rel', 'folder_id', 'department_id',
        compute='_compute_access_departments', store=True, recursive=True)
    read_operating_unit_ids = fields.Many2many(
        'operating.unit', 'dms_folder_read_ou_rel', 'folder_id', 'operating_unit_id',
        compute='_compute_access_units', store=True, recursive=True)
    write_operating_unit_ids = fields.Many2many(
        'operating.unit', 'dms_folder_write_ou_rel', 'folder_id', 'operating_unit_id',
        compute='_compute_access_units', store=True, recursive=True)
    document_count = fields.Integer(compute='_compute_document_count')
    display_name = fields.Char(recursive=True)

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if self._has_cycle():
            raise ValidationError(_('A folder cannot be its own ancestor.'))

    # Effective access = own rules + (when "Inherit Parent Access") the parent's effective access.
    #
    # One small compute per kind of target (users / groups / departments / operating units),
    # each depending only on its own two parent fields. A single method computing all nine
    # fields made every field depend on every other one, which sent Odoo's dependency walker
    # through millions of paths (minutes to open the folder form or save an access rule).
    def _effective(self, folder, target, write_field, read_field, extra=None):
        """(read set, write set) of one kind of target for one folder.

        ``extra`` maps a set of rules to more records of the same kind (e.g. the users who
        manage the operating units named by the rules).
        """
        rules = folder.access_ids
        writes = rules.filtered(lambda r: r.permission == 'write')
        parent = folder.parent_id if folder.inherit_access else folder.browse()
        read = rules[target] | parent[read_field]
        write = writes[target] | parent[write_field]
        if extra:
            read |= extra(rules)
            write |= extra(writes)
        return read, write

    @staticmethod
    def _unit_manager_users(rules):
        """Users of the managers (operating.unit.manager_id -> hr.employee) of the rules' units."""
        return rules.manager_unit_id.manager_id.user_id

    @api.depends('inherit_access', 'parent_id', 'parent_id.read_user_ids', 'parent_id.write_user_ids',
                 'access_ids.user_id', 'access_ids.permission', 'access_ids.manager_unit_id',
                 'access_ids.manager_unit_id.manager_id.user_id')
    def _compute_access_users(self):
        for folder in self:
            folder.read_user_ids, folder.write_user_ids = self._effective(
                folder, 'user_id', 'write_user_ids', 'read_user_ids', extra=self._unit_manager_users)

    @api.depends('inherit_access', 'parent_id', 'parent_id.read_group_ids', 'parent_id.write_group_ids',
                 'access_ids.group_id', 'access_ids.permission')
    def _compute_access_groups(self):
        for folder in self:
            folder.read_group_ids, folder.write_group_ids = self._effective(
                folder, 'group_id', 'write_group_ids', 'read_group_ids')

    @api.depends('inherit_access', 'parent_id', 'parent_id.read_department_ids',
                 'parent_id.write_department_ids', 'access_ids.department_id', 'access_ids.permission')
    def _compute_access_departments(self):
        for folder in self:
            folder.read_department_ids, folder.write_department_ids = self._effective(
                folder, 'department_id', 'write_department_ids', 'read_department_ids')

    @api.depends('inherit_access', 'parent_id', 'parent_id.read_operating_unit_ids',
                 'parent_id.write_operating_unit_ids', 'access_ids.operating_unit_id',
                 'access_ids.permission')
    def _compute_access_units(self):
        for folder in self:
            folder.read_operating_unit_ids, folder.write_operating_unit_ids = self._effective(
                folder, 'operating_unit_id', 'write_operating_unit_ids', 'read_operating_unit_ids')

    @api.depends('read_user_ids', 'read_group_ids', 'read_department_ids', 'read_operating_unit_ids')
    def _compute_restricted(self):
        # the read sets already include everything inherited from the parent
        for folder in self:
            folder.restricted = bool(
                folder.read_user_ids or folder.read_group_ids
                or folder.read_department_ids or folder.read_operating_unit_ids)

    @api.depends('active')
    def _compute_status(self):
        for folder in self:
            folder.status = 'enabled' if folder.active else 'disabled'

    def _compute_document_count(self):
        data = self.env['dms.document']._read_group(
            [('folder_id', 'in', self.ids)], ['folder_id'], ['__count'])
        counts = {folder.id: count for folder, count in data}
        for folder in self:
            folder.document_count = counts.get(folder.id, 0)

    @api.depends('name', 'parent_id.display_name')
    def _compute_display_name(self):
        for folder in self:
            folder.display_name = (
                f'{folder.parent_id.display_name} / {folder.name}' if folder.parent_id else folder.name)

    # -------------------------------------------------- enable / disable (cascades)
    def write(self, vals):
        cascade = 'active' in vals and not self.env.context.get('dms_cascade')
        if cascade:
            if vals['active'] and any(f.parent_id and not f.parent_id.active for f in self):
                raise UserError(_('Enable the parent folder first.'))
            vals = dict(vals, disabled_by_folder=False)  # a manual choice wins over the parent's
        res = super().write(vals)
        if cascade:
            self._cascade_active(vals['active'])
        return res

    def _cascade_active(self, active):
        """Disabling a folder disables its sub-folders and every document below it.

        Enabling it brings back only what the cascade had disabled: documents or
        sub-folders someone disabled by hand stay disabled.
        """
        folders = self.with_context(active_test=False, dms_cascade=True)
        tree = folders.search([('id', 'child_of', self.ids)])
        docs = self.env['dms.document'].with_context(active_test=False, dms_cascade=True).search(
            [('folder_id', 'in', tree.ids)])
        if active:
            tree.filtered(lambda f: not f.active and f.disabled_by_folder).write(
                {'active': True, 'disabled_by_folder': False})
            docs.filtered(lambda d: not d.active and d.disabled_by_folder).write(
                {'active': True, 'disabled_by_folder': False})
        else:
            (tree - self).filtered('active').write({'active': False, 'disabled_by_folder': True})
            docs.filtered('active').write({'active': False, 'disabled_by_folder': True})

    def action_disable(self):
        self.write({'active': False})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_enable(self):
        self.write({'active': True})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('documents_lite.dms_document_action')
        action['context'] = {'default_folder_id': self.id, 'search_default_folder_id': self.id,
                             'active_test': False}
        action['domain'] = [('folder_id', 'child_of', self.id)]
        return action

    def _can_write(self, user=None):
        """Python twin of the write rule, for UI hints and tests.

        Only Admins (group_dms_manager) can write; Viewers are read-only whatever
        the folder access rules say.
        """
        self.ensure_one()
        user = user or self.env.user
        return user.has_group('documents_lite.group_dms_manager')


class DmsFolderAccess(models.Model):
    _name = 'dms.folder.access'
    _description = 'Folder Access Rule'
    _order = 'folder_id, permission desc, id'

    folder_id = fields.Many2one('dms.folder', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', ondelete='cascade', index='btree_not_null')
    group_id = fields.Many2one('res.groups', string='Group', ondelete='cascade', index='btree_not_null')
    department_id = fields.Many2one(
        'hr.department', string='Department', ondelete='cascade', index='btree_not_null',
        help="Everyone working in this department or in one of its sub-departments.")
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit', ondelete='cascade', index='btree_not_null',
        help="Everyone working in this operating unit or in one of its sub-units.")
    manager_unit_id = fields.Many2one(
        'operating.unit', string='Manager of Operating Unit', ondelete='cascade',
        index='btree_not_null', domain=[('manager_id', '!=', False)],
        help="Gives access to the manager of this operating unit (operating unit > Manager). "
             "When the unit gets a new manager, access moves to the new one.")
    manager_name = fields.Char(string='Manager', related='manager_unit_id.manager_id.name')
    permission = fields.Selection(
        [('read', 'Read'), ('write', 'Read & Write')], required=True, default='read')

    def _auto_init(self):
        """Before the unique constraints below are created, drop duplicates that already exist.

        A duplicate (same folder, same target) adds nothing: the line with the stronger
        permission is kept (the oldest one when they are equal), so nobody loses access.
        """
        cr = self.env.cr
        if sql.table_exists(cr, self._table):
            for column in ACCESS_TARGET_FIELDS:
                if sql.column_exists(cr, self._table, column):
                    cr.execute(f"""
                        DELETE FROM dms_folder_access a USING dms_folder_access b
                         WHERE a.folder_id = b.folder_id AND a.{column} = b.{column} AND a.id <> b.id
                           AND ((b.permission = 'write' AND a.permission <> 'write')
                                OR (b.permission = a.permission AND b.id < a.id))
                    """)
        return super()._auto_init()

    @api.constrains('folder_id', *ACCESS_TARGET_FIELDS)
    def _check_target_listed_once(self):
        """Each user / group / department / unit / unit manager is listed once per folder."""
        kinds = {
            'user_id': _('user'), 'group_id': _('group'), 'department_id': _('department'),
            'operating_unit_id': _('operating unit'), 'manager_unit_id': _('operating unit manager'),
        }
        for folder in self.folder_id:
            seen = set()
            for rule in folder.access_ids:
                for field_name in ACCESS_TARGET_FIELDS:
                    target = rule[field_name]
                    if not target:
                        continue
                    key = (field_name, target.id)
                    if key in seen:
                        raise ValidationError(_(
                            '"%(name)s" is already listed on this folder as a %(kind)s. '
                            'Each one can only appear once: change the permission of the existing line instead.',
                            name=target.display_name, kind=kinds[field_name]))
                    seen.add(key)

    def init(self):
        """Older versions allowed fewer targets on a rule ("a user or a group", later four kinds).
        Drop those checks so rules for the newer targets are accepted; the current check
        (below) replaces them."""
        super().init()
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
             WHERE conrelid = 'dms_folder_access'::regclass AND contype = 'c'
               AND pg_get_constraintdef(oid) ILIKE '%user_id%'
               AND pg_get_constraintdef(oid) ILIKE '%group_id%'
               AND pg_get_constraintdef(oid) NOT ILIKE '%manager_unit_id%'
        """)
        dropped = False
        for (name,) in self.env.cr.fetchall():
            self.env.cr.execute('ALTER TABLE dms_folder_access DROP CONSTRAINT "%s"' % name)
            dropped = True
        if dropped:
            self.env.cr.execute("""
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'dms_folder_access'::regclass AND contype = 'c'
                   AND pg_get_constraintdef(oid) ILIKE '%manager_unit_id%'
            """)
            if not self.env.cr.fetchone():
                self.env.cr.execute(
                    'ALTER TABLE dms_folder_access ADD CONSTRAINT dms_folder_access_target_check '
                    'CHECK ((user_id IS NOT NULL)::int + (group_id IS NOT NULL)::int'
                    ' + (department_id IS NOT NULL)::int + (operating_unit_id IS NOT NULL)::int'
                    ' + (manager_unit_id IS NOT NULL)::int = 1)')

    _target_check = models.Constraint(
        'CHECK ((user_id IS NOT NULL)::int + (group_id IS NOT NULL)::int'
        ' + (department_id IS NOT NULL)::int + (operating_unit_id IS NOT NULL)::int'
        ' + (manager_unit_id IS NOT NULL)::int = 1)',
        'Pick exactly one of a user, a group, a department, an operating unit or an operating unit manager on each access rule.')

    _unique_user = models.Constraint(
        'UNIQUE (folder_id, user_id)', 'This user is already listed on this folder.')
    _unique_group = models.Constraint(
        'UNIQUE (folder_id, group_id)', 'This group is already listed on this folder.')
    _unique_department = models.Constraint(
        'UNIQUE (folder_id, department_id)', 'This department is already listed on this folder.')
    _unique_operating_unit = models.Constraint(
        'UNIQUE (folder_id, operating_unit_id)', 'This operating unit is already listed on this folder.')
    _unique_manager_unit = models.Constraint(
        'UNIQUE (folder_id, manager_unit_id)', 'The manager of this operating unit is already listed on this folder.')

    # "Exactly one target per rule" is enforced by the constraint above and, in the form, by the
    # readonly modifiers on the access list (no onchange round trip to the server per click).
