from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from core.permissions import require_seller
from core.state import state
from core.format import esc, code, code_id, spoiler, _d, fmt_receipt, _truncate, reddit_url
from core.keyboards import confirm_keyboard, sell_select_keyboard, category_keyboard
from core.filters import (
    apply_list_filters,
    fmt_account_list_line, PAGE_SIZE,
)
from database import (
    get_account_by_id, get_sale_by_id, sell_account, get_seller_by_user_id,
    count_accounts, get_available_account_ids,
)
from database.sales import bulk_sell_accounts
from utils.notifications import notify_admin
import config
import logging

logger = logging.getLogger(__name__)


def _refresh_select_page(user_id, query, prefix="sell"):
    selected = state.get(user_id, f"{prefix}_selected", [])
    page = state.get(user_id, f"{prefix}_page", 1)
    filter_str = state.get(user_id, f"{prefix}_filter") or "status:available"
    cat_id = state.get(user_id, f"{prefix}_category")
    if cat_id:
        filter_str = f"cat:{cat_id}|{filter_str}"
    accounts, total = apply_list_filters(filter_str, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    return selected, accounts, page, total_pages, filter_str


def _sell_filter_str(user_id):
    cat_id = state.get(user_id, "sell_category")
    base = "status:available"
    if cat_id:
        return f"cat:{cat_id}|{base}"
    return base


def _sample_filter_str(user_id):
    cat_id = state.get(user_id, "sample_category")
    base = "status:available"
    if cat_id:
        return f"cat:{cat_id}|{base}"
    return base


def _mode_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👆 Pick accounts", callback_data="sellmode:selectmany"),
            InlineKeyboardButton("🔢 Enter number", callback_data="sellmode:number"),
        ],
    ])


def _fmt_sample_output(accounts):
    if not accounts:
        return "📭 No accounts found."
    lines = [f"<b>📋 Account Samples — {len(accounts)} account(s)</b>\n"]
    for acc in accounts:
        a = acc if isinstance(acc, dict) else dict(acc)
        username = a.get("username", "?")
        profile_link = f"https://reddit.com/user/{username}"
        has_2fa = "Yes" if a.get("has_2fa") else "No"
        is_verified = "Yes" if a.get("is_verified") else "No"
        acct_id = a.get("id", "?")
        lines.append(
            f"╭─ Account #{acct_id} ──────────\n"
            f"│ 👤 Username: <code>{esc(username)}</code>\n"
            f"│ 🔗 Link: {profile_link}\n"
            f"│ 🔐 2FA: {has_2fa}\n"
            f"│ ✅ Verified: {is_verified}\n"
            f"│ 🆔 ID: {acct_id}\n"
            f"╰───────────────────────"
        )
    result = "\n".join(lines)
    if len(result) > 4000:
        visible = len(accounts)
        result = _truncate(result, 3900)
        result += f"\n\n<i>({visible} accounts shown — message truncated)</i>"
    return result


async def try_handle(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str, user_id: int) -> bool:
    query = update.callback_query
    await query.answer()

    if data == "menu:sell":
        if not await require_seller(update):
            return True
        seller = get_seller_by_user_id(user_id)
        if not seller:
            await query.edit_message_text("⚠️ You are not registered as a seller.")
            return True
        kb = category_keyboard("sellcat", include_all=True, status="available")
        if not kb:
            state.set(user_id, "sell_category", None)
            await query.edit_message_text("💰 Sell accounts:", reply_markup=_mode_keyboard())
        else:
            await query.edit_message_text("📂 Select category to sell from:", reply_markup=kb)
        return True

    if data.startswith("sellcat:"):
        if not await require_seller(update):
            return True
        cat_value = data.split(":", 1)[1]
        if cat_value == "all":
            state.set(user_id, "sell_category", None)
        else:
            state.set(user_id, "sell_category", int(cat_value))
        await query.edit_message_text("💰 Sell accounts:", reply_markup=_mode_keyboard())
        return True

    if data.startswith("sellmode:"):
        if not await require_seller(update):
            return True
        mode = data.split(":", 1)[1]
        filter_str = _sell_filter_str(user_id)

        if mode == "selectmany":
            state.set(user_id, "sell_selected", [])
            state.set(user_id, "sell_page", 1)
            accounts, total = apply_list_filters(filter_str, limit=PAGE_SIZE, offset=0)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            text = f"<b>💰 Pick Accounts — Tap to select</b>\n\n"
            for acc in accounts:
                text += fmt_account_list_line(acc) + "\n"
            kb = sell_select_keyboard([], accounts, 1, total_pages, max_select=None)
            await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)

        elif mode == "number":
            cat_id = state.get(user_id, "sell_category")
            available = count_accounts(status="available", category_id=cat_id)
            state.set(user_id, "sell_stage", "number")
            await query.edit_message_text(
                f"🔢 How many accounts to sell? (available: {available})"
            )
        return True

    if data.startswith("selltoggle:"):
        if not await require_seller(update):
            return True
        try:
            account_id = int(data.split(":")[1])
        except ValueError:
            return True
        selected = state.get(user_id, "sell_selected", [])
        if account_id in selected:
            selected.remove(account_id)
        else:
            selected.append(account_id)
        state.set(user_id, "sell_selected", selected)
        selected, accounts, page, total_pages, filter_str = _refresh_select_page(user_id, query)
        text = f"<b>💰 Pick Accounts — {len(selected)} selected</b>\n\n"
        for acc in accounts:
            text += fmt_account_list_line(acc) + "\n"
        kb = sell_select_keyboard(selected, accounts, page, total_pages, max_select=None)
        await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)
        return True

    if data.startswith("sellpage:"):
        if not await require_seller(update):
            return True
        try:
            page = int(data.split(":")[1])
        except ValueError:
            return True
        state.set(user_id, "sell_page", page)
        selected, accounts, page, total_pages, filter_str = _refresh_select_page(user_id, query)
        text = f"<b>💰 Pick Accounts — {len(selected)} selected</b>\n\n"
        for acc in accounts:
            text += fmt_account_list_line(acc) + "\n"
        kb = sell_select_keyboard(selected, accounts, page, total_pages, max_select=None)
        await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)
        return True

    if data == "selldone":
        if not await require_seller(update):
            return True
        selected = state.get(user_id, "sell_selected", [])
        if not selected:
            await query.edit_message_text("⚠️ No accounts selected.")
            return True
        state.set(user_id, "sell_stage", "price")
        await query.edit_message_text(
            f"💰 {len(selected)} account(s) selected.\nEnter price per account ({config.CURRENCY}):"
        )
        return True

    if data.startswith("quicksell:"):
        if not await require_seller(update):
            return True
        try:
            account_id = int(data.split(":")[1])
        except ValueError:
            return True
        state.set(user_id, "sell_selected", [account_id])
        state.set(user_id, "sell_page", 1)
        state.set(user_id, "sell_stage", "price")
        await query.edit_message_text(f"💰 Enter price per account ({config.CURRENCY}):")
        return True

    if data.startswith("paystatus:"):
        if not await require_seller(update):
            return True
        payment_status = data.split(":", 1)[1]
        state.set(user_id, "sell_payment_status", payment_status)
        selected = state.get(user_id, "sell_selected", [])
        price = state.get(user_id, "sell_price")

        ps_label = "🟡 Pending Payment" if payment_status == "pending" else "🔴 Sold"
        if len(selected) == 1:
            account = get_account_by_id(selected[0])
            a = _d(account) if account else {}
            text_preview = (
                f"<b>Confirm Sale:</b>\n\n"
                f"Account: {code_id(a.get('id', '?'))} — {code(a.get('username', '?'))}\n"
                f"Price: {config.CURRENCY}{price:.0f}\n"
                f"Status: {ps_label}\n\n"
                f"✅ Confirm?"
            )
        else:
            text_preview = (
                f"<b>Confirm Bulk Sale:</b>\n\n"
                f"Accounts: {len(selected)}\n"
                f"Price per account: {config.CURRENCY}{price:.0f}\n"
                f"Status: {ps_label}\n\n"
                f"✅ Confirm?"
            )
        state.set(user_id, "sell_stage", "confirm")
        await query.edit_message_text(
            text_preview,
            parse_mode="HTML",
            reply_markup=confirm_keyboard("sellconfirm", "sellcancel"),
        )
        return True

    if data == "sellconfirm":
        if not await require_seller(update):
            return True
        seller = get_seller_by_user_id(user_id)
        if not seller:
            await query.edit_message_text("⚠️ You are not registered as a seller.")
            return True
        selected = state.pop(user_id, "sell_selected", [])
        price = state.pop(user_id, "sell_price", 0)
        payment_status = state.pop(user_id, "sell_payment_status", "pending")
        state.pop(user_id, "sell_stage", None)
        state.pop(user_id, "sell_filter", None)
        state.pop(user_id, "sell_page", None)
        state.pop(user_id, "sell_category", None)

        if not selected:
            await query.edit_message_text("⚠️ Session expired. Please start over.")
            return True

        if len(selected) == 1:
            account_id = selected[0]
            success, msg, sale_code = sell_account(
                account_id, seller["id"], price,
                payment_status=payment_status,
            )
            if success:
                sale = get_sale_by_id(sale_code)
                receipt = fmt_receipt(sale)
                await query.edit_message_text(receipt, parse_mode="HTML")
                status_label = "pending payment" if payment_status == "pending" else "sold"
                code_str = _d(sale).get("sale_code", sale_code) if sale else sale_code
                await notify_admin(context, f"💰 New sale! {code(code_str)} — {config.CURRENCY}{price:.0f} ({status_label}) — by {esc(seller['name'])}")
                if price >= config.HIGH_VALUE_THRESHOLD:
                    await notify_admin(context, f"🔥 High-value sale! {code(code_str)} — {config.CURRENCY}{price:.0f} — by {esc(seller['name'])}")
                try:
                    pay_cmd = f"/pay {code_str}"
                    chat = update.effective_chat
                    if chat is not None:
                        try:
                            await context.bot.send_message(
                                chat_id=chat.id,
                                text=f"use this command to generate payment link from tg-payment-pro\n\n{code(pay_cmd)}",
                                parse_mode="HTML",
                            )
                        except BadRequest:
                            await context.bot.send_message(
                                chat_id=chat.id,
                                text=f"use this command to generate payment link from tg-payment-pro\n\n{pay_cmd}",
                            )
                except Exception as e:
                    logger.error("Failed to send pay command hint: %s", e)
                    try:
                        await query.message.reply_text(
                            f"use this command to generate payment link from tg-payment-pro\n\n{pay_cmd}"
                        )
                    except Exception:
                        pass
            else:
                await query.edit_message_text(f"❌ {msg}")
        else:
            result = bulk_sell_accounts(
                selected, seller["id"], price,
                payment_status=payment_status,
            )
            status_label = "pending payment" if payment_status == "pending" else "sold"
            chat_id = update.effective_chat.id

            for sale_code in result.get("sale_codes", []):
                sale = get_sale_by_id(sale_code)
                if not sale:
                    continue
                receipt = fmt_receipt(sale)
                try:
                    await context.bot.send_message(chat_id=chat_id, text=receipt, parse_mode="HTML")
                except BadRequest as e:
                    logger.error("Failed to send receipt: %s", e)
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=receipt)
                    except Exception as e2:
                        logger.error("Failed to send receipt plain: %s", e2)
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"Sale {sale_code} created but receipt failed to send.",
                        )

            try:
                await query.edit_message_text(
                    f"✅ Bulk {status_label}: {result['added']} accounts — {config.CURRENCY}{price:.0f} each"
                )
            except BadRequest:
                pass
            await notify_admin(context, f"💰 Bulk sell: {result['added']} accounts — {config.CURRENCY}{price:.0f} each ({status_label}) — by {esc(seller['name'])}")
            sale_codes = result.get("sale_codes", [])
            if sale_codes:
                pay_cmd = "/pay " + ", ".join(sale_codes)
                try:
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"use this command to generate payment link from tg-payment-pro\n\n{code(pay_cmd)}",
                            parse_mode="HTML",
                        )
                    except BadRequest:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"use this command to generate payment link from tg-payment-pro\n\n{pay_cmd}",
                        )
                except Exception as e:
                    logger.error("Failed to send bulk pay command hint: %s", e)
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"use this command to generate payment link from tg-payment-pro\n\n{pay_cmd}",
                        )
                    except Exception:
                        pass
        return True

    if data == "sellcancel":
        for key in ("sell_selected", "sell_price", "sell_payment_status",
                     "sell_stage", "sell_filter", "sell_page", "sell_category"):
            state.pop(user_id, key, None)
        await query.edit_message_text("❌ Sale cancelled.")
        return True

    # ── Sample flow ────────────────────────────────────────
    if data == "menu:sample":
        if not await require_seller(update):
            return True
        for key in ("sample_selected", "sample_page", "sample_filter",
                     "sample_stage", "sample_category"):
            state.pop(user_id, key, None)
        state.set(user_id, "sample_category", None)
        kb = category_keyboard("samplecat", include_all=True)
        if not kb:
            await query.edit_message_text("📋 Generate account samples:", reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👆 Pick accounts", callback_data="samplemode:selectmany"),
                    InlineKeyboardButton("🔢 Enter number", callback_data="samplemode:number"),
                ],
            ]))
        else:
            await query.edit_message_text("📂 Select category for samples:", reply_markup=kb)
        return True

    if data.startswith("samplecat:"):
        if not await require_seller(update):
            return True
        cat_value = data.split(":", 1)[1]
        if cat_value == "all":
            state.set(user_id, "sample_category", None)
        else:
            state.set(user_id, "sample_category", int(cat_value))
        await query.edit_message_text("📋 Generate account samples:", reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👆 Pick accounts", callback_data="samplemode:selectmany"),
                InlineKeyboardButton("🔢 Enter number", callback_data="samplemode:number"),
            ],
        ]))
        return True

    if data.startswith("samplemode:"):
        if not await require_seller(update):
            return True
        mode = data.split(":", 1)[1]
        filter_str = _sample_filter_str(user_id)

        if mode == "selectmany":
            state.set(user_id, "sample_selected", [])
            state.set(user_id, "sample_page", 1)
            accounts, total = apply_list_filters(filter_str, limit=PAGE_SIZE, offset=0)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            text = f"<b>📋 Pick Accounts for Sample — Tap to select</b>\n\n"
            for acc in accounts:
                text += fmt_account_list_line(acc) + "\n"
            kb = sell_select_keyboard([], accounts, 1, total_pages, max_select=None, prefix="sample")
            await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)

        elif mode == "number":
            cat_id = state.get(user_id, "sample_category")
            available = count_accounts(status="available", category_id=cat_id)
            state.set(user_id, "sample_stage", "number")
            await query.edit_message_text(
                f"🔢 How many accounts for sample? (available: {available})"
            )
        return True

    if data.startswith("sampletoggle:"):
        if not await require_seller(update):
            return True
        try:
            account_id = int(data.split(":")[1])
        except ValueError:
            return True
        selected = state.get(user_id, "sample_selected", [])
        if account_id in selected:
            selected.remove(account_id)
        else:
            selected.append(account_id)
        state.set(user_id, "sample_selected", selected)
        selected, accounts, page, total_pages, filter_str = _refresh_select_page(user_id, query, prefix="sample")
        text = f"<b>📋 Pick Accounts for Sample — {len(selected)} selected</b>\n\n"
        for acc in accounts:
            text += fmt_account_list_line(acc) + "\n"
        kb = sell_select_keyboard(selected, accounts, page, total_pages, max_select=None, prefix="sample")
        await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)
        return True

    if data.startswith("samplepage:"):
        if not await require_seller(update):
            return True
        try:
            page = int(data.split(":")[1])
        except ValueError:
            return True
        state.set(user_id, "sample_page", page)
        selected, accounts, page, total_pages, filter_str = _refresh_select_page(user_id, query, prefix="sample")
        text = f"<b>📋 Pick Accounts for Sample — {len(selected)} selected</b>\n\n"
        for acc in accounts:
            text += fmt_account_list_line(acc) + "\n"
        kb = sell_select_keyboard(selected, accounts, page, total_pages, max_select=None, prefix="sample")
        await query.edit_message_text(_truncate(text), parse_mode="HTML", reply_markup=kb)
        return True

    if data == "sampledone":
        if not await require_seller(update):
            return True
        selected = state.get(user_id, "sample_selected", [])
        if not selected:
            await query.edit_message_text("⚠️ No accounts selected.")
            return True
        accounts = []
        for aid in selected:
            acc = get_account_by_id(aid)
            if acc:
                accounts.append(_d(acc))
        for key in ("sample_selected", "sample_page", "sample_filter",
                     "sample_stage", "sample_category"):
            state.pop(user_id, key, None)
        text = _fmt_sample_output(accounts)
        await query.edit_message_text(_truncate(text), parse_mode="HTML")
        return True

    if data == "samplecancel":
        for key in ("sample_selected", "sample_page", "sample_filter",
                     "sample_stage", "sample_category"):
            state.pop(user_id, key, None)
        await query.edit_message_text("❌ Sample cancelled.")
        return True

    return False
