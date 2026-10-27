# Odoo LMS implementation and release plan

**Updated:** 2026-10-26  
**Requirement baseline:** `../docs/Requirement2.txt:4059-4392`, `../docs/Requirement2.txt:5934-5971`, and `../docs/requirement.txt:5938-5943`.  
**Delivery choice:** use Odoo 19's authenticated web client on desktop and phones. Keep native and offline mobile learning as a separately designed future phase.

## Release decision

The implementation is in source, but this checkout is **not yet approved for production**. An isolated Odoo 19 clean install and 66 selected Odoo tests passed on the current test image; the EDS routing upgrade step passed three more tests on the same database and filestore. Source, player, and test Compose checks also pass. Upgrade of a production-like database, broader ERP regression, browser/device acceptance, load testing, identity integration, and a database-plus-filestore restore drill still require staging. Release only the exact commit and image that pass those gates.

The requirements ask for adaptive video, offline course downloads and exams, push notifications, and high availability. These depend on media packaging, device storage and conflict policy, identity and messaging services, and production infrastructure. The current release uses an authenticated MP4 Range stream and standard Odoo notifications in a responsive web interface. Those advanced capabilities are future scope until their architecture and acceptance rules are approved. Do not advertise the current player as adaptive or offline. Keep the media host allowlist empty for Odoo-stored files; enable redirects only for bank-controlled media hosts that enforce their own learner authorization.

**Local navigation incident (2026-10-26).** The live `ERP_local_full` database had `learning_management` recorded as installed at `19.0.1.0.0`, while `auditlog` was uninstalled. Because the current LMS manifest requires `auditlog`, Odoo skipped loading the LMS models and the app tile's enrollment action could not open (`Missing model lms.enrollment`). A source-only deploy therefore does not complete this release: back up the database and filestore, install `auditlog`, upgrade `learning_management`, restart Odoo, and verify the model registry and root tile. Stage dependencies and module migration before exposing the new source to users. Use [LMS_END_TO_END_UAT_GUIDE.md](LMS_END_TO_END_UAT_GUIDE.md) to record the role-by-role acceptance run.

## Implementation delivered in this checkout

| Area | Source implementation | Acceptance evidence still needed |
| --- | --- | --- |
| Course authoring and review (FR-LMS-001–003, 011) | Draft/review/publish/archive transitions check the assigned reviewer, material, assessments, real document uploads, deliberately entered video duration, and approved HTTPS media hosts. Reviewed and published content is frozen; a revision copies its lessons and question bank. Learners already enrolled may finish their archived version; new intake uses the latest publication. | Upgrade audit for older published courses, HTML-only document lessons, and default video durations; compare entered duration with actual media. Role and direct-RPC tests and review UAT remain. Record business acceptance of the in-progress learner exception to FR-LMS-011. |
| Learner flow and assessments (FR-LMS-007–017) | Lesson order and prerequisite gates, server-bounded video credit, opened plus acknowledged evidence for text/documents, pre/final assessment actions, and frozen question/answer/passing-policy snapshots per new exam attempt. Learner forms and exam controls are easier to use on phones. | The selected Odoo tests pass; run broader ERP regression and a mobile browser scenario. Audit already-active legacy exam attempts, which do not have snapshots. Per-attempt answer shuffling remains to be implemented if required. |
| Media and mobile web (FR-LMS-004–006; mobile web portion of FR-MOB) | Authenticated MP4 Range endpoint and responsive Odoo player with resume, status feedback, network retry, and final-save queue. Start/Resume opens the next lesson. Private course access and enrollment checks stay server side. | Test real phones, low bandwidth, interrupted streams, actual versus entered video duration, and unauthorized requests. HLS/adaptive delivery and offline storage are future work. |
| Assignments and renewal (FR-LMS-003, 018–022, 027) | Idempotent campaign delivery records; daily matching for new hires/transfers and approved competency gaps; multiple numbered enrollment attempts; certificate expiry opens one current mandatory renewal; previous history is retained. Early self-service renewal receives a deadline, and reconciliation tightens missing or later deadlines. Certificates are issued by the completion workflow; managers can revoke only through a reasoned, recorded action. | Clean install and selected certificate, renewal, and revocation tests pass. Test upgrade of the former enrollment uniqueness constraint on production-like data, concurrent jobs, and HR history reconciliation. |
| EDS and reporting (FR-LMS-023–029; partial FR-ELN) | EDS curriculum routing uses valid fields and idempotent nightly sync; draft LMS shells defer learner enrollment until publication. Participant feedback records completion and certificate state. Approved competency gaps can target assignment campaigns. Current compliance rolls archived course versions into the latest published course, accepts a prior valid certificate until expiry unless a new mandatory enrollment requires fresh completion, and excludes expired/revoked results. Odoo chatter sends targeted assignment, progress, and completion alerts; activities and scheduled reminders provide the baseline notification workflow. | Reconcile production EDS routes, compare dashboard numerators/denominators with actual records, configure SMTP/cron, verify branch access and one-time notifications. FR-ELN-004 outbound synchronization into competency profiles, career/succession records, and CLC remains pending; do not claim end-to-end FR-ELN coverage. |
| Recognition (FR-REC-001–008; partial) | LMS points and milestone messages, monthly best-scorer records, and a shared KMS/LMS recognition points and monthly-award ledger are in source. | Verify leaderboard and monthly jobs with real staff data, score ties, duplicate-run behavior, learner/supervisor notifications, HR reporting, and access from phones. Recognition on employee profiles and configurable categories, eligibility rules, and scoring weights beyond point values require a scope decision or further implementation. |
| Audit and deployment | OCA auditlog rules cover LMS create/write/delete changes on selected models. A separate production Compose template packages add-ons in an image behind TLS with a private database, secrets, health checks, and retained volumes. CI/static checker and isolated test Compose were added. The Performance Management dependency now assigns its default internal-user role through Odoo 19 `group_ids`, with a focused regression test. | The BRD's all-activity, non-editable audit requirement is not met by record-change logging alone: agree read/export/access coverage, immutable retention, and security acceptance. Set image digests, certificates, secrets, SSO/MFA, mail, backup, alerts, capacity, and restore targets. Run CI and staging checks. |

### Isolated verification completed on 2026-10-26

- `python scripts/check_lms_source.py`: parsed 34 Python and 19 XML files; all checked manifest references exist.
- `node --test custom_addons/learning_management/tests/lms_player.test.cjs`: 2 passed.
- Test Compose validation, production Compose validation with `deploy/production/env.example`, and scoped `git diff --check`: passed. The example environment is only a syntax check, not production configuration.
- Empty-database Odoo 19.0-20260926 install through `deploy/test/compose.yml`: **66 selected tests, 0 failures, 0 errors**. This includes KMS reviewer access, Odoo 19 user-group assignment, LMS course/assessment/certificate/security tests, three EDS routing tests, and the 14-stage KMS-to-LMS learner scenario.
- EDS upgrade on that installed test database, with the same filestore: **3 routing/feedback tests, 0 failures, 0 errors**.

These results cover the isolated test image and data. They do not establish a production-data upgrade, real-device behavior, throughput, identity integration, or operations readiness.

## Requirement interpretation and scope decisions

| Requirement | Release interpretation | Decision or dependency |
| --- | --- | --- |
| FR-LMS-011 superseded versions | Existing learners can finish an assigned version; new assignments use the latest published version. Historical attempts and certificates remain available to administrators. | The BRD says superseded versions become admin-only immediately. Confirm the continuity exception with PPDD and compliance before release. |
| FR-LMS-004–006 internal video, adaptive delivery, content protection | Private Odoo media and an authenticated MP4 Range player are the current delivery path. A bank-controlled HTTPS media host is allowed only when it enforces equivalent learner authorization. | Adaptive HLS/CDN packaging, watermarking, encryption/key management, and practical download deterrence need a media service design. Browsers cannot reliably prevent screen capture. Do not claim these controls are delivered. |
| FR-LMS-027–029 reminders and notifications | Odoo mail, activities, and scheduled assignment/expiry reconciliation provide the standard workflow. | Configure SMTP, cron, recipients, delivery monitoring, and the desired rule set in staging; bespoke notification-rule authoring is outside this release. |
| FR-ELN-001–005 integration | EDS routing and participant completion/certificate feedback, plus approved-gap assignment targeting, are the implemented links. | Outbound assessment scores, certifications, and competency achievements into competency profiles, career/succession development records, and CLC records (FR-ELN-004) are not implemented. Define ownership, target data contracts, and acceptance for those flows before claiming complete FR-ELN integration; align FR-ELN-005 analytics with available LMS/EDS measures. |
| FR-REC-001–008 recognition | Use the current points ledger, milestone messages, monthly honors, and shared recognition views as the baseline. | Validate the scoring/award jobs and decide whether employee-profile badges, configurable categories/eligibility/weights, supervisor alerts, and full HR recognition history are required for this release. Record accepted exceptions for any missing FR-REC behavior. |
| FR-MOB-001–003 and 008 phone access | Use the responsive authenticated Odoo web interface for learning, timed exams, and certificates. Server-side role and document rules apply to mobile sessions. | Connect the bank identity provider, provision each learner as an internal Odoo user linked to the correct `hr.employee`, and test MFA, session expiry, role changes, and representative phones. A login without that employee link cannot reach the authenticated learning media. Biometric login is an identity-provider/device decision. |
| FR-MOB-004–007 and 009 advanced mobile | Smaller layouts and progressive MP4 playback improve ordinary connected use. | Offline course/exam sync, adaptive video and compressed previews, native push, encrypted device cache, and device-loss revocation need a separate client and security design. They are not current-release claims. |
| Non-functional availability, DR, scale, and immutable audit | The deployment template supplies a private network, TLS edge, secrets, retained data, and log hooks. Current OCA rules capture changes on selected LMS models, not reads, exports, or every user activity. | Security and operations must agree the audit scope and prove access logging plus tamper-resistant retention. Operations must set and prove the concurrency target, 99.5% availability design, RTO/RPO, database plus filestore restore, and monitoring. |

## Remaining implementation decisions

1. **Legacy data audit.** Before upgrade, list published courses with missing/invalid lessons or assessments, HTML-only document lessons, default or inaccurate video durations, and in-progress exams without snapshots. Repair content through reviewed revisions; decide whether old exams finish under their original rules or are restarted. Reconcile existing EDS route failures and assignment campaigns. Preserve course, attempt, certificate, and HR history.
2. **Answer ordering.** Current question selection can randomize pools, but answer choices are not shuffled per attempt. The inactive authoring option is hidden and old enabled values are reset on upgrade so it cannot suggest this control is live. If the business needs it, add and test a stable per-attempt answer order before release; otherwise record an accepted scope change.
3. **Advanced mobile and media.** A native/offline client with encrypted expiring content, queued assessment submissions, conflict resolution, device revocation, and push is a separate project. Adaptive HLS also needs a private rendition pipeline, authorized playlist/segment delivery, and tested key/content policy. Plan those once supported devices, bandwidth targets, and security rules are set.
4. **Operations inputs.** IT must supply the identity provider configuration, SMTP, TLS certificates, pinned image digests, backup destination, retention store, bank-controlled HTTPS media hosts and their allowlist, media storage, target concurrency, RTO/RPO, and ownership for incident response. The deployment template deliberately contains placeholders.
5. **Audit scope.** The BRD asks for non-editable logs of all user activities. Decide which read, export, login, media access, and administrative events must be retained; measure the cost of logging them; and agree controlled, immutable retention before claiming this requirement complete.
6. **Recognition and downstream learning records.** Decide the FR-REC profile/configuration/supervisor requirements and the FR-ELN-004 destinations, record owners, data contracts, retry rules, and historical backfill policy. Limit release claims to the points, monthly awards, EDS feedback, and LMS reports actually verified.

## Release sequence and gates

### UI/UX acceptance route

| Journey | Check on desktop and representative phones | Pass condition |
| --- | --- | --- |
| Learner dashboard | Due and overdue assignments, locked prerequisites, progress, and the next lesson action. | A learner can find and resume the correct course without navigating an administrator menu; inaccessible actions show a clear reason. |
| Content playback | MP4 resume, pause/end save, document opening, text acknowledgment, and recovery after a slow or interrupted connection. | Progress is retained, the next required step is clear, and video credit matches the actual file duration. |
| Exam and certificate | Timed exam deadline, answer selection and submission, expired-session response, certificate PDF and verification status. | Small-screen controls and messages remain usable with touch and keyboard; server time and attempt rules are enforced. |
| Author and reviewer | Draft content checks, assigned review activity, publication errors, revision creation, and mobile read-only inspection. | The reviewer can approve a complete version and cannot accidentally edit or publish an incomplete one. |
| Manager and auditor | Assignment campaigns, renewal, branch compliance filters, certificate revocation, and audit evidence. | Figures reconcile to underlying enrollments and valid certificates; unauthorized actions fail through both UI and direct requests. |

The Odoo web client is the mobile surface for this release. Acceptance must cover the bank's supported devices and browsers, portrait and landscape layouts, screen-reader/keyboard paths, and the agreed low-bandwidth profile. Timed exam countdown or autosave enhancements should be decided from device UAT rather than presumed delivered.

### 1. Freeze and inspect the candidate

**Owners:** Odoo development lead and release manager.

- Review the already modified repository, select the intended files (including untracked LMS player assets, tests, migrations, and deployment files), and record one release commit. Keep the development Compose separate from `deploy/production/`.
- Run `python scripts/check_lms_source.py`, the player Node tests, the LMS Odoo suite, and the targeted EDS routing suite after LMS installation through `deploy/test/compose.yml` or CI. Run broader ERP regression on staging. The new tests cover publication, recertification, routing, and campaign reconciliation.
- Run clean module install, then upgrade a production-like database plus filestore. Inspect legacy constraints, published content, exam attempts, EDS mappings, and audit rules. Confirm the EDS 19.0.1.1.57 migration activates nightly reconciliation. Save migration and rollback logs.
- Resolve baseline dependency warnings in staging: inventory existing HR rows with missing job grade or operating unit and obtain approved values before enforcing their required constraints; review the table-less competency validator model/ACL and view access warnings. Verify the repaired Performance Management role assignment with the bank's provisioning and deprovisioning flow. Do not invent HR values during migration.

### 2. Stage and accept the workflow

**Owners:** QA, PPDD/learning owners, EDS/HR owners, and security reviewers.

- Use learner, course owner, reviewer, LMS manager, EDS/HR, branch manager, and auditor accounts. Try both valid actions and unauthorized ORM/RPC/HTTP requests.
- Verify identity provisioning and deprovisioning for learners: an internal Odoo user must resolve to the intended `hr.employee`; test an unlinked user, a transfer, and a disabled account on desktop and mobile before bank-wide rollout.
- Complete a representative mandatory path: assignment → phone learning → pre/post exam → certificate → HR history → EDS participant status → compliance report. Include new hire, transfer, expired certificate, second attempt, failed email retry, and interrupted video.
- Verify the supported phone sizes and browsers, keyboard/touch controls, timed exams, PDF output, actual video durations, interrupted playback, accessibility, mail delivery, branch visibility, audit retention, and agreed performance and low-bandwidth targets.

### 3. Rehearse operations and release

**Owners:** IT operations, identity/security, and the business release owner.

- Build a digest-pinned image. Configure secrets, TLS, SSO/MFA, SMTP, `dbfilter`, cron, log forwarding, backups, metrics, and alerts. Test database **and filestore** restore against approved RTO/RPO.
- Rehearse deploy and rollback on the same candidate. Approve a pilot group, monitor its first reminder/expiry cycle, then widen access after product, IT/security, and operations sign-off.

**Release gate:** no production cutover until the exact candidate passes install/upgrade tests, user and access UAT, identity/media checks, backup restore, and the accepted requirement traceability list. Any future-scope BRD item must have a recorded scope decision rather than being silently marked complete.
