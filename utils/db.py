import aiosqlite
import os

DB_PATH = "/tmp/datfo.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pharmacies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                inn           TEXT    UNIQUE NOT NULL,
                legal_name    TEXT,
                name          TEXT    NOT NULL,
                telegram_id   INTEGER UNIQUE,
                registered_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                producer     TEXT NOT NULL,
                period       TEXT NOT NULL,
                status       TEXT DEFAULT 'draft',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at      TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pharmacy_plans (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id  INTEGER NOT NULL,
                pharmacy_id  INTEGER NOT NULL,
                plan_total   REAL DEFAULT 0,
                plan_jan     REAL DEFAULT 0,
                plan_feb     REAL DEFAULT 0,
                plan_mar     REAL DEFAULT 0,
                bonus_jan    REAL DEFAULT 0,
                bonus_feb    REAL DEFAULT 0,
                bonus_mar    REAL DEFAULT 0,
                bonus_total  REAL DEFAULT 0,
                UNIQUE(campaign_id, pharmacy_id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS plan_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                pharmacy_id INTEGER NOT NULL,
                month       TEXT NOT NULL,
                sku         TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                price       REAL DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                pharmacy_id INTEGER NOT NULL,
                answer      TEXT,
                answered_at TIMESTAMP,
                reminded_at TIMESTAMP,
                UNIQUE(campaign_id, pharmacy_id),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (pharmacy_id) REFERENCES pharmacies(id)
            )
        """)
        await db.commit()


# ── Pharmacy ──────────────────────────────────────────────────────────────────

async def upsert_pharmacy(inn: str, name: str, legal_name: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO pharmacies (inn, name, legal_name)
            VALUES (?, ?, ?)
            ON CONFLICT(inn) DO UPDATE SET
                name = excluded.name,
                legal_name = excluded.legal_name
        """, (inn, name, legal_name))
        await db.commit()
        async with db.execute("SELECT id FROM pharmacies WHERE inn = ?", (inn,)) as cur:
            row = await cur.fetchone()
            return row[0]


async def get_pharmacy_by_inn(inn: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pharmacies WHERE inn = ?", (inn,)) as cur:
            return await cur.fetchone()


async def get_pharmacy_by_tg(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pharmacies WHERE telegram_id = ?", (telegram_id,)) as cur:
            return await cur.fetchone()


async def link_pharmacy_telegram(inn: str, telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE pharmacies SET telegram_id = ?, registered_at = CURRENT_TIMESTAMP
            WHERE inn = ?
        """, (telegram_id, inn))
        await db.commit()


async def get_all_pharmacies():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pharmacies ORDER BY inn") as cur:
            return await cur.fetchall()


# ── Campaign ──────────────────────────────────────────────────────────────────

async def create_campaign(producer: str, period: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO campaigns (producer, period) VALUES (?, ?)",
            (producer, period)
        )
        await db.commit()
        return cur.lastrowid


async def get_campaign(campaign_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)) as cur:
            return await cur.fetchone()


async def get_active_campaign():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM campaigns WHERE status = 'active' ORDER BY sent_at DESC LIMIT 1"
        ) as cur:
            return await cur.fetchone()


async def activate_campaign(campaign_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE campaigns SET status = 'active', sent_at = CURRENT_TIMESTAMP WHERE id = ?",
            (campaign_id,)
        )
        await db.commit()


# ── Pharmacy plans ────────────────────────────────────────────────────────────

async def save_pharmacy_plan(campaign_id: int, pharmacy_id: int, plan: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO pharmacy_plans
                (campaign_id, pharmacy_id, plan_total, plan_jan, plan_feb, plan_mar,
                 bonus_jan, bonus_feb, bonus_mar, bonus_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET
                plan_total  = excluded.plan_total,
                plan_jan    = excluded.plan_jan,
                plan_feb    = excluded.plan_feb,
                plan_mar    = excluded.plan_mar,
                bonus_jan   = excluded.bonus_jan,
                bonus_feb   = excluded.bonus_feb,
                bonus_mar   = excluded.bonus_mar,
                bonus_total = excluded.bonus_total
        """, (
            campaign_id, pharmacy_id,
            plan.get("plan_total", 0), plan.get("plan_jan", 0),
            plan.get("plan_feb", 0), plan.get("plan_mar", 0),
            plan.get("bonus_jan", 0), plan.get("bonus_feb", 0),
            plan.get("bonus_mar", 0), plan.get("bonus_total", 0),
        ))
        await db.commit()


async def get_pharmacy_plan(campaign_id: int, pharmacy_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM pharmacy_plans
            WHERE campaign_id = ? AND pharmacy_id = ?
        """, (campaign_id, pharmacy_id)) as cur:
            return await cur.fetchone()


# ── Plan items (препараты по месяцам) ─────────────────────────────────────────

async def save_plan_items_month(campaign_id: int, pharmacy_id: int, month: str, items: list):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM plan_items WHERE campaign_id=? AND pharmacy_id=? AND month=?",
            (campaign_id, pharmacy_id, month)
        )
        for item in items:
            await db.execute(
                "INSERT INTO plan_items (campaign_id, pharmacy_id, month, sku, qty, price) VALUES (?,?,?,?,?,?)",
                (campaign_id, pharmacy_id, month, item["sku"], item["qty"], item.get("price", 0))
            )
        await db.commit()


async def get_plan_items_month(campaign_id: int, pharmacy_id: int, month: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM plan_items
            WHERE campaign_id=? AND pharmacy_id=? AND month=?
        """, (campaign_id, pharmacy_id, month)) as cur:
            return await cur.fetchall()


async def get_all_plan_items(campaign_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM plan_items WHERE campaign_id=?", (campaign_id,)
        ) as cur:
            return await cur.fetchall()


async def get_pharmacies_in_campaign(campaign_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT DISTINCT p.*
            FROM pharmacy_plans pp
            JOIN pharmacies p ON p.id = pp.pharmacy_id
            WHERE pp.campaign_id = ?
        """, (campaign_id,)) as cur:
            return await cur.fetchall()


# ── Responses ─────────────────────────────────────────────────────────────────

async def save_response(campaign_id: int, pharmacy_id: int, answer: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO responses (campaign_id, pharmacy_id, answer, answered_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET
                answer = excluded.answer, answered_at = excluded.answered_at
        """, (campaign_id, pharmacy_id, answer))
        await db.commit()


async def mark_reminded(campaign_id: int, pharmacy_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO responses (campaign_id, pharmacy_id, reminded_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET reminded_at = CURRENT_TIMESTAMP
        """, (campaign_id, pharmacy_id))
        await db.commit()


async def get_campaign_stats(campaign_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async def count(sql, *args):
            async with db.execute(sql, args) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

        total    = await count("SELECT COUNT(DISTINCT pharmacy_id) FROM pharmacy_plans WHERE campaign_id=?", campaign_id)
        answered = await count("SELECT COUNT(*) FROM responses WHERE campaign_id=? AND answer IS NOT NULL", campaign_id)
        yes      = await count("SELECT COUNT(*) FROM responses WHERE campaign_id=? AND answer='yes'", campaign_id)
        no       = await count("SELECT COUNT(*) FROM responses WHERE campaign_id=? AND answer='no'", campaign_id)
        return {"total": total, "answered": answered, "yes": yes, "no": no, "pending": total - answered}


async def get_unanswered_pharmacies(campaign_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT DISTINCT p.* FROM pharmacy_plans pp
            JOIN pharmacies p ON p.id = pp.pharmacy_id
            WHERE pp.campaign_id = ?
              AND p.telegram_id IS NOT NULL
              AND p.id NOT IN (
                  SELECT pharmacy_id FROM responses
                  WHERE campaign_id = ? AND answer IS NOT NULL
              )
        """, (campaign_id, campaign_id)) as cur:
            return await cur.fetchall()


async def get_yes_pharmacies(campaign_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT p.inn, p.name, r.answered_at
            FROM responses r
            JOIN pharmacies p ON p.id = r.pharmacy_id
            WHERE r.campaign_id = ? AND r.answer = 'yes'
            ORDER BY p.inn
        """, (campaign_id,)) as cur:
            return await cur.fetchall()
