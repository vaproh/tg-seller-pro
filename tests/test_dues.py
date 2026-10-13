"""Tests for admin-editable dues + seller notification."""
import asyncio
from database import add_seller
from database.dues import get_dues_balance
from handlers.dues import _find_seller, _is_amount, duesadd_cmd
from utils.notifications import fmt_dues_update, notify_seller_dues_edit


class FakeBot:
    def __init__(self, fail_on=None):
        self.sent = []
        self.fail_on = fail_on

    async def send_message(self, chat_id, text, parse_mode=None):
        if self.fail_on is not None and chat_id == self.fail_on:
            raise RuntimeError("blocked")
        self.sent.append((chat_id, text))


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, user_id=12345, chat_id=None):
        self.effective_user = FakeUser(user_id)
        self.effective_chat = FakeChat(chat_id if chat_id is not None else user_id)
        self.message = FakeMessage()


class FakeContext:
    def __init__(self, args=None, bot=None):
        self.args = args or []
        self.bot = bot or FakeBot()
        self.user_data = {}


class TestFindSeller:
    def test_match_with_at_prefix(self, isolated_db):
        add_seller(999, "TestSeller", 12345)
        assert _find_seller("@testseller")["user_id"] == 999

    def test_unknown_returns_none(self, isolated_db):
        assert _find_seller("@nobody") is None


class TestIsAmount:
    def test_number(self):
        assert _is_amount("500") is True

    def test_name(self):
        assert _is_amount("@seller") is False


class TestDuesUpdateNotification:
    def test_format_shows_sign_and_balance(self):
        msg = fmt_dues_update("add", 500, "late fee", 1500)
        assert "+" in msg and "1500" in msg

    def test_seller_dmed_on_success(self, isolated_db):
        bot = FakeBot()
        ok = asyncio.run(notify_seller_dues_edit(
            FakeUpdate(), FakeContext(bot=bot),
            {"user_id": 999, "name": "TestSeller"}, "add", 500, "x", 500,
        ))
        assert ok is True
        assert bot.sent[0][0] == 999

    def test_visible_fallback_when_dm_fails(self, isolated_db):
        bot = FakeBot(fail_on=999)
        ok = asyncio.run(notify_seller_dues_edit(
            FakeUpdate(), FakeContext(bot=bot),
            {"user_id": 999, "name": "TestSeller"}, "add", 500, "x", 500,
        ))
        assert ok is False
        assert bot.sent[0][0] == 12345  # admin's own chat


class TestDuesAddCommand:
    def test_admin_adds_for_seller_and_notifies(self, isolated_db):
        add_seller(999, "TestSeller", 12345)
        ctx = FakeContext(args=["@TestSeller", "500", "late", "fee"])
        asyncio.run(duesadd_cmd(FakeUpdate(), ctx))
        seller_id = _find_seller("TestSeller")["id"]
        assert get_dues_balance(seller_id) == 500
        assert [c for c, _ in ctx.bot.sent] == [999]

    def test_admin_without_seller_name_gets_usage(self, isolated_db):
        add_seller(999, "TestSeller", 12345)
        ctx = FakeContext(args=["500"])
        update = FakeUpdate()
        asyncio.run(duesadd_cmd(update, ctx))
        assert "Usage" in update.message.replies[0]
        assert ctx.bot.sent == []

    def test_seller_adds_own_and_is_not_notified(self, isolated_db):
        add_seller(555, "SelfSeller", 12345)
        ctx = FakeContext(args=["500", "late", "fee"])
        asyncio.run(duesadd_cmd(FakeUpdate(user_id=555), ctx))
        seller_id = _find_seller("SelfSeller")["id"]
        assert get_dues_balance(seller_id) == 500
        assert ctx.bot.sent == []
