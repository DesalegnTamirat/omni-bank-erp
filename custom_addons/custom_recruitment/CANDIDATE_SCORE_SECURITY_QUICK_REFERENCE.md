# Candidate Score Security - Quick Reference Guide

## For System Administrators

### What Changed?
Candidate scoring fields are now **only visible to Recruitment Administrators**. Recruitment Officers can no longer see:
- Individual scores (PMS, Written Exam, Interview)
- Final computed scores
- Candidate rankings
- Score weights
- Penalty deductions

### User Roles

| Role | Can See Scores? | Can Rank Candidates? | Can Auto-Select? |
|------|----------------|---------------------|------------------|
| **Recruitment Officer** | ❌ No | ❌ No | ❌ No |
| **Recruitment Administrator** | ✅ Yes | ✅ Yes | ✅ Yes |

### Assigning Roles

**Path:** Settings → Users & Companies → Users → [Select User] → Access Rights Tab

**Under "Human Resources / Recruitment" section:**
- ☐ Recruitment Officer (Basic Access)
- ☐ Recruitment Administrator (Full Access + Scores)

### Quick Test

**As Recruitment Officer:**
```
1. Login
2. Go to: Recruitment → Candidate Scores
3. Expected: NO score columns visible
```

**As Recruitment Administrator:**
```
1. Login
2. Go to: Recruitment → Candidate Scores
3. Expected: ALL score columns visible
```

---

## For HR Management

### Business Impact

**Recruitment Officers can still:**
- ✅ Create and manage candidate records
- ✅ View candidate information
- ✅ See selection status (Selected, Reserve, Rejected)
- ✅ View disciplinary and leave status
- ✅ Manage interviews and assessments

**Recruitment Officers CANNOT:**
- ❌ See individual test scores
- ❌ See final computed scores
- ❌ See candidate rankings
- ❌ Run auto-selection algorithms
- ❌ Manipulate scoring weights

### Why This Matters

1. **Confidentiality:** Protects sensitive scoring data
2. **Fairness:** Prevents bias from premature score disclosure
3. **Compliance:** Aligns with HR data protection policies
4. **Separation of Duties:** Clear role boundaries

### Recommended Workflow

```
Step 1: Officers schedule interviews → ✅ No score visibility
Step 2: Officers enter basic candidate info → ✅ No score visibility
Step 3: Administrators enter scores → ✅ Score visibility
Step 4: Administrators run ranking → ✅ Algorithm access
Step 5: Administrators auto-select candidates → ✅ Decision access
Step 6: Officers notify selected candidates → ✅ No score visibility
```

---

## Troubleshooting

### "I'm an administrator but can't see scores"

**Check:**
1. Do you have "Recruitment Administrator" role assigned?
2. Try logging out and back in
3. Clear your browser cache (Ctrl+F5)
4. Contact IT support if issue persists

### "An officer can still see scores"

**Action:**
1. Go to Settings → Users & Companies → Users
2. Find the user
3. Remove "Recruitment Administrator" role
4. Keep only "Recruitment Officer" role
5. User must logout and login again

### "Scores not appearing in reports"

**Note:** This is expected behavior for users without administrator role. Reports will only show scores to authorized users.

---

## Emergency Access

If an emergency requires temporary score access for an officer:

1. **Grant temporary administrator role:**
   - Settings → Users → [User] → Access Rights
   - Check "Recruitment Administrator"
   - Save

2. **Complete urgent task**

3. **Remove administrator role immediately:**
   - Uncheck "Recruitment Administrator"
   - Save

4. **Document the access grant in audit log**

---

## Support Contacts

- **Technical Issues:** IT Support
- **Access Requests:** HR Management
- **Policy Questions:** HR Director

---

**Module Version:** 19.0.1.0.0
**Last Updated:** 2026-08-03
