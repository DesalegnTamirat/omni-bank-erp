# -*- coding: utf-8 -*-
from . import models
from . import controllers
from . import utils


def _kms_post_init_hook(env):
    """Generate cryptographically secure KMS encryption secret in ir.config_parameter if not set (FR-KMS-016)."""
    from .utils.encryption import get_kms_server_secret
    get_kms_server_secret(env)
