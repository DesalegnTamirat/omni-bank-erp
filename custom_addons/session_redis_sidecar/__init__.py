"""
Redis Session Store with Sidecar Pattern for Odoo
==================================================

This module implements a dual-connection Redis session store optimized for
Kubernetes deployments using the sidecar pattern:

- WRITES go to Redis Master (source of truth)
- READS go to Local Replica first (ultra-fast localhost access)
- FALLBACK to Master if local replica misses (handles replication lag)

Works in two modes:
1. Sidecar Mode: Master + Local Replica (recommended for K8s)
2. Single Redis Mode: When REDIS_LOCAL_HOST equals REDIS_MASTER_HOST

License: LGPL-3
"""

import os
import socket
import logging
import pickle

_logger = logging.getLogger(__name__)

# =============================================================================
# Configuration from Environment Variables and odoo.conf
# =============================================================================

from odoo.tools import config as odoo_config

# Redis Master (for WRITES and fallback READS)
REDIS_MASTER_HOST = os.environ.get('REDIS_MASTER_HOST') or odoo_config.get('redis_host', '10.1.13.138')
REDIS_MASTER_PORT = int(os.environ.get('REDIS_MASTER_PORT') or odoo_config.get('redis_port', 6379))
REDIS_MASTER_PASSWORD = os.environ.get('REDIS_MASTER_PASSWORD') or odoo_config.get('redis_password', 'Y//0QomK96002g+clYJsfOJfCQwUNAO7X9tHYA3zJ6U=')

# Redis Local Replica (for fast READS)
# Set same as master for single-redis mode
REDIS_LOCAL_HOST = os.environ.get('REDIS_LOCAL_HOST') or odoo_config.get('redis_local_host', REDIS_MASTER_HOST)
REDIS_LOCAL_PORT = int(os.environ.get('REDIS_LOCAL_PORT') or odoo_config.get('redis_local_port', REDIS_MASTER_PORT))
REDIS_LOCAL_PASSWORD = os.environ.get('REDIS_LOCAL_PASSWORD') or odoo_config.get('redis_local_password', REDIS_MASTER_PASSWORD)

# Common settings
def _get_default_instance_ip():
    """Detect local instance IP address for use as default session prefix."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((REDIS_MASTER_HOST, REDIS_MASTER_PORT))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'

DEFAULT_INSTANCE_IP = _get_default_instance_ip()
REDIS_DB = int(os.environ.get('REDIS_DB') or odoo_config.get('redis_db', 1))
SESSION_PREFIX = os.environ.get('SESSION_PREFIX') or odoo_config.get('redis_session_prefix') or DEFAULT_INSTANCE_IP
SESSION_EXPIRY = int(os.environ.get('SESSION_EXPIRY') or odoo_config.get('redis_session_expiry', 259200))
SESSION_EXPIRY_ANONYMOUS = int(os.environ.get('SESSION_EXPIRY_ANONYMOUS') or odoo_config.get('redis_session_expiry_anonymous', 10800))

# Connection settings
REDIS_SOCKET_TIMEOUT = int(os.environ.get('REDIS_SOCKET_TIMEOUT', 5))
REDIS_SOCKET_CONNECT_TIMEOUT = int(os.environ.get('REDIS_SOCKET_CONNECT_TIMEOUT', 5))
REDIS_RETRY_ON_TIMEOUT = os.environ.get('REDIS_RETRY_ON_TIMEOUT', 'true').lower() == 'true'

# Detect mode
SIDECAR_MODE = not (REDIS_MASTER_HOST == REDIS_LOCAL_HOST and REDIS_MASTER_PORT == REDIS_LOCAL_PORT)

# =============================================================================
# Redis Connection Management
# =============================================================================

_redis_master = None
_redis_local = None


def _create_redis_connection(host, port, password=None, name="Redis", timeout=5):
    """Create a Redis connection with proper error handling."""
    try:
        import redis
        
        conn = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=REDIS_DB,
            decode_responses=False,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )
        
        # Test connection
        conn.ping()
        _logger.info(f"{name} connected: {host}:{port}")
        return conn
        
    except ImportError:
        _logger.error("Redis library not installed. Run: pip install redis")
        return None
    except Exception as e:
        _logger.warning(f"Failed to connect to {name} ({host}:{port}): {e}")
        return None


def get_redis_master():
    """Get connection to Redis Master (for writes + fallback reads)."""
    global _redis_master
    
    if _redis_master is None:
        _redis_master = _create_redis_connection(
            host=REDIS_MASTER_HOST,
            port=REDIS_MASTER_PORT,
            password=REDIS_MASTER_PASSWORD,
            name="Redis MASTER",
            timeout=REDIS_SOCKET_TIMEOUT
        )
    
    return _redis_master


def get_redis_local():
    """Get connection to Local Redis Replica (for fast reads)."""
    global _redis_local
    
    # In single-redis mode, reuse master connection
    if not SIDECAR_MODE:
        return get_redis_master()
    
    if _redis_local is None:
        _redis_local = _create_redis_connection(
            host=REDIS_LOCAL_HOST,
            port=REDIS_LOCAL_PORT,
            password=REDIS_LOCAL_PASSWORD,
            name="Redis LOCAL",
            timeout=2  # Shorter timeout for sidecar
        )
    
    return _redis_local


def reset_connections():
    """Reset Redis connections (useful for testing or reconnection)."""
    global _redis_master, _redis_local
    _redis_master = None
    _redis_local = None


# =============================================================================
# Session Store Implementation
# =============================================================================

def _get_session_store_class():
    """
    Get the appropriate SessionStore base class for the current Odoo version.
    
    Handles import differences between Odoo versions:
    - Odoo 16+: odoo.tools._vendor.sessions.SessionStore
    - Odoo 14-15: werkzeug.contrib.sessions.SessionStore
    - Fallback: Create minimal base class
    """
    # Try Odoo 16+ path first
    try:
        from odoo.tools._vendor.sessions import SessionStore
        _logger.debug("Using Odoo 16+ SessionStore")
        return SessionStore
    except ImportError:
        pass
    
    # Try older Odoo / Werkzeug path
    try:
        from werkzeug.contrib.sessions import SessionStore
        _logger.debug("Using Werkzeug SessionStore")
        return SessionStore
    except ImportError:
        pass
    
    # Fallback: minimal implementation
    _logger.warning("Using fallback SessionStore implementation")
    
    class MinimalSessionStore:
        def __init__(self, session_class=None, *args, **kwargs):
            self.session_class = session_class
        
        def generate_key(self, salt=None):
            import uuid
            return str(uuid.uuid4())
    
    return MinimalSessionStore


def _patch_session_store():
    """
    Monkey-patch Odoo's session store to use Redis with sidecar pattern.
    """
    try:
        import time
        from odoo.http import (
            root, Session,
            STORED_SESSION_BYTES,
            SESSION_DELETION_TIMER,
        )
        from odoo.service import security

        BaseStore = type(root.session_store) if hasattr(root, 'session_store') and root.session_store else _get_session_store_class()
        
        class RedisSidecarSessionStore(BaseStore):
            """
            Redis Session Store with Master-Replica Sidecar Pattern.
            
            Optimized for Kubernetes deployments:
            1. Writes to Redis Master (network, ~1ms)
            2. Reads from Local Replica first (localhost, ~0.1ms)
            3. Falls back to Master on local miss (~1% of reads)
            
            Also works in single-redis mode when local == master.
            """
            
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.master = get_redis_master()
                self.local = get_redis_local()
                
                mode = "SIDECAR" if SIDECAR_MODE else "SINGLE"
                
                if self.master:
                    _logger.info(
                        f"RedisSidecarSessionStore initialized ({mode} mode)\n"
                        f"  WRITES  -> {REDIS_MASTER_HOST}:{REDIS_MASTER_PORT}\n"
                        f"  READS   -> {REDIS_LOCAL_HOST}:{REDIS_LOCAL_PORT}"
                    )
                else:
                    _logger.error(
                        "Redis Master not available! "
                        "Sessions will NOT persist."
                    )
            
            def _get_session_key(self, sid):
                """Generate Redis key for session ID."""
                return f"{SESSION_PREFIX}:{sid}"
            
            def _get_expiry(self, session):
                """Get session expiry based on authentication status."""
                if session.get('uid'):
                    return SESSION_EXPIRY
                return SESSION_EXPIRY_ANONYMOUS
            
            def save(self, session):
                """
                Save session to Redis Master.
                
                Writes always go to Master, which auto-replicates
                to all connected replicas (including sidecars).
                """
                if self.master is None:
                    _logger.warning("Redis Master unavailable - session not saved")
                    return
                
                key = self._get_session_key(session.sid)
                expiry = self._get_expiry(session)
                
                try:
                    data = pickle.dumps(dict(session))
                    self.master.set(key, data, ex=expiry)
                    _logger.debug(f"Session saved: {key} (TTL: {expiry}s)")
                except Exception as e:
                    _logger.error(f"Failed to save session: {e}")
            
            def delete(self, session):
                """
                Delete session from Redis Master.
                
                Deletion propagates to all replicas automatically.
                """
                if self.master is None:
                    return
                
                key = self._get_session_key(session.sid)
                
                try:
                    self.master.delete(key)
                    _logger.debug(f"Session deleted: {key}")
                except Exception as e:
                    _logger.error(f"Failed to delete session: {e}")
            
            def get(self, sid):
                """
                Get session from Redis.
                
                Read strategy:
                1. Try local replica first (fast, ~0.1ms)
                2. Fallback to master if local miss
                3. Return new session if not found
                """
                key = self._get_session_key(sid)
                data = None
                
                # Step 1: Try local replica (fast path)
                if self.local is not None:
                    try:
                        data = self.local.get(key)
                        if data:
                            _logger.debug(f"Session found (LOCAL): {key}")
                    except Exception as e:
                        _logger.warning(f"Local read failed: {e}")
                
                # Step 2: Fallback to master (sidecar mode only)
                if data is None and self.master is not None and SIDECAR_MODE:
                    try:
                        data = self.master.get(key)
                        if data:
                            _logger.debug(f"Session found (MASTER fallback): {key}")
                    except Exception as e:
                        _logger.error(f"Master read failed: {e}")
                
                # Step 3: Deserialize and return
                if data:
                    try:
                        session_data = pickle.loads(data)
                        return self.session_class(session_data, sid=sid)
                    except Exception as e:
                        _logger.error(f"Failed to deserialize session: {e}")
                
                # Step 4: Return new empty session
                return self.session_class({}, sid=sid, new=True)
            
            def rotate(self, session, env, soft=False):
                """
                Rotate session ID (security feature) compatible with Odoo 19.
                """
                if soft:
                    static = session.sid[:STORED_SESSION_BYTES]
                    recent_session = self.get(session.sid)
                    if 'next_sid' in recent_session:
                        session.sid = recent_session['next_sid']
                        return session
                    next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
                    session['next_sid'] = next_sid
                    session['deletion_time'] = time.time() + SESSION_DELETION_TIMER
                    self.save(session)
                    session['gc_previous_sessions'] = True
                    session.sid = next_sid
                    session.pop('deletion_time', None)
                    session.pop('next_sid', None)
                else:
                    self.delete(session)
                    session.sid = self.generate_key()

                if session.get('uid'):
                    assert env, "saving this session requires an environment"
                    session.session_token = security.compute_session_token(session, env)

                session.should_rotate = False
                session['create_time'] = time.time()
                self.save(session)
                return session

            def vacuum(self, max_lifetime=None):
                """Redis handles expiration via TTL automatically."""
                pass
            
            def list(self):
                """List all session IDs (admin/debug use)."""
                if self.master is None:
                    return []
                
                try:
                    pattern = f"{SESSION_PREFIX}:*"
                    keys = self.master.keys(pattern)
                    prefix_len = len(SESSION_PREFIX) + 1
                    return [key.decode()[prefix_len:] for key in keys]
                except Exception as e:
                    _logger.error(f"Failed to list sessions: {e}")
                    return []
            
            def count(self):
                """Count total sessions (admin/debug use)."""
                return len(self.list())
        
        # Apply the patch
        if hasattr(root, 'session_store'):
            root.session_store = RedisSidecarSessionStore(session_class=Session)
            _logger.info("Odoo session store patched successfully")
        else:
            _logger.warning("Could not find root.session_store to patch")
            
    except ImportError as e:
        _logger.error(f"Failed to import Odoo modules: {e}")
    except Exception as e:
        _logger.error(f"Failed to patch session store: {e}")
        import traceback
        _logger.error(traceback.format_exc())


# =============================================================================
# Module Initialization
# =============================================================================

def post_init_hook(env):
    """Post-installation hook."""
    _logger.info("Redis Session Store (Sidecar Pattern) installed")


# Apply patch on module load
_patch_session_store()
