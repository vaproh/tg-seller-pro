from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from core.permissions import require_seller, require_admin, get_user_role
from core.state import state
from core.format import esc, code, code_id, _d, _truncate
from core.keyboards import category_keyboard, confirm_keyboard
from core.filters import (
    payment_status_keyboard, parse_id_list,
    apply_list_filters, fmt_account_list_page,
    filter_page_keyboard, PAGE_SIZE,
)
from database import (
    add_accounts_bulk, get_account_by_id,
    get_category_name,
    delete_accounts_by_ids,
)
from database.sales import update_sale, get_sale_by_id, create_draft_sale
from database import get_seller_by_user_id
from utils.parsers import parse_bulk_lines, parse_csv_file
from utils.notifications import notify_admin, fmt_bulk_import, notify_seller_dues_edit
import config

MAX_CSV_SIZE = 5 * 1024 * 1024


def _dues_target_note(user_id, key):
    """For admins mid-flow: ' for <b>Name</b>', so they know whose ledger they're editing."""
    if get_user_role(user_id) != "admin":
        return ""
    seller_id = state.get(user_id, key)
    if not seller_id:
        return ""
    from database.sellers import get_seller_by_id
    target = get_seller_by_id(seller_id)
    return f" for <b>{esc(target['name'])}</b>" if target else ""


async def _editsale_process_ids_text(update, context, text):
    user_id = update.effective_user.id
    mode = state.get(user_id, "editsale_mode")
    state.pop(user_id, "editsale_mode", None)
    ids = [x.strip() for x in text.split(",") if x.strip()]
    seller = get_seller_by_user_id(user_id)
    seller_id = seller["id"] if seller else None
    valid_sales = []
    invalid_ids = []
    created_drafts = []
    for id_str in ids:
        if mode == "sale":
            sale = get_sale_by_id(id_str)
            if sale:
                valid_sales.append(_d(sale))
            else:
                invalid_ids.append(id_str)
        elif mode == "account":
            sale = get_sale_by_id(id_str)
            if sale:
                valid_sales.append(_d(sale))
                continue
            try:
                account_id = int(id_str)
            except ValueError:
                invalid_ids.append(id_str)
                continue
            account = get_account_by_id(account_id)
            if account and _d(account).get("status") in ("sold", "pending_payment"):
                draft_id = create_draft_sale(account_id, seller_id)
                if draft_id:
                    sale = get_sale_by_id(draft_id)
                    if sale:
                        sd = _d(sale)
                        valid_sales.append(sd)
                        created_drafts.append((id_str, sd.get("sale_code", f"#{draft_id}")))
                    else:
                        invalid_ids.append(id_str)
                else:
                    invalid_ids.append(id_str)
            else:
                invalid_ids.append(id_str)
        else:
            sale = get_sale_by_id(id_str)
            if sale:
                valid_sales.append(_d(sale))
            else:
                try:
                    account_id = int(id_str)
                except ValueError:
                    invalid_ids.append(id_str)
                    continue
                account = get_account_by_id(account_id)
                if account and _d(account).get("status") in ("sold", "pending_payment"):
                    draft_id = create_draft_sale(account_id, seller_id)
                    if draft_id:
                        sale = get_sale_by_id(draft_id)
                        if sale:
                            sd = _d(sale)
                            valid_sales.append(sd)
                            created_drafts.append((id_str, sd.get("sale_code", f"#{draft_id}")))
                        else:
                            invalid_ids.append(id_str)
                    else:
                        invalid_ids.append(id_str)
                else:
                    invalid_ids.append(id_str)
    if not valid_sales:
        await update.message.reply_text(f"⚠️ Not found: {', '.join(code(i) for i in invalid_ids)}", parse_mode="HTML")
        return
    state.set(user_id, "editsale_ids", [s["id"] for s in valid_sales])
    state.set(user_id, "editsale_pending", {})
    from handlers.sell import _editsale_summary, _editsale_field_keyboard
    text_msg = _editsale_summary(valid_sales, invalid_ids, created_drafts)
    kb = _editsale_field_keyboard()
    await update.message.reply_text(_truncate(text_msg), parse_mode="HTML", reply_markup=kb)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_seller(update):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ── Add account wizard ─────────────────────────────────
    stage = state.get(user_id, "add_stage")
    if stage == "username":
        if len(text) > config.MAX_USERNAME_LEN:
            await update.message.reply_text(f"⚠️ Username too long (max {config.MAX_USERNAME_LEN} chars).")
            return
        state.set(user_id, "add_username", text)
        state.set(user_id, "add_stage", "password")
        await update.message.reply_text(f"✅ Username: {code(text)}\n🔑 Send the password:", parse_mode="HTML")
        return

    if stage == "password":
        if len(text) > config.MAX_PASSWORD_LEN:
            await update.message.reply_text(f"⚠️ Password too long (max {config.MAX_PASSWORD_LEN} chars).")
            return
        state.set(user_id, "add_password", text)
        state.set(user_id, "add_stage", "email")
        await update.message.reply_text("✅ Password saved\n📧 Send email (or /skip):")
        return

    if stage == "email":
        if text.lower() == "/skip":
            state.set(user_id, "add_email", None)
            state.set(user_id, "add_stage", "email_password")
            await update.message.reply_text("📧 Send email password (or /skip):")
            return
        if len(text) > config.MAX_EMAIL_LEN:
            await update.message.reply_text(f"⚠️ Email too long (max {config.MAX_EMAIL_LEN} chars).")
            return
        state.set(user_id, "add_email", text)
        state.set(user_id, "add_stage", "email_password")
        await update.message.reply_text(f"✅ Email: {code(text)}\n📧 Send email password (or /skip):", parse_mode="HTML")
        return

    if stage == "email_password":
        if text.lower() == "/skip":
            state.set(user_id, "add_email_password", None)
            state.set(user_id, "add_stage", "2fa")
            await update.message.reply_text("🔐 Is 2FA enabled?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes", callback_data="add2fa:yes"),
                 InlineKeyboardButton("No", callback_data="add2fa:no")],
            ]))
            return
        state.set(user_id, "add_email_password", text)
        state.set(user_id, "add_stage", "2fa")
        await update.message.reply_text(
            "✅ Email password saved\n🔐 Is 2FA enabled?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes", callback_data="add2fa:yes"),
                 InlineKeyboardButton("No", callback_data="add2fa:no")],
            ]),
        )
        return

    if stage == "notes":
        if text.lower() == "/skip":
            state.set(user_id, "add_notes", None)
            state.set(user_id, "add_stage", "category")
            kb = category_keyboard("addcat")
            if kb:
                await update.message.reply_text("📂 Select category:", reply_markup=kb)
            else:
                await update.message.reply_text("📂 No categories. Create one with /addcategory first.")
            return
        if len(text) > config.MAX_NOTES_LEN:
            await update.message.reply_text(f"⚠️ Notes too long (max {config.MAX_NOTES_LEN} chars).")
            return
        state.set(user_id, "add_notes", text)
        state.set(user_id, "add_stage", "category")
        kb = category_keyboard("addcat")
        if kb:
            await update.message.reply_text("✅ Notes saved\n📂 Select category:", reply_markup=kb)
        else:
            await update.message.reply_text("📂 No categories. Create one with /addcategory first.")
        return

    # ── Bulk add ───────────────────────────────────────────
    bulk_stage = state.get(user_id, "bulk_stage")
    if bulk_stage == "lines":
        if text.lower() == "/done":
            raw = state.get(user_id, "bulk_lines", "")
            cat_id = state.get(user_id, "bulk_category")
            items = parse_bulk_lines(raw)
            if not items:
                await update.message.reply_text("📭 No valid lines found.")
                state.pop(user_id, "bulk_stage")
                state.pop(user_id, "bulk_lines")
                state.pop(user_id, "bulk_category")
                return
            result = add_accounts_bulk(items, cat_id)
            cat_name = get_category_name(cat_id) or "—"
            state.pop(user_id, "bulk_stage")
            state.pop(user_id, "bulk_lines")
            state.pop(user_id, "bulk_category")
            msg = f"📥 Bulk import: {result['added']} added, {result['skipped']} skipped in {code(cat_name)}"
            await update.message.reply_text(msg, parse_mode="HTML")
            await notify_admin(context, fmt_bulk_import(result["added"], result["skipped"], cat_name))
            return
        current = state.get(user_id, "bulk_lines", "")
        if len(current) > 100000:
            await update.message.reply_text("⚠️ Bulk input too large. Send /done to process what you have.")
            return
        state.set(user_id, "bulk_lines", current + text + "\n")
        lines = text.strip().splitlines()
        await update.message.reply_text(f"✅ {len(lines)} lines received. Send more or /done.")
        return

    # ── Bulk delete ────────────────────────────────────────
    bd_mode = state.get(user_id, "bulk_delete_mode")
    if bd_mode == "input":
        state.set(user_id, "bulk_delete_input", text)
        state.set(user_id, "bulk_delete_mode", "confirm")
        await update.message.reply_text(
            f"⚠️ Confirm delete:\n<code>{esc(text)}</code>",
            parse_mode="HTML",
            reply_markup=confirm_keyboard("bulkdelconfirm", "bulkdelcancel"),
        )
        return

    # ── Preview count ──────────────────────────────────────
    preview_stage = state.get(user_id, "preview_stage")
    if preview_stage == "count":
        from handlers.preview import handle_preview_count
        await handle_preview_count(update, context, text)
        return

    # ── Search value ───────────────────────────────────────
    search_stage = state.get(user_id, "search_stage")
    if search_stage == "value":
        from handlers.search import handle_search_value
        await handle_search_value(update, context, text)
        return

    # ── ID input for filters ───────────────────────────────
    # (removed old sell_ids_input — /sell now uses select UI)

    if state.get(user_id, "list_ids_input"):
        state.pop(user_id, "list_ids_input")
        ids = parse_id_list(text)
        if not ids:
            await update.message.reply_text("⚠️ No valid IDs. Enter comma-separated numbers:")
            state.set(user_id, "list_ids_input", True)
            return
        state.set(user_id, "list_filter", f"ids:{','.join(str(i) for i in ids)}")
        state.set(user_id, "list_page", 1)
        filter_str = state.get(user_id, "list_filter")
        accounts, total = apply_list_filters(filter_str, limit=PAGE_SIZE, offset=0)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        text_msg = fmt_account_list_page(accounts, 1, total_pages, title="Accounts")
        kb = filter_page_keyboard(
            "listfilter", 1, total_pages,
            include_all=True, include_available=True, include_sold=True,
            include_pending=True, include_ids=True,
        )
        await update.message.reply_text(text_msg, parse_mode="HTML", reply_markup=kb)
        return

    if state.get(user_id, "del_ids_input"):
        state.pop(user_id, "del_ids_input")
        ids = parse_id_list(text)
        if not ids:
            await update.message.reply_text("⚠️ No valid IDs. Enter comma-separated numbers:")
            state.set(user_id, "del_ids_input", True)
            return
        deleted = delete_accounts_by_ids(ids)
        await update.message.reply_text(f"✅ Deleted {deleted} account(s).")
        return

    # ── Sell flow ──────────────────────────────────────────
    sell_stage = state.get(user_id, "sell_stage")

    # ── Edit sale flow ─────────────────────────────────────
    editsale_stage = state.get(user_id, "editsale_stage")
    if editsale_stage == "awaiting_ids":
        state.pop(user_id, "editsale_stage")
        await _editsale_process_ids_text(update, context, text)
        return

    if editsale_stage == "awaiting_fields":
        sale_ids = state.get(user_id, "editsale_ids", [])
        state.pop(user_id, "editsale_ids")
        state.pop(user_id, "editsale_stage")
        fields = {}
        for line in text.strip().splitlines():
            line = line.strip()
            if not line or " " not in line:
                continue
            key, _, value = line.partition(" ")
            key = key.lower().strip()
            value = value.strip()
            if key == "price":
                try:
                    fields["price"] = float(value.replace(config.CURRENCY, "").replace(",", ""))
                except ValueError:
                    pass
            elif key in ("status", "payment_status", "paystatus"):
                if value.lower() in ("paid", "pending"):
                    fields["payment_status"] = value.lower()
            elif key == "notes":
                fields["notes"] = value
        if not fields:
            await update.message.reply_text("⚠️ No valid fields found. Use format: <code>key value</code>", parse_mode="HTML")
            return
        updated, failed = [], []
        for sid in sale_ids:
            sale = get_sale_by_id(sid)
            if not sale:
                failed.append(sid)
                continue
            if update_sale(sid, **fields):
                updated.append(sid)
            else:
                failed.append(sid)
        parts = []
        if updated:
            detail = ", ".join(code_id(i) for i in updated)
            field_names = ", ".join(fields.keys())
            parts.append(f"✏️ Updated {detail}: {field_names}")
        if failed:
            parts.append(f"⚠️ Failed: {', '.join(code(i) for i in failed)}")
        await update.message.reply_text("\n".join(parts), parse_mode="HTML")
        return

    editsale_field = state.get(user_id, "editsale_field")
    if editsale_field in ("price", "notes", "status"):
        sale_ids = state.get(user_id, "editsale_ids", [])
        pending = state.get(user_id, "editsale_pending", {})
        if editsale_field == "price":
            try:
                value = float(text.replace(config.CURRENCY, "").replace(",", ""))
            except ValueError:
                await update.message.reply_text("⚠️ Enter a valid price:")
                return
            field_key = "price"
        elif editsale_field == "notes":
            value = None if text.lower() == "/clear" else text
            field_key = "notes"
        elif editsale_field == "status":
            if text.lower() not in ("paid", "pending"):
                await update.message.reply_text("⚠️ Enter 'paid' or 'pending':")
                return
            value = text.lower()
            field_key = "payment_status"
        else:
            return
        for sid in sale_ids:
            if sid not in pending:
                pending[sid] = {}
            pending[sid][field_key] = value
        state.set(user_id, "editsale_pending", pending)
        state.pop(user_id, "editsale_field")
        from handlers.sell import _editsale_summary_with_pending, _editsale_field_keyboard
        sales = []
        for sid in sale_ids:
            sale = get_sale_by_id(sid)
            if sale:
                sales.append(_d(sale))
        display_value = value if value is not None else "(cleared)"
        text_msg = _editsale_summary_with_pending(sales, pending)
        text_msg += f"\n\n✅ Set {editsale_field} → <code>{esc(str(display_value))}</code> for all {len(sale_ids)} sale(s)"
        kb = _editsale_field_keyboard()
        await update.message.reply_text(_truncate(text_msg), parse_mode="HTML", reply_markup=kb)
        return

    if sell_stage == "price":
        try:
            price = float(text.replace(config.CURRENCY, "").replace(",", ""))
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid price:")
            return
        if price < 0:
            await update.message.reply_text("⚠️ Price must be positive:")
            return
        state.set(user_id, "sell_price", price)
        await update.message.reply_text(
            "📦 Mark as:",
            reply_markup=payment_status_keyboard("paystatus"),
        )
        return

    # ── Bulk sell flow ─────────────────────────────────────
    if sell_stage == "number":
        from database import count_accounts, get_available_account_ids
        try:
            num = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid number:")
            return
        cat_id = state.get(user_id, "sell_category")
        available = count_accounts(status="available", category_id=cat_id)
        if num < 1:
            await update.message.reply_text("⚠️ Must be at least 1:")
            return
        if num > available:
            await update.message.reply_text(f"⚠️ Only {available} available. Enter a smaller number:")
            return
        account_ids = get_available_account_ids(num, category_id=cat_id)
        state.set(user_id, "sell_selected", account_ids)
        state.set(user_id, "sell_stage", "price")
        await update.message.reply_text(
            f"✅ Selected {num} accounts.\n\n💰 Enter price ({config.CURRENCY}):",
        )
        return

    # ── Sample flow (enter number) ─────────────────────────
    sample_stage = state.get(user_id, "sample_stage")
    if sample_stage == "number":
        from database import count_accounts, get_available_account_ids
        try:
            num = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid number:")
            return
        cat_id = state.get(user_id, "sample_category")
        available = count_accounts(status="available", category_id=cat_id)
        if num < 1:
            await update.message.reply_text("⚠️ Must be at least 1:")
            return
        if num > available:
            await update.message.reply_text(f"⚠️ Only {available} available. Enter a smaller number:")
            return
        account_ids = get_available_account_ids(num, category_id=cat_id)
        accounts = []
        for aid in account_ids:
            acc = get_account_by_id(aid)
            if acc:
                accounts.append(_d(acc))
        for key in ("sample_stage", "sample_category", "sample_selected", "sample_page"):
            state.pop(user_id, key, None)
        from handlers.callbacks.sell import _fmt_sample_output
        text_msg = _fmt_sample_output(accounts)
        await update.message.reply_text(_truncate(text_msg), parse_mode="HTML")
        return

    # ── Dues add flow ──────────────────────────────────────
    duesadd_step = state.get(user_id, "duesadd_step")
    if duesadd_step == "amount":
        try:
            amount = float(text.replace(config.CURRENCY, "").replace(",", ""))
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid amount:")
            return
        if amount <= 0:
            await update.message.reply_text("⚠️ Amount must be positive:")
            return
        state.set(user_id, "duesadd_amount", amount)
        state.set(user_id, "duesadd_step", "reason")
        await update.message.reply_text(
            f"💰 Adding {config.CURRENCY}{amount:.0f}{_dues_target_note(user_id, 'duesadd_seller_id')} to dues.\n\n📝 Enter a reason:",
            parse_mode="HTML",
        )
        return

    if duesadd_step == "reason":
        from database.sellers import get_seller_by_user_id, get_seller_by_id
        from database.dues import add_due, get_dues_balance
        amount = state.get(user_id, "duesadd_amount")
        seller_id = state.get(user_id, "duesadd_seller_id")
        who = _dues_target_note(user_id, "duesadd_seller_id")
        state.pop(user_id, "duesadd_step", None)
        state.pop(user_id, "duesadd_amount", None)
        state.pop(user_id, "duesadd_seller_id", None)
        reason = text if text.lower() != "/skip" else None
        if seller_id is None:
            _s = get_seller_by_user_id(user_id)
            seller_id = _s["id"] if _s else None
        if seller_id and amount:
            add_due(seller_id, amount, reason)
            await update.message.reply_text(
                f"✅ <b>Due Added</b>{who}\n\n💰 Amount: {config.CURRENCY}{amount:.0f}\n"
                f"📝 Reason: {esc(reason) if reason else '—'}",
                parse_mode="HTML",
            )
            if who:
                target = get_seller_by_id(seller_id)
                if target:
                    await notify_seller_dues_edit(
                        update, context, target, "add", amount, reason,
                        get_dues_balance(seller_id),
                    )
        return

    # ── Dues remove flow ───────────────────────────────────
    duesremove_step = state.get(user_id, "duesremove_step")
    if duesremove_step == "amount":
        try:
            amount = float(text.replace(config.CURRENCY, "").replace(",", ""))
        except ValueError:
            await update.message.reply_text("⚠️ Enter a valid amount:")
            return
        if amount <= 0:
            await update.message.reply_text("⚠️ Amount must be positive:")
            return
        from database.sellers import get_seller_by_user_id as _get_seller
        from database.dues import get_dues_balance as _get_balance
        _seller_id = state.get(user_id, "duesremove_seller_id")
        if _seller_id is None:
            _seller = _get_seller(user_id)
            _seller_id = _seller["id"] if _seller else None
        if _seller_id:
            _balance = _get_balance(_seller_id)
            if amount > _balance:
                await update.message.reply_text(
                    f"⚠️ Cannot remove {config.CURRENCY}{amount:.0f}. "
                    f"Balance is {config.CURRENCY}{_balance:.0f}."
                )
                return
        state.set(user_id, "duesremove_amount", amount)
        state.set(user_id, "duesremove_step", "reason")
        await update.message.reply_text(
            f"📉 Removing {config.CURRENCY}{amount:.0f}{_dues_target_note(user_id, 'duesremove_seller_id')} from dues.\n\n📝 Enter a reason:",
            parse_mode="HTML",
        )
        return

    if duesremove_step == "reason":
        from database.sellers import get_seller_by_id
        from database.dues import remove_due, get_dues_balance
        amount = state.get(user_id, "duesremove_amount")
        seller_id = state.get(user_id, "duesremove_seller_id")
        who = _dues_target_note(user_id, "duesremove_seller_id")
        state.pop(user_id, "duesremove_step", None)
        state.pop(user_id, "duesremove_amount", None)
        state.pop(user_id, "duesremove_seller_id", None)
        reason = text if text.lower() != "/skip" else None
        if seller_id and amount:
            remove_due(seller_id, amount, reason)
            await update.message.reply_text(
                f"✅ <b>Due Removed</b>{who}\n\n💰 Amount: {config.CURRENCY}{amount:.0f}\n"
                f"📝 Reason: {esc(reason) if reason else '—'}",
                parse_mode="HTML",
            )
            if who:
                target = get_seller_by_id(seller_id)
                if target:
                    await notify_seller_dues_edit(
                        update, context, target, "remove", amount, reason,
                        get_dues_balance(seller_id),
                    )
        return


async def handle_csv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return
    user_id = update.effective_user.id
    csv_stage = state.get(user_id, "csv_stage")
    if csv_stage != "upload":
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".csv"):
        await update.message.reply_text("📁 Please upload a CSV file.")
        return
    if doc.file_size and doc.file_size > MAX_CSV_SIZE:
        await update.message.reply_text(f"⚠️ CSV file too large (max {MAX_CSV_SIZE // (1024*1024)}MB).")
        return
    file = await doc.get_file()
    content = await file.download_as_bytearray()
    headers, data = parse_csv_file(bytes(content))
    if not headers:
        await update.message.reply_text("⚠️ Could not parse CSV.")
        return
    state.set(user_id, "csv_headers", headers)
    state.set(user_id, "csv_data", data)
    state.set(user_id, "csv_mapping", {})
    state.set(user_id, "csv_stage", "map_username")
    buttons = [[InlineKeyboardButton(h, callback_data=f"csvcol:{i}")] for i, h in enumerate(headers)]
    await update.message.reply_text(
        f"<b>CSV Columns Detected:</b> {', '.join(headers)}\n\n"
        "Which column is the <b>Reddit username</b>?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
