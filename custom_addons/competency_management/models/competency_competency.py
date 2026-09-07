# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyRatingModel(models.Model):
    """Evaluation scale attachable to competencies ."""
    _name = 'competency.rating.model'
    _description = 'Competency Rating Model'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    max_rating = fields.Integer(
        string='Maximum Rating', default=4,
        help='Highest proficiency/rating value in this scale.')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Rating Model code must be unique!'),
    ]


class CompetencyLevelChangeLog(models.Model):
    """Audit log for definition changes on competency proficiency levels (FR-COM-006)."""
    _name = 'competency.level.change.log'
    _description = 'Competency Level Definition Change Log'
    _order = 'effective_date desc, id desc'

    level_id = fields.Many2one(
        'competency.proficiency.level', string='Proficiency Level', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    old_definition = fields.Text(string='Previous Definition')
    new_definition = fields.Text(string='New Definition')
    change_description = fields.Text(string='Change Description', required=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, required=True)
    user_id = fields.Many2one(
        'res.users', string='User Responsible', default=lambda self: self.env.user, required=True, readonly=True)


class CompetencyProficiencyLevel(models.Model):
    """One proficiency level (Basic..Expert) with mandatory behavioral indicators (FR-COM-003, FR-COM-004, FR-COM-005)."""
    _name = 'competency.proficiency.level'
    _description = 'Competency Proficiency Level'
    _order = 'competency_id, level'

    LEVEL_NAME_MAP = {
        '1': 'Basic',
        '2': 'Intermediate',
        '3': 'Advanced',
        '4': 'Expert',
    }

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Level', required=True, default='1')
    name = fields.Selection([
        ('Basic', 'Basic'),
        ('Intermediate', 'Intermediate'),
        ('Advanced', 'Advanced'),
        ('Expert', 'Expert'),
    ], string='Level Name', compute='_compute_name', store=True, readonly=True)
    definition = fields.Text(string='Definition')
    behavioral_indicators = fields.Text(string='Behavioral Indicators', required=True)

    _sql_constraints = [
        ('competency_level_uniq', 'unique(competency_id, level)',
         'This proficiency level already exists for this competency. You cannot create duplicate levels. Please edit the existing record instead.'),
    ]

    @api.depends('level')
    def _compute_name(self):
        for rec in self:
            rec.name = self.LEVEL_NAME_MAP.get(str(rec.level or '1'), 'Basic')

    @api.onchange('level')
    def _onchange_level(self):
        if self.level:
            self.name = self.LEVEL_NAME_MAP.get(str(self.level), 'Basic')

    @api.constrains('competency_id', 'level')
    def _check_level_uniqueness_and_limit(self):
        for rec in self:
            if rec.competency_id:
                all_levels = self.search([('competency_id', '=', rec.competency_id.id)])
                if len(all_levels) > 4:
                    raise ValidationError(_("A competency cannot have more than 4 proficiency levels. Exactly 4 levels (Level 1 - Basic, Level 2 - Intermediate, Level 3 - Advanced, Level 4 - Expert) are required."))
                duplicates = self.search([
                    ('competency_id', '=', rec.competency_id.id),
                    ('level', '=', rec.level),
                    ('id', '!=', rec.id)
                ])
                if duplicates:
                    raise ValidationError(_("This proficiency level (Level %s) already exists for this competency. You cannot create duplicate levels. Please edit the existing record instead.") % rec.level)

    @api.constrains('behavioral_indicators')
    def _check_behavioral_indicators(self):
        for rec in self:
            if not rec.behavioral_indicators or not rec.behavioral_indicators.strip():
                name_str = rec.name or self.LEVEL_NAME_MAP.get(str(rec.level or '1'), 'Basic')
                raise ValidationError(_("Behavioral Indicators are required for Level %s (%s). Please fill in the behavioral indicators before saving.") % (rec.level, name_str))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            lvl = str(vals.get('level') or '1')
            vals['name'] = self.LEVEL_NAME_MAP.get(lvl, 'Basic')
            comp_id = vals.get('competency_id')
            if comp_id:
                comp = self.env['competency.competency'].browse(comp_id)
                if comp.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                    raise ValidationError(_("Cannot add proficiency levels to a retired competency (%s).") % comp.name)
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.competency_id and rec.competency_id.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify proficiency levels on a retired competency (%s).") % rec.competency_id.name)
            
        if 'level' in vals or 'name' in vals:
            for rec in self:
                lvl = str(vals.get('level', rec.level) or '1')
                vals['name'] = self.LEVEL_NAME_MAP.get(lvl, 'Basic')
                
        if 'definition' in vals:
            for rec in self:
                new_def = (vals.get('definition') or '').strip()
                old_def = (rec.definition or '').strip()
                if new_def != old_def:
                    approved_fw = self.env['competency.framework.line'].search([
                        ('competency_id', '=', rec.competency_id.id),
                        ('framework_id.state', '=', 'approved')
                    ], limit=1)
                    if approved_fw and not self.env.context.get('eds_allow_definition_edit') and not self.env.context.get('force_write'):
                        raise ValidationError(_(
                            "Definition text cannot be freely re-edited for a competency on an approved framework "
                            "without going through the Competency Framework change/version-control workflow (FR-COM-006). "
                            "Create a new framework version or submit an approved change request."
                        ))
                    
                    change_desc = self.env.context.get('change_description') or _("Updated Level %s definition.") % rec.level
                    eff_date = self.env.context.get('effective_date') or fields.Date.context_today(self)
                    self.env['competency.level.change.log'].sudo().create({
                        'level_id': rec.id,
                        'competency_id': rec.competency_id.id,
                        'old_definition': old_def,
                        'new_definition': new_def,
                        'change_description': change_desc,
                        'effective_date': eff_date,
                        'user_id': self.env.user.id,
                    })
                    if rec.competency_id:
                        rec.competency_id.message_post(
                            body=_("Proficiency Level %s definition updated by %s.<br/><b>Old:</b> %s<br/><b>New:</b> %s") % (
                                rec.level, self.env.user.name, old_def, new_def
                            )
                        )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_retired(self):
        for rec in self:
            if rec.competency_id and rec.competency_id.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete proficiency levels from a retired competency (%s).") % rec.competency_id.name)



class Competency(models.Model):
    """Competency dictionary entry (FR-COM-002, FR-COM-003)."""
    _name = 'competency.competency'
    _description = 'Competency'
    _inherit = ['mail.thread']
    _order = 'pillar, code'

    name = fields.Char(string='Competency Name', required=True, tracking=True)
    code = fields.Char(string='Competency Code', required=True, tracking=True)
    pillar = fields.Selection([
        ('core', 'Core Competencies'),
        ('leadership', 'Leadership Competencies'),
        ('technical', 'Technical Competencies'),
    ], string='Pillar', required=True, tracking=True)
    functional_domain = fields.Char(string='Functional Domain')
    definition = fields.Text(string='Definition', tracking=True)
    rating_model_id = fields.Many2one('competency.rating.model', string='Rating Model')
    proficiency_level_ids = fields.One2many(
        'competency.proficiency.level', 'competency_id', string='Proficiency Levels')
    applicable_job_ids = fields.Many2many(
        'hr.job', string='Applicable Job Positions',
        compute='_compute_applicable_job_ids', store=True)

    @api.depends('status')
    def _compute_applicable_job_ids(self):
        RoleMappingLine = self.env['competency.role.mapping.line']
        for rec in self:
            lines = RoleMappingLine.search([
                ('competency_id', '=', rec.id),
                ('mapping_id.state', '=', 'approved')
            ])
            rec.applicable_job_ids = lines.mapped('mapping_id.job_position_id')
    change_log_ids = fields.One2many(
        'competency.level.change.log', 'competency_id', string='Definition Change Logs', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], string='Approval State', default='draft', tracking=True)

    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Status', compute='_compute_status', store=True)

    active = fields.Boolean(default=True, tracking=True)

    @api.depends('state')
    def _compute_status(self):
        for rec in self:
            if rec.state == 'approved':
                rec.status = 'active'
            else:
                rec.status = 'inactive'

    def action_submit(self):
        for rec in self:
            if not rec.proficiency_level_ids or len(rec.proficiency_level_ids) < 4:
                raise ValidationError(_("Competency '%s' must have all 4 proficiency levels defined before submitting for approval.") % rec.name)
            rec.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            rec.write({'state': 'approved', 'active': True})

    def action_retire(self):
        """Retire/inactivate competency and auto-disappear from clusters & job mappings."""
        for rec in self:
            rec.write({'state': 'retired', 'active': False})
            # Auto-disappear from clusters and role mappings
            self.env['competency.cluster.line'].search([('competency_id', '=', rec.id)]).unlink()
            self.env['competency.role.mapping.line'].search([('competency_id', '=', rec.id)]).unlink()
            rec.message_post(body=_("Competency '%s' has been retired and automatically unlinked from all clusters and role mappings.") % rec.name)

    def action_reset_draft(self):
        for rec in self:
            rec.write({'state': 'draft', 'active': True})

    @api.constrains('name')
    def _check_unique_name_case_insensitive(self):
        for rec in self:
            if rec.name:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('name', '=ilike', rec.name.strip())
                ], limit=1)
                if duplicate:
                    raise ValidationError(_("A competency with the name '%s' already exists (Code: %s). Competency names must be unique.") % (rec.name.strip(), duplicate.code))

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Competency Code must be unique!'),
    ]

    @api.constrains('proficiency_level_ids')
    def _check_proficiency_levels_completeness(self):
        for rec in self:
            levels = rec.proficiency_level_ids
            existing_lvl_codes = set(levels.mapped('level'))
            required_lvl_codes = {'1', '2', '3', '4'}
            
            if len(levels) > 4:
                raise ValidationError(_("A competency cannot have more than 4 proficiency levels. Exactly 4 levels (Level 1 - Basic, Level 2 - Intermediate, Level 3 - Advanced, Level 4 - Expert) are required."))
                
            if len(levels) != len(existing_lvl_codes):
                raise ValidationError(_("Duplicate proficiency levels detected on competency '%s'. Each competency must have unique levels (Level 1, Level 2, Level 3, Level 4).") % rec.name)
                
            missing = required_lvl_codes - existing_lvl_codes
            if missing:
                missing_names = []
                name_map = {'1': 'Level 1 (Basic)', '2': 'Level 2 (Intermediate)', '3': 'Level 3 (Advanced)', '4': 'Level 4 (Expert)'}
                for m in sorted(missing):
                    missing_names.append(name_map.get(m, m))
                raise ValidationError(_("Competencies must have all 4 proficiency levels. Missing level(s): %s.") % ", ".join(missing_names))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            # Auto-create the standard 4 proficiency levels unless provided.
            if not record.proficiency_level_ids:
                record._generate_default_proficiency_levels()
        return records

    def _generate_default_proficiency_levels(self):
        defaults = [
            ('1', 'Basic', 'Foundational understanding; applies with guidance.',
             'Demonstrates basic awareness and foundational knowledge; applies skills under direct supervision and guidance.'),
            ('2', 'Intermediate', 'Solid working knowledge; applies independently.',
             'Applies solid working knowledge independently in routine operational situations; resolves standard technical issues.'),
            ('3', 'Advanced', 'Deep expertise; serves as go-to resource.',
             'Demonstrates advanced proficiency and deep subject matter expertise; guides and mentors team members on complex scenarios.'),
            ('4', 'Expert', 'Mastery and thought leadership; shapes organizational direction.',
             'Displays strategic mastery and thought leadership; defines institutional standards and drives organizational innovation.'),
        ]
        Level = self.env['competency.proficiency.level']
        for level, name, definition, indicators in defaults:
            Level.create({
                'competency_id': self.id,
                'level': level,
                'name': name,
                'definition': definition,
                'behavioral_indicators': indicators,
            })

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        allow_def_edit = self.env.context.get('eds_allow_definition_edit')
        
        for rec in self:
            # 1. Retired status lock
            if rec.status == 'retired' and not force_write and not self.env.su:
                if set(vals.keys()) - {'status', 'active'}:
                    raise ValidationError(_("This competency (%s) is retired and cannot be edited. Reactivate the competency or use an Admin override instead.") % rec.name)
            
            # 2. Governed-edit check for name or pillar on approved framework
            if ('name' in vals or 'pillar' in vals) and not force_write and not allow_def_edit and not self.env.su:
                new_name = vals.get('name', rec.name)
                new_pillar = vals.get('pillar', rec.pillar)
                if new_name != rec.name or new_pillar != rec.pillar:
                    approved_fw = self.env['competency.framework.line'].search([
                        ('competency_id', '=', rec.id),
                        ('framework_id.state', '=', 'approved')
                    ], limit=1)
                    if approved_fw:
                        raise ValidationError(_(
                            "Competency name or pillar cannot be re-edited for a competency on an approved framework (%s) "
                            "without going through the Competency Framework change/version-control workflow (FR-COM-006). "
                            "Create a new framework version or submit an approved change request."
                        ) % approved_fw.framework_id.name)
                        
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_('Retired competencies cannot be deleted.'))
        return super().unlink()

    @api.model
    def action_seed_matrix_data(self):
        """Seed competencies, framework, clusters, and role mappings from docs/edited Final Comptency Matrix......xlsx."""
        import os, zipfile, re, logging
        import xml.etree.ElementTree as ET

        _logger = logging.getLogger(__name__)

        possible_paths = [
            r'docs/edited Final Comptency Matrix......xlsx',
            r'/mnt/extra-addons/competency_management/data/competency_matrix.xlsx',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'edited Final Comptency Matrix......xlsx')),
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'competency_matrix.xlsx')),
        ]
        
        target_path = False
        for p in possible_paths:
            if os.path.exists(p):
                target_path = p
                break
                
        if not target_path:
            _logger.info("Matrix XLSX seed file not found. Skipping auto-seed.")
            return True

        with zipfile.ZipFile(target_path, 'r') as z:
            strings_xml = z.read('xl/sharedStrings.xml')
            stree = ET.fromstring(strings_xml)
            shared_strings = [''.join(t.text or '' for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')) for si in stree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si')]

            def get_val(cell):
                t = cell.attrib.get('t')
                v = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                if v is None: return ''
                val = v.text
                if t == 's': return shared_strings[int(val)] if int(val) < len(shared_strings) else val
                return val

            wb_xml = z.read('xl/workbook.xml')
            wbtree = ET.fromstring(wb_xml)
            sheets_info = [child.attrib['name'] for child in wbtree.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets')]

            raw_mappings = []
            domain_comps_map = {}
            for idx, sname in enumerate(sheets_info, 1):
                if sname == 'Proficiency': continue
                try:
                    sheet_xml = z.read(f'xl/worksheets/sheet{idx}.xml')
                except Exception:
                    continue
                stree = ET.fromstring(sheet_xml)
                rows = list(stree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'))
                if not rows: continue
                
                for r in rows[1:]:
                    vals = [get_val(c).strip() for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')]
                    if len(vals) >= 4 and vals[1].strip():
                        cat = vals[0].strip()
                        cname = re.sub(r'\s+', ' ', vals[1].strip())
                        jtitle = re.sub(r'\s+', ' ', vals[2].strip())
                        prof = vals[3].strip()
                        wunit = vals[4].strip() if len(vals) > 4 else ''
                        raw_mappings.append((cat, cname, jtitle, prof, wunit, sname))
                        domain_comps_map.setdefault(sname, set()).add(cname)

        rating_model = self.env['competency.rating.model'].search([('code', '=', '4SCALE')], limit=1)
        if not rating_model:
            rating_model = self.env['competency.rating.model'].create({
                'name': '4-Point Proficiency Scale',
                'code': '4SCALE',
                'max_rating': 4,
                'description': 'Standard 4-Level scale (Level 1 Basic, Level 2 Intermediate, Level 3 Advanced, Level 4 Expert)'
            })

        core_names = {'Execution Mastery', 'Professional Authenticity', 'Ethical Influence', 'Collaboration', 'Creativity'}
        leadership_names = {'Strategy Management', 'Continuous Improvement', 'Prudential Decision Making', 'Self Leadership', 'People Leadership', 'Ambidexterity Leadership', 'Ambidextrous Leadership', 'Self-Leadership'}

        distinct_comps = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            cat_lower = cat.lower()
            if 'core' in cat_lower or cname_clean in core_names:
                pillar = 'core'
            elif 'lead' in cat_lower or cname_clean in leadership_names:
                pillar = 'leadership'
            else:
                pillar = 'technical'
            
            if cname_clean not in distinct_comps:
                distinct_comps[cname_clean] = (pillar, sname)

        # Parse definitions from docx file if present
        doc_defs = {}
        docx_path = False
        possible_docx = [
            r'docs/Final Competency Framework Reviesd.docx',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'Final Competency Framework Reviesd.docx')),
        ]
        for dp in possible_docx:
            if os.path.exists(dp):
                docx_path = dp
                break
        if docx_path:
            try:
                import docx
                d_doc = docx.Document(docx_path)
                for tbl in d_doc.tables:
                    if len(tbl.columns) >= 2:
                        for row in tbl.rows:
                            tc1 = row.cells[0].text.strip() if len(row.cells) > 0 else ''
                            tc2 = row.cells[1].text.strip() if len(row.cells) > 1 else ''
                            if tc1 and tc2 and tc1 not in ('Competency', 'Framework Pillar', 'Pillar', 'Instead of...'):
                                c1_clean = ' '.join(tc1.split()).lower()
                                c2_clean = ' '.join(tc2.split())
                                doc_defs[c1_clean] = c2_clean
            except Exception:
                pass

        matrix_config = self.env['competency.matrix.config'].get_active_config()

        tech_counter = 1
        comp_records = {}
        for cname, (pillar, domain) in sorted(distinct_comps.items()):
            comp = self.env['competency.competency'].search([('name', '=ilike', cname)], limit=1)
            rich_def = doc_defs.get(cname.lower(), f"Bunna Bank {pillar.capitalize()} Competency: {cname}")
            
            if not comp:
                if pillar == 'core':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'core']) + 1
                    code = f"CORE-{c_cnt:02d}"
                elif pillar == 'leadership':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'leadership']) + 1
                    code = f"LEAD-{c_cnt:02d}"
                else:
                    code = f"TECH-{tech_counter:03d}"
                    tech_counter += 1

                comp = self.env['competency.competency'].create({
                    'name': cname,
                    'code': code,
                    'pillar': pillar,
                    'functional_domain': domain if pillar == 'technical' else 'Bank-Wide',
                    'definition': rich_def,
                    'rating_model_id': rating_model.id,
                    'status': 'active',
                })
            else:
                if not comp.definition or comp.definition.startswith("Bunna Bank "):
                    comp.write({'definition': rich_def})

            comp_records[cname] = comp

            for lvl_val, lvl_name in [
                ('1', 'Basic'),
                ('2', 'Intermediate'),
                ('3', 'Advanced'),
                ('4', 'Expert'),
            ]:
                if pillar == 'technical':
                    b_ind = getattr(matrix_config, f'tech_indicator_level_{lvl_val}', f"Level {lvl_val} ({lvl_name}) technical behavioral indicator for {cname}.")
                else:
                    b_ind = f"Level {lvl_val} ({lvl_name}) behavioral indicators for {cname}."

                existing_lvl = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', comp.id),
                    ('level', '=', lvl_val)
                ], limit=1)
                if not existing_lvl:
                    self.env['competency.proficiency.level'].create({
                        'competency_id': comp.id,
                        'level': lvl_val,
                        'behavioral_indicators': b_ind,
                    })
                else:
                    existing_lvl.write({'behavioral_indicators': b_ind})

        framework = self.env['competency.framework'].search([('code', '=', 'BUNNA-FW-v1.0')], limit=1)
        if not framework:
            framework = self.env['competency.framework'].create({
                'name': "Bunna Bank Integrated Competency Framework",
                'code': 'BUNNA-FW-v1.0',
                'version': 'v1.0',
                'description': "Bunna Bank's official Integrated Competency Framework comprising Core, Leadership, and Technical competencies.",
                'state': 'draft',
            })
        
        fw_existing_comps = framework.line_ids.mapped('competency_id.id')
        fw_line_vals = []
        for cname, comp in comp_records.items():
            if comp.id not in fw_existing_comps:
                fw_line_vals.append({
                    'framework_id': framework.id,
                    'competency_id': comp.id,
                })
        if fw_line_vals:
            self.env['competency.framework.line'].create(fw_line_vals)

        if framework.state != 'approved':
            framework.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })

        clusters = {}
        core_comps = [c.id for c in comp_records.values() if c.pillar == 'core']
        core_cluster = self.env['competency.cluster'].search([('code', '=', 'CLUSTER-CORE')], limit=1)
        if not core_cluster:
            core_cluster = self.env['competency.cluster'].create({
                'name': 'Core Competency Cluster',
                'code': 'CLUSTER-CORE',
                'description': 'Universal Core Competencies required across all Bunna Bank roles.',
                'competency_ids': [(6, 0, core_comps)],
                'min_proficiency': '2',
            })
        else:
            core_cluster.write({'competency_ids': [(6, 0, core_comps)]})
        clusters['core'] = core_cluster

        lead_comps = [c.id for c in comp_records.values() if c.pillar == 'leadership']
        lead_cluster = self.env['competency.cluster'].search([('code', '=', 'CLUSTER-LEAD')], limit=1)
        if not lead_cluster:
            lead_cluster = self.env['competency.cluster'].create({
                'name': 'Leadership Capability Cluster',
                'code': 'CLUSTER-LEAD',
                'description': 'Leadership and Supervisory Competencies for managerial and leadership roles.',
                'competency_ids': [(6, 0, lead_comps)],
                'min_proficiency': '2',
            })
        else:
            lead_cluster.write({'competency_ids': [(6, 0, lead_comps)]})
        clusters['leadership'] = lead_cluster

        for sname, cnames in domain_comps_map.items():
            domain_comp_ids = [comp_records[cn].id for cn in cnames if cn in comp_records]
            code_safe = re.sub(r'[^A-Z0-9]', '', sname.upper())[:10]
            cluster_code = f"CLUSTER-TECH-{code_safe}"
            t_cluster = self.env['competency.cluster'].search([('code', '=', cluster_code)], limit=1)
            if not t_cluster and domain_comp_ids:
                t_cluster = self.env['competency.cluster'].create({
                    'name': f"{sname} Technical Cluster",
                    'code': cluster_code,
                    'description': f"Technical Competency Cluster for {sname} functional domain.",
                    'competency_ids': [(6, 0, domain_comp_ids)],
                    'min_proficiency': '2',
                })
            elif t_cluster and domain_comp_ids:
                t_cluster.write({'competency_ids': [(6, 0, domain_comp_ids)]})
            clusters[sname] = t_cluster

        job_mappings = {}
        job_domains = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            if not jtitle: continue
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            comp = comp_records.get(cname_clean)
            if not comp: continue
            
            prof_str = str(prof).strip()
            req_prof = prof_str if prof_str in ('1', '2', '3', '4') else '2'
            job_mappings.setdefault(jtitle, {})[comp.id] = req_prof
            job_domains.setdefault(jtitle, set()).add(sname)

        mapping_count = 0
        for jtitle, comp_dict in job_mappings.items():
            job = self.env['hr.job'].search([('name', '=ilike', jtitle)], limit=1)
            if not job:
                job = self.env['hr.job'].create({
                    'name': jtitle,
                    'description': f"Job Position for {jtitle}",
                })

            mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
            if not mapping:
                applicable_cluster_ids = [core_cluster.id]
                j_lower = jtitle.lower()
                if any(k in j_lower for k in ['manager', 'director', 'chief', 'leader', 'head', 'supervisor']):
                    applicable_cluster_ids.append(lead_cluster.id)
                for dom in job_domains.get(jtitle, []):
                    if dom in clusters and clusters[dom]:
                        applicable_cluster_ids.append(clusters[dom].id)

                mapping = self.env['competency.role.mapping'].create({
                    'job_position_id': job.id,
                    'version': 'v1.0',
                    'state': 'draft',
                    'effective_date': fields.Date.context_today(self),
                    'change_description': 'Official Bunna Bank Competency Framework matrix import',
                    'cluster_ids': [(6, 0, list(set(applicable_cluster_ids)))],
                })

            existing_comp_ids = mapping.line_ids.mapped('competency_id.id')
            line_create_vals = []
            for cid, req_p in comp_dict.items():
                if cid not in existing_comp_ids:
                    line_create_vals.append({
                        'mapping_id': mapping.id,
                        'competency_id': cid,
                        'required_proficiency': req_p,
                        'weight': 1.0,
                    })
            if line_create_vals:
                self.env['competency.role.mapping.line'].create(line_create_vals)

            if mapping.state != 'approved':
                mapping.with_context(force_write=True).write({
                    'state': 'approved',
                    'approved_by_id': self.env.user.id,
                    'approval_date': fields.Datetime.now(),
                })
            mapping_count += 1

        # Seed default Job Position Matrix lines
        for job in self.env['hr.job'].search([]):
            j_line = self.env['competency.job.matrix'].search([
                ('config_id', '=', matrix_config.id),
                ('job_id', '=', job.id)
            ], limit=1)
            if not j_line:
                core_l = self.env['competency.assessment']._get_matrix_required_level('core', job_name=job.name)
                lead_l = self.env['competency.assessment']._get_matrix_required_level('leadership', job_name=job.name)
                tech_l = self.env['competency.assessment']._get_matrix_required_level('technical', job_name=job.name)
                self.env['competency.job.matrix'].create({
                    'config_id': matrix_config.id,
                    'job_id': job.id,
                    'required_core_level': core_l,
                    'required_leadership_level': lead_l,
                    'required_technical_level': tech_l,
                })

        # Seed default Job Grade Matrix lines
        for grade in self.env['employee.grade'].search([]):
            g_line = self.env['competency.grade.matrix'].search([
                ('config_id', '=', matrix_config.id),
                ('grade_id', '=', grade.id)
            ], limit=1)
            if not g_line:
                core_l = self.env['competency.assessment']._get_matrix_required_level('core', grade=grade)
                lead_l = self.env['competency.assessment']._get_matrix_required_level('leadership', grade=grade)
                tech_l = self.env['competency.assessment']._get_matrix_required_level('technical', grade=grade)
                self.env['competency.grade.matrix'].create({
                    'config_id': matrix_config.id,
                    'grade_id': grade.id,
                    'required_core_level': core_l,
                    'required_leadership_level': lead_l,
                    'required_technical_level': tech_l,
                })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Matrix Seeding Complete'),
                'message': _('Seeded %s competencies (with docx definitions), %s clusters, and %s job position role mappings successfully.') % (len(comp_records), len(clusters), mapping_count),
                'type': 'success',
                'sticky': False,
            }
        }


