# Learning Management: end-to-end manual UAT

**Use with:** Odoo 19, `learning_management` and its installed dependencies.

**Run ID:** __________ **Database / URL:** __________ **Build or commit:** __________

**Test dates:** __________ **QA lead:** __________ **Business owner:** __________

This is a repeatable **manual test script** for a disposable UAT database or an approved staging copy. It follows the page-by-page style of `../docs/guides/EDS_PRODUCTION_UAT_AND_OPERATIONAL_GUIDE.md`, but its expected results are based on the current LMS code. Record actual results and screenshots; do not mark a step passed merely because an automated unit test passed. Use synthetic people and training content. Never manipulate production certificates or backdate production records to run expiry tests.

## 1. Run rules and evidence

- Run sections **2–8 in order** for the main journey. Run sections **9–12** on the same data, except where a step asks for a separate test record. The LMS root tile and **My Learning** menu must open before creating data; a blank learner dashboard is valid, a frozen launcher or error is not.
- For every case, record `Pass / Fail / Blocked / Not applicable`, tester, time, browser/device, record IDs, expected versus actual result, and a defect link. Capture the complete error text and the browser Network response for failures. Never attach session cookies, passwords, private HR details, exam answer keys, or full production videos to tickets.
- Use an incognito/private window or a separate browser profile per persona. Sign out before changing persona. Do not grant all users Administrator access just to make a screen work.
- Treat `Blocked` as a gate: record the prerequisite (for example SMTP, EDS sample course, supported phone, or a staging-only job run) and owner. Retest after fixing it.
- A site-wide Odoo error, access leak, failed exam integrity gate, incorrect certificate validity, or inaccessible assigned learning is a release blocker. Cosmetic issues still need a defect and an agreed disposition.

### Execution log (copy one row per case)

| Case | Persona / device | Actual result and record ID | Evidence link | Status | Defect / owner |
| --- | --- | --- | --- | --- | --- |
| NAV-01 | | | | | |
| AUTH-01 | | | | | |
| COURSE-01 | | | | | |

## 2. Environment and accounts

### 2.1 Starting state

1. Have an Odoo 19 staging database with `learning_management`, `employee_development_system`, HR, Competency, Knowledge Management, and Recognition installed. Record module versions and exact Git commit/image. For an **upgrade** rehearsal, use a separately restored production-like database **and filestore**, and preserve a rollback snapshot. A clean install alone does not exercise legacy data.
2. Confirm Odoo scheduled actions are enabled in staging, mail is routed to a test mailbox, `web.base.url` points to this staging host, the filestore persists across restarts, and a test administrator can reach **Settings → Technical → Automation → Scheduled Actions**. Only an administrator should manually run scheduled jobs.
3. Prepare a real playable, bank-approved **60-second MP4** (`uat_lms_60s.mp4`) and a harmless one-page PDF (`uat_lms_reading.pdf`). Record the MP4's actual duration with a media inspector and enter the same number of seconds in the lesson. The file must live in the test filestore after upload. Avoid a fake or truncated file: playback UAT cannot be inferred from an upload control.
4. Agree the supported desktop and mobile browsers, phone models, OS versions, viewport sizes, accessibility tools, and low-bandwidth profile before execution. Minimum practical run: desktop Chromium, Android Chrome, and iPhone Safari; test portrait and landscape on phones. Use HTTPS for real-phone access to a reachable staging hostname; `localhost` on a phone points to the phone itself.
5. Verify the existing LMS category **AML/CFT & Regulatory Compliance** and certificate template **Bunna Bank Standard Certificate of Achievement**. If either is absent, record an install/data defect. Do not silently recreate seeded records.

### 2.2 Personas and permissions

Create distinct internal Odoo users and link each learner to a distinct active `hr.employee` via the employee's **Related User / User Account** field. Give the employees different departments and branches/operating units so cross-user checks are meaningful. The names below are synthetic.

| ID | Example login | Groups / purpose |
| --- | --- | --- |
| SYS | `uat.lms.sys` | Odoo Settings administrator, for setup, scheduled jobs, and technical evidence only. |
| AUTH | `uat.lms.author` | **Learning Management: Instructor / Course Creator**; owns course content. Link to an employee. |
| REV | `uat.lms.reviewer` | **Learning Management: Training Manager / L&D Officer**; assigned reviewer and campaign dispatcher. Link to an employee. |
| L1 | `uat.lms.learner1` | Internal user with the implied **Learner / Employee** LMS group; linked employee in Branch A. Main mobile learner. |
| L2 | `uat.lms.learner2` | Separate learner, Branch B; deliberately **not enrolled** in the core course at first. |
| MGR | `uat.lms.line.manager` | HR line manager of L1; ordinary LMS learner unless explicitly granted an LMS manager role. Used for reminder and segregation checks. |
| EDS | `uat.eds.manager` | **EDS Administrator** (which implies EDS Manager) so the **Employee Development → Configuration → LMS Routing** menu is visible and its manager-only sync actions are permitted. Link this user to an employee for routed course ownership. |
| HR | `uat.hr.officer` | Authorized HR user to inspect employee training history and documents, without making this user an LMS manager. |

The current LMS has learner, instructor, manager, and administrator groups. It has **no separate read-only LMS auditor group**, and an LMS manager's configured rules allow bank-wide LMS records. Do not infer branch-limited manager access from the report filters. If the bank requires a read-only auditor or branch-limited LMS manager, record a security scope decision/defect before production.

### 2.3 Test records to build

Use a unique run suffix, for example `UAT26-001`, on every name. Record generated course codes and IDs after saving.

| Record | Test values / purpose |
| --- | --- |
| Foundation course | `UAT26-001 Foundation`: one mandatory **text** lesson, no pre/final assessment, no certificate; published first. |
| Core course | `UAT26-001 Connected Learning`: mandatory, category AML/CFT, pre-assessment enabled, final assessment enabled, certificate enabled, template above, **1-month** validity, 70% course pass threshold. |
| Core lessons, in order | `1 Reading` rich text; `2 Policy PDF` with real PDF; `3 Video` with 60-second MP4, duration 60 seconds, anti-skip enabled, minimum watch 90%; `4 Checkpoint` linked to a module quiz. All mandatory. |
| Pre-assessment | One single-choice question, 2 options, one correct; 100% pass, 2 attempts, 0 cooldown, timed 5 minutes. Turn **Draw Random Questions from Category Pools** off to expose the Fixed Question Bank. |
| Module quiz | One single-choice question, 2 options, one correct; 100% pass, 2 attempts, 0 cooldown, timed 5 minutes. Turn the random-pool option off. |
| Final assessment | Two single-choice questions worth 1 point each, 2 options each, one correct per question; 70% pass, 2 attempts, 0 cooldown, timed 10 minutes. Turn the random-pool option off. This permits an intentional first score of 50%, then 100%. |
| Learning path | `UAT26-001 Path`, stages Foundation then Core, no optional branch. |
| Campaign | `UAT26-001 Main Campaign`, assign the **path** to L1 only, mandatory, due in 14 days. |

Use these harmless question texts and answer choices so a second tester can reproduce the 0%, 50%, and 100% scores. Enter each question's title, full question text, and two answer rows; mark only the listed correct row **Correct Answer**. Put a short, nonempty instruction on every assessment.

| Question / assessment | Question text | Correct choice | Incorrect choice |
| --- | --- | --- | --- |
| `UAT PRE 1` / Pre | Which action should a learner use to begin an assigned course? | `Open the assigned course` | `Edit the certificate` |
| `UAT QUIZ 1` / Checkpoint | When can a learner confirm a text or PDF lesson was reviewed? | `Open the lesson before confirming review` | `Confirm review without opening it` |
| `UAT FINAL 1` / Final | Which LMS menu shows assigned courses? | `My Learning` | `System Settings` |
| `UAT FINAL 2` / Final | Which LMS menu lists earned certificates? | `Issued Certificates` | `Question Bank` |

## 3. Navigation, identity, and desktop entry

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| NAV-01 | SYS, desktop | Sign in; click the **Learning Management** app tile. Repeat from the app launcher after another app. Click **My Learning → Assigned Courses**. | The tile opens **My Active Courses** (even if empty), menus respond, and the URL/action settles without a full-screen launcher, browser console error, or Odoo traceback. Capture both tile and resulting page. |
| NAV-02 | L1, desktop | Sign in; open LMS tile, **My Learning → Course Catalog**, **Completed & History**, and **Certifications → Issued Certificates**. | Each view loads. Before assignment, dashboard/history/certificates may be empty. L1 does not see manager-only **Learner Tracking**, **Compliance & Analytics**, or **Assignment Campaigns**. |
| NAV-03 | AUTH and REV, desktop | Open LMS tile. AUTH visits **Course Administration → All Courses**, **Assessments & Quizzes → Question Bank / Assessments**. REV also visits **Awaiting Approval** and **Assignment Campaigns**. | Correct menus and list/form views load without access errors. AUTH cannot dispatch a campaign or approve another review; REV can see those actions. |
| AUTH-01 | SYS | Inspect each test user's Groups and employee link. Log in as L1 and L2 separately. | L1 and L2 resolve to their own `hr.employee` and are not interchangeable. Record user ID, employee ID, department, and operating unit (use synthetic data only). |
| AUTH-02 | SYS | Create a separate internal user **without** an employee link. Open LMS and attempt a lesson video URL and exam. | Media returns **403** and exam cannot begin; no other learner's progress is exposed. An empty dashboard alone is not proof of correct identity setup. |

If **NAV-01** fails, stop this script and log a navigation defect with the exact URL, timestamp, browser console error, failed Network request, server traceback, and whether **My Learning → Assigned Courses** works. Do not continue with content UAT through an administrator bookmark while the root tile remains broken.

## 4. Authoring, review, and assignment

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| COURSE-01 | AUTH | In **Course Administration → All Courses**, clear the default **Published & Active** search filter so drafts remain findable. Create Foundation with category, description, instructor AUTH, one rich-text lesson, `Requires Post-Course Final Assessment = off`, `Issue Certificate on Completion = off`. Save and note code. | Draft course and text lesson persist. |
| COURSE-02 | AUTH | Create Core with the values in §2.3. Save before linking assessments. Add one **Curriculum Section / Module**, then the four lessons in that section with sequence 10, 20, 30, 40. For the video choose **Direct Video File Upload (Internal Storage)**, upload MP4, set **Video Length (Seconds) = 60**, anti-skip on, minimum watch 90. Upload the PDF as a **Document / PDF Slide Deck** lesson; put actual HTML content in the text lesson. | Each lesson belongs to Core, ordered as intended. Real video/document binaries survive reload. The duration displayed matches the inspected file. |
| EXAM-01 | AUTH | In **Assessments & Quizzes → Question Bank**, create four distinct questions with the options from §2.3, marking exactly one option correct on each. In **Assessments**, create Pre (**Pre-Course Diagnostic Assessment**), Checkpoint (**Mid-Module Checkpoint Quiz**), and Final (**Post-Course Final Assessment (Certification Gate)**) for Core. For each, turn **Draw Random Questions from Category Pools** off, set instructions, timing, 2 attempts, **0 cooldown**, pass score, and Fixed Question Bank. Link them in the Core course and quiz lesson. | All assessments point to Core with the correct type; answer options and scores save. Final has exactly two 1-point questions. Answer-key fields are not available to a learner. |
| COURSE-03 | AUTH | On separate **otherwise publication-ready** drafts, omit only the video duration in one and only the PDF upload in another. Try **Submit for Approval**; if they enter review, have REV try **Approve & Publish**. | Submission may enter review after the basic lesson check, but publication is blocked for the intended missing material, not an unrelated missing assessment. Record each precise message. REV can return disposable records to draft before AUTH deletes them. |
| COURSE-04 | AUTH | Submit Foundation and Core with **Submit for Approval**, assigning REV as **Reviewer**. | State becomes **Review**, REV receives a targeted review notification/activity, and reviewed content cannot be edited directly. |
| COURSE-05 | REV | Open **Course Administration → Awaiting Approval**; review lessons, duration, question bank, audience, certificates. Use **Return to Draft** on Foundation once; AUTH edits and resubmits; REV then **Approve & Publish** both. | Only assigned active LMS manager REV can publish. Both states become **Published**, latest version true. Course codes and version remain recorded. |
| COURSE-06 | AUTH, L1 | Try to edit a published lesson, question answer, and course policy as AUTH. Try viewing a draft course in L1's catalog. | Direct mutation is blocked; L1 sees only eligible published catalog items. Direct ORM/RPC checks in §11 must also fail. |
| PATH-01 | AUTH | In **Course Administration → Learning Paths**, create the path with Foundation stage first and Core second. Save. | Both stages appear in order; Core is locked until Foundation completion for a learner assigned the path. |
| ASSIGN-01 | REV | In **Course Administration → Assignment Campaigns**, create the individual, mandatory, 14-day path campaign targeting **L1 only**. Click **Execute Campaign & Enroll Learners**. | Campaign becomes **Dispatched & Enrolled**; exactly one Foundation and one Core enrollment exist for L1, Core is locked, and L1 gets an assignment notification. L2 gets none. Capture campaign ID and enrollment IDs. |
| ASSIGN-02 | REV | Reopen the executed campaign and run the **LMS: Reconcile Assignment Campaigns** scheduled action once from SYS (or wait for its normal schedule); run it a second time. | No duplicate delivery/enrollment for L1. Do not use **Execute** again: that button is intentionally for drafts only. Record before/after counts. |
| ASSIGN-03 | REV, SYS | On a separate published course, create a department/branch/role/grade campaign in staging, then add/transfer a synthetic employee into scope and run the reconciliation job. | Only matching active employees gain one enrollment. A nonmatching employee does not. Record the exact audience rule and before/after employee IDs. For a competency-filtered campaign, use only an approved, current primary gap line and verify unrelated/draft gaps are excluded. |

## 5. Learner desktop and connected mobile journey

Run the same enrolled L1 account on desktop first and then phone. Keep both browsers signed into L1; verify that server-saved progress follows the account. Do **not** try to install a separate native LMS app: the supported current surface is Odoo's responsive authenticated web client.

| Case | Actor / device | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| LEARN-01 | L1 desktop | Open **My Learning → Assigned Courses**. Inspect the two cards; open locked Core and confirm **Start / Resume Learning** is absent; then open Foundation. A technical tester can attempt the locked action directly in SEC-06. | Mandatory/due badges and progress are readable. Core says prerequisites pending and blocks content. Foundation opens its next lesson. |
| LEARN-02 | L1 desktop | In Foundation **My Lessons**, click **Confirm reviewed** before **Open Lesson**; then open the text and read it; return and click **Confirm reviewed**. | Early confirmation is rejected. After opening, state becomes completed with opened/reviewed timestamps and learner acknowledgment; Foundation enrollment completes. Core unlocks on refresh. |
| LEARN-03 | L1 phone | Sign in through the phone browser at the staging HTTPS URL. Open LMS tile, **My Learning**, Core, and **Take Pre-Assessment**. Fail once intentionally and then pass the second attempt. | The dashboard/card/form fit the small screen without horizontal clipping or hidden primary controls. Core content remains blocked after failed pre-test, then becomes available after pass. Each result is tied to L1's own attempt. |
| LEARN-04 | L1 phone | Tap **Start / Resume Learning**; open `1 Reading`, then return and **Confirm reviewed**. Open `2 Policy PDF`, inspect it in the browser/PDF viewer, then return and **Confirm reviewed**. | Start opens the next required lesson, not an admin list. The PDF can be zoomed/read. Confirming each is possible only after opening. Progress updates on desktop after refresh. |
| LEARN-05 | L1 phone | Open `3 Video` through **Open Lesson**. Play normally past 20 seconds, pause, switch apps for 10 seconds, return; close the tab and reopen **Start / Resume Learning**. | Authenticated player loads and remains usable by touch. The position/progress save and resume near the last allowed point; no false completion occurs on pause, tab close, or inactivity. See §6 for stream protocol checks. |
| LEARN-06 | L1 phone | Finish at least 90% of the 60-second video at normal speed. Return to enrollment. | Video progress becomes complete from server-backed watch credit, with `Video Watch Threshold` evidence; next lesson becomes available. The exact timing may vary by heartbeat interval, so verify status rather than a single frame. |
| LEARN-07 | L1 phone | Open `4 Checkpoint`, answer incorrectly once and then correctly on the allowed second attempt. Refresh the enrollment and inspect **My Lessons** before attempting the final. | First result fails and does not complete the quiz lesson; second passes and the quiz progress completes. A third attempt is not available after cap. **If the passed quiz remains incomplete, stop here and log a release-blocking defect; do not use a manager completion override.** |
| LEARN-08 | L1 phone | Tap **Take Final Assessment**. Answer one of two questions correctly (50%); submit. Start final again, answer both correctly (100%); submit. | First attempt fails without certificate and within configured cap; second passes. Enrollment becomes **Completed** with final score and a certificate, and leaves **My Active Courses** after refresh. The question/answer display, Save, and Submit stay usable in portrait and landscape. |
| LEARN-09 | L1 phone and desktop | Open **Completed & History**, reopen the completed course and its certificate. Repeat in a second browser. | Completion and progress are persistent across sessions/devices; historical attempt numbers and timestamps remain. The learner can read only their own records. |
| LEARN-10 | L2 desktop/phone | Open catalog and attempt to reach L1's enrollment, exam, document, certificate, and video by copied direct links/IDs. | L2 cannot read or alter L1's private records or stream L1-only lessons. A public certificate **verification** page is intentionally public and shows only its designed validation details; it must not expose the PDF or HR record. |

### Mobile UX observation sheet

For each supported phone/browser, record model, OS, browser version, width × height, orientation, network, and screenshots of: app tile → dashboard → course form → text/PDF → video player → exam answer form → certificate PDF. Check touch target size, visible focus, font scaling at 200%, keyboard/screen-reader traversal, modal and soft-keyboard behavior, back navigation, error messages, session expiry and sign-in return. Repeat once with a slow connection. Log specific defects; a generic “mobile passed” is not enough.

## 6. Video streaming and media security

Use the uploaded file lesson's numeric ID from the player URL (`/lms/video/<lesson-id>/player`). The `<lesson-id>` below is that **lesson** ID, not the course ID. Inspect Network responses in the browser; do not include authentication cookies in evidence.

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| MEDIA-01 | L1 | Open the player; inspect the stream request and the Network **Response Headers**. | Video bytes arrive from `/lms/video/<lesson-id>/stream`, with `Content-Type` appropriate for the file, `Accept-Ranges: bytes`, and `Cache-Control: private, no-store`. A normal first request may be HTTP **200** or **206**, depending on the browser. |
| MEDIA-02 | L1, browser DevTools | While signed in, run the following in the player tab console, substituting the actual ID: `fetch('/lms/video/123/stream', {headers: {Range: 'bytes=0-1023'}, credentials: 'same-origin'}).then(r => console.log(r.status, r.headers.get('Content-Range'), r.headers.get('Content-Length')))` | HTTP **206**, `Content-Range: bytes 0-1023/<actual size>`, `Content-Length: 1024` for a file at least 1024 bytes. This checks the real endpoint, not only the player widget. |
| MEDIA-03 | L1, DevTools | Repeat with `Range: 'bytes=999999999999-'` and inspect status/header. | HTTP **416** with `Content-Range: bytes */<actual size>`; no whole-file fallback. |
| MEDIA-04 | L1 phone | Before the required watch threshold, drag the playhead far ahead and attempt the next mandatory lesson/final exam. | Player/server refuse unearned watch credit; video lesson remains incomplete and the later gate remains closed. Seeking backward is allowed for review. |
| MEDIA-05 | L1 phone | Use browser network throttling and then a real weak connection; interrupt connectivity mid-play, restore it, pause/end playback, close/reopen. | Player shows a recoverable network state; credited position is never greater than watched time, and resume survives reconnect. Capture if the video cannot buffer under the agreed bandwidth profile as a performance defect, not as evidence of adaptive streaming. |
| MEDIA-06 | L2 / unlinked user | Paste the same player, stream, document, and `.m3u8` URLs into a separate signed-in session. Also try while signed out. | Unassigned/unlinked user receives **403** for protected media; signed-out access requires login. No media bytes leak. Document response is `private, no-store` when authorized. |
| MEDIA-07 | REV / L1 | REV tries publishing a **separate, otherwise complete draft** with an external HTTP/unapproved HTTPS video URL. Do not change the approved main course. L1 opens the uploaded MP4's `.m3u8` URL after satisfying its course gates. | Publication refuses unapproved media host. The approved run uses uploaded MP4; the HLS manifest route for that MP4 returns **501** because HLS packaging is not delivered. |

If an approved bank media URL is enabled later, repeat access tests at both Odoo redirect and media host. A redirect alone does not make the host private; the host must independently authorize the learner. Do not use a public video URL as a substitute for this test.

## 7. Exams, certificate, renewal, and version history

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| EXAM-02 | L1 | On a separate timed test attempt, leave the exam open beyond its configured deadline. Try editing/submitting after deadline; ask SYS to run **LMS: Submit Expired Timed Exams** if the normal 5-minute job has not run. | Server deadline governs; late edits are rejected or the saved answers are auto-graded. The outcome has one submitted/passed/failed record, not duplicate submissions. Record server time and deadline. |
| EXAM-03 | AUTH / L1 | Start a separate exam attempt, then try changing its question, correct answer, point weight, or pass score. Use a course revision for any legitimate future change. | Reviewed/published source is frozen; the active attempt retains the question/answer/policy snapshot it began with. No learner can edit grading fields through the UI or RPC. |
| EXAM-04 | L1 | Have AUTH prepare and REV publish a separate course/assessment with a 1-hour cooldown. Fail it and immediately retry. On the main Final, attempt a third start after two graded attempts. | Cooldown and attempt-cap messages are enforced by the server. Do not wait an hour to prove the immediate block; use a fresh case or authorized time-controlled test environment to prove later retry. |
| CERT-01 | L1, REV, HR | After LEARN-08, open **Certifications → Issued Certificates**. Inspect serial, security code, PDF, issue/expiry date, score, and `PDF / HR Delivery`. HR inspects the linked **HR Training History** and **Employee Document**. | One certificate for the completed attempt; PDF opens on desktop and phone; delivery is `Complete`, and both HR links are populated. The date interval matches one-month validity. Failed attempt has none. |
| CERT-02 | L2, public browser | Copy the **Verification URL** from L1's certificate; open it in a signed-out browser, then alter one character of the code. | Valid code verifies the current status; altered code is not found. No session/HR/PDF data is leaked. |
| CERT-03 | REV | On a **separate disposable completed enrollment/certificate**, click **Revoke**, enter a reason, confirm, then open public verification again. | Reason, actor, timestamp, and revoked state are saved; public verification no longer treats it as valid. Learner cannot revoke or rewrite certificate fields. Keep the main golden-path certificate valid for other cases. |
| CERT-04 | SYS / REV | In a disposable staging record, simulate an expiry through an authorized test fixture or advance a separate test environment clock; run **LMS: Check Certification Validity Expiry** twice. | Certificate becomes expired once; one active mandatory renewal attempt appears with a due date; old certificate, score, and HR history stay intact. Never manually change a signed production certificate to manufacture this state. |
| CERT-05 | L1 | On a separate near-expiry completed enrollment, click **Renew Course**; on a far-from-expiry valid certificate, try the same. | Near-expiry renewal opens one new enrollment attempt; repeated click reuses it. Early renewal is blocked for ordinary learner. Manager can arrange a repeat under policy. |
| VERSION-01 | AUTH / REV | On **published** Core, click **Initiate Version Update**. Edit the new draft's lesson/assessment and revision notes; submit; REV publishes it. REV creates a new individual campaign for L2 using the published successor. | A new version copies curriculum and its own question/answer bank; old version archives and is no longer offered for new assignments. Existing L1 can still read their frozen assigned version/history. New L2 enrollment targets the latest published version. |
| VERSION-02 | REV | Try to create/dispatch a campaign for archived Core; try publishing two competing draft successors of one predecessor. | Archived version cannot be newly assigned. Only one successor can be published. Record the message; do not destroy historical records. |

## 8. EDS, HR, KMS, competency, and recognition

These are integration tests. Use staging records owned by the respective application teams; if a team has not provided a valid source workflow, mark that case **Blocked**, not passed.

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| EDS-01 | EDS | In **Employee Development → Configuration → LMS Routing**, create/open a route for an approved EDS e-learning course whose creator or EDS user has an employee link. Use a session with an L1 participant in EDS state **Enrolled** or **Completed**. Click **Sync to LMS**. | Route becomes synced and points to an LMS **draft shell**. Learners are not prematurely enrolled in unpublished material. Repeating sync does not create a second shell. |
| EDS-02 | AUTH / REV / EDS | Add legitimate lessons/assessments to that shell, review and publish it. On the EDS route click **Sync Participants**, then repeat. | L1 gains one LMS enrollment; no duplicate on retry. A draft shell refuses participant sync. Note EDS course, route, LMS course, and enrollment IDs. |
| EDS-03 | L1 / EDS | Complete the routed course; on route click **Refresh Completion** (or wait for nightly sync). Inspect the EDS participant's **Linked Online Learning** fields and route completion percent. | LMS completion date/state and certificate validity reflect the actual LMS record. Repeating reconciliation is idempotent; expired/revoked certificates do not appear valid. |
| HR-01 | HR | Inspect L1 employee record after CERT-01: training history and attached LMS training certificate document. Then inspect a second failed attempt. | Passed completion has one matching history and PDF document; failed attempt has none. Certificate number/course/employee match LMS. Retry PDF/HR sync on a separate failed-delivery fixture creates no duplicate HR rows. |
| KMS-01 | AUTH / KMS reviewer | Publish an approved KMS digital-library item through its normal review workflow and associate it with the latest LMS course. Open the course/library link as authorized roles; also try an unapproved/restricted KMS item with a learner. | Approved resource is linked and opens for its permitted audience; reviewer notifications work without granting unrelated private HR access. KMS access rules still govern the source record. If unapproved/restricted material becomes visible to a learner, log a release-blocking access defect. |
| COMP-01 | Competency owner / REV | Create an approved current **primary reporting line** assessment gap for L1 and a draft/older/unrelated gap for L2; create an LMS assignment campaign with **Target Competency Gap Focus** and run dispatch/reconcile. | L1 is matched once; L2's draft/old gap does not qualify. Preserve the competency source reference as evidence. This is inbound gap targeting, not a claim that LMS scores update competency profiles. |
| REC-01 | REV / L1 / SYS | After a completed course and passed exam, inspect **Recognition → Learning Points Ledger**, **Gamification Leaderboards**, and **Best Scorer of the Month**. The monthly job considers **the previous calendar month**; use a separately prepared, authorized staging fixture with a completion in that month, then have SYS run **LMS: Calculate Best Scorer of the Month** twice. | Points/milestones are traceable to the learner event; repeated job does not create duplicate monthly honors. Record the date window and eligibility. A course completed only this month should not create last month's award. |
| REPORT-01 | REV | Open **Learner Tracking → All Enrollments** and **Compliance & Analytics → Branch Compliance Matrix / Course Engagement & Analytics**. Filter by branch, department, course; compare counts with the actual enrollment/certificate records, including archived versions and expired/revoked certificates. | Report numerators/denominators reconcile to source records under the documented valid-certificate policy. Ordinary L1/L2 do not see manager reports. Record filter, counts, and source IDs. |

## 9. Notifications, scheduled jobs, and failure recovery

| Case | Actor | Steps | Expected result / evidence |
| --- | --- | --- | --- |
| OPS-01 | REV / L1 | Review campaign assignment, progress 50%/100%, completion, and review activities in Odoo chatter/inbox and the staging mail sink. | Correct recipient, course, action link, and event time; no notification to L2. Actual email delivery depends on configured SMTP/queue; separate in-app creation from external delivery evidence. |
| OPS-02 | SYS / MGR | On a disposable mandatory enrollment set due within configured reminder window; run **LMS: Send Overdue and Nearing-Deadline Mandatory Reminders** twice. Repeat with an overdue record. | One reminder per configured interval, learner recipient correct, line manager added only for overdue if that setting is enabled. Second immediate run does not duplicate. |
| OPS-03 | SYS / REV | On a staging certificate with intentionally failed PDF/HR delivery, inspect error, repair the missing dependency, click **Retry PDF / HR Sync** or run its hourly job twice. | Delivery moves to `Complete`; existing PDF, HR history, and document are reused, not duplicated. Retain the original error and retry result. |
| OPS-04 | SYS | Restart Odoo while keeping database **and filestore**, then replay an authorized stream, open the PDF and certificate, and resume L1 progress. | Attachments and server progress survive. A database-only restore is insufficient; rehearse combined restore separately before deployment. |
| OPS-05 | SYS | Inspect OCA `auditlog` rules for selected LMS models; perform a draft create/edit and an authorized revocation. Inspect entries using the bank's authorized audit viewer. | Selected create/write/delete changes can be traced to actor/time/record. **Read, export, media access, login, and immutable retention are not covered by this check**; raise a separate security acceptance item rather than marking the BRD's all-activity audit complete. |

## 10. Negative access and direct-request checks

Menu hiding is not an access test. A technical tester should repeat these through Odoo's authenticated RPC/ORM harness or equivalent requests using the **same non-admin persona**; never run them as `sudo` or an administrator. Record model, record ID, method, user ID, response, and denied/allowed result. Do not include tokens/cookies in the report.

| Case | Non-admin actor and attempted action | Expected result |
| --- | --- | --- |
| SEC-01 | L2 read/write L1 enrollment, lesson progress, exam attempt/answer, or certificate by known ID. | Access denied/no private data, even if a direct URL is pasted. |
| SEC-02 | L1 create a certificate, change grade/result/progress timestamps, select another employee for an exam, submit another learner's exam, or call a completion method on a locked lesson. | Server denies mutation; learner cannot award themselves completion. |
| SEC-03 | AUTH publish/archive without being the assigned manager reviewer; call `write({'state': 'published'})` directly; alter a reviewed/published lesson or correct answer. | Server rejects unauthorized transition/edit, not just a hidden button. |
| SEC-04 | L1 or AUTH execute an assignment campaign or revoke a certificate by direct method call. | Only LMS manager workflow succeeds; revocation requires a reason and produces actor/timestamp evidence. |
| SEC-05 | L2 request L1's protected player/stream/document, including a valid `Range` header; unlinked user request same. | **403** with no protected bytes. Public verification route remains the intentional narrow exception. |
| SEC-06 | L1 start post-assessment before mandatory lessons, start quiz before earlier lessons, bypass pre-assessment, or replay an exhausted/timed-out exam. | Server rejects each gate and preserves the prior attempt record. |

## 11. UI, accessibility, and performance acceptance

| Case | Steps | Pass evidence |
| --- | --- | --- |
| UX-01 | Keyboard-only navigate app tile, learner card, lesson, exam answer checkbox/radio, Submit, certificate link. Repeat with a screen reader. | Logical focus and labels, visible focus indicator, error/status announced, no keyboard trap. Log exact control/phone/reader defects. |
| UX-02 | At 200% text zoom and narrow portrait, repeat dashboard, player, exam, and PDF. Rotate to landscape mid-exam. | Primary buttons, displayed deadline, choices, and feedback remain legible and reachable; no lost saved answer. The server deadline remains authoritative; a visual countdown is not part of the current exam view. |
| PERF-01 | Use the agreed concurrent learner count and a representative large MP4 on staging. Measure dashboard load, first frame, seek/resume, answer save, exam submit, and PDF generation across branches. | Attach measured p50/p95, error rate, network profile, database/worker load, and bank-approved thresholds. The repository provides no production capacity proof or universal latency threshold. |
| PERF-02 | Test session expiry and account deactivation during playback/exam on phone. | Subsequent protected requests require reauthentication or are denied; after authorized return, saved progress/answers follow the server record without exposing another learner. |

## 12. Scope boundary and sign-off

**Current release acceptance target:** connected Odoo web on desktop/phone, authenticated MP4 with HTTP Range and server watch credit, text/PDF lessons, question/assessment gates, course review and versions, assignment/renewal, certificate PDF/verification/HR links, EDS routing/feedback, inbound approved competency-gap targeting, recognition baseline, and the specified Odoo reports.

**Not current-release pass criteria:** native iOS/Android LMS app, offline video/course/exam sync, device encrypted cache or revocation, adaptive HLS/CDN renditions, native push, biometric login, full outbound LMS score/certification propagation into competency/career/CLC, configurable recognition policy/profile badges, and all-activity immutable audit. The HLS placeholder returning 501 is expected for the uploaded MP4. Test these only after their architecture and acceptance requirements are approved; never mark them passed from this web UAT.

### Final handover checklist

- [ ] NAV-01 root tile opens on the exact release candidate; all persona menus work.
- [ ] Main desktop/mobile learning path, real MP4, PDF, exam fail/retry/pass, and certificate evidence attached.
- [ ] Stream 206/416/403 and resume/anti-skip/weak-network checks recorded.
- [ ] Course review, assignment, version, renewal, HR, EDS, KMS, competency, recognition, reports, and negative access cases resolved or explicitly blocked with owners.
- [ ] Scheduled jobs, SMTP, database **plus filestore** restore, production-like upgrade, browser/device matrix, load target, and security/audit scope accepted by their owners.
- [ ] Every failed case has a defect ID, severity, owner, retest result, and release decision. Business owner signs the actual tested commit/image, not a different build.

| QA lead | L&D owner | HR/EDS owner | IT/identity owner | Security owner | Release decision/date |
| --- | --- | --- | --- | --- | --- |
| __________ | __________ | __________ | __________ | __________ | __________ |
