# EDS delivery workflow: implementation and release plan

Updated 2026-10-13. Scope is the Employee Development System add-on only.

## One workflow for HR

1. **Course catalog** defines what can be taught: competency and PMS mappings, a suggested delivery source, provider/trainer eligibility, certificate wording, and the current curriculum. The annual plan chooses the delivery method and a session can adjust it.
2. **TNA cycle** combines individual requests, work-unit nominations, competency gaps, and PMS gaps. A course shows each distinct employee once, ranked by how many independent sources support the need. Opening the employee reveals every source and its diagnostic values.
3. **Annual plan** takes selected course demand into one program line per selected course. It records delivery type, participant count, currency, budget, and approval. A PDF preview shows the annual mix and currency totals.
4. **Sourcing** compares training organizations and hotels against one approved plan program. Each selected winner flows to that program's sessions. International bids default to USD; individual bids can use another enabled currency.
5. **Session** schedules a specific delivery of the planned course. Its roster starts with the course's planned employees and their source evidence. HR can add other employees directly, filter by organizational fields, and invite selected people. Employees accept or decline; a manager can propose a replacement. HR decides which roster entries remain.
6. **Delivery and evidence** use dated attendance export/import, trainer-entered pre/post scores, participant reaction feedback, later manager behavior review, and an issued certificate. The employee can see the certificate in EDS and HR can retrieve it from the employee master view.

## Vocabulary

| Term | Use |
| --- | --- |
| Course | Reusable catalog offering such as Core Banking Operations. It owns competency/PMS mappings and default certificate wording. |
| Curriculum | Versioned learning content and module sequence for a course. It describes what is taught, not who attends. |
| Batch / cohort | A group that may move through one or more sessions together. It is an optional grouping tool. |
| Session | One scheduled delivery with dates, venue, trainer, roster, attendance, and evaluations. A course can run in multiple sessions. |
| Program | The annual plan's course or custom training line. Sourcing attaches to this line so an awarded organization and hotel apply to the correct planned delivery. |

## Implemented in this change

- Course demand detail and source ranking; diagnostic evidence and organization filters.
- Separate local/international organization and hotel sourcing; organization-specific external trainers and internal ToT trainers; award propagation to sessions.
- Annual-plan currency handling, currency-aware company totals, and PDF preview.
- Direct session roster, invitations, employee responses, manager replacement requests, and approved-plan year filtering.
- Dated attendance Excel export/import with validation.
- Course/session certificate PDF previews, certificate wording fallback, multi-day attendance eligibility, issued-certificate notifications, and existing employee-master retrieval.
- Automatic Level 1 survey distribution and Level 3 manager review after completed attendance; trainer/L&D reminders for pre/post scores; automatic Level 2 learning-gain linkage once those scores are entered.

## TNA correction pass (2026-10-13)

| # | Change | Reason |
| --- | --- | --- |
| 1 | The cycle assessment year defaults to the current year and is read-only in the form. | HR cannot accidentally label a new cycle with another year; historic cycles retain their stored year. |
| 2 | Competency and PMS pull dialogs show only the ingestion outcome and Close after a pull. Their source, scope, and threshold controls disappear; the server rejects a second pull on the same dialog. | Prevents an apparent second editable pull and makes the result easy to read. |
| 3 | Each employee in course demand shows an overall weighted priority. The score is the highest configured TNA weighted score plus five points per additional independent source, capped at 100. | Keeps the configured priority rules visible while ranking a person supported by several sources above an otherwise equal single-source case. |
| 4 | PMS import stores the appraisal measurement title, rating, target type, target and actual values, and accomplishment percentage. It links a missing measure by exact name within the job and unit when possible; a free-text criterion remains visible when no master record exists. An Unsatisfactory rating triggers a gap even if the numeric threshold does not. | PMS appraisals can contain either linked measurements or legacy criteria and can express performance with a rating as well as a percentage. |
| 5 | The cycle has separate Duplicates and Other Invalid / Excluded tabs. | HR can review screening outcomes without mixing them with valid demand. |
| 6 | The employee request hides the work-unit choice; the existing Target Group field remains visible. A work-unit request has its own navigation. | Employees submit their own need, while a unit leader nominates a group. |
| 7 | Individual organization fields come from the employee master and cannot be edited. Work-unit leaders can choose among units they manage, then filter staff by unit, department, and job; the server validates the selected staff. | Preserves the source of truth and stops nominations outside the selected scope. |
| 8 | A course outside the catalog can be proposed only on a work-unit request. | Custom program proposals need a unit-level business sponsor. |
| 9 | The Individual Training Needs cycle tab contains submitted manual employee requests only; competency and PMS results appear in Diagnostics. | Diagnostic entries use an individual employee but are not self-submitted TNA requests. |
| 10 | The TNA cycle picker shows only cycles collecting needs, and submission checks the state again on the server. | A saved draft cannot be submitted into a closed cycle. |
| 11 | Individual and work-unit cycle tabs omit drafts; course demand already aggregates only submitted or later valid states. | Unsubmitted ideas do not inflate training demand. |
| 12 | Work-unit requests require a manager of the unit, its parent, or its department. The HR employee read rule is limited to people in managed units. | A branch or department leader can nominate their staff without gaining access to every work unit. |
| 13 | Delivery place and method are removed from the course form and list. Planning and sessions retain delivery method. | The catalog describes reusable content; delivery is decided for a particular plan and session. |
| 14 | A course's recommended source initializes the plan delivery method and can be changed there. | The recommendation guides planning without locking the operational choice. |
| 15 | Auto-compiled learning outcomes include mapped PMS measurements as well as competencies. | A PMS-only course now has meaningful generated outcomes. |

### Verification of this pass

- The full EDS module suite passed 62 post-tests with no failures or test errors on the local integration database, including manager scope, PMS ingestion, cycle demand, and a PMS-only learning-outcome case.
- A subsequent EDS module upgrade completed after removing the duplicate `PMS Measurement` field-label warning. The upgrade log had no EDS-specific warnings or errors. It still reports warnings and a missing `internal.candidates.v` table from other installed modules; those require review in their owning modules.
- Browser layout, real employee/manager accounts, and outgoing notification delivery still need the release checks below. The automated tests validate model, view loading, access rules, and workflow behavior but do not prove the rendered screens or mail transport.

### Next EDS review targets

1. Run the four-source TNA → annual plan → sourcing → session → certificate path with real employee, branch manager, director, and L&D accounts in the browser. Automated ORM tests cannot confirm responsive layout or actual mail delivery.
2. Measure `_sync_course_demand` on a large cycle. It rebuilds per-employee evidence rows on refresh; incremental updates may be needed for bank-wide volume.
3. Review the remaining duplicate administrative routes and legacy nomination actions with HR users against the active menus. The direct session roster is the current delivery path; historical nominations remain readable.
4. Check deployment logs for deprecations and missing filestore assets after module upgrade. Warnings from PMS or HR modules are outside this EDS-only change and should be fixed in their owning modules.

## Release checks

1. Upgrade `employee_development_system` on a database copy and run all module tests. Resolve every error before deployment.
2. With employee, manager, trainer, officer, and director users, run a representative path from four-source TNA demand through annual plan, sourcing, session invitation, two-day attendance, assessments, evaluations, certificate, and employee-master retrieval. Verify access and notification delivery in the configured mail environment.
3. Render the annual-plan and certificate PDFs in the deployment environment and inspect the Bunna artwork, wording, currency totals, and page layout. Review a narrow-screen session roster and trainer form with HR staff.
4. Reconcile existing sessions and certificates before enabling any optional backfill. Existing nomination records remain readable for history, while new sessions use the direct roster.

## Decisions before broader rollout

- **Course category mapping:** the current catalog has three policy categories and nine program categories; Level 1–4 names belong to evaluation stages. No HR category template file was present in this repository. Map the official HR template's exact category labels and codes before replacing the existing values or migrating historical courses.
- **Assessment delivery:** pre/post assessment records currently store scores entered by a trainer or L&D officer. The evaluation instrument model does not define correct answers or exam grading, so an employee-facing online exam needs a question bank, grading rules, timing, retakes, and anti-duplication policy. Until that is agreed, notifications route score entry to the responsible staff.
- **Calendar days:** the attendance workbook provides a date column for each calendar day between session start and end. HR may clear unused dates before importing. If non-training days must be excluded automatically, add a session training-day calendar and drive both export and eligibility from it.
- **Certificate artwork:** the existing Bunna certificate background and logo are reused. HR should sign off on the preview against the approved physical template before release.
