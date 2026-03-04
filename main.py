import os
import asyncio
from datetime import datetime, timedelta, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from playwright.async_api import async_playwright
import playwright_stealth
import aiohttp
from aiohttp import web
import uuid

# Timezone for Yerevan (UTC+4)
YEREVAN_TZ = timezone(timedelta(hours=4))

# Helper to parse Yandex time and calculate relative minutes
def format_arrival_time(time_str: str) -> str:
    time_str = time_str.strip()
    
    # If it's already relative (e.g., "5 мин" or "< 1 мин"), return as is
    if "мин" in time_str or "ч" in time_str:
        return time_str
        
    # If it's absolute (e.g., "07:09")
    try:
        now = datetime.now(YEREVAN_TZ)
        target_time = datetime.strptime(time_str, "%H:%M")
        
        # Set target date to today
        arrival = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
        
        # If the arrival time is earlier than now, it's likely for the next day (unlikely for buses, but safe)
        if arrival < now:
            arrival += timedelta(days=1)
            
        diff_minutes = (arrival - now).total_seconds() / 60
        
        # Round up like Yandex does
        diff_rounded = int(diff_minutes + 0.5)
        
        if diff_rounded <= 0:
            return f"{time_str} (сейчас)"
        return f"{time_str} (через {diff_rounded} мин)"
    except:
        return time_str

# Fetch token from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "8697237632:AAH_UMAaucv-OcMZAIpZIzyPBJF-ANIJxEs")

# Specific URLs for Yandex Maps with transport layer
STOPS = {
    "Комитас 🏛️": "https://yandex.com/maps/-/CPq-mANv",
    "Сарян 🎨": "https://yandex.com/maps/-/CPq-mCPa"
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Reply Keyboard Generator
def get_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Комитас 🏛️")],
            [KeyboardButton(text="Сарян 🎨")]
        ],
        resize_keyboard=True
    )
    return keyboard

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "Привет! Нажми на кнопку остановки, и я пришлю скриншот карты с ближайшими автобусами.",
        reply_markup=get_keyboard()
    )

# Function to extract bus arrival times
async def get_arrival_times(url: str):
    async with async_playwright() as p:
        # Launch Chromium with extra args
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            locale="ru-RU"
        )
        page = await context.new_page()
        
        # Apply stealth
        try:
            if hasattr(playwright_stealth, 'stealth_async'):
                await playwright_stealth.stealth_async(page)
        except:
            pass

        # Visit Yandex home to seed cookies (optional but helpful)
        try:
            await page.goto("https://yandex.ru/", wait_until="networkidle", timeout=15000)
        except:
            pass
            
        # Navigate to the Map URL
        await page.goto(url, wait_until="networkidle")
        
        # Small wait for AJAX data
        await asyncio.sleep(5)
        
        # Extract data using the selectors identified
        arrivals = await page.evaluate("""() => {
            const items = document.querySelectorAll('li.masstransit-vehicle-snippet-view');
            return Array.from(items).map(item => {
                const nameEl = item.querySelector('.masstransit-vehicle-snippet-view__name');
                const timeEl = item.querySelector('.masstransit-vehicle-snippet-view__prognoses');
                return {
                    name: nameEl ? nameEl.innerText.trim() : '?',
                    time: timeEl ? timeEl.innerText.trim() : '?'
                };
            });
        }""")
        
        await browser.close()
        return arrivals

@dp.message(lambda message: message.text in STOPS.keys())
async def handle_stop_click(message: types.Message):
    stop_name = message.text
    url = STOPS[stop_name]
    
    status_msg = await message.answer(f"⏳ Получаю данные об автобусах для остановки {stop_name}...")
    
    try:
        arrivals = await get_arrival_times(url)
        
        if not arrivals:
            await message.answer(f"🚏 {stop_name}:\nК сожалению, сейчас нет данных о прибывающем транспорте.")
        else:
            text = f"🚏 *{stop_name}*\n\nБлижайший транспорт:\n"
            for arr in arrivals:
                # Format time to be relative if absolute
                display_time = format_arrival_time(arr['time'])
                text += f"• `{arr['name']}` — *{display_time}*\n"
            
            await message.answer(text, parse_mode="Markdown")
            
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при получении данных:\n{e}")
    finally:
        try:
            await status_msg.delete()
        except:
            pass

# Background task for bot polling
async def bot_polling(app):
    print("Background bot polling task started...", flush=True)
    while True:
        try:
            print("Attempting to connect to Telegram...", flush=True)
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
            break
        except Exception as e:
            print(f"Connection failed: {type(e).__name__} - {e}")
            print("Retrying in 5 seconds...", flush=True)
            await asyncio.sleep(5)

# Simple health check endpoint for Render
async def health_check(request):
    return web.Response(text="Bot is running! Health check passed.", status=200)

app = web.Application()
app.router.add_get('/', health_check)

# Self-ping task to prevent Render from sleeping
async def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        print("Keep-alive: RENDER_EXTERNAL_URL is not set. Skipping self-ping.", flush=True)
        return

    print(f"Keep-alive: Starting self-ping task for {url}", flush=True)
    await asyncio.sleep(60) # Wait for server to fully start
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as response:
                    print(f"Keep-alive: Ping sent to {url}, status: {response.status}", flush=True)
            except Exception as e:
                print(f"Keep-alive: Ping failed: {e}", flush=True)
            
            # Ping every 14 minutes (Free tier sleeps after 15 min of inactivity)
            await asyncio.sleep(14 * 60)

# Attach the bot polling to run in the background when the web server starts
async def start_background_tasks(app):
    app['bot_task'] = asyncio.create_task(bot_polling(app))
    app['ping_task'] = asyncio.create_task(self_ping())

async def cleanup_background_tasks(app):
    app['bot_task'].cancel()
    app['ping_task'].cancel()
    try:
        await app['bot_task']
        await app['ping_task']
    except asyncio.CancelledError:
        pass

app.on_startup.append(start_background_tasks)
app.on_cleanup.append(cleanup_background_tasks)

def main():
    # Fetch port from environment variable, default to 10000 for Render
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting web server on port {port}...", flush=True)
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
