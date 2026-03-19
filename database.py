import sqlite3
from pathlib import Path

DB_PATH = Path("savl.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_name TEXT NOT NULL,
        team_role_id INTEGER NOT NULL UNIQUE,
        captain_discord_id INTEGER NOT NULL UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS roster (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        discord_id INTEGER NOT NULL,
        role_type TEXT NOT NULL CHECK(role_type IN ('player', 'vice_captain')),
        added_by INTEGER,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(team_id, discord_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        requester_discord_id INTEGER NOT NULL,
        player_discord_id INTEGER NOT NULL,
        requested_role_type TEXT NOT NULL CHECK(requested_role_type IN ('player', 'vice_captain')),
        roblox_username TEXT,
        roblox_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'denied')),
        reason TEXT,
        message_id INTEGER,
        channel_id INTEGER,
        handled_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1_role_id INTEGER NOT NULL,
        team1_name TEXT NOT NULL,
        team2_role_id INTEGER NOT NULL,
        team2_name TEXT NOT NULL,
        match_time_iso TEXT NOT NULL,
        reminded INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS match_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT NOT NULL,
        set1 TEXT,
        set2 TEXT,
        set3 TEXT,
        set4 TEXT,
        set5 TEXT,
        winner_team_role_id INTEGER NOT NULL,
        loser_team_role_id INTEGER NOT NULL,
        winner_mvp_discord_id INTEGER NOT NULL,
        loser_mvp_discord_id INTEGER NOT NULL,
        referee_discord_id INTEGER NOT NULL,
        media_link TEXT,
        created_by INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def execute(query: str, params: tuple = ()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    lastrowid = cur.lastrowid
    conn.close()
    return lastrowid


def fetchone(query: str, params: tuple = ()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return row


def fetchall(query: str, params: tuple = ()):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows