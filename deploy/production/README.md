# LMS production deployment template

This template packages the current add-ons into an immutable Odoo image and keeps PostgreSQL and Odoo on a private Compose network. `docker-compose.yml` at the repository root is for local development.

1. Copy `env.example` and `odoo.conf.example` to a private operations directory. Replace every placeholder, choose the real Odoo database name in `dbfilter`, and restrict file permissions. The PostgreSQL password file is read by both the official PostgreSQL and Odoo images. Keep `db_host`, `db_user`, and `db_password` out of `odoo.conf`; the Odoo entrypoint reads `HOST`, `USER`, and `PASSWORD_FILE` and supplies those settings.
2. Set approved image digests, certificate paths, the immutable application image name, and an authorized HTTPS bind address. Build and validate the exact image in staging before production. The default bind is loopback for sites with an existing perimeter proxy; only expose it to the intended network.
3. Restore or create the Odoo database and filestore before starting the application. Back up PostgreSQL, the `odoo_data` filestore, configuration, certificates/media keys, and the release image as one recovery set. Rehearse restore and record the measured RTO/RPO.
4. Run `docker compose --env-file /private/path/production.env -f deploy/production/compose.yml config --quiet`, then `build`, `up -d`, and inspect health and logs. Run clean install or upgrade with the exact candidate image in staging first.
5. Verify SSO/MFA, SMTP, media routes, scheduled jobs, certificate PDF/HR delivery, the LMS role matrix, backup alerts, and the agreed performance/availability targets. Route Odoo, proxy, and database logs to the approved retention/alerting system.

This template does not configure a bank identity provider, mail relay, backup scheduler, external media CDN, or tamper-resistant log store; operations must supply and verify those services before release.
