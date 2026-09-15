# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyDirectorPeerConfig(models.Model):
    """Director Peer Evaluation Exception Configuration.
    
    Stores explicit peer assignments for Directors & Executive Leadership as per Bunna Bank 360-degree evaluation rules.
    Auto-populates all Directorates and Executive positions as starting seed with empty peers.
    Restricts peer candidate dropdown strictly to employees with same coach & different position.
    """
    _name = 'competency.director.peer.config'
    _description = 'Director Peer Evaluation Configuration'
    _order = 'director_id'
    _rec_name = 'director_id'

    director_id = fields.Many2one(
        'hr.employee', string='Director', required=True, ondelete='cascade',
        index=True)
    job_id = fields.Many2one(
        'hr.job', related='director_id.job_id', string='Job Position', store=True, readonly=True)
    grade_id = fields.Many2one(
        'employee.grade', string='Job Grade', compute='_compute_grade_id', store=True, readonly=True)
    department_id = fields.Many2one(
        'hr.department', related='director_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit', compute='_compute_operating_unit_id', store=True, readonly=True)
    coach_id = fields.Many2one(
        'hr.employee', string='Coach / Supervisor', compute='_compute_coach_id', store=True, readonly=True)
    candidate_peer_ids = fields.Many2many(
        'hr.employee', compute='_compute_candidate_peer_ids',
        string='Candidate Peers Pool',
        help="Calculated pool of eligible peers sharing the director's coach with a different position.")
    peer_ids = fields.Many2many(
        'hr.employee', 'competency_director_peer_rel', 'config_id', 'peer_id',
        string='Assigned 360° Peers',
        domain="[('id', 'in', candidate_peer_ids)]",
        help="Select peers for this Director. Restricted strictly to candidates sharing the same coach with a different position.")
    notes = fields.Text(string='Notes / Rationale')

    @api.depends('director_id', 'director_id.grade_id', 'director_id.job_grade')
    def _compute_grade_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.director_id
                rec.grade_id = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False)
            else:
                rec.grade_id = False

    @api.depends('director_id', 'director_id.default_operating_unit_id', 'director_id.department_id', 'director_id.department_id.operating_unit_id')
    def _compute_operating_unit_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.director_id
                rec.operating_unit_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            else:
                rec.operating_unit_id = False

    @api.depends('director_id', 'director_id.coach_id', 'director_id.parent_id')
    def _compute_coach_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.director_id
                rec.coach_id = getattr(emp, 'coach_id', False) or emp.parent_id
            else:
                rec.coach_id = False

    @api.model
    def _get_grade_number(self, emp):
        """Extract numeric grade level (1..17) from employee's assigned job grade or position."""
        if not emp:
            return 0
        grade_rec = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False)
        if not grade_rec and emp.job_id:
            grade_rec = getattr(emp.job_id, 'grade', False) or getattr(emp.job_id, 'grade_id', False)
        if not grade_rec:
            return 0

        g_str = (getattr(grade_rec, 'grade_name', False) or getattr(grade_rec, 'name', False) or getattr(grade_rec, 'code', False) or str(grade_rec)).lower().strip()

        # Roman numerals map
        tokens = g_str.replace('-', ' ').replace('_', ' ').split()
        roman_map = {
            'xvii': 17, 'xvi': 16, 'xv': 15, 'xiv': 14, 'xiii': 13, 'xii': 12, 'xi': 11,
            'x': 10, 'ix': 9, 'viii': 8, 'vii': 7, 'vi': 6, 'v': 5, 'iv': 4, 'iii': 3, 'ii': 2, 'i': 1
        }
        for token in tokens:
            if token in roman_map:
                return roman_map[token]
        if g_str in roman_map:
            return roman_map[g_str]

        import re
        numbers = re.findall(r'\d+', g_str)
        if numbers:
            return int(numbers[0])

        return 0

    @api.model
    def _is_director_or_chief(self, emp):
        """Strictly classify as Director (Grade 16) or Chief (Grade 17). Exclude Grade II, III, IV, etc."""
        if not emp or not emp.active:
            return False
        g_num = self._get_grade_number(emp)
        if g_num in (16, 17):
            return True
        return False

    @api.depends('director_id', 'grade_id', 'director_id.job_id', 'director_id.grade_id', 'director_id.job_grade')
    def _compute_candidate_peer_ids(self):
        """Calculate pool of eligible peers for Directors (Grade 16) & Chiefs (Grade 17) matching the exception rule: Same Job Grade."""
        for rec in self:
            if not rec.director_id:
                rec.candidate_peer_ids = self.env['hr.employee']
                continue

            dir_emp = rec.director_id
            dir_g_num = self._get_grade_number(dir_emp)
            dir_grade_id = rec.grade_id.id if rec.grade_id else False

            domain = [('id', '!=', dir_emp.id), ('active', '=', True)]
            all_emps = self.env['hr.employee'].search(domain)

            if dir_g_num in (16, 17):
                candidates = all_emps.filtered(lambda c: self._get_grade_number(c) == dir_g_num)
            elif dir_grade_id:
                candidates = all_emps.filtered(lambda c: (
                    (getattr(c, 'grade_id', False) and c.grade_id.id == dir_grade_id) or
                    (getattr(c, 'job_grade', False) and c.job_grade.id == dir_grade_id) or
                    (c.job_id and getattr(c.job_id, 'grade_id', False) and c.job_id.grade_id.id == dir_grade_id) or
                    (c.job_id and getattr(c.job_id, 'grade', False) and c.job_id.grade.id == dir_grade_id)
                ))
            else:
                candidates = all_emps

            rec.candidate_peer_ids = candidates

    @api.constrains('director_id')
    def _check_unique_director(self):
        for rec in self:
            if rec.director_id:
                existing = self.search([
                    ('id', '!=', rec.id),
                    ('director_id', '=', rec.director_id.id)
                ], limit=1)
                if existing:
                    raise ValidationError(_("A peer configuration record already exists for Director '%s'.") % rec.director_id.name)

    @api.model
    def action_generate_director_records(self):
        """Scan active hr.employee records strictly for Directors (Grade 16) and Chiefs (Grade 17) and create missing configuration records, purging Grade II, III, IV, etc. non-executive entries."""
        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        director_emp_ids = set()

        for emp in all_employees:
            if self._is_director_or_chief(emp):
                director_emp_ids.add(emp.id)

        # Purge non-director/non-chief config records (e.g. Grade II, III, IV, etc.)
        invalid_configs = self.search([('director_id', 'not in', list(director_emp_ids))])
        if invalid_configs:
            invalid_configs.unlink()

        existing_director_ids = set(self.search([]).mapped('director_id.id'))
        created_count = 0

        for emp_id in director_emp_ids:
            if emp_id not in existing_director_ids:
                self.create({'director_id': emp_id})
                existing_director_ids.add(emp_id)
                created_count += 1

        msg = _("Successfully synchronized Director Peer Configuration. Created: %d, Total Active Directors (Grade 16) & Chiefs (Grade 17): %d. Non-executive records purged.") % (created_count, len(existing_director_ids))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Director Records Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            }
        }

