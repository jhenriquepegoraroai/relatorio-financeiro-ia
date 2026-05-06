import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "logs" / "interacoes.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS interacoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    referencia    TEXT    NOT NULL,
    pergunta      TEXT    NOT NULL,
    resposta      TEXT    NOT NULL,
    modelo        TEXT    NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    sql_usado     TEXT    NOT NULL DEFAULT ''
)
"""

_MIGRATE_SQL = "ALTER TABLE interacoes ADD COLUMN modelo TEXT NOT NULL DEFAULT ''"


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(_CREATE_SQL)
        # migração: adiciona coluna se o banco já existia sem ela
        cols = {row[1] for row in conn.execute("PRAGMA table_info(interacoes)")}
        if "modelo" not in cols:
            conn.execute(_MIGRATE_SQL)


def registrar_log(
    referencia: str,
    pergunta: str,
    resposta: str,
    modelo: str,
    input_tokens: int,
    output_tokens: int,
    sql_usado: str,
) -> None:
    init_db()
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO interacoes (timestamp, referencia, pergunta, resposta, modelo, "
            "input_tokens, output_tokens, sql_usado) VALUES (?,?,?,?,?,?,?,?)",
            (ts, referencia, pergunta, resposta, modelo, input_tokens, output_tokens, sql_usado),
        )


def listar_logs(limit: int = 100) -> list[dict]:
    if not _DB_PATH.exists():
        return []
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM interacoes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
