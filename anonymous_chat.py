"""Anonymous one-to-one chat and gender-aware matchmaking for GLADIATOR GAMES.
All matching, profile, session and reporting logic lives in this module so the
actual game-discovery handlers remain separate. No chat content is sent to the
admin or stored in SQLite; Telegram messages are copied to the matched partner.
"""
from __future__ import annotations
import html
import logging
import time
import uuid
from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes
import anonymous_chat_database as chat_db
logger = logging.getLogger(__name__)
SendUIText = Callable[..., Any]
# Basic anti-spam protection, stored in memory; it resets on process restart.
_MESSAGE_TIMES: dict[int, deque[float]] = defaultdict(deque)
MAX_MESSAGES_PER_MINUTE = 25
# Chat log: message text/captions and attachment metadata are appended to this TXT file.
_CHAT_LOG_PATH = Path(__file__).resolve().parent / "data" / "chat_logs.txt"
_ACTIVE_AUDIT_CONVERSATIONS: dict[tuple[str, int, int], str] = {}
def _audit_key(mode: str, user_a: int, user_b: int) -> tuple[str, int, int]:
    low, high = sorted((int(user_a), int(user_b)))
    return str(mode), low, high
def _get_audit_conversation_id(mode: str, user_a: int, user_b: int) -> str:
    """Return a shared identifier for a pair; no message content is retained."""
    key = _audit_key(mode, user_a, user_b)
    conversation_id = _ACTIVE_AUDIT_CONVERSATIONS.get(key)
    if conversation_id is None:
        prefix = "RANDOM" if mode == "random" else "FRIEND"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        conversation_id = f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"
        _ACTIVE_AUDIT_CONVERSATIONS[key] = conversation_id
    return conversation_id
def _finish_audit_conversation(mode: str, user_a: int, user_b: int) -> None:
    _ACTIVE_AUDIT_CONVERSATIONS.pop(_audit_key(mode, user_a, user_b), None)
def _write_chat_audit_event(
    sender_id: int,
    recipient_id: int,
    mode: str,
    message_type: str,
    status: str,
    conversation_id: str | None = None,
    content: str | None = None,
) -> None:
    """Append chat delivery metadata and text/caption/attachment details to the TXT log."""
    try:
        conversation_id = conversation_id or _get_audit_conversation_id(
            mode, sender_id, recipient_id
        )
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = (
            f"[{timestamp}]\n"
            f"conversation_id: {conversation_id}\n"
            f"mode: {mode}\n"
            f"sender_user_id: {int(sender_id)}\n"
            f"recipient_user_id: {int(recipient_id)}\n"
            f"message_type: {message_type}\n"
            f"status: {status}\n"
            f"message_content_and_attachment_details:\n{content or '[no text/caption]'}\n"
            f"{'-' * 40}\n"
        )
        with _CHAT_LOG_PATH.open("a", encoding="utf-8", newline="\n") as log_file:
            log_file.write(entry)
    except OSError:
        # Audit storage failure must not interrupt the chat itself.
        logger.warning("Could not write metadata-only chat audit event.", exc_info=True)
def _get_message_type(message) -> str:
    """Classify a Telegram message without inspecting or storing its content."""
    for attr, label in (
        ("photo", "photo"),
        ("video", "video"),
        ("animation", "animation"),
        ("voice", "voice"),
        ("video_note", "video_note"),
        ("audio", "audio"),
        ("document", "document"),
        ("sticker", "sticker"),
        ("contact", "contact"),
        ("location", "location"),
        ("venue", "venue"),
        ("poll", "poll"),
    ):
        if getattr(message, attr, None) is not None:
            return label
    return "other_media"

def _get_message_log_content(message) -> str:
    """Return readable message text plus available Telegram attachment details for the TXT log."""
    parts: list[str] = []
    text = getattr(message, "text", None)
    caption = getattr(message, "caption", None)
    if text:
        parts.append(f"text: {text}")
    if caption:
        parts.append(f"caption: {caption}")

    # Record attachment identifiers and basic metadata, not the binary file itself.
    for attr in ("photo", "video", "animation", "voice", "video_note", "audio", "document", "sticker"):
        value = getattr(message, attr, None)
        if value is None:
            continue
        media = value[-1] if attr == "photo" and isinstance(value, (list, tuple)) and value else value
        if isinstance(media, (list, tuple)):
            media = media[-1] if media else None
        if media is None:
            continue
        details = [f"attachment_type: {attr}"]
        for field in ("file_id", "file_unique_id", "file_name", "mime_type", "duration", "file_size", "width", "height", "emoji"):
            field_value = getattr(media, field, None)
            if field_value is not None:
                details.append(f"{field}: {field_value}")
        parts.append("\n".join(details))

    contact = getattr(message, "contact", None)
    if contact is not None:
        for field in ("phone_number", "first_name", "last_name", "user_id", "vcard"):
            value = getattr(contact, field, None)
            if value is not None:
                parts.append(f"contact_{field}: {value}")

    location = getattr(message, "location", None)
    if location is not None:
        parts.append(f"location: latitude={getattr(location, 'latitude', None)}, longitude={getattr(location, 'longitude', None)}")

    venue = getattr(message, "venue", None)
    if venue is not None:
        parts.append(f"venue: title={getattr(venue, 'title', None)}, address={getattr(venue, 'address', None)}")

    poll = getattr(message, "poll", None)
    if poll is not None:
        question = getattr(poll, "question", None)
        options = getattr(poll, "options", None)
        parts.append(f"poll_question: {question}")
        if options:
            parts.append("poll_options: " + " | ".join(str(getattr(option, 'text', option)) for option in options))

    return "\n".join(parts) if parts else "[no text/caption; attachment details unavailable]"

GENDER_LABELS = {"female": "دختر", "male": "پسر"}
PREFERENCE_LABELS = {"female": "دخترها", "male": "پسرها", "any": "فرقی ندارد"}
def is_configured() -> bool:
    """Compatibility check used by the main bot to enable anonymous chat.
    Random matchmaking uses the main bot's existing Telegram application/token;
    it does not require a separate admin ID or a second bot token.
    """
    return True
def init_db() -> None:
    chat_db.init_db()
def _chat_home_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 شروع جست‌وجو", callback_data="chat:search")],
        [InlineKeyboardButton("⚧ انتخاب جنسیت مخاطب", callback_data="chat:preferences")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="chat:profile")],
        [InlineKeyboardButton("🤝 دوستان من", callback_data="chat:friends")],
        [InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="anonymous_cancel")],
    ])
def _profile_gender_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👩 دختر", callback_data="chat:profile_gender:female")],
        [InlineKeyboardButton("👨 پسر", callback_data="chat:profile_gender:male")],
        [InlineKeyboardButton("لغو", callback_data="chat:cancel_flow")],
    ])
def _preference_markup(prefix: str = "chat:profile_preference") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👩 چت با دخترها", callback_data=f"{prefix}:female")],
        [InlineKeyboardButton("👨 چت با پسرها", callback_data=f"{prefix}:male")],
        [InlineKeyboardButton("🎲 فرقی ندارد", callback_data=f"{prefix}:any")],
        [InlineKeyboardButton("لغو", callback_data="chat:cancel_flow")],
    ])
def _chat_controls_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏭ نفر بعدی", callback_data="chat:next"),
            InlineKeyboardButton("🛑 پایان چت", callback_data="chat:end"),
        ],
        [InlineKeyboardButton("🤝 درخواست دوستی", callback_data="chat:friend_request")],
        [InlineKeyboardButton("🚩 گزارش و قطع ارتباط", callback_data="chat:report")],
    ])
def _friend_request_markup(requester_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ قبول دوستی", callback_data=f"chat:friend_accept:{int(requester_id)}")],
        [InlineKeyboardButton("❌ رد درخواست", callback_data=f"chat:friend_decline:{int(requester_id)}")],
    ])
def _friends_markup(friends: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for friend in friends[:50]:
        friend_id = int(friend["user_id"])
        name = str(friend.get("display_name") or "دوست")[:25]
        rows.append([InlineKeyboardButton(f"💬 {name}", callback_data=f"chat:friend_chat:{friend_id}")])
        rows.append([InlineKeyboardButton(f"🗑 حذف {name}", callback_data=f"chat:friend_remove:{friend_id}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="chat:home")])
    return InlineKeyboardMarkup(rows)
def _friend_chat_markup(friend_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏹ پایان پیام به دوست", callback_data="chat:friend_chat_stop")],
        [InlineKeyboardButton("👥 فهرست دوستان", callback_data="chat:friends")],
    ])
def _waiting_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو جست‌وجو", callback_data="chat:stop_search")],
        [InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="anonymous_cancel")],
    ])
def _main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 بخش بازی‌ها", callback_data="games_section")],
        [InlineKeyboardButton("💬 گفت‌وگوی ناشناس", callback_data="anonymous_chat")],
    ])
async def _send_ui(message, context, send_ui_text: SendUIText | None, text: str, **kwargs):
    if send_ui_text:
        return await send_ui_text(message, context, text, **kwargs)
    return await context.bot.send_message(chat_id=message.chat_id, text=text, **kwargs)
async def _delete_saved_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, field: str) -> None:
    profile = chat_db.get_profile(int(user_id))
    if not profile:
        return
    message_id = profile.get(field)
    if message_id:
        try:
            await context.bot.delete_message(chat_id=int(user_id), message_id=int(message_id))
        except TelegramError:
            # It may already have been removed by the main UI's screen cleanup.
            pass
        if field == "waiting_message_id":
            chat_db.clear_waiting_message_id(user_id)
        elif field == "session_message_id":
            chat_db.clear_session_message_id(user_id)
async def _send_to_user(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str,
                        reply_markup: InlineKeyboardMarkup | None = None):
    """Send a chat status/card and remember it so old control keyboards are removed."""
    try:
        await _delete_saved_message(context, user_id, "session_message_id")
        sent = await context.bot.send_message(chat_id=int(user_id), text=text, reply_markup=reply_markup,
                                              parse_mode="HTML")
        chat_db.set_session_message_id(user_id, sent.message_id)
        return sent
    except (Forbidden, TelegramError):
        logger.info("Could not notify chat user (details intentionally omitted).")
        return None
async def _delete_waiting_card(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    await _delete_saved_message(context, user_id, "waiting_message_id")
def _message_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    bucket = _MESSAGE_TIMES[int(user_id)]
    while bucket and now - bucket[0] >= 60:
        bucket.popleft()
    if len(bucket) >= MAX_MESSAGES_PER_MINUTE:
        return True
    bucket.append(now)
    return False
def _profile_description(profile: dict[str, Any]) -> str:
    # The selected display name and city are shown to a match. Telegram ID and
    # username are never shown. We explicitly advise users to use a nickname.
    name = html.escape(str(profile.get("display_name") or "کاربر"))
    gender = GENDER_LABELS.get(str(profile.get("gender")), "نامشخص")
    city = html.escape(str(profile.get("city") or "نامشخص"))
    return f"👤 نام نمایشی: {name}\n⚧ جنسیت: {gender}\n📍 شهر: {city}"
async def _show_home(message, context, send_ui_text: SendUIText | None, user_id: int,
                     notice: str | None = None):
    await _delete_saved_message(context, user_id, "session_message_id")
    profile = chat_db.get_profile(user_id)
    if not profile:
        await _begin_profile(message, context, send_ui_text)
        return
    preference = PREFERENCE_LABELS.get(str(profile.get("preference")), "فرقی ندارد")
    text = (
        "💬 <b>چت ناشناس</b>\n\n"
        f"{_profile_description(profile)}\n"
        f"🎯 مخاطب دلخواه: {preference}\n\n"
        "با «شروع جست‌وجو» وارد صف کاربران آمادهٔ گفت‌وگو می‌شوید. "
        "وقتی کاربری با تنظیمات سازگار هم‌زمان در صف باشد، به هم وصل می‌شوید."
    )
    if notice:
        text = f"{html.escape(notice)}\n\n{text}"
    await _send_ui(message, context, send_ui_text, text, parse_mode="HTML", reply_markup=_chat_home_markup())
async def _begin_profile(message, context, send_ui_text: SendUIText | None):
    existing = chat_db.get_profile(message.chat_id)
    # This module is used only in private bot chats, so chat_id is the Telegram user ID.
    context.user_data["chat_profile_form"] = {}
    context.user_data["chat_profile_step"] = "name"
    prompt = (
        "👤 <b>ساخت پروفایل چت ناشناس</b>\n\n"
        "لطفاً یک نام نمایشی وارد کنید (۲ تا ۳۵ نویسه). پیشنهاد می‌کنیم از نام مستعار استفاده کنید.\n\n"
        "نکتهٔ حریم خصوصی: نام نمایشی، جنسیت و شهری که وارد می‌کنید به مخاطب گفت‌وگو نمایش داده می‌شود؛ "
        "آیدی تلگرام و نام کاربری شما نمایش داده نخواهد شد. "
        "برای رسیدگی به مشکلات و سوءاستفاده، متن پیام‌ها، کپشن‌ها و مشخصات رسانه‌ها در فایل گزارش ربات ثبت می‌شود؛ "
        "خود فایل عکس یا ویدیو داخل فایل متنی ذخیره نمی‌شود."
    )
    if existing:
        context.user_data["chat_profile_form"] = {
            "name": existing["display_name"],
            "gender": existing["gender"],
            "city": existing["city"],
            "preference": existing["preference"],
        }
    await _send_ui(message, context, send_ui_text, prompt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("لغو", callback_data="chat:cancel_flow")]
    ]))
async def enter_section(update: Update, context: ContextTypes.DEFAULT_TYPE, send_ui_text: SendUIText | None = None):
    query = update.callback_query
    await query.answer()
    user_id = int(query.from_user.id)
    context.user_data["anonymous_mode"] = True
    context.user_data["waiting_for_search"] = False
    profile = chat_db.get_profile(user_id)
    if not profile:
        await _begin_profile(query.message, context, send_ui_text)
    else:
        await _show_home(query.message, context, send_ui_text, user_id)
async def leave_current_session(user_id: int, context: ContextTypes.DEFAULT_TYPE,
                                notice: str = "مخاطب از گفت‌وگوی ناشناس خارج شد.") -> int | None:
    await _delete_saved_message(context, user_id, "session_message_id")
    await _delete_saved_message(context, user_id, "waiting_message_id")
    partner_id = chat_db.get_partner_id(int(user_id))
    if partner_id is not None:
        conversation_id = _get_audit_conversation_id("random", user_id, partner_id)
        _write_chat_audit_event(
            user_id, partner_id, "random", "session_ended", "ended", conversation_id
        )
        _finish_audit_conversation("random", user_id, partner_id)
    partner_id = chat_db.end_chat(int(user_id), remember_pair=True)
    if partner_id is not None:
        await _send_to_user(
            context, partner_id,
            "🛑 گفت‌وگو پایان یافت. می‌توانید از منوی چت ناشناس دوباره جست‌وجو کنید.",
            reply_markup=_chat_home_markup(),
        )
    return partner_id
async def leave_to_main(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await leave_current_session(user_id, context)
async def _start_search(message, context, send_ui_text: SendUIText | None, user_id: int):
    await _delete_saved_message(context, user_id, "session_message_id")
    await _delete_saved_message(context, user_id, "waiting_message_id")
    profile = chat_db.get_profile(user_id)
    if not profile:
        await _begin_profile(message, context, send_ui_text)
        return
    existing_partner = chat_db.get_partner_id(user_id)
    if existing_partner is not None:
        await _send_ui(message, context, send_ui_text,
                       "✅ شما در حال حاضر به یک نفر متصل هستید. از دکمه‌های زیر استفاده کنید.",
                       reply_markup=_chat_controls_markup())
        return
    try:
        partner_id = chat_db.find_match_or_queue(user_id)
    except Exception:
        logger.exception("Anonymous matchmaking failed")
        await _send_ui(message, context, send_ui_text,
                       "❌ فعلاً جست‌وجو انجام نشد. لطفاً دوباره تلاش کنید.",
                       reply_markup=_chat_home_markup())
        return
    if partner_id is None:
        waiting_message = await _send_ui(
            message, context, send_ui_text,
            "🔎 در حال جست‌وجوی مخاطب سازگار هستید.\n\n"
            "وقتی کاربری با جنسیت و ترجیح متقابل شما وارد صف شود، گفت‌وگو خودکار شروع می‌شود. "
            "در این ربات، «آماده بودن» یعنی کاربر دکمهٔ جست‌وجو را زده است؛ وضعیت آنلاین تلگرام قابل مشاهده نیست.",
            reply_markup=_waiting_markup(),
        )
        if waiting_message and getattr(waiting_message, "message_id", None):
            chat_db.set_waiting_message_id(user_id, waiting_message.message_id)
        return
    own = chat_db.get_profile(user_id)
    partner = chat_db.get_profile(partner_id)
    if not own or not partner:
        await chat_db.end_chat(user_id, remember_pair=False)
        await _send_ui(message, context, send_ui_text, "❌ پروفایل مخاطب در دسترس نیست. لطفاً دوباره جست‌وجو کنید.", reply_markup=_chat_home_markup())
        return
    # Notify both users in their own private bot conversation. Message contents
    # are never routed to the administrator.
    await _delete_waiting_card(context, user_id)
    await _delete_waiting_card(context, partner_id)
    own_intro = (
        "✅ <b>مخاطب پیدا شد!</b> گفت‌وگوی شما آغاز شد.\n\n"
        f"{_profile_description(partner)}\n\n"
        "پیام‌هایتان مستقیماً به هم می‌رسند؛ آیدی و نام کاربری تلگرام نمایش داده نمی‌شود. "
        "متن پیام‌ها، کپشن‌ها و مشخصات رسانه‌ها در فایل گزارش ربات ثبت می‌شود."
    )
    partner_intro = (
        "✅ <b>مخاطب پیدا شد!</b> گفت‌وگوی شما آغاز شد.\n\n"
        f"{_profile_description(own)}\n\n"
        "پیام‌هایتان مستقیماً به هم می‌رسند؛ آیدی و نام کاربری تلگرام نمایش داده نمی‌شود. "
        "متن پیام‌ها، کپشن‌ها و مشخصات رسانه‌ها در فایل گزارش ربات ثبت می‌شود."
    )
    conversation_id = _get_audit_conversation_id("random", user_id, partner_id)
    sent_own = await _send_to_user(context, user_id, own_intro, _chat_controls_markup())
    sent_partner = await _send_to_user(context, partner_id, partner_intro, _chat_controls_markup())
    if sent_own and sent_partner:
        _write_chat_audit_event(
            user_id, partner_id, "random", "session_started", "success", conversation_id
        )
    else:
        _write_chat_audit_event(
            user_id, partner_id, "random", "session_started", "failure", conversation_id
        )
        _finish_audit_conversation("random", user_id, partner_id)
    if not sent_own or not sent_partner:
        await chat_db.end_chat(user_id, remember_pair=False)
        if sent_own:
            await _send_to_user(context, user_id, "⚠️ اتصال قطع شد؛ لطفاً دوباره جست‌وجو کنید.", _chat_home_markup())
        if sent_partner:
            await _send_to_user(context, partner_id, "⚠️ اتصال قطع شد؛ لطفاً دوباره جست‌وجو کنید.", _chat_home_markup())
async def _finish_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE,
                       reason: str = "end", requeue: bool = False,
                       send_ui_message=None, send_ui_text: SendUIText | None = None):
    await _delete_saved_message(context, user_id, "session_message_id")
    await _delete_saved_message(context, user_id, "waiting_message_id")
    partner_before_end = chat_db.get_partner_id(int(user_id))
    if partner_before_end is not None:
        conversation_id = _get_audit_conversation_id("random", user_id, partner_before_end)
        _write_chat_audit_event(
            user_id, partner_before_end, "random", "session_ended", "ended", conversation_id
        )
        _finish_audit_conversation("random", user_id, partner_before_end)
    partner_id = chat_db.end_chat(int(user_id), remember_pair=True)
    if partner_id is not None:
        reason_text = {
            "next": "⏭ مخاطب شما نفر بعدی را انتخاب کرد؛ گفت‌وگو پایان یافت.",
            "report": "🚩 گفت‌وگو توسط مخاطب پایان یافت.",
            "end": "🛑 مخاطب گفت‌وگو را پایان داد.",
            "edit": "گفت‌وگو برای ویرایش پروفایل پایان یافت.",
        }.get(reason, "🛑 گفت‌وگو پایان یافت.")
        await _send_to_user(context, partner_id, reason_text, _chat_home_markup())
    user_data = context.user_data
    user_data["anonymous_mode"] = True
    user_data["waiting_for_search"] = False
    if requeue and send_ui_message is not None:
        await _start_search(send_ui_message, context, send_ui_text, user_id)
    elif send_ui_message is not None:
        await _show_home(send_ui_message, context, send_ui_text, user_id,
                         notice="گفت‌وگو پایان یافت." if reason != "report" else "گزارش ثبت شد و گفت‌وگو پایان یافت.")
async def _handle_profile_text(message, context, send_ui_text: SendUIText | None, user_id: int):
    step = context.user_data.get("chat_profile_step")
    text = (message.text or "").strip()
    if step == "name":
        if len(text) < 2 or len(text) > 35:
            await _send_ui(message, context, send_ui_text, "نام نمایشی باید بین ۲ تا ۳۵ نویسه باشد. لطفاً دوباره وارد کنید.")
            return True
        context.user_data.setdefault("chat_profile_form", {})["name"] = text
        context.user_data["chat_profile_step"] = "gender"
        await _send_ui(message, context, send_ui_text, "لطفاً جنسیت خود را انتخاب کنید:", reply_markup=_profile_gender_markup())
        return True
    if step == "city":
        if len(text) < 2 or len(text) > 70:
            await _send_ui(message, context, send_ui_text, "نام شهر باید بین ۲ تا ۷۰ نویسه باشد. لطفاً دوباره وارد کنید.")
            return True
        context.user_data.setdefault("chat_profile_form", {})["city"] = text
        context.user_data["chat_profile_step"] = "preference"
        await _send_ui(message, context, send_ui_text, "دوست دارید با چه جنسیتی گفت‌وگو کنید؟", reply_markup=_preference_markup())
        return True
    if step == "gender":
        await _send_ui(message, context, send_ui_text, "لطفاً جنسیت را با یکی از دکمه‌های زیر انتخاب کنید:", reply_markup=_profile_gender_markup())
        return True
    if step == "preference":
        await _send_ui(message, context, send_ui_text, "لطفاً جنسیت مخاطب را با یکی از گزینه‌های زیر انتخاب کنید:", reply_markup=_preference_markup())
        return True
    return False
async def handle_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           send_ui_text: SendUIText | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not message.text or not user:
        return
    user_id = int(user.id)
    context.user_data["anonymous_mode"] = True
    if await _handle_profile_text(message, context, send_ui_text, user_id):
        return
    friend_target = context.user_data.get("friend_chat_target")
    if friend_target is not None:
        friend_target = int(friend_target)
        if not chat_db.are_friends(user_id, friend_target):
            context.user_data.pop("friend_chat_target", None)
            await _send_ui(message, context, send_ui_text, "این کاربر دیگر در فهرست دوستان شما نیست.", reply_markup=_chat_home_markup())
            return
        if _message_rate_limited(user_id):
            await _send_ui(message, context, send_ui_text, "⚠️ پیام‌ها خیلی سریع ارسال می‌شوند. کمی آهسته‌تر پیام بدهید.")
            return
        try:
            await context.bot.send_message(
                chat_id=friend_target,
                text=f"💌 پیام از دوست شما، {html.escape(str(chat_db.get_profile(user_id).get('display_name') or 'دوست'))}:",
                parse_mode="HTML",
            )
            await context.bot.send_message(chat_id=friend_target, text=message.text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ پاسخ به دوست", callback_data=f"chat:friend_chat:{user_id}")]]))
            _write_chat_audit_event(user_id, friend_target, "friend", "text", "success", content=_get_message_log_content(message))
        except TelegramError:
            _write_chat_audit_event(user_id, friend_target, "friend", "text", "failure", content=_get_message_log_content(message))
            await _send_ui(message, context, send_ui_text, "ارسال پیام انجام نشد. ممکن است دوستتان ربات را مسدود کرده باشد.")
        return
    partner_id = chat_db.get_partner_id(user_id)
    if partner_id is not None:
        if _message_rate_limited(user_id):
            await _send_ui(message, context, send_ui_text, "⚠️ پیام‌ها خیلی سریع ارسال می‌شوند. کمی آهسته‌تر پیام بدهید.")
            return
        try:
            await context.bot.send_message(chat_id=partner_id, text=message.text)
            _write_chat_audit_event(user_id, partner_id, "random", "text", "success", content=_get_message_log_content(message))
        except TelegramError:
            _write_chat_audit_event(user_id, partner_id, "random", "text", "failure", content=_get_message_log_content(message))
            logger.info("Could not relay a text message to the active partner.")
            await chat_db.end_chat(user_id, remember_pair=False)
            await _send_ui(message, context, send_ui_text,
                           "⚠️ ارتباط قطع شد. لطفاً دوباره جست‌وجو کنید.", reply_markup=_chat_home_markup())
        return
    if chat_db.is_searching(user_id):
        await _send_ui(message, context, send_ui_text,
                       "🔎 هنوز در صف جست‌وجو هستید. پس از پیدا شدن مخاطب می‌توانید پیام بدهید.",
                       reply_markup=_waiting_markup())
        return
    if not chat_db.get_profile(user_id):
        await _begin_profile(message, context, send_ui_text)
    else:
        await _send_ui(message, context, send_ui_text,
                       "برای شروع گفت‌وگو، دکمهٔ «شروع جست‌وجو» را از منوی چت ناشناس انتخاب کنید.",
                       reply_markup=_chat_home_markup())
async def handle_user_media(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            send_ui_text: SendUIText | None = None) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    user_id = int(user.id)
    if context.user_data.get("chat_profile_step"):
        await _send_ui(message, context, send_ui_text, "برای تکمیل پروفایل لطفاً نام یا شهر را به‌صورت متن وارد کنید یا دکمه‌های انتخاب را بزنید.")
        return
    friend_target = context.user_data.get("friend_chat_target")
    if friend_target is not None:
        friend_target = int(friend_target)
        if not chat_db.are_friends(user_id, friend_target):
            context.user_data.pop("friend_chat_target", None)
            await _send_ui(message, context, send_ui_text, "این کاربر دیگر در فهرست دوستان شما نیست.", reply_markup=_chat_home_markup())
            return
        if _message_rate_limited(user_id):
            await _send_ui(message, context, send_ui_text, "⚠️ پیام‌ها خیلی سریع ارسال می‌شوند. کمی آهسته‌تر تلاش کنید.")
            return
        try:
            await context.bot.send_message(chat_id=friend_target,
                text=f"💌 فایل یا رسانه از دوست شما، {html.escape(str(chat_db.get_profile(user_id).get('display_name') or 'دوست'))}:",
                parse_mode="HTML")
            await context.bot.copy_message(chat_id=friend_target, from_chat_id=message.chat_id,
                message_id=message.message_id,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ پاسخ به دوست", callback_data=f"chat:friend_chat:{user_id}")]]))
            _write_chat_audit_event(user_id, friend_target, "friend", _get_message_type(message), "success", content=_get_message_log_content(message))
        except TelegramError:
            _write_chat_audit_event(user_id, friend_target, "friend", _get_message_type(message), "failure", content=_get_message_log_content(message))
            await _send_ui(message, context, send_ui_text, "ارسال رسانه انجام نشد. ممکن است دوستتان ربات را مسدود کرده باشد.")
        return
    partner_id = chat_db.get_partner_id(user_id)
    if partner_id is None:
        if chat_db.is_searching(user_id):
            await _send_ui(message, context, send_ui_text, "🔎 هنوز مخاطبی پیدا نشده؛ پس از اتصال می‌توانید عکس یا فایل بفرستید.", reply_markup=_waiting_markup())
        else:
            await _send_ui(message, context, send_ui_text, "برای ارسال فایل، ابتدا از منوی چت ناشناس جست‌وجو را شروع کنید.", reply_markup=_chat_home_markup())
        return
    if _message_rate_limited(user_id):
        await _send_ui(message, context, send_ui_text, "⚠️ پیام‌ها خیلی سریع ارسال می‌شوند. کمی آهسته‌تر تلاش کنید.")
        return
    try:
        # copy_message creates a new message without forwarding attribution.
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        _write_chat_audit_event(user_id, partner_id, "random", _get_message_type(message), "success", content=_get_message_log_content(message))
    except TelegramError:
        _write_chat_audit_event(user_id, partner_id, "random", _get_message_type(message), "failure", content=_get_message_log_content(message))
        logger.info("Could not relay a media message to the active partner.")
        await chat_db.end_chat(user_id, remember_pair=False)
        await _send_ui(message, context, send_ui_text, "⚠️ ارسال فایل انجام نشد و ارتباط قطع شد. لطفاً دوباره جست‌وجو کنید.", reply_markup=_chat_home_markup())
async def _start_profile_callback(query, context, send_ui_text: SendUIText | None, user_id: int):
    await leave_current_session(user_id, context, notice="")
    context.user_data["chat_profile_form"] = {}
    context.user_data["chat_profile_step"] = "name"
    context.user_data["anonymous_mode"] = True
    await _begin_profile(query.message, context, send_ui_text)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          send_ui_text: SendUIText | None = None) -> bool:
    query = update.callback_query
    if not query or not (query.data or "").startswith("chat:"):
        return False
    await query.answer()
    user_id = int(query.from_user.id)
    data = query.data or ""
    context.user_data["anonymous_mode"] = True
    context.user_data["waiting_for_search"] = False
    if data == "chat:home":
        await _show_home(query.message, context, send_ui_text, user_id)
        return True
    if data == "chat:friends":
        context.user_data.pop("friend_chat_target", None)
        friends = chat_db.list_friends(user_id)
        if not friends:
            await _send_ui(query.message, context, send_ui_text,
                           "🤝 هنوز دوستی ندارید. هنگام گفت‌وگوی ناشناس، «درخواست دوستی» را بزنید؛ اگر طرف مقابل قبول کند، در این فهرست اضافه می‌شود.",
                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="chat:home")]]))
        else:
            lines = ["🤝 <b>دوستان شما</b>", "برای شروع گفت‌وگوی دوباره، نام دوست را انتخاب کنید:"]
            for friend in friends[:50]:
                lines.append(f"• {html.escape(str(friend.get('display_name') or 'دوست'))} — {GENDER_LABELS.get(str(friend.get('gender')), 'نامشخص')}، {html.escape(str(friend.get('city') or ''))}")
            await _send_ui(query.message, context, send_ui_text, "\n".join(lines), parse_mode="HTML", reply_markup=_friends_markup(friends))
        return True
    if data == "chat:friend_request":
        partner_id = chat_db.get_partner_id(user_id)
        if partner_id is None:
            await _send_ui(query.message, context, send_ui_text, "برای درخواست دوستی باید ابتدا به یک کاربر وصل شوید.", reply_markup=_chat_home_markup())
            return True
        result = chat_db.create_friend_request(user_id, partner_id)
        if result == "created":
            profile = chat_db.get_profile(user_id) or {}
            sender_name = html.escape(str(profile.get("display_name") or "کاربر"))
            try:
                await context.bot.send_message(chat_id=partner_id,
                    text=f"🤝 <b>{sender_name}</b> از شما درخواست دوستی دارد. اگر قبول کنید، در فهرست دوستان یکدیگر قرار می‌گیرید و بعداً می‌توانید دوباره پیام بدهید.",
                    parse_mode="HTML", reply_markup=_friend_request_markup(user_id))
                await _send_ui(query.message, context, send_ui_text, "✅ درخواست دوستی ارسال شد. پس از قبول طرف مقابل، در فهرست دوستان هم قرار می‌گیرید.")
            except TelegramError:
                await _send_ui(query.message, context, send_ui_text, "درخواست ذخیره شد، اما پیام به مخاطب نرسید. لطفاً بعداً دوباره تلاش کنید.")
        elif result == "pending":
            await _send_ui(query.message, context, send_ui_text, "درخواست دوستی شما قبلاً ارسال شده و هنوز پاسخ داده نشده است.")
        elif result == "friends":
            await _send_ui(query.message, context, send_ui_text, "شما از قبل دوست هستید؛ از بخش «دوستان من» پیام بدهید.")
        else:
            await _send_ui(query.message, context, send_ui_text, "امکان ارسال درخواست دوستی وجود ندارد.")
        return True
    if data.startswith("chat:friend_accept:") or data.startswith("chat:friend_decline:"):
        try:
            requester_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await _send_ui(query.message, context, send_ui_text, "درخواست نامعتبر است.")
            return True
        accept = data.startswith("chat:friend_accept:")
        ok = chat_db.respond_friend_request(user_id, requester_id, accept)
        if not ok:
            await _send_ui(query.message, context, send_ui_text, "این درخواست دیگر فعال نیست.")
            return True
        if accept:
            own = chat_db.get_profile(user_id) or {}
            try:
                await context.bot.send_message(chat_id=requester_id,
                    text=f"✅ درخواست دوستی شما توسط {html.escape(str(own.get('display_name') or 'دوست'))} پذیرفته شد. حالا می‌توانید از بخش «دوستان من» دوباره پیام بدهید.",
                    parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 باز کردن دوستان", callback_data="chat:friends")]]))
            except TelegramError:
                pass
            await _send_ui(query.message, context, send_ui_text, "✅ درخواست پذیرفته شد؛ این کاربر به فهرست دوستان شما اضافه شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 دوستان من", callback_data="chat:friends")]]))
        else:
            try:
                await context.bot.send_message(chat_id=requester_id, text="درخواست دوستی شما پذیرفته نشد.")
            except TelegramError:
                pass
            await _send_ui(query.message, context, send_ui_text, "درخواست دوستی رد شد.")
        return True
    if data.startswith("chat:friend_chat:"):
        try:
            friend_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await _send_ui(query.message, context, send_ui_text, "دوست انتخاب‌شده معتبر نیست.")
            return True
        if not chat_db.are_friends(user_id, friend_id):
            await _send_ui(query.message, context, send_ui_text, "این کاربر در فهرست دوستان شما نیست.", reply_markup=_chat_home_markup())
            return True
        if chat_db.get_partner_id(user_id) is not None:
            await leave_current_session(user_id, context)
        chat_db.stop_search(user_id)
        context.user_data["friend_chat_target"] = friend_id
        friend = chat_db.get_profile(friend_id) or {}
        await _send_ui(query.message, context, send_ui_text,
            f"💌 اکنون می‌توانید به دوستتان «{html.escape(str(friend.get('display_name') or 'دوست'))}» پیام بدهید. پیام‌ها فقط بین حساب‌های شما و دوستتان ارسال می‌شوند. برای پایان، دکمهٔ زیر را بزنید.",
            parse_mode="HTML", reply_markup=_friend_chat_markup(friend_id))
        try:
            own = chat_db.get_profile(user_id) or {}
            await context.bot.send_message(chat_id=friend_id,
                text=f"💌 دوست شما، {html.escape(str(own.get('display_name') or 'دوست'))}، می‌خواهد با شما گفت‌وگو کند.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ پاسخ به دوست", callback_data=f"chat:friend_chat:{user_id}")]]))
        except TelegramError:
            pass
        return True
    if data == "chat:friend_chat_stop":
        context.user_data.pop("friend_chat_target", None)
        await _send_ui(query.message, context, send_ui_text, "گفت‌وگو با دوست پایان یافت.", reply_markup=_chat_home_markup())
        return True
    if data.startswith("chat:friend_remove:"):
        try:
            friend_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await _send_ui(query.message, context, send_ui_text, "دوست انتخاب‌شده معتبر نیست.")
            return True
        context.user_data.pop("friend_chat_target", None)
        removed = chat_db.remove_friend(user_id, friend_id)
        await _send_ui(query.message, context, send_ui_text,
            "دوست از فهرست شما حذف شد." if removed else "این کاربر در فهرست دوستان شما نبود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 بازگشت به دوستان", callback_data="chat:friends")]]))
        return True
    if data == "chat:profile":
        profile = chat_db.get_profile(user_id)
        if not profile:
            await _start_profile_callback(query, context, send_ui_text, user_id)
        else:
            pref = PREFERENCE_LABELS.get(str(profile["preference"]), "فرقی ندارد")
            await _send_ui(query.message, context, send_ui_text,
                           "👤 <b>پروفایل شما</b>\n\n"
                           f"{_profile_description(profile)}\n"
                           f"🎯 مخاطب دلخواه: {pref}\n\n"
                           "این اطلاعات در معرفی اولیه برای مخاطب نمایش داده می‌شود.",
                           parse_mode="HTML",
                           reply_markup=InlineKeyboardMarkup([
                               [InlineKeyboardButton("✏️ ویرایش پروفایل", callback_data="chat:edit_profile")],
                               [InlineKeyboardButton("🤝 دوستان من", callback_data="chat:friends")],
                               [InlineKeyboardButton("⬅️ بازگشت", callback_data="chat:home")],
                           ]))
        return True
    if data == "chat:edit_profile":
        partner = chat_db.get_partner_id(user_id)
        if partner is not None:
            await leave_current_session(user_id, context)
        else:
            chat_db.end_chat(user_id, remember_pair=False)
        await _start_profile_callback(query, context, send_ui_text, user_id)
        return True
    if data == "chat:profile_gender:female" or data == "chat:profile_gender:male":
        if context.user_data.get("chat_profile_step") != "gender":
            await _send_ui(query.message, context, send_ui_text, "برای تغییر جنسیت، از بخش پروفایل گزینهٔ ویرایش را انتخاب کنید.")
            return True
        gender = data.rsplit(":", 1)[1]
        context.user_data.setdefault("chat_profile_form", {})["gender"] = gender
        context.user_data["chat_profile_step"] = "city"
        await _send_ui(query.message, context, send_ui_text, "📍 نام شهر محل زندگی‌تان را وارد کنید (۲ تا ۷۰ نویسه):",
                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لغو", callback_data="chat:cancel_flow")]]))
        return True
    if data.startswith("chat:profile_preference:"):
        if context.user_data.get("chat_profile_step") != "preference":
            await _send_ui(query.message, context, send_ui_text, "برای تغییر ترجیح جنسیت مخاطب، از منوی چت گزینهٔ انتخاب جنسیت مخاطب را بزنید.")
            return True
        preference = data.rsplit(":", 1)[1]
        if preference not in PREFERENCE_LABELS:
            await _send_ui(query.message, context, send_ui_text, "گزینهٔ جنسیت معتبر نیست.")
            return True
        form = context.user_data.get("chat_profile_form", {})
        if not all(form.get(key) for key in ("name", "gender", "city")):
            context.user_data.pop("chat_profile_step", None)
            context.user_data.pop("chat_profile_form", None)
            await _begin_profile(query.message, context, send_ui_text)
            return True
        chat_db.save_profile(user_id, form["name"], form["gender"], form["city"], preference)
        context.user_data.pop("chat_profile_step", None)
        context.user_data.pop("chat_profile_form", None)
        await _show_home(query.message, context, send_ui_text, user_id, notice="✅ پروفایل شما ذخیره شد.")
        return True
    if data == "chat:preferences":
        profile = chat_db.get_profile(user_id)
        if not profile:
            await _begin_profile(query.message, context, send_ui_text)
            return True
        await _send_ui(query.message, context, send_ui_text, "دوست دارید با چه جنسیتی گفت‌وگو کنید؟", reply_markup=_preference_markup("chat:set_preference"))
        return True
    if data.startswith("chat:set_preference:"):
        preference = data.rsplit(":", 1)[1]
        if preference not in PREFERENCE_LABELS:
            await _send_ui(query.message, context, send_ui_text, "گزینهٔ انتخاب‌شده معتبر نیست.")
            return True
        chat_db.update_preference(user_id, preference)
        await _show_home(query.message, context, send_ui_text, user_id, notice="✅ ترجیح جنسیت مخاطب ذخیره شد؛ در جست‌وجوی بعدی اعمال می‌شود.")
        return True
    if data == "chat:search":
        await _start_search(query.message, context, send_ui_text, user_id)
        return True
    if data == "chat:stop_search":
        partner = chat_db.get_partner_id(user_id)
        if partner is not None:
            await _finish_chat(user_id, context, reason="end", send_ui_message=query.message, send_ui_text=send_ui_text)
        else:
            chat_db.stop_search(user_id)
            await _show_home(query.message, context, send_ui_text, user_id, notice="جست‌وجو لغو شد.")
        return True
    if data == "chat:next":
        await _finish_chat(user_id, context, reason="next", requeue=True,
                           send_ui_message=query.message, send_ui_text=send_ui_text)
        return True
    if data == "chat:end":
        await _finish_chat(user_id, context, reason="end", send_ui_message=query.message, send_ui_text=send_ui_text)
        return True
    if data == "chat:report":
        partner = chat_db.get_partner_id(user_id)
        if partner is not None:
            chat_db.record_report(user_id, partner)
        await _finish_chat(user_id, context, reason="report", send_ui_message=query.message, send_ui_text=send_ui_text)
        return True
    if data == "chat:cancel_flow":
        await _delete_saved_message(context, user_id, "session_message_id")
        await _delete_saved_message(context, user_id, "waiting_message_id")
        context.user_data.pop("chat_profile_step", None)
        context.user_data.pop("chat_profile_form", None)
        profile = chat_db.get_profile(user_id)
        if profile:
            await _show_home(query.message, context, send_ui_text, user_id, notice="ویرایش پروفایل لغو شد.")
        else:
            context.user_data["anonymous_mode"] = False
            await _send_ui(query.message, context, send_ui_text, "ساخت پروفایل لغو شد. از منوی اصلی هر زمان خواستید دوباره وارد شوید.", reply_markup=_main_menu_markup())
        return True
    return True
def should_handle_user_message(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Route text/media into chat even after an app restart if a match is active."""
    if context.user_data.get("anonymous_mode") or context.user_data.get("chat_profile_step") or context.user_data.get("friend_chat_target") is not None:
        return True
    return chat_db.get_partner_id(user_id) is not None or chat_db.is_searching(user_id)
def has_profile(user_id: int) -> bool:
    return chat_db.get_profile(user_id) is not None
def is_currently_chatting(user_id: int) -> bool:
    return chat_db.get_partner_id(user_id) is not None
def get_counts() -> dict[str, int]:
    return chat_db.get_counts()
