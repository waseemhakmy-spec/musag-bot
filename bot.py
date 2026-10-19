import os
import glob
import asyncio
import time
import threading
import discord
from discord.ext import commands
import google.generativeai as genai
from flask import Flask

# =========================================================
# 0. سيرفر ويب وهمي لإرضاء منصة Render ومنع خطأ البورت
# =========================================================
app = Flask('')

@app.route('/')
def home():
    return "Musag Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.start()

keep_alive()

# =========================================================
# 1. مفاتيح الربط
# =========================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
genai.configure(api_key=GEMINI_API_KEY)

# =========================================================
# 2. قراءة ورفع ملفات الأنظمة والسوابق (من المجلد الحالي)
# =========================================================
uploaded_files = []
laws_folder = "." 

print("⏳ جاري فحص وقراءة ملفات الأنظمة والسوابق القضائية...")
for file_path in glob.glob(f"{laws_folder}/*.txt"):
    try:
        file_ref = genai.upload_file(file_path=file_path)
        uploaded_files.append(file_ref)
        print(f"✅ تم رفع واعتماد: {os.path.basename(file_path)}")
    except Exception as e:
        print(f"❌ تعذر رفع {os.path.basename(file_path)}: {e}")

# =========================================================
# 3. التعليمات البرمجية للنظام (مُحسنة لسرعة ودقة الاستلال)
# =========================================================
SYSTEM_INSTRUCTION = """
أنت مساعد قانوني ذكي واسمك 'مصاغ'، صُممت وقمت بإنشائك من قِبل طالب قانون على وشك التخرج لتكون أداة مساعدة لخدمة طلبة القانون والمهتمين وعامة المستفيدين في الأنظمة السعودية والسوابق القضائية.

تعليمات الاستناد الصارمة ودقة الاستلال:
1. دقة الاقتباس الحرفي: عند ذكر أي مادة نظامية، يجب اقتباس نصها الحرفي والدقيق تماماً كما ورد في الملفات المرفوعة دون أي تحريف أو زيادة أو نقصان. يُمنع منعاً باتاً التأليف أو التخمين في أرقام المواد أو النصوص.
2. تنويه نظامي إلزامي: يجب أن تُذكر دائمًا في نهاية أي إفادة أو تحليل بأن: "هذه الإفادة أو الرأي القانوني هي لأغراض تعليمية وبحثية فقط، ولا تُغني بحال من الأحوال عن مراجعة محامي مرخص أو مختص نظامي".
3. تجنب تام لكلمة "استشارة قانونية" واستبدالها دائماً بـ "إفادة نظامية" أو "رأي قانوني تحليلي".
4. إذا لم تجد المادة أو السابقة متوفرة بدقة في الملفات المرفوعة، قل بوضوح: "عذراً، هذا النص/السابقة غير متوفر بدقة في ملفات الأنظمة المرفوعة لدي حالياً"، ثم قدم تحليلاً عاماً مبنياً على المبادئ النظامية العامة بدون ادعاء الاقتباس.

منهجية التحليل القانوني (IRAC):
- **المسألة (Issue):** تحديد الإشكالية القانونية بدقة.
- **القاعدة القانونية (Rule):** ذكر النص النظامي والسابقة بدقة فائقة.
- **التطبيق (Application):** إسقاط القاعدة على الواقعة.
- **النتيجة (Conclusion):** خلاصة الرأي القانوني المعتمد.

أسلوبك أخوي، مشجع، احترافي، دقيق، وداعم للطلاب.
"""

# =========================================================
# 4. إعدادات البوت والمهلة الزمنية
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
COOLDOWN_TIME = 5

@bot.event
async def on_ready():
    print(f"✅ تم تشغيل البوت بنجاح باسم: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="⚖️ التحليل القانوني ومنهجية IRAC"))

# =========================================================
# 5. الترحيب التلقائي عند فتح تكت جديد
# =========================================================
@bot.event
async def on_guild_channel_create(channel):
    if channel.name.startswith("ticket-"):
        await asyncio.sleep(1)
        embed = discord.Embed(
            title="⚖️ مرحباً بك في (مصاغ)!",
            description=(
                "أنا **مساعدك القانوني**، صُممت وأُنشئت من قِبل طالب قانون على وشك التخرج لأكون سنداً لطلبة القانون والعامة في الأنظمة والسوابق السعودية 🤍.\n\n"
                "📌 **تنبيه هام:** جميع الإفادات والتحليلات هنا لأغراض تعليمية وبحثية فقط، **ولا تُغني بحال من الأحوال عن مراجعة محامي مرخص**.\n\n"
                "تفضل اطرح سؤالك أو قضيتك لنقوم بتحليلها معاً وفق منهجية IRAC 🚀✨"
            ),
            color=0x2b2d31
        )
        await channel.send(embed=embed)

# =========================================================
# 6. الاستجابة للرسائل (باستخدام gemini-3.8-flash)
# =========================================================
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
                remaining = COOLDOWN_TIME - elapsed
                await message.channel.send(f"⏳ يرجى الانتظار **{remaining:.1f}** ثانية قبل إرسال إفادة جديدة 🌹.")
                return

        user_cooldowns[user_id] = current_time

        async with message.channel.typing():
            try:
                contents = []
                if uploaded_files:
                    contents.extend(uploaded_files)
                contents.append(message.content)

                # استخدام نموذج gemini-3.8-flash
                model = genai.GenerativeModel(
                    model_name="gemini-3.8-flash",
                    system_instruction=SYSTEM_INSTRUCTION
                )

                response = model.generate_content(
                    contents=contents,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1
                    )
                )

                answer = response.text
                
                if len(answer) <= 1900:
                    await message.channel.send(answer)
                else:
                    for i in range(0, len(answer), 1900):
                        await message.channel.send(answer[i:i+1900])
                        await asyncio.sleep(0.3)

            except Exception as e:
                await message.channel.send(f"❌ حدث خطأ أثناء التحليل: {e}")

    await bot.process_commands(message)

# =========================================================
# 7. تشغيل البوت
# =========================================================
bot.run(DISCORD_TOKEN)
