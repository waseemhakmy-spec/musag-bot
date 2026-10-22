import os
import glob
import json
import time
import asyncio
import threading
import hashlib
import pickle
import logging

import discord
import anthropic
import numpy as np

from discord.ext import commands
from flask import Flask, Response
from google import genai
from google.genai import types


# =========================================================
# 1. الإعدادات الأساسية
# =========================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# تم التعديل إلى نموذج Sonnet 3.5 الأذكى والأوفر
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022").strip()

EMBEDDING_MODEL = "gemini-embedding-001"

INDEX_FILE = "rag_index.pkl"

TOP_K = 5
COOLDOWN_TIME = 5
MAX_CONTEXT_CHARS = 22000
MAX_DISCORD_MESSAGE = 1900

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("musag")


# =========================================================
# 2. التحقق من المفاتيح
# =========================================================

if not ANTHROPIC_API_KEY:
    raise RuntimeError("مفتاح ANTHROPIC_API_KEY غير موجود!")

if not GEMINI_API_KEY:
    raise RuntimeError("مفتاح GEMINI_API_KEY غير موجود!")

if not DISCORD_TOKEN:
    raise RuntimeError("مفتاح DISCORD_TOKEN غير موجود!")


# =========================================================
# 3. الاتصال بالخدمات
# =========================================================

ai_client = anthropic.AsyncAnthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=90.0,
    max_retries=2
)

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# 4. سيرفر الويب
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return Response(
        "مُصاغ يعمل بنظام RAG ⚖️",
        status=200,
        mimetype="text/plain"
    )


def run_web():
    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )


def keep_alive():
    thread = threading.Thread(
        target=run_web,
        daemon=True
    )
    thread.start()


# =========================================================
# 5. تعليمات مصاغ
# =========================================================

BASE_SYSTEM_INSTRUCTION = """
أنت مساعد قانوني سعودي ذكي باسم "مصاغ"،
صُممت لمساعدة طلبة القانون والمهتمين بالأنظمة السعودية.

قواعد الإجابة:

1. أجب بوضوح وبأسلوب مهني ومباشر، وبما يتناسب مع السؤال.

2. اعتمد في تقرير النصوص النظامية على المصادر المستخرجة
المرفقة في الطلب الحالي.

3. عند نقل مادة نظامية، انقل نصها حرفيًا من المصدر المتاح،
ولا تعدّل كلماتها أو تنشئ نصًا مشابهًا وتقدمه على أنه اقتباس.

4. لا تخترع أرقام مواد أو أسماء أنظمة أو أحكامًا قضائية
أو مددًا أو استثناءات غير موجودة في المصادر.

5. إذا لم تتوفر معلومات كافية، فقل:
"عذرًا، المصادر المتاحة لدي لا تكفي للجزم بالإجابة عن هذه المسألة."

6. ميّز بين النص النظامي الحرفي وبين شرحك أو استنتاجك منه.

7. عدم ظهور حكم في المقاطع المسترجعة لا يعني أن الحكم غير موجود
في النظام أو في الأنظمة الأخرى.

8. إذا طلب المستخدم تحليل مسألة، فنظّم الإجابة بحسب الحاجة:
الوقائع، المسألة القانونية، القاعدة النظامية، التطبيق، النتيجة.

9. لا تدّعِ أنك تحققت من سريان النظام أو آخر تعديلاته
ما لم يتوفر مصدر يثبت ذلك.

10. استبدل عبارة "استشارة قانونية" بعبارة "إفادة نظامية".

11. لا تكرر نصوصًا طويلة لا تخدم السؤال، ولا تنسب نصًا
إلى نظام ما لم يظهر مصدره بوضوح.

12. أسلوبك أخوي، مشجع، احترافي وداعم.

13. أضف في نهاية الإجابة:
"هذه الإفادة لأغراض تعليمية وبحثية فقط، ولا تُغني عن مراجعة محامٍ مرخص."

14. أضف بعدها في سطر مستقل:
"(إذا كنت ترغب في تحليل المسألة تفصيليًا عبر منهجية IRAC،
أخبرني بذلك لأحللها لك)."
"""


# =========================================================
# 6. إنشاء مقاطع قاعدة المعرفة
# =========================================================

knowledge_chunks = []
knowledge_embeddings = []


def get_file_hash(content):
    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def split_into_chunks(file_name, content):
    """
    تقسيم النص مع الحفاظ على الفقرات.
    إذا كانت الفقرة طويلة، تُقسّم إلى مقاطع أصغر.
    """

    paragraphs = [
        p.strip()
        for p in content.split("\n\n")
        if p.strip()
    ]

    chunks = []
    current = []
    current_length = 0
    max_chunk_length = 1800

    for paragraph in paragraphs:
        if len(paragraph) > max_chunk_length:
            if current:
                text = "\n\n".join(current)
                chunks.append(
                    f"[المصدر: {file_name}]\n{text}"
                )
                current = []
                current_length = 0

            for start in range(0, len(paragraph), max_chunk_length):
                piece = paragraph[start:start + max_chunk_length]

                if len(piece.strip()) > 50:
                    chunks.append(
                        f"[المصدر: {file_name}]\n{piece}"
                    )

            continue

        if current_length + len(paragraph) > max_chunk_length and current:
            text = "\n\n".join(current)

            chunks.append(
                f"[المصدر: {file_name}]\n{text}"
            )

            current = []
            current_length = 0

        current.append(paragraph)
        current_length += len(paragraph)

    if current:
        text = "\n\n".join(current)

        chunks.append(
            f"[المصدر: {file_name}]\n{text}"
        )

    return chunks


# =========================================================
# 7. إنشاء Embedding
# =========================================================

def create_embedding(text, task_type):
    result = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type
        )
    )

    if not result.embeddings:
        raise RuntimeError("لم يرجع نموذج التضمين أي متجه.")

    return result.embeddings[0].values


# =========================================================
# 8. بناء الفهرس وحفظه
# =========================================================

def build_rag_database():
    global knowledge_chunks, knowledge_embeddings

    logger.info("بدء تجهيز قاعدة المعرفة...")

    file_paths = sorted(glob.glob("./*.txt"))

    source_files = {}

    for file_path in file_paths:
        file_name = os.path.basename(file_path)

        if "requirements" in file_name.lower():
            continue

        try:
            with open(file_path, "r", encoding="utf-8-sig") as file:
                content = file.read()

            if content.strip():
                source_files[file_name] = {
                    "hash": get_file_hash(content),
                    "content": content
                }

        except Exception:
            logger.exception
