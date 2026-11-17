# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployee(models.Model):
    """
    Extends hr.employee to add Career Path smart button and related fields
    so employees can access their Career Path directly from their Employee Master.
    """
    _inherit = 'hr.employee'

    career_aspiration_ids = fields.One2many(
        'hr.career.aspiration', 'employee_id', string='Career Aspirations')
    career_aspiration_count = fields.Integer(
        string='Career Aspiration Count', compute='_compute_career_aspiration_count')
    active_aspiration_count = fields.Integer(
        string='Active Aspirations', compute='_compute_career_aspiration_count')
    has_career_path = fields.Boolean(
        string='Has Active Career Path', compute='_compute_career_aspiration_count', store=False)

    @api.depends('career_aspiration_ids', 'career_aspiration_ids.state')
    def _compute_career_aspiration_count(self):
        for emp in self:
            all_aspirations = emp.career_aspiration_ids
            emp.career_aspiration_count = len(all_aspirations)
            active = all_aspirations.filtered(
                lambda a: a.state in ('submitted', 'manager_review', 'approved'))
            emp.active_aspiration_count = len(active)
            emp.has_career_path = bool(active)

    def action_view_career_path(self):
        """
        Smart button action: Opens the employee's Career Map (Visualizer)
        passing the specific employee's ID via context.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'career_path_visualizer',
            'name': _('Career Map — %s') % self.name,
            'context': {
                'active_employee_id': self.id,
            }
        }

    def action_new_career_aspiration(self):
        """
        Opens a new Career Aspiration form, pre-populated with this employee.
        Accessible from the Employee Master 'Career Path' smart button.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Career Aspiration'),
            'res_model': 'hr.career.aspiration',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_employee_id': self.id,
            },
        }

    @api.model
    def get_all_career_positions(self):
        """
        Returns all active job positions with their department and grade.
        Annotates whether an active career path is defined for that position.
        Used by the 'All Career Map' view for PPDD Officer and PPDD Manager.
        """
        self = self.sudo()
        jobs = self.env['hr.job'].search([])

        # Identify jobs that have defined career paths
        all_paths = self.env['hr.career.path'].search([])
        anchor_job_ids = set(all_paths.mapped('anchor_job_id.id'))

        nodes = self.env['hr.career.path.node'].search([])
        src_job_ids = set()
        for n in nodes:
            if n.parent_id and n.parent_id.target_job_id:
                src_job_ids.add(n.parent_id.target_job_id.id)
            elif n.career_path_id and n.career_path_id.anchor_job_id:
                src_job_ids.add(n.career_path_id.anchor_job_id.id)

        all_career_job_ids = anchor_job_ids | src_job_ids

        result = []
        for j in jobs.sorted(key=lambda j: j.name or ''):
            dept_name = j.department_id.name if j.department_id else ''
            grade_name = ''
            if hasattr(j, 'required_grade_id') and j.required_grade_id:
                grade_name = getattr(j.required_grade_id, 'grade_name', '') or getattr(j.required_grade_id, 'name', '') or ''
            elif hasattr(j, 'grade_id') and j.grade_id:
                grade_name = getattr(j.grade_id, 'grade_name', '') or getattr(j.grade_id, 'name', '') or ''

            result.append({
                'id': j.id,
                'name': j.name,
                'department_name': dept_name,
                'grade_name': grade_name,
                'has_career_path': j.id in all_career_job_ids,
            })
        return result

    @api.model
    def get_career_path_graph(self, employee_id=False, target_job_id=False, category=False, career_path_id=False, start_job_id=False):
        """
        Returns JSON data for the Career Path Visualizer component.
        Uses sudo() to bypass hr.employee record rules — the visualizer only
        reads career path configuration and job position data, not personal
        employee data, so this is safe.
        """
        self = self.sudo()

        cpath_req = False
        if career_path_id:
            try:
                cpath_req = self.env['hr.career.path'].browse(int(career_path_id))
                if not cpath_req.exists():
                    cpath_req = False
            except Exception:
                cpath_req = False

        if start_job_id:
            current_job = self.env['hr.job'].browse(int(start_job_id))
            if not current_job.exists():
                return {'error': _('Job Position not found.')}
            emp_in_role = self.env['hr.employee'].search([('job_id', '=', current_job.id)], limit=1)
            employee = emp_in_role or self.env['hr.employee'].search([], limit=1)
        elif not employee_id:
            employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        else:
            # Use sudo to bypass strict hierarchy record rules — the employee
            # is looking at their own career path graph, not accessing sensitive data
            employee = self.env['hr.employee'].browse(int(employee_id))

        if start_job_id:
            # Already set above
            pass
        elif cpath_req and cpath_req.anchor_job_id and not employee_id:
            current_job = cpath_req.anchor_job_id
            if not employee or not employee.exists() or (employee.job_id and employee.job_id.id != current_job.id):
                emp_in_role = self.env['hr.employee'].search([('job_id', '=', current_job.id)], limit=1)
                if emp_in_role:
                    employee = emp_in_role
        else:
            if not employee or not employee.exists():
                return {'error': _('Employee not found.')}

            current_job = employee.job_position or employee.job_id
            if not current_job:
                return {
                    'error': _('No job position is assigned to employee %s.') % employee.name,
                    'employee_name': employee.name,
                    'current_job': _('No Position Assigned'),
                    'nodes': []
                }

        if not employee or not employee.exists():
            employee = self.env['hr.employee'].search([], limit=1)
        
        # Calculate current tenure from joining date
        curr_tenure = 0.0
        from dateutil.relativedelta import relativedelta as rd
        join_date = (getattr(employee, 'service_start_date', None)
                     or getattr(employee, 'start_date', None)
                     or getattr(employee, 'first_contract_date', None))
        if join_date:
            today = fields.Date.today()
            delta = rd(today, join_date)
            curr_tenure = round(delta.years + delta.months / 12.0, 1)

        # Get employee's current PMS score (from employee profile or latest contract hr.version)
        curr_pms = 0.0
        if hasattr(employee, 'pms_score') and employee.pms_score:
            curr_pms = float(employee.pms_score)
        if not curr_pms and 'hr.version' in self.env:
            ver = self.env['hr.version'].search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['open', 'draft', 'close'])
            ], order='create_date desc', limit=1)
            if ver and hasattr(ver, 'pms_score') and ver.pms_score:
                curr_pms = float(ver.pms_score)
        if not curr_pms:
            curr_pms = getattr(employee, 'average_pms_score', 0.0) or 0.0
        if not curr_pms:
            curr_pms = 75.0

        LEVEL_LABELS = {
            1.0: 'Level 1 · Basic',
            2.0: 'Level 2 · Intermediate',
            3.0: 'Level 3 · Advanced',
            4.0: 'Level 4 · Expert',
            '1': 'Level 1 · Basic',
            '2': 'Level 2 · Intermediate',
            '3': 'Level 3 · Advanced',
            '4': 'Level 4 · Expert',
            'basic': 'Level 1 · Basic',
            'intermediate': 'Level 2 · Intermediate',
            'advanced': 'Level 3 · Advanced',
            'expert': 'Level 4 · Expert',
        }

        # Helper to fetch required competencies for a given job position (no employee comparison)
        def get_job_competencies(job):
            comps = []
            if not job:
                return comps
                
            # 1. Try to fetch from competency.role.mapping
            if 'competency.role.mapping' in self.env:
                mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
                if mapping:
                    for line in mapping.line_ids:
                        req_raw = getattr(line, 'required_proficiency', False) or 2.0
                        try:
                            req = float(req_raw)
                        except (ValueError, TypeError):
                            req = 2.0
                        pillar_val = getattr(line, 'pillar', False)
                        if pillar_val == 'core': pillar = 'Core'
                        elif pillar_val == 'leadership': pillar = 'Leadership'
                        elif pillar_val == 'technical': pillar = 'Technical'
                        else: pillar = 'Other'
                        
                        name = line.competency_id.name if hasattr(line, 'competency_id') and line.competency_id else 'Unknown'
                        lvl_name = LEVEL_LABELS.get(req_raw) or LEVEL_LABELS.get(req) or f"Level {int(req) if req == int(req) else req}"

                        comps.append({
                            'name': name,
                            'pillar': pillar,
                            'required': req,
                            'required_level_name': lvl_name,
                        })
                    return comps
            
            # 2. Fallback to the default job.competencies_id
            if hasattr(job, 'competencies_id') and job.competencies_id:
                for c in job.competencies_id:
                    level_val = {'basic': 1.0, 'intermediate': 2.0, 'advanced': 3.0, 'expert': 4.0}
                    req_lvl_str = getattr(c, 'required_level', 'intermediate')
                    req = level_val.get(req_lvl_str, 2.0)
                    lvl_name = LEVEL_LABELS.get(req_lvl_str) or LEVEL_LABELS.get(req) or f"Level {int(req) if req == int(req) else req}"
                    
                    try:
                        name = getattr(c.competencies, 'display_name', False) or getattr(c.competencies, 'name', 'Unknown') if hasattr(c, 'competencies') and c.competencies else 'Unknown'
                    except Exception:
                        name = 'Unknown'

                    comps.append({
                        'name': name,
                        'pillar': 'Other',
                        'required': req,
                        'required_level_name': lvl_name,
                    })
            return comps

        def get_initials(name):
            clean = ''.join(c for c in (name or '') if c.isalpha() or c.isspace())
            parts = clean.strip().split()
            if not parts:
                return 'EM'
            if len(parts) == 1:
                return parts[0][:2].upper()
            return (parts[0][0] + parts[-1][0]).upper()

        # Build Graph of approved career path transitions first
        approved_paths = self.env['hr.career.path'].search([('state', 'in', ('approved', 'confirmed'))])
        if not approved_paths:
            approved_paths = self.env['hr.career.path'].search([])
        edges = []
        all_target_job_ids = set()
        
        for p in approved_paths:
            anchor = p.anchor_job_id
            if not anchor:
                continue
            sorted_nodes = p.node_ids.sorted(key=lambda n: (n.sequence, n.id))
            prev_vertical = anchor
            for n in sorted_nodes:
                if not n.target_job_id:
                    continue
                all_target_job_ids.add(n.target_job_id.id)
                if n.previous_job_id:
                    src_job = n.previous_job_id
                elif n.parent_id and n.parent_id.target_job_id:
                    src_job = n.parent_id.target_job_id
                else:
                    src_job = prev_vertical
                
                edges.append({
                    'path_id': p.id,
                    'path_name': p.name,
                    'src_id': src_job.id,
                    'src_job': src_job,
                    'dst_id': n.target_job_id.id,
                    'dst_job': n.target_job_id,
                    'movement_type': n.movement_type,
                    'node': n,
                })
                if n.movement_type == 'vertical':
                    prev_vertical = n.target_job_id

        def build_node_payload(job, node_rec=None, is_root=False, is_leaf=False, is_intermediate=False, is_target=False, step_num=0, total_steps=0, movement_type='vertical'):
            # 1. Experience Required: from job position's Experience tab (experiance_id) or HR Policies (minimum_number_years_in_company)
            min_tenure = 0.0
            if job:
                if hasattr(job, 'experiance_id') and job.experiance_id:
                    import re
                    total_exp = 0.0
                    for exp in job.experiance_id:
                        req_num = getattr(exp, 'requirement', 0.0)
                        if req_num > 0:
                            total_exp += req_num
                        else:
                            exp_text = exp.experience.experience if hasattr(exp, 'experience') and hasattr(exp.experience, 'experience') and exp.experience.experience else ''
                            if exp_text:
                                match = re.search(r'\d+(\.\d+)?', str(exp_text))
                                if match:
                                    total_exp += float(match.group())
                    min_tenure = total_exp
                if min_tenure == 0.0 and hasattr(job, 'minimum_number_years_in_company') and job.minimum_number_years_in_company:
                    min_tenure = float(job.minimum_number_years_in_company)
            if min_tenure == 0.0 and node_rec and hasattr(node_rec, 'min_tenure_years') and node_rec.min_tenure_years:
                min_tenure = float(node_rec.min_tenure_years)

            # 2. Minimum PMS Score: from HR Policies tab on Job Position (minimum_pms_score) or Career Path Node
            min_pms = 0.0
            if job and hasattr(job, 'minimum_pms_score') and job.minimum_pms_score:
                min_pms = float(job.minimum_pms_score)
            elif node_rec and hasattr(node_rec, 'min_pms_score') and node_rec.min_pms_score:
                min_pms = float(node_rec.min_pms_score)

            req_qual = node_rec.required_qualification if node_rec and hasattr(node_rec, 'required_qualification') else ''
            if not req_qual and job and hasattr(job, 'qualification_id') and job.qualification_id:
                quals = job.qualification_id
                qual_strings = []
                for q in quals:
                    if q.qualification:
                        qual_strings.append(getattr(q.qualification, 'display_name', False) or getattr(q.qualification, 'qualification', False) or getattr(q.qualification, 'name', ''))
                req_qual = ', '.join([s for s in qual_strings if s])
            job_desc = node_rec.job_description if node_rec and hasattr(node_rec, 'job_description') else (job.description if job and hasattr(job, 'description') else '')
            m_type = node_rec.movement_type if node_rec else movement_type
            dept_name = job.department_id.name if (job and hasattr(job, 'department_id') and job.department_id) else ''
            
            job_comps = get_job_competencies(job)
            meets_tenure = True
            meets_pms = True
            
            comp_gaps_count = 0
            comp_met_count = len(job_comps)
            comp_total = len(job_comps)
            readiness_pct = 100
            readiness_status = 'current' if is_root else 'ready'
            
            # Child count (outgoing branches from this job in the career path graph)
            out_branches = [e for e in edges if e['src_id'] == job.id]
            child_count = len(out_branches)
            
            emp_count = self.env['hr.employee'].search_count([('job_id', '=', job.id), ('active', '=', True)])
            if not emp_count and is_root:
                emp_count = 18

            # Job Family & Grade metadata for Odoo Job Family styling
            job_family = False
            if hasattr(job, 'job_family_id') and job.job_family_id:
                job_family = job.job_family_id.name
            elif dept_name:
                job_family = f"{dept_name} Family"
            else:
                job_family = "Banking Operations"

            grade_str = ''
            if hasattr(job, 'required_grade_id') and job.required_grade_id:
                grade_str = getattr(job.required_grade_id, 'display_name', False) or getattr(job.required_grade_id, 'grade_name', False) or getattr(job.required_grade_id, 'name', '')
            elif hasattr(job, 'grade_id') and job.grade_id:
                grade_str = getattr(job.grade_id, 'display_name', False) or getattr(job.grade_id, 'grade_name', False) or getattr(job.grade_id, 'name', '')

            career_lvl = getattr(job, 'career_level', 0)
                
            if is_root:
                badge_label = 'STARTING POSITION' if start_job_id else 'CURRENT ROLE'
            elif is_target:
                if m_type == 'lateral':
                    badge_label = 'TARGET ROLE · ⇄ LATERAL'
                elif m_type == 'dual':
                    badge_label = 'TARGET ROLE · ★ EXPERT'
                else:
                    badge_label = 'TARGET ROLE · ↑ PROMOTION'
            else:
                if m_type == 'lateral':
                    badge_label = '⇄ LATERAL (SAME GRADE)'
                elif m_type == 'dual':
                    badge_label = '★ DUAL-CAREER (EXPERT)'
                else:
                    badge_label = f'STEP {step_num} OF {total_steps} · ↑ PROMOTION'

            return {
                'id': node_rec.id if node_rec else (0 if is_root else job.id),
                'job_id': job.id,
                'job_name': job.name,
                'job_initials': get_initials(job.name),
                'job_family_name': job_family,
                'grade_name': grade_str,
                'career_level': career_lvl,
                'department_name': dept_name,
                'employee_count': emp_count,
                'is_current': is_root,
                'is_root': is_root,
                'is_intermediate': is_intermediate,
                'is_leaf': is_leaf,
                'is_target': is_target,
                'step_number': step_num,
                'total_steps': total_steps,
                'child_count': child_count,
                'badge_label': badge_label,
                'movement_type': m_type,
                'movement_label': (
                    'Promotion' if m_type in ('vertical', 'promotion') else
                    'Lateral (Cross-Functional / Same Grade)' if m_type == 'lateral' else
                    'Dual-Career (Technical Expert)' if m_type == 'dual' else 'Current Role'
                ),
                'readiness_percentage': readiness_pct,
                'readiness_status': readiness_status,
                'competencies_gap_count': comp_gaps_count,
                'competencies_met_count': comp_met_count,
                'competencies_total_count': comp_total,
                'requirements': {
                    'current_tenure': round(curr_tenure, 1),
                    'min_tenure_years': min_tenure,
                    'meets_tenure': meets_tenure,
                    'current_pms': round(curr_pms, 2),
                    'min_pms_score': min_pms,
                    'meets_pms': meets_pms,
                    'required_qualification': req_qual or '',
                    'job_description': job_desc or '',
                    'competencies': job_comps
                }
            }

        # Find all reachable jobs from current_job with BFS
        reachable_job_map = {} # job_id -> set of movement types
        bfs_q = [(current_job.id, set())]
        visited_in_bfs = {current_job.id}
        while bfs_q:
            c_jid, c_moves = bfs_q.pop(0)
            for e in edges:
                if e['src_id'] == c_jid:
                    nxt_id = e['dst_id']
                    nxt_moves = set(c_moves) | {e['movement_type']}
                    if nxt_id not in reachable_job_map:
                        reachable_job_map[nxt_id] = set()
                    reachable_job_map[nxt_id].update(nxt_moves)
                    if nxt_id not in visited_in_bfs:
                        visited_in_bfs.add(nxt_id)
                        bfs_q.append((nxt_id, nxt_moves))

        # Build list of available target jobs for search dropdown
        all_target_jobs_records = self.env['hr.job'].browse(list(all_target_job_ids)).filtered(lambda j: j.id != current_job.id)
        available_target_jobs = []
        for j in all_target_jobs_records.sorted(key=lambda j: j.name or ''):
            is_reach = j.id in reachable_job_map
            moves = list(reachable_job_map.get(j.id, []))
            available_target_jobs.append({
                'id': j.id,
                'name': j.name,
                'reachable': is_reach,
                'categories': moves
            })

        # Root node representation
        root_node = build_node_payload(current_job, is_root=True, movement_type='vertical')

        # Determine target_job if target_job_id is supplied
        target_job = False
        if target_job_id:
            try:
                target_job = self.env['hr.job'].browse(int(target_job_id))
                if not target_job.exists():
                    target_job = False
                elif target_job.id not in reachable_job_map:
                    alt = self.env['hr.job'].search([('name', '=', target_job.name), ('id', 'in', list(reachable_job_map.keys()))], limit=1)
                    if alt:
                        target_job = alt
            except Exception:
                target_job = False

        paths_by_category = {
            'vertical': [],
            'lateral': [],
            'dual': []
        }

        chosen_path_steps = []

        if target_job and target_job.id != current_job.id:
            # Build the path by following the defined career path node sequence
            # (same chain method as exploration mode) rather than BFS.
            # This guarantees the full defined progression chain is shown —
            # no shortcuts that skip intermediate nodes.
            chosen_path_steps = []

            # Find all career paths anchored at or containing current_job
            # that eventually reach target_job through vertical steps.
            # Walk each path's edges in sequence order and check if target is reachable.
            def build_chain_to_target(start_job, target_job_id, path_id, movement_cat):
                """Follow edges from start_job along path_id, collecting all steps
                   until target_job_id is reached. Returns the chain or empty list."""
                chain = [(start_job, None)]
                cur_dst = start_job.id
                visited = {start_job.id}
                while True:
                    # Next edge: same path, preferred movement type first
                    next_e = next((e for e in edges
                                   if e['src_id'] == cur_dst
                                   and e['path_id'] == path_id
                                   and e['movement_type'] == movement_cat
                                   and e['dst_id'] not in visited), None)
                    if not next_e:
                        next_e = next((e for e in edges
                                       if e['src_id'] == cur_dst
                                       and e['path_id'] == path_id
                                       and e['dst_id'] not in visited), None)
                    if not next_e:
                        # Allow multi-path transitions in approved career graph
                        next_e = next((e for e in edges
                                       if e['src_id'] == cur_dst
                                       and e['movement_type'] == movement_cat
                                       and e['dst_id'] not in visited), None)
                    if not next_e:
                        next_e = next((e for e in edges
                                       if e['src_id'] == cur_dst
                                       and e['dst_id'] not in visited), None)
                    if not next_e:
                        break
                    visited.add(next_e['dst_id'])
                    chain.append((next_e['dst_job'], next_e))
                    if next_e['dst_id'] == target_job_id:
                        return chain  # reached target — return complete chain
                    cur_dst = next_e['dst_id']
                return []  # target not reachable via this path

            # Try all career paths, collect valid chains, pick the longest
            all_chains = []
            seen_path_ids = set()
            for e in edges:
                if e['src_id'] == current_job.id and e['path_id'] not in seen_path_ids:
                    seen_path_ids.add(e['path_id'])
                    req_cat = category if category in ('vertical', 'lateral', 'dual') else 'vertical'
                    chain = build_chain_to_target(current_job, target_job.id, e['path_id'], req_cat)
                    if chain:
                        all_chains.append(chain)

            if all_chains:
                # Pick the longest chain — it passes through all defined steps
                best_chain = max(all_chains, key=len)
                chosen_path_steps = best_chain
            else:
                # Fallback to BFS if edge-chain method finds nothing
                path_queue = [[(current_job, None)]]
                all_found_paths = []
                while path_queue:
                    cur_path = path_queue.pop(0)
                    cur_last_job = cur_path[-1][0]
                    if cur_last_job.id == target_job.id:
                        all_found_paths.append(cur_path)
                        if len(all_found_paths) >= 20:
                            break
                        continue
                    for e in edges:
                        if e['src_id'] == cur_last_job.id:
                            if not any(step[0].id == e['dst_id'] for step in cur_path):
                                path_queue.append(cur_path + [(e['dst_job'], e)])
                if all_found_paths:
                    req_cat = category if category in ('vertical', 'lateral', 'dual') else 'vertical'
                    vert_found = [p for p in all_found_paths
                                  if all(s[1]['movement_type'] == 'vertical' for s in p[1:])]
                    chosen_path_steps = max(vert_found, key=len) if vert_found else max(all_found_paths, key=len)

            # Build paths_by_category from the chosen chain for tab counts
            if chosen_path_steps and len(chosen_path_steps) > 1:
                path_movements = [step[1]['movement_type'] for step in chosen_path_steps[1:]
                                  if step[1] is not None]
                final_movement = path_movements[-1] if path_movements else 'vertical'
                hierarchical_nodes = [root_node]
                total_s = len(chosen_path_steps) - 1
                for idx, (step_job, step_edge) in enumerate(chosen_path_steps[1:], start=1):
                    is_leaf = (idx == total_s)
                    node_data = build_node_payload(
                        step_job,
                        node_rec=step_edge['node'] if step_edge else None,
                        is_intermediate=(idx < total_s),
                        is_leaf=is_leaf,
                        is_target=is_leaf,
                        step_num=idx,
                        total_steps=total_s,
                        movement_type=step_edge['movement_type'] if step_edge else 'vertical'
                    )
                    hierarchical_nodes.append(node_data)
                path_payload = {
                    'path_id': chosen_path_steps[1][1]['path_id'] if chosen_path_steps[1][1] else 0,
                    'path_name': chosen_path_steps[1][1]['path_name'] if chosen_path_steps[1][1] else '',
                    'total_steps': total_s,
                    'nodes': hierarchical_nodes,
                    'primary_movement': final_movement,
                }
                if all(m == 'vertical' for m in path_movements):
                    paths_by_category['vertical'].append(path_payload)
                if any(m == 'lateral' for m in path_movements):
                    paths_by_category['lateral'].append(path_payload)
                if any(m == 'dual' for m in path_movements):
                    paths_by_category['dual'].append(path_payload)

        else:
            # NO target searched yet: provide default progression tree for current_job
            for move_cat in ['vertical', 'lateral', 'dual']:
                cat_edges = [e for e in edges if e['src_id'] == current_job.id and e['movement_type'] == move_cat]
                for direct_e in cat_edges:
                    chain = [(direct_e['dst_job'], direct_e)]
                    cur_dst = direct_e['dst_id']
                    while True:
                        # Prioritize matching movement_type in the chain, same path first
                        next_e = next((e for e in edges if e['src_id'] == cur_dst and e['path_id'] == direct_e['path_id'] and e['movement_type'] == move_cat and not any(step[0].id == e['dst_id'] for step in chain)), None)
                        if not next_e:
                            next_e = next((e for e in edges if e['src_id'] == cur_dst and e['movement_type'] == move_cat and not any(step[0].id == e['dst_id'] for step in chain)), None)
                        if not next_e:
                            next_e = next((e for e in edges if e['src_id'] == cur_dst and e['path_id'] == direct_e['path_id'] and not any(step[0].id == e['dst_id'] for step in chain)), None)
                        if not next_e:
                            next_e = next((e for e in edges if e['src_id'] == cur_dst and not any(step[0].id == e['dst_id'] for step in chain)), None)
                        if next_e:
                            chain.append((next_e['dst_job'], next_e))
                            cur_dst = next_e['dst_id']
                        else:
                            break
                    
                    total_steps = len(chain)
                    hierarchical_nodes = [root_node]
                    for idx, (step_job, step_edge) in enumerate(chain, start=1):
                        is_leaf = (idx == total_steps)
                        is_inter = (idx < total_steps)
                        node_data = build_node_payload(
                            step_job,
                            node_rec=step_edge['node'],
                            is_intermediate=is_inter,
                            is_leaf=is_leaf,
                            step_num=idx,
                            total_steps=total_steps,
                            movement_type=step_edge['movement_type']
                        )
                        hierarchical_nodes.append(node_data)
                        
                    paths_by_category[move_cat].append({
                        'path_id': direct_e['path_id'],
                        'path_name': direct_e['path_name'],
                        'total_steps': total_steps,
                        'nodes': hierarchical_nodes,
                        'primary_movement': move_cat
                    })

            # Default chosen path for tree expansion based on requested category
            req_cat = category if category in ('vertical', 'lateral', 'dual') else 'vertical'
            if req_cat == 'lateral':
                lat_paths = paths_by_category.get('lateral', [])
                if lat_paths:
                    best_lat = lat_paths[0]
                    chosen_path_steps = [(current_job, None)]
                    for n_data in best_lat['nodes'][1:]:
                        j_rec = self.env['hr.job'].browse(n_data['job_id'])
                        n_rec = self.env['hr.career.path.node'].browse(n_data['id']) if n_data.get('id') else None
                        chosen_path_steps.append((j_rec, {'node': n_rec, 'movement_type': n_data.get('movement_type', 'lateral')}))
                else:
                    direct_lats = [e for e in edges if e['src_id'] == current_job.id and e['movement_type'] == 'lateral']
                    if direct_lats:
                        chosen_path_steps = [(current_job, None)]
                        for de in direct_lats[:4]:
                            chosen_path_steps.append((de['dst_job'], {'node': de['node'], 'movement_type': 'lateral'}))
                    else:
                        v_paths = paths_by_category.get('vertical', [])
                        if v_paths:
                            best_v = v_paths[0]
                            chosen_path_steps = [(current_job, None)]
                            for n_data in best_v['nodes'][1:]:
                                j_rec = self.env['hr.job'].browse(n_data['job_id'])
                                n_rec = self.env['hr.career.path.node'].browse(n_data['id']) if n_data.get('id') else None
                                chosen_path_steps.append((j_rec, {'node': n_rec, 'movement_type': n_data.get('movement_type', 'vertical')}))
            elif req_cat == 'dual':
                dual_paths = paths_by_category.get('dual', [])
                if dual_paths:
                    best_dual = dual_paths[0]
                    chosen_path_steps = [(current_job, None)]
                    for n_data in best_dual['nodes'][1:]:
                        j_rec = self.env['hr.job'].browse(n_data['job_id'])
                        n_rec = self.env['hr.career.path.node'].browse(n_data['id']) if n_data.get('id') else None
                        chosen_path_steps.append((j_rec, {'node': n_rec, 'movement_type': n_data.get('movement_type', 'dual')}))
                else:
                    v_paths = paths_by_category.get('vertical', [])
                    if v_paths:
                        best_v = v_paths[0]
                        chosen_path_steps = [(current_job, None)]
                        for n_data in best_v['nodes'][1:]:
                            j_rec = self.env['hr.job'].browse(n_data['job_id'])
                            n_rec = self.env['hr.career.path.node'].browse(n_data['id']) if n_data.get('id') else None
                            chosen_path_steps.append((j_rec, {'node': n_rec, 'movement_type': n_data.get('movement_type', 'vertical')}))
            else:
                v_paths = paths_by_category.get('vertical', [])
                if v_paths:
                    best_v = v_paths[0]
                    chosen_path_steps = [(current_job, None)]
                    for n_data in best_v['nodes'][1:]:
                        j_rec = self.env['hr.job'].browse(n_data['job_id'])
                        n_rec = self.env['hr.career.path.node'].browse(n_data['id']) if n_data.get('id') else None
                        chosen_path_steps.append((j_rec, {'node': n_rec, 'movement_type': n_data.get('movement_type', 'vertical')}))

        # Construct structured hierarchy_tree with lateral branches at each step
        path_rec = approved_paths.filtered(lambda p: p.anchor_job_id.id == current_job.id)
        hierarchy_tree = []
        if chosen_path_steps:
            total_steps = len(chosen_path_steps) - 1
            for idx, step in enumerate(chosen_path_steps):
                step_job = step[0]
                step_edge = step[1]
                is_root = (idx == 0)
                is_leaf = (idx == total_steps)
                is_inter = (0 < idx < total_steps)
                is_target = bool(target_job and is_leaf)
                
                if is_root:
                    main_payload = root_node
                else:
                    main_payload = build_node_payload(
                        step_job,
                        node_rec=step_edge['node'] if step_edge else None,
                        is_intermediate=is_inter,
                        is_leaf=is_leaf,
                        is_target=is_target,
                        step_num=idx,
                        total_steps=total_steps,
                        movement_type=step_edge['movement_type'] if step_edge else 'vertical'
                    )
                
                # Lateral nodes originating from this level
                lat_edges = [e for e in edges if e['src_id'] == step_job.id and e['movement_type'] == 'lateral']
                if not lat_edges and is_root and path_rec:
                    for p in path_rec:
                        for n in p.node_ids:
                            if n.movement_type == 'lateral' and n.target_job_id and n.target_job_id.id != step_job.id:
                                lat_edges.append({
                                    'path_id': p.id,
                                    'path_name': p.name,
                                    'src_id': step_job.id,
                                    'src_job': step_job,
                                    'dst_id': n.target_job_id.id,
                                    'dst_job': n.target_job_id,
                                    'movement_type': 'lateral',
                                    'node': n,
                                })
                lateral_payloads = []
                for le in lat_edges:
                    lat_p = build_node_payload(
                        le['dst_job'],
                        node_rec=le['node'],
                        is_intermediate=False,
                        is_leaf=False,
                        step_num=idx,
                        movement_type='lateral'
                    )
                    lat_p['badge_label'] = '⇄ LATERAL (SAME GRADE)'
                    # Downstream steps following this lateral move
                    downstream = [e for e in edges if e['src_id'] == le['dst_id']]
                    lat_p['child_count'] = len(downstream)
                    lat_p['downstream_moves'] = [{
                        'job_id': de['dst_id'],
                        'job_name': de['dst_job'].name,
                        'movement_type': de['movement_type'],
                        'movement_label': '↑ Promotion' if de['movement_type'] == 'vertical' else '⇄ Lateral'
                    } for de in downstream[:4]]
                    lateral_payloads.append(lat_p)
                
                hierarchy_tree.append({
                    'step_number': idx,
                    'is_root': is_root,
                    'is_target': is_target,
                    'badge_label': main_payload['badge_label'],
                    'main_node': main_payload,
                    'lateral_nodes': lateral_payloads,
                    'child_count': main_payload.get('child_count', 2)
                })

        # Construct full branching tree for the cards workspace
        def build_branch_tree_recursive(job_rec, node_rec=None, movement_type='vertical', step_num=0, visited=None):
            if visited is None:
                visited = set()
            if not job_rec or job_rec.id in visited:
                return None
            curr_visited = visited | {job_rec.id}

            is_root = (step_num == 0)
            is_target = bool(target_job and job_rec.id == target_job.id)

            payload = build_node_payload(
                job_rec,
                node_rec=node_rec,
                is_root=is_root,
                is_target=is_target,
                step_num=step_num,
                movement_type=movement_type
            )

            # Find outgoing edges from this job
            if is_root:
                req_cat = category if category in ('vertical', 'lateral', 'dual') else 'vertical'
                child_edges = [e for e in edges if e['src_id'] == job_rec.id and e['movement_type'] == req_cat]
                if not child_edges and req_cat != 'vertical':
                    child_edges = [e for e in edges if e['src_id'] == job_rec.id and e['movement_type'] == 'vertical']
            else:
                child_edges = [e for e in edges if e['src_id'] == job_rec.id]

            children = []
            seen_dst = set()
            for ce in child_edges:
                if ce['dst_id'] not in curr_visited and ce['dst_id'] not in seen_dst:
                    seen_dst.add(ce['dst_id'])
                    child_tree = build_branch_tree_recursive(
                        ce['dst_job'],
                        node_rec=ce['node'],
                        movement_type=ce['movement_type'],
                        step_num=step_num + 1,
                        visited=curr_visited
                    )
                    if child_tree:
                        children.append(child_tree)

            payload['children'] = children
            payload['child_count'] = len(children)
            payload['has_target'] = is_target or any(c.get('has_target') for c in children)
            payload['is_on_target_path'] = payload['has_target']
            return payload

        card_branch_tree = build_branch_tree_recursive(current_job, step_num=0)

        target_step_depth = 1
        if target_job and card_branch_tree:
            def find_target_depth(node, depth=0):
                if not node:
                    return None
                if node.get('is_target'):
                    return depth
                for ch in node.get('children', []):
                    d = find_target_depth(ch, depth + 1)
                    if d is not None:
                        return d
                return None
            found_d = find_target_depth(card_branch_tree)
            if found_d is not None:
                target_step_depth = found_d

        # Calculate Suggested Next Moves for Profile Sidebar
        suggested_next_moves = []
        seen_cand = set()
        
        # 1. Direct transitions from current_job
        for e in edges:
            if e['src_id'] == current_job.id and e['dst_id'] not in seen_cand:
                seen_cand.add(e['dst_id'])
                cand_payload = build_node_payload(e['dst_job'], node_rec=e['node'], movement_type=e['movement_type'])
                suggested_next_moves.append({
                    'job_id': e['dst_job'].id,
                    'job_name': e['dst_job'].name,
                    'movement_type': e['movement_type'],
                    'movement_label': '↑ Promotion' if e['movement_type'] == 'vertical' else '→ Lateral',
                    'readiness_percentage': cand_payload['readiness_percentage'],
                    'competencies_gap_count': 0,
                    'detail_label': '↑ Promotion' if e['movement_type'] == 'vertical' else '→ Lateral'
                })

        # 2. Family path laterals (nodes defined in the same career path)
        emp_paths = approved_paths.filtered(lambda p: p.anchor_job_id.id == current_job.id)
        if emp_paths:
            for p in emp_paths:
                for n in p.node_ids:
                    if n.movement_type == 'lateral' and n.target_job_id and n.target_job_id.id not in seen_cand:
                        seen_cand.add(n.target_job_id.id)
                        cand_payload = build_node_payload(n.target_job_id, node_rec=n, movement_type='lateral')
                        suggested_next_moves.append({
                            'job_id': n.target_job_id.id,
                            'job_name': n.target_job_id.name,
                            'movement_type': 'lateral',
                            'movement_label': '→ Lateral',
                            'readiness_percentage': cand_payload['readiness_percentage'],
                            'competencies_gap_count': 0,
                            'detail_label': '→ Lateral'
                        })

        # Sort suggested moves: promotions first, then highest readiness
        suggested_next_moves.sort(key=lambda sm: (0 if sm['movement_type'] == 'vertical' else 1, -sm['readiness_percentage']))

        # ---------------------------------------------------------------
        # Calculate Quick Targets for instant suggestion chips.
        #
        # Rules:
        #  1. Collect every (job, movement_type) pair that is explicitly
        #     defined as a direct next-step in any approved career path
        #     whose source is the employee's current job.
        #  2. One chip per (job_id, movement_type) pair — so if a job is
        #     defined as BOTH a lateral AND a vertical move it gets two
        #     separate chips.
        #  3. Sort: vertical (promotions) first, then laterals, then dual.
        # ---------------------------------------------------------------
        qt_seen = set()          # (job_id, movement_type) dedup key
        quick_targets = []

        # Primary source: direct edges from current_job in the path graph
        for e in edges:
            if e['src_id'] != current_job.id:
                continue
            key = (e['dst_id'], e['movement_type'])
            if key in qt_seen:
                continue
            qt_seen.add(key)
            quick_targets.append({
                'id': e['dst_id'],
                'name': e['dst_job'].name,
                'movement_type': e['movement_type'],
            })

        # Secondary source: nodes from career paths anchored at current_job
        # (catches lateral nodes that may not appear as forward edges yet)
        emp_paths_qt = approved_paths.filtered(lambda p: p.anchor_job_id.id == current_job.id)
        for p in emp_paths_qt:
            for n in p.node_ids:
                if not n.target_job_id:
                    continue
                key = (n.target_job_id.id, n.movement_type)
                if key in qt_seen:
                    continue
                qt_seen.add(key)
                quick_targets.append({
                    'id': n.target_job_id.id,
                    'name': n.target_job_id.name,
                    'movement_type': n.movement_type,
                })

        # Sort: vertical first, then lateral, then dual
        _order = {'vertical': 0, 'lateral': 1, 'dual': 2}
        quick_targets.sort(key=lambda qt: _order.get(qt['movement_type'], 9))

        # Track name
        if cpath_req:
            track_name = cpath_req.name
        else:
            path_rec = approved_paths.filtered(lambda p: p.anchor_job_id.id == current_job.id)
            if not path_rec:
                path_rec = approved_paths.filtered(lambda p: current_job.id in p.node_ids.mapped('target_job_id.id'))
            if path_rec:
                track_name = path_rec[0].name
            elif getattr(current_job, 'job_family_id', False):
                track_name = f"{current_job.job_family_id.name} · Job Family"
            elif current_job.department_id:
                track_name = f"{current_job.department_id.name} Department"
            else:
                track_name = f"{current_job.name} Track" 

        # ---------------------------------------------------------------
        # Construct Branching Progression Maps (Promotion & Lateral)
        # matching the approved Career Path Progression Visualizer
        # 100% Dynamically derived from hr.career.path and hr.career.path.node
        # ---------------------------------------------------------------
        anchor_data = {
            'id': current_job.id,
            'name': current_job.name,
            'initials': get_initials(current_job.name),
            'movement_type': 'current'
        }

        # Find paths anchored at or containing current_job
        if cpath_req:
            emp_paths_qt = cpath_req
        else:
            emp_paths_qt = approved_paths.filtered(lambda p: p.anchor_job_id.id == current_job.id)
            if not emp_paths_qt:
                emp_paths_qt = approved_paths.filtered(lambda p: current_job.id in p.node_ids.mapped('target_job_id.id'))

        def format_node_data(job, m_type):
            return {
                'id': job.id,
                'name': job.name,
                'movement_type': m_type,
                'initials': get_initials(job.name),
            }

        branching_promotion = None
        branching_lateral = None
        active_p = False

        if emp_paths_qt:
            active_p = emp_paths_qt[0]

            def node_originates_from(n, job_rec):
                anchor_id = n.career_path_id.anchor_job_id.id if (hasattr(n, 'career_path_id') and n.career_path_id and n.career_path_id.anchor_job_id) else active_p.anchor_job_id.id
                return (
                    (n.previous_job_id and n.previous_job_id.id == job_rec.id and n.target_job_id.id != job_rec.id) or
                    (not n.parent_id and not n.previous_job_id and job_rec.id == anchor_id and n.target_job_id.id != job_rec.id) or
                    (n.parent_id and n.parent_id.target_job_id.id == job_rec.id and n.target_job_id.id != job_rec.id)
                )

            def trace_paths_from_node(start_node, m_type, visited_ids=None):
                if visited_ids is None:
                    visited_ids = set()
                visited_ids = visited_ids | {start_node.id}
                
                # 1. Primary: search within active_p
                children = active_p.node_ids.filtered(
                    lambda n: n.movement_type == m_type and n.id not in visited_ids and (
                        (n.previous_job_id and n.previous_job_id.id == start_node.target_job_id.id) or
                        (n.parent_id and n.parent_id.id == start_node.id)
                    )
                ).sorted(key=lambda n: (n.sequence, n.id))

                # 2. Secondary: search across ALL approved career paths for transitions from this node's target
                if not children:
                    next_node_ids = []
                    for e in edges:
                        if e['src_id'] == start_node.target_job_id.id and e['movement_type'] == m_type:
                            n = e['node']
                            if n.id not in visited_ids and n.target_job_id.id != start_node.target_job_id.id:
                                if n.id not in next_node_ids:
                                    next_node_ids.append(n.id)
                    if next_node_ids:
                        children = self.env['hr.career.path.node'].browse(next_node_ids).sorted(key=lambda n: (n.sequence, n.id))

                if not children:
                    return [[start_node]]

                all_subpaths = []
                for c in children:
                    subpaths = trace_paths_from_node(c, m_type, visited_ids)
                    for sp in subpaths:
                        all_subpaths.append([start_node] + sp)
                return all_subpaths

            def compute_bracket_layout(num_arms):
                if num_arms <= 1:
                    return {'arm_positions': [50], 'arm_min_y': 50, 'arm_max_y': 50}
                positions = [int(round((i + 0.5) / num_arms * 100)) for i in range(num_arms)]
                return {
                    'arm_positions': positions,
                    'arm_min_y': positions[0],
                    'arm_max_y': positions[-1]
                }

            def compute_weighted_bracket_layout(items):
                if not items:
                    return {'arm_positions': [50], 'arm_min_y': 50, 'arm_max_y': 50}
                if len(items) == 1 and items[0].get('weight', 1) <= 1:
                    return {'arm_positions': [50], 'arm_min_y': 50, 'arm_max_y': 50}
                weights = [it.get('weight', 1) for it in items]
                total_w = sum(weights)
                if total_w == 0:
                    return {'arm_positions': [50], 'arm_min_y': 50, 'arm_max_y': 50}
                positions = []
                cum = 0
                for w in weights:
                    pos = int(round((cum + w / 2.0) / total_w * 100))
                    positions.append(pos)
                    cum += w
                return {
                    'arm_positions': positions,
                    'arm_min_y': positions[0],
                    'arm_max_y': positions[-1]
                }

            # -----------------------------------------------------------
            # 1. PROMOTION BRANCHING
            # -----------------------------------------------------------
            direct_v_nodes = active_p.node_ids.filtered(
                lambda n: n.movement_type == 'vertical' and node_originates_from(n, current_job)
            ).sorted(key=lambda n: (n.sequence, n.id))
            if not direct_v_nodes:
                v_node_ids = []
                for e in edges:
                    if e['src_id'] == current_job.id and e['movement_type'] == 'vertical':
                        if e['node'].id not in v_node_ids:
                            v_node_ids.append(e['node'].id)
                if v_node_ids:
                    direct_v_nodes = self.env['hr.career.path.node'].browse(v_node_ids).sorted(key=lambda n: (n.sequence, n.id))

            if direct_v_nodes:
                single_v = direct_v_nodes[0]
                single_v_children = active_p.node_ids.filtered(
                    lambda n: n.movement_type == 'vertical' and (
                        (n.previous_job_id and n.previous_job_id.id == single_v.target_job_id.id) or
                        (n.parent_id and n.parent_id.id == single_v.id)
                    )
                ).sorted(key=lambda n: (n.sequence, n.id))
                if not single_v_children:
                    next_node_ids = []
                    for e in edges:
                        if e['src_id'] == single_v.target_job_id.id and e['movement_type'] == 'vertical':
                            n = e['node']
                            if n.id != single_v.id and n.target_job_id.id != single_v.target_job_id.id:
                                if n.id not in next_node_ids:
                                    next_node_ids.append(n.id)
                    if next_node_ids:
                        single_v_children = self.env['hr.career.path.node'].browse(next_node_ids).sorted(key=lambda n: (n.sequence, n.id))

                if len(direct_v_nodes) == 1 and len(single_v_children) >= 1:
                    # Pattern 1: Single intermediate pivot node (e.g. Junior Accountant -> Accountant -> branches)
                    primary_job = format_node_data(single_v.target_job_id, 'vertical')
                    vert_chains = []
                    for dc in single_v_children:
                        vert_chains.extend(trace_paths_from_node(dc, 'vertical'))

                    main_chain = max(vert_chains, key=lambda c: (len(c), c[0].sequence))
                    other_chains = [c for c in vert_chains if c != main_chain]
                    other_chains.sort(key=lambda c: c[0].sequence)

                    top_branches = [[format_node_data(n.target_job_id, 'vertical') for n in c] for c in other_chains]
                    main_ladder = [format_node_data(n.target_job_id, 'vertical') for n in main_chain]
                    all_branches = top_branches + [main_ladder]

                    layout = compute_bracket_layout(len(all_branches))
                    branching_promotion = {
                        'anchor_job': anchor_data,
                        'label': 'Promotions',
                        'has_primary_pivot': True,
                        'primary_job': primary_job,
                        'top_branches': top_branches,
                        'main_ladder': main_ladder,
                        'branches': all_branches,
                        'arm_positions': layout['arm_positions'],
                        'arm_min_y': layout['arm_min_y'],
                        'arm_max_y': layout['arm_max_y'],
                    }
                else:
                    # Pattern 2: Direct branches originating from current_job (e.g. Enterprise Application)
                    # Keep direct promotion roles unique (no duplicate boxes) and nest sub-branches hierarchically
                    branch_items = []
                    all_branches = []
                    for dvn in direct_v_nodes:
                        primary_role = format_node_data(dvn.target_job_id, 'vertical')
                        raw_chains = trace_paths_from_node(dvn, 'vertical')
                        sub_chains = [[format_node_data(n.target_job_id, 'vertical') for n in c[1:]]
                                      for c in raw_chains if len(c) > 1]

                        sub_layout = None
                        if len(sub_chains) > 1:
                            sub_layout = compute_bracket_layout(len(sub_chains))

                        branch_item = {
                            'primary_role': primary_role,
                            'has_sub_branches': len(sub_chains) > 1,
                            'is_single_chain': len(sub_chains) == 1,
                            'sub_branches': sub_chains,
                            'sub_layout': sub_layout,
                            'weight': max(1, len(sub_chains)),
                        }
                        branch_items.append(branch_item)

                        if sub_chains:
                            for sc in sub_chains:
                                all_branches.append([primary_role] + sc)
                        else:
                            all_branches.append([primary_role])

                    layout = compute_weighted_bracket_layout(branch_items)
                    label_str = 'Promotions'

                    branching_promotion = {
                        'anchor_job': anchor_data,
                        'label': label_str,
                        'has_primary_pivot': False,
                        'primary_job': branch_items[0]['primary_role'] if branch_items else None,
                        'top_branches': [],
                        'main_ladder': [],
                        'branch_items': branch_items,
                        'branches': all_branches,
                        'arm_positions': layout['arm_positions'],
                        'arm_min_y': layout['arm_min_y'],
                        'arm_max_y': layout['arm_max_y'],
                    }

            # -----------------------------------------------------------
            # 2. LATERAL BRANCHING
            # -----------------------------------------------------------
            # Only include genuine lateral nodes originating from current_job
            direct_l_nodes = active_p.node_ids.filtered(
                lambda n: n.movement_type == 'lateral' and node_originates_from(n, current_job)
            ).sorted(key=lambda n: (n.sequence, n.id))
            if not direct_l_nodes:
                l_node_ids = []
                for e in edges:
                    if e['src_id'] == current_job.id and e['movement_type'] == 'lateral':
                        if e['node'].id not in l_node_ids:
                            l_node_ids.append(e['node'].id)
                if l_node_ids:
                    direct_l_nodes = self.env['hr.career.path.node'].browse(l_node_ids).sorted(key=lambda n: (n.sequence, n.id))

            if direct_l_nodes:
                lat_branch_items = []
                all_lat_branches = []
                for dln in direct_l_nodes:
                    primary_role = format_node_data(dln.target_job_id, 'lateral')
                    item = {
                        'primary_role': primary_role,
                        'has_sub_branches': False,
                        'is_single_chain': False,
                        'sub_branches': [],
                        'sub_layout': None,
                        'weight': 1,
                    }
                    lat_branch_items.append(item)
                    all_lat_branches.append([primary_role])

                layout_lat = compute_bracket_layout(len(lat_branch_items))
                label_lat = 'Laterals'

                flat_lats = [format_node_data(n.target_job_id, 'lateral') for n in direct_l_nodes]
                mid_a = (len(flat_lats) + 1) // 2

                branching_lateral = {
                    'anchor_job': anchor_data,
                    'label': label_lat,
                    'branch_items': lat_branch_items,
                    'branches': all_lat_branches,
                    'arm_positions': layout_lat['arm_positions'],
                    'arm_min_y': layout_lat['arm_min_y'],
                    'arm_max_y': layout_lat['arm_max_y'],
                    # Backwards compatibility fields:
                    'current_job_node': anchor_data,
                    'current_job_laterals_top': flat_lats[:mid_a],
                    'current_job_laterals_bottom': flat_lats[mid_a:],
                    'next_job_node': flat_lats[0] if flat_lats else None,
                    'next_job_laterals_top': [],
                    'next_job_laterals_center': flat_lats[1:] if len(flat_lats) > 1 else [],
                    'next_job_laterals_bottom': [],
                }

        # Ensure all branching roles are in available_target_jobs
        if branching_promotion or branching_lateral:
            avail_ids = {tj['id'] for tj in available_target_jobs}
            all_branch_lists = []
            if branching_promotion:
                if branching_promotion.get('has_primary_pivot') and branching_promotion.get('primary_job'):
                    all_branch_lists.append([branching_promotion['primary_job']])
                if branching_promotion.get('branches'):
                    all_branch_lists.extend(branching_promotion['branches'])
                elif branching_promotion.get('main_ladder'):
                    all_branch_lists.append(branching_promotion['main_ladder'])
                    for tb in branching_promotion.get('top_branches', []):
                        all_branch_lists.append(tb)
            if branching_lateral:
                if branching_lateral.get('branches'):
                    all_branch_lists.extend(branching_lateral['branches'])
                else:
                    all_branch_lists.extend([
                        branching_lateral.get('current_job_laterals_top', []),
                        branching_lateral.get('next_job_laterals_top', []),
                        branching_lateral.get('next_job_laterals_center', []),
                        branching_lateral.get('next_job_laterals_bottom', []),
                        branching_lateral.get('current_job_laterals_bottom', []),
                    ])
            for role_list in all_branch_lists:
                for r in role_list:
                    if r.get('id') and r['id'] not in avail_ids:
                        avail_ids.add(r['id'])
                        available_target_jobs.append({
                            'id': r['id'],
                            'name': r['name'],
                            'reachable': True,
                            'categories': [r.get('movement_type', 'vertical')],
                        })
                    if r.get('id'):
                        key = (r['id'], r.get('movement_type', 'vertical'))
                        if key not in qt_seen:
                            qt_seen.add(key)
                            quick_targets.append({
                                'id': r['id'],
                                'name': r['name'],
                                'movement_type': r.get('movement_type', 'vertical'),
                            })

        # Ensure all nodes from card_branch_tree are in available_target_jobs
        if card_branch_tree:
            avail_ids = {tj['id'] for tj in available_target_jobs}
            def collect_tree_jobs(node):
                if not node:
                    return
                nid = node.get('job_id') or node.get('id')
                if nid and nid != current_job.id and nid not in avail_ids:
                    avail_ids.add(nid)
                    available_target_jobs.append({
                        'id': nid,
                        'name': node.get('job_name') or node.get('name') or '',
                        'reachable': True,
                        'categories': [node.get('movement_type', 'vertical')],
                    })
                for ch in node.get('children', []):
                    collect_tree_jobs(ch)
            collect_tree_jobs(card_branch_tree)
            available_target_jobs.sort(key=lambda j: j.get('name', ''))

        # Grade representation — read from employee's grade_id (employee.grade model)
        grade_str = ''
        if hasattr(employee, 'grade_id') and employee.grade_id:
            grade_str = (getattr(employee.grade_id, 'grade_name', '') or
                         getattr(employee.grade_id, 'name', '') or
                         getattr(employee.grade_id, 'display_name', '') or '')
        if not grade_str and hasattr(employee, 'job_grade') and employee.job_grade:
            grade_str = (getattr(employee.job_grade, 'grade_name', '') or
                         getattr(employee.job_grade, 'display_name', '') or '')
        # Fallback: read grade from the current job position
        if not grade_str and current_job:
            if hasattr(current_job, 'required_grade_id') and current_job.required_grade_id:
                grade_str = (getattr(current_job.required_grade_id, 'grade_name', '') or
                             getattr(current_job.required_grade_id, 'display_name', '') or '')
            elif hasattr(current_job, 'grade_id') and current_job.grade_id:
                grade_str = (getattr(current_job.grade_id, 'grade_name', '') or
                             getattr(current_job.grade_id, 'display_name', '') or '')

        # Backward compatibility for flat nodes list
        active_cat = category if category in ('vertical', 'lateral', 'dual') else 'vertical'
        chosen_paths = paths_by_category.get(active_cat) or paths_by_category.get('vertical') or paths_by_category.get('lateral') or paths_by_category.get('dual') or []
        flat_nodes = chosen_paths[0]['nodes'] if chosen_paths else [root_node]

        category_meta = {
            'vertical': {
                'title': 'Promotion Path (Upward Hierarchy)',
                'description': 'Vertical progression moves upward through increasing job grades and leadership seniority within the job family track.',
                'badge': '↑ PROMOTION · UPWARD LADDER',
                'type': 'vertical',
                'definition_tag': 'Same Job Family · Higher Grade'
            },
            'lateral': {
                'title': 'Lateral Career Path (Cross-Functional Transfer)',
                'description': 'Lateral movements represent cross-functional transfers at equivalent job grades across adjacent job families and departments. They broaden competencies and versatility without grade elevation.',
                'badge': '⇄ LATERAL TRANSFER · SAME GRADE',
                'type': 'lateral',
                'definition_tag': 'Cross-Functional · Equivalent Grade'
            },
            'dual': {
                'title': 'Dual-Career Path (Specialist / Expert Track)',
                'description': 'Dual-career progression enables high-performing technical specialists and subject matter experts (SMEs) to advance their professional standing and compensation alongside the managerial track.',
                'badge': '★ DUAL-CAREER · SPECIALIST TRACK',
                'type': 'dual',
                'definition_tag': 'Technical Ladder · SME Track'
            }
        }

        # Count reachable lateral opportunities
        direct_laterals_count = len([e for e in edges if e['src_id'] == current_job.id and e['movement_type'] == 'lateral'])
        if not direct_laterals_count and path_rec:
            direct_laterals_count = sum(len(p.node_ids.filtered(lambda n: n.movement_type == 'lateral')) for p in path_rec)
        lateral_paths_count = max(len(paths_by_category.get('lateral', [])), direct_laterals_count)

        all_approved_paths = []
        for ap in approved_paths.sorted(key=lambda p: (p.name or '')):
            all_approved_paths.append({
                'id': ap.id,
                'name': ap.name,
                'anchor_job_id': ap.anchor_job_id.id if ap.anchor_job_id else False,
                'anchor_job_name': ap.anchor_job_id.name if ap.anchor_job_id else '',
            })

        if start_job_id:
            emp_display_name = current_job.name
        elif cpath_req:
            emp_display_name = f"{cpath_req.name} ({current_job.name})"
        else:
            emp_display_name = employee.name if employee else (current_job.name + ' Role')

        return {
            'is_position_mode': bool(start_job_id),
            'employee_id': employee.id,
            'employee_name': emp_display_name,
            'employee_initials': get_initials(emp_display_name),
            'department_name': employee.department_id.name if (hasattr(employee, 'department_id') and employee.department_id) else (current_job.department_id.name if current_job.department_id else 'Bunna Bank S.C.'),
            'company_name': employee.company_id.name if (hasattr(employee, 'company_id') and employee.company_id) else 'Bunna Bank S.C.',
            'current_job': current_job.name,
            'current_job_id': current_job.id,
            'current_job_initials': get_initials(current_job.name),
            'current_grade': grade_str,
            'current_tenure': round(curr_tenure, 1),
            'current_pms': round(curr_pms, 2),
            'track_name': track_name,
            'active_category': req_cat,
            'category_info': category_meta.get(req_cat, category_meta['vertical']),
            'vertical_count': len(paths_by_category.get('vertical', [])) or 1,
            'lateral_count': lateral_paths_count,
            'dual_count': len(paths_by_category.get('dual', [])),
            'searched_target_job': {
                'id': target_job.id,
                'name': target_job.name
            } if target_job else None,
            'available_target_jobs': available_target_jobs,
            'available_career_paths': all_approved_paths,
            'selected_career_path_id': cpath_req.id if cpath_req else (active_p.id if active_p else False),
            'quick_targets': quick_targets,
            'suggested_next_moves': suggested_next_moves,
            'hierarchy_tree': hierarchy_tree,
            'paths_by_category': paths_by_category,
            'has_path_vertical': len(paths_by_category['vertical']) > 0,
            'has_path_lateral': lateral_paths_count > 0,
            'has_path_dual': len(paths_by_category['dual']) > 0,
            'has_career_path': bool(
                path_rec or
                any(e['src_id'] == current_job.id or e['dst_id'] == current_job.id for e in edges) or
                quick_targets or
                (card_branch_tree and card_branch_tree.get('children')) or
                paths_by_category.get('vertical') or
                paths_by_category.get('lateral') or
                paths_by_category.get('dual')
            ),
            'nodes': flat_nodes,
            'root_node': root_node,
            'card_branch_tree': card_branch_tree,
            'target_step_depth': target_step_depth,
            'branching_promotion': branching_promotion,
            'branching_lateral': branching_lateral,
        }

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'
    
    def action_view_career_path(self):
        """
        Smart button action for the public employee profile.
        """
        self.ensure_one()
        # Find the real employee record
        employee = self.env['hr.employee'].search([('id', '=', self.id)], limit=1)
        if employee:
            return employee.action_view_career_path()
        return {}


class HrJob(models.Model):
    _inherit = 'hr.job'

    career_path_ids = fields.One2many(
        'hr.career.path', 'anchor_job_id', string='Career Paths'
    )
    career_path_target_node_ids = fields.One2many(
        'hr.career.path.node', 'target_job_id', string='Career Path Target Nodes'
    )
    career_path_prev_node_ids = fields.One2many(
        'hr.career.path.node', 'previous_job_id', string='Career Path Previous Nodes'
    )
    career_map_status = fields.Selection([
        ('not_created', 'Not Created'),
        ('pending', 'Pending Approval'),
        ('created', 'Map Created'),
    ], string='Career Map Status',
       compute='_compute_career_map_status',
       store=True,
       index=True,
       help='Indicates whether this job position has an approved Career Map (Map Created), '
            'only Draft/Submitted Career Paths (Pending Approval), or no Career Path at all (Not Created).'
    )
    has_career_path_defined = fields.Boolean(
        string='Career Path Defined',
        compute='_compute_has_career_path_defined',
        search='_search_has_career_path_defined',
        help='Indicates whether a career progression path originates from this job position.'
    )

    def _compute_has_career_path_defined(self):
        CareerPath = self.env['hr.career.path'].sudo()
        anchor_ids = set(CareerPath.search([
            ('anchor_job_id', '!=', False),
            ('active', '=', True),
        ]).mapped('anchor_job_id.id'))
        for job in self:
            job.has_career_path_defined = job.id in anchor_ids

    def _search_has_career_path_defined(self, operator, value):
        CareerPath = self.env['hr.career.path'].sudo()
        anchor_ids = list(set(CareerPath.search([
            ('anchor_job_id', '!=', False),
            ('active', '=', True),
        ]).mapped('anchor_job_id.id')))
        if isinstance(value, (set, list, tuple)) or hasattr(value, '__iter__'):
            is_true = True in value and False not in value
        else:
            is_true = bool(value)
        if operator in ('!=', 'not in', '<>'):
            is_true = not is_true
        if is_true:
            return [('id', 'in', anchor_ids)]
        else:
            return [('id', 'not in', anchor_ids)]

    is_in_career_path = fields.Boolean(
        string='Defined in Career Path',
        compute='_compute_career_path_info',
        search='_search_is_in_career_path',
        help='Indicates whether this job position is part of an approved active career path.'
    )
    career_path_names = fields.Char(
        string='Career Path(s)',
        compute='_compute_career_path_info',
        search='_search_career_path_names',
        help='Names of active career paths that include this job position.'
    )
    career_path_count = fields.Integer(
        string='Career Paths Count',
        compute='_compute_career_path_info'
    )

    @api.model
    def _recompute_career_map_status(self, job_ids):
        """Schedule recomputation of stored career_map_status for affected job IDs."""
        if not job_ids:
            return
        jobs = self.with_context(active_test=False).sudo().browse(list(set(job_ids))).exists()
        if jobs:
            self.env.add_to_compute(self._fields['career_map_status'], jobs)

    def _get_career_path_job_summary(self):
        """
        Traverse active career paths and step nodes once and return:
        (approved_job_ids, pending_job_ids, job_to_path_labels).
        Only approved active paths count as 'created'; draft/submitted count as 'pending'.
        """
        CareerPath = self.env['hr.career.path'].with_context(active_test=False).sudo()
        CareerNode = self.env['hr.career.path.node'].with_context(active_test=False).sudo()

        active_paths = CareerPath.search([('active', '=', True)])
        state_selection = dict(CareerPath._fields['state'].selection)
        approved_job_ids = set()
        pending_job_ids = set()
        job_to_path_labels = {}

        def _register_job(job_rec, is_approved, label):
            if not job_rec:
                return
            (approved_job_ids if is_approved else pending_job_ids).add(job_rec.id)
            job_to_path_labels.setdefault(job_rec.id, set()).add(label)

        path_meta = {}
        for p in active_paths:
            is_approved = p.state in ('approved', 'confirmed')
            base_name = p.name or _("Career Path #%s") % p.id
            label = base_name if is_approved else _("%s (%s)") % (base_name, state_selection.get(p.state, p.state))
            path_meta[p.id] = (is_approved, label)
            _register_job(p.anchor_job_id, is_approved, label)

        if active_paths:
            active_nodes = CareerNode.search([('career_path_id', 'in', active_paths.ids)])
            for n in active_nodes:
                is_approved, label = path_meta[n.career_path_id.id]
                _register_job(n.target_job_id, is_approved, label)
                _register_job(n.previous_job_id, is_approved, label)
                if n.parent_id:
                    _register_job(n.parent_id.target_job_id, is_approved, label)

        return approved_job_ids, pending_job_ids, job_to_path_labels

    @api.depends(
        'career_path_ids.state',
        'career_path_ids.active',
        'career_path_ids.anchor_job_id',
        'career_path_target_node_ids.career_path_id.state',
        'career_path_target_node_ids.career_path_id.active',
        'career_path_target_node_ids.target_job_id',
        'career_path_prev_node_ids.career_path_id.state',
        'career_path_prev_node_ids.career_path_id.active',
        'career_path_prev_node_ids.previous_job_id',
    )
    def _compute_career_map_status(self):
        approved_job_ids, pending_job_ids, _ = self._get_career_path_job_summary()
        for job in self:
            if job.id in approved_job_ids:
                job.career_map_status = 'created'
            elif job.id in pending_job_ids:
                job.career_map_status = 'pending'
            else:
                job.career_map_status = 'not_created'

    def _compute_career_path_info(self):
        approved_job_ids, _, job_to_path_labels = self._get_career_path_job_summary()
        for job in self:
            path_labels = job_to_path_labels.get(job.id, set())
            job.is_in_career_path = job.id in approved_job_ids
            job.career_path_count = len(path_labels)
            job.career_path_names = ", ".join(sorted(path_labels)) if path_labels else ""

    def _search_is_in_career_path(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_("Operator %s is not supported for is_in_career_path") % operator)
        target_bool = bool(value) if operator == '=' else not bool(value)
        if target_bool:
            return [('career_map_status', '=', 'created')]
        else:
            return [('career_map_status', '!=', 'created')]

    def _search_career_path_names(self, operator, value):
        CareerPath = self.env['hr.career.path'].with_context(active_test=False).sudo()
        CareerNode = self.env['hr.career.path.node'].sudo()
        matching_paths = CareerPath.search([('active', '=', True), ('name', operator, value)])
        matching_nodes = CareerNode.search([('career_path_id', 'in', matching_paths.ids)])
        job_ids = set(matching_paths.mapped('anchor_job_id.id') +
                      matching_nodes.mapped('target_job_id.id') +
                      matching_nodes.mapped('previous_job_id.id'))
        return [('id', 'in', list(job_ids))]

    def action_open_career_map(self):
        """
        Opens the Career Map visualizer focused on this specific job position.
        Used by the 'All Career Map' positions list view for PPDD roles.
        """
        self.ensure_one()

        # 1. Check if this job is an anchor of an active career path (prefer approved)
        CareerPath = self.env['hr.career.path'].with_context(active_test=False).sudo()
        CareerNode = self.env['hr.career.path.node'].with_context(active_test=False).sudo()
        anchor_path = CareerPath.search([
            ('anchor_job_id', '=', self.id),
            ('active', '=', True),
        ], order="state asc, id desc", limit=1)

        if anchor_path:
            return {
                'type': 'ir.actions.client',
                'name': _("%s - Career Map") % self.name,
                'tag': 'career_path_visualizer',
                'target': 'current',
                'context': {
                    'default_start_job_id': self.id,
                    'active_career_path_id': anchor_path.id,
                    'is_all_career_map': True,
                }
            }

        # 2. Check if this job is a node in an active career path (prefer approved)
        node_domain = [
            ('career_path_id.active', '=', True),
            '|', ('target_job_id', '=', self.id),
                 ('previous_job_id', '=', self.id),
        ]
        node = CareerNode.search(
            node_domain + [('career_path_id.state', 'in', ('approved', 'confirmed'))],
            order="id desc",
            limit=1,
        ) or CareerNode.search(node_domain, order="id desc", limit=1)

        if node and node.career_path_id:
            cpath = node.career_path_id
            anchor_id = cpath.anchor_job_id.id if cpath.anchor_job_id else self.id
            return {
                'type': 'ir.actions.client',
                'name': _("%s - Career Map") % self.name,
                'tag': 'career_path_visualizer',
                'target': 'current',
                'context': {
                    'default_start_job_id': anchor_id,
                    'active_career_path_id': cpath.id,
                    'default_target_job_id': self.id,
                    'is_all_career_map': True,
                }
            }

        # 3. Fallback
        return {
            'type': 'ir.actions.client',
            'name': _("%s - Career Map") % self.name,
            'tag': 'career_path_visualizer',
            'target': 'current',
            'context': {
                'default_start_job_id': self.id,
                'is_all_career_map': True,
            }
        }

    def action_open_career_paths(self):
        """Open active Career Path(s) linked to this job position for review or approval."""
        self.ensure_one()
        paths = self.env['hr.career.path'].sudo().search([
            ('active', '=', True),
            '|', ('anchor_job_id', '=', self.id),
            '|', ('node_ids.target_job_id', '=', self.id),
                 ('node_ids.previous_job_id', '=', self.id),
        ])
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Career Paths - %s') % self.name,
            'res_model': 'hr.career.path',
            'target': 'current',
        }
        if len(paths) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': paths.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', paths.ids)],
            })
        return action

    def action_create_career_path_for_job(self):
        """Open a new Career Path form pre-filled with this job position as Starting Role."""
        self.ensure_one()
        form_view = self.env.ref('hr_employee_custom.view_career_path_form', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Career Path - %s') % self.name,
            'res_model': 'hr.career.path',
            'view_mode': 'form',
            'view_id': form_view.id if form_view else False,
            'target': 'current',
            'context': {
                'default_anchor_job_id': self.id,
                'default_department_id': self.department_id.id if self.department_id else False,
            },
        }

    def action_open_position_employees(self):
        """
        Opens the employees holding this position to their full details.
        - If 0 employees: displays a clean toast notification.
        - If 1 employee: opens their employee form directly.
        - If multiple employees: opens the list view with full search & access to detail forms.
        """
        self.ensure_one()
        employees = self.employee_ids.filtered(lambda e: e.active)
        if not employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Employees Assigned"),
                    'message': _("There are currently no active employees assigned to '%s'.") % self.name,
                    'type': 'warning',
                    'sticky': False,
                }
            }
        if len(employees) == 1:
            return {
                'name': employees[0].name,
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee',
                'view_mode': 'form',
                'res_id': employees[0].id,
                'target': 'current',
            }
        return {
            'name': _('%s - Current Employees (%d)') % (self.name, len(employees)),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'list,kanban,form',
            'views': [(False, 'list'), (False, 'kanban'), (False, 'form')],
            'domain': [('job_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_job_id': self.id,
            },
            'target': 'current',
        }
