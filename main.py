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

# Timezone for Yerevan (UTC+4)
YEREVAN_TZ = timezone(timedelta(hours=4))

# Global cache for arrivals
CACHE = {
    "Комитас 🏛️": None,
    "Сарян 🎨": None
}

def format_arrival_time(time_str: str) -> str:
    lines = [line.strip() for line in time_str.split('\n') if line.strip()]
    formatted_times = []
    
    for line in lines:
        if line == "прибывает":
            formatted_times.append("сейчас")
            continue
            
        if "мин" in line or "ч" in line:
            formatted_times.append(line)
            continue
            
        try:
            now = datetime.now(YEREVAN_TZ)
            target_time = datetime.strptime(line, "%H:%M")
            arrival = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
            if arrival < now:
                arrival += timedelta(days=1)
                
            diff_minutes = (arrival - now).total_seconds() / 60
            diff_rounded = int(diff_minutes + 0.5)
            
            if diff_rounded <= 0:
                formatted_times.append(f"{line} (сейчас)")
            else:
                formatted_times.append(f"{line} (через {diff_rounded} мин)")
        except:
            formatted_times.append(line)
            
    return " • ".join(formatted_times)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8697237632:AAH_UMAaucv-OcMZAIpZIzyPBJF-ANIJxEs")

STOPS = {
    "Комитас 🏛️": "https://yandex.com/maps/-/CPq-mANv",
    "Сарян 🎨": "https://yandex.com/maps/-/CPq-mCPa"
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Комитас 🏛️")],
            [KeyboardButton(text="Сарян 🎨")]
        ],
        resize_keyboard=True
    )

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "Привет! Нажми на кнопку остановки, и я моментально пришлю список ближайших автобусов.",
        reply_markup=get_keyboard()
    )

@dp.message(lambda message: message.text in STOPS.keys())
async def handle_stop_click(message: types.Message):
    stop_name = message.text
    arrivals = CACHE.get(stop_name)
    
    if arrivals is None:
        await message.answer(f"⏳ Данные для остановки {stop_name} еще загружаются (бот только что запущен). Попробуй через 10-15 секунд...")
        return
        
    if not arrivals:
        await message.answer(f"🚏 *{stop_name}*\n\nНикаких данных о транспорте сейчас нет. Попробуй чуть позже или проверь карту вручную.")
    else:
        text = f"🚏 *{stop_name}*\n\nБлижайший транспорт:\n"
        for arr in arrivals:
            display_time = format_arrival_time(arr['time'])
            text += f"• `{arr['name']:>3}` — *{display_time}*\n"
        
        await message.answer(text, parse_mode="Markdown")

async def browser_polling_task(app):
    print("Background browser task started...", flush=True)
    while True:
        try:
            print("Launching persistent browser...", flush=True)
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
                )
                
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                    locale="ru-RU"
                )
                
                pages = {}
                
                # Fetch a seeded page once
                try:
                    seed_page = await context.new_page()
                    await seed_page.goto("https://yandex.ru/", wait_until="networkidle", timeout=15000)
                    await seed_page.close()
                except:
                    pass
                
                for stop_name, url in STOPS.items():
                    page = await context.new_page()
                    try:
                        if hasattr(playwright_stealth, 'stealth_async'):
                            await playwright_stealth.stealth_async(page)
                    except:
                        pass
                    
                    print(f"Loading page for {stop_name}...", flush=True)
                    await page.goto(url, wait_until="networkidle")
                    pages[stop_name] = page
                
                await asyncio.sleep(5)
                
                print("Started continuous scraping loop...", flush=True)
                while True:
                    for stop_name, page in pages.items():
                        try:
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
                            CACHE[stop_name] = arrivals
                        except Exception as eval_err:
                            print(f"Error evaluating page for {stop_name}: {eval_err}", flush=True)
                            # If page is totally broken, exit inner loop to recreate browser
                            raise eval_err
                    
                    # Wait 5 seconds before next scrape
                    await asyncio.sleep(5)
                    
        except Exception as e:
            print(f"Browser task error: {e}. Restarting browser in 5 seconds...", flush=True)
            await asyncio.sleep(5)

async def bot_polling(app):
    print("Background bot task started...", flush=True)
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

async def health_check(request):
    return web.Response(text="Bot is running! Health check passed.", status=200)

app = web.Application()
app.router.add_get('/', health_check)

async def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return

    await asyncio.sleep(60)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as response:
                    pass
            except Exception:
                pass
            await asyncio.sleep(14 * 60)

async def start_background_tasks(app):
    app['bot_task'] = asyncio.create_task(bot_polling(app))
    app['browser_task'] = asyncio.create_task(browser_polling_task(app))
    app['ping_task'] = asyncio.create_task(self_ping())

async def cleanup_background_tasks(app):
    app['bot_task'].cancel()
    app['browser_task'].cancel()
    app['ping_task'].cancel()
    try:
        await app['bot_task']
        await app['browser_task']
        await app['ping_task']
    except asyncio.CancelledError:
        pass

app.on_startup.append(start_background_tasks)
app.on_cleanup.append(cleanup_background_tasks)

def main():
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting web server on port {port}...", flush=True)
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
