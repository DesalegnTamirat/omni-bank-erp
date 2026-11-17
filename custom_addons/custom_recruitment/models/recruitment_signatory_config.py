# -*- coding: utf-8 -*-
import base64
import os
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class RecruitmentSignatoryConfig(models.Model):
    """
    Universal Authorized Signatories & Official Stamps Configuration.
    Enables HR administrators to manage official signatures and rubber stamps
    for all Bank letters (Lateral Transfer, Promotion, Employment) and Minutes.
    """
    _name = 'recruitment.signatory.config'
    _description = 'Authorized Signatory and Official Stamp Configuration'
    _order = 'is_default desc, id desc'

    name = fields.Char(
        string='Configuration Name',
        required=True,
    )
    def _default_department_id(self):
        dept = self.env['hr.department'].search([
            ('name', 'ilike', 'People Operation Management')
        ], limit=1)
        if not dept:
            dept = self.env['hr.department'].search([
                ('name', 'ilike', 'People Operation')
            ], limit=1)
        if not dept:
            dept = self.env['hr.department'].search([
                ('name', 'ilike', 'Head Office')
            ], limit=1)
        return dept.id if dept else False

    def _default_signatory_title(self):
        dept = self.env['hr.department'].search([
            ('name', 'ilike', 'People Operation Management')
        ], limit=1)
        if dept:
            return dept.name
        return 'People Operation Management Directorate'

    signatory_name = fields.Char(
        string='Signatory Full Name',
        required=True,
        default='Abayneh Markos',
        help='Full name of the authorized director / executive'
    )
    signatory_title = fields.Char(
        string='Authorized Signatory Title',
        required=True,
        default=lambda self: self._default_signatory_title(),
        help='Directorate or official title appearing on the letter/minute. Automatically set based on the selected Organizational Level.'
    )
    signatory_company = fields.Char(
        string='Company Name',
        required=True,
        default='Bunna Bank S.C.'
    )
    org_level = fields.Selection([
        ('head_office', 'Head Office'),
        ('district', 'District'),
    ], string='Department Type', default='head_office', required=True,
       help='Defines whether this signature applies to Head Office or a specific District')

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='District / Operating Unit',
        domain="[('work_unit_type', 'in', ('district_office', 'head_office', 'regional_office'))]",
        help='Select the District Office this configuration belongs to.'
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Head Office Department',
        default=lambda self: self._default_department_id(),
        domain="[('name', 'not ilike', 'district')]",
        help='Select the Head Office department/directorate (defaults to People Operation Management Directorate).'
    )

    @api.onchange('org_level')
    def _onchange_org_level(self):
        for rec in self:
            if rec.org_level == 'head_office':
                rec.operating_unit_id = False
                if not rec.department_id:
                    rec.department_id = rec._default_department_id()
                if rec.department_id:
                    rec.signatory_title = rec.department_id.name
                else:
                    rec.signatory_title = 'People Operation Management Directorate'
            elif rec.org_level == 'district':
                rec.department_id = False
                if rec.operating_unit_id:
                    rec.signatory_title = rec.operating_unit_id.name

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_id(self):
        for rec in self:
            if rec.org_level == 'district' and rec.operating_unit_id:
                rec.signatory_title = rec.operating_unit_id.name

    @api.onchange('department_id')
    def _onchange_department_id(self):
        for rec in self:
            if rec.org_level == 'head_office' and rec.department_id:
                rec.signatory_title = rec.department_id.name

    document_scope = fields.Selection([
        ('all', 'All Documents & Minutes'),
        ('transfer_letter', 'Lateral Transfer Letters'),
        ('promotion_letter', 'Promotion Letters'),
        ('permanent_letter', 'Probation Confirmation / Permanent Letters'),
        ('experience_letter', 'Work Experience Letters'),
        ('committee_minute', 'Committee Minutes'),
        ('employment_letter', 'External Employment Letters'),
    ], string='Applicable Document Scope', default='all', required=True)

    signature_image = fields.Binary(
        string='Signatory Handwritten Signature',
        attachment=True,
        help='Upload PNG/JPG containing the personal handwritten signature of the authorized signatory (transparent/white background)'
    )
    stamp_image = fields.Binary(
        string='Official Rubber Stamp / Seal',
        attachment=True,
        help='Upload PNG/JPG containing the official circular purple Bunna Bank rubber stamp (transparent/white background)'
    )
    stamp_position = fields.Selection([
        ('right', 'Stamp to the Right of Signature'),
        ('left', 'Stamp to the Left of Signature'),
        ('overlap', 'Stamp Overlapping Signature'),
    ], string='Stamp Placement', default='right', required=True,
       help='Positioning of the official stamp relative to the handwritten signature')

    signature_stamp_image = fields.Binary(
        string='Combined Signature & Stamp (Legacy)',
        attachment=True,
        help='Legacy upload PNG/JPG containing both signature and stamp merged into a single image'
    )
    is_default = fields.Boolean(
        string='Default Active Signatory',
        default=True,
        help='If checked, this signatory & stamp will be automatically used for matching documents'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Uncheck to archive when personnel rotate while preserving past audit trail'
    )

    def _auto_init(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    ALTER TABLE recruitment_signatory_config 
                    ADD COLUMN IF NOT EXISTS org_level varchar DEFAULT 'head_office',
                    ADD COLUMN IF NOT EXISTS operating_unit_id integer,
                    ADD COLUMN IF NOT EXISTS department_id integer,
                    ADD COLUMN IF NOT EXISTS stamp_position varchar DEFAULT 'right';

                    UPDATE recruitment_signatory_config 
                    SET org_level = 'head_office' 
                    WHERE org_level IS NULL OR org_level = '' OR org_level = 'all';
                    UPDATE recruitment_signatory_config 
                    SET stamp_position = 'right' 
                    WHERE stamp_position IS NULL OR stamp_position = '';
                """)
        except Exception:
            pass
        return super()._auto_init()

    @api.constrains('is_default', 'document_scope', 'org_level', 'operating_unit_id', 'active')
    def _check_single_default_per_scope(self):
        for rec in self:
            if rec.is_default and rec.active:
                domain = [
                    ('id', '!=', rec.id),
                    ('is_default', '=', True),
                    ('active', '=', True),
                    ('document_scope', '=', rec.document_scope),
                    ('org_level', '=', rec.org_level),
                    ('operating_unit_id', '=', rec.operating_unit_id.id if rec.operating_unit_id else False),
                ]
                others = self.search(domain)
                if others:
                    others.write({'is_default': False})

    def get_signature_base64(self):
        """Returns the Base64 data URI of the signatory handwritten signature."""
        self.ensure_one()
        if self.signature_image:
            b64_str = self.signature_image.decode('utf-8') if isinstance(self.signature_image, bytes) else self.signature_image
            return f"data:image/png;base64,{b64_str}"
        return ""

    def get_stamp_base64(self):
        """Returns the Base64 data URI of the official bank rubber stamp."""
        self.ensure_one()
        if self.stamp_image:
            b64_str = self.stamp_image.decode('utf-8') if isinstance(self.stamp_image, bytes) else self.stamp_image
            return f"data:image/png;base64,{b64_str}"

        # If this signatory has no stamp, search if a default stamp exists for this operating unit
        if self.operating_unit_id:
            parent_sig = self.search([
                ('active', '=', True),
                ('operating_unit_id', '=', self.operating_unit_id.id),
                ('stamp_image', '!=', False)
            ], limit=1)
            if parent_sig and parent_sig.stamp_image:
                b64_str = parent_sig.stamp_image.decode('utf-8') if isinstance(parent_sig.stamp_image, bytes) else parent_sig.stamp_image
                return f"data:image/png;base64,{b64_str}"

        # Search default head office stamp
        ho_sig = self.search([
            ('active', '=', True),
            ('org_level', '=', 'head_office'),
            ('stamp_image', '!=', False)
        ], limit=1)
        if ho_sig and ho_sig.stamp_image:
            b64_str = ho_sig.stamp_image.decode('utf-8') if isinstance(ho_sig.stamp_image, bytes) else ho_sig.stamp_image
            return f"data:image/png;base64,{b64_str}"

        return ""

    def has_separate_signature_and_stamp(self):
        """Returns True if this signatory config has separate signature or stamp images."""
        self.ensure_one()
        return bool(self.signature_image or self.stamp_image)

    def get_letter_signature_data(self):
        """Returns a comprehensive dict with signature, stamp, and layout options for all letter reports."""
        self.ensure_one()
        sig_b64 = self.get_signature_base64()
        stamp_b64 = self.get_stamp_base64()
        legacy_b64 = self.get_signature_stamp_base64()
        has_split = bool(sig_b64 or stamp_b64)
        return {
            'has_split': has_split,
            'signature_b64': sig_b64,
            'stamp_b64': stamp_b64,
            'legacy_b64': legacy_b64 if not has_split else '',
            'stamp_position': self.stamp_position or 'right',
            'signatory_name': self.signatory_name or '',
            'signatory_title': self.signatory_title or '',
            'signatory_company': self.signatory_company or 'Bunna Bank S.C.',
        }

    def get_signature_stamp_base64(self):
        """
        Returns the Base64 data URI of the legacy combined image or fallback.
        """
        self.ensure_one()
        if self.signature_stamp_image:
            b64_str = self.signature_stamp_image.decode('utf-8') if isinstance(self.signature_stamp_image, bytes) else self.signature_stamp_image
            return f"data:image/png;base64,{b64_str}"

        if self.signature_image and not self.stamp_image:
            return self.get_signature_base64()

        # Fallback to static asset
        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    @api.model
    def _find_org_level_and_district(self, work_unit=None, department=None):
        """
        Hierarchically resolves a work unit or department into (org_level, district_unit).
        Walks up the parent_unit hierarchy (up to 20 levels) until a district_office or
        head_office unit is encountered.
        """
        unit_rec = False
        if isinstance(work_unit, int):
            unit_rec = self.env['operating.unit'].browse(work_unit)
        elif hasattr(work_unit, '_name') and work_unit._name == 'operating.unit':
            unit_rec = work_unit
        elif isinstance(work_unit, str) and work_unit.strip():
            unit_rec = self.env['operating.unit'].search([
                '|', ('name', '=ilike', work_unit.strip()),
                     ('district', '=ilike', work_unit.strip())
            ], limit=1)

        if unit_rec and unit_rec.exists():
            seen = self.env['operating.unit']
            curr = unit_rec
            for _ in range(20):
                if not curr or curr in seen:
                    break
                if curr.work_unit_type == 'district_office':
                    return 'district', curr
                if curr.work_unit_type == 'head_office':
                    return 'head_office', curr
                seen |= curr
                curr = curr.parent_unit

            # Check if department belongs to head office
            if unit_rec.department and ('head office' in (unit_rec.department.name or '').lower()):
                return 'head_office', False

        dept_rec = False
        if isinstance(department, int):
            dept_rec = self.env['hr.department'].browse(department)
        elif hasattr(department, '_name') and department._name == 'hr.department':
            dept_rec = department

        if dept_rec and dept_rec.exists():
            dname = (dept_rec.name or '').lower()
            if 'district' in dname:
                dist_ou = self.env['operating.unit'].search([
                    ('work_unit_type', '=', 'district_office'),
                    ('name', 'ilike', dept_rec.name)
                ], limit=1)
                return 'district', dist_ou
            if 'head office' in dname or 'directorate' in dname:
                return 'head_office', False

        return 'head_office', False

    @api.model
    def get_signatory_for_unit(self, work_unit=None, department=None, doc_type='all'):
        """
        Dynamically resolves the active signatory configuration based on:
        Hiring Work Unit -> Department / Parent -> Org Level (Head Office vs District) -> Signatory Config.
        Falls back smoothly to Head Office or Universal Default.
        """
        org_level, district_unit = self._find_org_level_and_district(work_unit, department)

        # 1. District-specific match
        if org_level == 'district' and district_unit:
            # 1a: Specific document scope
            if doc_type and doc_type != 'all':
                sig = self.search([
                    ('active', '=', True),
                    ('is_default', '=', True),
                    ('org_level', '=', 'district'),
                    ('operating_unit_id', '=', district_unit.id),
                    ('document_scope', '=', doc_type),
                ], limit=1)
                if sig:
                    return sig

            # 1b: All documents scope for this district
            sig = self.search([
                ('active', '=', True),
                ('is_default', '=', True),
                ('org_level', '=', 'district'),
                ('operating_unit_id', '=', district_unit.id),
                ('document_scope', '=', 'all'),
            ], limit=1)
            if sig:
                return sig

        # 2. Head Office match
        # 2a: Specific document scope for Head Office
        if doc_type and doc_type != 'all':
            sig = self.search([
                ('active', '=', True),
                ('is_default', '=', True),
                ('org_level', '=', 'head_office'),
                ('document_scope', '=', doc_type),
            ], limit=1)
            if sig:
                return sig

        # 2b: All documents scope for Head Office
        sig = self.search([
            ('active', '=', True),
            ('is_default', '=', True),
            ('org_level', '=', 'head_office'),
            ('document_scope', '=', 'all'),
        ], limit=1)
        if sig:
            return sig

        # 3. Universal fallback
        return self.get_active_signatory(doc_type=doc_type)

    @api.model
    def get_active_signatory(self, doc_type='all', work_unit=None, department=None):
        """
        Retrieves the active default signatory configuration for a document type.
        If work_unit or department is provided, delegates to dynamic organizational resolution.
        """
        if work_unit or department:
            return self.get_signatory_for_unit(work_unit=work_unit, department=department, doc_type=doc_type)

        signatory = False
        if doc_type and doc_type != 'all':
            signatory = self.search([
                ('active', '=', True),
                ('is_default', '=', True),
                ('document_scope', '=', doc_type)
            ], limit=1)

        if not signatory:
            signatory = self.search([
                ('active', '=', True),
                ('is_default', '=', True),
                ('document_scope', '=', 'all')
            ], limit=1)

        if not signatory:
            signatory = self.search([('active', '=', True)], order='id asc', limit=1)

        return signatory

    @api.model
    def get_active_signature_stamp_base64(self, doc_type='all', work_unit=None, department=None):
        """Direct helper to retrieve Base64 signature data URI for any QWeb report template."""
        sig = self.get_active_signatory(doc_type=doc_type, work_unit=work_unit, department=department)
        if sig:
            return sig.get_signature_stamp_base64()

        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    @api.model
    def get_active_letter_signature_data(self, doc_type='all', work_unit=None, department=None):
        """Direct helper to retrieve structured signature and stamp data dictionary for any letter report."""
        sig = self.get_active_signatory(doc_type=doc_type, work_unit=work_unit, department=department)
        if sig:
            return sig.get_letter_signature_data()

        legacy_b64 = self.get_active_signature_stamp_base64(doc_type=doc_type, work_unit=work_unit, department=department)
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'legacy_b64': legacy_b64,
            'stamp_position': 'right',
            'signatory_name': self.signatory_name if hasattr(self, 'signatory_name') and self.signatory_name else 'Abayneh Markos',
            'signatory_title': self.signatory_title if hasattr(self, 'signatory_title') and self.signatory_title else 'People Operation Management Directorate',
            'signatory_company': self.signatory_company if hasattr(self, 'signatory_company') and self.signatory_company else 'Bunna Bank S.C.',
        }
