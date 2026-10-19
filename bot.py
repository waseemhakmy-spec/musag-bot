import os
import glob
import asyncio
import time
import threading
import discord
from discord.ext import commands
import google.generativeai as genai
from flask import Flask, Response

# =========================================================
# 0. سيرفر ويب وهمي لإرضاء منصة Render ومنع خطأ البورت
# =========================================================
app = Flask('')

@app.route('/')
def home():
    return Response("OK", status=200, mimetype='text/plain')

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

keep_alive()

# =========================================================
# 1. مفاتيح الربط
# =========================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
genai.configure(api_key=GEMINI_API_KEY)

uploaded_files = []

# =========================================================
# 2. التعليمات البرمجية للنظام
# =========================================================
SYSTEM_INSTRUCTION = """
أنت مساعد قانوني ذكي واسمك 'مصاغ'، صُممت وقمت بإنشائك من قِبل طالب قانون على وشك التخرج لتكون أداة مساعدة لخدمة طلبة القانون والمهتمين وعامة المستفيدين في الأنظمة السعودية والسوابق القضائية.

تعليمات الرد والإجابة:
1. قم بالإجابة على سؤال المستفيد بشكل طبيعي، مباشر، واضح، ودقيق بناءً على الأنظمة والمستندات المرفوعة لديك دون تطبيق منهجية (IRAC) تلقائياً في الرد الأساسي.
2. دقة الاقتباس الحرفي: عند ذكر أي مادة نظامية، يجب اقتباس نصها الحرفي والدقيق تماماً كما ورد في الملفات المرفوعة دون أي تحريف أو زيادة أو نقصان. يُمنع منعاً باتاً التأليف أو التخمين في أرقام المواد أو النصوص.
3. إذا لم تجد المادة أو السابقة متوفرة بدقة في الملفات المرفوعة، قل بوضوح: "عذراً، هذا النص/السابقة غير متوفر بدقة في ملفات الأنظمة المرفوعة لدي حالياً"، ثم قدم تحليلاً عاماً مبنياً على المبادئ النظامية العامة بدون ادعاء الاقتباس.
4. تنويه نظامي إلزامي: يجب أن تُذكر دائمًا في نهاية أي إفادة أو تحليل بأن: "هذه الإفادة أو الرأي القانوني هي لأغراض تعليمية وبحثية فقط، ولا تُغني بحال من الأحوال عن مراجعة محامي مرخص أو مختص نظامي".
5. تجنب تام لكلمة "استشارة قانونية" واستبدالها دائماً بـ "إفادة نظامية" أو "رأي قانوني تحليلي".
6. في نهاية كل إجابة، أضف الجملة التالية نصاً وبكل وضوح في سطر مستقل:
   "(إذا كنت ترغب في تحليل هذه المسألة تفصيلياً عبر منهجية IRAC، أخبرني بذلك لأسقطها لك)."

أسلوبك أخوي، مشجع، احترافي، دقيق، وداعم للطلاب.
"""

# =========================================================
# 3. إعدادات البوت والمهلة الزمنية
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
# تفعيل إعادة الاتصال التلقائي بحدود أمان لمنع حظر الـ 429
bot = commands.Bot(command_prefix="!", intents=intents, reconnect=True)

user_cooldowns = {}
COOLDOWN_TIME = 5

async def load_laws_files():
    global uploaded_files
    laws_folder = "." 
    print("⏳ جاري فحص وقراءة ملفات الأنظمة والسوابق القضائية في الخلفية...")
    loop = asyncio.get_event_loop()
    files_to_upload = glob.glob(f"{laws_folder}/*.txt")
    
    for file_path in files_to_upload:
        if file_path.endswith("requirements.txt"):
            continue
        try:
            file_ref = await loop.run_in_executor(None, lambda: genai.upload_file(path=file_path))
            uploaded_files.append(file_ref)
            print(f"✅ تم رفع واعتماد: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"❌ تعذر رفع {os.path.basename(file_path)}: {e}")

@bot.event
async def on_ready():
    print(f"✅ تم اتصال وتأكيد تشغيل البوت بنجاح باسم: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="⚖️ الإفادات والتحليلات النظامية"))
    asyncio.create_task(load_laws_files())

@bot.event
async def on_guild_channel_create(channel):
    if channel.name.startswith("ticket-"):
        await asyncio.sleep(1)
        embed = discord.Embed(
            title="⚖️ مرحباً بك في (مصاغ)!",
            description=(
                "أنا **مساعدك القانوني**، صُممت وأُنشئت من قِبل طالب قانون على وشك التخرج لأكون سنداً لطلبة القانون والعامة في الأنظمة والسوابق السعودية 🤍.\n\n"
                "📌 **تنبيه هام:** جميع الإفادات والتحليلات هنا لأغراض تعليمية وبحثية فقط، **ولا تُغني بحال من الأحوال عن مراجعة محامي مرخص**.\n\n"
                "تفضل اطرح سؤالك أو قضيتك لنقوم بالإجابة عليها وتحليلها معاً 🚀✨"
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
                full_response = f"{message.author.mention}\n\n{answer}"

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
# 6. تشغيل البوت مع معالجة الاستثناءات لتجنب الكراش
# =========================================================
if __name__ == "__main__":
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            print(f"⚠️ واجهنا انقطاع مؤقت في الاتصال بديسكورد: {e}")
            print("⏳ جارٍ إعادة المحاولة خلال 10 ثوانٍ...")
            time.sleep(10)
