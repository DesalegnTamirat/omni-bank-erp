# Supply an approved digest, for example odoo:19.0@sha256:<digest>.
ARG ODOO_BASE_IMAGE=odoo:19.0
FROM ${ODOO_BASE_IMAGE}

COPY --chown=odoo:odoo custom_addons/ /mnt/extra-addons/

