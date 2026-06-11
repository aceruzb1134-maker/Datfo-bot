import math
import openpyxl
from io import BytesIO
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.db import (
    create_campaign, get_campaign, activate_campaign,
    get_campaign_stats, get_yes_pharmacies, get_all_pharmacies,
    get_unanswered_pharmacies, mark_reminded, get_active_campaign,
    save_pharmacy_plan, get_pharmacy_plan, save_plan_items_month,
    get_plan_items_month, get_pharmacies_in_campaign,
    get_pharmacy_by_inn, upsert_pharmacy, get_pharmacy_by_tg,
    get_all_plan_items, save_response,
)
from utils.excel import (
    parse_svod, parse_month_sheet,
    format_pharmacy_plan_message, format_admin_preview,
    format_my_plan_message,
)
from keyboards.kb import (
    confirm_send_kb, admin_main_kb, remind_confirm_kb,
    pharmacy_answer_kb, confirm_repeat_kb,
)

router = Router()

# Global map for +30% repeat source
_repeat_map: dict[int, int] = {}


class UploadState(StatesGroup):
    waiting_for_file = State()


class AddPharmacyState(StatesGroup):
    waiting_for_inn  = State()
    waiting_for_name = State()


def is_admin(user_id: int, admin_ids: list) -> bool:
    return user_id in admin_ids


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def admin_start(message: Message, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await message.answer(
        "👋 Добро пожаловать в панель *DATFO*!\n\n"
        "• 📤 Загрузите Excel со сводным планом квартала\n"
        "• 🔄 Повторите прошлый план +30%\n"
        "• 📊 Следите за статистикой",
        parse_mode="Markdown",
        reply_markup=admin_main_kb()
    )


# ── Upload Excel plan ─────────────────────────────────────────────────────────

@router.message(F.text == "📤 Загрузить план (Excel)")
async def prompt_upload(message: Message, state: FSMContext, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return
    await state.set_state(UploadState.waiting_for_file)
    await message.answer(
        "📎 *Отправьте Excel-файл со сводным планом.*\n\n"
        "Файл должен содержать листы:\n"
        "• *Svod* — сводный план квартала\n"
        "• *Yanvar* — препараты на январь\n"
        "• *Fevral* — препараты на февраль\n"
        "• *Mart* — препараты на март\n\n"
        "ИНН аптек из файла автоматически добавятся в систему.",
        parse_mode="Markdown"
    )


@router.message(UploadState.waiting_for_file, F.document)
async def handle_excel(message: Message, state: FSMContext, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return

    doc = message.document
    if not doc.file_name.endswith((".xlsx", ".xls")):
        await message.answer("❌ Нужен файл .xlsx")
        return

    processing = await message.answer("⏳ Обрабатываю файл...")
    file = await message.bot.get_file(doc.file_id)
    content = (await message.bot.download_file(file.file_path)).read()

    # Parse Svod
    svod = parse_svod(content)
    if not svod:
        await processing.edit_text("❌ Не удалось прочитать лист Svod. Проверьте формат файла.")
        await state.clear()
        return

    # Parse monthly sheets
    items_jan = parse_month_sheet(content, "Yanvar")
    items_feb = parse_month_sheet(content, "Fevral")
    items_mar = parse_month_sheet(content, "Mart")

    # Create campaign
    campaign_id = await create_campaign(svod["producer"], svod["period"])

    # Save all pharmacies and their plans
    saved = 0
    for inn, ph_data in svod["pharmacies"].items():
        ph_id = await upsert_pharmacy(inn, ph_data["name"], ph_data.get("legal_name", ""))
        await save_pharmacy_plan(campaign_id, ph_id, ph_data)

        if inn in items_jan:
            await save_plan_items_month(campaign_id, ph_id, "jan", items_jan[inn])
        if inn in items_feb:
            await save_plan_items_month(campaign_id, ph_id, "feb", items_feb[inn])
        if inn in items_mar:
            await save_plan_items_month(campaign_id, ph_id, "mar", items_mar[inn])
        saved += 1

    await state.clear()

    registered = 0
    for ph in svod["pharmacies"].values():
        ph_record = await get_pharmacy_by_inn(ph["inn"])
        if ph_record and ph_record["telegram_id"]:
            registered += 1

    preview = format_admin_preview(svod)
    await processing.edit_text(
        f"{preview}\n\n"
        f"✅ Загружено аптек: *{saved}*\n"
        f"📲 Уже зарегистрированы в боте: *{registered}*",
        parse_mode="Markdown",
        reply_markup=confirm_send_kb(campaign_id)
    )


# ── Broadcast ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("send:"))
async def confirm_broadcast(callback: CallbackQuery, admin_ids: list):
    if not is_admin(callback.from_user.id, admin_ids):
        return

    campaign_id = int(callback.data.split(":")[1])
    campaign = await get_campaign(campaign_id)
    if not campaign:
        await callback.answer("Кампания не найдена", show_alert=True)
        return

    await activate_campaign(campaign_id)
    pharmacies = await get_pharmacies_in_campaign(campaign_id)
    status_msg = await callback.message.answer(f"📤 Начинаю рассылку по {len(pharmacies)} аптекам...")
    sent, skipped = 0, 0

    for pharmacy in pharmacies:
        if not pharmacy["telegram_id"]:
            skipped += 1
            continue

        plan = await get_pharmacy_plan(campaign_id, pharmacy["id"])
        if not plan:
            skipped += 1
            continue

        items_jan = await get_plan_items_month(campaign_id, pharmacy["id"], "jan")
        items_feb = await get_plan_items_month(campaign_id, pharmacy["id"], "feb")
        items_mar = await get_plan_items_month(campaign_id, pharmacy["id"], "mar")

        ph_dict = {
            "plan_total":  plan["plan_total"],
            "plan_jan":    plan["plan_jan"],
            "plan_feb":    plan["plan_feb"],
            "plan_mar":    plan["plan_mar"],
            "bonus_jan":   plan["bonus_jan"],
            "bonus_feb":   plan["bonus_feb"],
            "bonus_mar":   plan["bonus_mar"],
            "bonus_total": plan["bonus_total"],
        }
        items_j = [{"sku": i["sku"], "qty": i["qty"]} for i in items_jan]
        items_f = [{"sku": i["sku"], "qty": i["qty"]} for i in items_feb]
        items_m = [{"sku": i["sku"], "qty": i["qty"]} for i in items_mar]

        text = format_pharmacy_plan_message(ph_dict, items_j, items_f, items_m)

        try:
            await callback.bot.send_message(
                chat_id=pharmacy["telegram_id"],
                text=text,
                parse_mode="Markdown",
                reply_markup=pharmacy_answer_kb(campaign_id)
            )
            sent += 1
        except Exception:
            skipped += 1

        if sent % 30 == 0:
            try:
                await status_msg.edit_text(f"📤 Отправлено: {sent}...")
            except Exception:
                pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await status_msg.edit_text(
        f"✅ *Рассылка завершена!*\n\n"
        f"📨 Отправлено: *{sent}*\n"
        f"⏳ Не зарегистрированы (пропущено): *{skipped}*",
        parse_mode="Markdown"
    )
    await callback.answer()


# ── Repeat +30% ───────────────────────────────────────────────────────────────

@router.message(F.text == "🔄 Повторить +30%")
async def repeat_start(message: Message, state: FSMContext, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Нет прошлых кампаний. Загрузите план через Excel.")
        return

    pharmacies = await get_pharmacies_in_campaign(campaign["id"])
    await state.update_data(source_campaign_id=campaign["id"])

    new_campaign_id = await create_campaign(
        campaign["producer"] + " (+30%)",
        campaign["period"] + " (новый)"
    )
    _repeat_map[new_campaign_id] = campaign["id"]

    # Copy all plans with +30%
    for pharmacy in pharmacies:
        plan = await get_pharmacy_plan(campaign["id"], pharmacy["id"])
        if not plan:
            continue

        new_plan = {
            "plan_total":  math.ceil(plan["plan_total"] * 1.3),
            "plan_jan":    math.ceil(plan["plan_jan"]   * 1.3),
            "plan_feb":    math.ceil(plan["plan_feb"]   * 1.3),
            "plan_mar":    math.ceil(plan["plan_mar"]   * 1.3),
            "bonus_jan":   plan["bonus_jan"],
            "bonus_feb":   plan["bonus_feb"],
            "bonus_mar":   plan["bonus_mar"],
            "bonus_total": plan["bonus_total"],
        }
        await save_pharmacy_plan(new_campaign_id, pharmacy["id"], new_plan)

        for month in ("jan", "feb", "mar"):
            items = await get_plan_items_month(campaign["id"], pharmacy["id"], month)
            new_items = [
                {"sku": i["sku"], "qty": math.ceil(i["qty"] * 1.3), "price": i["price"]}
                for i in items
            ]
            if new_items:
                await save_plan_items_month(new_campaign_id, pharmacy["id"], month, new_items)

    await state.clear()

    await message.answer(
        f"✅ *План +30% создан!*\n\n"
        f"🏭 {campaign['producer']}\n"
        f"🏪 Аптек: {len(pharmacies)}\n\n"
        f"Все суммы и количества увеличены на 30%.\n"
        f"Запустить рассылку?",
        parse_mode="Markdown",
        reply_markup=confirm_send_kb(new_campaign_id)
    )


# ── Pharmacy answer ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ans:"))
async def handle_pharmacy_answer(callback: CallbackQuery):
    _, answer, campaign_id_str = callback.data.split(":")
    campaign_id = int(campaign_id_str)

    pharmacy = await get_pharmacy_by_tg(callback.from_user.id)
    if not pharmacy:
        await callback.answer("Вы не зарегистрированы.", show_alert=True)
        return

    await save_response(campaign_id, pharmacy["id"], answer)

    if answer == "yes":
        text = "✅ *Отлично!* Ваш ответ принят.\n\n📋 /myplan — посмотреть ваш план"
    else:
        text = "Понял, спасибо. Если передумаете — свяжитесь с менеджером DATFO."

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


# ── Statistics ────────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Нет активных кампаний.")
        return

    stats = await get_campaign_stats(campaign["id"])
    pct     = round(stats["answered"] / stats["total"] * 100) if stats["total"] else 0
    yes_pct = round(stats["yes"] / stats["answered"] * 100) if stats["answered"] else 0
    bar = "█" * round(pct / 10) + "░" * (10 - round(pct / 10))

    await message.answer(
        f"📊 *Статистика*\n"
        f"🏭 {campaign['producer']} · {campaign['period']}\n\n"
        f"`{bar}` {pct}% ответили\n\n"
        f"👥 Всего аптек: *{stats['total']}*\n"
        f"✅ Ответили: *{stats['answered']}*\n"
        f"⏳ Молчат: *{stats['pending']}*\n\n"
        f"✅ Согласились: *{stats['yes']}* ({yes_pct}%)\n"
        f"❌ Отказались: *{stats['no']}*",
        parse_mode="Markdown"
    )


# ── Yes list ──────────────────────────────────────────────────────────────────

@router.message(F.text == "📋 Согласились")
async def show_yes_list(message: Message, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Нет активных кампаний.")
        return

    yes_list = await get_yes_pharmacies(campaign["id"])
    if not yes_list:
        await message.answer("Пока никто не согласился.")
        return

    lines = [f"✅ *Согласились ({len(yes_list)} аптек):*\n"]
    for p in yes_list:
        lines.append(f"• `{p['inn']}` — {p['name']}")

    chunks, current, size = [], [], 0
    for line in lines:
        current.append(line)
        size += len(line)
        if size > 3500:
            chunks.append("\n".join(current))
            current, size = [], 0
    if current:
        chunks.append("\n".join(current))
    for chunk in chunks:
        await message.answer(chunk, parse_mode="Markdown")


# ── Reminders ─────────────────────────────────────────────────────────────────

@router.message(F.text == "🔔 Напомнить")
async def prompt_remind(message: Message, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Нет активных кампаний.")
        return

    pending = await get_unanswered_pharmacies(campaign["id"])
    if not pending:
        await message.answer("🎉 Все аптеки уже ответили!")
        return

    await message.answer(
        f"🔔 Не ответили: *{len(pending)}* аптек.\nОтправить напоминание?",
        parse_mode="Markdown",
        reply_markup=remind_confirm_kb(campaign["id"])
    )


@router.callback_query(F.data.startswith("remind:"))
async def send_reminders(callback: CallbackQuery, admin_ids: list):
    if not is_admin(callback.from_user.id, admin_ids):
        return

    campaign_id = int(callback.data.split(":")[1])
    campaign    = await get_campaign(campaign_id)
    pending     = await get_unanswered_pharmacies(campaign_id)

    sent = 0
    for pharmacy in pending:
        plan = await get_pharmacy_plan(campaign_id, pharmacy["id"])
        if not plan:
            continue

        items_jan = await get_plan_items_month(campaign_id, pharmacy["id"], "jan")
        items_feb = await get_plan_items_month(campaign_id, pharmacy["id"], "feb")
        items_mar = await get_plan_items_month(campaign_id, pharmacy["id"], "mar")

        ph_dict = {k: plan[k] for k in ("plan_total","plan_jan","plan_feb","plan_mar",
                                         "bonus_jan","bonus_feb","bonus_mar","bonus_total")}
        text = "🔔 *Напоминание от DATFO*\n\nВы ещё не ответили.\n\n" + format_pharmacy_plan_message(
            ph_dict,
            [{"sku": i["sku"], "qty": i["qty"]} for i in items_jan],
            [{"sku": i["sku"], "qty": i["qty"]} for i in items_feb],
            [{"sku": i["sku"], "qty": i["qty"]} for i in items_mar],
        )
        try:
            await callback.bot.send_message(
                chat_id=pharmacy["telegram_id"], text=text,
                parse_mode="Markdown", reply_markup=pharmacy_answer_kb(campaign_id)
            )
            await mark_reminded(campaign_id, pharmacy["id"])
            sent += 1
        except Exception:
            pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Напоминание отправлено *{sent}* аптекам.", parse_mode="Markdown")
    await callback.answer()


# ── List pharmacies ───────────────────────────────────────────────────────────

@router.message(F.text == "🏪 Список аптек")
async def list_pharmacies(message: Message, admin_ids: list):
    if not is_admin(message.from_user.id, admin_ids):
        return
    all_ph = await get_all_pharmacies()
    if not all_ph:
        await message.answer("Аптек пока нет.")
        return

    registered = sum(1 for p in all_ph if p["telegram_id"])
    lines = [f"🏪 *Аптеки ({len(all_ph)} всего, {registered} зарегистрированы)*\n"]
    for p in all_ph:
        status = "✅" if p["telegram_id"] else "⏳"
        lines.append(f"{status} `{p['inn']}` — {p['name']}")

    chunk, size = [], 0
    for line in lines:
        chunk.append(line)
        size += len(line)
        if size > 3000:
            await message.answer("\n".join(chunk), parse_mode="Markdown")
            chunk, size = [], 0
    if chunk:
        await message.answer("\n".join(chunk), parse_mode="Markdown")


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel")
async def cancel_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отменено")
