import logging
from telegram import Bot
from core.format import code_id, code, esc
import config

logger = logging.getLogger(__name__)


async def notify_admin(context, message):
    try:
        await context.bot.send_message(chat_id=config.ADMIN_USER_ID, text=message, parse_mode="HTML")
    except Exception as e:
        logger.error("Failed to notify admin: %s", e)


async def notify_seller(context, user_id, message):
    try:
        await context.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")
        return True
    except Exception as e:
        logger.error("Failed to notify seller %s: %s", user_id, e)
        return False


def fmt_dues_update(action, amount, reason, balance):
    emoji = "📈" if action == "add" else "📉"
    sign = "+" if action == "add" else "-"
    return (
        f"💳 <b>Your dues were updated by admin</b>\n\n"
        f"{emoji} {sign}{config.CURRENCY}{amount:.0f}\n"
        f"📝 {esc(reason) if reason else '—'}\n"
        f"💰 New balance: {config.CURRENCY}{balance:.0f}"
    )


async def notify_seller_dues_edit(update, context, target, action, amount, reason, balance):
    """Tell a seller admin edited their dues; on failure show it in the admin's chat."""
    if await notify_seller(context, target["user_id"], fmt_dues_update(action, amount, reason, balance)):
        return True
    chat = update.effective_chat
    if chat:
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"⚠️ Dues updated, but could not DM <b>{esc(target['name'])}</b>.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to send dues edit fallback: %s", e)
    return False


def fmt_void_notification(sale_code):
    return f"♻️ {code(sale_code)} voided — account returned to stock"


def fmt_seller_added(name, user_id):
    return f"👤 New seller: {esc(name)} (ID: {code_id(user_id)})"


def fmt_seller_removed(name, user_id):
    return f"🚫 Seller removed: {esc(name)} (ID: {code_id(user_id)})"


def fmt_bulk_import(added, skipped, category):
    return f"📥 Bulk import: {added} added, {skipped} skipped in {code(category or '—')}"



