# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """EDS configuration parameters (BRD Part 2 defaults).

    Defaults follow the BRD:
      - TNA cycle starts 1 April (FREDS001)
      - submission window 10 working days (FREDS002)
      - approval deadline 31 May (FREDS009)
      - minimum 80% attendance for certification (FREDS040)
      - default class size 25-30 (FREDS039)
      - curriculum SLA 10 working days (FREDS014)
      - course-to-competency mapping SLA 5 working days (FREDS012)
      - calendar SLA 5 working days (FREDS020)
      - Level 1 evaluation report SLA 7 working days (FREDS054)
      - sponsorship minimum service 12 months (FREDS062)
      - learning partnership minimum score 70% (FREDS069)
    """
    _inherit = 'res.config.settings'

    # TNA timing (FREDS001/002/009)
    eds_tna_cycle_start_month = fields.Integer(
        string='TNA Cycle Start Month',
        default=4,
        config_parameter='eds.tna_cycle_start_month',
        help='Month (1-12) when the annual TNA cycle starts. Default: 4 (April).')
    eds_tna_submission_days = fields.Integer(
        string='TNA Submission Window (Working Days)',
        default=10,
        config_parameter='eds.tna_submission_days',
        help='Submission window in working days (FREDS002).')
    eds_tna_approval_deadline_month = fields.Integer(
        string='TNA Approval Deadline Month',
        default=5,
        config_parameter='eds.tna_approval_deadline_month',
        help='Month when the TNA must be finally approved (FREDS009). Default: 5 (May).')
    eds_tna_approval_deadline_day = fields.Integer(
        string='TNA Approval Deadline Day',
        default=31,
        config_parameter='eds.tna_approval_deadline_day',
        help='Day of the TNA approval deadline. Default: 31.')

    # Delivery (FREDS039/040)
    eds_default_class_capacity = fields.Integer(
        string='Default Session Capacity',
        default=30,
        config_parameter='eds.default_class_capacity',
        help='Default class size for training sessions (BRD: 25-30).')
    eds_min_attendance_pct = fields.Float(
        string='Minimum Attendance % for Certification',
        default=80.0,
        config_parameter='eds.min_attendance_pct',
        help='Minimum attendance percentage required for certificate eligibility (FREDS040).')

    # SLAs (FREDS012/014/020/054)
    eds_course_mapping_sla_days = fields.Integer(
        string='Course-to-Competency Mapping SLA (Working Days)',
        default=5,
        config_parameter='eds.course_mapping_sla_days')
    eds_curriculum_sla_days = fields.Integer(
        string='Curriculum Development SLA (Working Days)',
        default=10,
        config_parameter='eds.curriculum_sla_days')
    eds_calendar_sla_days = fields.Integer(
        string='Annual Calendar Generation SLA (Working Days)',
        default=5,
        config_parameter='eds.calendar_sla_days')
    eds_level1_report_sla_days = fields.Integer(
        string='Level 1 Evaluation Report SLA (Working Days)',
        default=7,
        config_parameter='eds.level1_report_sla_days')

    # Evaluation & finance (FR-EDS-038, FREDS062/069)
    eds_level2_pass_threshold = fields.Float(
        string='Level 2 Pass Threshold (%)',
        default=60.0,
        config_parameter='eds.level2_pass_threshold',
        help='Recommended default 60% - the BRD only requires a configurable threshold (FR-EDS-038).')

    # Nomination approval chain (FR-EDS-026)
    eds_nomination_require_line_manager = fields.Boolean(
        string='Require Line Manager Approval Step',
        default=True,
        config_parameter='eds.nomination_require_line_manager',
        help='Whether the Line Manager approval step is part of the nomination chain. '
             'Off = Line Manager -> L&D is skipped directly to L&D (FR-EDS-026).')
    eds_nomination_require_budget = fields.Boolean(
        string='Require Budget/HR Approval Step',
        default=False,
        config_parameter='eds.nomination_require_budget',
        help='Whether nominations always pass an explicit Budget/HR approval gate '
             '(overridable per session approval flow, FR-EDS-026).')

    # Procurement & vendors (FREDS030/032/034)
    eds_rfp_min_providers = fields.Integer(
        string='Minimum Providers per RFP',
        default=3,
        config_parameter='eds.rfp_min_providers',
        help='Minimum number of qualified providers an RFP must be issued to (FREDS030, default >= 3).')
    eds_technical_min_threshold = fields.Float(
        string='Technical Minimum Threshold (%)',
        default=70.0,
        config_parameter='eds.technical_min_threshold',
        help='Minimum technical qualification threshold before the financial evaluation is permitted (FREDS032).')
    eds_technical_financial_blend = fields.Integer(
        string='Technical / Financial Weight (%)',
        default=70,
        config_parameter='eds.technical_financial_blend',
        help='Weight of the technical score in the combined score; financial is 100 minus this (FREDS034).')
    eds_sponsorship_min_service_months = fields.Integer(
        string='Sponsorship Minimum Service (Months)',
        default=12,
        config_parameter='eds.sponsorship_min_service_months',
        help='Minimum continuous service period for certification sponsorship eligibility (FREDS062).')
    eds_partnership_min_score = fields.Float(
        string='Learning Partnership Minimum Score',
        default=70.0,
        config_parameter='eds.partnership_min_score',
        help='Minimum qualification threshold for learning partnership proposals (FREDS069).')
