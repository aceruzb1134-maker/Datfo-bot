from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)


def pharmacy_answer_kb(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, берём план",  callback_data=f"ans:yes:{campaign_id}"),
        InlineKeyboardButton(text="❌ Нет, не сможем", callback_data=f"ans:no:{campaign_id}"),
    ]])


def confirm_send_kb(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Отправить всем", callback_data=f"send:{campaign_id}"),
        InlineKeyboardButton(text="❌ Отмена",         callback_data="cancel"),
    ]])


def confirm_repeat_kb(campaign_id: int) -> InlineKeyboardMarkup:
    """Confirm repeat campaign with +30%"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, создать план +30%", callback_data=f"repeat:{campaign_id}"),
            InlineKeyboardButton(text="❌ Отмена",                callback_data="cancel"),
        ]
    ])


def remind_confirm_kb(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔔 Да, напомнить", callback_data=f"remind:{campaign_id}"),
        InlineKeyboardButton(text="Отмена",           callback_data="cancel"),
    ]])


def admin_main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Загрузить план (Excel)")],
            [KeyboardButton(text="🔄 Повторить +30%")],
            [KeyboardButton(text="📊 Статистика"),             KeyboardButton(text="📋 Согласились")],
            [KeyboardButton(text="🔔 Напомнить"),              KeyboardButton(text="➕ Добавить аптеку")],
            [KeyboardButton(text="📥 Загрузить аптеки (Excel)"), KeyboardButton(text="🏪 Список аптек")],
        ],
        resize_keyboard=True,
    )
