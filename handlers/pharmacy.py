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
    waiting_for_inn   = State()
    waiting_for_phone = State()


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

    await state.update_data(inn=inn)
    await state.set_state(RegState.waiting_for_phone)
    await message.answer(
        f"✅ ИНН найден: *{pharmacy['name']}*\n\n"
        f"Теперь введите *номер телефона* аптеки:\n"
        f"Пример: `+998901234567`",
        parse_mode="Markdown"
    )


@router.message(RegState.waiting_for_phone)
async def handle_phone(message: Message, state: FSMContext):
    phone = message.text.strip()

    # Basic validation
    if len(phone.replace("+", "").replace(" ", "")) < 9:
        await message.answer("❌ Неверный формат номера. Попробуйте снова.\nПример: `+998901234567`", parse_mode="Markdown")
        return

    data = await state.get_data()
    inn = data["inn"]

    await link_pharmacy_telegram(inn, message.from_user.id, phone)
    await state.clear()

    pharmacy = await get_pharmacy_by_inn(inn)
    await message.answer(
        f"✅ *Регистрация прошла успешно!*\n\n"
        f"🏪 {pharmacy['name']}\n"
        f"🔑 ИНН: `{inn}`\n"
        f"📞 Телефон: {phone}\n\n"
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
        await message.answer("📭 В текущей программе для вашей аптек
