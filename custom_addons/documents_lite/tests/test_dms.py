import base64

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

FILE_A = base64.b64encode(b'first version of the file').decode()
FILE_B = base64.b64encode(b'second version of the file').decode()


class DmsCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Every internal user is a Viewer by default; Admin is granted explicitly.
        cls.alice = new_test_user(cls.env, 'dl_alice', groups='base.group_user,documents_lite.group_dms_user')
        cls.bob = new_test_user(cls.env, 'dl_bob', groups='base.group_user,documents_lite.group_dms_user')
        cls.boss = new_test_user(cls.env, 'dl_boss', groups='base.group_user,documents_lite.group_dms_manager')
        cls.Folder = cls.env['dms.folder']
        cls.Doc = cls.env['dms.document']
        cls.open_folder = cls.Folder.create({'name': 'Open'})
        cls.secret = cls.Folder.create({
            'name': 'Secret',
            'access_ids': [(0, 0, {'user_id': cls.alice.id, 'permission': 'read'})],
        })
        cls.secret_doc = cls.Doc.create({'name': 'plan.txt', 'folder_id': cls.secret.id, 'file': FILE_A})

    def doc_as(self, user, folder, name='x.txt'):
        return self.Doc.with_user(user).create({'name': name, 'folder_id': folder.id, 'file': FILE_A})


@tagged('post_install', '-at_install')
class TestFolderAccess(DmsCommon):

    def test_open_folder_everybody(self):
        doc = self.doc_as(self.boss, self.open_folder)
        self.assertTrue(doc.with_user(self.alice).name)
        self.assertIn(doc, self.Doc.with_user(self.alice).search([]))

    def test_restricted_folder_hidden(self):
        self.assertTrue(self.secret.restricted)
        self.assertFalse(self.Doc.with_user(self.bob).search([('id', '=', self.secret_doc.id)]))
        with self.assertRaises(AccessError):
            self.secret_doc.with_user(self.bob).name  # noqa: B018
        self.assertNotIn(self.secret, self.Folder.with_user(self.bob).search([]))
        self.assertIn(self.secret, self.Folder.with_user(self.alice).search([]))

    def test_restricted_folder_blocks_create_for_outsider(self):
        with self.assertRaises(AccessError):
            self.doc_as(self.bob, self.secret)

    def test_read_only_user(self):
        self.secret.access_ids = [(0, 0, {'user_id': self.bob.id, 'permission': 'read'})]
        doc = self.secret_doc.with_user(self.bob)
        self.assertEqual(doc.name, 'plan.txt')
        with self.assertRaises(AccessError):
            doc.write({'name': 'hacked'})
        with self.assertRaises(AccessError):
            self.doc_as(self.bob, self.secret)
        with self.assertRaises(AccessError):
            doc.unlink()

    def test_group_access(self):
        group = self.env.ref('base.group_partner_manager')
        folder = self.Folder.create({'name': 'Sales only', 'access_ids': [(0, 0, {'group_id': group.id, 'permission': 'read'})]})
        doc = self.Doc.create({'name': 'g.txt', 'folder_id': folder.id, 'file': FILE_A})
        self.assertFalse(doc.with_user(self.bob).has_access('read'))
        self.bob.group_ids = [(4, group.id)]
        self.assertTrue(doc.with_user(self.bob).has_access('read'))
        # a Viewer never gets write access, even through a "Read & Write" folder rule
        self.assertFalse(doc.with_user(self.bob).has_access('write'))

    def test_inheritance(self):
        child = self.Folder.create({'name': 'Child', 'parent_id': self.secret.id})
        self.assertTrue(child.restricted)
        self.assertIn(self.alice, child.read_user_ids)
        self.assertNotIn(child, self.Folder.with_user(self.bob).search([]))
        # parent change propagates
        self.secret.access_ids = [(0, 0, {'user_id': self.bob.id, 'permission': 'read'})]
        self.assertIn(self.bob, child.read_user_ids)
        self.assertNotIn(self.bob, child.write_user_ids)

    def test_no_inheritance(self):
        child = self.Folder.create({'name': 'Public child', 'parent_id': self.secret.id, 'inherit_access': False})
        self.assertFalse(child.restricted)
        doc = self.doc_as(self.boss, child)
        self.assertTrue(doc.with_user(self.bob).name)

    def test_manager_sees_everything(self):
        self.assertTrue(self.secret_doc.with_user(self.boss).has_access('write'))
        self.assertIn(self.secret, self.Folder.with_user(self.boss).search([]))

    def test_only_admins_edit_access_rules(self):
        self.secret.access_ids = [(0, 0, {'user_id': self.bob.id, 'permission': 'read'})]
        with self.assertRaises(AccessError):
            self.secret.with_user(self.bob).write({'access_ids': [(0, 0, {'user_id': self.bob.id, 'permission': 'write'})]})
        self.secret.with_user(self.boss).write({'access_ids': [(0, 0, {'user_id': self.bob.id, 'permission': 'write'})]})

    def test_access_rule_needs_one_target(self):
        with self.assertRaises(Exception), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.env['dms.folder.access'].create({'folder_id': self.open_folder.id})

    def test_multi_company(self):
        company = self.env['res.company'].create({'name': 'Other Co'})
        folder = self.Folder.create({'name': 'Other', 'company_id': company.id})
        self.assertNotIn(folder, self.Folder.with_user(self.bob).search([]))
        self.bob.company_ids = [(4, company.id)]
        self.assertIn(folder, self.Folder.with_user(self.bob).with_context(allowed_company_ids=[company.id]).search([]))

    def test_versions_follow_document_access(self):
        self.secret_doc.write({'file': FILE_B})
        version = self.secret_doc.version_ids
        self.assertTrue(version)
        self.assertFalse(self.env['dms.document.version'].with_user(self.bob).search([('id', '=', version.id)]))
        self.assertTrue(self.env['dms.document.version'].with_user(self.alice).search([('id', '=', version.id)]))


@tagged('post_install', '-at_install')
class TestOrgAccess(DmsCommon):
    """Folder access by department and by operating unit, next to users and groups."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Unit = cls.env['operating.unit']
        # If your operating.unit model has more required fields than a name, add them here.
        cls.unit_district = cls.Unit.create(cls._with_required_units(cls.Unit, {'name': 'District'}))
        cls.unit_branch = cls.Unit.create(
            cls._with_required_units(cls.Unit, {'name': 'Branch', 'parent_unit': cls.unit_district.id}))
        cls.unit_other = cls.Unit.create(cls._with_required_units(cls.Unit, {'name': 'Other unit'}))
        Department = cls.env['hr.department']
        cls.dept_parent = Department.create(cls._with_required_units(Department, {'name': 'Finance'}))
        cls.dept_child = Department.create(cls._with_required_units(
            Department, {'name': 'Accounts', 'parent_id': cls.dept_parent.id}))
        cls.dept_other = Department.create(cls._with_required_units(Department, {'name': 'Operations'}))
        cls._employee(cls.alice, cls.dept_child, cls.unit_branch)   # Accounts, in the Branch unit
        cls._employee(cls.bob, cls.dept_other, cls.unit_other)

    @classmethod
    def _with_required_units(cls, model, vals):
        """Fill any required operating-unit field of ``model`` that ``vals`` does not set."""
        default = getattr(cls, 'unit_other', None) or getattr(cls, 'unit_district', None)
        for name, field in model._fields.items():
            if (field.required and field.comodel_name == 'operating.unit' and name not in vals
                    and name != 'parent_unit' and default):
                vals[name] = default.id
        return vals

    @classmethod
    def _employee(cls, user, department, unit=None):
        Employee = cls.env['hr.employee']
        employee = user.employee_ids[:1] or Employee.create(
            cls._with_required_units(Employee, {'name': user.name, 'user_id': user.id}))
        employee.department_id = department
        if unit and 'operating_unit_id' in employee._fields:
            employee.operating_unit_id = unit
        return employee

    def _folder(self, **target):
        folder = self.Folder.create({'name': 'Restricted by %s' % list(target)[0]})
        folder.access_ids = [(0, 0, dict(target, permission='read'))]
        doc = self.Doc.create({'name': 'f.txt', 'folder_id': folder.id, 'file': FILE_A})
        return folder, doc

    def _can_read(self, user, doc):
        return doc in self.Doc.with_user(user).search([('id', '=', doc.id)])

    # ---- departments
    def test_department_access(self):
        _folder, doc = self._folder(department_id=self.dept_child.id)
        self.assertTrue(self._can_read(self.alice, doc))
        self.assertFalse(self._can_read(self.bob, doc))

    def test_sub_department_inherits_parent_department_rule(self):
        # alice works in "Accounts", a sub-department of "Finance"
        _folder, doc = self._folder(department_id=self.dept_parent.id)
        self.assertTrue(self._can_read(self.alice, doc))
        self.assertFalse(self._can_read(self.bob, doc))

    def test_parent_department_member_does_not_get_child_only_rule(self):
        self._employee(self.bob, self.dept_parent)
        _folder, doc = self._folder(department_id=self.dept_child.id)
        self.assertFalse(self._can_read(self.bob, doc))

    # ---- operating units
    def test_operating_unit_access(self):
        _folder, doc = self._folder(operating_unit_id=self.unit_branch.id)
        self.assertTrue(self._can_read(self.alice, doc))
        self.assertFalse(self._can_read(self.bob, doc))

    def test_parent_unit_rule_covers_sub_units(self):
        # alice's unit "Branch" sits under "District"
        _folder, doc = self._folder(operating_unit_id=self.unit_district.id)
        self.assertTrue(self._can_read(self.alice, doc))
        self.assertFalse(self._can_read(self.bob, doc))

    def test_sub_unit_rule_does_not_cover_parent_unit_members(self):
        carol = new_test_user(self.env, 'dl_carol', groups='base.group_user,documents_lite.group_dms_user')
        self._employee(carol, self.dept_other, self.unit_district)
        _folder, doc = self._folder(operating_unit_id=self.unit_branch.id)
        self.assertFalse(self._can_read(carol, doc))

    def test_operating_unit_manager_access(self):
        if 'manager_id' not in self.Unit._fields:
            self.skipTest('operating.unit.manager_id is not available')
        bob_employee = self.bob.employee_ids[:1]
        alice_employee = self.alice.employee_ids[:1]
        self.unit_other.manager_id = bob_employee
        _folder, doc = self._folder(manager_unit_id=self.unit_other.id)
        self.assertTrue(self._can_read(self.bob, doc))      # bob manages the unit
        self.assertFalse(self._can_read(self.alice, doc))
        # a new manager takes over the access
        self.unit_other.manager_id = alice_employee
        self.assertTrue(self._can_read(self.alice, doc))
        self.assertFalse(self._can_read(self.bob, doc))

    def test_same_target_cannot_be_listed_twice(self):
        folder, _doc = self._folder(operating_unit_id=self.unit_branch.id)
        # same unit again, even with another permission
        with self.assertRaises(ValidationError):
            folder.access_ids = [(0, 0, {'operating_unit_id': self.unit_branch.id, 'permission': 'write'})]
        # two identical new lines in one save
        other = self.Folder.create({'name': 'Dupes'})
        with self.assertRaises(ValidationError):
            other.access_ids = [
                (0, 0, {'department_id': self.dept_child.id, 'permission': 'read'}),
                (0, 0, {'department_id': self.dept_child.id, 'permission': 'read'})]
        # a unit and the manager of that unit are different targets, so both may be listed
        if 'manager_id' in self.Unit._fields:
            folder.access_ids = [(0, 0, {'manager_unit_id': self.unit_branch.id, 'permission': 'read'})]
            self.assertEqual(len(folder.access_ids), 2)
            with self.assertRaises(ValidationError):
                folder.access_ids = [(0, 0, {'manager_unit_id': self.unit_branch.id, 'permission': 'read'})]

    def test_user_assigned_operating_units(self):
        if 'assigned_operating_unit_ids' not in self.env['res.users']._fields:
            self.skipTest('res.users.assigned_operating_unit_ids is not available')
        self.bob.assigned_operating_unit_ids = [(4, self.unit_branch.id)]
        _folder, doc = self._folder(operating_unit_id=self.unit_branch.id)
        self.assertTrue(self._can_read(self.bob, doc))

    # ---- mixing and inheritance
    def test_any_matching_target_is_enough(self):
        """A folder lists a user, a group, a department and an operating unit: any one lets you in."""
        carol = new_test_user(self.env, 'dl_carol2', groups='base.group_user,documents_lite.group_dms_user')
        dave = new_test_user(self.env, 'dl_dave', groups='base.group_user,documents_lite.group_dms_user')
        erin = new_test_user(self.env, 'dl_erin', groups='base.group_user,documents_lite.group_dms_user')
        outsider = new_test_user(self.env, 'dl_frank', groups='base.group_user,documents_lite.group_dms_user')
        group = self.env.ref('base.group_partner_manager')
        carol.group_ids = [(4, group.id)]
        self._employee(dave, self.dept_parent)                     # by department
        self._employee(erin, self.dept_other, self.unit_district)  # by operating unit
        folder = self.Folder.create({'name': 'Mixed', 'access_ids': [
            (0, 0, {'user_id': self.bob.id}), (0, 0, {'group_id': group.id}),
            (0, 0, {'department_id': self.dept_parent.id}), (0, 0, {'operating_unit_id': self.unit_district.id}),
        ]})
        doc = self.Doc.create({'name': 'm.txt', 'folder_id': folder.id, 'file': FILE_A})
        for user in (self.bob, carol, dave, erin, self.alice):  # alice: Finance / Accounts and Branch
            self.assertTrue(self._can_read(user, doc), user.login)
        self.assertFalse(self._can_read(outsider, doc))

    def test_child_folder_inherits_department_and_unit_access(self):
        parent, _doc = self._folder(department_id=self.dept_parent.id)
        parent.access_ids = [(0, 0, {'operating_unit_id': self.unit_district.id, 'permission': 'read'})]
        child = self.Folder.create({'name': 'Child', 'parent_id': parent.id})
        self.assertTrue(child.restricted)
        self.assertIn(self.dept_parent, child.read_department_ids)
        self.assertIn(self.unit_district, child.read_operating_unit_ids)
        # ... unless the child opts out of inheritance
        child.inherit_access = False
        self.assertFalse(child.restricted)
        self.assertFalse(child.read_department_ids)

    def test_user_without_employee_gets_nothing(self):
        nobody = new_test_user(self.env, 'dl_nobody', groups='base.group_user,documents_lite.group_dms_user')
        _folder, doc = self._folder(department_id=self.dept_parent.id)
        _folder_u, doc_u = self._folder(operating_unit_id=self.unit_district.id)
        self.assertFalse(self._can_read(nobody, doc))
        self.assertFalse(self._can_read(nobody, doc_u))

    def test_moving_department_or_unit_takes_effect_immediately(self):
        """The evaluated rule domain is cached per user: HR changes must drop that cache."""
        _folder, doc = self._folder(department_id=self.dept_child.id)
        self.assertTrue(self._can_read(self.alice, doc))      # primes the cache
        self._employee(self.alice, self.dept_other)           # alice moves to Operations
        self.assertFalse(self._can_read(self.alice, doc))
        _folder_u, doc_u = self._folder(operating_unit_id=self.unit_branch.id)
        self.assertTrue(self._can_read(self.alice, doc_u))    # primes the cache again
        self._employee(self.alice, self.dept_other, self.unit_other)  # alice moves to another unit
        self.assertFalse(self._can_read(self.alice, doc_u))

    def test_admin_still_sees_everything(self):
        _folder, doc = self._folder(operating_unit_id=self.unit_other.id)
        self.assertTrue(self._can_read(self.boss, doc))

    def test_rule_needs_exactly_one_target(self):
        folder = self.Folder.create({'name': 'Targets'})
        with self.assertRaises(Exception), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.env['dms.folder.access'].create(
                {'folder_id': folder.id, 'department_id': self.dept_child.id,
                 'operating_unit_id': self.unit_branch.id})
        with self.assertRaises(Exception), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            self.env['dms.folder.access'].create({'folder_id': folder.id})


@tagged('post_install', '-at_install')
class TestDocuments(DmsCommon):

    def test_file_meta(self):
        doc = self.Doc.create({'name': 'notes.txt', 'folder_id': self.open_folder.id, 'file': FILE_A})
        self.assertEqual(doc.file_size, len(b'first version of the file'))
        self.assertTrue(doc.checksum)
        self.assertEqual(doc.extension, 'txt')
        self.assertTrue(doc.is_viewable)

    def test_version_history_and_restore(self):
        doc = self.Doc.create({'name': 'v.txt', 'folder_id': self.open_folder.id, 'file': FILE_A})
        self.assertEqual(doc.version_no, 1)
        doc.write({'file': FILE_B})
        self.assertEqual((doc.version_no, doc.version_count), (2, 1))
        old = doc.version_ids
        self.assertEqual(base64.b64decode(old.file), b'first version of the file')
        old.action_restore()
        self.assertEqual(base64.b64decode(doc.file), b'first version of the file')
        self.assertEqual((doc.version_no, doc.version_count), (3, 2))

    def test_duplicates(self):
        unique = base64.b64encode(b'a very unique payload').decode()
        a = self.Doc.create({'name': 'a.txt', 'folder_id': self.open_folder.id, 'file': unique})
        self.assertFalse(a.has_duplicate)
        b = self.Doc.create({'name': 'b.txt', 'folder_id': self.open_folder.id, 'file': unique})
        (a | b).invalidate_recordset()
        self.assertEqual((a | b).mapped('has_duplicate'), [True, True])

    def test_full_text_search(self):
        tag = self.env['dms.tag'].create({'name': 'Zebra'})
        doc = self.Doc.create({
            'name': 'Quarterly report', 'folder_id': self.open_folder.id, 'file': FILE_A,
            'description': 'contains pineapple budget', 'tag_ids': [(6, 0, tag.ids)]})
        search = lambda dom: self.Doc.search(dom + [('folder_id', '=', self.open_folder.id)])  # noqa: E731
        self.assertEqual(search([('name', 'ilike', 'quarterly')]), doc)
        self.assertEqual(search([('description', 'ilike', 'pineapple')]), doc)
        self.assertEqual(search([('tag_ids', 'ilike', 'zebra')]), doc)
        text = self.Doc.create({
            'name': 'readme', 'folder_id': self.open_folder.id, 'file_name': 'readme.txt',
            'file': base64.b64encode(b'the quick purple giraffe jumps').decode()})
        self.assertEqual(search([('content_search', 'ilike', 'giraffe')]), text)
        self.assertFalse(search([('content_search', 'ilike', 'nonexistingword')]))

    def test_disable_tag_and_status(self):
        tag = self.env['dms.tag'].create({'name': 'Temp tag'})
        self.assertEqual(tag.status, 'enabled')
        tag.action_disable()
        self.assertEqual(tag.status, 'disabled')
        self.assertFalse(self.env['dms.tag'].search([('name', '=', 'Temp tag')]))
        tag.action_enable()
        self.assertEqual(tag.status, 'enabled')
        self.assertTrue(self.env['dms.tag'].search([('name', '=', 'Temp tag')]))

    def test_folder_and_document_status(self):
        folder = self.Folder.create({'name': 'Status folder'})
        doc = self.Doc.create({'name': 's.txt', 'folder_id': folder.id, 'file': FILE_A})
        self.assertEqual((folder.status, doc.status), ('enabled', 'enabled'))
        folder.action_disable()
        doc = doc.with_context(active_test=False)
        self.assertEqual((folder.status, doc.status), ('disabled', 'disabled'))
        folder.action_enable()
        self.assertEqual((folder.status, doc.status), ('enabled', 'enabled'))
        # individual document
        doc.action_disable()
        self.assertEqual(doc.status, 'disabled')
        doc.action_enable()
        self.assertEqual(doc.status, 'enabled')

    def test_link_and_smart_button(self):
        partner = self.env['res.partner'].create({'name': 'Linked Partner'})
        self.Doc.create({'name': 'l.txt', 'folder_id': self.open_folder.id, 'file': FILE_A,
                         'res_model': 'res.partner', 'res_id': partner.id})
        self.assertEqual(self.Doc.search([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)]).res_name,
                         'Linked Partner')
        action = partner.action_dms_open_documents()
        self.assertEqual(self.Doc.search(action['domain']).res_id, partner.id)
        arch = self.env['res.partner'].get_view(view_type='form')['arch']
        self.assertIn('action_dms_open_documents', arch)
        # no button on a model outside the list
        arch = self.env['res.company'].get_view(view_type='form')['arch']
        self.assertNotIn('action_dms_open_documents', arch)

    def test_autofile_rule(self):
        model = self.env['ir.model']._get('res.partner')
        tag = self.env['dms.tag'].create({'name': 'Auto'})
        self.env['dms.rule'].create({
            'name': 'Partner contracts', 'sequence': 1, 'model_id': model.id, 'name_pattern': 'contract*.pdf',
            'folder_id': self.open_folder.id, 'tag_ids': [(6, 0, tag.ids)]})
        partner = self.env['res.partner'].create({'name': 'Rule Partner'})
        att = self.env['ir.attachment'].create({
            'name': 'Contract-2026.PDF', 'raw': b'%PDF-1.4 fake', 'res_model': 'res.partner', 'res_id': partner.id})
        self.env['ir.attachment'].create({
            'name': 'photo.png', 'raw': b'png', 'res_model': 'res.partner', 'res_id': partner.id})
        docs = self.Doc.search([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs.source_attachment_id, att)
        self.assertEqual(docs.folder_id, self.open_folder)
        self.assertEqual(docs.tag_ids, tag)
        # writing the attachment again must not duplicate
        att.write({'res_id': partner.id})
        self.assertEqual(self.Doc.search_count([('res_id', '=', partner.id), ('res_model', '=', 'res.partner')]), 1)

    def test_trash(self):
        doc = self.Doc.create({'name': 't.txt', 'folder_id': self.open_folder.id, 'file': FILE_A})
        doc.active = False
        self.assertFalse(self.Doc.search([('id', '=', doc.id)]))
        self.assertTrue(self.Doc.with_context(active_test=False).search([('id', '=', doc.id)]))


@tagged('post_install', '-at_install')
class TestRoles(DmsCommon):
    """Admin (group_dms_manager) and Viewer (group_dms_user)."""

    def test_internal_user_is_viewer_by_default(self):
        carol = new_test_user(self.env, 'dl_carol', groups='base.group_user')
        self.assertTrue(carol.has_group('documents_lite.group_dms_user'))
        self.assertFalse(carol.has_group('documents_lite.group_dms_manager'))
        self.assertIn(self.open_folder, self.Folder.with_user(carol).search([]))
        self.assertNotIn(self.secret, self.Folder.with_user(carol).search([]))

    def test_admin_implies_viewer(self):
        self.assertTrue(self.boss.has_group('documents_lite.group_dms_user'))
        self.assertFalse(self.alice.has_group('documents_lite.group_dms_manager'))

    def test_viewer_cannot_create_document(self):
        with self.assertRaises(AccessError):
            self.doc_as(self.alice, self.open_folder)
        # not even in a folder the viewer is explicitly allowed to read
        with self.assertRaises(AccessError):
            self.doc_as(self.alice, self.secret)

    def test_viewer_cannot_edit_document(self):
        doc = self.doc_as(self.boss, self.open_folder)
        viewer_doc = doc.with_user(self.alice)
        with self.assertRaises(AccessError):
            viewer_doc.write({'name': 'hacked'})
        with self.assertRaises(AccessError):
            viewer_doc.write({'file': FILE_B})
        with self.assertRaises(AccessError):
            viewer_doc.write({'allow_download': False, 'file_password': 'x'})
        with self.assertRaises(AccessError):
            viewer_doc.unlink()
        self.assertEqual(doc.name, 'x.txt')
        self.assertEqual(doc.version_no, 1)

    def test_viewer_can_read_document(self):
        doc = self.doc_as(self.boss, self.open_folder)
        self.assertEqual(doc.with_user(self.alice).name, 'x.txt')
        self.assertIn(doc, self.Doc.with_user(self.alice).search([]))
        # restricted folder: allowed viewer reads, other viewer does not
        self.assertEqual(self.secret_doc.with_user(self.alice).name, 'plan.txt')
        self.assertFalse(self.Doc.with_user(self.bob).search([('id', '=', self.secret_doc.id)]))
        with self.assertRaises(AccessError):
            self.secret_doc.with_user(self.bob).name  # noqa: B018

    def test_viewer_cannot_manage_folders_tags_rules(self):
        with self.assertRaises(AccessError):
            self.Folder.with_user(self.alice).create({'name': 'Nope'})
        with self.assertRaises(AccessError):
            self.open_folder.with_user(self.alice).write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            self.env['dms.tag'].with_user(self.alice).create({'name': 'Nope'})
        with self.assertRaises(AccessError):
            self.env['dms.rule'].with_user(self.alice).create({
                'name': 'Nope', 'model_id': self.env['ir.model']._get('res.partner').id,
                'folder_id': self.open_folder.id})

    def test_viewer_respects_download_flag(self):
        doc = self.doc_as(self.boss, self.open_folder)
        self.assertTrue(doc.with_user(self.alice).action_download())
        doc.allow_download = False
        with self.assertRaises(UserError):
            doc.with_user(self.alice).action_download()

    def test_download_flag_blocks_binary_download(self):
        doc = self.doc_as(self.boss, self.open_folder)
        doc.allow_download = False
        Binary = self.env['ir.binary'].with_user(self.alice)
        viewer_doc = doc.with_user(self.alice)
        # /web/content?download=true sets download_attachments: refused for a Viewer
        with self.assertRaises(AccessError):
            Binary._get_stream_from(viewer_doc.with_context(download_attachments=True), 'file')
        # a plain (preview) read is still served
        self.assertTrue(Binary._get_stream_from(viewer_doc, 'file'))
        # allowed again once the Admin ticks the box
        doc.allow_download = True
        self.assertTrue(Binary._get_stream_from(viewer_doc.with_context(download_attachments=True), 'file'))
        # Admins are never blocked
        doc.allow_download = False
        self.assertTrue(self.env['ir.binary'].with_user(self.boss)._get_stream_from(
            doc.with_user(self.boss).with_context(download_attachments=True), 'file'))

    def test_disable_hides_document_from_viewers(self):
        doc = self.doc_as(self.boss, self.open_folder)
        self.assertIn(doc, self.Doc.with_user(self.alice).search([]))
        doc.with_user(self.boss).action_disable()
        self.assertFalse(doc.active)
        self.assertNotIn(doc, self.Doc.with_user(self.alice).search([]))
        # not even by id
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).with_context(active_test=False).name  # noqa: B018
        # admins still find it, and can enable it again
        self.assertIn(doc, self.Doc.with_user(self.boss).with_context(active_test=False).search([]))
        doc.with_user(self.boss).action_enable()
        self.assertTrue(doc.active)
        self.assertEqual(doc.with_user(self.alice).name, 'x.txt')

    def test_viewer_cannot_enable_or_disable(self):
        doc = self.doc_as(self.boss, self.open_folder)
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).action_disable()
        with self.assertRaises(AccessError):
            doc.with_user(self.alice).write({'active': False})

    def test_file_size_limit(self):
        big = base64.b64encode(b'x' * (6 * 1024 * 1024))
        with self.assertRaises(ValidationError):
            self.Doc.create({'name': 'big.txt', 'folder_id': self.open_folder.id, 'file': big})
        ok = base64.b64encode(b'x' * (4 * 1024 * 1024))
        self.assertTrue(self.Doc.create({'name': 'ok.txt', 'folder_id': self.open_folder.id, 'file': ok}))

    def test_allowed_file_types(self):
        samples = {
            'a.pdf': b'%PDF-1.4 body',
            'a.png': b'\x89PNG\r\n\x1a\n' + b'0' * 8,
            'a.jpg': b'\xff\xd8\xff\xe0' + b'0' * 8,
            'a.docx': b'PK\x03\x04' + b'0' * 8,
            'a.xls': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'0' * 8,
            'a.csv': b'sku,name\n1,x\n',
        }
        for name, raw in samples.items():
            doc = self.Doc.create({
                'name': name, 'folder_id': self.open_folder.id, 'file': base64.b64encode(raw)})
            self.assertTrue(doc.file, name)

    def test_image_gets_small_thumbnail(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (1600, 1200), (200, 30, 30)).save(buf, 'PNG')
        doc = self.Doc.create({
            'name': 'big.png', 'folder_id': self.open_folder.id, 'file': base64.b64encode(buf.getvalue())})
        self.assertTrue(doc.thumbnail)
        thumb = Image.open(io.BytesIO(base64.b64decode(doc.thumbnail)))
        self.assertLessEqual(max(thumb.size), 256)
        self.assertLess(len(base64.b64decode(doc.thumbnail)), len(buf.getvalue()))
        text = self.Doc.create({'name': 'a.txt', 'folder_id': self.open_folder.id, 'file': FILE_A})
        self.assertFalse(text.thumbnail)
        doc.thumbnail = False
        self.Doc._dms_backfill_thumbnails()
        self.assertTrue(doc.thumbnail)

    def test_res_name_for_many_documents(self):
        partners = self.env['res.partner'].create([{'name': 'P%d' % i} for i in range(5)])
        docs = self.Doc.browse()
        for partner in partners:
            docs |= self.Doc.create({
                'name': 'l%d.txt' % partner.id, 'folder_id': self.open_folder.id, 'file': FILE_A,
                'res_model': 'res.partner', 'res_id': partner.id})
        self.assertEqual(docs.mapped('res_name'), partners.mapped('display_name'))

    def test_folder_dependency_graph_stays_small(self):
        """Regression: nine fields computed together depended on each other, so building the
        folder form took minutes (millions of dependency paths)."""
        import time
        registry = self.env.registry
        started = time.monotonic()
        for model, names in (('dms.folder.access', ('permission', 'group_id', 'user_id')),
                             ('dms.folder', ('parent_id', 'inherit_access', 'access_ids'))):
            for name in names:
                field = self.env[model]._fields[name]
                registry.get_dependent_fields(field.base_field)
        self.assertLess(time.monotonic() - started, 5)

    def test_disallowed_file_types(self):
        bad = {
            'run.exe': b'MZ\x90\x00',
            'page.html': b'<html></html>',
            'pic.svg': b'<svg></svg>',
            'bundle.zip': b'PK\x03\x04' + b'0' * 8,
            'noextension': b'plain text',
            'fake.pdf': b'MZ\x90\x00 not a pdf',
            'fake.png': b'not an image',
            'fake.docx': b'not a zip',
        }
        for name, raw in bad.items():
            with self.assertRaises(ValidationError, msg=name):
                self.Doc.create({
                    'name': name, 'folder_id': self.open_folder.id, 'file': base64.b64encode(raw)})

    def test_replacing_with_disallowed_file_is_refused(self):
        doc = self.Doc.create({'name': 'v.txt', 'folder_id': self.open_folder.id, 'file': FILE_A})
        with self.assertRaises(ValidationError):
            doc.write({'file': base64.b64encode(b'MZ\x90\x00'), 'file_name': 'v.exe'})

    def test_autofile_skips_disallowed_files(self):
        model = self.env['ir.model']._get('res.partner')
        self.env['dms.rule'].create({
            'name': 'Everything', 'sequence': 1, 'model_id': model.id, 'folder_id': self.open_folder.id})
        partner = self.env['res.partner'].create({'name': 'Skip Partner'})
        # the chatter upload itself must still succeed
        self.env['ir.attachment'].create({
            'name': 'tool.exe', 'raw': b'MZ\x90\x00', 'res_model': 'res.partner', 'res_id': partner.id})
        self.assertFalse(self.Doc.search([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)]))

    def test_disable_folder_cascades_to_documents(self):
        parent = self.Folder.create({'name': 'Parent'})
        child = self.Folder.create({'name': 'Child', 'parent_id': parent.id})
        d1 = self.doc_as(self.boss, parent, 'd1.txt')
        d2 = self.doc_as(self.boss, child, 'd2.txt')
        d3 = self.doc_as(self.boss, parent, 'd3.txt')
        d3.with_user(self.boss).action_disable()  # disabled by hand before the folder
        parent.with_user(self.boss).action_disable()
        self.assertFalse(parent.active or child.active or d1.active or d2.active)
        self.assertTrue(d1.disabled_by_folder and d2.disabled_by_folder and child.disabled_by_folder)
        self.assertFalse(d3.disabled_by_folder)
        self.assertEqual((d1.status, d3.status), ('disabled', 'disabled'))
        # viewers see neither the folders nor the documents
        self.assertFalse(self.Folder.with_user(self.alice).with_context(active_test=False).search(
            [('id', 'in', (parent | child).ids)]))
        self.assertFalse(self.Doc.with_user(self.alice).with_context(active_test=False).search(
            [('id', 'in', (d1 | d2 | d3).ids)]))
        # enabling brings back what the cascade disabled, not the hand-disabled document
        parent.with_user(self.boss).action_enable()
        self.assertTrue(parent.active and child.active and d1.active and d2.active)
        self.assertFalse(d3.active)
        self.assertFalse(d1.disabled_by_folder)
        self.assertEqual(d1.status, 'enabled')

    def test_cannot_enable_inside_disabled_folder(self):
        parent = self.Folder.create({'name': 'Parent2'})
        child = self.Folder.create({'name': 'Child2', 'parent_id': parent.id})
        doc = self.doc_as(self.boss, parent)
        parent.with_user(self.boss).action_disable()
        with self.assertRaises(UserError):
            doc.with_user(self.boss).action_enable()
        with self.assertRaises(UserError):
            child.with_user(self.boss).action_enable()

    def test_viewer_cannot_restore_version(self):
        self.secret_doc.write({'file': FILE_B})
        version = self.secret_doc.version_ids
        with self.assertRaises(AccessError):
            version.with_user(self.alice).action_restore()
        version.with_user(self.boss).action_restore()
        self.assertEqual(base64.b64decode(self.secret_doc.file), b'first version of the file')

    def test_admin_full_access(self):
        # documents: create, edit, restrict, replace file (-> version), disable
        doc = self.doc_as(self.boss, self.secret)
        doc.with_user(self.boss).write({'name': 'renamed.txt', 'allow_download': False, 'file_password': 'pw'})
        self.assertEqual((doc.name, doc.allow_download, doc.file_password), ('renamed.txt', False, 'pw'))
        doc.with_user(self.boss).write({'file': FILE_B})
        self.assertEqual((doc.version_no, doc.version_count), (2, 1))
        # restricted folder the admin is not listed in is still fully visible
        self.assertTrue(self.secret_doc.with_user(self.boss).has_access('write'))
        # folders, tags, rules
        folder = self.Folder.with_user(self.boss).create({'name': 'Admin folder'})
        tag = self.env['dms.tag'].with_user(self.boss).create({'name': 'Admin tag'})
        rule = self.env['dms.rule'].with_user(self.boss).create({
            'name': 'Admin rule', 'model_id': self.env['ir.model']._get('res.partner').id,
            'folder_id': folder.id, 'tag_ids': [(6, 0, tag.ids)]})
        folder.with_user(self.boss).write({'name': 'Admin folder 2'})
        # nothing can be deleted, not even by an Admin: records are disabled instead
        for record in (rule, tag, folder, doc):
            with self.assertRaises(AccessError):
                record.with_user(self.boss).unlink()
        doc.with_user(self.boss).action_disable()
        self.assertFalse(doc.active)
        self.assertTrue(doc.exists())

    def test_details_action_opens_form(self):
        doc = self.doc_as(self.boss, self.open_folder)
        action = doc.with_user(self.boss).action_open_details()
        self.assertEqual((action['res_model'], action['res_id']), ('dms.document', doc.id))
        self.assertEqual(action['views'], [(False, 'form')])


@tagged('post_install', '-at_install')
class TestHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.folder = self.env['dms.folder'].create({'name': 'HTTP'})
        self.doc = self.env['dms.document'].create({
            'name': 'dl.txt', 'file_name': 'dl.txt', 'folder_id': self.folder.id, 'file': FILE_A})

    def test_upload_route(self):
        self.authenticate('admin', 'admin')
        csrf = http.Request.csrf_token(self)
        res = self.url_open('/dms/upload', data={'csrf_token': csrf, 'folder_id': self.folder.id},
                            files=[('ufile', ('a.txt', b'aaa', 'text/plain')), ('ufile', ('b.txt', b'bbb', 'text/plain'))])
        self.assertEqual(len(res.json()['ids']), 2)
        docs = self.env['dms.document'].browse(res.json()['ids'])
        self.assertEqual(docs.mapped('folder_id'), self.folder)
        self.assertEqual(sorted(docs.mapped('name')), ['a.txt', 'b.txt'])
        # linked mode
        partner = self.env['res.partner'].create({'name': 'Upload Partner'})
        res = self.url_open('/dms/upload', data={'csrf_token': csrf, 'folder_id': 'false', 'res_model': 'res.partner', 'res_id': partner.id},
                            files=[('ufile', ('c.txt', b'ccc', 'text/plain'))])
        doc = self.env['dms.document'].browse(res.json()['ids'])
        self.assertEqual((doc.res_model, doc.res_id), ('res.partner', partner.id))
        self.assertEqual(doc.folder_id, self.env.ref('documents_lite.dms_folder_inbox'))

    def test_upload_requires_login(self):
        self.authenticate(None, None)
        res = self.url_open('/dms/upload', data={'csrf_token': http.Request.csrf_token(self)},
                            files=[('ufile', ('a.txt', b'aaa', 'text/plain'))], allow_redirects=False)
        self.assertNotEqual(res.status_code, 200)

    def test_content_route_respects_folder_access(self):
        secret = self.env['dms.folder'].create({
            'name': 'Admin only', 'access_ids': [(0, 0, {'user_id': 2, 'permission': 'write'})]})
        doc = self.env['dms.document'].create({'name': 's.txt', 'folder_id': secret.id, 'file': FILE_A})
        new_test_user(self.env, 'dl_http', groups='base.group_user,documents_lite.group_dms_user', password='dl_http')
        self.authenticate('dl_http', 'dl_http')
        res = self.url_open(f'/web/content/dms.document/{doc.id}/file')
        self.assertIn(res.status_code, (403, 404))

    def test_viewer_upload_denied(self):
        new_test_user(self.env, 'dl_http_viewer', groups='base.group_user,documents_lite.group_dms_user',
                      password='dl_http_viewer')
        self.authenticate('dl_http_viewer', 'dl_http_viewer')
        before = self.env['dms.document'].search_count([])
        res = self.url_open('/dms/upload', data={'csrf_token': http.Request.csrf_token(self), 'folder_id': self.folder.id},
                            files=[('ufile', ('v.txt', b'vvv', 'text/plain'))])
        self.assertIn('error', res.json())
        self.assertEqual(self.env['dms.document'].search_count([]), before)

    def test_preview_is_inline_and_download_is_guarded(self):
        new_test_user(self.env, 'dl_http_prev', groups='base.group_user,documents_lite.group_dms_user',
                      password='dl_http_prev')
        self.authenticate('dl_http_prev', 'dl_http_prev')
        res = self.url_open(f'/dms/preview/{self.doc.id}')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('attachment', res.headers.get('Content-Disposition', ''))
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.doc.allow_download = False
        # preview keeps working, every explicit download route is refused
        self.assertEqual(self.url_open(f'/dms/preview/{self.doc.id}').status_code, 200)
        self.assertEqual(self.url_open(f'/dms/download/{self.doc.id}').status_code, 403)
        self.assertNotEqual(
            self.url_open(f'/web/content/dms.document/{self.doc.id}/file?download=true').status_code, 200)

    def test_disabled_document_is_not_served_to_viewers(self):
        new_test_user(self.env, 'dl_http_dis', groups='base.group_user,documents_lite.group_dms_user',
                      password='dl_http_dis')
        self.doc.action_disable()
        self.authenticate('dl_http_dis', 'dl_http_dis')
        self.assertEqual(self.url_open(f'/dms/preview/{self.doc.id}').status_code, 404)
        self.assertEqual(self.url_open(f'/dms/download/{self.doc.id}').status_code, 404)
