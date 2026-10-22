"""Кто просил VPN и какие настройки ему выданы. Хранится в файле SQLite.

Закрытые ключи клиентов здесь не храним: они уходят человеку один раз.
"""
import sqlite3
import time

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
REVOKED = "revoked"


class Db:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS peers (
                public_key TEXT PRIMARY KEY,
                tg_id INTEGER NOT NULL,
                ip TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )

    def user(self, tg_id: int):
        return self.conn.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()

    def set_user(self, tg_id: int, name: str, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO users (tg_id, name, status, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(tg_id) DO UPDATE SET name = excluded.name,"
                " status = excluded.status, updated_at = excluded.updated_at",
                (tg_id, name, status, int(time.time())),
            )

    def set_status(self, tg_id: int, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE tg_id = ?",
                (status, int(time.time()), tg_id),
            )

    def approved_users(self):
        return self.conn.execute(
            "SELECT u.tg_id, u.name, COUNT(p.public_key) AS devices FROM users u"
            " LEFT JOIN peers p ON p.tg_id = u.tg_id"
            " WHERE u.status = ? GROUP BY u.tg_id ORDER BY u.name",
            (APPROVED,),
        ).fetchall()

    def peers_of(self, tg_id: int):
        return self.conn.execute("SELECT * FROM peers WHERE tg_id = ?", (tg_id,)).fetchall()

    def add_peer(self, tg_id: int, public_key: str, ip: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO peers (public_key, tg_id, ip, created_at) VALUES (?, ?, ?, ?)",
                (public_key, tg_id, ip, int(time.time())),
            )

    def remove_peer(self, public_key: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM peers WHERE public_key = ?", (public_key,))
