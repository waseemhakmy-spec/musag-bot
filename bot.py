import os
import glob
import asyncio
import time
import discord
from discord.ext import commands
import google.generativeai as genai
# =========================================================
# 1. مفاتيح الربط (تمت موازنتها وإضافتها)
# =========================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
genai.configure(api_key=GEMINI_API_KEY)
# =========================================================
# 2. قراءة ورفع ملفات الأنظمة والسوابق القضائية
# =========================================================
uploaded_files = []
laws_folder = "./laws"

if os.path.exists(laws_folder):
    print("⏳ جاري فحص وقراءة مجلد الأنظمة والسوابق القضائية...")
    for file_path in glob.glob(f"{laws_folder}/*.*"):
        try:
           file_ref = genai.upload_file(file_path=file_path)
            uploaded_files.append(file_ref)
            print(f"✅ تم رفع: {os.path.basename(file_path)}")
        except Exception as e
            print(f"❌ تعذر رفع {os.path.basename(file_path)}: {e}")

# =========================================================
# 3. التعليمات البرمجية للنظام (System Instruction)
# =========================================================
SYSTEM_INSTRUCTION = """
أنت مساعد قانوني ذكي واسمك 'مصاغ'، مُصمم لمساعدة الطلاب والمستفيدين في الأنظمة السعودية والسوابق القضائية.

تعليمات الاستناد الصارمة:
1. عند سؤال المستفيد عن مواد نظامية أو واقعة، ابحث دائمًا في الملفات المرفوعة المرفقة (الأنظمة والسوابق).
2. اقتبس نص المادة الحرفي والدقيق مباشرة من الأنظمة المرفوعة بدون أي تغيير. يُمنع منعاً باتاً التأليف أو التخمين.
3. إذا سأل المستفيد عن سابقة قضائية أو موضوع يحتاج دعمًا، استخرج السابقة القضائية المناسبة من الملفات، واذكر رقمها/دائرتها والمبدأ القضائي وكيف تدعم الموقف.
4. إذا لم تجد المادة أو السابقة متوفرة بدقة في الملفات المرفوعة، قل بوضوح: "عذراً، هذا النص/السابقة غير متوفر بدقة في ملفات الأنظمة المرفوعة لدي حالياً"، ثم قدم تحليلاً عاماً مبنياً على المبادئ بدون ادعاء الاقتباس.

منهجية التحليل القانوني (IRAC) والشرح الأكاديمي:
1. عند إجراء أي تحليل قانوني عادي، التزم بـ IRAC:
   - **المسألة (Issue):** تحديد الإشكالية القانونية بدقة.
   - **القاعدة القانونية (Rule):** ذكر النص النظامي والسابقة القضائية من الملفات.
   - **التطبيق (Application):** إسقاط القاعدة على الواقعة المعروضة.
   - **النتيجة (Conclusion):** تقديم خلاصة الرأي القانوني.
2. إذا سألك المستفيد خصيصاً عن **منهجية IRAC** أو كيف يستخدمها ويطبقها في دراسته القانونية الجامعية، اشرحها له بأسلوب أخوي مشجع، مبسط، وبخطوات عملية مع إعطائه مثالاً تطبيقياً قصيراً ليتمكن من استخدامها في اختباراته وبحوثه.

أسلوبك أخوي، مشجع، احترافي، وداعم للطلاب.
"""

# =========================================================
# 4. إعدادات البوت والمهلة الزمنية
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
COOLDOWN_TIME = 10 

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
                "أنا **مساعدك القانوني**، مخصص لك ومُنشأ من طالب على وشك التخرج. "
                "قمت بدمج الأنظمة والسوابق القضائية لخدمتك مجاناً بالكامل 🤍.\n\n"
                "تفضل واسأل أي سؤال وبجاوبك! وإذا حاب تعرف وتفهم أكثر عن **منهجية IRAC القانونية** "
                "وكيف تطبقها وتستفيد منها في دراستك وإجاباتك الجامعية، بس اسأل عنها وستجد توضيحاً شاملاً ومبسطاً 🌹✨"
            ),
            color=0x2b2d31
        )
        await channel.send(embed=embed)

# =========================================================
# 6. الاستجابة للرسائل وتقسيم النص تلقائياً
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
                await message.channel.send(f"⏳ يرجى الانتظار **{remaining:.1f}** ثانية قبل إرسال استشارة جديدة 🌹.")
                return

        user_cooldowns[user_id] = current_time

        async with message.channel.typing():
            try:
                contents = []
                contents.extend(uploaded_files)
                contents.append(message.content)

                response = ai_client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.2
                    )
                )

                answer = response.text
                
                if len(answer) <= 1900:
                    await message.channel.send(answer)
                else:
                    for i in range(0, len(answer), 1900):
                        await message.channel.send(answer[i:i+1900])
                        await asyncio.sleep(0.5)

            except Exception as e:
                await message.channel.send(f"❌ حدث خطأ أثناء التحليل: {e}")

    await bot.process_commands(message)

# =========================================================
# 7. تشغيل البوت
# =========================================================
bot.run(DISCORD_TOKEN)
