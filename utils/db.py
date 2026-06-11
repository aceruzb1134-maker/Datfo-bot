import os
import asyncpg

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ.get("DATABASE_URL"), ssl="require")
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pharmacies (
                id            SERIAL PRIMARY KEY,
                inn           TEXT    UNIQUE NOT NULL,
                legal_name    TEXT,
                name          TEXT    NOT NULL,
                telegram_id   BIGINT  UNIQUE,
                registered_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id          SERIAL PRIMARY KEY,
                producer    TEXT NOT NULL,
                period      TEXT NOT NULL,
                status      TEXT DEFAULT 'draft',
                created_at  TIMESTAMP DEFAULT NOW(),
                sent_at     TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pharmacy_plans (
                id           SERIAL PRIMARY KEY,
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
                UNIQUE(campaign_id, pharmacy_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS plan_items (
                id          SERIAL PRIMARY KEY,
                campaign_id INTEGER NOT NULL,
                pharmacy_id INTEGER NOT NULL,
                month       TEXT NOT NULL,
                sku         TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                price       REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id          SERIAL PRIMARY KEY,
                campaign_id INTEGER NOT NULL,
                pharmacy_id INTEGER NOT NULL,
                answer      TEXT,
                answered_at TIMESTAMP,
                reminded_at TIMESTAMP,
                UNIQUE(campaign_id, pharmacy_id)
            )
        """)


# ── Pharmacy ──────────────────────────────────────────────────────────────────

async def upsert_pharmacy(inn: str, name: str, legal_name: str = "") -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow("""
            INSERT INTO pharmacies (inn, name, legal_name)
            VALUES ($1, $2, $3)
            ON CONFLICT(inn) DO UPDATE SET name = EXCLUDED.name, legal_name = EXCLUDED.legal_name
            RETURNING id
        """, inn, name, legal_name)
        return row["id"]


async def get_pharmacy_by_inn(inn: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetchrow("SELECT * FROM pharmacies WHERE inn = $1", inn)


async def get_pharmacy_by_tg(telegram_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetchrow("SELECT * FROM pharmacies WHERE telegram_id = $1", telegram_id)


async def link_pharmacy_telegram(inn: str, telegram_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            UPDATE pharmacies SET telegram_id = $1, registered_at = NOW() WHERE inn = $2
        """, telegram_id, inn)


async def get_all_pharmacies():
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("SELECT * FROM pharmacies ORDER BY inn")


# ── Campaign ──────────────────────────────────────────────────────────────────

async def create_campaign(producer: str, period: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        row = await db.fetchrow(
            "INSERT INTO campaigns (producer, period) VALUES ($1, $2) RETURNING id",
            producer, period
        )
        return row["id"]


async def get_campaign(campaign_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetchrow("SELECT * FROM campaigns WHERE id = $1", campaign_id)


async def get_active_campaign():
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetchrow(
            "SELECT * FROM campaigns WHERE status = 'active' ORDER BY sent_at DESC LIMIT 1"
        )


async def activate_campaign(campaign_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE campaigns SET status = 'active', sent_at = NOW() WHERE id = $1",
            campaign_id
        )


# ── Pharmacy plans ────────────────────────────────────────────────────────────

async def save_pharmacy_plan(campaign_id: int, pharmacy_id: int, plan: dict):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO pharmacy_plans
                (campaign_id, pharmacy_id, plan_total, plan_jan, plan_feb, plan_mar,
                 bonus_jan, bonus_feb, bonus_mar, bonus_total)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET
                plan_total=EXCLUDED.plan_total, plan_jan=EXCLUDED.plan_jan,
                plan_feb=EXCLUDED.plan_feb, plan_mar=EXCLUDED.plan_mar,
                bonus_jan=EXCLUDED.bonus_jan, bonus_feb=EXCLUDED.bonus_feb,
                bonus_mar=EXCLUDED.bonus_mar, bonus_total=EXCLUDED.bonus_total
        """, campaign_id, pharmacy_id,
            plan.get("plan_total", 0), plan.get("plan_jan", 0),
            plan.get("plan_feb", 0), plan.get("plan_mar", 0),
            plan.get("bonus_jan", 0), plan.get("bonus_feb", 0),
            plan.get("bonus_mar", 0), plan.get("bonus_total", 0)
        )


async def get_pharmacy_plan(campaign_id: int, pharmacy_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetchrow("""
            SELECT * FROM pharmacy_plans WHERE campaign_id=$1 AND pharmacy_id=$2
        """, campaign_id, pharmacy_id)


# ── Plan items ────────────────────────────────────────────────────────────────

async def save_plan_items_month(campaign_id: int, pharmacy_id: int, month: str, items: list):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM plan_items WHERE campaign_id=$1 AND pharmacy_id=$2 AND month=$3",
            campaign_id, pharmacy_id, month
        )
        for item in items:
            await db.execute(
                "INSERT INTO plan_items (campaign_id, pharmacy_id, month, sku, qty, price) VALUES ($1,$2,$3,$4,$5,$6)",
                campaign_id, pharmacy_id, month, item["sku"], item["qty"], item.get("price", 0)
            )


async def get_plan_items_month(campaign_id: int, pharmacy_id: int, month: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("""
            SELECT * FROM plan_items WHERE campaign_id=$1 AND pharmacy_id=$2 AND month=$3
        """, campaign_id, pharmacy_id, month)


async def get_all_plan_items(campaign_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("SELECT * FROM plan_items WHERE campaign_id=$1", campaign_id)


async def get_pharmacies_in_campaign(campaign_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("""
            SELECT DISTINCT p.* FROM pharmacy_plans pp
            JOIN pharmacies p ON p.id = pp.pharmacy_id
            WHERE pp.campaign_id = $1
        """, campaign_id)


# ── Responses ─────────────────────────────────────────────────────────────────

async def save_response(campaign_id: int, pharmacy_id: int, answer: str):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO responses (campaign_id, pharmacy_id, answer, answered_at)
            VALUES ($1,$2,$3,NOW())
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET
                answer=EXCLUDED.answer, answered_at=NOW()
        """, campaign_id, pharmacy_id, answer)


async def mark_reminded(campaign_id: int, pharmacy_id: int):
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute("""
            INSERT INTO responses (campaign_id, pharmacy_id, reminded_at)
            VALUES ($1,$2,NOW())
            ON CONFLICT(campaign_id, pharmacy_id) DO UPDATE SET reminded_at=NOW()
        """, campaign_id, pharmacy_id)


async def get_campaign_stats(campaign_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as db:
        total    = await db.fetchval("SELECT COUNT(DISTINCT pharmacy_id) FROM pharmacy_plans WHERE campaign_id=$1", campaign_id)
        answered = await db.fetchval("SELECT COUNT(*) FROM responses WHERE campaign_id=$1 AND answer IS NOT NULL", campaign_id)
        yes      = await db.fetchval("SELECT COUNT(*) FROM responses WHERE campaign_id=$1 AND answer='yes'", campaign_id)
        no       = await db.fetchval("SELECT COUNT(*) FROM responses WHERE campaign_id=$1 AND answer='no'", campaign_id)
        return {"total": total, "answered": answered, "yes": yes, "no": no, "pending": total - answered}


async def get_unanswered_pharmacies(campaign_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("""
            SELECT DISTINCT p.* FROM pharmacy_plans pp
            JOIN pharmacies p ON p.id = pp.pharmacy_id
            WHERE pp.campaign_id = $1
              AND p.telegram_id IS NOT NULL
              AND p.id NOT IN (
                  SELECT pharmacy_id FROM responses
                  WHERE campaign_id = $1 AND answer IS NOT NULL
              )
        """, campaign_id)


async def get_yes_pharmacies(campaign_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        return await db.fetch("""
            SELECT p.inn, p.name, r.answered_at
            FROM responses r
            JOIN pharmacies p ON p.id = r.pharmacy_id
            WHERE r.campaign_id = $1 AND r.answer = 'yes'
            ORDER BY p.inn
        """, campaign_id)
