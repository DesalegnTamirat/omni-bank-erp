# Security & Data Protection Architecture Record (FR-COM-057)

**Module:** Competency Management System (`competency_management`)  
**Target Organization:** Bunna Bank S.C.  
**Requirement Standard:** FR-COM-057 (Data Encryption at Rest & In Transit)

---

## 1. Executive Summary

Requirement **FR-COM-057** mandates that all employee competency data, assessment ratings, 360° multi-rater evaluation scores, and individual development plans (IDPs) must be protected against unauthorized access and tampering via encryption **in transit** and **at rest**.

This document outlines the technical security controls implemented across the infrastructure, application, and database layers for Bunna Bank ERP.

---

## 2. Encryption Controls Architecture

### 2.1 Transport Encryption (Data In Transit)
- **Protocol Enforced**: TLS 1.3 (with TLS 1.2 fallback for legacy banking endpoints).
- **Implementation**: Terminated at the reverse proxy load balancer (NGINX / F5 BIG-IP).
- **HTTPS Enforcement**: All HTTP traffic is automatically redirected to HTTPS (Port 443) using HTTP Strict Transport Security (`HSTS` header: `max-age=31536000; includeSubDomains; preload`).
- **Cipher Suites**: Restricted to forward-secrecy cipher suites (e.g., `ECDHE-ECDSA-AES128-GCM-SHA256`, `ECDHE-RSA-AES256-GCM-SHA384`).
- **RPC & REST API**: JSON-RPC and Odoo web controller traffic are strictly transmitted over HTTPS TLS connections.

### 2.2 Database Encryption (Data At Rest)
- **PostgreSQL Encryption**:
  - PostgreSQL database storage volumes (`/var/lib/postgresql/data`) reside on Linux `LUKS` (Linux Unified Key Setup) encrypted block devices using AES-256-XTS cipher.
  - Encryption keys are managed by Bunna Bank's Enterprise Key Management System (KMS) or Hardware Security Module (HSM).
- **Backup Encryption**:
  - Automated database dump backups (`.dump`, `.sql.gz`) are encrypted at rest using AES-256 before transmission to secondary backup storage.

### 2.3 Filestore & Attachment Security
- **Assessment Evidence Attachments**:
  - Evidence files (certificates, examination proof, rating evidence) stored in Odoo's filestore (`/var/lib/odoo/filestore/`) are hosted on an encrypted filesystem volume.
- **Access Control**:
  - Direct file path traversal is disabled; attachment access requires authenticated session tokens evaluated against Odoo `ir.attachment` record security rules.

---

## 3. Rater Anonymity & Row-Level Access Security (360° Multi-Rater)

- **Peer Anonymity**: Raters completing 360° multi-rater assessments (`is_rater_assessment=True`) have row-level record security (`ir.rule`) restricted exclusively to their own rater submission (`rater_id == user.id`).
- **Aggregate Visibility**: Supervisors and HR Administrators view aggregated scores on the parent 360° assessment record (`parent_assessment_id`), preventing individual score disclosure among peer raters.

---

## 4. Compliance Verification & Sign-Off

| Security Layer | Encryption Control Standard | Status | Verified By |
| :--- | :--- | :---: | :--- |
| **In Transit** | TLS 1.3 HTTPS Reverse Proxy | **COMPLIANT** | Infrastructure Security Team |
| **At Rest (Database)** | AES-256 LUKS Volume Encryption | **COMPLIANT** | Database Administrator (DBA) |
| **At Rest (Filestore)** | Encrypted Attachment Storage | **COMPLIANT** | System Administrator |
| **Data Governance** | Segregation of Duties (FR-COM-055) | **COMPLIANT** | Application Security Lead |

---

## 5. Dashboard Trend Storage & Scheduled Report Distribution (FR-RPT-008, FR-RPT-010)

- **Snapshot Data Security (`competency.dashboard.snapshot`)**: Stored trend snapshots maintain strict read permissions restricted to HR Supervisors (`group_competency_supervisor`) and HR Administrators (`group_competency_admin`).
- **Scheduled Email Distribution**: Automated cron email dispatches utilize internal system email gateways over encrypted SMTP TLS channels (`Port 587/465`) targeting authenticated HR admin accounts only.

