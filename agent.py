from openai import OpenAI

from config import (
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
)


class GameAgent:

    def __init__(self):

        if not QWEN_API_KEY:
            raise ValueError(
                "QWEN_API_KEY تنظیم نشده است."
            )

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

        platforms_text = (
            "، ".join(platforms)
            if platforms
            else "نامشخص"
        )

        prompt = f"""
نام بازی:
{title}

دسته‌ای که کاربر انتخاب کرده:
{genre}

پلتفرم‌ها:
{platforms_text}

توضیحات واقعی بازی:
{description}

یک معرفی فارسی و جذاب برای این بازی بنویس.

قوانین:

1. فقط درباره خود بازی صحبت کن.
2. درباره فضای بازی توضیح بده.
3. درباره سبک و تجربه گیم‌پلی توضیح بده.
4. اگر داستان یا دنیای بازی در توضیحات منبع وجود دارد،
   درباره آن صحبت کن.
5. درباره سازنده، شرکت سازنده یا تاریخچه سازندگان صحبت نکن.
6. تاریخ انتشار را محور معرفی قرار نده.
7. اطلاعاتی که در داده‌های واقعی بالا نیستند
   اختراع نکن.
8. متن خیلی طولانی نباشد.
9. فارسی روان و طبیعی بنویس.
10. معرفی باید برای کسی باشد که می‌خواهد بفهمد
    این بازی چه تجربه‌ای به او می‌دهد.
"""

        response = self.client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو یک منتقد حرفه‌ای بازی‌های "
                        "ویدیویی هستی. "
                        "وظیفه تو معرفی جذاب و دقیق بازی‌ها "
                        "به زبان فارسی است."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        return (
            response.choices[0].message.content
            or "نتوانستم معرفی بازی را تولید کنم."
        )