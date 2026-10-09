import logging

from openai import OpenAI

from config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL


logger = logging.getLogger(__name__)


class GameAgent:
    def __init__(self):
        self.enabled = bool(QWEN_API_KEY and QWEN_BASE_URL and QWEN_MODEL)
        self.client = None

        if self.enabled:
            self.client = OpenAI(
                api_key=QWEN_API_KEY,
                base_url=QWEN_BASE_URL,
            )

    def describe_game(
        self,
        title: str,
        genre: str | list[str] | None,
        description: str,
        platforms: list[str] | None,
    ) -> str:
        genres = genre if isinstance(genre, list) else [genre] if genre else []
        genre_text = "، ".join(str(item) for item in genres) or "نامشخص"
        platforms_text = "، ".join(platforms or []) or "نامشخص"

        if not self.enabled:
            return description or f"{title} یک بازی در سبک {genre_text} است."

        prompt = f"""
نام بازی:
{title}

سبک:
{genre_text}

پلتفرم‌ها:
{platforms_text}

توضیحات واقعی بازی:
{description}

یک معرفی فارسی کوتاه، جذاب و دقیق برای این بازی بنویس.

قوانین:
1. اطلاعات جدید اختراع نکن.
2. فقط بر اساس اطلاعات داده‌شده بنویس.
3. درباره تجربه گیم‌پلی فقط از روی توضیحات موجود صحبت کن.
4. درباره فضای بازی فقط از روی توضیحات موجود صحبت کن.
5. اگر داستان در توضیحات وجود داشت، به آن اشاره کن.
6. متن کوتاه و خوانا باشد.
7. متن را با املای صحیح فارسی، نیم‌فاصله‌های مناسب و نشانه‌گذاری خوانا بنویس.
8. نام بازی و اطلاعات اصلی را تغییر نده.\n9. متن برای مخاطبان عمومی است؛ مخاطب را با «تو» خطاب نکن و به اطلاعات شخصی کاربر اشاره نکن.
"""

        try:
            response = self.client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "تو یک منتقد حرفه‌ای بازی‌های ویدیویی هستی.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
            )

            result = response.choices[0].message.content
            if result:
                return result.strip()
        except Exception as exc:
            logger.exception("AI description failed: %s", exc)

        return description or f"{title} یک بازی در سبک {genre_text} است."
    def answer_question(self, question: str) -> str | None:
        """Answer a general game-related question when an AI provider is configured."""
        if not self.enabled or not self.client:
            return None
        prompt = f"""
به زبان فارسی به پرسش کاربر درباره بازی‌های ویدیویی پاسخ بده.
پرسش: {question}

قواعد:
- اگر درباره بازی مشخصی سؤال شده، فقط اطلاعاتی را بگو که از دانسته‌های قابل اتکایت داری.
- تاریخ انتشار، قیمت، نسخه‌های جدید و جزئیات روز را حدس نزن؛ اگر مطمئن نیستی صریح بگو.
- برای درخواست پیشنهاد بازی، سبک، پلتفرم و سلیقه کاربر را در نظر بگیر.
- پاسخ خوانا و مفید باشد و در صورت نیاز نام بازی‌ها را انگلیسی نگه دار.
- اگر سؤال خارج از حوزه بازی است، کوتاه توضیح بده که این ربات برای کشف و اطلاعات بازی طراحی شده است.
"""
        try:
            response = self.client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": "تو دستیار فارسی‌زبان متخصص بازی‌های ویدیویی هستی."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35,
            )
            answer = response.choices[0].message.content
            return answer.strip() if answer else None
        except Exception as exc:
            logger.exception("General game question failed: %s", exc)
            return None
