from openai import OpenAI

from config import (
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
)


class GameAgent:

    def __init__(self):

        self.enabled = bool(
            QWEN_API_KEY
        )

        self.client = None

        if self.enabled:

            self.client = OpenAI(
                api_key=QWEN_API_KEY,
                base_url=QWEN_BASE_URL,
            )

    def describe_game(
        self,
        title: str,
        genre: str,
        description: str,
        platforms: list[str],
    ):

        # اگر Qwen فعال نیست،
        # همان توضیح RAWG را برمی‌گردانیم.

        if not self.enabled:

            return description or (
                f"{title} یک بازی در سبک "
                f"{genre} است."
            )

        platforms_text = (
            "، ".join(platforms)
            if platforms
            else "نامشخص"
        )

        prompt = f"""
نام بازی:
{title}

سبک:
{genre}

پلتفرم‌ها:
{platforms_text}

توضیحات واقعی بازی:
{description}

یک معرفی فارسی کوتاه، جذاب و دقیق
برای این بازی بنویس.

قوانین:

1. اطلاعات جدید اختراع نکن.
2. فقط بر اساس اطلاعات داده‌شده بنویس.
3. درباره تجربه گیم‌پلی توضیح بده.
4. درباره فضای بازی توضیح بده.
5. اگر داستان در توضیحات وجود داشت،
   به آن اشاره کن.
6. متن خیلی طولانی نباشد.
7. فارسی روان باشد.
"""

        try:

            response = (
                self.client.chat.completions.create(
                    model=QWEN_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "تو یک منتقد حرفه‌ای "
                                "بازی‌های ویدیویی هستی."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                )
            )

            result = (
                response
                .choices[0]
                .message
                .content
            )

            if result:
                return result

        except Exception:

            pass

        return description or (
            f"{title} یک بازی در سبک "
            f"{genre} است."
        )