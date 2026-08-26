#!/usr/bin/env python3
"""
Aj Signals Telegram bot
- Welcome + offer
- Pay with Telegram Stars (automatic access)
- Pay with USDC (screenshot -> admin /approve)
- Remembers paid users in paid_users.json
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
PRIVATE_CHANNEL_LINK = os.getenv("PRIVATE_CHANNEL_LINK", "").strip()
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "").strip()
USDT_NETWORK = os.getenv("USDT_NETWORK", "TRC20").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "Rexx Signals").strip()
PRICE_USD = os.getenv("PRICE_USD", "15").strip()
PRICE_STARS = int(os.getenv("PRICE_STARS", "750") or 750)

DATA_FILE = Path(__file__).with_name("paid_users.json")
PAYLOAD = "lifetime_signals_v1"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("signals_bot")


def load_paid() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"users": {}}
    return {"users": {}}


def save_paid(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_paid(user_id: int) -> bool:
    return str(user_id) in load_paid().get("users", {})


def mark_paid(user_id: int, username: str | None, method: str, extra: str = "") -> None:
    data = load_paid()
    data.setdefault("users", {})
    data["users"][str(user_id)] = {
        "username": username or "",
        "method": method,
        "extra": extra,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
    save_paid(data)


def welcome_text() -> str:
    return (
        f"🔥 *Welcome to {BRAND_NAME}*\n\n"
        "Get daily high-quality trading signals in my private channel.\n\n"
        "✅ Daily signals\n"
        "✅ Clear entry, stop loss & take profit\n"
        "✅ Private community access\n\n"
        f"💰 *Price: ${PRICE_USD}* (Lifetime access)\n\n"
        "👇 Choose how you want to pay:"
    )


def access_text() -> str:
    if PRIVATE_CHANNEL_LINK:
        return (
            "🎉 *Payment confirmed!*\n\n"
            "Welcome to the private signals channel:\n\n"
            f"{PRIVATE_CHANNEL_LINK}\n\n"
            "See you inside 🔥"
        )
    return (
        "🎉 *Payment confirmed!*\n\n"
        "Access is approved. The admin will send the private channel link shortly."
    )


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"⭐ Pay with Telegram Stars", callback_data="pay_stars")],
            [InlineKeyboardButton("💰 Pay with USDC (Crypto)", callback_data="pay_usdt")],
            [InlineKeyboardButton("📩 I already paid", callback_data="already_paid")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and is_paid(user.id):
        await update.message.reply_text(
            "You already have access ✅\n\n" + access_text(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        welcome_text(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/start — open the offer\n"
        "/help — this message\n\n"
        "After USDC payment, send a screenshot here."
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id if query.message else user.id
    data = query.data or ""

    # Answer instantly so the button stops showing "Loading..."
    try:
        if data == "pay_stars":
            await query.answer("Opening Stars payment…")
        elif data == "pay_usdt":
            await query.answer("Opening USDC payment…")
        elif data == "already_paid":
            await query.answer("Checking…")
        else:
            await query.answer()
    except TelegramError:
        pass

    if is_paid(user.id):
        await context.bot.send_message(chat_id, access_text(), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "pay_stars":
        try:
            await context.bot.send_invoice(
                chat_id=chat_id,
                title=f"{BRAND_NAME} — Lifetime Access",
                description="Lifetime access to the private daily trading signals channel.",
                payload=PAYLOAD,
                currency="XTR",
                prices=[LabeledPrice(label="Lifetime Access", amount=PRICE_STARS)],
            )
        except TelegramError as exc:
            logger.exception("Failed to send Stars invoice")
            await context.bot.send_message(
                chat_id,
                "Could not open Stars payment right now.\n"
                f"Error: {exc}\n\n"
                "Use USDC instead, or try again later.",
            )

    elif data == "pay_usdt":
        if not USDT_ADDRESS:
            await context.bot.send_message(
                chat_id,
                "USDC wallet is not set yet. Please use Telegram Stars for now.",
            )
            return
        text = (
            f"💰 *Pay with USDC ({USDT_NETWORK})*\n\n"
            f"Send *exactly ${PRICE_USD} USDC* to:\n\n"
            f"`{USDT_ADDRESS}`\n\n"
            f"Network: *{USDT_NETWORK}*\n\n"
            "After payment, send a *screenshot* of the transaction in this chat.\n"
            "Admin will verify and unlock access."
        )
        # New message is faster/more reliable than editing the old one
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)

    elif data == "already_paid":
        if is_paid(user.id):
            await context.bot.send_message(chat_id, access_text(), parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(
                chat_id,
                "I don’t see a confirmed payment for your account yet.\n\n"
                "If you paid with USDC, send the screenshot here.\n"
                "If you paid with Stars, use /start and try again only if needed.",
            )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    ok = query.invoice_payload == PAYLOAD and query.currency == "XTR"
    await query.answer(ok=ok, error_message=None if ok else "Invalid invoice.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    user = update.effective_user
    mark_paid(
        user.id,
        user.username,
        "stars",
        extra=payment.telegram_payment_charge_id,
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "✅ Stars payment received\n\n"
                    f"Name: {user.full_name}\n"
                    f"Username: @{user.username or '—'}\n"
                    f"User ID: `{user.id}`\n"
                    f"Stars: {payment.total_amount}\n"
                    f"Charge: `{payment.telegram_payment_charge_id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            logger.exception("Could not notify admin")

    await update.message.reply_text(access_text(), parse_mode=ParseMode.MARKDOWN)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_paid(user.id):
        await update.message.reply_text("You already have access ✅")
        return

    if ADMIN_ID:
        try:
            await context.bot.forward_message(
                chat_id=ADMIN_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📷 Possible USDC payment\n\n"
                    f"Name: {user.full_name}\n"
                    f"Username: @{user.username or '—'}\n"
                    f"User ID: `{user.id}`\n\n"
                    f"Approve with:\n`/approve {user.id}`\n"
                    f"Reject with:\n`/reject {user.id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            logger.exception("Could not forward screenshot to admin")

    await update.message.reply_text(
        "✅ Screenshot received.\nI will verify and send the channel link shortly."
    )


async def handle_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text and update.message.text.startswith("/"):
        return
    await update.message.reply_text(
        "Tap /start to see the offer, or send a payment screenshot if you paid with USDC."
    )


def admin_only(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("USER_ID must be a number.")
        return

    mark_paid(user_id, None, "usdt")
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=access_text(),
            parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_text(f"✅ Access sent to {user_id}")
    except TelegramError as exc:
        await update.message.reply_text(
            f"Marked as paid, but could not message the user: {exc}"
        )


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /reject USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("USER_ID must be a number.")
        return
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ Payment could not be verified.\n\n"
                "Please check the amount, network, and wallet address, "
                "then send a clearer screenshot."
            ),
        )
        await update.message.reply_text(f"Reject message sent to {user_id}")
    except TelegramError as exc:
        await update.message.reply_text(f"Could not message user: {exc}")


async def paid_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_only(update):
        return
    users = load_paid().get("users", {})
    if not users:
        await update.message.reply_text("No paid users yet.")
        return
    lines = [f"{uid} | @{info.get('username') or '—'} | {info.get('method')}" for uid, info in users.items()]
    text = "Paid users:\n" + "\n".join(lines[-50:])
    await update.message.reply_text(text)


def validate_config() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing.")
    if not ADMIN_ID:
        logger.warning("ADMIN_ID is not set. USDT screenshot alerts will not be delivered.")
    if not PRIVATE_CHANNEL_LINK:
        logger.warning("PRIVATE_CHANNEL_LINK is not set.")
    if not USDT_ADDRESS:
        logger.warning("USDT_ADDRESS is not set.")


def main() -> None:
    validate_config()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("paid", paid_list))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_fallback))
    logger.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
