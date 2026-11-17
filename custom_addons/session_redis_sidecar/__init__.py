"""
Redis Session Store (sidecar pattern) for Odoo, with filesystem fallback
========================================================================

- WRITES go to the local filesystem store (always) AND Redis master (best effort)
- READS try the local replica, then the master, then the filesystem store
- If Redis errors or times out, a per-process circuit breaker skips Redis for
  BREAKER_SECONDS, so requests never wait on a dead Redis
- Redis is checked once at startup in a background thread (never blocks startup)

With Redis down, users can still log in. Sessions then live on the local
disk of each app host, so use sticky routing (ip_hash) during an outage and
keep Odoo's session directory on a persistent volume.

Settings: environment variable wins, then odoo.conf, then the DEFAULTS below.
A missing, empty or invalid value falls back to its default.

    setting (odoo.conf)               environment variable          default
    redis_host                        REDIS_MASTER_HOST             none (Redis disabled)
    redis_port                        REDIS_MASTER_PORT             6379
    redis_password                    REDIS_MASTER_PASSWORD         none (no AUTH)
    redis_db                          REDIS_DB                      1
    redis_session_prefix              SESSION_PREFIX                odoo19
    redis_session_expiry              SESSION_EXPIRY                259200
    redis_session_expiry_anonymous    SESSION_EXPIRY_ANONYMOUS      10800
    redis_session_timeout             REDIS_SESSION_TIMEOUT         1.0 (seconds)
    redis_breaker_seconds             REDIS_BREAKER_SECONDS         30
    redis_local_host/port/password    REDIS_LOCAL_HOST/PORT/PASSWORD  same as master

IMPORTANT: there is no default Redis host. If redis_host / REDIS_MASTER_HOST is
not set, Redis is disabled and Odoo uses filesystem sessions only. Set a
different SESSION_PREFIX (and ideally REDIS_DB) per environment, e.g.
bunna_odoo19_uat and bunna_odoo19_prod.

License: LGPL-3
"""

import logging
import os
import pickle
import time

from odoo.tools import config as odoo_config

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults used when a value is missing from the environment AND odoo.conf.
# No host default on purpose: UAT must never fall back to the production Redis.
# Do not put the Redis password in source code.
# ---------------------------------------------------------------------------
DEFAULTS = {
    'host': None,                 # fail closed: no host configured -> no Redis
    'port': 6379,
    'password': None,
    'db': 1,
    'session_prefix': 'odoo19',   # override per environment
    'expiry': 259200,             # 3 days, logged-in sessions
    'expiry_anonymous': 10800,    # 3 hours, anonymous sessions
    'timeout': 1.0,               # seconds per Redis call
    'breaker_seconds': 30.0,      # skip Redis this long after a failure
}

def _conf_get(conf_name):
    misc = getattr(odoo_config, 'misc', None) or {}
    val = misc.get('redis_session', {}).get(conf_name)
    if val is None:
        val = odoo_config.get(conf_name)   # old location still works
    return val


def _cfg(env_name, conf_name, default=None, cast=str):
    """env var -> odoo.conf -> default. Empty/invalid values use the default.

    A value of 0 is valid (for example redis_db = 0).
    """
    value = os.environ.get(env_name)
    if value is None or value == '':
        #value = odoo_config.get(conf_name)
        value = _conf_get(conf_name)
    if value is None or value == '' or value is False:
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        _logger.warning("Invalid value %r for %s / %s; using default %r",
                        value, env_name, conf_name, default)
        return default


MASTER_HOST = _cfg('REDIS_MASTER_HOST', 'redis_host', DEFAULTS['host'])
MASTER_PORT = _cfg('REDIS_MASTER_PORT', 'redis_port', DEFAULTS['port'], int)
MASTER_PASSWORD = _cfg('REDIS_MASTER_PASSWORD', 'redis_password', DEFAULTS['password'])

LOCAL_HOST = _cfg('REDIS_LOCAL_HOST', 'redis_local_host', MASTER_HOST)
LOCAL_PORT = _cfg('REDIS_LOCAL_PORT', 'redis_local_port', MASTER_PORT, int)
LOCAL_PASSWORD = _cfg('REDIS_LOCAL_PASSWORD', 'redis_local_password', MASTER_PASSWORD)

REDIS_DB = _cfg('REDIS_DB', 'redis_db', DEFAULTS['db'], int)
SESSION_PREFIX = _cfg('SESSION_PREFIX', 'redis_session_prefix', DEFAULTS['session_prefix'])
SESSION_EXPIRY = _cfg('SESSION_EXPIRY', 'redis_session_expiry', DEFAULTS['expiry'], int)
SESSION_EXPIRY_ANONYMOUS = _cfg(
    'SESSION_EXPIRY_ANONYMOUS', 'redis_session_expiry_anonymous',
    DEFAULTS['expiry_anonymous'], int)

TIMEOUT = _cfg('REDIS_SESSION_TIMEOUT', 'redis_session_timeout', DEFAULTS['timeout'], float)
BREAKER_SECONDS = _cfg('REDIS_BREAKER_SECONDS', 'redis_breaker_seconds',
                       DEFAULTS['breaker_seconds'], float)
if TIMEOUT <= 0:
    TIMEOUT = DEFAULTS['timeout']
if BREAKER_SECONDS < 0:
    BREAKER_SECONDS = DEFAULTS['breaker_seconds']

SIDECAR_MODE = bool(MASTER_HOST) and (
    (MASTER_HOST, MASTER_PORT) != (LOCAL_HOST, LOCAL_PORT))

_SKIP = object()  # "Redis not usable right now"


class _RedisLink:
    """Lazy Redis connection with a circuit breaker. One per server."""

    def __init__(self, name, host, port, password):
        self.name = name
        self.host = host
        self.port = port
        self.password = password
        self._client = None
        self._down_until = 0.0
        self._is_down = False
        self._last_log_time = 0.0  # last time an outage warning was logged

    def client(self):
        """Return a client, or None if Redis is disabled or the breaker is open."""
        if not self.host:
            return None
        if time.monotonic() < self._down_until:
            return None
        if self._client is None:
            try:
                self._client = self._build(TIMEOUT)  # does not connect yet
            except Exception as exc:
                self.fail(exc)
                return None
        return self._client

    def _build(self, timeout):
        import redis
        kwargs = dict(
            host=self.host, port=self.port, password=self.password,
            db=REDIS_DB, decode_responses=False,
            socket_timeout=timeout, socket_connect_timeout=timeout,
        )
        try:  # redis-py >= 4: disable built-in retries using Retry
            from redis.backoff import NoBackoff
            from redis.retry import Retry
            kwargs['retry'] = Retry(NoBackoff(), 0)
        except Exception:
            kwargs['retry_on_timeout'] = False
        return redis.Redis(**kwargs)

    def probe(self):
        """One-off startup check. Runs in a background thread, never blocks startup."""
        if not self.host:
            return
        try:
            conn = self._build(3)
            conn.ping()
            try:
                conn.close()
            except Exception:
                pass
        except Exception as exc:
            self.fail(exc)
        else:
            _logger.info("Redis %s (%s:%s) startup check OK",
                         self.name, self.host, self.port)
            self.ok()

    def ok(self):
        if self._is_down:
            self._is_down = False
            _logger.info("Redis %s (%s:%s) is reachable again",
                         self.name, self.host, self.port)

    def fail(self, exc):
        now = time.monotonic()
        self._down_until = now + BREAKER_SECONDS

        # Log at the start of an outage, then at most once per BREAKER_SECONDS
        if not self._is_down or (now - self._last_log_time) >= BREAKER_SECONDS:
            status_word = "failed" if not self._is_down else "is still unreachable"
            _logger.warning(
                "Redis %s (%s:%s) %s: %s: %s. Using filesystem sessions; "
                "retrying in %ss", self.name, self.host, self.port,
                status_word, type(exc).__name__, str(exc).rstrip('.'),
                int(BREAKER_SECONDS))
            self._last_log_time = now

        self._is_down = True


_master = _RedisLink('MASTER', MASTER_HOST, MASTER_PORT, MASTER_PASSWORD)
_local = (_RedisLink('LOCAL', LOCAL_HOST, LOCAL_PORT, LOCAL_PASSWORD)
          if SIDECAR_MODE else _master)


def _call(link, fn):
    """Run fn(redis_client); on any error trip the breaker and return _SKIP."""
    client = link.client()
    if client is None:
        return _SKIP
    try:
        result = fn(client)
        link.ok()
        return result
    except Exception as exc:  # redis.RedisError, OSError, ...
        link.fail(exc)
        return _SKIP


def _patch_session_store():
    try:
        from odoo.http import root

        original = root.session_store  # Odoo's normal filesystem store
        Base = type(original)

        class RedisSidecarSessionStore(Base):
            # NOTE: rotate() is intentionally NOT overridden. Odoo's base
            # implementation calls self.get / self.save / self.delete, so the
            # Redis logic below applies to it automatically and stays correct
            # across Odoo 19.x updates.

            def __init__(self, fs_store):
                self.__dict__.update(fs_store.__dict__)
                self._fs = fs_store
                if MASTER_HOST:
                    _logger.info(
                        "RedisSidecarSessionStore ready (%s mode, timeout=%ss, "
                        "filesystem fallback ON, prefix=%s, db=%s)\n"
                        "  WRITES -> %s:%s\n  READS  -> %s:%s",
                        "SIDECAR" if SIDECAR_MODE else "SINGLE", TIMEOUT,
                        SESSION_PREFIX, REDIS_DB, MASTER_HOST, MASTER_PORT,
                        LOCAL_HOST, LOCAL_PORT)
                else:
                    _logger.warning(
                        "No redis_host configured: using filesystem sessions only")

            @staticmethod
            def _key(sid):
                return f"{SESSION_PREFIX}:{sid}"

            @staticmethod
            def _expiry(session):
                return SESSION_EXPIRY if session.get('uid') else SESSION_EXPIRY_ANONYMOUS

            def save(self, session):
                self._fs.save(session)  # always keep a local copy
                try:
                    data = pickle.dumps(dict(session))
                except Exception as exc:
                    _logger.error("Cannot serialize session for Redis: %s", exc)
                    return
                _call(_master, lambda r: r.set(
                    self._key(session.sid), data, ex=self._expiry(session)))

            def delete(self, session):
                self._fs.delete(session)
                _call(_master, lambda r: r.delete(self._key(session.sid)))

            def get(self, sid):
                # Never build a Redis key from an invalid sid
                if not self.is_valid_key(sid):
                    return self.new()

                key = self._key(sid)
                data = _call(_local, lambda r: r.get(key))
                if (data is _SKIP or not data) and SIDECAR_MODE:  # local down or miss -> master
                    data = _call(_master, lambda r: r.get(key))
                if data and data is not _SKIP:
                    try:
                        return self.session_class(pickle.loads(data), sid=sid)
                    except Exception as exc:
                        _logger.error("Failed to deserialize session: %s", exc)
                # Redis miss, error, or down -> Odoo's filesystem store
                return self._fs.get(sid)

            def vacuum(self, *args, **kwargs):
                """Redis expires keys by TTL; vacuum only the filesystem copies."""
                return self._fs.vacuum(*args, **kwargs)

            def list(self):
                # SCAN instead of KEYS: KEYS is O(N) and blocks Redis for everyone
                keys = _call(_master, lambda r: list(
                    r.scan_iter(match=f"{SESSION_PREFIX}:*", count=500)))
                if keys is _SKIP:
                    return []
                n = len(SESSION_PREFIX) + 1
                return [k.decode()[n:] for k in keys]

            def count(self):
                return len(self.list())

        root.session_store = RedisSidecarSessionStore(original)
        _logger.info("Odoo session store patched successfully")

        import threading

        def _probe_all():
            _master.probe()
            if _local is not _master:
                _local.probe()

        threading.Thread(target=_probe_all, name='redis-startup-check',
                         daemon=True).start()

    except Exception:
        _logger.exception("Failed to patch session store; Odoo default store stays active")


def post_init_hook(env):
    _logger.info("Redis Session Store (Sidecar Pattern) installed")


_patch_session_store()

































# """
# Redis Session Store with Sidecar Pattern for Odoo
# ==================================================

# This module implements a dual-connection Redis session store optimized for
# Kubernetes deployments using the sidecar pattern:

# - WRITES go to Redis Master (source of truth)
# - READS go to Local Replica first (ultra-fast localhost access)
# - FALLBACK to Master if local replica misses (handles replication lag)

# Works in two modes:
# 1. Sidecar Mode: Master + Local Replica (recommended for K8s)
# 2. Single Redis Mode: When REDIS_LOCAL_HOST equals REDIS_MASTER_HOST

# License: LGPL-3
# """

# import os
# import socket
# import logging
# import pickle

# _logger = logging.getLogger(__name__)

# # =============================================================================
# # Configuration from Environment Variables and odoo.conf
# # =============================================================================

# from odoo.tools import config as odoo_config

# # Redis Master (for WRITES and fallback READS)
# REDIS_MASTER_HOST = os.environ.get('REDIS_MASTER_HOST') or odoo_config.get('redis_host', '10.1.13.138')
# REDIS_MASTER_PORT = int(os.environ.get('REDIS_MASTER_PORT') or odoo_config.get('redis_port', 6379))
# REDIS_MASTER_PASSWORD = os.environ.get('REDIS_MASTER_PASSWORD') or odoo_config.get('redis_password', 'Y//0QomK96002g+clYJsfOJfCQwUNAO7X9tHYA3zJ6U=')

# # Redis Local Replica (for fast READS)
# # Set same as master for single-redis mode
# REDIS_LOCAL_HOST = os.environ.get('REDIS_LOCAL_HOST') or odoo_config.get('redis_local_host', REDIS_MASTER_HOST)
# REDIS_LOCAL_PORT = int(os.environ.get('REDIS_LOCAL_PORT') or odoo_config.get('redis_local_port', REDIS_MASTER_PORT))
# REDIS_LOCAL_PASSWORD = os.environ.get('REDIS_LOCAL_PASSWORD') or odoo_config.get('redis_local_password', REDIS_MASTER_PASSWORD)

# # Common settings
# def _get_default_instance_ip():
#     """Detect local instance IP address for use as default session prefix."""
#     try:
#         s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         s.connect((REDIS_MASTER_HOST, REDIS_MASTER_PORT))
#         ip = s.getsockname()[0]
#         s.close()
#         return ip
#     except Exception:
#         try:
#             return socket.gethostbyname(socket.gethostname())
#         except Exception:
#             return '127.0.0.1'

# DEFAULT_INSTANCE_IP = _get_default_instance_ip()
# REDIS_DB = int(os.environ.get('REDIS_DB') or odoo_config.get('redis_db', 1))
# SESSION_PREFIX = os.environ.get('SESSION_PREFIX') or odoo_config.get('redis_session_prefix') or DEFAULT_INSTANCE_IP
# SESSION_EXPIRY = int(os.environ.get('SESSION_EXPIRY') or odoo_config.get('redis_session_expiry', 259200))
# SESSION_EXPIRY_ANONYMOUS = int(os.environ.get('SESSION_EXPIRY_ANONYMOUS') or odoo_config.get('redis_session_expiry_anonymous', 10800))

# # Connection settings
# REDIS_SOCKET_TIMEOUT = int(os.environ.get('REDIS_SOCKET_TIMEOUT', 5))
# REDIS_SOCKET_CONNECT_TIMEOUT = int(os.environ.get('REDIS_SOCKET_CONNECT_TIMEOUT', 5))
# REDIS_RETRY_ON_TIMEOUT = os.environ.get('REDIS_RETRY_ON_TIMEOUT', 'true').lower() == 'true'

# # Detect mode
# SIDECAR_MODE = not (REDIS_MASTER_HOST == REDIS_LOCAL_HOST and REDIS_MASTER_PORT == REDIS_LOCAL_PORT)

# # =============================================================================
# # Redis Connection Management
# # =============================================================================

# _redis_master = None
# _redis_local = None


# def _create_redis_connection(host, port, password=None, name="Redis", timeout=5):
#     """Create a Redis connection with proper error handling."""
#     try:
#         import redis
        
#         conn = redis.Redis(
#             host=host,
#             port=port,
#             password=password,
#             db=REDIS_DB,
#             decode_responses=False,
#             socket_timeout=timeout,
#             socket_connect_timeout=timeout,
#         )
        
#         # Test connection
#         conn.ping()
#         _logger.info(f"{name} connected: {host}:{port}")
#         return conn
        
#     except ImportError:
#         _logger.error("Redis library not installed. Run: pip install redis")
#         return None
#     except Exception as e:
#         _logger.warning(f"Failed to connect to {name} ({host}:{port}): {e}")
#         return None


# def get_redis_master():
#     """Get connection to Redis Master (for writes + fallback reads)."""
#     global _redis_master
    
#     if _redis_master is None:
#         _redis_master = _create_redis_connection(
#             host=REDIS_MASTER_HOST,
#             port=REDIS_MASTER_PORT,
#             password=REDIS_MASTER_PASSWORD,
#             name="Redis MASTER",
#             timeout=REDIS_SOCKET_TIMEOUT
#         )
    
#     return _redis_master


# def get_redis_local():
#     """Get connection to Local Redis Replica (for fast reads)."""
#     global _redis_local
    
#     # In single-redis mode, reuse master connection
#     if not SIDECAR_MODE:
#         return get_redis_master()
    
#     if _redis_local is None:
#         _redis_local = _create_redis_connection(
#             host=REDIS_LOCAL_HOST,
#             port=REDIS_LOCAL_PORT,
#             password=REDIS_LOCAL_PASSWORD,
#             name="Redis LOCAL",
#             timeout=2  # Shorter timeout for sidecar
#         )
    
#     return _redis_local


# def reset_connections():
#     """Reset Redis connections (useful for testing or reconnection)."""
#     global _redis_master, _redis_local
#     _redis_master = None
#     _redis_local = None


# # =============================================================================
# # Session Store Implementation
# # =============================================================================

# def _get_session_store_class():
#     """
#     Get the appropriate SessionStore base class for the current Odoo version.
    
#     Handles import differences between Odoo versions:
#     - Odoo 16+: odoo.tools._vendor.sessions.SessionStore
#     - Odoo 14-15: werkzeug.contrib.sessions.SessionStore
#     - Fallback: Create minimal base class
#     """
#     # Try Odoo 16+ path first
#     try:
#         from odoo.tools._vendor.sessions import SessionStore
#         _logger.debug("Using Odoo 16+ SessionStore")
#         return SessionStore
#     except ImportError:
#         pass
    
#     # Try older Odoo / Werkzeug path
#     try:
#         from werkzeug.contrib.sessions import SessionStore
#         _logger.debug("Using Werkzeug SessionStore")
#         return SessionStore
#     except ImportError:
#         pass
    
#     # Fallback: minimal implementation
#     _logger.warning("Using fallback SessionStore implementation")
    
#     class MinimalSessionStore:
#         def __init__(self, session_class=None, *args, **kwargs):
#             self.session_class = session_class
        
#         def generate_key(self, salt=None):
#             import uuid
#             return str(uuid.uuid4())
    
#     return MinimalSessionStore


# def _patch_session_store():
#     """
#     Monkey-patch Odoo's session store to use Redis with sidecar pattern.
#     """
#     try:
#         import time
#         from odoo.http import (
#             root, Session,
#             STORED_SESSION_BYTES,
#             SESSION_DELETION_TIMER,
#         )
#         from odoo.service import security

#         BaseStore = type(root.session_store) if hasattr(root, 'session_store') and root.session_store else _get_session_store_class()
        
#         class RedisSidecarSessionStore(BaseStore):
#             """
#             Redis Session Store with Master-Replica Sidecar Pattern.
            
#             Optimized for Kubernetes deployments:
#             1. Writes to Redis Master (network, ~1ms)
#             2. Reads from Local Replica first (localhost, ~0.1ms)
#             3. Falls back to Master on local miss (~1% of reads)
            
#             Also works in single-redis mode when local == master.
#             """
            
#             def __init__(self, *args, **kwargs):
#                 super().__init__(*args, **kwargs)
#                 self.master = get_redis_master()
#                 self.local = get_redis_local()
                
#                 mode = "SIDECAR" if SIDECAR_MODE else "SINGLE"
                
#                 if self.master:
#                     _logger.info(
#                         f"RedisSidecarSessionStore initialized ({mode} mode)\n"
#                         f"  WRITES  -> {REDIS_MASTER_HOST}:{REDIS_MASTER_PORT}\n"
#                         f"  READS   -> {REDIS_LOCAL_HOST}:{REDIS_LOCAL_PORT}"
#                     )
#                 else:
#                     _logger.error(
#                         "Redis Master not available! "
#                         "Sessions will NOT persist."
#                     )
            
#             def _get_session_key(self, sid):
#                 """Generate Redis key for session ID."""
#                 return f"{SESSION_PREFIX}:{sid}"
            
#             def _get_expiry(self, session):
#                 """Get session expiry based on authentication status."""
#                 if session.get('uid'):
#                     return SESSION_EXPIRY
#                 return SESSION_EXPIRY_ANONYMOUS
            
#             def save(self, session):
#                 """
#                 Save session to Redis Master.
                
#                 Writes always go to Master, which auto-replicates
#                 to all connected replicas (including sidecars).
#                 """
#                 if self.master is None:
#                     _logger.warning("Redis Master unavailable - session not saved")
#                     return
                
#                 key = self._get_session_key(session.sid)
#                 expiry = self._get_expiry(session)
                
#                 try:
#                     data = pickle.dumps(dict(session))
#                     self.master.set(key, data, ex=expiry)
#                     _logger.debug(f"Session saved: {key} (TTL: {expiry}s)")
#                 except Exception as e:
#                     _logger.error(f"Failed to save session: {e}")
            
#             def delete(self, session):
#                 """
#                 Delete session from Redis Master.
                
#                 Deletion propagates to all replicas automatically.
#                 """
#                 if self.master is None:
#                     return
                
#                 key = self._get_session_key(session.sid)
                
#                 try:
#                     self.master.delete(key)
#                     _logger.debug(f"Session deleted: {key}")
#                 except Exception as e:
#                     _logger.error(f"Failed to delete session: {e}")
            
#             def get(self, sid):
#                 """
#                 Get session from Redis.
                
#                 Read strategy:
#                 1. Try local replica first (fast, ~0.1ms)
#                 2. Fallback to master if local miss
#                 3. Return new session if not found
#                 """
#                 key = self._get_session_key(sid)
#                 data = None
                
#                 # Step 1: Try local replica (fast path)
#                 if self.local is not None:
#                     try:
#                         data = self.local.get(key)
#                         if data:
#                             _logger.debug(f"Session found (LOCAL): {key}")
#                     except Exception as e:
#                         _logger.warning(f"Local read failed: {e}")
                
#                 # Step 2: Fallback to master (sidecar mode only)
#                 if data is None and self.master is not None and SIDECAR_MODE:
#                     try:
#                         data = self.master.get(key)
#                         if data:
#                             _logger.debug(f"Session found (MASTER fallback): {key}")
#                     except Exception as e:
#                         _logger.error(f"Master read failed: {e}")
                
#                 # Step 3: Deserialize and return
#                 if data:
#                     try:
#                         session_data = pickle.loads(data)
#                         return self.session_class(session_data, sid=sid)
#                     except Exception as e:
#                         _logger.error(f"Failed to deserialize session: {e}")
                
#                 # Step 4: Return new empty session
#                 return self.session_class({}, sid=sid, new=True)
            
#             def rotate(self, session, env, soft=False):
#                 """
#                 Rotate session ID (security feature) compatible with Odoo 19.
#                 """
#                 if soft:
#                     static = session.sid[:STORED_SESSION_BYTES]
#                     recent_session = self.get(session.sid)
#                     if 'next_sid' in recent_session:
#                         session.sid = recent_session['next_sid']
#                         return session
#                     next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
#                     session['next_sid'] = next_sid
#                     session['deletion_time'] = time.time() + SESSION_DELETION_TIMER
#                     self.save(session)
#                     session['gc_previous_sessions'] = True
#                     session.sid = next_sid
#                     session.pop('deletion_time', None)
#                     session.pop('next_sid', None)
#                 else:
#                     self.delete(session)
#                     session.sid = self.generate_key()

#                 if session.get('uid'):
#                     assert env, "saving this session requires an environment"
#                     session.session_token = security.compute_session_token(session, env)

#                 session.should_rotate = False
#                 session['create_time'] = time.time()
#                 self.save(session)
#                 return session

#             def vacuum(self, max_lifetime=None):
#                 """Redis handles expiration via TTL automatically."""
#                 pass
            
#             def list(self):
#                 """List all session IDs (admin/debug use)."""
#                 if self.master is None:
#                     return []
                
#                 try:
#                     pattern = f"{SESSION_PREFIX}:*"
#                     keys = self.master.keys(pattern)
#                     prefix_len = len(SESSION_PREFIX) + 1
#                     return [key.decode()[prefix_len:] for key in keys]
#                 except Exception as e:
#                     _logger.error(f"Failed to list sessions: {e}")
#                     return []
            
#             def count(self):
#                 """Count total sessions (admin/debug use)."""
#                 return len(self.list())
        
#         # Apply the patch
#         if hasattr(root, 'session_store'):
#             root.session_store = RedisSidecarSessionStore(session_class=Session)
#             _logger.info("Odoo session store patched successfully")
#         else:
#             _logger.warning("Could not find root.session_store to patch")
            
#     except ImportError as e:
#         _logger.error(f"Failed to import Odoo modules: {e}")
#     except Exception as e:
#         _logger.error(f"Failed to patch session store: {e}")
#         import traceback
#         _logger.error(traceback.format_exc())


# # =============================================================================
# # Module Initialization
# # =============================================================================

# def post_init_hook(env):
#     """Post-installation hook."""
#     _logger.info("Redis Session Store (Sidecar Pattern) installed")


# # Apply patch on module load
# _patch_session_store()
