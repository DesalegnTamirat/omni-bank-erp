# -*- coding: utf-8 -*-
import base64
import hashlib
import secrets
from cryptography.fernet import Fernet, InvalidToken

CONFIG_PARAM_KEY = 'knowledge_management.kms_encryption_secret'
DEFAULT_TOKEN_EXPIRY_SECONDS = 900  # 15 minutes session-bound expiry window (FR-KMS-016)


def get_kms_server_secret(env=None):
    """
    Retrieves the server secret from ir.config_parameter (FR-KMS-016).
    If not yet set in database, generates a cryptographically secure 256-bit random key
    and persists it in ir.config_parameter.
    Never relies on hardcoded string literals in source code.
    """
    if env is not None:
        ICP = env['ir.config_parameter'].sudo()
        secret = ICP.get_param(CONFIG_PARAM_KEY)
        if not secret:
            secret = secrets.token_hex(32)
            ICP.set_param(CONFIG_PARAM_KEY, secret)
        get_kms_server_secret._runtime_cache = secret
        return secret

    try:
        from odoo.http import request
        if request and hasattr(request, 'env') and request.env:
            return get_kms_server_secret(request.env)
    except Exception:
        pass

    # If runtime cache was already populated from database environment, reuse it
    if hasattr(get_kms_server_secret, '_runtime_cache'):
        return get_kms_server_secret._runtime_cache

    # Standalone execution fallback
    get_kms_server_secret._runtime_cache = secrets.token_hex(32)
    return get_kms_server_secret._runtime_cache


def derive_symmetric_key(doc_id, user_id, secret=None, session_id=None, env=None):
    """
    Derives a session/identity-bound 32-byte urlsafe Fernet key
    from (doc_id, user_id, session_id, server_secret) (FR-KMS-016).
    """
    secret = secret or get_kms_server_secret(env)
    key_material = f"{doc_id}:{user_id}:{session_id or ''}:{secret}".encode('utf-8')
    digest = hashlib.sha256(key_material).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_document_data(raw_bytes, doc_id, user_id, secret=None, session_id=None, env=None):
    """
    Encrypts document byte payload with session/identity-bound Fernet key.
    Includes built-in Fernet timestamp for TTL expiration verification.
    """
    secret = secret or get_kms_server_secret(env)
    key = derive_symmetric_key(doc_id, user_id, secret, session_id, env=env)
    fernet = Fernet(key)
    return fernet.encrypt(raw_bytes)


def decrypt_document_data(encrypted_bytes, doc_id, user_id, secret=None, session_id=None, env=None, max_age_seconds=DEFAULT_TOKEN_EXPIRY_SECONDS):
    """
    Decrypts document byte payload.
    Validates identity, session binding, and expiry TTL (FR-KMS-016).
    Raises InvalidToken if key, identity, or session mismatch, or if token is older than max_age_seconds.
    """
    secret = secret or get_kms_server_secret(env)
    key = derive_symmetric_key(doc_id, user_id, secret, session_id, env=env)
    fernet = Fernet(key)
    # Fernet.decrypt(token, ttl=...) verifies token timestamp <= max_age_seconds
    return fernet.decrypt(encrypted_bytes, ttl=max_age_seconds)

