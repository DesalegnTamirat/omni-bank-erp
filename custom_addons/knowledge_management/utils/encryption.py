# -*- coding: utf-8 -*-
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

DEFAULT_KMS_SECRET = 'BUNNA_BANK_KMS_SECURE_TOKEN_2026_ERP'


def derive_symmetric_key(doc_id, user_id, secret=None):
    """
    Derives a session/identity-bound 32-byte urlsafe Fernet key
    from (doc_id, user_id, server_secret) (FR-KMS-016).
    """
    secret = secret or DEFAULT_KMS_SECRET
    key_material = f"{doc_id}:{user_id}:{secret}".encode('utf-8')
    digest = hashlib.sha256(key_material).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_document_data(raw_bytes, doc_id, user_id, secret=None):
    """
    Encrypts document byte payload with identity-bound Fernet key.
    """
    key = derive_symmetric_key(doc_id, user_id, secret)
    fernet = Fernet(key)
    return fernet.encrypt(raw_bytes)


def decrypt_document_data(encrypted_bytes, doc_id, user_id, secret=None):
    """
    Decrypts document byte payload. Raises InvalidToken if key/identity does not match.
    """
    key = derive_symmetric_key(doc_id, user_id, secret)
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_bytes)

