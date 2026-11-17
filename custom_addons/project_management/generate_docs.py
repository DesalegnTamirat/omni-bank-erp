#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate highly comprehensive, styled Microsoft Word (.docx) documents for:
1. Enterprise Project Management (Odoo 19) — Role-Based User Manual
2. Enterprise Project Management (Odoo 19) — Technical Architecture & Support Guide
"""

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import os

# Official Bunna Bank Corporate Color Palette
COLOR_MAROON = RGBColor(84, 23, 24)       # #541718
COLOR_PINE = RGBColor(30, 41, 23)         # #1E2917
COLOR_GREEN = RGBColor(66, 87, 39)        # #425727
COLOR_BRONZE = RGBColor(193, 117, 64)     # #C17540
COLOR_OLIVE = RGBColor(114, 103, 50)      # #726732
COLOR_NAVY = RGBColor(29, 43, 50)         # #1D2B32
COLOR_DARK_TEXT = RGBColor(33, 37, 41)    # #212529
COLOR_MUTED = RGBColor(108, 117, 125)     # #6C757D

HEX_MAROON = "541718"
HEX_GREEN = "425727"
HEX_NAVY = "1D2B32"
HEX_LIGHT_BG = "F8F9FA"
HEX_BORDER = "DEE2E6"


def set_cell_background(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m_name, m_val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m_name}')
        node.set(qn('w:w'), str(m_val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)


def add_callout(doc, title, text, border_color=HEX_MAROON, bg_color=HEX_LIGHT_BG):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    tbl.columns[0].width = Inches(6.5)
    
    cell = tbl.cell(0, 0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    # Left border styling
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    
    left_b = OxmlElement('w:left')
    left_b.set(qn('w:val'), 'single')
    left_b.set(qn('w:sz'), '24')  # 3pt
    left_b.set(qn('w:space'), '0')
    left_b.set(qn('w:color'), border_color)
    tcBorders.append(left_b)
    
    for b_name in ['top', 'bottom', 'right']:
        b = OxmlElement(f'w:{b_name}')
        b.set(qn('w:val'), 'none')
        tcBorders.append(b)
    tcPr.append(tcBorders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    run_t = p.add_run(f"★ {title}\n")
    run_t.font.bold = True
    run_t.font.name = "Calibri"
    run_t.font.size = Pt(11)
    run_t.font.color.rgb = COLOR_MAROON
    
    run_body = p.add_run(text)
    run_body.font.name = "Calibri"
    run_body.font.size = Pt(10)
    run_body.font.color.rgb = COLOR_DARK_TEXT
    doc.add_paragraph()


def format_table_headers(table, col_widths, col_names):
    hdr_cells = table.rows[0].cells
    for i, name in enumerate(col_names):
        hdr_cells[i].text = name
        hdr_cells[i].width = col_widths[i]
        set_cell_background(hdr_cells[i], HEX_MAROON)
        set_cell_margins(hdr_cells[i], top=120, bottom=120, left=140, right=140)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for r in p.runs:
            r.font.bold = True
            r.font.name = "Calibri"
            r.font.color.rgb = RGBColor(255, 255, 255)
            r.font.size = Pt(10)


def populate_table_row(row, values, col_widths, is_even=False):
    for i, val in enumerate(values):
        cell = row.cells[i]
        cell.text = str(val)
        cell.width = col_widths[i]
        bg = HEX_LIGHT_BG if is_even else "FFFFFF"
        set_cell_background(cell, bg)
        set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
        p = cell.paragraphs[0]
        for r in p.runs:
            r.font.name = "Calibri"
            r.font.size = Pt(9.5)
            r.font.color.rgb = COLOR_DARK_TEXT


# =========================================================================
# DOCUMENT 1: ROLE-BASED USER MANUAL
# =========================================================================
def build_user_manual():
    print("Generating Role-Based User Manual (.docx)...")
    doc = docx.Document()
    
    # Page setup: Standard Letter, 0.8 in margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # 1. Document Title Cover Banner
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(36)
    p_title.paragraph_format.space_after = Pt(4)
    run_title = p_title.add_run("Enterprise Project Management (Odoo 19)\nRole-Based Operational User Manual")
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(26)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_MAROON

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(24)
    run_sub = p_sub.add_run("Comprehensive Operating Procedures, Multi-Tier Governance, Preconditions, Error Resolutions & Executive Dashboards")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = COLOR_OLIVE

    # Metadata block
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(28)
    r_meta = p_meta.add_run("Version: 19.0.2.0-Enterprise  |  Classification: Production Operational Guide  |  System: Bunna Bank PM")
    r_meta.font.name = "Calibri"
    r_meta.font.size = Pt(10)
    r_meta.font.color.rgb = COLOR_MUTED

    doc.add_page_break()

    # SECTION 1
    h1 = doc.add_heading("1. Executive Summary & Core Architectural Philosophy", level=1)
    h1.runs[0].font.color.rgb = COLOR_MAROON
    
    p = doc.add_paragraph(
        "The Enterprise Project Management module for Odoo 19 is engineered to unify strategic vision with operational execution. "
        "Unlike generic project trackers, this platform strictly enforces a 6-tier corporate governance hierarchy linking national and corporate strategic sources directly to frontline sprint subtasks:"
    )
    p.runs[0].font.size = Pt(11)

    add_callout(
        doc,
        "The 6-Tier Strategic Alignment Hierarchy",
        "Strategic Source ➔ Strategic Issue ➔ Strategic Objective ➔ Strategic Initiative ➔ Project ➔ Milestone ➔ Deliverable ➔ Task ➔ Subtask\n\n"
        "In addition to the Project pipeline, the system incorporates an independent Operational (Non-Project) Task workflow for routine departmental operations, support tickets, and ad-hoc requests.",
        border_color=HEX_MAROON
    )

    # SECTION 2
    h2 = doc.add_heading("2. Security Roles, Access Permissions & Responsibilities", level=1)
    h2.runs[0].font.color.rgb = COLOR_MAROON

    p2 = doc.add_paragraph(
        "The system enforces role-based access security using four standard privilege groups defined under Settings > Users > Project Management:"
    )
    p2.runs[0].font.size = Pt(11)

    # Security Matrix Table
    role_table = doc.add_table(rows=5, cols=4)
    role_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    col_w = [Inches(1.5), Inches(1.8), Inches(2.0), Inches(1.5)]
    headers = ["Role Name", "Technical XML ID", "Scope of Authority", "Menu Access"]
    format_table_headers(role_table, col_w, headers)

    role_data = [
        ("Administrator", "group_pm_manager", "Full administrative governance, system catalogs, schemas, sequence IDs, and global settings.", "All menus: Dashboards, Initiatives, Tasks, Documentation, Reporting, Configuration."),
        ("Project Manager", "group_pm_project_manager", "End-to-end management of projects where designated as Manager, Coordinator, or Member. Full task and WBS controls.", "Dashboards, Initiatives (Projects, Milestones, Deliverables, Project Tasks), Tasks, Documentation, Reporting."),
        ("Task Manager (Assignee)", "group_pm_user", "Execution of assigned project tasks. Full management of self-owned or assigned Non-Project operational tasks.", "Dashboards, My Tasks, Non-Project Tasks, Documentation, Reporting (Task Analytics)."),
        ("Initiative Lead (Audit)", "group_pm_audit", "Executive oversight and compliance audit across all projects, initiatives, documents, test cases, and tasks.", "Dashboards, Initiatives, Tasks, Documentation, Reporting (Strict read-only across all models).")
    ]
    for idx, row_val in enumerate(role_data):
        populate_table_row(role_table.rows[idx + 1], row_val, col_w, is_even=(idx % 2 == 1))

    doc.add_paragraph().paragraph_format.space_after = Pt(16)

    # SECTION 3
    h3 = doc.add_heading("3. Step-by-Step Operational Workflows by Role", level=1)
    h3.runs[0].font.color.rgb = COLOR_MAROON

    # 3.1 Administrator
    h3_1 = doc.add_heading("3.1 Role: System Administrator (Master Configuration & Alignment)", level=2)
    h3_1.runs[0].font.color.rgb = COLOR_NAVY
    
    doc.add_paragraph(
        "Before any Project Manager can launch a project, the Administrator must establish the strategic foundation and master data catalogs."
    ).runs[0].font.size = Pt(10.5)

    doc.add_heading("Step 1: Configure Governance Catalogs", level=3)
    p = doc.add_paragraph()
    p.add_run("1. Project Sponsors: ").bold = True
    p.add_run("Go to Configuration > Project Sponsors > New. Enter Sponsor Name (e.g., 'Retail Banking Division'), Code ('RBD'), and Head of Division. Save.\n")
    p.add_run("2. Process Owners: ").bold = True
    p.add_run("Go to Configuration > Process Owners > New. Enter Name (e.g., 'Digital Operations Department'), Code ('DOD'), and Department Head. Save.\n")
    p.add_run("3. Lead Offices: ").bold = True
    p.add_run("Go to Configuration > Project Lead Offices > New. Enter Name (e.g., 'PMO Enterprise Office'), Code ('PMO'), and Office Lead. Save.")

    doc.add_heading("Step 2: Define Strategic Foundation & Initiatives", level=3)
    p = doc.add_paragraph()
    p.add_run("1. Strategic Sources: ").bold = True
    p.add_run("Go to Configuration > Strategic Sources > New. Enter Source Name (e.g., 'National Digital Financial Strategy 2025-2030'), Code, and Authority.\n")
    p.add_run("2. Strategic Issues: ").bold = True
    p.add_run("Go to Configuration > Strategic Issues > New. Select Strategic Source. Enter the Problem Statement and Theme.\n")
    p.add_run("3. Strategic Objectives: ").bold = True
    p.add_run("Go to Configuration > Strategic Objectives > New. Select Strategic Issue and Sources. Enter Corporate Objective Title.\n")
    p.add_run("4. Strategic Initiatives: ").bold = True
    p.add_run("Go to Configuration > Strategic Initiatives (or Initiatives > Initiatives) > New. Select Strategic Objectives. Notice the strategic issue and sources are auto-derived. Enter Start and End Dates. Switch to Key Performance Indicators (KPIs) tab and add targets (KPI Name, Target, Remark, Sequence).")

    add_callout(
        doc,
        "Initiative Layout & KPI Best Practice",
        "Strategic Initiatives are structured with the Description tab first, followed by Aligned Projects, and then the Key Performance Indicators (KPIs) table. Ensure all corporate KPIs have explicit quantitative targets (e.g., '99.99% Availability', '< 150ms Latency').",
        border_color=HEX_GREEN
    )

    # 3.2 Project Manager
    h3_2 = doc.add_heading("3.2 Role: Project Manager (Project Charter, WBS, Execution & Risks)", level=2)
    h3_2.runs[0].font.color.rgb = COLOR_NAVY

    doc.add_heading("Step 1: Project Charter Creation", level=3)
    p = doc.add_paragraph()
    p.add_run("1. Navigate to Initiatives > Projects > New.\n")
    p.add_run("2. Enter Project Name (e.g., 'Core API Gateway Implementation').\n")
    p.add_run("3. Select Strategic Initiative. Start Date, Objective, and Source are populated automatically.\n")
    p.add_run("4. Multi-Unit Governance: Select Project Sponsor(s), Lead Office(s), and Process Owner(s) from the tags dropdown.\n")
    p.add_run("5. Set Project Type: Choose between Internal, External, or Both using the radio buttons.\n")
    p.add_run("6. Enter Target End Date, Estimated Cost, and Staff Required. Save.")

    doc.add_heading("Step 2: Building the WBS Hierarchy (Milestones, Deliverables & Tasks)", level=3)
    p = doc.add_paragraph()
    p.add_run("1. Create Milestones: On the Milestones tab, click Add a Line. Set Title, Start Date, Deadline, and Weight (%).\n   CRITICAL RULE: The cumulative weight of all milestones in a project CANNOT exceed 100.0%.\n")
    p.add_run("2. Create Deliverables: Under Deliverables tab, click Add a Line. Select parent Milestone and assign Deliverable Weight (%).\n   CRITICAL RULE: Total deliverable weights under a milestone CANNOT exceed the parent milestone weight.\n")
    p.add_run("3. Create Project Tasks: Navigate to Initiatives > Project Tasks > New. Check 'Is Project Task = True', select Project, Milestone, Deliverable, and set Task Weight (%). Assign resources and dates.\n   CRITICAL RULE: Total task weights CANNOT exceed deliverable weight.")

    doc.add_heading("Step 3: Dependency Enforcement & Blocker Workflow", level=3)
    p = doc.add_paragraph(
        "To establish prerequisite constraints between tasks:\n"
        "1. Open the dependent task (Task B).\n"
        "2. In the 'Blocked By' field, add the predecessor task (Task A).\n"
        "3. Task B immediately displays an 'is_blocked' state with a red badge.\n"
        "4. If a team member attempts to click 'Start Work' on Task B, the system blocks them with a UserError.\n"
        "5. Once Task A is completed, the system automatically unblocks Task B without manual intervention."
    )

    doc.add_heading("Step 4: Managing Risks & Executive Progress Updates", level=3)
    p = doc.add_paragraph(
        "1. Project Risk Register: On the project form Risks tab, record identified risks. Set Probability (1-5) and Impact (1-5). "
        "The system calculates Severity = Probability * Impact. Severity >= 9 triggers Critical status.\n"
        "2. Periodic Progress Updates: Go to Reporting > Progress Updates > New. Select Project, set Health State, and document accomplishments and roadblocks."
    )

    # 3.3 Task Manager / Assignee
    h3_3 = doc.add_heading("3.3 Role: Task Manager / Assignee (Sprint Execution & Operational Tasks)", level=2)
    h3_3.runs[0].font.color.rgb = COLOR_NAVY

    doc.add_heading("Workflow A: Executing Project Tasks", level=3)
    p = doc.add_paragraph(
        "1. Open Tasks > My Tasks. Tasks assigned to you appear automatically.\n"
        "2. Open the task and view the Subtasks tab.\n"
        "3. Add subtasks with proportional weights (e.g., Step 1 = 50%, Step 2 = 50%).\n"
        "4. As you check subtasks as Done, the parent task progress automatically rolls up.\n"
        "5. Move tasks across stages: To Do -> In Progress -> In Review -> Done."
    )

    doc.add_heading("Workflow B: Managing Non-Project (Operational) Tasks", level=3)
    p = doc.add_paragraph(
        "For routine work, maintenance, support, or general tasks:\n"
        "1. Go to Tasks > Non-Project Tasks > New.\n"
        "2. Project, Milestone, and Deliverable fields are completely omitted.\n"
        "3. Task Owner: Defaults to you, but can be reassigned to any colleague.\n"
        "4. Task Type: Radio selection choosing Internal, External, or Both.\n"
        "5. Assignees: Choose team members from the entire company user pool.\n"
        "6. Subtasks operate independently with their own progress calculation."
    )

    # 3.4 Auditor / Executive
    h3_4 = doc.add_heading("3.4 Role: Initiative Lead / Auditor (Dashboards & Governance Analytics)", level=2)
    h3_4.runs[0].font.color.rgb = COLOR_NAVY

    doc.add_paragraph(
        "Executives utilize two dedicated interactive dashboards equipped with filter ribbons, KPI drilldowns, and presentation modes:"
    )

    doc.add_heading("Dashboard 1: Executive Project Dashboard (Dashboards > Project Dashboard)", level=3)
    p = doc.add_paragraph(
        "• 6-Column Filter Ribbon: Filter portfolio by Lead Office, Project Manager, Process Owner, Initiative, Project, and Task Status.\n"
        "• Row 1 Strategic KPIs: Strategic Objectives, Initiatives, Projects, Health Status (On Track / At Risk / Overdue), Milestones, Deliverables.\n"
        "• Row 2 Velocity KPIs: To Do, In Progress, In Review, Completed, Total Tasks, Blocked Tasks.\n"
        "• Charts: Tasks by Stage and Team Workload distribution.\n"
        "• Tables: Critical Risk Register, Blocked Tasks Bottlenecks, Impending Deadlines.\n"
        "• Fullscreen Presentation: Click the expand icon on any table or card to present during board meetings."
    )

    doc.add_heading("Dashboard 2: Non-Project Dashboard (Dashboards > Non-Project Dashboard)", level=3)
    p = doc.add_paragraph(
        "• Filter Ribbon: Filter by Requester, Task Owner, Task Type, Date Range, and Status.\n"
        "• KPIs: Total Tasks, Completed, Open, In Progress, Overdue, Blocked, Completion Rate %.\n"
        "• Stage Breakdown Table: Real-time share percentage of operational tasks per stage.\n"
        "• Overdue & Blocked operational backlog tables."
    )

    # SECTION 4
    h4 = doc.add_heading("4. Comprehensive Validation Errors & Troubleshooting Runbook", level=1)
    h4.runs[0].font.color.rgb = COLOR_MAROON

    err_table = doc.add_table(rows=7, cols=4)
    err_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    col_w_err = [Inches(1.4), Inches(1.8), Inches(2.0), Inches(1.6)]
    err_headers = ["Action Trigger", "Precondition Required", "System Validation Error", "Resolution Action"]
    format_table_headers(err_table, col_w_err, err_headers)

    err_data = [
        ("Save Milestone", "Total milestone weights in project <= 100.0%.", "ValidationError: Total milestone weight cannot exceed 100%! Current total: X%", "Lower the milestone weight or reduce existing milestone weights so sum <= 100%."),
        ("Save Deliverable", "Deliverable weights <= parent milestone weight.", "ValidationError: Total deliverable weights (X%) exceed Milestone weight (Y%)!", "Reduce deliverable weight so sum <= parent milestone weight."),
        ("Save Project Task", "Task weights <= parent deliverable weight.", "ValidationError: Total task weights (X%) exceed Deliverable weight (Y%)!", "Reduce task weight so sum <= deliverable weight."),
        ("Save Any Date", "End Date / Deadline >= Start Date.", "ValidationError: The Target End Date must be after or equal to the Start Date!", "Set Target End Date / Deadline on or after Start Date."),
        ("Save Work Units", "No duplicate work units in multi-selection.", "ValidationError: Duplicate Project Sponsor selection is not allowed in one place.", "Remove duplicate tags from the sponsor, lead office, or process owner field."),
        ("Start Blocked Task", "All prerequisite tasks must be in closed state.", "UserError: This task is blocked by prerequisite tasks that are not yet finished.", "Complete prerequisite predecessor tasks before starting dependent work.")
    ]
    for idx, row_val in enumerate(err_data):
        populate_table_row(err_table.rows[idx + 1], row_val, col_w_err, is_even=(idx % 2 == 1))

    doc_path = "/mnt/extra-addons/project_management/USER_MANUAL.docx"
    doc.save(doc_path)
    print(f"User Manual successfully generated: {doc_path}")


# =========================================================================
# DOCUMENT 2: TECHNICAL ARCHITECTURE & SUPPORT GUIDE
# =========================================================================
def build_technical_guide():
    print("Generating Technical Architecture Guide (.docx)...")
    doc = docx.Document()
    
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # Title
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(36)
    p_title.paragraph_format.space_after = Pt(4)
    run_title = p_title.add_run("Enterprise Project Management (Odoo 19)\nTechnical Architecture & Database Support Guide")
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(26)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_MAROON

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(24)
    run_sub = p_sub.add_run("Complete Database Schema Catalog, Mathematical Rollup Specifications, Security Domain Models & CLI Runbook")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = COLOR_OLIVE

    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(28)
    r_meta = p_meta.add_run("Module: project_management  |  Database: PostgreSQL 15+  |  Framework: Odoo 19 / OWL 2  |  Audience: DBA / Technical Support")
    r_meta.font.name = "Calibri"
    r_meta.font.size = Pt(10)
    r_meta.font.color.rgb = COLOR_MUTED

    doc.add_page_break()

    # SECTION 1
    h1 = doc.add_heading("1. Technical Architecture & Technology Stack", level=1)
    h1.runs[0].font.color.rgb = COLOR_MAROON

    p = doc.add_paragraph(
        "The project_management module is architected as a standalone Odoo 19 application without external third-party dependencies. "
        "It consists of a three-tier decoupled architecture:"
    )
    p.runs[0].font.size = Pt(11)

    add_callout(
        doc,
        "Technology Stack Overview",
        "• Backend: Python 3.10+, Odoo ORM (Odoo 19.0.2.0)\n"
        "• Database: PostgreSQL 15+ Relational Database Management System\n"
        "• Frontend: OWL 2 (Odoo Web Library), Chart.js (via web.chartjs_lib), XML Templates\n"
        "• Styling: Bunna Bank Brand Guidelines SCSS (#541718 Deep Maroon, #425727 Forest Green, #726732 Olive Gold)\n"
        "• Dependencies: base, mail, web",
        border_color=HEX_MAROON
    )

    # SECTION 2
    h2 = doc.add_heading("2. Complete PostgreSQL Database Schema Catalog", level=1)
    h2.runs[0].font.color.rgb = COLOR_MAROON

    p2 = doc.add_paragraph(
        "Below is the complete database catalog of all 24 models and Many2many relation tables implemented by the module:"
    )
    p2.runs[0].font.size = Pt(11)

    schema_table = doc.add_table(rows=25, cols=4)
    schema_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    col_w_sch = [Inches(1.8), Inches(1.8), Inches(2.0), Inches(1.2)]
    sch_headers = ["Odoo Model Name", "PostgreSQL Table Name", "Primary Columns & Constraints", "Tier"]
    format_table_headers(schema_table, col_w_sch, sch_headers)

    schema_data = [
        ("pm.strategic.source", "pm_strategic_source", "id (PK), name (varchar), code (varchar), active (bool)", "Tier 1: Strategic"),
        ("pm.strategic.issue", "pm_strategic_issue", "id (PK), name, code, strategic_source_id (FK)", "Tier 1: Strategic"),
        ("pm.strategic.objective", "pm_strategic_objective", "id (PK), name, code, strategic_issue_id (FK)", "Tier 1: Strategic"),
        ("pm.initiative", "pm_initiative", "id (PK), name, code (seq), owner_id (FK), state, progress_rate", "Tier 1: Strategic"),
        ("pm.initiative.kpi", "pm_initiative_kpi", "id (PK), initiative_id (FK), sequence, name, target, remark", "Tier 1: Strategic"),
        ("pm.project.sponsor", "pm_project_sponsor", "id (PK), name, code, head_id (FK res_users)", "Tier 2: Governance"),
        ("pm.process.owner", "pm_process_owner", "id (PK), name, code, head_id (FK res_users)", "Tier 2: Governance"),
        ("pm.lead.office", "pm_lead_office", "id (PK), name, code, head_id (FK res_users)", "Tier 2: Governance"),
        ("pm.project", "pm_project", "id (PK), name, code (seq), initiative_id (FK), manager_id (FK), coordinator_id (FK), status, health_state, progress_rate, is_health_manual", "Tier 2: Governance"),
        ("pm_project_sponsor_rel", "pm_project_sponsor_rel", "project_id (FK), sponsor_id (FK) [Composite PK]", "Tier 2: Junction"),
        ("pm_project_lead_office_rel", "pm_project_lead_office_rel", "project_id (FK), lead_office_id (FK) [Composite PK]", "Tier 2: Junction"),
        ("pm_project_process_owner_rel", "pm_project_process_owner_rel", "project_id (FK), process_owner_id (FK) [Composite PK]", "Tier 2: Junction"),
        ("pm.milestone", "pm_milestone", "id (PK), name, code (seq), project_id (FK), weight (float), state, is_state_manual (bool), progress_rate", "Tier 3: WBS"),
        ("pm.deliverable", "pm_deliverable", "id (PK), name, code (seq), project_id (FK), milestone_id (FK), weight (float), state, is_state_manual (bool), progress_rate", "Tier 3: WBS"),
        ("pm.task", "pm_task", "id (PK), name, code (seq), project_id (FK), milestone_id (FK), deliverable_id (FK), is_project_task (bool), owner_id (FK res_users), tag_type, weight, stage_id (FK), state, is_blocked (bool), is_closed (bool)", "Tier 4 & 5: Tasks"),
        ("pm_task_user_rel", "pm_task_user_rel", "task_id (FK), user_id (FK) [Composite PK]", "Tier 4: Junction"),
        ("pm_task_dependency_rel", "pm_task_dependency_rel", "task_id (FK), prerequisite_id (FK) [Composite PK]", "Tier 4: Junction"),
        ("pm.task.subtask", "pm_task_subtask", "id (PK), task_id (FK), name, weight (float), is_done (bool)", "Tier 4: Execution"),
        ("pm.task.stage", "pm_task_stage", "id (PK), name, sequence (int), is_closed (bool)", "Tier 4: Workflow"),
        ("pm.project.risk", "pm_project_risk", "id (PK), project_id (FK), name, probability, impact, severity (int), status", "Tier 6: Risks"),
        ("pm.project.progress.update", "pm_project_progress_update", "id (PK), project_id (FK), name, report_date, health_state, executive_summary", "Tier 6: Reporting"),
        ("pm.test.case.line", "pm_test_case_line", "id (PK), project_id (FK), category, name, expected_result", "Tier 7: QA Testing"),
        ("pm.test.execution", "pm_test_execution", "id (PK), project_id (FK), name, total_cases, executed_cases, pass_rate, state", "Tier 7: QA Testing"),
        ("pm.test.execution.line", "pm_test_execution_line", "id (PK), execution_id (FK), case_line_id (FK), status, result, remarks", "Tier 7: QA Testing")
    ]
    for idx, row_val in enumerate(schema_data):
        populate_table_row(schema_table.rows[idx + 1], row_val, col_w_sch, is_even=(idx % 2 == 1))

    doc.add_paragraph().paragraph_format.space_after = Pt(16)

    # SECTION 3
    h3 = doc.add_heading("3. Mathematical Rollup Engine & Calculation Logic", level=1)
    h3.runs[0].font.color.rgb = COLOR_MAROON

    doc.add_heading("3.1 Subtask to Task Progress Formula", level=2)
    p = doc.add_paragraph(
        "For any task T with n subtasks where each subtask s_i has weight w(s_i) and completion boolean delta(s_i):\n\n"
        "Progress(T) = [ Sum(w(s_i) * delta(s_i)) / Sum(w(s_i)) ] * 100%   (if total subtask weight > 0)\n"
        "Progress(T) = [ Sum(delta(s_i)) / n ] * 100%                       (if unweighted subtasks)\n"
        "Progress(T) = 100% if task stage is_closed = True and no subtasks exist."
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("3.2 Task to Deliverable Progress Formula", level=2)
    p = doc.add_paragraph(
        "For a deliverable D containing k tasks:\n\n"
        "Progress(D) = 100% if D.state = 'completed' (Manual override preserved)\n"
        "Progress(D) = [ Sum(Progress(T_j) * Weight(T_j)) / Sum(Weight(T_j)) ] (if task weights > 0)\n"
        "Progress(D) = [ Sum(Progress(T_j)) / k ]                              (if unweighted)"
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("3.3 Deliverable to Milestone Progress Formula", level=2)
    p = doc.add_paragraph(
        "For a milestone M containing m deliverables:\n\n"
        "Progress(M) = 100% if M.state = 'completed' and M.is_state_manual = True\n"
        "Progress(M) = [ Sum(Progress(D_l) * Weight(D_l)) / Sum(Weight(D_l)) ] (if deliverable weights > 0)\n"
        "Progress(M) = [ Sum(Progress(D_l)) / m ]                              (if unweighted)"
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("3.4 Milestone to Project Progress Formula", level=2)
    p = doc.add_paragraph(
        "For a project P containing p milestones:\n\n"
        "Progress(P) = [ Sum(Progress(M_h) * Weight(M_h)) / Sum(Weight(M_h)) ] (if milestone weights > 0)\n"
        "Progress(P) = [ Sum(Progress(M_h)) / p ]                              (if unweighted)"
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("3.5 Project Health Evaluation Engine", level=2)
    p = doc.add_paragraph(
        "Health state is evaluated automatically in _compute_health_state():\n"
        "• 'done': If status == 'completed' or progress_rate >= 100.0%\n"
        "• 'on_hold': If status == 'on_hold'\n"
        "• 'off_track': If date_end < today and progress_rate < 100.0%\n"
        "• 'at_risk': If (date_end - today) <= 7 days and progress_rate < 70.0%, or if any task is_blocked = True\n"
        "• 'on_track': Default when deadlines and progress velocity are healthy.\n"
        "• Manual Override: If PM manually sets health, is_health_manual is set True to freeze state until project completion."
    )

    # SECTION 4
    h4 = doc.add_heading("4. Security Record Rules & Domain Filter Models", level=1)
    h4.runs[0].font.color.rgb = COLOR_MAROON

    doc.add_paragraph(
        "The security model enforces row-level data isolation using ir.rule record rules in security/record_rules.xml:"
    )

    add_callout(
        doc,
        "Record Rule Domain Logic Specifications",
        "1. Assignee Project Read Rule (rule_pm_project_assignee_read):\n"
        "   ['|', '|', ('member_ids', 'in', [user.id]), ('manager_id', '=', user.id), ('coordinator_id', '=', user.id)]\n\n"
        "2. Assignee Task Rule (rule_pm_task_assignee):\n"
        "   ['|', '|', '|', ('user_ids', 'in', [user.id]), ('owner_id', '=', user.id), ('create_uid', '=', user.id), ('project_id.member_ids', 'in', [user.id])]\n\n"
        "3. Project Manager Project Rule (rule_pm_project_manager_own):\n"
        "   ['|', '|', '|', ('manager_id', '=', user.id), ('coordinator_id', '=', user.id), ('member_ids', 'in', [user.id]), ('create_uid', '=', user.id)]\n\n"
        "4. Project Manager Task Rule (rule_pm_task_pm_own):\n"
        "   ['|', '|', '|', '|', ('project_id.manager_id', '=', user.id), ('project_id.coordinator_id', '=', user.id), ('user_ids', 'in', [user.id]), ('owner_id', '=', user.id), ('create_uid', '=', user.id)]",
        border_color=HEX_NAVY
    )

    # SECTION 5
    h5 = doc.add_heading("5. Production Operations, CLI Commands & Troubleshooting", level=1)
    h5.runs[0].font.color.rgb = COLOR_MAROON

    doc.add_heading("5.1 Module Upgrades via Docker CLI", level=2)
    p = doc.add_paragraph(
        "To upgrade the module schema, XML views, and assets after code modifications:\n"
        "docker exec odoo19-pm-web odoo -u project_management -d pm_db --stop-after-init"
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("5.2 Running the 33-Scenario Automated Production Test Suite", level=2)
    p = doc.add_paragraph(
        "To verify database schema, security rules, and calculations across all 8 tiers:\n"
        "docker exec odoo19-pm-web python3 /mnt/extra-addons/project_management/test_production_suite.py"
    )
    p.runs[0].font.name = "Consolas"
    p.runs[0].font.size = Pt(9.5)

    doc.add_heading("5.3 Common Support Issues & Root Cause Resolutions", level=2)
    p = doc.add_paragraph(
        "1. Milestone State Reverting to Planned on Save:\n"
        "   Root Cause: Compute method recalculation overwriting manual status.\n"
        "   Fix: The system sets is_state_manual = True whenever state is changed via statusbar or manual write. Ensure is_state_manual is True.\n\n"
        "2. Automated Tests Failing with Duplicate Rows:\n"
        "   Root Cause: ValidationError swallowed without rolling back postgres cursor.\n"
        "   Fix: Wrap negative tests in 'with self.env.cr.savepoint():' so PostgreSQL immediately aborts the invalid insert.\n\n"
        "3. Circular Task Dependency:\n"
        "   Root Cause: Task A set as prerequisite of Task B, and Task B set as prerequisite of Task A.\n"
        "   Fix: Open Task B form and remove Task A from 'Blocked By' table."
    )

    doc_path = "/mnt/extra-addons/project_management/TECHNICAL_GUIDE.docx"
    doc.save(doc_path)
    print(f"Technical Architecture Guide successfully generated: {doc_path}")


if __name__ == "__main__":
    build_user_manual()
    build_technical_guide()
