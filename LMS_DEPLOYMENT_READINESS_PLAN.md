# LMS deployment readiness implementation plan

> Historical gap audit. The implementation that followed this audit and its current release gates are recorded in [LMS_ODOO_RELEASE_PLAN.md](LMS_ODOO_RELEASE_PLAN.md). Use that plan for the current checkout.

**Prepared:** 2026-10-26  
**Scope:** `custom_addons/learning_management` and the HR, EDS, competency, identity, media, and deployment paths required for an end-to-end LMS release.  
**Requirement baseline:** Part 3, Module 2 of `../docs/Business_Requirement_Document_for_ERP_System_Enhancement_and_upgrading.pdf`, indexed in `../docs/Requirement2.txt:4059-4277`; Part 3 mobile and recognition requirements at `:4291-4392`; e-learning/competency requirements at `:5934-5971`; and onboarding requirement FR-OB-005 in `../docs/requirement.txt:5938-5943`.

## Readiness decision and audit limits

**Do not deploy the current checkout to production yet.** It has substantial LMS functionality in source, but the BRD's adaptive video and offline mobile requirements are not delivered, content and assessment revision controls have gaps, renewal/compliance handling is incomplete, and a production deployment and runtime test result are not available. The existing `EDS_LMS_KMS_IMPLEMENTATION_PLAN.md` is a 2026-10-12 audit of an earlier state; use the findings below for the current checkout.

This is a static review, not an Odoo acceptance result. `docker compose config --quiet` passed, but the Docker engine denied access, so no module install/upgrade, Odoo test suite, browser UAT, media load test, or restore drill was run. The repository also contains modified and untracked LMS files; define and freeze the intended release commit before testing it. Status terms below mean **source present** (code found, runtime unverified), **partial** (a confirmed requirement gap), and **not found** (no implementation identified in the reviewed module).

## Requirement coverage and target outcome

| BRD area | Current evidence | Deployment acceptance |
| --- | --- | --- |
| FR-LMS-001–003: course lifecycle, paths, assignments | **Partial.** Course states, learning paths, and role/department/branch assignment code exist (`models/lms_course.py`, `models/lms_learning_path.py`, `models/lms_assignment.py`). Published course content, lessons, assessments, and answer keys can still be changed outside a new reviewed version; direct state writes do not perform all `action_publish()` side effects. | Draft → review → approved/published → revision/archive enforced for ORM, RPC, and UI writes. Branch/department/role access and new-hire/role-change assignment pass an approved role matrix. Old versions and learner history remain readable only to authorized roles. |
| FR-LMS-004–006: internal, adaptive, protected video | **Partial.** Authenticated byte-range MP4 streaming exists (`controllers/main.py:110-179`), but the HLS endpoint returns 501 (`:181-201`). Byte-range playback is not adaptive bitrate delivery. The existing player deterrents and raw stream do not establish the BRD's content protection policy. | Approved private hosting/CDN design produces multiple bitrate renditions for low-bandwidth use; authenticated manifests and segments cannot be fetched by unauthorized users; permitted offline use, encryption, watermarking, and download policy are tested. |
| FR-LMS-007–011: mandatory progress, anti-skip, resume, dashboard, revisions | **Partial.** Server-bounded video progress, gates, resume, and version fields exist (`models/lms_enrollment.py`, `models/lms_course.py`). Mandatory text/document lessons can be marked complete without opening them (`models/lms_enrollment.py:631-655`); revision enforcement has the gaps above. | Define and enforce completion evidence for every lesson format. Direct-write and replay/seek tests cannot award unearned completion. Resume and superseding work across interrupted sessions; published content is frozen and older versions are retired atomically. |
| FR-LMS-012–017: assessment gate, diagnostic exam, timer, pools, attempts, grading | **Partial.** Assessment and exam engines implement these controls (`models/lms_assessment.py`, `models/lms_exam_session.py`). Exam lines reference live questions/answers, so edits during an attempt can change grading. | Freeze a published question bank or snapshot questions, options, and correct answers per attempt. Server-side timer, attempt/cooldown, randomization, answer-key privacy, and completion gates pass adversarial ORM/RPC tests. |
| FR-LMS-018–022: certificate, validity, history, HR attachment | **Partial.** PDF issue, expiry job, and retryable HR delivery are present (`models/lms_certificate.py`). Unique employee/course enrollment and expiry-only processing leave no supported same-course recertification cycle (`models/lms_enrollment.py:72-75`, `models/lms_certificate.py:217-229`). | Multiple certification cycles preserve prior attempts/certificates, issue distinct renewals, update HR documents/history once per cycle, and mark expired/revoked certificates non-compliant. |
| FR-LMS-023–029: dashboards, compliance, analytics, notifications | **Partial.** SQL views and scheduled reminders exist (`models/lms_analytics.py`, `data/lms_default_data.xml`). Compliance currently counts completed enrollments even when certification later expires; the branch graph sums percentage rows; notification settings cover timing/manager flag but not a full trigger/channel/recipient rule set. | Branch/department totals and weighted rates match source records and stay within 0–100%, expiry/revocation changes compliance, reports respect the approved access matrix, and configurable notifications are delivered once through approved channels. |
| Part 3 FR-MOB-001–009: mobile access, low bandwidth, offline courses/assessment, push/sync | **Partial/not found.** Mobile-styled Odoo views exist; no LMS offline storage, queued assessment/sync, or mobile push implementation was found. | Supported devices can securely download assigned mandatory learning, complete approved activities offline, and sync idempotently after reconnect. Conflict, expiry, lost-device, and poor-network cases pass UAT. |
| FR-REC-001–008; FR-ELN-001–005; EDS and HR onboarding | **Partial.** LMS points/badges/monthly scorer and EDS→LMS/HR bridges exist (`models/lms_gamification.py`, `employee_development_system/models/eds_integration.py`, `models/lms_certificate.py`). EDS curriculum auto-routing passes fields the routing model does not define (`employee_development_system/models/eds_curriculum.py:166-180`); reconciliation returns an aggregate percentage, not each learner's training status. Competency linking and one-time campaigns do not establish automatic gap-driven and role-change learning. | EDS creates a valid LMS shell and assignments, receives each learner's completion/history, competency changes drive/record relevant learning, and PPDD onboarding assigns mandatory videos by role and grade. |
| Cross-cutting access, audit, availability, DR | **Partial.** LDAP/TOTP dependencies and Odoo chatter exist, but configured SSO/MFA and an immutable LMS audit trail have not been demonstrated. Current Compose is development-oriented (`docker-compose.yml`, `config/odoo.conf`). | Signed role/branch matrix, SSO/MFA and audit evidence, approved performance and recovery targets, measured ≥99.5% availability design, monitored operations, and a successful database **plus filestore** restore drill. |

## Implementation work packages

Complete package 0 first. Packages 1, 2, and 4 can then progress in parallel; package 3 depends on the agreed learning and renewal rules. Package 5 is the release gate for all streams.

### 0. Freeze acceptance rules and release baseline — product owner, PPDD, IT/security, QA

1. Turn every FR-LMS-001–029 and relevant Part 3 FR-MOB, FR-REC, FR-ELN, EDS, and FR-OB-005 requirement into a testable traceability row with owner, evidence, and pass/fail status. Use the PDF as the approval baseline; keep `Requirement2.txt` as the searchable index.
2. Approve the role matrix (learner, instructor/content owner, reviewer, LMS manager, branch/department manager, auditor), content revision rules, assignment/due-date rules, certificate validity/renewal rules, offline assessment policy, notification recipients/channels, and audit retention.
3. Approve private media/CDN and mobile architecture. Reconcile FR-LMS-006 download restriction with FR-MOB-005 offline downloads through an explicit encrypted, expiring offline license policy.
4. Set measurable targets for concurrent learners/streams, low-bandwidth playback, dashboard latency, sync lag, backup frequency, RTO/RPO, audit retention, and alert response. The BRD gives ≥99.5% availability but leaves these targets open (`../docs/Requirement2.txt:4256-4277`).
5. Review all LMS modified/untracked files, commit only the intended release content, and tag a candidate. Re-run every gate below on that exact commit and its built image.

**Exit evidence:** signed requirement/role matrix and architecture decisions; reproducible release candidate identifier.

### 1. Close lifecycle, exam, and certification integrity — LMS/Odoo team

1. Put course state transitions behind one server-side transition service. Publishing must verify reviewer approval, required lessons/assessments, and revision lineage, then retire the preceding version in the same transaction. Reject direct writes to state/version fields that bypass this service.
2. Prevent updates and deletion of published lessons, videos, assessments, questions, and answer keys in place. Validate that each lesson has the required video/document/text/quiz content before publishing. Create a draft revision with copied curriculum/question bank; preserve historical attempts, enrollments, and certificates against the exact version used. Snapshot grading material per attempt or freeze its referenced version.
3. Define and implement a server-verifiable completion event for mandatory text and document lessons, such as opening the authorized content and a deliberate learner acknowledgement. Match the business-approved evidence level; do not award credit from a bare `mark_completed()` call.
4. Implement a repeatable recertification cycle. Replace the employee/course uniqueness rule with cycle/version-aware uniqueness; define how a renewal enrollment is opened, passes, expires, and links to the old certificate. Recalculate compliance from current valid certification, not only completed enrollment.
5. Add an append-only LMS audit record for approval, publication, versioning, assignment, progress exceptions, exam submission/grade, certificate issue/revocation, and admin override. Restrict mutation/deletion and forward records to an approved retained audit store. Odoo chatter alone is insufficient proof of immutability.
6. Add tests for direct ORM/RPC mutation, concurrent approval, empty lessons, text/document completion, exam question changes mid-attempt, replayed video heartbeats, repeated completion, renewal, and certificate delivery retry. Preserve legitimate instructor and learner workflows.

**Exit evidence:** automated negative/positive tests and UAT show no bypass of review, progress, grading, or renewal; historical records remain intact.

### 2. Deliver media and mobile requirements — media/mobile team with IT/security

1. Package internal video into real adaptive renditions and playlists, store them in approved private infrastructure, and serve manifests/segments only after the same enrollment, course-state, and lesson-order checks as the current stream route. Define low-bandwidth fallback, caching, key rotation, and watermark behavior. Remove or replace the 501 HLS endpoint only when the complete media path works.
2. Implement the chosen mobile client or progressive web app with encrypted offline storage for assigned mandatory courses and an explicit expiration/revocation policy. Queue progress and any approved offline exams with server-issued attempt IDs, timestamps, idempotency keys, and conflict rules; validate all completion gates on sync. Add the BRD's push alerts and responsive accessibility checks.
3. Load-test concurrent authorized streams, slow and interrupted networks, resume, seek prevention, unauthorized media/attachment access, expired enrollments, and offline-to-online reconciliation. Publish target devices and browser versions.

**Exit evidence:** a learner completes mandatory training under the approved low-bandwidth/offline scenarios without leaking media or manufacturing completion.

### 3. Complete integration, reporting, and notification rules — LMS, EDS, HR, competency teams

1. Repair EDS curriculum auto-routing (`eds_curriculum.py:166-180`) against the actual `eds.lms.routing` schema, then make EDS→LMS creation/enrollment and learner-level completion return idempotent and retryable. Reconcile existing failed/partial routing records.
2. Implement approved HR/competency triggers: new-hire and role/grade changes create mandatory onboarding/learning assignments; competency gaps select relevant learning; completion updates the employee's development history and any approved competency status. Reconcile batch campaigns for staff who joined or moved after campaign execution.
3. Correct compliance views for certificate validity/revocation and approved overdue rules. Aggregate numerator/denominator counts before calculating percentages in branch charts. Check report record rules and branch visibility with a multi-branch fixture; test large-data query plans.
4. Add configurable notification events, recipients, channels, timing, deduplication, and failure/retry status. Verify assignment, due/overdue, completion, certificate expiry, and required manager/auditor alerts through real mail/push configuration.

**Exit evidence:** an EDS need/PPDD onboarding rule creates an LMS assignment, learning and assessment complete, a valid certificate reaches HR, EDS receives that employee's result, compliance updates, and each expected notification is sent once.

### 4. Build the production platform and release process — DevOps/IT/security

1. Replace the development Compose settings with an approved production deployment: secrets outside source control, rotated credentials, private database network, TLS/reverse proxy, explicit DB host configuration, restrictive `dbfilter`, health checks, resource limits, log shipping, and environment-specific configuration. Pin Odoo and PostgreSQL image digests and package add-ons into an immutable image rather than bind mounting the checkout.
2. Configure and verify LDAP/SSO, MFA, SMTP, approved media hosts, `web.base.url`, time zone, cron workers, and certificates. Test identity failure/recovery and media authorization with each role.
3. Add CI for Python/XML checks, clean LMS install, upgrade from the currently deployed version, module/cross-module tests, access and HTTP media tests, and artifact publication. Import `tests/test_scenario_kms_lms_full_lifecycle.py` from `tests/__init__.py` or remove it from the required suite with a documented replacement.
4. Prepare versioned migrations and a data reconciliation script where schema/rule changes affect existing courses, enrollments, certificates, and EDS routes. Rehearse upgrade and rollback on a production-like database **and filestore** clone.
5. Back up database, filestore, configuration, and media keys under one recoverable snapshot policy. Measure a restore against agreed RTO/RPO. Alert on failed crons, certificate delivery errors, sync backlog, 5xx/403 spikes, storage capacity, and availability.

**Exit evidence:** clean install/upgrade logs, green CI, signed security review, successful restore, monitoring dashboard and alert test, and an immutable release artifact.

### 5. UAT, staging rehearsal, and controlled rollout — QA, business owners, IT

1. Run the complete Odoo test suite and an end-to-end staging scenario with learner, instructor, reviewer, manager, branch manager, HR/PPDD, and auditor accounts. Include malicious direct-write/HTTP attempts, multi-branch visibility, offline conflict/replay, renewal, failed mail/PDF retry, and EDS reconciliation.
2. Test desktop and supported mobile devices with real course/video content and representative data volume. Confirm accessible controls and the approved performance, availability, and low-bandwidth targets.
3. Rehearse deployment, data migration, rollback, database/filestore restore, and post-release smoke checks on the exact candidate artifact. Obtain product, security, operations, and UAT sign-off before production cutover.
4. Roll out to a controlled pilot cohort, monitor failure/backlog and learning metrics, fix issues, then expand to all branches. Keep an owner and escalation path for the first full certificate/expiry/reminder cycle.

**Exit evidence:** signed traceability matrix with no unaccepted mandatory requirement gaps, passed staging and pilot gates, and recorded cutover/rollback results.

## Release gates

Production approval requires **all** of these results on the same release candidate:

1. Every mandatory BRD requirement is passed or has a formally approved scope change; the unresolved decisions in work package 0 are closed.
2. Clean install and upgrade pass on Odoo 19 with its exact add-on dependencies; migrations preserve production-like history.
3. Automated and manual role, branch, progression, assessment, media, mobile/offline, certificate, and cross-module tests pass with no high-severity defect.
4. Capacity, low-bandwidth, accessibility, SSO/MFA, audit retention, and availability evidence meets signed targets.
5. Backup/restore meets approved RTO/RPO; alerts, runbooks, rollback, and on-call ownership are exercised.

**Immediate next action:** complete work package 0 and bring up a controlled Odoo staging instance. Runtime evidence may change the ranking of individual defects, but it does not remove the confirmed adaptive-media, offline-mobile, lifecycle, renewal, or production-platform gaps above.
