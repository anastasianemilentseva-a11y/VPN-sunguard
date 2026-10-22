"""Telegram-бот: по кнопке выдаёт настройку WireGuard (файл и QR-код).

Первый раз человек получает VPN только после одобрения администратора.
Дальше он сам может взять настройки ещё на несколько устройств (до MAX_DEVICES).
Запуск на VPN-сервере от root: python bot/main.py
"""
import asyncio
import io
import logging

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

import db as dbm
import wg as wgm
from config import load_config

cfg = load_config()
db = dbm.Db(cfg.db_path)
wireguard = wgm.WireGuard(cfg.wg_bin, cfg.wg_interface, cfg.wg_config_path)
wg_lock = asyncio.Lock()
dp = Dispatcher()

GET_BUTTON = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔑 Получить VPN", callback_data="get")]]
)


def display_name(user: User) -> str:
    name = user.full_name
    if user.username:
        name += f" (@{user.username})"
    return name


def is_admin(user: User) -> bool:
    return user.id == cfg.admin_id


async def issue_config(bot: Bot, tg_id: int) -> str:
    """Создаёт клиента на сервере и отправляет человеку файл и QR-код. Возвращает адрес."""
    async with wg_lock:
        also_used = {p["ip"] for p in db.conn.execute("SELECT ip FROM peers")}
        peer = await asyncio.to_thread(wireguard.add_peer, tg_id, also_used)
        db.add_peer(tg_id, peer.public_key, peer.ip)
        server_key = await asyncio.to_thread(wireguard.server_public_key)
    text = wgm.client_config(
        peer, server_key, cfg.endpoint, cfg.client_dns, cfg.client_mtu, cfg.client_allowed_ips
    )
    number = len(db.peers_of(tg_id))
    png = io.BytesIO()
    qrcode.make(text).save(png, format="PNG")
    await bot.send_document(
        tg_id,
        BufferedInputFile(text.encode(), filename=f"sunguard{number}.conf"),
        caption=(
            f"Твой VPN, устройство {number} из {cfg.max_devices}.\n"
            "Компьютер: поставь программу WireGuard и открой в ней этот файл.\n"
            "Телефон: в WireGuard нажми «+» → «Сканировать QR-код»."
        ),
    )
    await bot.send_photo(tg_id, BufferedInputFile(png.getvalue(), filename="sunguard.png"))
    return peer.ip


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Привет! Это VPN Sunguard. Нажми кнопку, чтобы получить настройку.",
        reply_markup=GET_BUTTON,
    )


@dp.callback_query(F.data == "get")
async def get_vpn(call: CallbackQuery, bot: Bot) -> None:
    user = call.from_user
    row = db.user(user.id)
    status = row["status"] if row else None
    await call.answer()

    if status == dbm.APPROVED:
        if len(db.peers_of(user.id)) >= cfg.max_devices:
            await call.message.answer(
                f"У тебя уже {cfg.max_devices} настройки — это максимум. "
                "Если нужна замена, напиши администратору."
            )
            return
        try:
            await issue_config(bot, user.id)
        except Exception as e:
            logging.exception("Не удалось выдать настройку")
            await call.message.answer("Не получилось создать настройку. Администратор уже знает.")
            await bot.send_message(cfg.admin_id, f"Ошибка при выдаче VPN {display_name(user)}: {str(e)[:300]}")
        return
    if status == dbm.PENDING:
        await call.message.answer("Запрос уже у администратора. Как только он ответит, я напишу.")
        return
    if status == dbm.DENIED:
        await call.message.answer("Администратор отказал в доступе.")
        return

    db.set_user(user.id, display_name(user), dbm.PENDING)
    await call.message.answer("Отправил запрос администратору. Как только он ответит, я напишу.")
    await bot.send_message(
        cfg.admin_id,
        f"Запрос на VPN: {display_name(user)}, id {user.id}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Разрешить", callback_data=f"approve:{user.id}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"deny:{user.id}"),
        ]]),
    )


@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery, bot: Bot) -> None:
    if not is_admin(call.from_user):
        await call.answer("Это кнопка администратора.", show_alert=True)
        return
    tg_id = int(call.data.split(":", 1)[1])
    row = db.user(tg_id)
    if not row or row["status"] != dbm.PENDING:
        await call.answer("Этот запрос уже обработан.", show_alert=True)
        return
    await call.answer()
    db.set_status(tg_id, dbm.APPROVED)
    try:
        ip = await issue_config(bot, tg_id)
    except Exception as e:
        logging.exception("Не удалось выдать настройку")
        db.set_status(tg_id, dbm.PENDING)
        await call.message.answer(f"Не получилось создать настройку: {str(e)[:300]}")
        return
    await call.message.edit_text(f"✅ Разрешено: {row['name']}, адрес {ip}")


@dp.callback_query(F.data.startswith("deny:"))
async def deny(call: CallbackQuery, bot: Bot) -> None:
    if not is_admin(call.from_user):
        await call.answer("Это кнопка администратора.", show_alert=True)
        return
    tg_id = int(call.data.split(":", 1)[1])
    row = db.user(tg_id)
    if not row or row["status"] != dbm.PENDING:
        await call.answer("Этот запрос уже обработан.", show_alert=True)
        return
    await call.answer()
    db.set_status(tg_id, dbm.DENIED)
    await bot.send_message(tg_id, "Администратор отказал в доступе к VPN.")
    await call.message.edit_text(f"❌ Отказано: {row['name']}")


@dp.message(Command("users"))
async def users(message: Message) -> None:
    if not is_admin(message.from_user):
        return
    rows = db.approved_users()
    if not rows:
        await message.answer("Пока никому не выдан VPN.")
        return
    lines = [f"{r['name']} — устройств: {r['devices']}" for r in rows]
    buttons = [
        [InlineKeyboardButton(text=f"🚫 Отключить {r['name'][:40]}", callback_data=f"revoke:{r['tg_id']}")]
        for r in rows
    ]
    await message.answer(
        "Кому выдан VPN:\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("revoke:"))
async def revoke(call: CallbackQuery, bot: Bot) -> None:
    if not is_admin(call.from_user):
        await call.answer("Это кнопка администратора.", show_alert=True)
        return
    tg_id = int(call.data.split(":", 1)[1])
    row = db.user(tg_id)
    if not row or row["status"] != dbm.APPROVED:
        await call.answer("Этот человек уже отключён.", show_alert=True)
        return
    await call.answer()
    async with wg_lock:
        for peer in db.peers_of(tg_id):
            await asyncio.to_thread(wireguard.remove_peer, peer["public_key"])
            db.remove_peer(peer["public_key"])
    db.set_status(tg_id, dbm.REVOKED)
    await bot.send_message(tg_id, "Твой VPN отключён администратором.")
    await call.message.answer(f"🚫 Отключён: {row['name']}")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(cfg.bot_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
