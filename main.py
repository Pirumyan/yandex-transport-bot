import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from playwright.async_api import async_playwright
import playwright_stealth
from aiohttp import web
import uuid

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

# Function to take the screenshot
async def take_screenshot(url: str, filename: str):
    async with async_playwright() as p:
        # Launch Headless Chromium
        browser = await p.chromium.launch(headless=True)
        
        # User-Agent mobile iPhone + Russian locale and timezone to look human
        context = await browser.new_context(
            viewport={"width": 400, "height": 800},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Referer": "https://yandex.ru/"
            }
        )
        page = await context.new_page()
        
        # Apply stealth plugin
        try:
            if hasattr(playwright_stealth, 'stealth_async'):
                await playwright_stealth.stealth_async(page)
            elif hasattr(playwright_stealth, 'stealth'):
                res = playwright_stealth.stealth(page)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as stealth_e:
            print(f"Stealth warning: {stealth_e}", flush=True)
            
        # Navigate to URL
        await page.goto(url, wait_until="domcontentloaded")
        
        # Human-like interaction: Initial wait and simulated scrolling
        await asyncio.sleep(2.5)
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(1.2)
        await page.mouse.wheel(0, -400)
        
        # Give more time for the data/map to load specifically
        await asyncio.sleep(5.5)
        
        # Hide cookie banners, overlays and captcha leftovers
        await page.evaluate("""
            const hideElements = () => {
                const selectors = [
                    '[class*="banner"]', 
                    '[class*="cookie"]', 
                    '[class*="popup"]',
                    '.Verification-SmartCaptcha',
                    '.dist-banner-container',
                    '.Swithcer-Content',
                    '.MapActionControls-Swithcer'
                ];
                selectors.forEach(selector => {
                    try {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.display = 'none';
                            el.style.opacity = '0';
                            el.style.visibility = 'hidden';
                        });
                    } catch (e) {}
                });
            };
            hideElements();
            setInterval(hideElements, 1000);
        """)
        
        # Take the screenshot
        await page.screenshot(path=filename)
        await browser.close()

@dp.message(lambda message: message.text in STOPS.keys())
async def handle_stop_click(message: types.Message):
    stop_name = message.text
    url = STOPS[stop_name]
    
    # Notify user that process has started
    status_msg = await message.answer(f"⏳ Открываю карту для остановки {stop_name} и делаю скриншот...")
    
    # Generate random filename
    filename = f"screenshot_{uuid.uuid4()}.png"
    
    try:
        await take_screenshot(url, filename)
        
        from aiogram.types import FSInputFile
        photo = FSInputFile(filename)
        
        # Send Photo
        await message.answer_photo(
            photo=photo,
            caption=f"🚏 Остановка: {stop_name}\nВот карта с ближайшим транспортом:"
        )
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при создании скриншота:\n{e}")
    finally:
        # Delete the status message
        try:
            await status_msg.delete()
        except:
            pass
        
        # Always clean up the screenshot
        if os.path.exists(filename):
            os.remove(filename)

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

# Attach the bot polling to run in the background when the web server starts
async def start_background_tasks(app):
    app['bot_task'] = asyncio.create_task(bot_polling(app))

async def cleanup_background_tasks(app):
    app['bot_task'].cancel()
    try:
        await app['bot_task']
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
