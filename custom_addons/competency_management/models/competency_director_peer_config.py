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

    @api.depends('director_id', 'director_id.job_id', 'director_id.parent_id', 'director_id.coach_id', 'coach_id')
    def _compute_candidate_peer_ids(self):
        for rec in self:
            if not rec.director_id:
                rec.candidate_peer_ids = self.env['hr.employee']
                continue

            dir_emp = rec.director_id
            coach = rec.coach_id
            dir_job_id = dir_emp.job_id.id if dir_emp.job_id else False

            if coach:
                domain = [
                    ('id', '!=', dir_emp.id),
                    '|', ('parent_id', '=', coach.id), ('coach_id', '=', coach.id),
                ]
                if dir_job_id:
                    domain.append(('job_id', '!=', dir_job_id))
                candidates = self.env['hr.employee'].search(domain)
            else:
                domain = [('id', '!=', dir_emp.id)]
                if dir_job_id:
                    domain.append(('job_id', '!=', dir_job_id))
                candidates = self.env['hr.employee'].search(domain, limit=100)

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
        """Scan active hr.employee records strictly for Directors, Chiefs, VPs, Executives, and Leadership positions and create missing configuration records with empty peer lists, purging non-director entries."""
        import re

        pattern = re.compile(
            r'\b(director|chief|vp|vice president|executive director|managing director|president|ceo|cfo|cio|cto|coo|head of)\b',
            re.IGNORECASE
        )
        exclude_pattern = re.compile(
            r'\b(assistant|secretary|driver|clerk|officer|analyst|technician|specialist|junior|team leader|customer service|branch manager|division|consultant|maintenance|engineer|counsel|associate|attendant|guard|cashier|accountant|janitor|representative|auditor|agent|inspector|coordinator)\b',
            re.IGNORECASE
        )

        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        director_emp_ids = set()

        for emp in all_employees:
            job_name = emp.job_id.name or getattr(emp, 'job_title', '') or ''
            if pattern.search(job_name) and not exclude_pattern.search(job_name):
                director_emp_ids.add(emp.id)

        # Purge non-director config records
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

        msg = _("Successfully updated Director Peer Configuration records. Created: %d, Total Active Directors: %d.") % (created_count, len(existing_director_ids))
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

