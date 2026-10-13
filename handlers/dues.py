from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.permissions import require_seller, require_admin, get_user_role
from core.format import esc, code, _truncate
from core.state import state
from database.sellers import get_seller_by_user_id, list_sellers
from database.dues import (
    add_due, remove_due, get_dues_balance,
    get_all_dues_balances, get_dues_history, count_dues,
)
from utils.notifications import notify_seller_dues_edit
import config

DUES_PER_PAGE = 5


def _find_seller(name):
    target_name = name.lstrip("@").lower()
    fallback = None
    for s in list_sellers():
        sd = dict(s) if not isinstance(s, dict) else s
        if sd["name"].lower() != target_name:
            continue
        if sd.get("active"):
            return sd
        fallback = fallback or sd
    return fallback


def _is_amount(token):
    try:
        float(token.replace(config.CURRENCY, "").replace(",", ""))
        return True
    except ValueError:
        return False


def _fmt_due_entry(entry):
    e = dict(entry) if not isinstance(entry, dict) else entry
    due_type = e.get("type", "add")
    amount = e.get("amount", 0)
    reason = e.get("reason") or "—"
    seller_name = e.get("seller_name", "—")
    created_at = e.get("created_at", "?")
    emoji = "📈" if due_type == "add" else "📉"
    sign = "+" if due_type == "add" else "-"
    return (
        f"{emoji} <b>{esc(seller_name)}</b>\n"
        f"💰 {sign}{config.CURRENCY}{amount:.0f}\n"
        f"📝 {esc(reason)}\n"
        f"🕒 <code>{esc(str(created_at)[:19])}</code>"
    )


def _fmt_dues_page(entries, page, total_pages, summary_text=""):
    text = f"<b>💳 Dues — page {page}/{total_pages}</b>\n"
    if summary_text:
        text += f"{summary_text}\n"
    text += "\n"
    for entry in entries:
        text += _fmt_due_entry(entry) + "\n\n"
    if not entries:
        text += "📭 No dues found."
    return text


def _dues_keyboard(page, total_pages):
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"duespage:{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"duespage:{page + 1}"))
    return InlineKeyboardMarkup([nav_row])


async def dues_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_seller(update):
        return
    user_id = update.effective_user.id
    role = get_user_role(user_id)
    seller = get_seller_by_user_id(user_id)
    if role != "admin" and not seller:
        await update.message.reply_text("⚠️ You are not registered as a seller.")
        return
    args = context.args
    if args and args[0].lower() == "all" and role == "admin":
        balances = get_all_dues_balances()
        if not balances:
            await update.message.reply_text("📭 No pending dues.")
            return
        text = "<b>💳 All Seller Dues</b>\n\n"
        for b in balances:
            bd = dict(b) if not isinstance(b, dict) else b
            text += f"👤 <code>{esc(bd['seller_name'])}</code> — {config.CURRENCY}{bd['balance']:.0f}\n"
        await update.message.reply_text(_truncate(text), parse_mode="HTML")
        return
    if args and role == "admin":
        target = _find_seller(args[0])
        if not target:
            await update.message.reply_text(f"⚠️ Seller <code>{esc(args[0])}</code> not found.", parse_mode="HTML")
            return
        balance = get_dues_balance(target["id"])
        total = count_dues(seller_id=target["id"])
        total_pages = max(1, (total + DUES_PER_PAGE - 1) // DUES_PER_PAGE)
        entries = get_dues_history(seller_id=target["id"], limit=DUES_PER_PAGE, offset=0)
        summary = f"\n👤 <b>{esc(target['name'])}</b> — Total: {config.CURRENCY}{balance:.0f}"
        text = _fmt_dues_page(entries, 1, total_pages, summary)
        kb = _dues_keyboard(1, total_pages)
        context.user_data["dues_seller_id"] = target["id"]
        await update.message.reply_text(_truncate(text), parse_mode="HTML", reply_markup=kb)
        return
    seller_id = seller["id"] if seller else None
    if role == "admin":
        balances = get_all_dues_balances()
        text = "<b>💳 Seller Dues Overview</b>\n\n"
        if balances:
            for b in balances:
                bd = dict(b) if not isinstance(b, dict) else b
                text += f"👤 <code>{esc(bd['seller_name'])}</code> — {config.CURRENCY}{bd['balance']:.0f}\n"
        else:
            text += "📭 No pending dues."
        text += "\n\n<i>Use /dues @name for seller history</i>"
        await update.message.reply_text(_truncate(text), parse_mode="HTML")
        return
    balance = get_dues_balance(seller_id) if seller_id else 0
    total = count_dues(seller_id=seller_id)
    if total == 0:
        await update.message.reply_text(
            f"💳 <b>Your Dues:</b> {config.CURRENCY}{balance:.0f}\n\n📭 No dues history.",
            parse_mode="HTML",
        )
        return
    total_pages = max(1, (total + DUES_PER_PAGE - 1) // DUES_PER_PAGE)
    entries = get_dues_history(seller_id=seller_id, limit=DUES_PER_PAGE, offset=0)
    summary = f"\n💰 <b>Total Due:</b> {config.CURRENCY}{balance:.0f}"
    text = _fmt_dues_page(entries, 1, total_pages, summary)
    kb = _dues_keyboard(1, total_pages)
    context.user_data["dues_seller_id"] = seller_id
    await update.message.reply_text(_truncate(text), parse_mode="HTML", reply_markup=kb)


async def duesadd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_seller(update):
        return
    user_id = update.effective_user.id
    is_admin = get_user_role(user_id) == "admin"
    args = list(context.args or [])
    if is_admin:
        if not args or _is_amount(args[0]):
            await update.message.reply_text("⚠️ Usage: /duesadd @seller <amount> [reason]")
            return
        target = _find_seller(args[0])
        if not target:
            await update.message.reply_text(f"⚠️ Seller <code>{esc(args[0])}</code> not found.", parse_mode="HTML")
            return
        args = args[1:]
        who = f" for <b>{esc(target['name'])}</b>"
    else:
        target = get_seller_by_user_id(user_id)
        if not target:
            await update.message.reply_text("⚠️ You are not registered as a seller.")
            return
        who = ""
    target_id = target["id"]

    if not args:
        state.set(user_id, "duesadd_seller_id", target_id)
        state.set(user_id, "duesadd_step", "amount")
        await update.message.reply_text(
            f"💰 <b>Add Due</b>{who}\n\nHow much do you want to add?",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(args[0])
        if amount <= 0:
            await update.message.reply_text("⚠️ Amount must be positive.")
            return
    except ValueError:
        usage = "/duesadd @seller 500 reason" if is_admin else "/duesadd 500"
        await update.message.reply_text(f"⚠️ Invalid amount. Usage: {usage}")
        return

    reason = " ".join(args[1:]) if len(args) > 1 else None
    if not reason:
        state.set(user_id, "duesadd_seller_id", target_id)
        state.set(user_id, "duesadd_amount", amount)
        state.set(user_id, "duesadd_step", "reason")
        await update.message.reply_text(
            f"💰 Adding {config.CURRENCY}{amount:.0f}{who} to dues.\n\n"
            f"📝 Please enter a reason for this due:",
            parse_mode="HTML",
        )
        return
    add_due(target_id, amount, reason)
    await update.message.reply_text(
        f"✅ <b>Due Added</b>{who}\n\n"
        f"💰 Amount: {config.CURRENCY}{amount:.0f}\n"
        f"📝 Reason: {esc(reason)}",
        parse_mode="HTML",
    )
    if is_admin:
        await notify_seller_dues_edit(
            update, context, target, "add", amount, reason, get_dues_balance(target_id)
        )


async def duesremove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_seller(update):
        return
    user_id = update.effective_user.id
    is_admin = get_user_role(user_id) == "admin"
    args = list(context.args or [])
    if is_admin:
        if not args or _is_amount(args[0]):
            await update.message.reply_text("⚠️ Usage: /duesremove @seller <amount> [reason]")
            return
        target = _find_seller(args[0])
        if not target:
            await update.message.reply_text(f"⚠️ Seller <code>{esc(args[0])}</code> not found.", parse_mode="HTML")
            return
        args = args[1:]
        who = f" for <b>{esc(target['name'])}</b>"
    else:
        target = get_seller_by_user_id(user_id)
        if not target:
            await update.message.reply_text("⚠️ You are not registered as a seller.")
            return
        who = ""
    target_id = target["id"]
    balance = get_dues_balance(target_id)

    if not args:
        if balance <= 0:
            await update.message.reply_text(f"📭 No dues to remove{who}.", parse_mode="HTML")
            return
        state.set(user_id, "duesremove_seller_id", target_id)
        state.set(user_id, "duesremove_step", "amount")
        await update.message.reply_text(
            f"📉 <b>Remove Due</b>{who} (Balance: {config.CURRENCY}{balance:.0f})\n\n"
            f"How much do you want to remove?",
            parse_mode="HTML",
        )
        return

    try:
        amount = float(args[0])
        if amount <= 0:
            await update.message.reply_text("⚠️ Amount must be positive.")
            return
    except ValueError:
        usage = "/duesremove @seller 500 reason" if is_admin else "/duesremove 500"
        await update.message.reply_text(f"⚠️ Invalid amount. Usage: {usage}")
        return

    if amount > balance:
        await update.message.reply_text(
            f"⚠️ Cannot remove {config.CURRENCY}{amount:.0f}. "
            f"Balance is {config.CURRENCY}{balance:.0f}."
        )
        return

    reason = " ".join(args[1:]) if len(args) > 1 else None
    if not reason:
        state.set(user_id, "duesremove_seller_id", target_id)
        state.set(user_id, "duesremove_amount", amount)
        state.set(user_id, "duesremove_step", "reason")
        await update.message.reply_text(
            f"📉 Removing {config.CURRENCY}{amount:.0f}{who} from dues.\n\n"
            f"📝 Please enter a reason for this removal:",
            parse_mode="HTML",
        )
        return
    remove_due(target_id, amount, reason)
    await update.message.reply_text(
        f"✅ <b>Due Removed</b>{who}\n\n"
        f"💰 Amount: {config.CURRENCY}{amount:.0f}\n"
        f"📝 Reason: {esc(reason)}",
        parse_mode="HTML",
    )
    if is_admin:
        await notify_seller_dues_edit(
            update, context, target, "remove", amount, reason, get_dues_balance(target_id)
        )
