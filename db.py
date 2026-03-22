import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

log = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get('DATABASE_URL', '')
if _DATABASE_URL.startswith('postgres://'):
    _DATABASE_URL = _DATABASE_URL.replace('postgres://', 'postgresql://', 1)

_engine = None
_SessionLocal = None
_TOOL_ID: Optional[int] = None


def get_engine():
    global _engine
    if _engine is None and _DATABASE_URL:
        try:
            _engine = create_engine(_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
            log.info('[DB] Connected to central database')
        except Exception as e:
            log.error('[DB] Failed to connect: %s', e)
    return _engine


def get_session() -> Optional[Session]:
    global _SessionLocal
    engine = get_engine()
    if engine is None:
        return None
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


def ensure_schema() -> None:
    session = get_session()
    if not session:
        return
    try:
        engine_name = session.bind.dialect.name
        if engine_name == 'postgresql':
            stmts = [
                """
                CREATE TABLE IF NOT EXISTS checklist_jobs (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR(100) UNIQUE NOT NULL,
                    session_id VARCHAR(100) UNIQUE NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    plan_type VARCHAR(50),
                    tool_slug VARCHAR(50) NOT NULL DEFAULT 'checklist',
                    status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
                    current_step TEXT,
                    error_message TEXT,
                    upload_path TEXT,
                    extracted_data_path TEXT,
                    reviewed_data_path TEXT,
                    output_path TEXT,
                    uploaded_file_count INTEGER DEFAULT 0,
                    generated_file_count INTEGER DEFAULT 0,
                    extraction_token_charged BOOLEAN DEFAULT FALSE,
                    extraction_token_charge_id INTEGER,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    queued_at TIMESTAMP,
                    started_at TIMESTAMP,
                    extract_completed_at TIMESTAMP,
                    generated_at TIMESTAMP
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_checklist_jobs_status_queue ON checklist_jobs(tool_slug, status, queued_at)",
                "CREATE INDEX IF NOT EXISTS idx_checklist_jobs_user_status ON checklist_jobs(tenant_id, user_id, status)",
                """
                CREATE TABLE IF NOT EXISTS checklist_outputs (
                    id SERIAL PRIMARY KEY,
                    output_id VARCHAR(100) UNIQUE NOT NULL,
                    job_id VARCHAR(100) NOT NULL,
                    session_id VARCHAR(100) NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    template_key VARCHAR(100),
                    template_name VARCHAR(255) NOT NULL,
                    output_filename VARCHAR(255) NOT NULL,
                    output_path TEXT NOT NULL,
                    is_generated BOOLEAN DEFAULT TRUE,
                    generated_at TIMESTAMP DEFAULT NOW(),
                    download_token_charged BOOLEAN DEFAULT FALSE,
                    download_token_charge_id INTEGER,
                    first_downloaded_at TIMESTAMP,
                    last_downloaded_at TIMESTAMP,
                    download_count INTEGER DEFAULT 0
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_checklist_outputs_session_owner ON checklist_outputs(session_id, tenant_id, user_id)",
                "CREATE INDEX IF NOT EXISTS idx_checklist_outputs_job ON checklist_outputs(job_id)",
            ]
        else:
            stmts = [
                """
                CREATE TABLE IF NOT EXISTS checklist_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    session_id TEXT UNIQUE NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    plan_type TEXT,
                    tool_slug TEXT NOT NULL DEFAULT 'checklist',
                    status TEXT NOT NULL DEFAULT 'uploaded',
                    current_step TEXT,
                    error_message TEXT,
                    upload_path TEXT,
                    extracted_data_path TEXT,
                    reviewed_data_path TEXT,
                    output_path TEXT,
                    uploaded_file_count INTEGER DEFAULT 0,
                    generated_file_count INTEGER DEFAULT 0,
                    extraction_token_charged INTEGER DEFAULT 0,
                    extraction_token_charge_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    queued_at TEXT,
                    started_at TEXT,
                    extract_completed_at TEXT,
                    generated_at TEXT
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_checklist_jobs_status_queue ON checklist_jobs(tool_slug, status, queued_at)",
                "CREATE INDEX IF NOT EXISTS idx_checklist_jobs_user_status ON checklist_jobs(tenant_id, user_id, status)",
                """
                CREATE TABLE IF NOT EXISTS checklist_outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    output_id TEXT UNIQUE NOT NULL,
                    job_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    template_key TEXT,
                    template_name TEXT NOT NULL,
                    output_filename TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    is_generated INTEGER DEFAULT 1,
                    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    download_token_charged INTEGER DEFAULT 0,
                    download_token_charge_id INTEGER,
                    first_downloaded_at TEXT,
                    last_downloaded_at TEXT,
                    download_count INTEGER DEFAULT 0
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_checklist_outputs_session_owner ON checklist_outputs(session_id, tenant_id, user_id)",
                "CREATE INDEX IF NOT EXISTS idx_checklist_outputs_job ON checklist_outputs(job_id)",
            ]
        for stmt in stmts:
            session.execute(text(stmt))
        session.commit()
    except Exception as e:
        session.rollback()
        log.error('[DB] ensure_schema error: %s', e)
    finally:
        session.close()


def get_checklist_tool_id() -> Optional[int]:
    global _TOOL_ID
    if _TOOL_ID is not None:
        return _TOOL_ID
    session = get_session()
    if not session:
        return None
    try:
        result = session.execute(text("SELECT id FROM tools WHERE slug = 'checklist' LIMIT 1")).fetchone()
        if result:
            _TOOL_ID = result[0]
        return _TOOL_ID
    except Exception as e:
        log.error('[DB] get_checklist_tool_id error: %s', e)
        return None
    finally:
        session.close()


def get_tenant_tokens_remaining(tenant_id: int) -> int:
    session = get_session()
    if not session:
        return -1
    try:
        result = session.execute(text('SELECT tokens_total, tokens_used FROM tenants WHERE id = :tid'), {'tid': tenant_id}).fetchone()
        if not result:
            return 0
        return max(0, (result[0] or 0) - (result[1] or 0))
    except Exception as e:
        log.error('[DB] get_tenant_tokens_remaining error: %s', e)
        return -1
    finally:
        session.close()


def get_plan_concurrency(ctx: Dict[str, Any]) -> int:
    role = (ctx or {}).get('role')
    if role == 'owner':
        return 3
    plan_name = ((ctx or {}).get('plan_name') or '').lower()
    return 3 if 'standard' in plan_name or 'premium' in plan_name or 'pro' in plan_name else 1


def validate_user_token(token: str) -> Optional[dict]:
    if not token:
        return None
    session = get_session()
    if not session:
        return None
    try:
        row = session.execute(text("""
            SELECT u.id, u.tenant_id, u.role, u.active, u.name, t.status, t.company_name, t.plan_name
            FROM users u
            JOIN tenants t ON t.id = u.tenant_id
            WHERE u.id = (
                SELECT user_id FROM user_sessions WHERE token = :token AND expires_at > :now LIMIT 1
            )
        """), {'token': token, 'now': datetime.utcnow()}).fetchone()
        if not row:
            return None
        user_id, tenant_id, role, active, name, tenant_status, company_name, plan_name = row
        if not active or tenant_status != 'active':
            return None
        return {
            'user_id': user_id,
            'tenant_id': tenant_id,
            'role': role,
            'name': name,
            'tenant_name': company_name,
            'plan_name': plan_name or '',
        }
    except Exception as e:
        log.error('[DB] validate_user_token error: %s', e)
        return None
    finally:
        session.close()


def create_checklist_job(*, job_id: str, session_id: str, tenant_id: int, user_id: int, plan_type: str,
                         upload_path: str, uploaded_file_count: int) -> bool:
    ensure_schema()
    session = get_session()
    if not session:
        return False
    try:
        session.execute(text("""
            INSERT INTO checklist_jobs (job_id, session_id, tenant_id, user_id, plan_type, tool_slug, status,
                                        upload_path, uploaded_file_count, created_at, updated_at)
            VALUES (:job_id, :session_id, :tenant_id, :user_id, :plan_type, 'checklist', 'uploaded',
                    :upload_path, :uploaded_file_count, :now, :now)
        """), {
            'job_id': job_id, 'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id,
            'plan_type': plan_type, 'upload_path': upload_path, 'uploaded_file_count': uploaded_file_count,
            'now': datetime.utcnow(),
        })
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        log.error('[DB] create_checklist_job error: %s', e)
        return False
    finally:
        session.close()


def update_checklist_job(job_id: str, tenant_id: int, user_id: int, **fields) -> bool:
    if not fields:
        return True
    session = get_session()
    if not session:
        return False
    try:
        fields['updated_at'] = datetime.utcnow()
        sets = ', '.join(f"{k} = :{k}" for k in fields.keys())
        fields.update({'job_id': job_id, 'tenant_id': tenant_id, 'user_id': user_id})
        session.execute(text(f"UPDATE checklist_jobs SET {sets} WHERE job_id = :job_id AND tenant_id = :tenant_id AND user_id = :user_id"), fields)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        log.error('[DB] update_checklist_job error: %s', e)
        return False
    finally:
        session.close()


def queue_checklist_job(job_id: str, session_id: str, tenant_id: int, user_id: int) -> bool:
    session = get_session()
    if not session:
        return False
    try:
        result = session.execute(text("""
            UPDATE checklist_jobs
            SET status = 'extract_queued', queued_at = :now, error_message = NULL,
                current_step = 'Queued for extraction', updated_at = :now
            WHERE job_id = :job_id AND session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id
              AND status IN ('uploaded', 'extract_failed')
        """), {'job_id': job_id, 'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id, 'now': datetime.utcnow()})
        session.commit()
        return (result.rowcount or 0) > 0
    except Exception as e:
        session.rollback()
        log.error('[DB] queue_checklist_job error: %s', e)
        return False
    finally:
        session.close()


def get_checklist_job(job_id: str, tenant_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    session = get_session()
    if not session:
        return None
    try:
        row = session.execute(text("SELECT * FROM checklist_jobs WHERE job_id = :job_id AND tenant_id = :tenant_id AND user_id = :user_id"),
                              {'job_id': job_id, 'tenant_id': tenant_id, 'user_id': user_id}).mappings().first()
        return dict(row) if row else None
    except Exception as e:
        log.error('[DB] get_checklist_job error: %s', e)
        return None
    finally:
        session.close()


def get_job_by_session(session_id: str, tenant_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    session = get_session()
    if not session:
        return None
    try:
        row = session.execute(text("SELECT * FROM checklist_jobs WHERE session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id ORDER BY id DESC LIMIT 1"),
                              {'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id}).mappings().first()
        return dict(row) if row else None
    except Exception as e:
        log.error('[DB] get_job_by_session error: %s', e)
        return None
    finally:
        session.close()


def count_running_jobs_for_user(tenant_id: int, user_id: int) -> int:
    session = get_session()
    if not session:
        return 0
    try:
        row = session.execute(text("SELECT COUNT(*) FROM checklist_jobs WHERE tool_slug = 'checklist' AND status = 'extract_running' AND tenant_id = :tenant_id AND user_id = :user_id"),
                              {'tenant_id': tenant_id, 'user_id': user_id}).fetchone()
        return int(row[0] or 0)
    except Exception as e:
        log.error('[DB] count_running_jobs_for_user error: %s', e)
        return 0
    finally:
        session.close()


def count_total_running_jobs() -> int:
    session = get_session()
    if not session:
        return 0
    try:
        row = session.execute(text("SELECT COUNT(*) FROM checklist_jobs WHERE tool_slug = 'checklist' AND status = 'extract_running'" )).fetchone()
        return int(row[0] or 0)
    except Exception as e:
        log.error('[DB] count_total_running_jobs error: %s', e)
        return 0
    finally:
        session.close()


def list_queued_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    session = get_session()
    if not session:
        return []
    try:
        rows = session.execute(text("SELECT * FROM checklist_jobs WHERE tool_slug = 'checklist' AND status = 'extract_queued' ORDER BY queued_at ASC, created_at ASC LIMIT :limit"), {'limit': limit}).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error('[DB] list_queued_jobs error: %s', e)
        return []
    finally:
        session.close()


def claim_queued_job(job_id: str) -> bool:
    session = get_session()
    if not session:
        return False
    try:
        result = session.execute(text("""
            UPDATE checklist_jobs
            SET status = 'extract_running', started_at = :now, current_step = 'Starting extraction', updated_at = :now
            WHERE job_id = :job_id AND status = 'extract_queued'
        """), {'job_id': job_id, 'now': datetime.utcnow()})
        session.commit()
        return (result.rowcount or 0) == 1
    except Exception as e:
        session.rollback()
        log.error('[DB] claim_queued_job error: %s', e)
        return False
    finally:
        session.close()


def requeue_stale_running_jobs(minutes: int = 30) -> int:
    session = get_session()
    if not session:
        return 0
    try:
        cutoff = datetime.utcnow().timestamp() - (minutes * 60)
        dialect = session.bind.dialect.name
        if dialect == 'postgresql':
            result = session.execute(text("""
                UPDATE checklist_jobs
                SET status = 'extract_queued', current_step = 'Re-queued after stale worker recovery', updated_at = :now, queued_at = :now
                WHERE tool_slug = 'checklist' AND status = 'extract_running' AND started_at < :cutoff
            """), {'now': datetime.utcnow(), 'cutoff': datetime.utcfromtimestamp(cutoff)})
        else:
            # best effort for sqlite/text timestamps
            rows = session.execute(text("SELECT job_id, started_at FROM checklist_jobs WHERE tool_slug='checklist' AND status='extract_running'" )).mappings().all()
            count = 0
            for r in rows:
                st = r.get('started_at')
                try:
                    started_dt = datetime.fromisoformat(str(st).replace('Z', '+00:00').replace(' ', 'T'))
                except Exception:
                    continue
                if started_dt.timestamp() < cutoff:
                    session.execute(text("UPDATE checklist_jobs SET status='extract_queued', current_step='Re-queued after stale worker recovery', updated_at=:now, queued_at=:now WHERE job_id=:job_id AND status='extract_running'"), {'job_id': r['job_id'], 'now': datetime.utcnow()})
                    count += 1
            session.commit()
            return count
        session.commit()
        return int(result.rowcount or 0)
    except Exception as e:
        session.rollback()
        log.error('[DB] requeue_stale_running_jobs error: %s', e)
        return 0
    finally:
        session.close()


def record_usage(*, tenant_id: int, user_id: int, db_job_id: Optional[int], successful_outputs: int) -> Optional[int]:
    if successful_outputs <= 0:
        return None
    session = get_session()
    if not session:
        return None
    try:
        tool_id = get_checklist_tool_id()
        row = session.execute(text("""
            INSERT INTO usage_records (tenant_id, user_id, tool_id, job_id, billable_output_count, created_at)
            VALUES (:tenant_id, :user_id, :tool_id, :job_id, :count, :now)
            RETURNING id
        """), {'tenant_id': tenant_id, 'user_id': user_id, 'tool_id': tool_id, 'job_id': db_job_id, 'count': successful_outputs, 'now': datetime.utcnow()}).fetchone()
        session.execute(text("UPDATE tenants SET tokens_used = COALESCE(tokens_used, 0) + :count WHERE id = :tenant_id"), {'count': successful_outputs, 'tenant_id': tenant_id})
        session.commit()
        return row[0] if row else None
    except Exception as e:
        session.rollback()
        log.error('[DB] record_usage error: %s', e)
        return None
    finally:
        session.close()


def create_legacy_job_record(*, tenant_id: int, user_id: int, total_items: int, status: str = 'running') -> Optional[int]:
    session = get_session()
    if not session:
        return None
    try:
        tool_id = get_checklist_tool_id()
        row = session.execute(text("""
            INSERT INTO jobs (tenant_id, user_id, tool_id, status, total_items, successful_items, failed_items, created_at)
            VALUES (:tenant_id, :user_id, :tool_id, :status, :total_items, 0, 0, :now)
            RETURNING id
        """), {'tenant_id': tenant_id, 'user_id': user_id, 'tool_id': tool_id, 'status': status, 'total_items': total_items, 'now': datetime.utcnow()}).fetchone()
        session.commit()
        return row[0] if row else None
    except Exception as e:
        session.rollback()
        log.error('[DB] create_legacy_job_record error: %s', e)
        return None
    finally:
        session.close()


def update_legacy_job_status(*, db_job_id: int, status: str, successful_items: int, failed_items: int) -> None:
    session = get_session()
    if not session:
        return
    try:
        session.execute(text("""
            UPDATE jobs
            SET status = :status,
                successful_items = :successful_items,
                failed_items = :failed_items,
                completed_at = :completed_at
            WHERE id = :job_id
        """), {'status': status, 'successful_items': successful_items, 'failed_items': failed_items,
                'completed_at': datetime.utcnow() if status in ('completed', 'failed') else None, 'job_id': db_job_id})
        session.commit()
    except Exception as e:
        session.rollback()
        log.error('[DB] update_legacy_job_status error: %s', e)
    finally:
        session.close()


def save_output_rows(*, job_id: str, session_id: str, tenant_id: int, user_id: int, outputs: List[Dict[str, Any]]) -> bool:
    session = get_session()
    if not session:
        return False
    try:
        for out in outputs:
            session.execute(text("""
                INSERT INTO checklist_outputs (output_id, job_id, session_id, tenant_id, user_id,
                                               template_key, template_name, output_filename, output_path,
                                               is_generated, generated_at, download_token_charged, download_count)
                VALUES (:output_id, :job_id, :session_id, :tenant_id, :user_id,
                        :template_key, :template_name, :output_filename, :output_path,
                        :is_generated, :generated_at, :download_token_charged, :download_count)
            """), {
                'output_id': out['output_id'], 'job_id': job_id, 'session_id': session_id,
                'tenant_id': tenant_id, 'user_id': user_id, 'template_key': out.get('template_key'),
                'template_name': out.get('template_name'), 'output_filename': out.get('output_filename'),
                'output_path': out.get('output_path'), 'is_generated': 1, 'generated_at': datetime.utcnow(),
                'download_token_charged': 0, 'download_count': 0,
            })
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        log.error('[DB] save_output_rows error: %s', e)
        return False
    finally:
        session.close()


def list_outputs(session_id: str, tenant_id: int, user_id: int) -> List[Dict[str, Any]]:
    session = get_session()
    if not session:
        return []
    try:
        rows = session.execute(text("SELECT * FROM checklist_outputs WHERE session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id AND is_generated = 1 ORDER BY generated_at ASC"),
                              {'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id}).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error('[DB] list_outputs error: %s', e)
        return []
    finally:
        session.close()


def get_output_by_filename(session_id: str, tenant_id: int, user_id: int, filename: str) -> Optional[Dict[str, Any]]:
    session = get_session()
    if not session:
        return None
    try:
        row = session.execute(text("SELECT * FROM checklist_outputs WHERE session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id AND output_filename = :filename LIMIT 1"),
                              {'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id, 'filename': filename}).mappings().first()
        return dict(row) if row else None
    except Exception as e:
        log.error('[DB] get_output_by_filename error: %s', e)
        return None
    finally:
        session.close()


def mark_output_downloaded(output_id: str, tenant_id: int, user_id: int, charge_usage_id: Optional[int] = None, charge_now: bool = False) -> bool:
    session = get_session()
    if not session:
        return False
    try:
        if charge_now:
            session.execute(text("""
                UPDATE checklist_outputs
                SET download_token_charged = 1,
                    download_token_charge_id = :charge_id,
                    first_downloaded_at = COALESCE(first_downloaded_at, :now),
                    last_downloaded_at = :now,
                    download_count = COALESCE(download_count, 0) + 1
                WHERE output_id = :output_id AND tenant_id = :tenant_id AND user_id = :user_id
            """), {'output_id': output_id, 'tenant_id': tenant_id, 'user_id': user_id, 'charge_id': charge_usage_id, 'now': datetime.utcnow()})
        else:
            session.execute(text("""
                UPDATE checklist_outputs
                SET last_downloaded_at = :now,
                    download_count = COALESCE(download_count, 0) + 1
                WHERE output_id = :output_id AND tenant_id = :tenant_id AND user_id = :user_id
            """), {'output_id': output_id, 'tenant_id': tenant_id, 'user_id': user_id, 'now': datetime.utcnow()})
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        log.error('[DB] mark_output_downloaded error: %s', e)
        return False
    finally:
        session.close()


def mark_multiple_outputs_downloaded(session_id: str, tenant_id: int, user_id: int, output_ids_to_charge: List[str], charge_usage_id: Optional[int] = None) -> bool:
    session = get_session()
    if not session:
        return False
    try:
        now = datetime.utcnow()
        if output_ids_to_charge:
            session.execute(text("""
                UPDATE checklist_outputs
                SET download_token_charged = 1,
                    download_token_charge_id = :charge_id,
                    first_downloaded_at = COALESCE(first_downloaded_at, :now),
                    last_downloaded_at = :now,
                    download_count = COALESCE(download_count, 0) + 1
                WHERE session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id
                  AND output_id IN :output_ids
            """).bindparams(text('')), {'charge_id': charge_usage_id, 'now': now, 'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id, 'output_ids': tuple(output_ids_to_charge)})
        session.execute(text("""
            UPDATE checklist_outputs
            SET last_downloaded_at = :now,
                download_count = COALESCE(download_count, 0) + 1
            WHERE session_id = :session_id AND tenant_id = :tenant_id AND user_id = :user_id AND is_generated = 1
        """), {'now': now, 'session_id': session_id, 'tenant_id': tenant_id, 'user_id': user_id})
        session.commit()
        return True
    except Exception:
        session.rollback()
        # fallback per-row for sqlite / IN handling differences
        try:
            outs = list_outputs(session_id, tenant_id, user_id)
            session = get_session()
            for out in outs:
                charge = out['output_id'] in set(output_ids_to_charge)
                if charge:
                    session.execute(text("UPDATE checklist_outputs SET download_token_charged = 1, download_token_charge_id = :charge_id, first_downloaded_at = COALESCE(first_downloaded_at, :now), last_downloaded_at = :now, download_count = COALESCE(download_count,0)+1 WHERE output_id=:output_id AND tenant_id=:tenant_id AND user_id=:user_id"),
                                    {'charge_id': charge_usage_id, 'now': datetime.utcnow(), 'output_id': out['output_id'], 'tenant_id': tenant_id, 'user_id': user_id})
                else:
                    session.execute(text("UPDATE checklist_outputs SET last_downloaded_at = :now, download_count = COALESCE(download_count,0)+1 WHERE output_id=:output_id AND tenant_id=:tenant_id AND user_id=:user_id"),
                                    {'now': datetime.utcnow(), 'output_id': out['output_id'], 'tenant_id': tenant_id, 'user_id': user_id})
            session.commit()
            return True
        except Exception as e:
            log.error('[DB] mark_multiple_outputs_downloaded error: %s', e)
            try:
                session.rollback()
            except Exception:
                pass
            return False
        finally:
            try:
                session.close()
            except Exception:
                pass
