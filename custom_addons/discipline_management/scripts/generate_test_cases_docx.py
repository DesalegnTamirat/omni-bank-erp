# -*- coding: utf-8 -*-
"""
Generates a richly formatted Microsoft Word (.docx) Comprehensive Test Case & End-to-End Verification Guide
for the Bunna Bank ERP Discipline Management System (Odoo 19).
Uses standard OpenXML (zipfile + XML) so it runs with zero external dependencies.
"""
import os
import zipfile
from xml.sax.saxutils import escape


def _w_p(text="", style=None, bold=False, color=None, size_pt=11, space_after=120):
    pPr = []
    if style:
        pPr.append(f'<w:pStyle w:val="{style}"/>')
    pPr.append(f'<w:spacing w:after="{space_after}"/>')
    pPr_xml = f"<w:pPr>{''.join(pPr)}</w:pPr>" if pPr else ""

    rPr = []
    if bold:
        rPr.append("<w:b/>")
    if color:
        rPr.append(f'<w:color w:val="{color}"/>')
    if size_pt:
        val = int(size_pt * 2)
        rPr.append(f'<w:sz w:val="{val}"/><w:szCs w:val="{val}"/>')
    rPr_xml = f"<w:rPr>{''.join(rPr)}</w:rPr>" if rPr else ""

    lines = str(text).split("\n")
    runs = []
    for idx, line in enumerate(lines):
        if idx > 0:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(f'<w:r>{rPr_xml}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>')
    return f"<w:p>{pPr_xml}{''.join(runs)}</w:p>"


def _w_table(headers, rows, col_widths=None):
    if not col_widths:
        col_widths = [1400, 2200, 1800, 2800, 2800]
    tblPr = """
    <w:tblPr>
        <w:tblW w:w="5000" w:type="pct"/>
        <w:tblBorders>
            <w:top w:val="single" w:sz="6" w:space="0" w:color="8B0000"/>
            <w:left w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>
            <w:bottom w:val="single" w:sz="6" w:space="0" w:color="8B0000"/>
            <w:right w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>
            <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E0E0E0"/>
            <w:insideV w:val="single" w:sz="4" w:space="0" w:color="E0E0E0"/>
        </w:tblBorders>
    </w:tblPr>
    """
    tr_list = []
    # Header row
    h_cells = []
    for i, h in enumerate(headers):
        w = col_widths[i] if i < len(col_widths) else 2000
        h_cells.append(f"""
        <w:tc>
            <w:tcPr>
                <w:tcW w:w="{w}" w:type="dxa"/>
                <w:shd w:val="clear" w:color="auto" w:fill="5C1018"/>
            </w:tcPr>
            {_w_p(h, bold=True, color="FFFFFF", size_pt=10, space_after=60)}
        </w:tc>
        """)
    tr_list.append(f"<w:tr>{''.join(h_cells)}</w:tr>")

    # Data rows
    for r_idx, row in enumerate(rows):
        fill = "F9F5F6" if r_idx % 2 == 1 else "FFFFFF"
        d_cells = []
        for i, cell_val in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 2000
            is_id_col = (i == 0)
            d_cells.append(f"""
            <w:tc>
                <w:tcPr>
                    <w:tcW w:w="{w}" w:type="dxa"/>
                    <w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>
                </w:tcPr>
                {_w_p(cell_val, bold=is_id_col, color="5C1018" if is_id_col else "222222", size_pt=9.5, space_after=60)}
            </w:tc>
            """)
        tr_list.append(f"<w:tr>{''.join(d_cells)}</w:tr>")

    return f"<w:tbl>{tblPr}{''.join(tr_list)}</w:tbl>"


SECTIONS = [
    {
        "title": "1. Access Groups, Organizational Hierarchy & Dynamic Role Segregation",
        "overview": (
            "The Discipline Management System uses 7 core security groups: User / Employee (default for all staff, "
            "line managers, directors, deputy chiefs, and chiefs), Internal Audit Directorate, Legal Directorate, "
            "POMD (Committee Secretary), CPCO (Committee Chairperson), CEO, and HR Administrator. "
            "Within the 'User / Employee' group, managerial authority (Coach -> Director -> Deputy Chief -> Chief -> CEO) "
            "is dynamically resolved via the employee's coaching/reporting chain (`coach_id` / `parent_id`)."
        ),
        "cases": [
            (
                "TC-SEC-01",
                "Normal Employee Access & Isolation",
                "User / Employee (Non-Managerial, e.g., Abeza)",
                "1. Log in as a normal employee.\n2. Open Discipline -> Discipline Operations -> Disciplinary Cases.\n3. Attempt to view another peer employee's disciplinary case.",
                "- Employee sees ONLY their own disciplinary cases and attendance cases.\n- Cannot view peer employees' cases.\n- Cannot initiate Formal Committee Escalation cases."
            ),
            (
                "TC-SEC-02",
                "Direct Coach / Line Manager Hierarchy Access",
                "User / Employee (Coach of Employee, e.g., Eyob)",
                "1. Log in as Direct Coach (Eyob).\n2. Open Disciplinary Cases -> Click New.\n3. Open Subject Employee dropdown.",
                "- Coach sees their direct and indirect subordinates in the Subject Employee dropdown.\n- Cannot select themselves as Subject Employee.\n- Can initiate and directly enforce minor/moderate cases (Levels 2–5) for subordinates."
            ),
            (
                "TC-SEC-03",
                "Director / Deputy Chief / Chief Multi-Tier Hierarchy Access",
                "User / Employee (Coach of Coach / Director / Chief, e.g., Derese)",
                "1. Log in as Director / Chief (Derese, who is Coach of Eyob).\n2. Navigate to Disciplinary Cases and Appeals & Reviews.",
                "- Can view cases initiated/enforced by subordinate managers (Eyob) for second-line employees (Abeza).\n- Can access and decide 1st/2nd Level Appeals routed to them without any AccessError on hr.employee."
            ),
            (
                "TC-SEC-04",
                "Governance Roles (POMD, CPCO, CEO, Auditor, Legal, Admin)",
                "POMD / CPCO / CEO / Auditor / Legal / HR Admin",
                "1. Log in with each governance group.\n2. Check menu visibility and record access across Cases, Investigations, Committee Meetings, Suspensions, and Payroll Deductions.",
                "- Only POMD, CPCO, and Admin see 'Suspensions' and 'Payroll Deductions' menus.\n- Investigations and Committee Meetings menus are restricted and stage-gated by workflow."
            ),
        ],
    },
    {
        "title": "2. Case Initiation Form, Operating Unit & Employment Category Detection",
        "overview": (
            "Verifies the enhanced Case Initiation form fields: Subject Employee, Reporting Manager / Initiator, "
            "Operating Unit (before Department), Department, Job Position, and Employment Category "
            "('Managerial' vs 'Non-Managerial', blank before employee selection)."
        ),
        "cases": [
            (
                "TC-INIT-01",
                "Blank Employment Category Before Employee Selection",
                "Direct Coach / Initiator",
                "1. Go to Discipline -> Discipline Operations -> Disciplinary Cases -> Click New.\n2. Observe 'Operating Unit', 'Department', 'Job Position', and 'Employment Category' before selecting a Subject Employee.",
                "- 'Employment Category' is completely BLANK (empty) before selecting a Subject Employee.\n- 'Work Location' field is removed.\n- 'Operating Unit' appears immediately above 'Department'."
            ),
            (
                "TC-INIT-02",
                "Non-Managerial Employee Category & Percentage Penalty Mode",
                "Direct Coach / Initiator",
                "1. Select a Non-Managerial employee (e.g., Senior Officer or Relationship Manager with hr.job.employee_category = 'Non Managerial').\n2. Select a Level 4 / Level 3 / Level 2 offense.",
                "- 'Employment Category' displays 'Non-Managerial' (without the word 'Staff').\n- 'Salary Deduction Rate (%)' is displayed (5%, 10%, or 20%).\n- 'Salary Fine (Days)' is hidden."
            ),
            (
                "TC-INIT-03",
                "Managerial Employee Category & Day-Fine Penalty Mode",
                "Director / Chief / Initiator",
                "1. Select a Managerial employee (hr.job.employee_category = 'Managerial' or Division Manager / Director).\n2. Select a Level 4 / Level 3 / Level 2 offense.",
                "- 'Employment Category' displays 'Managerial' (without the word 'Staff').\n- 'Salary Fine (Days)' is displayed (1, 2, or 3 days).\n- 'Salary Deduction Rate (%)' is hidden."
            ),
        ],
    },
    {
        "title": "3. Direct Enforcement Track (Coach Initiation -> Statutory Mitigation -> Enforcement)",
        "overview": (
            "Covers minor/moderate misconduct (Severity Levels 2–5) handled directly by the Direct Coach / Line Manager "
            "under 'Direct Action (Coach / Minor Misconduct)'."
        ),
        "cases": [
            (
                "TC-DIR-01",
                "Direct Case Initiation & Employee Notification",
                "Direct Coach (Eyob)",
                "1. Create a new case for subordinate (Abeza) with Action Pathway = 'Direct Action'.\n2. Select a Level 4 offense, enter Incident Description, and click 'Initiate Case'.",
                "- Case state changes from 'Draft' to 'Initiated'.\n- Case Reference (DISC/YYYY/XXXX) is generated.\n- Subject employee receives an instant Odoo Discuss Direct Message and Chatter notification."
            ),
            (
                "TC-DIR-02",
                "Statutory Mitigation (-1 Grade Step-Down per Art. 33.13)",
                "Direct Coach (Eyob)",
                "1. On an Initiated Level 3 (Second Warning + 10%) case, check 'Apply Statutory Mitigation (-1 Grade)'.\n2. Attempt to save without Mitigation Justification.\n3. Enter Mitigation Justification and observe Prescribed Measure.",
                "- System requires 'Mitigation Grounds & Justification' when mitigation is checked.\n- Prescribed Disciplinary Measure steps down by 1 rank (e.g., Second Warning 10% -> First Warning 5%)."
            ),
            (
                "TC-DIR-03",
                "Direct Coach Approval & Enforcement + Warning Letter PDF",
                "Direct Coach (Eyob)",
                "1. Click 'Approve & Enforce Decision' on the initiated case.\n2. Click 'Print Warning Letter'.",
                "- Case state transitions to 'Enforced'.\n- Employee warning count increments by 1; active validity countdown starts.\n- Payroll penalty record (PEN/YYYY/XXXX) is immediately created in 'Pending Transmission' for the current month.\n- Official Warning Letter PDF downloads with Bunna Bank logo, salutation, legal citation, and CC lines."
            ),
            (
                "TC-DIR-04",
                "Coach Authority Limit Guardrail (Blocking Level 1 Dismissal on Direct Track)",
                "Direct Coach (Eyob)",
                "1. Attempt to enforce a Level 1 (Dismissal) or Demotion sanction under the 'Direct Action' track.",
                "- System blocks enforcement with a UserError instructing the Coach to switch to 'Formal Escalation' and route to the Respective Chief / Committee."
            ),
        ],
    },
    {
        "title": "4. Formal Escalation Track (Initiator -> Director -> Respective Chief -> Audit / CEO)",
        "overview": (
            "Covers major misconduct (Level 1 Dismissal, Demotion, or complex cases) escalated through the executive hierarchy."
        ),
        "cases": [
            (
                "TC-ESC-01",
                "Submit Initiated Case to Respective Chief",
                "Initiator / Coach / Director",
                "1. Initiate a case with Action Pathway = 'Formal Escalation'.\n2. Click 'Submit to Respective Chief'.",
                "- System automatically resolves the employee's Respective Chief (`chief_id`).\n- State transitions to 'Submitted to Respective Chief' (`submitted_chief`).\n- Respective Chief receives an Odoo Discuss Direct Message and Chatter notification."
            ),
            (
                "TC-ESC-02",
                "Respective Chief Option A: Exonerate & Close Case",
                "Respective Chief Officer",
                "1. Log in as the Respective Chief.\n2. Open the case in `submitted_chief` state.\n3. Enter Chief Review Notes and click 'Exonerate & Close Case'.",
                "- Case state transitions immediately to 'Closed' (`punishment_type = 'exonerate'`, 0% penalty).\n- Employee receives an Odoo Discuss DM confirming official exoneration.\n- 'Print Exoneration Certificate' button becomes available."
            ),
            (
                "TC-ESC-03",
                "Respective Chief Option B: Escalate to Audit Directorate",
                "Respective Chief Officer",
                "1. Open a case in `submitted_chief` state.\n2. Click 'Escalate to Audit for Investigation'.",
                "- Case state transitions to 'Under Investigation' (`investigating`).\n- A linked `discipline.investigation` record (INV/YYYY/XXXX) is automatically created in 'Draft' state.\n- Both Audit Director and CEO receive Odoo Discuss Direct Messages."
            ),
            (
                "TC-ESC-04",
                "Respective Chief Option C: Escalate Directly to CEO",
                "Respective Chief Officer",
                "1. Open a case in `submitted_chief` state.\n2. Click 'Escalate to CEO'.\n3. Log in as CEO and click 'Announce to Audit & Instruct Suspension'.",
                "- Case moves to `ceo_review`, then `investigating`.\n- CEO directive automatically creates both the `discipline.investigation` record for Audit AND a `discipline.suspension` draft record for POMD.\n- Audit Director, POMD Secretary, and CPCO receive Discuss DMs."
            ),
        ],
    },
    {
        "title": "5. Audit Investigation Workflow & Stage-Gated Confidentiality (Auditor -> CEO -> CPCO -> POMD)",
        "overview": (
            "Verifies the strict workflow-gated visibility of Audit Investigations: "
            "Auditor sends ONLY to CEO (`submitted_ceo`) -> CEO forwards to CPCO (`forwarded_cpco`) -> CPCO forwards to POMD (`approved`). "
            "Subject Employee and Line Managers NEVER see the investigation report."
        ),
        "cases": [
            (
                "TC-INV-01",
                "Investigation Confidentiality During Draft & In-Progress (`draft`, `in_progress`)",
                "Auditor vs. CEO / CPCO / POMD / Employee / Manager",
                "1. Log in as Internal Auditor, open the Investigation (INV/YYYY/XXXX), click 'Begin Investigation', and enter findings.\n2. While state is `in_progress`, log in as Subject Employee, Coach, POMD, CPCO, and CEO.",
                "- Auditor & HR Admin: Full access.\n- Subject Employee, Coach, POMD, CPCO, CEO: Cannot see the unsubmitted investigation record; 'Investigations' smart button & tab are hidden."
            ),
            (
                "TC-INV-02",
                "Auditor Submits Investigation to CEO (`submitted_ceo`)",
                "Internal Auditor -> CEO vs. CPCO / POMD / Employee",
                "1. As Internal Auditor, fill Summary of Findings and Investigator Recommendation, then click 'Submit Report to CEO'.\n2. Check visibility as CEO, CPCO, POMD, and Subject Employee.",
                "- Investigation state becomes `submitted_ceo`; Case state transitions to `ceo_review`.\n- CEO can now view the Investigation report and smart button.\n- CPCO, POMD, Coach, and Subject Employee STILL CANNOT see the investigation report (`Access Denied` / hidden)."
            ),
            (
                "TC-INV-03",
                "CEO Forwards Case & Investigation to Committee Chair / CPCO (`forwarded_cpco`)",
                "CEO -> CPCO vs. POMD / Employee",
                "1. Log in as CEO on the case in `ceo_review`.\n2. Click 'Forward to Committee Chair (CPCO)'.\n3. Check visibility as CPCO, POMD, and Subject Employee.",
                "- Case state becomes `chairman_review`; Investigation state automatically transitions to `forwarded_cpco`.\n- CPCO now gains access to view the Investigation report.\n- POMD, Coach, and Subject Employee STILL CANNOT see the investigation report."
            ),
            (
                "TC-INV-04",
                "CPCO Refers Case & Investigation to Committee Secretary / POMD (`approved`)",
                "CPCO -> POMD & Committee Panel vs. Subject Employee",
                "1. Log in as CPCO on the case in `chairman_review`.\n2. Click 'Forward to Secretary (POMD) for Hearing'.\n3. Check visibility as POMD, Legal/Panel Members, and Subject Employee.",
                "- Case state becomes `committee_review`; Investigation state transitions to `approved`.\n- POMD, Legal, and designated Committee Panel Members now have access to the Investigation report.\n- Subject Employee and non-panel Line Managers NEVER see the investigation report at any stage."
            ),
        ],
    },
    {
        "title": "6. Precautionary Suspension Management (With/Without Pay, Attendance Block & Reinstatement)",
        "overview": (
            "Verifies employee suspension up to 30 working days, biometric/attendance blocking during unpaid suspension, "
            "and automatic reinstatement/backpay upon exoneration or non-dismissal verdict."
        ),
        "cases": [
            (
                "TC-SUSP-01",
                "Activate Precautionary Suspension & Block Unpaid Attendance",
                "POMD / CPCO",
                "1. Open the Suspension record (SUSP/YYYY/XXXX) with type = 'Without Pay'.\n2. Submit and Approve/Activate the suspension.\n3. Attempt to create an `hr.attendance` check-in for the suspended employee.",
                "- Employee profile is flagged `is_suspended = True`.\n- Creating an attendance check-in raises a ValidationError blocking attendance during active Without-Pay suspension."
            ),
            (
                "TC-SUSP-02",
                "Auto-Reinstatement When Final Verdict Is Warning / Demotion / Exoneration",
                "CEO / CPCO",
                "1. Enforce a non-dismissal decision (e.g., Final Warning or Exoneration) on a case with an active suspension.",
                "- Active suspension automatically transitions to Reinstated/Revoked.\n- Unpaid suspension payroll deductions are waived unless the final decision is Dismissal."
            ),
        ],
    },
    {
        "title": "7. Disciplinary Committee Hearing, Verdict Confidentiality & CEO Final Enforcement",
        "overview": (
            "Verifies committee scheduling by POMD, 5-member panel quorum, confidentiality of the committee's verdict before enforcement, "
            "and exclusive enforcement by the CEO."
        ),
        "cases": [
            (
                "TC-COM-01",
                "Schedule Committee Hearing & Pre-Populate 5-Member Panel",
                "Committee Secretary (POMD)",
                "1. Log in as POMD on a case in `committee_review`.\n2. Click 'Schedule Committee Meeting'.",
                "- Opens Committee Meeting form (DCM/YYYY/XXXX) pre-populated with: Chairperson (CPCO), Respective Director, Legal Representative, Secretary (POMD), and Labour Union Representative."
            ),
            (
                "TC-COM-02",
                "Quorum Validation, Complete Hearing & Submit Decision to CEO",
                "Committee Secretary (POMD) / CPCO",
                "1. Convene the meeting, record attendance (at least 50%+1 quorum), enter Minutes and Final Recommendation (e.g., Final Warning or Dismissal), and click 'Complete Meeting'.\n2. On the Case, click 'Submit Committee Decision for Approval'.",
                "- Case state transitions to `pending_approval`.\n- `decided_punishment_type` is populated from the Committee's recommendation."
            ),
            (
                "TC-COM-03",
                "Committee Verdict Confidentiality Before CEO Enforcement",
                "Subject Employee / Initiator Coach vs. CEO / CPCO / POMD",
                "1. While the case is in `committee_review` or `pending_approval` (before CEO enforces), log in as the Subject Employee or non-panel Initiator Coach and open the case.",
                "- The Committee Deliberation & Verdict tab, Committee Meetings smart button, and Prescribed/Decided Punishment fields are HIDDEN from the Subject Employee and non-panel Coach until the CEO enforces the case."
            ),
            (
                "TC-COM-04",
                "CEO Exclusive Enforcement of Committee Decision",
                "POMD / CPCO vs. CEO",
                "1. Attempt to click 'Approve & Enforce' as POMD or Coach -> Verify blocked.\n2. Log in as CEO and click 'Approve & Enforce Decision'.",
                "- Only the CEO (or HR Admin) sees and can execute 'Approve & Enforce Decision' on committee-escalated cases.\n- Upon CEO enforcement, case becomes `enforced`, payroll deduction is scheduled immediately, and the employee now sees the final enforced decision and receives a Discuss DM."
            ),
        ],
    },
    {
        "title": "8. Immediate Payroll Deduction (No Day-15 Cutoff / No Appeal Freeze) & Next-Period Appeal Reimbursement",
        "overview": (
            "Verifies that financial penalties are scheduled immediately for the current month's payroll run (typically on the 23rd, "
            "even if enforced on the 22nd, regardless of open appeal windows), and that any appeal reduction/exoneration after payroll deduction "
            "automatically generates a Reimbursement (`transaction_type = 'refund'`) for the next payroll period."
        ),
        "cases": [
            (
                "TC-PAY-01",
                "Immediate Payroll Deduction Scheduling Even on Day 22 While Appeal Window Is Open",
                "Direct Coach / CEO -> POMD",
                "1. Enforce a case with a 10% or 20% salary penalty (or managerial day fine) on the 22nd of the month.\n2. Open Discipline -> Discipline Operations -> Payroll Deductions.",
                "- Case `deduction_status` is immediately set to `'scheduled'` (never frozen in `appeal_pending`).\n- `discipline.payroll.penalty` record is created immediately with `payroll_month` = current month and `state = 'pending'`.\n- Calling `get_pending_penalties()` returns the deduction immediately for the 23rd payroll run even while the 10-day appeal window is open."
            ),
            (
                "TC-PAY-02",
                "Pre-Payroll Appeal Reduction (Penalty Still `pending`)",
                "Appeal Reviewer (Director / Chief / CEO)",
                "1. Before payroll runs (penalty is still `pending`), employee submits an appeal and the reviewer reduces the penalty from 20% to 5% (or overturns to Exonerated).",
                "- Because the penalty has not yet been deducted in a payslip, the existing `pending` payroll penalty record is updated in-place to 5% (or cancelled if exonerated)."
            ),
            (
                "TC-PAY-03",
                "Post-Payroll Appeal Reduction -> Automatic Next-Period Reimbursement (`refund`)",
                "POMD -> Appeal Reviewer",
                "1. On a 20% penalty (e.g., Basic Salary 20,000 ETB -> 4,000 ETB deducted), click 'Transmit to Payroll' and 'Mark as Deducted' (enter Payslip Ref).\n2. Decide the employee's appeal with outcome = 'Penalty Reduced' (revised to 5% = 1,000 ETB).",
                "- Original deducted penalty record (4,000 ETB) remains intact as `deducted` for audit history.\n- System automatically creates a new `discipline.payroll.penalty` record with `transaction_type = 'refund'`, `penalty_type = 'reimbursement'`, `refund_amount = 3,000 ETB` (the exact decreased difference), scheduled for the NEXT payroll month.\n- Case `deduction_status` updates to `'refund_scheduled'` (`signed_amount = -3000.0` in payroll payload)."
            ),
            (
                "TC-PAY-04",
                "Post-Payroll Appeal Overturned (Exonerated) -> 100% Full Reimbursement",
                "Appeal Reviewer",
                "1. After a 4,000 ETB penalty is marked `deducted`, decide the appeal with outcome = 'Overturned / Exonerated'.",
                "- System automatically creates a Reimbursement (`transaction_type = 'refund'`) for the full 4,000 ETB in the next payroll month."
            ),
        ],
    },
    {
        "title": "9. Multi-Tier Appeals (1st, 2nd, 3rd Level) & POMD On-Behalf Dismissal Appeals",
        "overview": (
            "Verifies dynamic appeal routing up the enforcer's coaching hierarchy and POMD's authority to lodge appeals on behalf of dismissed employees."
        ),
        "cases": [
            (
                "TC-APP-01",
                "1st Level Appeal Routed to Enforcer's Coach (e.g., Abeza -> Eyob -> Derese)",
                "Employee (Abeza) -> Enforcer's Coach (Derese)",
                "1. Eyob (Coach of Abeza) enforces a warning on Abeza.\n2. Log in as Abeza and click 'Submit Appeal' within the 10-day window.\n3. Log in as Derese (Coach of Eyob) and open the appeal.",
                "- `designated_reviewer_id` is automatically set to Derese (Eyob's coach).\n- Derese can open the appeal, view Abeza's employee/case details without any AccessError, and record the 1st Level Appeal decision."
            ),
            (
                "TC-APP-02",
                "2nd & 3rd Level Appeal Escalation Up to CEO",
                "Employee -> Chief / CPCO -> CEO",
                "1. After 1st Level Appeal is Upheld by Director, employee clicks 'Submit 2nd Level Appeal' (routes to Chief / CPCO).\n2. After 2nd Level Appeal is Upheld, employee clicks 'Submit 3rd Level Appeal (To CEO)'.",
                "- 2nd Level Appeal routes to the next higher executive (Chief / CPCO).\n- 3rd Level Appeal routes to the CEO, whose decision is final and exhausts further appeal buttons."
            ),
            (
                "TC-APP-03",
                "POMD Lodges Appeal on Behalf of Dismissed Employee",
                "POMD Director",
                "1. Enforce a Level 1 Dismissal case (which deactivates the employee's user login).\n2. Log in as POMD and click 'Lodge Appeal (On Behalf)' on the enforced dismissal case.",
                "- POMD can lodge 1st, 2nd, and 3rd Level Appeals on behalf of the dismissed employee (`is_submitted_on_behalf = True`)."
            ),
        ],
    },
    {
        "title": "10. Repeated Disciplinary Cases & Cash Shortage Matrix (Article 33.9 & Article 33.1.4)",
        "overview": (
            "Verifies automatic occurrence counting (`occurrence_count`) within active warning validity periods and "
            "the statutory Cash Shortage Matrix across ETB brackets and recurrence tiers."
        ),
        "cases": [
            (
                "TC-CSH-01",
                "Cash Shortage Up to 500 ETB Across 1st, 2nd, 3rd & 4th Occurrences",
                "Direct Coach / Initiator",
                "1. Select a Cash Shortage offense (`CSH` / Art. 33.9) and enter `Cash Shortage Discrepancy (ETB) = 400`.\n2. Verify sanctions for 1st, 2nd, 3rd, and 4th active occurrences.",
                "- 1st Occurrence: Verbal Warning (0%)\n- 2nd Occurrence: 1st Warning (0%)\n- 3rd Occurrence: 2nd Warning (10%)\n- 4th+ Occurrence: Final Warning (20%)"
            ),
            (
                "TC-CSH-02",
                "Cash Shortage 501 – 5,000 ETB Across Occurrences",
                "Direct Coach / Initiator",
                "1. Enter `Cash Shortage Discrepancy (ETB) = 3,500` across 1st, 2nd/3rd, and 4th occurrences.",
                "- 1st Occurrence: 1st Warning (0%)\n- 2nd & 3rd Occurrences: 2nd Warning (10%)\n- 4th+ Occurrence: Final Warning (20%)"
            ),
            (
                "TC-CSH-03",
                "Cash Shortage 5,001 – 10,000 ETB Reaching Demotion on 3rd Occurrence",
                "Direct Coach -> Committee Escalation",
                "1. Enter `Cash Shortage Discrepancy (ETB) = 8,000` across 1st, 2nd, and 3rd occurrences.",
                "- 1st Occurrence: 2nd Warning (10%)\n- 2nd Occurrence: Final Warning (20%)\n- 3rd+ Occurrence: Demotion (requires Formal Escalation)"
            ),
            (
                "TC-CSH-04",
                "Cash Shortage 10,001 – 20,000 ETB & > 20,000 ETB Reaching Dismissal",
                "Initiator -> Committee Escalation -> CEO",
                "1. Test 15,000 ETB (1st, 2nd, 3rd occurrence) and 25,000 ETB (1st, 2nd occurrence).",
                "- 10,001–20,000 ETB: 1st = 2nd Warning (10%), 2nd = Final Warning (20%), 3rd = Dismissal.\n- > 20,000 ETB: 1st = Final Warning (20%), 2nd = Dismissal."
            ),
        ],
    },
    {
        "title": "11. Dedicated Attendance Disciplinary Cases (`discipline.attendance.case`), Shift-Aware Sunday Logic & Leave Conversion",
        "overview": (
            "Verifies the dedicated Attendance Cases module (`Discipline -> Discipline Operations -> Attendance Cases`), "
            "nightly cron execution at 01:30 AM, shift-aware Sunday working day calculation, Direct Coach enforcement/leave-adjustment/exoneration, "
            "individual & batch HR refusal, and the streamlined Director -> POMD workflow for >= 5 consecutive days dismissal absences."
        ),
        "cases": [
            (
                "TC-ATT-01",
                "Nightly Cron Configuration at 01:30 AM",
                "HR Administrator",
                "1. Go to Settings -> Technical -> Automation -> Scheduled Actions.\n2. Locate 'Discipline Management: Nightly Attendance & Absence Violation Scan'.",
                "- Cron is active, runs daily (`1 Days`), calls `model._cron_escalate_attendance_violations()`, and is scheduled at 01:30 AM off-peak night time."
            ),
            (
                "TC-ATT-02",
                "Shift-Aware Sunday Working Day & Weekday Rest-Day Calculation",
                "HR Admin / Coach",
                "1. Configure Employee A on a standard Mon–Sat schedule (absent Fri, Sat, Mon).\n2. Configure Employee B as a Shift Worker scheduled to work on Sunday (`my.shift.schedule.line` / `job.position.roster.exception.line` or Sunday in `resource.calendar`), and absent on Sunday.\n3. Run 'Scan Attendance Violations'.",
                "- Employee A: Sunday is skipped as rest day; Fri -> Sat -> Mon counts as 3 consecutive working days (`Standard Mon–Sat Working Schedule`).\n- Employee B: Sunday is counted as a required working day (`Shift Schedule (Sunday Working Shift Included)`), so missing Sunday increments absent/consecutive working days accurately."
            ),
            (
                "TC-ATT-03",
                "Minor / Prolonged Attendance Case -> Direct Coach Enforce, Adjust by Leave, or Exonerate",
                "Direct Coach",
                "1. Open a generated Attendance Case (`ATT-DISC/YYYY/XXXX`) in `Pending Coach Action` (`coach_review`).\n2. Test all 3 Coach buttons:\n   a) 'Adjust / Convert Absence to Leave'\n   b) 'Acknowledge / Exonerate' (with justification)\n   c) 'Enforce Penalty (Coach)'",
                "- Adjust by Leave: Links/creates `hr.leave` and closes case as `Adjusted by Leave` (0 penalty).\n- Acknowledge / Exonerate: Requires justification reason and closes case as `Exonerated` (0 penalty).\n- Enforce Penalty: Sets state to `Enforced` and immediately schedules `discipline.payroll.penalty`."
            ),
            (
                "TC-ATT-04",
                "HR / POMD Individual & Batch Refusal of Attendance Cases",
                "POMD / HR Admin",
                "1. Open an Attendance Case form and click 'Refuse Case (HR)' -> Enter reason.\n2. In the Attendance Cases list view, select multiple cases, click 'Batch Refuse (HR)' (or Actions -> Batch Refuse Attendance Cases (HR)), and enter a batch refusal reason.",
                "- All selected attendance cases transition to `Refused by HR` (`hr_refused`).\n- Any pending/scheduled payroll penalty lines linked to those cases are automatically cancelled."
            ),
            (
                "TC-ATT-05",
                "Dismissal Absence (>= 5 Consecutive Working Days): Director Notification -> Pre-Enforcement Leave Conversion -> POMD Enforcement",
                "Director -> Employee -> POMD",
                "1. Scan an employee with >= 5 consecutive unexcused working days.\n2. Verify case starts in `Pending Director Review (≥5 Days)` (`director_review`) and Director is notified.\n3. Scenario A (Leave Conversion Before Enforcement): Employee or Coach clicks 'Adjust / Convert Absence to Leave' and covers the days with leave.\n4. Scenario B (Unexcused Dismissal): Director clicks 'Send to POMD for Dismissal Enforcement' (`pomd_review`), and POMD clicks 'Enforce Dismissal & Separation (POMD)'.",
                "- Scenario A: Covering all days with leave before POMD enforces automatically closes the case as `Adjusted by Leave` (or downgrades to `coach_review` if consecutive unexcused days drop below 5).\n- Scenario B: Director forwards to POMD (`pomd_review`), and POMD enforces dismissal (`enforced`), archiving the employee and deactivating system login."
            ),
        ],
    },
]


def build_docx(output_path):
    body_parts = []
    # Title Block
    body_parts.append(_w_p("BUNNA BANK S.C. — ERP HUMAN CAPITAL MANAGEMENT", bold=True, color="8B0000", size_pt=11, space_after=40))
    body_parts.append(_w_p("Discipline & Attendance Management System — Comprehensive End-to-End Test Case Specification", bold=True, color="5C1018", size_pt=16, space_after=80))
    body_parts.append(_w_p(
        "Document Purpose: Complete functional verification checklist covering all workflows, access groups, "
        "direct enforcement, committee & audit investigations, confidentiality gates, immediate payroll deductions & "
        "next-period appeal refunds, cash shortage recurrence matrices, and shift-aware attendance disciplinary cases.",
        color="444444", size_pt=10, space_after=200
    ))

    headers = ["Test ID", "Test Scenario", "Actor / Role", "Step-by-Step Test Procedure", "Expected System Result"]
    for sec in SECTIONS:
        body_parts.append(_w_p(sec["title"], bold=True, color="5C1018", size_pt=13, space_after=80))
        body_parts.append(_w_p(sec["overview"], color="333333", size_pt=10, space_after=120))
        body_parts.append(_w_table(headers, sec["cases"]))
        body_parts.append(_w_p("", size_pt=8, space_after=160))

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body>
        {''.join(body_parts)}
        <w:sectPr>
            <w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>
            <w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>
        </w:sectPr>
    </w:body>
</w:document>"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)


if __name__ == "__main__":
    out_dir = "/mnt/extra-addons/discipline_management/static/docs"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "Discipline_Management_Comprehensive_Test_Cases.docx")
    build_docx(out_file)
    print("Generated:", out_file, os.path.getsize(out_file), "bytes")
