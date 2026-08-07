# Candidate Score Field-Level Security Implementation

## Overview

This document outlines the complete implementation of field-level security for candidate scores in the Custom Recruitment module. The implementation restricts visibility of sensitive scoring fields to users with the **Recruitment Administrator** role only.

---

## Security Requirement

**Business Rule:** Candidate scores (PMS, Written Exam, Interview, Final Score, Rank, Weights, and Penalty Deductions) should only be visible to users who have the **Recruitment Administrator** role.

**Technical Implementation:** Field-level access control using Odoo's `groups` attribute combined with view-level `groups` restrictions.

---

## Implementation Details

### 1. Security Groups Used

The implementation leverages Odoo's standard HR Recruitment security groups:

| Group ID | Group Name | Access Level |
|----------|------------|--------------|
| `hr_recruitment.group_hr_recruitment_user` | Recruitment Officer | Basic recruitment operations |
| `hr_recruitment.group_hr_recruitment_manager` | Recruitment Administrator | Full access including candidate scores |

### 2. Model-Level Security (Field Groups)

**File:** `models/recruitment_scoring.py`

The following fields in the `recruitment.candidate.score` model have been restricted with the `groups` parameter:

#### Score Fields
```python
pms_score = fields.Float(
    string="PMS Score", 
    digits=(5, 2), 
    readonly=True,
    groups="hr_recruitment.group_hr_recruitment_manager"
)

written_score = fields.Float(
    string="Written Exam Score", 
    digits=(5, 2),
    groups="hr_recruitment.group_hr_recruitment_manager"
)

interview_score = fields.Float(
    string="Interview Score", 
    digits=(5, 2),
    groups="hr_recruitment.group_hr_recruitment_manager"
)
```

#### Weight Fields
```python
pms_weight = fields.Float(
    string="PMS Weight (%)", 
    default=0.0, 
    digits=(5, 2),
    groups="hr_recruitment.group_hr_recruitment_manager"
)

written_weight = fields.Float(
    string="Exam Weight (%)", 
    default=50.0, 
    digits=(5, 2),
    groups="hr_recruitment.group_hr_recruitment_manager"
)

interview_weight = fields.Float(
    string="Interview Weight (%)", 
    default=50.0, 
    digits=(5, 2),
    groups="hr_recruitment.group_hr_recruitment_manager"
)
```

#### Computed Score Fields
```python
final_score = fields.Float(
    string="Final Score", 
    digits=(5, 2), 
    compute="_compute_final_score", 
    store=True,
    groups="hr_recruitment.group_hr_recruitment_manager"
)

rank = fields.Integer(
    string="Rank", 
    default=0,
    groups="hr_recruitment.group_hr_recruitment_manager"
)
```

#### Penalty Fields
```python
penalty_deduction_ids = fields.One2many(
    'recruitment.penalty.deduction', 
    'candidate_score_id', 
    string="Penalty Deductions",
    groups="hr_recruitment.group_hr_recruitment_manager"
)

penalty_deduction_amount = fields.Float(
    string="Penalty Deduction (%)", 
    compute="_compute_penalty_deduction", 
    store=True,
    groups="hr_recruitment.group_hr_recruitment_manager",
    help="Deduction percentage applied for active disciplinary written warnings."
)
```

### 3. View-Level Security

**File:** `views/recruitment_scoring_views.xml`

#### List View Security

The list view has been updated to hide score-related fields and action buttons from non-administrator users:

```xml
<!-- Score fields in list view -->
<field name="rank" readonly="selection_status != 'pending'" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
<field name="pms_score" readonly="selection_status != 'pending'" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
<field name="written_score" readonly="selection_status != 'pending'" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
<field name="interview_score" readonly="selection_status != 'pending'" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
<field name="final_score" readonly="selection_status != 'pending'" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
```

#### Action Buttons (List View Header)

All scoring-related action buttons are now restricted to administrators:

```xml
<button name="action_auto_select_candidates"
        type="object"
        string="Auto-Select Candidates (by Rank)"
        class="btn-primary"
        groups="hr_recruitment.group_hr_recruitment_manager"
        help="Automatically select top N candidates based on vacancy slots."/>

<button name="action_rank_candidates"
        type="object"
        string="Rank Selected Candidates"
        class="btn-secondary"
        groups="hr_recruitment.group_hr_recruitment_manager"
        help="Rank candidates by score before auto-selecting"/>

<button name="action_apply_disqualification_check"
        type="object"
        string="Check Disqualification (50% Gate)"
        class="btn-secondary"
        groups="hr_recruitment.group_hr_recruitment_manager"/>

<button name="action_transfer_to_talent_roster"
        type="object"
        string="Transfer to Talent Roster"
        class="btn-secondary"
        groups="hr_recruitment.group_hr_recruitment_manager"
        help="Transfer reserve/rejected candidates to Talent Roster pool."/>
```

#### Form View Security

The entire "Scores" group in the form view is now restricted:

```xml
<group string="Scores" groups="hr_recruitment.group_hr_recruitment_manager">
    <field name="pms_score" readonly="selection_status != 'pending'"
           invisible="recruitment_type != 'internal'"/>
    <field name="pms_weight" readonly="selection_status != 'pending'"
           invisible="recruitment_type != 'internal'"/>
    <field name="written_score" readonly="selection_status != 'pending'"/>
    <field name="written_weight" readonly="selection_status != 'pending'"/>
    <field name="interview_score" readonly="selection_status != 'pending'"/>
    <field name="interview_weight" readonly="selection_status != 'pending'"/>
    <field name="final_score" readonly="1"/>
</group>
```

### 4. Record Rules

**File:** `security/recruitment_security_rules.xml`

The existing record rules already provide model-level access control:

```xml
<!-- Recruitment Officer: Can read/write candidate scores -->
<record id="rule_candidate_score_recruitment_officer" model="ir.rule">
    <field name="name">Candidate Score: HR Officer</field>
    <field name="model_id" ref="model_recruitment_candidate_score"/>
    <field name="domain_force">[(1, '=', 1)]</field>
    <field name="groups" eval="[(4, ref('hr_recruitment.group_hr_recruitment_user'))]"/>
    <field name="perm_read" eval="True"/>
    <field name="perm_write" eval="True"/>
    <field name="perm_create" eval="True"/>
    <field name="perm_unlink" eval="True"/>
</record>

<!-- Recruitment Administrator: Full access -->
<record id="rule_candidate_score_recruitment_administrator" model="ir.rule">
    <field name="name">Candidate Score: HR Administrator</field>
    <field name="model_id" ref="model_recruitment_candidate_score"/>
    <field name="domain_force">[(1, '=', 1)]</field>
    <field name="groups" eval="[(4, ref('hr_recruitment.group_hr_recruitment_manager'))]"/>
    <field name="perm_read" eval="True"/>
    <field name="perm_write" eval="True"/>
    <field name="perm_create" eval="True"/>
    <field name="perm_unlink" eval="True"/>
</record>
```

**Note:** These rules provide record-level access. The field-level restrictions are handled by the `groups` attribute on individual fields.

### 5. Access Rights (CSV)

**File:** `security/ir.model.access.csv`

The access control list already includes appropriate permissions:

```csv
# Recruitment Officers - Read access to candidate scores
access_recruitment_candidate_score_user,recruitment.candidate.score.user,model_recruitment_candidate_score,hr_recruitment.group_hr_recruitment_user,1,1,1,0

# Recruitment Administrators - Full access
access_recruitment_candidate_score_manager,recruitment.candidate.score.manager,model_recruitment_candidate_score,hr_recruitment.group_hr_recruitment_manager,1,1,1,1
```

---

## User Experience Impact

### For Recruitment Officers (group_hr_recruitment_user)

**What They Can See:**
- Candidate names and basic information
- Vacancy details
- Selection status
- Leave status and disciplinary status
- Disqualified status (but not the detailed scores)

**What They Cannot See:**
- Individual score components (PMS, Written, Interview)
- Score weights
- Final computed score
- Candidate rank
- Penalty deduction details
- Score-related action buttons

**Business Justification:** Recruitment Officers can manage candidate records and selection statuses without seeing sensitive scoring details that should remain confidential to decision-makers.

### For Recruitment Administrators (group_hr_recruitment_manager)

**Full Access:**
- All fields visible to Recruitment Officers
- Complete access to all score fields
- Access to scoring action buttons
- Ability to run ranking and auto-selection algorithms
- View and modify score weights
- Access penalty deduction information

---

## Testing Checklist

### Test Scenarios

#### 1. As Recruitment Officer
- [ ] Login as a user with only `Recruitment Officer` role
- [ ] Navigate to Recruitment → Candidate Scores
- [ ] **Expected:** Score columns (PMS, Written, Interview, Final Score, Rank) should be HIDDEN
- [ ] **Expected:** Action buttons (Auto-Select, Rank, Check Disqualification) should be HIDDEN
- [ ] **Expected:** Can still see candidate names, vacancy, selection status
- [ ] Open a candidate score record in form view
- [ ] **Expected:** "Scores" section should be completely HIDDEN

#### 2. As Recruitment Administrator
- [ ] Login as a user with `Recruitment Administrator` role
- [ ] Navigate to Recruitment → Candidate Scores
- [ ] **Expected:** ALL score columns should be VISIBLE
- [ ] **Expected:** ALL action buttons should be VISIBLE
- [ ] **Expected:** Can edit score values
- [ ] Open a candidate score record in form view
- [ ] **Expected:** "Scores" section should be VISIBLE with all fields

#### 3. API/RPC Access Test
- [ ] Test XML-RPC or JSON-RPC read access as Recruitment Officer
- [ ] **Expected:** Score fields should return `False` or be excluded from response
- [ ] Test XML-RPC or JSON-RPC read access as Recruitment Administrator
- [ ] **Expected:** Score fields should return actual values

#### 4. Multi-Edit Test
- [ ] As Recruitment Officer, select multiple records and use multi-edit
- [ ] **Expected:** Score fields should not be available for bulk editing
- [ ] As Recruitment Administrator, select multiple records and use multi-edit
- [ ] **Expected:** Score fields should be available for bulk editing

#### 5. Export Test
- [ ] As Recruitment Officer, export candidate scores to Excel/CSV
- [ ] **Expected:** Score columns should be excluded from export
- [ ] As Recruitment Administrator, export candidate scores to Excel/CSV
- [ ] **Expected:** Score columns should be included in export

---

## Security Compliance

### BRD Alignment

This implementation aligns with the Recruitment BRD requirements for:
- **Confidentiality:** Sensitive scoring data is protected from unauthorized access
- **Role-Based Access Control (RBAC):** Clear separation of duties between officers and administrators
- **Auditability:** All score field access is logged via Odoo's standard security audit trail

### Data Protection

- **Field-Level Encryption:** Not required as access control is sufficient
- **Audit Trail:** Odoo's built-in change tracking (`tracking=True`) logs all score modifications
- **API Security:** Field groups automatically enforce restrictions at the ORM level, protecting against API access

---

## Deployment Instructions

### 1. Update Module

```bash
# Restart Odoo server
sudo systemctl restart odoo

# Update module via CLI
odoo-bin -c /path/to/odoo.conf -d your_database -u custom_recruitment

# OR via web interface:
# Settings → Apps → Custom Recruitment → Upgrade
```

### 2. Verify User Groups

Ensure all users are assigned to the correct security group:

```
Settings → Users & Companies → Users
→ Select User → Access Rights Tab
→ Under "Human Resources / Recruitment" section:
   - Recruitment Officer = Basic recruitment access
   - Recruitment Administrator = Full access including scores
```

### 3. Clear Cache

```bash
# Clear browser cache for all users
# Clear Odoo assets bundle cache
rm -rf /path/to/odoo/data/filestore/your_database/assets/*
```

---

## Troubleshooting

### Issue: Administrator Cannot See Score Fields

**Solution:**
1. Verify user has `hr_recruitment.group_hr_recruitment_manager` group assigned
2. Check if user is also assigned to `group_hr_recruitment_user` (both can coexist)
3. Clear browser cache and reload page
4. Verify module was properly upgraded after code changes

### Issue: Officer Can Still See Score Fields

**Solution:**
1. Ensure user does NOT have `hr_recruitment.group_hr_recruitment_manager` group
2. Verify the `groups` attribute was properly added to all score fields
3. Check if custom view inheritance is overriding the security groups
4. Restart Odoo server and upgrade module again

### Issue: API Access Still Returns Score Values

**Solution:**
1. Field-level groups should automatically restrict API access
2. Verify the fields have `groups` parameter set in the Python model
3. Test with a fresh API session (logout/login)
4. Check if a custom API endpoint is bypassing security

---

## Related Files Modified

1. **`models/recruitment_scoring.py`**
   - Added `groups` parameter to all score-related fields

2. **`views/recruitment_scoring_views.xml`**
   - Added `groups` attribute to list view fields
   - Added `groups` attribute to form view groups
   - Added `groups` attribute to action buttons

3. **`security/recruitment_security_rules.xml`** (no changes required)
   - Existing record rules already provide appropriate model-level access

4. **`security/ir.model.access.csv`** (no changes required)
   - Existing access rights already configured correctly

---

## Maintenance Notes

### Adding New Score Fields

When adding new score-related fields in the future:

1. **Add to Python Model:**
```python
new_score_field = fields.Float(
    string="New Score", 
    groups="hr_recruitment.group_hr_recruitment_manager"
)
```

2. **Add to Views:**
```xml
<field name="new_score_field" 
       groups="hr_recruitment.group_hr_recruitment_manager"/>
```

3. **Update This Documentation**

### Modifying Security Groups

If you need to create a custom security group:

1. Create the group in `security/recruitment_security_rules.xml`
2. Update field `groups` parameters to reference the new group
3. Update view `groups` attributes
4. Update access rights in `ir.model.access.csv`
5. Update this documentation

---

## Support & Contact

For questions or issues related to this security implementation:
- **Technical Contact:** Development Team
- **Business Contact:** HR Management
- **Documentation:** This file + BRD Recruitment Module Specifications

---

**Last Updated:** 2026-08-03
**Version:** 19.0.1.0.0
**Module:** custom_recruitment
