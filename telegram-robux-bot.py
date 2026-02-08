# telegram-robux-bot.py
# Версия: aiogram 3.x
# Работает через переменную окружения BOT_TOKEN

import os
import asyncio
import logging
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = 7227557185
PRICE_RATE = 2  # 1 рубль = 2 робукса
FEEDBACK_LINK = "https://t.me/rbxklev/2"
GROUP_LINK = "https://www.roblox.com/communities/737889565/angebnny#!/about"
# =============================================

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================== FSM ==================
class OrderForm(StatesGroup):
    roblox_nick = State()
    robux_amount = State()
    waiting_screenshot = State()
# =========================================


# ================== БАЗА =================
async def init_db():
    async with aiosqlite.connect("orders.db") as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                roblox_nick TEXT,
                amount INTEGER,
                price_rub REAL,
                status TEXT,
                created_at TEXT
            )
            """
        )
        await db.commit()
# =========================================


def generate_order_id():
    return "RBX" + datetime.now().strftime("%Y%m%d%H%M%S")


def calculate_price(amount: int) -> float:
    return amount / PRICE_RATE


# ================== START =================
@dp.message(Command("start"))
async def start(message: types.Message):
    if message.chat.type != types.ChatType.PRIVATE:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Да, больше 14 дней", callback_data="group_yes")
    builder.button(text="Проверку админом", callback_data="group_check")
    builder.adjust(1)

    await message.answer(
        f"Ты в группе {GROUP_LINK} уже 14 дней?",
        reply_markup=builder.as_markup()
    )


# ================= ПРОВЕРКА ГРУППЫ =================
@dp.callback_query(F.data == "group_yes")
async def group_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ваш ник в Roblox:")
    await state.set_state(OrderForm.roblox_nick)
    await callback.answer()


@dp.callback_query(F.data == "group_check")
async def group_check(callback: types.CallbackQuery):
    user = callback.from_user
    username = f"@{user.username}" if user.username else f"id {user.id}"

    await bot.send_message(
        ADMIN_ID,
        f"Нужна проверка участия в группе от {username}"
    )

    await callback.message.answer("Администратор проверит участие. Ожидайте.")
    await callback.answer()


# ================= ОФОРМЛЕНИЕ ЗАКАЗА =================
@dp.message(OrderForm.roblox_nick)
async def get_nick(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if not nick:
        await message.answer("Ник не может быть пустым.")
        return

    await state.update_data(roblox_nick=nick)
    await message.answer("Введите количество робуксов (минимум 800):")
    await state.set_state(OrderForm.robux_amount)


@dp.message(OrderForm.robux_amount)
async def get_amount(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return

    amount = int(message.text)
    if amount < 800:
        await message.answer("Минимум 800 робуксов.")
        return

    data = await state.get_data()
    nick = data["roblox_nick"]

    price = calculate_price(amount)
    order_id = generate_order_id()

    async with aiosqlite.connect("orders.db") as db:
        await db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                message.from_user.id,
                message.from_user.username or "",
                nick,
                amount,
                price,
                "waiting_payment",
                datetime.now().isoformat()
            )
        )
        await db.commit()

    await state.update_data(order_id=order_id, amount=amount, price=price)

    await message.answer(
        f"🧾 Заказ создан\n"
        f"ID: {order_id}\n"
        f"Робуксы: {amount}\n"
        f"К оплате: {price:.2f} руб.\n\n"
        f"Переведите сумму и отправьте скрин перевода."
    )

    await state.set_state(OrderForm.waiting_screenshot)


# ================= СКРИН ОПЛАТЫ =================
@dp.message(F.photo, OrderForm.waiting_screenshot)
async def get_screenshot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["order_id"]
    amount = data["amount"]
    price = data["price"]
    nick = data["roblox_nick"]

    user = message.from_user
    username = f"@{user.username}" if user.username else f"id {user.id}"

    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=f"confirm_{order_id}")
    builder.button(text="Отклонить", callback_data=f"reject_{order_id}")
    builder.adjust(1)

    await bot.send_photo(
        ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=(
            f"Новый заказ {order_id}\n"
            f"Пользователь: {username}\n"
            f"Ник Roblox: {nick}\n"
            f"Робуксы: {amount}\n"
            f"Сумма: {price:.2f} руб."
        ),
        reply_markup=builder.as_markup()
    )

    await message.answer("Скрин отправлен администратору. Ожидайте подтверждения.")
    await state.clear()


# ================= АДМИН ДЕЙСТВИЯ =================
@dp.callback_query(F.data.startswith("confirm_"))
async def confirm(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", ("confirmed", order_id))
        await db.commit()

    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                await bot.send_message(
                    row[0],
                    f"✅ Заказ {order_id} подтверждён.\n"
                    f"После получения робуксов оставьте отзыв: {FEEDBACK_LINK}"
                )

    await callback.answer("Подтверждено")


@dp.callback_query(F.data.startswith("reject_"))
async def reject(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]

    async with aiosqlite.connect("orders.db") as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", ("rejected", order_id))
        await db.commit()

    async with aiosqlite.connect("orders.db") as db:
        async with db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                await bot.send_message(row[0], f"❌ Заказ {order_id} отклонён.")

    await callback.answer("Отклонено")


# ================= ЗАПУСК =================
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
