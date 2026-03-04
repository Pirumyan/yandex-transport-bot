import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
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
        # Headless Chromium
        browser = await p.chromium.launch(headless=True)
        # Mobile-like viewport 400x800 with realistic User-Agent
        context = await browser.new_context(
            viewport={"width": 400, "height": 800},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
        )
        page = await context.new_page()
        
        # Apply stealth to avoid bot detection
        await stealth_async(page)
        
        await page.goto(url, wait_until="networkidle")
        
        # Wait 5 seconds for Yandex Maps and routes to load completely
        await asyncio.sleep(5)
        
        # Hide cookie banners, overlays and captcha blocks
        await page.evaluate("""
            const hideElements = () => {
                const selectors = [
                    '[class*="banner"]', 
                    '[class*="cookie"]', 
                    '[class*="popup"]',
                    '.Verification-SmartCaptcha',
                    '.dist-banner-container'
                ];
                selectors.forEach(selector => {
                    try {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.opacity = '0';
                            el.style.pointerEvents = 'none';
                        });
                    } catch (e) {}
                });
            };
            hideElements();
            // Periodically check for new banners during the wait
            setInterval(hideElements, 1000);
        """)
        
        # Small additional wait after hiding elements
        await asyncio.sleep(1)
        
        # Taking a screenshot of the 400x800 viewport
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
            break # If polling successfully stops gracefully
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
    await app['bot_task']

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
