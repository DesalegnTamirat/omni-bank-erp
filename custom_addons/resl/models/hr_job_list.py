# -*- coding: utf-8 -*-
"""The Job Positions list (also the "Search more..." dialog of the approver /
disbursor lines): only Job Position, Grade, Number of employees and
Department. The recruitment / website columns are removed whatever views
the installed modules add."""
from odoo import api, models

# columns to remove, matched by the label the user sees
_REMOVE_LABELS = {
    'website', 'total forecasted employees', 'hired', 'hired employees', 'alias',
    'open applications', 'published', 'target', 'responsible',
}
# ... and by technical name (hr_recruitment / website_hr_recruitment)
_REMOVE_NAMES = {
    'website_id', 'expected_employees', 'no_of_hired_employee', 'alias_id', 'alias_name',
    'alias_email', 'application_count', 'open_application_count', 'is_published',
    'website_published', 'no_of_recruitment', 'user_id', 'interviewer_ids',
}


class HrJobList(models.Model):
    _inherit = 'hr.job'

    @api.depends_context('resl_job_family')
    def _compute_display_name(self):
        """On the Approvers & Disbursors lines a district job position shows its
        generic name: "Director I - Bahir Dar District" -> "Director I"."""
        super()._compute_display_name()
        if self.env.context.get('resl_job_family'):
            Rule = self.env['resl.routing.rule']
            for job in self:
                job.display_name = Rule._job_label(job.name) or job.display_name

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'list':
            self._resl_slim_list(arch)
        return arch, view

    @api.model
    def _resl_slim_list(self, arch):
        fields_map = self._fields
        grade = next((n for n, f in fields_map.items()
                      if f.store and 'grade' in n.lower()), None) or next(
            (n for n, f in fields_map.items()
             if f.store and 'grade' in (f.string or '').lower()), None)
        count = next((n for n in ('no_of_employee', 'employee_count')
                      if n in fields_map), None)

        def label(node):
            fld = fields_map.get(node.get('name'))
            return (node.get('string') or (fld.string if fld else '') or '').strip().lower()

        for node in list(arch.iter('field')):
            name = node.get('name')
            if name in (grade, count, 'name'):
                continue
            if name in _REMOVE_NAMES or label(node) in _REMOVE_LABELS:
                node.getparent().remove(node)

        # first columns: Job Position, Grade, Number of employees
        parent = None
        for node in arch.iter('field'):
            parent = node.getparent()
            break
        if parent is None:
            return
        wanted = [n for n in ('name', grade, count) if n]
        by_name = {n.get('name'): n for n in parent.findall('field')}
        position = 0
        for name in wanted:
            node = by_name.get(name)
            if node is None:
                continue
            for attr in ('optional', 'column_invisible', 'invisible'):
                if attr in node.attrib:
                    del node.attrib[attr]
            parent.remove(node)
            parent.insert(position, node)
            position += 1