#!/usr/bin/env python3
"""
Rexx Signals Telegram bot
Packages:
  - vip1  ($15 / 750 Stars): VIP Group 1 only
  - full  ($25 / 1250 Stars): VIP Group 1 + VIP Group 2 + 1-on-1 mentorship
  - vip2  ($15 / 750 Stars): VIP Group 2 only (upgrade if user already has vip1)
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
LINK_VIP1 = os.getenv("PRIVATE_CHANNEL_LINK", "").strip()
LINK_VIP2 = os.getenv("PRIVATE_CHANNEL_LINK_2", "").strip()
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "").strip()
USDT_NETWORK = os.getenv("USDT_NETWORK", "ERC20 (Ethereum)").strip()
BRAND_NAME = os.getenv("BRAND_NAME", "Rexx Signals").strip()

# Prices
PRICE_VIP1_USD = 15
PRICE_FULL_USD = 25
PRICE_VIP2_USD = 15  # upgrade only
STARS_VIP1 = int(os.getenv("PRICE_STARS_VIP1", "750") or 750)
STARS_FULL = int(os.getenv("PRICE_STARS_FULL", "1250") or 1250)
STARS_VIP2 = int(os.getenv("PRICE_STARS_VIP2", "750") or 750)

DATA_FILE = Path(__file__).with_name("paid_users.json")

PACKAGES = {
    "vip1": {
        "title": "VIP Group 1",
        "usd": PRICE_VIP1_USD,
        "stars": STARS_VIP1,
        "payload": "pkg_vip1",
        "desc": "Daily signals · Private VIP Group 1 · Lifetime",
    },
    "full": {
        "title": "Full Access (VIP 1 + VIP 2 + Mentorship)",
        "usd": PRICE_FULL_USD,
        "stars": STARS_FULL,
        "payload": "pkg_full",
        "desc": "VIP Group 1 + VIP Group 2 + 1-on-1 mentorship · Lifetime",
    },
    "vip2": {
        "title": "VIP Group 2 (Upgrade)",
        "usd": PRICE_VIP2_USD,
        "stars": STARS_VIP2,
        "payload": "pkg_vip2",
        "desc": "VIP Group 2 only (for members who already have VIP 1)",
    },
}

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


def user_record(user_id: int) -> dict:
    return load_paid().get("users", {}).get(str(user_id), {})


def user_packages(user_id: int) -> set[str]:
    rec = user_record(user_id)
    pkgs = set(rec.get("packages") or [])
    # legacy single-purchase users
    if not pkgs and rec:
        pkgs.add("vip1")
    return pkgs


def has_package(user_id: int, pkg: str) -> bool:
    pkgs = user_packages(user_id)
    if pkg == "vip1":
        return "vip1" in pkgs or "full" in pkgs
    if pkg == "vip2":
        return "vip2" in pkgs or "full" in pkgs
    if pkg == "full":
        return "full" in pkgs or ("vip1" in pkgs and "vip2" in pkgs)
    return pkg in pkgs


def mark_paid(
    user_id: int,
    username: str | None,
    method: str,
    package: str,
    extra: str = "",
) -> None:
    data = load_paid()
    data.setdefault("users", {})
    rec = data["users"].get(str(user_id), {})
    pkgs = set(rec.get("packages") or [])
    if package == "full":
        pkgs.update({"vip1", "vip2", "full"})
    else:
        pkgs.add(package)
        if "vip1" in pkgs and "vip2" in pkgs:
            pkgs.add("full")
    data["users"][str(user_id)] = {
        "username": username or rec.get("username") or "",
        "method": method,
        "package": package,
        "packages": sorted(pkgs),
        "extra": extra,
        "paid_at": datetime.now(timezone.utc).isoformat(),
    }
    save_paid(data)


def access_text_for(user_id: int) -> str:
    pkgs = user_packages(user_id)
    lines = ["🎉 *Payment confirmed!*", ""]
    if "full" in pkgs or ("vip1" in pkgs and "vip2" in pkgs):
        lines.append("*Full Access unlocked*")
        lines.append("")
        if LINK_VIP1:
            lines.append(f"VIP Group 1:\n{LINK_VIP1}")
            lines.append("")
        if LINK_VIP2:
            lines.append(f"VIP Group 2:\n{LINK_VIP2}")
            lines.append("")
        lines.append("1-on-1 mentorship: admin will contact you shortly.")
    elif "vip1" in pkgs:
        lines.append("*VIP Group 1 unlocked*")
        lines.append("")
        if LINK_VIP1:
            lines.append(LINK_VIP1)
        lines.append("")
        lines.append("Want VIP 2 + mentorship later? Pay the $15 upgrade.")
    elif "vip2" in pkgs:
        lines.append("*VIP Group 2 unlocked*")
        lines.append("")
        if LINK_VIP2:
            lines.append(LINK_VIP2)
    else:
        lines.append("Access is approved. Admin will send links shortly.")
    lines.append("")
    lines.append("See you inside 🔥")
    return "\n".join(lines)


def welcome_text() -> str:
    # Promo: 75% off for 2 months. Current prices are discounted.
    # Normal VIP1 $60 → $15 | Full $100 → $25 | Upgrade $60 → $15
    return (
        f"🔥 <b>Welcome to {BRAND_NAME}</b>\n\n"
        "⏱ <b>75% OFF — 2 months only</b>\n"
        "One-time payment · lifetime access\n\n"
        f"📦 <b>VIP Group 1</b>\n"
        f"<s>$60</s> → <b>${PRICE_VIP1_USD}</b>  (save $45)\n"
        "• Daily high-quality signals\n"
        "• Clear entry, SL & TP\n"
        "• Private VIP Group 1\n\n"
        f"🚀 <b>Full Access</b>\n"
        f"<s>$100</s> → <b>${PRICE_FULL_USD}</b>  (save $75)\n"
        "• Everything in VIP Group 1\n"
        "• VIP Group 2\n"
        "• 1-on-1 mentorship\n\n"
        f"⬆️ <b>Already have VIP 1?</b>\n"
        f"Upgrade VIP 2: <s>$60</s> → <b>${PRICE_VIP2_USD}</b>\n\n"
        "👇 Select a package:"
    )


def package_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"📦 VIP 1 — $60 → ${PRICE_VIP1_USD}", callback_data="pkg_vip1")],
            [InlineKeyboardButton(f"🚀 Full — $100 → ${PRICE_FULL_USD}", callback_data="pkg_full")],
            [InlineKeyboardButton(f"⬆️ VIP 2 upgrade — $60 → ${PRICE_VIP2_USD}", callback_data="pkg_vip2")],
            [InlineKeyboardButton("📩 I already paid", callback_data="already_paid")],
        ]
    )


def pay_method_keyboard(pkg: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⭐ Pay with Telegram Stars", callback_data=f"stars_{pkg}")],
            [InlineKeyboardButton("💰 Pay with USDC (Crypto)", callback_data=f"usdc_{pkg}")],
            [InlineKeyboardButton("« Back", callback_data="back_packages")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user and has_package(user.id, "full"):
        await update.message.reply_text(
            "You already have *Full Access* ✅\n\n" + access_text_for(user.id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        welcome_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=package_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commands:\n"
        "/start — packages & payment\n"
        "/help — this message\n\n"
        "After USDC payment, send a screenshot here."
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id if query.message else user.id
    data = query.data or ""

    try:
        await query.answer()
    except TelegramError:
        pass

    # Admin approve / reject buttons
    if data.startswith("approve_") or data.startswith("reject_"):
        if user.id != ADMIN_ID:
            await query.answer("Admin only", show_alert=True)
            return
        try:
            target_id = int(data.split("_", 1)[1])
        except ValueError:
            await query.answer("Invalid user id", show_alert=True)
            return

        if data.startswith("approve_"):
            # Default approve as vip1 unless pending package stored
            pending = context.application.bot_data.get("pending_pkg", {}).get(str(target_id), "vip1")
            mark_paid(target_id, None, "usdc", pending)
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=access_text_for(target_id),
                    parse_mode=ParseMode.MARKDOWN,
                )
                await query.edit_message_text(
                    (query.message.text or "") + f"\n\n✅ Approved ({pending}) — access sent to {target_id}"
                )
            except TelegramError as exc:
                await context.bot.send_message(chat_id, f"Marked paid but could not message user: {exc}")
            return

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "❌ Payment could not be verified.\n\n"
                    "Please check the amount, network, and wallet address, "
                    "then send a clearer screenshot."
                ),
            )
            await query.edit_message_text(
                (query.message.text or "") + f"\n\n❌ Rejected — user {target_id} notified"
            )
        except TelegramError as exc:
            await context.bot.send_message(chat_id, f"Could not message user: {exc}")
        return

    if data == "back_packages":
        await query.edit_message_text(
            welcome_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=package_keyboard(),
        )
        return

    if data in ("pkg_vip1", "pkg_full", "pkg_vip2"):
        pkg = data.replace("pkg_", "")
        if pkg == "vip2" and not has_package(user.id, "vip1"):
            await context.bot.send_message(
                chat_id,
                "VIP 2 upgrade is only for members who already have VIP Group 1.\n"
                "Buy VIP 1 first, or choose Full Access.",
            )
            return
        if pkg == "vip1" and has_package(user.id, "vip1"):
            await context.bot.send_message(chat_id, "You already have VIP Group 1 ✅")
            return
        if pkg == "full" and has_package(user.id, "full"):
            await context.bot.send_message(chat_id, "You already have Full Access ✅")
            return
        if pkg == "vip2" and has_package(user.id, "vip2"):
            await context.bot.send_message(chat_id, "You already have VIP Group 2 ✅")
            return

        info = PACKAGES[pkg]
        normal = {15: 60, 25: 100}.get(info["usd"], info["usd"] * 4)
        text = (
            f"<b>{info['title']}</b>\n"
            f"{info['desc']}\n\n"
            f"⏱ <b>75% OFF · 2 months only</b>\n"
            f"Was <s>${normal}</s> → Now <b>${info['usd']}</b> (one-time · lifetime)\n\n"
            "Choose payment method:"
        )
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=pay_method_keyboard(pkg),
        )
        return

    if data.startswith("stars_"):
        pkg = data.replace("stars_", "")
        info = PACKAGES.get(pkg)
        if not info:
            return
        try:
            await context.bot.send_invoice(
                chat_id=chat_id,
                title=f"{BRAND_NAME} — {info['title']}",
                description=info["desc"],
                payload=info["payload"],
                currency="XTR",
                prices=[LabeledPrice(label=info["title"], amount=info["stars"])],
            )
        except TelegramError as exc:
            logger.exception("Stars invoice failed")
            await context.bot.send_message(
                chat_id,
                f"Could not open Stars payment.\nError: {exc}\n\nUse USDC instead.",
            )
        return

    if data.startswith("usdc_"):
        pkg = data.replace("usdc_", "")
        info = PACKAGES.get(pkg)
        if not info:
            return
        if not USDT_ADDRESS:
            await context.bot.send_message(chat_id, "USDC wallet not set. Use Stars for now.")
            return
        # remember what this user is trying to buy
        context.application.bot_data.setdefault("pending_pkg", {})[str(user.id)] = pkg
        text = (
            f"💰 *Pay with USDC ({USDT_NETWORK})*\n\n"
            f"Package: *{info['title']}*\n"
            f"Send *exactly ${info['usd']} USDC* to:\n\n"
            f"`{USDT_ADDRESS}`\n\n"
            f"Network: *{USDT_NETWORK}*\n\n"
            "After payment, send a *screenshot* of the transaction in this chat.\n"
            "Admin will verify and unlock access."
        )
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "already_paid":
        if has_package(user.id, "vip1") or has_package(user.id, "vip2"):
            await context.bot.send_message(
                chat_id, access_text_for(user.id), parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id,
                "I don’t see a confirmed payment yet.\n\n"
                "If you paid with USDC, send the screenshot here.",
            )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    ok = query.currency == "XTR" and query.invoice_payload in {
        p["payload"] for p in PACKAGES.values()
    }
    await query.answer(ok=ok, error_message=None if ok else "Invalid invoice.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    payment = update.message.successful_payment
    user = update.effective_user
    payload = payment.invoice_payload
    pkg = "vip1"
    for key, info in PACKAGES.items():
        if info["payload"] == payload:
            pkg = key
            break
    mark_paid(user.id, user.username, "stars", pkg, payment.telegram_payment_charge_id)

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "✅ Stars payment received\n\n"
                    f"Name: {user.full_name}\n"
                    f"Username: @{user.username or '—'}\n"
                    f"User ID: `{user.id}`\n"
                    f"Package: {pkg}\n"
                    f"Stars: {payment.total_amount}\n"
                    f"Charge: `{payment.telegram_payment_charge_id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError:
            logger.exception("Could not notify admin")

    await update.message.reply_text(access_text_for(user.id), parse_mode=ParseMode.MARKDOWN)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    pending = context.application.bot_data.get("pending_pkg", {}).get(str(user.id), "vip1")

    if ADMIN_ID:
        try:
            await context.bot.forward_message(
                chat_id=ADMIN_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
            )
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"✅ Approve ({pending})",
                            callback_data=f"approve_{user.id}",
                        ),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}"),
                    ]
                ]
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📷 Possible USDC payment\n\n"
                    f"Name: {user.full_name}\n"
                    f"Username: @{user.username or '—'}\n"
                    f"User ID: `{user.id}`\n"
                    f"Claimed package: *{pending}*\n\n"
                    "Tap a button, or:\n"
                    f"`/approve {user.id} {pending}`\n"
                    f"`/reject {user.id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
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
        "Tap /start to see packages, or send a payment screenshot if you paid with USDC."
    )


def admin_only(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == ADMIN_ID)


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /approve USER_ID [vip1|full|vip2]")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("USER_ID must be a number.")
        return
    pkg = context.args[1] if len(context.args) > 1 else "vip1"
    if pkg not in PACKAGES:
        await update.message.reply_text("Package must be vip1, full, or vip2")
        return
    mark_paid(user_id, None, "usdc", pkg)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=access_text_for(user_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_text(f"✅ Access ({pkg}) sent to {user_id}")
    except TelegramError as exc:
        await update.message.reply_text(f"Marked as paid, but could not message the user: {exc}")


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
    lines = []
    for uid, info in users.items():
        pkgs = ",".join(info.get("packages") or [info.get("package") or "?"])
        lines.append(f"{uid} | @{info.get('username') or '—'} | {pkgs} | {info.get('method')}")
    await update.message.reply_text("Paid users:\n" + "\n".join(lines[-50:]))


def validate_config() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing.")
    if not ADMIN_ID:
        logger.warning("ADMIN_ID is not set.")
    if not LINK_VIP1:
        logger.warning("PRIVATE_CHANNEL_LINK (VIP1) is not set.")
    if not LINK_VIP2:
        logger.warning("PRIVATE_CHANNEL_LINK_2 (VIP2) is not set.")
    if not USDT_ADDRESS:
        logger.warning("USDT_ADDRESS is not set.")


def main() -> None:
    validate_config()
    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["pending_pkg"] = {}
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
