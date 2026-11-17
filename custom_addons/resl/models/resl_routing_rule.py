# -*- coding: utf-8 -*-
"""Configurable approver / disbursor assignment (Configuration menu).

Each rule answers: "for a borrower working in a Branch / District / Head
Office, WHO plays role X?"  The person is chosen either

  * by job position  - an ordered list (first = preferred). For every
    borrower the first job position that has somebody in the right place
    wins; if nobody holds it there (e.g. no "Supervisor-I" in that branch),
    the next job position of the list is tried, and so on; or
  * by specific employees.

"Select from" says WHERE the people are looked up (always chosen first):
the borrower's Branch, the District it belongs to, or the Head Office.

When no rule is configured, or a rule finds nobody, resl.loan falls back to
the previous hard-coded behaviour, so nothing stops working.
"""
import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

BRANCH_TYPES = ('branch', 'sub_branch', 'service_center')
DISTRICT_TYPES = ('district_office', 'regional_office')

TIERS = [
    ('branch', 'Branch'),
    ('district', 'District'),
    ('head_office', 'Head Office'),
]

ROLES = [
    ('approver', 'Approver'),
    ('manager_approver', "Approver's Approver (Manager's / Director's Approver)"),
    ('director_approver', "Approver's Approver (Director's Approver)"),
    ('disbursor', 'Disburser'),
    ('disbursor_backup', "Disburser's Disburser"),
    ('ho_approver', 'HO Approver'),
    ('hr_approver', "HO Approver's Approver"),
    ('hr_auditor', 'HR Auditor'),
    ('hr_accountant', 'HR Disburser'),
    ('hr_accountant_backup', "HR Disburser's Disburser"),
]

# roles that disburse (they use the "Number" / "May disburse own loan" options)
DISBURSE_ROLES = ('disbursor', 'disbursor_backup', 'hr_accountant', 'hr_accountant_backup')

# Which roles exist for which tier of the BORROWER's work unit.
TIER_ROLES = {
    'branch': ('approver', 'manager_approver', 'disbursor', 'disbursor_backup'),
    'district': ('approver', 'director_approver', 'disbursor', 'disbursor_backup'),
    'head_office': ('ho_approver', 'hr_approver', 'hr_auditor', 'hr_accountant',
                    'hr_accountant_backup'),
}
# Where the people may be taken from, per tier.
TIER_SOURCES = {
    'branch': ('branch', 'district', 'head_office'),
    'district': ('district', 'branch', 'head_office'),
    'head_office': ('head_office', 'district', 'branch'),
}
# Head Office roles are also permissions (record rules, buttons, queues), so
# the people a rule designates are put in the matching RESL group.
ROLE_GROUPS = {
    'ho_approver': 'resl.group_resl_ho_approver',
    'hr_approver': 'resl.group_resl_hr_senior',
    'hr_auditor': 'resl.group_resl_hr_auditor',
    'hr_accountant': 'resl.group_resl_hr_accountant',
    'hr_accountant_backup': 'resl.group_resl_hr_accountant',
}
ROLE_LABELS = dict(ROLES)

# role -> the role it stands behind (its people are shown on the line)
LINKED_ROLE = {
    'manager_approver': 'approver',
    'director_approver': 'approver',
    'disbursor_backup': 'disbursor',
    'hr_approver': 'ho_approver',
    'hr_accountant_backup': 'hr_accountant',
}


class ReslRoutingRule(models.Model):
    _name = 'resl.routing.rule'
    _description = 'RESL Approver / Disbursor Assignment'
    _order = 'tier, role, sequence, id'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    unit_id = fields.Many2one(
        'operating.unit', string="District / Branch", index=True, ondelete='cascade',
        help="Set: this line applies ONLY to the staff of this district (or branch) and "
             "comes before the general lines. Empty: general line for every district "
             "(or branch). Set it from Configuration > District / Branch Setup.")
    scope_ou_ids = fields.Many2many(
        'operating.unit', compute='_compute_scope', string="Places people are chosen from")
    scope_warning = fields.Char(compute='_compute_scope')
    scope_dept_ids = fields.Many2many(
        'hr.department', compute='_compute_scope',
        string="Departments people are chosen from (district's department)")
    scope_job_ids = fields.Many2many(
        'hr.job', compute='_compute_scope', string="Job positions that have people there")
    setup_id = fields.Many2one('resl.routing.unit', string="Setup", ondelete='cascade', index=True)
    people_text = fields.Text(compute='_compute_people_text', string="Who it will be")
    linked_text = fields.Text(compute='_compute_people_text', string="Selected person(s) above")

    tier = fields.Selection(
        TIERS, string="Applies to borrowers working in", required=True, default='branch',
        help="The work unit type of the person who requests the loan.")
    role = fields.Selection(
        ROLES, string="Role", required=True, default='approver',
        help="Approver: approves the requests of the unit's staff.\n"
             "Manager's Approver (branch): approves the request of the person who is "
             "himself / herself the branch approver (the Manager).\n"
             "Director's Approver (district): approves the request of the person who is "
             "himself / herself the district approver (the Director).\n"
             "Disbursor: disburses the approved loans.")
    source = fields.Selection(
        [('branch', 'Branch'), ('district', 'District'), ('head_office', 'Head Office')],
        string="Select people from", required=True, default='branch',
        help="Where the job positions / employees are looked up. Chosen first, then the "
             "job positions and employees below.\n"
             "Branch: for a branch borrower its own branch; for a district borrower the "
             "branches of that district.\n"
             "District: for a branch borrower the district its branch belongs to; for a "
             "district borrower the district office itself.\n"
             "Head Office: the Head Office employees.")
    mode = fields.Selection(
        [('job', 'By job position'), ('employee', 'Specific employees')],
        string="Select by", required=True, default='job',
        ondelete={'both': lambda recs: recs._migrate_mode_both()},
        help="By job position: the people holding the job positions you list (in order). "
             "Specific employees: the employees you pick by name.")

    def _migrate_mode_both(self):
        """The removed choice "Job positions + additional employees": keep the
        job positions when there are some, otherwise the employees."""
        for rule in self:
            has_jobs = bool(rule.job_line_ids.filtered('job_id'))
            rule.mode = 'employee' if (rule.employee_ids and not has_jobs) else 'job'
    job_line_ids = fields.One2many(
        'resl.routing.rule.job', 'rule_id', string="Job positions (in order of preference)",
        copy=True)
    employee_ids = fields.Many2many(
        'hr.employee', 'resl_routing_rule_employee_rel', 'rule_id', 'employee_id',
        string="Employees",
        domain="[('user_id', '!=', False)]")
    max_count = fields.Integer(
        string="Number of disbursors", default=1,
        help="How many people are taken per borrower, in alphabetical order of name. "
             "Any one of them can disburse without the others.")
    fill_from_next_jobs = fields.Boolean(
        string="Complete from the next job positions",
        help="When the first job position has fewer people than the number wanted, "
             "take the missing ones from the following job positions of the list. "
             "Off: the next job position is used only when the first has nobody.")
    allow_self_disburse = fields.Boolean(
        string="May disburse own loan", default=False,
        help="Disbursor only. On: a selected disbursor who is himself / herself the "
             "borrower disburses his / her own loan. Off: another person is selected "
             "for that loan (the borrower is skipped).")
    granted_user_ids = fields.Many2many(
        'res.users', 'resl_routing_rule_granted_rel', 'rule_id', 'user_id',
        string="Users given the RESL group by this rule", readonly=True, copy=False)
    note = fields.Char(compute='_compute_note')
    job_summary = fields.Char(compute='_compute_job_summary')

    # ── display ────────────────────────────────────────────────────────────
    @api.depends('tier', 'role', 'unit_id')
    def _compute_name(self):
        tiers = dict(TIERS)
        for rule in self:
            rule.name = "%s - %s" % (
                rule.unit_id.name if rule.unit_id else tiers.get(rule.tier, ''),
                ROLE_LABELS.get(rule.role, ''))

    @api.depends('tier', 'role', 'unit_id', 'mode', 'job_line_ids.job_id', 'employee_ids',
                 'max_count', 'source')
    def _compute_people_text(self):
        """Shows the employees a line designates (jobs -> their employees), and,
        for 'X's Approver / Disburser's Disburser' lines, the person(s) of the
        line they stand behind."""
        Employee = self.env['hr.employee'].sudo()

        def names(emps):
            emps = emps[:30]
            return ', '.join(
                "%s%s" % (e.name, " (%s)" % (e.job_title or e.job_id.name)
                          if (e.job_title or e.job_id) else '') for e in emps)

        for rule in self:
            text = linked = ''
            if rule.id and (rule.unit_id or rule.tier == 'head_office'):
                try:
                    unit = rule.unit_id
                    text = names(rule._pick(Employee.browse(), unit, None, all_matches=True))
                    base_role = LINKED_ROLE.get(rule.role)
                    if base_role:
                        base = self.sudo().search([
                            ('tier', '=', rule.tier), ('role', '=', base_role),
                            ('unit_id', '=', unit.id)])
                        people = Employee.browse()
                        for b in base:
                            people |= b._pick(Employee.browse(), unit, None, all_matches=True)
                        linked = names(people)
                except Exception:
                    _logger.exception("RESL: could not compute the people of rule %s", rule.id)
            rule.people_text = text
            rule.linked_text = linked

    @api.depends('job_line_ids.job_id', 'job_line_ids.sequence')
    def _compute_job_summary(self):
        for rule in self:
            rule.job_summary = ' > '.join(
                rule._job_label(j.name)
                for j in rule.job_line_ids.sorted(lambda l: (l.sequence, l.id)).mapped('job_id'))

    @api.depends('tier', 'role', 'source')
    def _compute_note(self):
        for rule in self:
            note = ''
            if rule.role in ('disbursor_backup', 'hr_accountant_backup'):
                note = _("Used instead of the Disburser when the borrower is himself / herself "
                         "the Disburser (nobody disburses his / her own loan).")
            elif rule.tier == 'district' and rule.role == 'disbursor':
                note = _("The selected disbursor (an employee anywhere, e.g. in a branch) "
                         "disburses the district-office staff who are in the SAME department "
                         "as the disbursor. Branch staff keep their own branch disbursor.")
            elif rule.tier == 'head_office':
                note = _("The selected people are also given the matching RESL group "
                         "(permissions); it is removed again when they are no longer selected.")
            rule.note = note

    # ── onchange / constraints ─────────────────────────────────────────────
    @api.onchange('tier')
    def _onchange_tier(self):
        for rule in self:
            if rule.role not in TIER_ROLES.get(rule.tier, ()):
                rule.role = TIER_ROLES[rule.tier][0] if rule.tier else False
            if rule.source not in TIER_SOURCES.get(rule.tier, ()):
                rule.source = TIER_SOURCES[rule.tier][0] if rule.tier else False

    @api.constrains('tier', 'role', 'source', 'unit_id', 'max_count', 'mode', 'job_line_ids', 'employee_ids')
    def _check_rule(self):
        for rule in self:
            if rule.role not in TIER_ROLES.get(rule.tier, ()):
                raise ValidationError(_(
                    "The role '%(role)s' does not exist for %(tier)s borrowers.") % {
                        'role': ROLE_LABELS.get(rule.role, ''),
                        'tier': dict(TIERS).get(rule.tier, '')})
            if rule.source not in TIER_SOURCES.get(rule.tier, ()):
                raise ValidationError(_(
                    "For %(tier)s borrowers people can only be selected from: %(src)s.") % {
                        'tier': dict(TIERS).get(rule.tier, ''),
                        'src': ', '.join(dict(TIERS)[s] for s in TIER_SOURCES[rule.tier])})
            if rule.unit_id:
                types = BRANCH_TYPES if rule.tier == 'branch' else (
                    DISTRICT_TYPES if rule.tier == 'district' else ())
                if rule.unit_id.work_unit_type not in types:
                    raise ValidationError(_(
                        "%(unit)s is not a work unit of type %(tier)s.") % {
                            'unit': rule.unit_id.name, 'tier': dict(TIERS).get(rule.tier, '')})
            if rule.max_count < 1:
                raise ValidationError(_("The number of people must be at least 1."))
            # A line may stay empty (default lines the admin has not filled in
            # yet): it designates nobody and the next line / built-in behaviour is used.

    # ── organisation helpers ───────────────────────────────────────────────
    @api.model
    def _ou_parent_field(self):
        """Name of the operating.unit field that points a branch to its
        district. Set the system parameter `resl.ou_parent_field` when the
        field has a different name than the usual ones."""
        OU = self.env['operating.unit'].sudo()
        param = self.env['ir.config_parameter'].sudo().get_param('resl.ou_parent_field')
        names = ([param] if param else []) + [
            'parent_id', 'district_id', 'district_office_id',
            'parent_operating_unit_id', 'parent_unit_id', 'region_id']
        # any other field of operating.unit that points to operating.unit
        for fname, fld in OU._fields.items():
            if (fld.type == 'many2one' and fld.comodel_name == 'operating.unit'
                    and fld.store and fname not in names
                    and fname not in ('create_uid', 'write_uid')):
                names.append(fname)
        first = False
        for fname in names:
            fld = OU._fields.get(fname)
            if not (fld and fld.type == 'many2one' and fld.comodel_name == 'operating.unit'):
                continue
            first = first or fname
            # the link that is really filled in (an empty parent_id is skipped)
            if OU.search_count([(fname, '!=', False)]):
                return fname
        return first

    @api.model
    def _district_of(self, ou):
        """The district / regional office a work unit belongs to (itself when
        it already is one)."""
        OU = self.env['operating.unit'].sudo()
        if not ou:
            return OU.browse()
        ou = ou.sudo()
        if ou.work_unit_type in DISTRICT_TYPES:
            return ou
        fname = self._ou_parent_field()
        node = ou
        for _i in range(6):
            parent = node[fname] if fname else False
            if not parent:
                break
            if parent.work_unit_type in DISTRICT_TYPES:
                return parent
            node = parent
        return OU.browse()

    @api.model
    def _branches_of(self, district_ou):
        """Branches (any depth) that belong to a district / regional office."""
        OU = self.env['operating.unit'].sudo()
        fname = self._ou_parent_field()
        if not (district_ou and fname):
            return OU.browse()
        found = OU.browse()
        level = district_ou.sudo()
        for _i in range(4):
            level = OU.search([(fname, 'in', level.ids)]) - found
            if not level:
                break
            found |= level
        return found.filtered(lambda o: o.work_unit_type in BRANCH_TYPES)

    @api.model
    def _district_by_department(self, dept):
        """The district office whose setup department is `dept` or one of its
        parents: branch staff belong to a district through their department
        (the same department as the district's staff)."""
        OU = self.env['operating.unit'].sudo()
        if not dept:
            return OU.browse()
        dept = dept.sudo()
        ancestors = {int(x) for x in (dept.parent_path or '').split('/') if x} | {dept.id}
        units = self.env['resl.routing.unit'].sudo().with_context(active_test=False).search(
            [('department_id', 'in', list(ancestors)), ('tier', '=', 'district')])
        # the closest (deepest) department wins
        units = units.sorted(lambda u: -len((u.department_id.parent_path or '').split('/')))
        return units[:1].operating_unit_id

    def _dept_scope(self):
        """Department the branch people of a district's own line must belong
        to (the district's department and its sub-departments)."""
        self.ensure_one()
        Dept = self.env['hr.department'].sudo()
        if self.unit_id and self.tier == 'district' and self.source == 'branch':
            unit = self.env['resl.routing.unit'].sudo().with_context(active_test=False).search(
                [('operating_unit_id', '=', self.unit_id.id)], limit=1)
            return unit.department_id.sudo()
        return Dept.browse()

    def _dept_for_pick(self, borrower, borrower_ou):
        """Department filter used when the loan picks people."""
        self.ensure_one()
        dept = self._dept_scope()
        if dept:
            return dept
        # general District line, branches wanted, but no branch is linked to the
        # district on the operating unit: use the borrower's department instead
        if (self.tier == 'district' and self.source == 'branch' and not self.unit_id
                and borrower and borrower.sudo().department_id):
            district = self._district_of(borrower_ou) if borrower_ou else False
            if not (district and self._branches_of(district)):
                return borrower.sudo().department_id
        return self.env['hr.department'].browse()

    def _branch_ous_of_unit(self):
        """Branch OUs of this line's district: all branch units when the
        district has a department (the department narrows the people), else the
        branches linked to it on the operating unit."""
        self.ensure_one()
        OU = self.env['operating.unit'].sudo()
        if self._dept_scope():
            return OU.search([('work_unit_type', 'in', list(BRANCH_TYPES))])
        return self._branches_of(self.unit_id.sudo())

    def _scope_ous(self, borrower_ou, borrower=None):
        """Operating units the people are taken from, for this borrower."""
        self.ensure_one()
        OU = self.env['operating.unit'].sudo()
        if self.source == 'head_office':
            return OU.search([('work_unit_type', '=', 'head_office')])
        if self.unit_id and self.tier == 'district':
            # a district's own line: only that district / the branches of that district
            if self.source == 'district':
                return self.unit_id.sudo()
            return self._branch_ous_of_unit()
        if self.tier == 'district' and self.role == 'disbursor':
            # No branch -> district link needed: the disbursor can be any
            # employee of the chosen kind of unit; what ties him / her to a
            # borrower is the department (see _pick).
            types = BRANCH_TYPES if self.source == 'branch' else DISTRICT_TYPES
            return OU.search([('work_unit_type', 'in', list(types))])
        if self.tier == 'head_office':
            # Head Office lines are not tied to a borrower's place: every
            # district / branch unit when that is where the people come from
            types = DISTRICT_TYPES if self.source == 'district' else BRANCH_TYPES
            return OU.search([('work_unit_type', 'in', list(types))])
        if self.tier == 'branch' and self.source == 'branch':
            return borrower_ou.sudo() if borrower_ou else OU.browse()
        if self.tier == 'branch' and self.source == 'district':
            district = self._district_of(borrower_ou) if borrower_ou else OU.browse()
            if not district and borrower:
                district = self._district_by_department(borrower.sudo().department_id)
            return district
        if not borrower_ou:
            return OU.browse()
        if self.tier == 'district':
            if self.source == 'district':
                return self._district_of(borrower_ou) or borrower_ou.sudo()
            if self.source == 'branch':
                branches = self._branches_of(self._district_of(borrower_ou) or borrower_ou)
                # no link on the operating unit: the department narrows (see _pick)
                return branches or OU.search([('work_unit_type', 'in', list(BRANCH_TYPES))])
        return OU.browse()

    def _picker_ous(self):
        """Operating units the job positions / employees may be CHOSEN from
        when filling in this line.
          - a district's own line: that district only (source District), or
            the branches of that district (source Branch, narrowed by the
            district's department);
          - Branch Setup / HO Setup / general lines: every unit of the kind."""
        self.ensure_one()
        OU = self.env['operating.unit'].sudo()
        if self.source == 'head_office':
            return OU.search([('work_unit_type', '=', 'head_office')])
        if self.unit_id and self.tier == 'district':
            if self.source == 'district':
                return self.unit_id.sudo()
            return self._branch_ous_of_unit()
        types = DISTRICT_TYPES if self.source == 'district' else BRANCH_TYPES
        return OU.search([('work_unit_type', 'in', list(types))])

    def _picker_domain(self, use_dept=True):
        """hr.employee domain of everybody this line may choose from.
        `use_dept=False` skips the district-department narrowing (used to list
        the job positions, so that every position of the branches shows)."""
        self.ensure_one()
        dom = [('default_operating_unit_id', 'in', self._picker_ous().ids),
               ('user_id', '!=', False)]
        dept = self._dept_scope() if use_dept else False
        if dept:
            dom.append(('department_id', 'child_of', dept.id))
        return dom

    @api.model
    def _job_level_counts(self):
        """{level: {job id: active employees with a user}} for the three levels."""
        Employee = self.env['hr.employee'].sudo()
        levels = {'branch': BRANCH_TYPES, 'district': DISTRICT_TYPES,
                  'head_office': ('head_office',)}
        out = {}
        for level, types in levels.items():
            out[level] = {
                job.id: count for job, count in Employee._read_group(
                    [('default_operating_unit_id.work_unit_type', 'in', list(types)),
                     ('user_id', '!=', False), ('job_id', '!=', False)],
                    groupby=['job_id'], aggregates=['__count'])}
        return out

    @api.depends('tier', 'source', 'unit_id', 'setup_id.department_id')
    def _compute_scope(self):
        Employee = self.env['hr.employee'].sudo()
        Dept = self.env['hr.department'].sudo()
        level_counts = None
        for rule in self:
            ready = bool(rule.tier and rule.source)
            ous = rule._picker_ous() if ready else rule.env['operating.unit']
            dept = rule._dept_scope() if ready else Dept.browse()
            rule.scope_ou_ids = ous
            rule.scope_dept_ids = Dept.search([('id', 'child_of', dept.id)]) if dept else Dept
            rule.scope_warning = False
            if ready and rule.unit_id and rule.tier == 'district' and rule.source == 'branch' \
                    and not dept and not ous:
                rule.scope_warning = _(
                    "No branch can be found for %s. Set the District department on its "
                    "District Setup: the branch employees working under the district are "
                    "the ones in that department.") % rule.unit_id.name
            jobs = self.env['hr.job']
            if ready and ous:
                for job, _count in Employee._read_group(
                        rule._picker_domain(use_dept=False) + [('job_id', '!=', False)],
                        groupby=['job_id'], aggregates=['__count']):
                    jobs |= job
                # District / Head Office: a job position belongs to the level
                # where most of its people work (a Branch Manager seen once in a
                # district office does not make it a district job position).
                # Branch: every job position found in the branches is listed.
                if rule.source != 'branch':
                    if level_counts is None:
                        level_counts = self._job_level_counts()
                    mine = level_counts.get(rule.source, {})
                    jobs = jobs.filtered(lambda j: mine.get(j.id, 0) and mine.get(j.id, 0) >= max(
                        lc.get(j.id, 0) for lc in level_counts.values()))
            # One entry per kind of job position: "Director I" of every district
            # is the same choice (the borrower's own district is found when the
            # request is routed), so it is listed once.
            first = {}
            for j in jobs.sorted('id'):
                first.setdefault(rule._job_family(j.name), j)
            rule.scope_job_ids = self.env['hr.job'].concat(*first.values()) if first else jobs

    # ── candidate lookup ───────────────────────────────────────────────────
    @staticmethod
    def _job_label(name):
        """Generic label of a job position, original casing:
        "Director I - Bahir Dar District" -> "Director I"."""
        name = re.sub(r'\s+', ' ', (name or '')).strip()
        if '-' in name and re.search(r'\bdistrict$', name, re.I):
            name = name.split('-', 1)[0]
        return name.strip()

    @staticmethod
    def _job_family(name):
        """Generic name of a district-specific job position:
        "Director I - Bahir Dar District", "Director I- East Addis Ababa District"
        -> "director i". Names that do not end with "District" are kept as they
        are ("Branch Manager - I" stays "branch manager - i")."""
        name = re.sub(r'\s+', ' ', (name or '')).strip()
        if '-' in name and re.search(r'\bdistrict$', name, re.I):
            name = name.split('-', 1)[0]
        return re.sub(r'\s+', ' ', name).strip().lower()

    def _same_named_jobs(self, job):
        """The job position and every job position of the same kind: same name,
        or the same generic name in another district (Director I of every
        district). The district itself is chosen by the people lookup (the
        borrower's district / department), so each borrower reaches the Director
        of ITS district."""
        Job = self.env['hr.job'].sudo()
        family = self._job_family(job.name)
        same = Job.search([('name', '=', job.name)])
        if family and family != (job.name or '').strip().lower():
            same |= Job.search([('name', 'ilike', family.split(' ')[0])]).filtered(
                lambda j: self._job_family(j.name) == family)
        return job | same

    def _pick(self, borrower, borrower_ou, exclude_ids=None, all_matches=False):
        """hr.employee recordset (alphabetical, at most `max_count`) this rule
        designates for the borrower. `all_matches` returns every person the
        rule can ever designate (used to give the Head Office groups)."""
        self.ensure_one()
        Employee = self.env['hr.employee'].sudo()
        ous = self._scope_ous(borrower_ou, borrower)
        if not ous and not (self.mode in ('employee', 'both') and self.employee_ids):
            return Employee.browse()
        domain = [('user_id', '!=', False)]
        if self.source == 'district' and 'operating_unit_ids' in Employee._fields:
            domain += ['|', ('default_operating_unit_id', 'in', ous.ids),
                       ('operating_unit_ids', 'in', ous.ids)]
        else:
            domain.append(('default_operating_unit_id', 'in', ous.ids))
        dept = self._dept_for_pick(borrower, borrower_ou)
        if dept:
            domain.append(('department_id', 'child_of', dept.id))
        if exclude_ids and not (self.role == 'disbursor' and self.allow_self_disburse):
            domain.append(('id', 'not in', list(exclude_ids)))
        # District disbursor: only the district-office staff of the SAME
        # department as the disbursor. The branches of the district have
        # their own disbursor.
        if (self.tier == 'district' and self.role == 'disbursor' and not all_matches
                and not self.unit_id):
            dept = borrower.sudo().department_id if borrower else False
            if not dept:
                return Employee.browse()
            domain.append(('department_id', '=', dept.id))

        order = 'name asc, id asc'
        count = self.max_count or 1
        emp_found = Employee.browse()
        if self.mode in ('employee', 'both') and self.employee_ids:
            # names picked by hand are taken wherever they work
            emp_domain = [d for d in domain if not (
                isinstance(d, (tuple, list)) and d and (d[0] in (
                    'default_operating_unit_id', 'operating_unit_ids')
                    or (len(d) > 1 and d[1] == 'child_of')))
                and d != '|']
            emp_found = Employee.search(emp_domain + [('id', 'in', self.employee_ids.ids)],
                                        order=order)
        if self.mode == 'employee':
            # every employee picked by hand can act (any one of them)
            return emp_found

        found = Employee.browse()
        for line in self.job_line_ids.sorted(lambda l: (l.sequence, l.id)):
            if not line.job_id:
                continue
            leaves = [('job_id', 'in', self._same_named_jobs(line.job_id).ids)]
            if 'job_title' in Employee._fields:
                leaves = ['|', ('job_title', '=ilike', line.job_id.name)] + leaves
            people = Employee.search(domain + leaves, order=order) - found
            if not people:
                continue
            if all_matches:
                found |= people
                continue
            if not self.fill_from_next_jobs:
                found |= people
                break
            found |= people[:count - len(found)]
            if len(found) >= count:
                break
        # 'both': the employees added by hand come after the job-position people
        return (found if all_matches else found[:count]) | emp_found

    @api.model
    def _tables_ready(self):
        """False while the module is being installed / upgraded and the
        configuration tables do not exist yet (a failed SQL statement would
        abort the whole upgrade transaction, even when caught in Python)."""
        from odoo.tools import sql
        cr = self.env.cr
        return all(sql.table_exists(cr, t) for t in (
            'resl_routing_rule', 'resl_routing_rule_job', 'resl_routing_rule_employee_rel'))

    @api.model
    def resolve(self, tier, role, borrower, borrower_ou, exclude_ids=None):
        """People designated for `role` on a borrower of this `tier`, or an
        empty recordset when no rule is configured / nobody is found (the
        caller then uses the previous behaviour)."""
        Employee = self.env['hr.employee'].sudo()
        if not self._tables_ready():
            return Employee.browse()
        unit = self._unit_for(tier, borrower_ou)
        rules = self.sudo().search(
            [('tier', '=', tier), ('role', '=', role),
             '|', ('unit_id', '=', False), ('unit_id', '=', unit.id or 0)],
            order='sequence, id')
        # the lines made for THIS district / branch come before the general ones
        rules = rules.sorted(lambda r: (0 if r.unit_id else 1, r.sequence, r.id))
        for rule in rules:
            people = rule._pick(borrower, borrower_ou, exclude_ids)
            if people:
                return people
        return Employee.browse()

    @api.model
    def _unit_for(self, tier, ou):
        """The district (district tier) or branch (branch tier) whose own
        setup applies to a borrower working in `ou`."""
        OU = self.env['operating.unit'].sudo()
        if not ou or tier not in ('branch', 'district'):
            return OU.browse()
        ou = ou.sudo()
        if tier == 'branch':
            return ou
        return self._district_of(ou) or ou

    @api.model
    def has_rules(self, tier, role):
        if not self._tables_ready():
            return False
        return bool(self.sudo().search_count([('tier', '=', tier), ('role', '=', role)]))

    # ── Head Office roles <-> RESL groups ──────────────────────────────────
    @api.model
    def sync_role_groups(self, orphans=None):
        """Give the Head Office roles' RESL group to the people the rules
        designate, and take it back from people this module gave it to who
        are no longer designated. Groups assigned by hand are never removed.
        `orphans` = {role: users} granted by rules that were just deleted."""
        Users = self.env['res.users'].sudo()
        Employee = self.env['hr.employee'].sudo()
        orphans = orphans or {}
        if not self._tables_ready():
            return True
        by_group = {}
        for role, xmlid in ROLE_GROUPS.items():
            by_group.setdefault(xmlid, []).append(role)
        for xmlid, roles in by_group.items():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            rules = self.sudo().with_context(active_test=False).search(
                [('tier', '=', 'head_office'), ('role', 'in', roles)], order='id')
            orphan_users = Users
            for role in roles:
                orphan_users |= orphans.get(role, Users)
            wanted = Users
            for rule in rules.filtered('active'):
                wanted |= rule._pick(Employee.browse(), False, None, all_matches=True).mapped('user_id')
            members = group.sudo().user_ids - orphan_users
            to_add = wanted - members
            # the flag stops res.users.write (which refreshes the loan routing,
            # and that refresh synchronises the groups) from re-entering here
            writer = Users.with_context(resl_syncing_groups=True)
            if to_add:
                writer.browse(to_add.ids).write({'group_ids': [(4, group.id)]})
            to_remove = (rules.mapped('granted_user_ids') | orphan_users) - wanted
            if to_remove:
                writer.browse(to_remove.ids).write({'group_ids': [(3, group.id)]})
            for index, rule in enumerate(rules):
                granted = rule.granted_user_ids - to_remove
                if index == 0:
                    granted |= to_add
                if granted != rule.granted_user_ids:
                    rule.write({'granted_user_ids': [(6, 0, granted.ids)]})
        return True

    # ── keep open loans in line with the configuration ─────────────────────
    @api.model
    def _refresh_open_loans(self):
        try:
            loans = self.env['resl.loan'].sudo().search([
                ('status', 'in', ('draft', 'guarantor_pending', 'manager_review', 'approved')),
                ('core_banking_status', '!=', 'disbursed'),
            ])
            loans._compute_designated_approver()
        except Exception:
            _logger.exception("RESL: could not refresh the routing of open loans")

    def _after_change(self):
        try:
            self.env['resl.routing.rule'].sync_role_groups()
        except Exception:
            _logger.exception("RESL: could not synchronise the Head Office role groups")
        self.env['resl.routing.rule']._refresh_open_loans()
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        if not self.env.context.get('resl_skip_refresh'):
            rules._after_change()
        return rules

    def write(self, vals):
        res = super().write(vals)
        if (set(vals) - {'granted_user_ids', 'sequence'}
                and not self.env.context.get('resl_skip_refresh')):
            self._after_change()
        return res

    def unlink(self):
        orphans = {}
        for rule in self:
            if rule.tier == 'head_office' and rule.role in ROLE_GROUPS:
                orphans[rule.role] = orphans.get(rule.role, self.env['res.users']) | rule.granted_user_ids
        res = super().unlink()
        self.env['resl.routing.rule'].sync_role_groups(orphans=orphans)
        self.env['resl.routing.rule']._refresh_open_loans()
        return res

    def action_apply_now(self):
        """Button: re-apply the configuration to the open requests now."""
        self._after_change()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("Routing updated"), 'type': 'success', 'sticky': False,
                       'message': _("Open requests now follow this configuration.")},
        }

    @api.model
    def _remove_job_picker_view(self):
        """Earlier version made a separate hr.job list view; the columns are now
        handled in models/hr_job_list.py, so that view is removed."""
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'resl'), ('name', '=', 'view_hr_job_picker_list')])
        for rec in data:
            self.env['ir.ui.view'].sudo().browse(rec.res_id).exists().unlink()
            rec.unlink()
        return True

    # ── default configuration ──────────────────────────────────────────────
    @staticmethod
    def _job_key(name):
        """'Branch Manager - I' == 'branch manager-i' == 'Branch  Manager -I';
        '&' counts as 'and'."""
        import re
        return re.sub(r'[^0-9a-z]+', '', (name or '').lower().replace('&', ' and '))

    @api.model
    def _find_default_job(self, name):
        """hr.job called `name`, ignoring case, spaces, hyphens and '&' / 'and'
        ("Branch Manager - I" finds "Branch Manager-I" but never "... - II").
        When there is no such job, the only job whose name contains / is contained
        in it (not for names ending in a grade like "- I"). Empty recordset when
        nothing fits."""
        import re
        Job = self.env['hr.job'].sudo().with_context(active_test=False)
        key = self._job_key(name)
        key_no_and = key.replace('and', '')
        jobs = Job.search([])

        def pick(found):
            active = found.filtered('active') if 'active' in Job._fields else found
            return (active or found)[:1]

        exact = jobs.filtered(lambda j: self._job_key(j.name) == key or
                              self._job_key(j.name).replace('and', '') == key_no_and)
        if exact:
            return pick(exact)
        graded = re.search(r'(^|[-\s])(i{1,3}|iv|v|vi{0,3}|\d+)$', (name or '').strip().lower())
        if graded or len(key) < 10:
            return Job.browse()
        loose = jobs.filtered(lambda j: self._job_key(j.name) and (
            key in self._job_key(j.name) or self._job_key(j.name) in key))
        return pick(loose) if len(loose) == 1 else Job.browse()

    @api.model
    def _similar_job_names(self, name, limit=8):
        """Names of existing job positions (archived ones too) that look like
        `name`, for the message when a default job position is not found."""
        words = [w.lower() for w in (name or '').replace('-', ' ').replace('&', ' ').split()
                 if len(w) > 3 and w.lower() != 'and']
        jobs = self.env['hr.job'].sudo().with_context(active_test=False).search([])
        scored = sorted(
            ((sum(w in (j.name or '').lower() for w in words), j) for j in jobs),
            key=lambda t: -t[0])
        return [j.name + ('' if j.active else ' [archived]')
                for score, j in scored[:limit] if score]

    def _fill_default_jobs(self, jobs):
        """Put the default job positions on a line that has neither job
        positions nor employees yet (a line somebody filled is never touched)."""
        for rule in self:
            if (rule.mode != 'job' or rule.job_line_ids.filtered('job_id')
                    or rule.employee_ids):
                continue
            lines = []
            for seq, name in enumerate(jobs, start=1):
                job = self._find_default_job(name)
                if job:
                    lines.append((0, 0, {'sequence': seq * 10, 'job_id': job.id}))
            if lines:
                rule.with_context(resl_skip_refresh=True).write({'job_line_ids': lines})

    # (tier, role, source, [default jobs], max_count, allow_self_disburse)
    # Branch = ONE set for every branch. District lines per district: see
    # resl.routing.unit. Head Office: no job names are known, filled by hand.
    GENERAL_DEFAULTS = [
        ('branch', 'approver', 'branch', ['Branch Manager - I'], 1, False),
        ('branch', 'manager_approver', 'district', ['District Director'], 1, False),
        ('branch', 'disbursor', 'branch', ['Branch Sales and Relationship Officer'], 1, False),
        ('branch', 'disbursor_backup', 'branch', ['Branch Manager - I'], 1, False),
        ('district', 'approver', 'district', ['District Director'], 1, False),
        ('district', 'director_approver', 'branch', ['Branch Support and Compliance Officer'], 1, False),
        ('district', 'disbursor', 'branch', ['Branch Sales and Relationship Officer'], 1, False),
        ('district', 'disbursor_backup', 'branch', ['Branch Manager - I'], 1, False),
        ('head_office', 'ho_approver', 'head_office', [], 1, False),
        ('head_office', 'hr_approver', 'head_office', [], 1, False),
        ('head_office', 'hr_auditor', 'head_office', [], 1, False),
        ('head_office', 'hr_accountant', 'head_office', [], 1, False),
        ('head_office', 'hr_accountant_backup', 'head_office', [], 1, False),
    ]

    # (tier, role) -> (source, default jobs) of the second set of defaults
    DEFAULTS_V2 = {
        ('branch', 'approver'): ('branch', ['Branch Manager - I']),
        ('branch', 'manager_approver'): ('district', ['District Director']),
        ('branch', 'disbursor'): ('branch', ['Branch Sales and Relationship Officer']),
        ('branch', 'disbursor_backup'): ('branch', ['Branch Manager - I']),
        ('district', 'director_approver'): ('branch', ['Branch Support and Compliance Officer']),
        ('district', 'disbursor'): ('branch', ['Branch Sales and Relationship Officer']),
    }

    def action_set_default(self):
        """Put the selected line(s) back to their default: where people come from,
        job positions in order, no hand-picked employees, "May disburse own
        loan" unticked. Tells which default job positions do not exist."""
        lookup = {(t, r): (src, jobs, cnt, selfd)
                  for t, r, src, jobs, cnt, selfd in self.GENERAL_DEFAULTS}
        missing = []
        quiet = self.with_context(resl_skip_refresh=True)
        for rule in quiet:
            default = lookup.get((rule.tier, rule.role))
            if not default:
                continue
            source, jobs, count, self_disb = default
            rule.write({
                'source': source, 'mode': 'job' if jobs else 'employee',
                'job_line_ids': [(5, 0, 0)], 'employee_ids': [(5, 0, 0)],
                'allow_self_disburse': self_disb, 'max_count': count})
            for seq, name in enumerate(jobs, start=1):
                job = self._find_default_job(name)
                if job:
                    rule.write({'job_line_ids': [(0, 0, {'sequence': seq * 10,
                                                         'job_id': job.id})]})
                else:
                    missing.append(name)
        self.env['resl.routing.rule']._after_change()
        message = _("Set to default.")
        if missing:
            parts = []
            for name in sorted(set(missing)):
                similar = self._similar_job_names(name)
                parts.append("%s%s" % (name, (" (similar: %s)" % ', '.join(similar)) if similar else ''))
            message = _("Set to default, but these job positions were not found, pick the "
                        "job yourself or fix its name in Job Positions: %s") % '; '.join(parts)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("Default lines"), 'message': message,
                       'type': 'warning' if missing else 'success', 'sticky': bool(missing),
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    @api.model
    def action_reset_all_defaults(self):
        """Every Branch and District line (Branch Setup, the general District lines
        and each district's own lines) back to its default. Head Office lines are
        left alone: no defaults are known for them."""
        rules = self.sudo().with_context(active_test=False).search(
            [('tier', 'in', ('branch', 'district'))])
        return rules.action_set_default()

    @api.model
    def _migrate_defaults_v2(self):
        """ONCE: put the new default job positions on the Branch / District lines
        (general and each district's own) and untick "May disburse own loan"
        everywhere. Afterwards nothing is overwritten."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('resl.defaults_v2_done') or not self._tables_ready():
            return True
        Rule = self.sudo().with_context(active_test=False, resl_skip_refresh=True)
        for (tier, role), (source, jobs) in self.DEFAULTS_V2.items():
            for rule in Rule.search([('tier', '=', tier), ('role', '=', role)]):
                rule.write({'source': source, 'mode': 'job',
                            'job_line_ids': [(5, 0, 0)], 'employee_ids': [(5, 0, 0)]})
                rule._fill_default_jobs(jobs)
        Rule.search([('allow_self_disburse', '=', True)]).write({'allow_self_disburse': False})
        ICP.set_param('resl.defaults_v2_done', '1')
        self.env['resl.routing.rule']._after_change()
        return True

    @api.model
    def _migrate_defaults_v3(self):
        """ONCE: the Branch "Approver's Approver" (the branch Manager's request)
        is approved by the District Director, picked from the DISTRICT office
        (a branch has no District Director). Afterwards nothing is overwritten."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('resl.defaults_v3_done') or not self._tables_ready():
            return True
        Rule = self.sudo().with_context(active_test=False, resl_skip_refresh=True)
        for rule in Rule.search([('tier', '=', 'branch'), ('role', '=', 'manager_approver')]):
            rule.write({'source': 'district', 'mode': 'job',
                        'job_line_ids': [(5, 0, 0)], 'employee_ids': [(5, 0, 0)]})
            rule._fill_default_jobs(['District Director'])
        ICP.set_param('resl.defaults_v3_done', '1')
        self.env['resl.routing.rule']._after_change()
        return True

    @api.model
    def _create_default_rules(self):
        """Make sure every general line (Branch Setup, HO Setup, and the
        fall-back District lines) exists, and give the empty ones their
        default job positions. Safe to run again: lines that exist are kept,
        lines somebody filled in are never changed."""
        if not self._tables_ready():
            return True
        Rule = self.sudo().with_context(active_test=False)
        created = self.browse()
        for tier, role, source, jobs, count, self_disb in self.GENERAL_DEFAULTS:
            rule = Rule.search([('tier', '=', tier), ('role', '=', role),
                                ('unit_id', '=', False)], limit=1)
            if not rule:
                rule = Rule.with_context(resl_skip_refresh=True).create({
                    'tier': tier, 'role': role, 'source': source,
                    'mode': 'job' if jobs else 'employee', 'max_count': count, 'allow_self_disburse': self_disb})
                created |= rule
            if not rule.active:
                continue
            rule._fill_default_jobs(jobs)
        self._migrate_defaults_v2()
        self._migrate_defaults_v3()
        self.env['resl.routing.rule']._after_change()
        return True


class ReslRoutingRuleJob(models.Model):
    _name = 'resl.routing.rule.job'
    _description = 'RESL Assignment - Job Position (ordered)'
    _order = 'sequence, id'

    rule_id = fields.Many2one('resl.routing.rule', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    job_id = fields.Many2one('hr.job', string="Job Position")
    employee_count = fields.Integer(
        string="Active employees", compute='_compute_employee_count',
        help="Active employees with a user holding this job position in the places "
             "this line chooses from.")

    @api.depends('job_id', 'rule_id.tier', 'rule_id.source', 'rule_id.unit_id')
    def _compute_employee_count(self):
        Employee = self.env['hr.employee'].sudo()
        for line in self:
            count = 0
            rule = line.rule_id
            if line.job_id and rule and rule.id:
                jobs = rule._same_named_jobs(line.job_id)
                count = Employee.search_count(
                    rule._picker_domain(use_dept=False) + [('job_id', 'in', jobs.ids)])
            line.employee_count = count