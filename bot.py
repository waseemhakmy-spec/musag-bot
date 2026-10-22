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
            logger.exception("تعذر قراءة الملف: %s", file_name)

    if not source_files:
        logger.warning("لم يتم العثور على ملفات TXT تحتوي على نصوص.")
        return

    old_index = {}

    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "rb") as file:
                old_index = pickle.load(file)

            if not isinstance(old_index, dict):
                old_index = {}

        except Exception:
            logger.exception("تعذر تحميل الفهرس القديم، ستتم إعادة بنائه.")
            old_index = {}

    old_files = old_index.get("files", {})
    new_files = {}

    for file_name, data in source_files.items():
        old_data = old_files.get(file_name)

        # إذا لم يتغير الملف، نستخدم المقاطع والمتجهات المحفوظة.
        if (
            old_data
            and old_data.get("hash") == data["hash"]
            and old_data.get("chunks")
            and len(old_data.get("chunks", []))
                == len(old_data.get("embeddings", []))
        ):
            new_files[file_name] = old_data
            logger.info("استخدام الفهرس المحفوظ: %s", file_name)
            continue

        logger.info("فهرسة الملف أو تحديثه: %s", file_name)

        chunks = split_into_chunks(
            file_name,
            data["content"]
        )

        embeddings = []

        for index, chunk in enumerate(chunks, start=1):
            success = False
            for attempt in range(5): # محاولات إعادة في حال الضغط
                try:
                    embedding = create_embedding(
                        chunk,
                        "RETRIEVAL_DOCUMENT"
                    )
                    embeddings.append(embedding)
                    success = True
                    time.sleep(1.2) # تأخير إجباري لتفادي خطأ 429 RESOURCE_EXHAUSTED
                    break
                except Exception as e:
                    logger.warning(f"تنبيه: ضغط طلبات عند المقطع {index} (المحاولة {attempt+1}/5). جاري الانتظار...")
                    time.sleep(5 * (attempt + 1)) # انتظار تصاعدي

            if not success:
                logger.error(f"فشلت فهرسة المقطع {index} في {file_name}")
                raise RuntimeError(
                    f"فشلت فهرسة الملف {file_name}. "
                    "تحقق من الاتصال وحدود API ثم أعد التشغيل."
                )

            if index % 20 == 0:
                logger.info(
                    "%s: تمت فهرسة %s من %s",
                    file_name,
                    index,
                    len(chunks)
                )

        new_files[file_name] = {
            "hash": data["hash"],
            "chunks": chunks,
            "embeddings": embeddings
        }

    # إعادة بناء القوائم بالترتيب نفسه.
    knowledge_chunks = []
    knowledge_embeddings = []

    for file_name in sorted(new_files):
        data = new_files[file_name]

        knowledge_chunks.extend(data["chunks"])
        knowledge_embeddings.extend(data["embeddings"])

    saved_index = {
        "embedding_model": EMBEDDING_MODEL,
        "files": new_files
    }

    temporary_file = INDEX_FILE + ".tmp"

    with open(temporary_file, "wb") as file:
        pickle.dump(
            saved_index,
            file,
            protocol=pickle.HIGHEST_PROTOCOL
        )

    os.replace(temporary_file, INDEX_FILE)

    logger.info(
        "اكتملت قاعدة المعرفة: %s مقطعًا من %s ملفًا.",
        len(knowledge_chunks),
        len(new_files)
    )


# =========================================================
# 9. استرجاع النصوص النظامية
# =========================================================

def retrieve_relevant_laws(query, top_k=TOP_K):
    if not knowledge_chunks or not knowledge_embeddings:
        return "لا توجد نصوص نظامية مفهرسة حاليًا."

    query_embedding = create_embedding(
        query,
        "RETRIEVAL_QUERY"
    )

    query_vector = np.asarray(
        query_embedding,
        dtype=np.float32
    )

    database_vectors = np.asarray(
        knowledge_embeddings,
        dtype=np.float32
    )

    query_norm = np.linalg.norm(query_vector)

    if query_norm == 0:
        return "تعذر إجراء البحث الدلالي عن السؤال."

    database_norms = np.linalg.norm(
        database_vectors,
        axis=1
    )

    denominator = database_norms * query_norm

    similarities = np.divide(
        np.dot(database_vectors, query_vector),
        denominator,
        out=np.zeros_like(database_norms),
        where=denominator != 0
    )

    # نأخذ أفضل النتائج، ثم نضيفها مع مراعاة حجم السياق.
    top_indices = np.argsort(similarities)[::-1]

    retrieved_texts = []
    total_chars = 0

    for index in top_indices:
        if len(retrieved_texts) >= top_k:
            break

        chunk = knowledge_chunks[int(index)]

        if total_chars + len(chunk) > MAX_CONTEXT_CHARS:
            continue

        retrieved_texts.append(
            f"[درجة التشابه: {similarities[index]:.3f}]\n{chunk}"
        )

        total_chars += len(chunk)

    if not retrieved_texts:
        return "لم يتم العثور على نصوص مناسبة للسؤال."

    return "\n\n--------------------\n\n".join(
        retrieved_texts
    )


# =========================================================
# 10. إعداد Discord
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    reconnect=True
)

user_cooldowns = {}

# منع تنفيذ عدد كبير من طلبات AI بالتزامن.
ai_semaphore = asyncio.Semaphore(3)


@bot.event
async def on_ready():
    logger.info("تم تشغيل البوت باسم: %s", bot.user)

    await bot.change_presence(
        activity=discord.Game(
            name="⚖️ الإفادات والتحليلات النظامية | RAG"
        )
    )


# =========================================================
# 11. رسالة الترحيب بالتذاكر
# =========================================================

@bot.event
async def on_guild_channel_create(channel):
    if not channel.name.startswith("ticket-"):
        return

    await asyncio.sleep(1)

    embed = discord.Embed(
        title="⚖️ مرحبًا بك في مُصاغ!",
        description=(
            "أنا **مساعدك القانوني**، صُممت لمساعدة "
            "طلبة القانون والمهتمين بالأنظمة السعودية.\n\n"
            "📌 الإفادات والتحليلات لأغراض تعليمية وبحثية فقط.\n\n"
            "تفضل بطرح سؤالك."
        ),
        color=0x2B2D31
    )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        logger.exception("تعذر إرسال رسالة الترحيب.")


# =========================================================
# 12. إرسال الإجابة على أجزاء
# =========================================================

async def send_long_message(channel, content):
    for start in range(0, len(content), MAX_DISCORD_MESSAGE):
        part = content[start:start + MAX_DISCORD_MESSAGE]

        await channel.send(
            part,
            allowed_mentions=discord.AllowedMentions.none()
        )

        if start + MAX_DISCORD_MESSAGE < len(content):
            await asyncio.sleep(0.4)


# =========================================================
# 13. استقبال الأسئلة وتحليلها
# =========================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    channel_name = getattr(message.channel, "name", "")

    is_ticket = channel_name.startswith("ticket-")
    is_musag_channel = channel_name == "musag"

    if not (is_ticket or is_musag_channel):
        await bot.process_commands(message)
        return

    question = message.content.strip()

    if not question:
        return

    if len(question) > 6000:
        await message.channel.send(
            "⚠️ السؤال طويل جدًا. اختصره أو أرسله على أجزاء."
        )
        return

    user_id = message.author.id
    now = time.monotonic()

    previous_time = user_cooldowns.get(user_id, 0)
    elapsed = now - previous_time

    if elapsed < COOLDOWN_TIME:
        remaining = max(
            1,
            int(COOLDOWN_TIME - elapsed)
        )

        await message.channel.send(
            f"⏳ انتظر {remaining} ثانية قبل إرسال سؤال جديد."
        )
        return

    user_cooldowns[user_id] = now

    async with ai_semaphore:
        async with message.channel.typing():
            try:
                loop = asyncio.get_running_loop()

                relevant_context = await loop.run_in_executor(
                    None,
                    retrieve_relevant_laws,
                    question
                )

                # التعليمات الثابتة منفصلة عن النصوص المسترجعة.
                system_prompt = [
                    {
                        "type": "text",
                        "text": BASE_SYSTEM_INSTRUCTION,
                        "cache_control": {
                            "type": "ephemeral"
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "النصوص النظامية المسترجعة للسؤال الحالي:\n\n"
                            + relevant_context
                        )
                    }
                ]

                response = await ai_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=3000,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": question
                        }
                    ]
                )

                answer = "".join(
                    block.text
                    for block in response.content
                    if block.type == "text"
                ).strip()

                if not answer:
                    answer = (
                        "تعذر إعداد الإفادة من الطلب الحالي. "
                        "يرجى المحاولة مرة أخرى."
                    )

                full_response = (
                    f"{message.author.mention}\n\n{answer}"
                )

                usage = response.usage

                logger.info(
                    "Claude usage | User=%s | Input=%s | Output=%s "
                    "| Cache read=%s | Cache write=%s",
                    message.author.id,
                    usage.input_tokens,
                    usage.output_tokens,
                    getattr(usage, "cache_read_input_tokens", 0),
                    getattr(usage, "cache_creation_input_tokens", 0)
                )

                await send_long_message(
                    message.channel,
                    full_response
                )

            except Exception as error:
                logger.exception(
                    "فشل الطلب للمستخدم %s",
                    message.author.id
                )

                await message.channel.send(
                    "❌ تعذر إعداد الإفادة حاليًا. "
                    "حاول مرة أخرى بعد قليل."
                )

    await bot.process_commands(message)


# =========================================================
# 14. تشغيل البوت
# =========================================================

if __name__ == "__main__":
    # 1. تشغيل السيرفر الوهمي أولاً لإخبار Render أن البوت يعمل ويفتح البورت
    keep_alive()

    # 2. بدء فهرسة الأنظمة
    build_rag_database()

    # 3. تشغيل ديسكورد
    bot.run(DISCORD_TOKEN)
