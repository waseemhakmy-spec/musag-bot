import os
import glob
import asyncio
import time
import threading
import discord
from discord.ext import commands
import anthropic
import google.generativeai as genai
import numpy as np
from flask import Flask, Response

# =========================================================
# 0. سيرفر ويب وهمي لمنع إيقاف الاستضافة
# =========================================================
app = Flask('')

@app.route('/')
def home():
    return Response("مُصاغ يعمل بنظام RAG بنجاح! ⚖️🚀", status=200, mimetype='text/plain')

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

keep_alive()

# =========================================================
# 1. مفاتيح الربط وتجهيز الذكاء الاصطناعي
# =========================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if ANTHROPIC_API_KEY and GEMINI_API_KEY:
    ai_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️ تنبيه: تأكد من وجود مفاتيح كلود وجيميني في متغيرات البيئة!")

# =========================================================
# 2. بناء نظام RAG المبسط
# =========================================================
knowledge_chunks = []
knowledge_embeddings = []

def build_rag_database():
    global knowledge_chunks, knowledge_embeddings
    print("⏳ جاري بناء قاعدة بيانات RAG الذكية...")
    
    files_to_read = glob.glob("./*.txt")
    all_text_chunks = []
    
    for file_path in files_to_read:
        if "requirements" in file_path:
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                paragraphs = content.split('\n\n')
                file_name = os.path.basename(file_path)
                for p in paragraphs:
                    if len(p.strip()) > 50:
                        all_text_chunks.append(f"[المصدر: {file_name}]\n{p.strip()}")
        except Exception as e:
            print(f"❌ تعذر قراءة {file_path}: {e}")

    print(f"📖 تم استخراج {len(all_text_chunks)} مادة نظامية. جاري الفهرسة...")
    
    for chunk in all_text_chunks:
        try:
            emb = genai.embed_content(
                model="models/text-embedding-004",
                content=chunk,
                task_type="retrieval_document"
            )['embedding']
            knowledge_chunks.append(chunk)
            knowledge_embeddings.append(emb)
        except Exception as e:
            print(f"⚠️ خطأ في فهرسة جزء من النص: {e}")
            time.sleep(1)
            
    print("✅ اكتمل بناء قاعدة بيانات RAG بنجاح!")

build_rag_database()

def retrieve_relevant_laws(query, top_k=3):
    if not knowledge_embeddings:
        return "لا توجد نصوص نظامية متوفرة في قاعدة البيانات حالياً."
        
    query_emb = genai.embed_content(
        model="models/text-embedding-004",
        content=query,
        task_type="retrieval_query"
    )['embedding']
    
    q_vec = np.array(query_emb)
    db_vecs = np.array(knowledge_embeddings)
    similarities = np.dot(db_vecs, q_vec) / (np.linalg.norm(db_vecs, axis=1) * np.linalg.norm(q_vec))
    
    top_indices = similarities.argsort()[-top_k:][::-1]
    retrieved_texts = [knowledge_chunks[i] for i in top_indices]
    
    return "\n\n---\n\n".join(retrieved_texts)

# =========================================================
# 3. التعليمات البرمجية الأساسية לנظام
# =========================================================
BASE_SYSTEM_INSTRUCTION = """
أنت مساعد قانوني ذكي واسمك 'مصاغ'، صُممت وقمت بإنشائك من قِبل طالب قانون على وشك التخرج لتكون أداة مساعدة لخدمة طلبة القانون والمهتمين.

تعليمات الرد والإجابة:
1. أجب بشكل طبيعي، مباشر، وواضح بناءً **فقط** على "النصوص النظامية المستخرجة" المرفقة لك أدناه.
2. دقة الاقتباس الحرفي: عند ذكر أي مادة من النصوص المستخرجة، اقتبسها حرفياً. يُمنع التخمين أو جلب معلومات من خارج النصوص المستخرجة.
3. إذا كانت النصوص المستخرجة لا تحتوي على إجابة واضحة للسؤال، قل بوضوح: "عذراً، التفاصيل الدقيقة غير متوفرة في ملفات الأنظمة المرفوعة لدي حالياً"، ثم قدم إجابة عامة جداً.
4. أضف دائماً في النهاية: "هذه الإفادة لأغراض تعليمية وبحثية فقط، ولا تُغني عن مراجعة محامي مرخص".
5. استبدل كلمة "استشارة قانونية" بـ "إفادة نظامية".
6. أضف في سطر مستقل بالنهاية: "(إذا كنت ترغب في تحليل المسألة تفصيلياً عبر منهجية IRAC، أخبرني بذلك لأسقطها لك)."

أسلوبك أخوي، مشجع، احترافي، وداعم.
"""

# =========================================================
# 4. إعدادات البوت
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, reconnect=True)

user_cooldowns = {}
COOLDOWN_TIME = 5

@bot.event
async def on_ready():
    print(f"✅ تم اتصال وتأكيد تشغيل البوت بنجاح باسم: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="⚖️ الإفادات والتحليلات النظامية | RAG Powered"))

@bot.event
async def on_guild_channel_create(channel):
    if channel.name.startswith("ticket-"):
        await asyncio.sleep(1)
        embed = discord.Embed(
            title="⚖️ مرحباً بك في (مصاغ)!",
            description=(
                "أنا **مساعدك القانوني**، صُممت لأكون سنداً لطلبة القانون والعامة في الأنظمة والسوابق السعودية 🤍.\n\n"
                "📌 **تنبيه هام:** جميع الإفادات والتحليلات لأغراض تعليمية فقط.\n\n"
                "تفضل اطرح سؤالك لنقوم بالإجابة عليه وتحليله 🚀✨"
            ),
            color=0x2b2d31
        )
        await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.name.startswith("ticket-") or message.channel.name == "musag":
        user_id = message.author.id
        current_time = time.time()

        if user_id in user_cooldowns:
            elapsed = current_time - user_cooldowns[user_id]
            if elapsed < COOLDOWN_TIME:
                await message.channel.send("⏳ يرجى الانتظار قليلاً قبل إرسال إفادة جديدة 🌹.")
                return
        user_cooldowns[user_id] = current_time

        async with message.channel.typing():
            try:
                loop = asyncio.get_running_loop()
                relevant_context = await loop.run_in_executor(None, retrieve_relevant_laws, message.content)
                
                FINAL_PROMPT = f"{BASE_SYSTEM_INSTRUCTION}\n\n[النصوص النظامية المستخرجة:\n{relevant_context}\n]"

                response = await ai_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=3000,
                    temperature=0.1,
                    system=FINAL_PROMPT,
                    messages=[{"role": "user", "content": message.content}]
                )

                answer = response.content[0].text
                full_response = f"{message.author.mention}\n\n{answer}"

                in_tokens = response.usage.input_tokens
                out_tokens = response.usage.output_tokens
                print(f"RAG Usage - User: {message.author.name} | Input: {in_tokens} | Output: {out_tokens}")

                if len(full_response) <= 1900:
                    await message.channel.send(full_response)
                else:
                    first_part = full_response[:1900]
                    await message.channel.send(first_part)
                    remaining_text = full_response[1900:]
                    for i in range(0, len(remaining_text), 1900):
                        await message.channel.send(remaining_text[i:i+1900])
                        await asyncio.sleep(0.3)

            except Exception as e:
                await message.channel.send(f"❌ حدث خطأ أثناء التحليل: {e}")

    await bot.process_commands(message)

# =========================================================
# 5. تشغيل البوت
# =========================================================
if __name__ == "__main__":
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            print(f"⚠️ انقطاع مؤقت في الاتصال: {e}")
            time.sleep(10)
