from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from utils.db import (
    get_pharmacy_by_inn, get_pharmacy_by_tg,
    link_pharmacy_telegram, get_active_campaign,
    get_pharmacy_plan, get_plan_items_month,
)
from utils.excel import format_my_plan_message

router = Router()


class RegState(StatesGroup):
    waiting_for_inn = State()


@router.message(Command("start"))
async def pharmacy_start(message: Message, state: FSMContext, admin_ids: list):
    if message.from_user.id in admin_ids:
        return

    pharmacy = await get_pharmacy_by_tg(message.from_user.id)
    if pharmacy:
        await message.answer(
            f"👋 Добро пожаловать!\n\n"
            f"🏪 *{pharmacy['name']}*\n"
            f"🔑 ИНН: `{pharmacy['inn']}`\n\n"
            f"📋 /myplan — посмотреть текущий план\n"
            f"ℹ️ /info — информация о программе",
            parse_mode="Markdown"
        )
        return

    await state.set_state(RegState.waiting_for_inn)
    await message.answer(
        "👋 Добро пожаловать в систему DATFO!\n\n"
        "Для регистрации введите *ИНН вашей аптеки*.\n\n"
        "Пример: `302341262`",
        parse_mode="Markdown"
    )


@router.message(RegState.waiting_for_inn)
async def handle_inn(message: Message, state: FSMContext):
    inn = message.text.strip()

    # Validate — only digits
    if not inn.isdigit():
        await message.answer("❌ ИНН должен состоять только из цифр. Попробуйте снова.")
        return

    pharmacy = await get_pharmacy_by_inn(inn)
    if not pharmacy:
        await message.answer(
            "❌ ИНН не найден в системе.\n\n"
            "Проверьте правильность ИНН или обратитесь к менеджеру DATFO."
        )
        return

    if pharmacy["telegram_id"]:
        await message.answer(
            "⚠️ Этот ИНН уже зарегистрирован.\n"
            "Если это ошибка — обратитесь к менеджеру DATFO."
        )
        return

    await link_pharmacy_telegram(inn, message.from_user.id)
    await state.clear()

    await message.answer(
        f"✅ *Регистрация прошла успешно!*\n\n"
        f"🏪 {pharmacy['name']}\n"
        f"🔑 ИНН: `{inn}`\n\n"
        f"Теперь вы будете получать планы продаж от DATFO.\n\n"
        f"📋 /myplan — посмотреть текущий план",
        parse_mode="Markdown"
    )


@router.message(Command("myplan"))
async def show_my_plan(message: Message, admin_ids: list):
    if message.from_user.id in admin_ids:
        return

    pharmacy = await get_pharmacy_by_tg(message.from_user.id)
    if not pharmacy:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start.")
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Активных программ сейчас нет.")
        return

    plan = await get_pharmacy_plan(campaign["id"], pharmacy["id"])
    if not plan:
        await message.answer("📭 В текущей программе для вашей аптеки план не назначен.")
        return

    items_jan = await get_plan_items_month(campaign["id"], pharmacy["id"], "jan")
    items_feb = await get_plan_items_month(campaign["id"], pharmacy["id"], "feb")
    items_mar = await get_plan_items_month(campaign["id"], pharmacy["id"], "mar")

    ph_dict = {k: plan[k] for k in ("plan_total","plan_jan","plan_feb","plan_mar",
                                     "bonus_jan","bonus_feb","bonus_mar","bonus_total")}
    text = format_my_plan_message(
        ph_dict,
        [{"sku": i["sku"], "qty": i["qty"]} for i in items_jan],
        [{"sku": i["sku"], "qty": i["qty"]} for i in items_feb],
        [{"sku": i["sku"], "qty": i["qty"]} for i in items_mar],
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("info"))
async def show_info(message: Message, admin_ids: list):
    if message.from_user.id in admin_ids:
        return

    pharmacy = await get_pharmacy_by_tg(message.from_user.id)
    if not pharmacy:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start.")
        return

    campaign = await get_active_campaign()
    if not campaign:
        await message.answer("📭 Активных программ сейчас нет.")
        return

    await message.answer(
        f"ℹ️ *Текущая программа*\n\n"
        f"🏭 {campaign['producer']}\n"
        f"📅 {campaign['period']}\n\n"
        f"📋 /myplan — посмотреть ваш план",
        parse_mode="Markdown"
    )
