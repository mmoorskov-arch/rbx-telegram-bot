import logging
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, Text
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# Bot token and admin ID (provided by user)
TOKEN = "7618433242:AAFONW18pKNiuKmzOQMaZZkKIdzgQ4GETd4"
ADMIN_ID = 7227557185

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define FSM states for order process
class OrderStates(StatesGroup):
    waiting_nick = State()
    waiting_amount = State()
    waiting_photo = State()

# Initialize bot and dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

async def init_db():
    """Initialize the SQLite database and create orders table if not exists."""
    async with aiosqlite.connect('orders.db') as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                roblox_nick TEXT,
                amount INTEGER,
                price_rub REAL,
                status TEXT,
                created_at TEXT
            )"""
        )
        await db.commit()

# Start command handler: ask about group membership
@dp.message(Command("start"))
async def start_command(message: types.Message):
    # Work only in private chat
    if message.chat.type != types.ChatType.PRIVATE:
        return
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="Да, больше 14 дней", callback_data="group_yes")
    keyboard.button(text="Проверку админом", callback_data="group_check")
    keyboard.adjust(1, 1)
    await message.answer(
        "Ты в группе https://www.roblox.com/communities/737889565/angebnny#!/about уже 14 дней?",
        reply_markup=keyboard.as_markup()
    )

# Callback handler: user confirms membership
@dp.callback_query(Text("group_yes"))
async def group_yes(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Отлично! Введите ник в Roblox:")
    await state.set_state(OrderStates.waiting_nick)
    await callback.answer()

# Callback handler: user requests admin check
@dp.callback_query(Text("group_check"))
async def group_check(callback: CallbackQuery):
    user = callback.from_user
    identifier = f"@{user.username}" if user.username else f"id {user.id}"
    try:
        await bot.send_message(ADMIN_ID, f"Нужна проверка участия в группе от {identifier}")
        await callback.message.answer("Администратор проверит ваше участие, пожалуйста, подождите.")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
        await callback.message.answer("Не удалось отправить запрос администратору.")
    await callback.answer()

# Handler: receive Roblox nickname
@dp.message(OrderStates.waiting_nick)
async def process_nick(message: types.Message, state: FSMContext):
    if message.chat.type != types.ChatType.PRIVATE:
        return
    nick = message.text.strip()
    if not nick:
        await message.answer("Ник не может быть пустым. Попробуйте еще раз.")
        return
    await state.update_data(roblox_nick=nick)
    await message.answer("Введите количество робуксов (минимум 800):")
    await state.set_state(OrderStates.waiting_amount)

# Handler: receive Robux amount
@dp.message(OrderStates.waiting_amount)
async def process_amount(message: types.Message, state: FSMContext):
    if message.chat.type != types.ChatType.PRIVATE:
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Пожалуйста, введите число.")
        return
    amount = int(text)
    if amount < 800:
        await message.answer("Минимальное количество робуксов - 800. Попробуйте еще раз.")
        return
    price = amount / 2  # 1 руб = 2 робукса
    data = await state.get_data()
    roblox_nick = data.get("roblox_nick")
    # Generate unique order ID
    order_id = f"RBX{datetime.now().strftime('%Y%m%d%H%M%S')}"
    # Store order in database (status = pending)
    async with aiosqlite.connect('orders.db') as db:
        await db.execute(
            "INSERT INTO orders (id, user_id, username, roblox_nick, amount, price_rub, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                message.from_user.id,
                message.from_user.username or "",
                roblox_nick,
                amount,
                price,
                'pending',
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        )
        await db.commit()
    # Send order details and payment instructions to user
    await message.answer(
        f"ID заказа: {order_id}\n"
        f"Переведите {price:.2f} рублей на карту. Скиньте скрин перевода."
    )
    await message.answer("Теперь отправьте скриншот перевода.")
    await state.update_data(order_id=order_id, amount=amount, price=price)
    await state.set_state(OrderStates.waiting_photo)

# Handler: receive payment screenshot (photo)
@dp.message(lambda message: message.photo, OrderStates.waiting_photo)
async def process_photo(message: types.Message, state: FSMContext):
    if message.chat.type != types.ChatType.PRIVATE:
        return
    data = await state.get_data()
    order_id = data.get("order_id")
    amount = data.get("amount")
    price = data.get("price")
    roblox_nick = data.get("roblox_nick")

    # Send photo to admin with inline buttons for Confirm/Reject
    user = message.from_user
    username = f"@{user.username}" if user.username else f"id {user.id}"
    caption = (
        f"Новый заказ {order_id}\n"
        f"Пользователь: {username}\n"
        f"Roblox ник: {roblox_nick}\n"
        f"Количество робуксов: {amount}\n"
        f"Сумма: {price:.2f} руб."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=f"confirm_{order_id}")
    builder.button(text="Отклонить", callback_data=f"reject_{order_id}")
    builder.adjust(1, 1)
    try:
        await bot.send_photo(chat_id=ADMIN_ID, photo=message.photo[-1].file_id,
                             caption=caption, reply_markup=builder.as_markup())
        await message.answer("Скриншот отправлен администратору. Ожидайте подтверждения.")
    except Exception as e:
        logger.error(f"Failed to send order to admin: {e}")
        await message.answer("Не удалось отправить заказ администратору.")
    await state.clear()

# Callback handler: admin confirms order
@dp.callback_query(Text(startswith="confirm_"))
async def confirm_order(callback: CallbackQuery):
    order_id = callback.data.split("_", 1)[1]
    async with aiosqlite.connect('orders.db') as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", ('confirmed', order_id))
        await db.commit()
    try:
        await callback.message.edit_caption(f"{callback.message.caption}\n\n✅ Заказ подтверждён")
    except Exception as e:
        logger.error(f"Failed to edit admin message on confirm: {e}")
    await bot.send_message(ADMIN_ID, f"Заказ {order_id} подтверждён.")
    await callback.answer("Заказ подтверждён")
    # Notify user with feedback link
    async with aiosqlite.connect('orders.db') as db:
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                user_id = row[0]
                try:
                    await bot.send_message(user_id, 
                                          "Ваш заказ подтверждён! Спасибо за покупку. Пожалуйста, оставьте отзыв: https://t.me/rbxklev/2")
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")

# Callback handler: admin rejects order
@dp.callback_query(Text(startswith="reject_"))
async def reject_order(callback: CallbackQuery):
    order_id = callback.data.split("_", 1)[1]
    async with aiosqlite.connect('orders.db') as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", ('rejected', order_id))
        await db.commit()
    try:
        await callback.message.edit_caption(f"{callback.message.caption}\n\n❌ Заказ отклонён")
    except Exception as e:
        logger.error(f"Failed to edit admin message on reject: {e}")
    await bot.send_message(ADMIN_ID, f"Заказ {order_id} отклонён.")
    await callback.answer("Заказ отклонён")
    # Notify user about rejection
    async with aiosqlite.connect('orders.db') as db:
        async with db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                user_id = row[0]
                try:
                    await bot.send_message(user_id, "Ваш заказ был отклонён администратором.")
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
