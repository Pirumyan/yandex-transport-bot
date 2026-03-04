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
        # Launch Chromium with extra args to look less like a bot
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        # Use a high-end Desktop profile (more common for cloud traffic)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
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

        # STEP 1: Visit Yandex homepage FIRST to get standard cookies
        try:
            await page.goto("https://yandex.ru/", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2) # Look at the homepage
        except:
            pass # Continue even if home fails
            
        # STEP 2: Navigate to the actual MAP URL
        await page.goto(url, wait_until="networkidle")
        
        # Human-like interaction: Random waits and small scrolls
        await asyncio.sleep(4) 
        
        # --- NEW: Check for Captcha and try to auto-click ---
        try:
            # Look for the SmartCaptcha container
            captcha_container = await page.query_selector('.Verification-SmartCaptcha')
            if captcha_container:
                print("Captcha detected! Attempting to auto-click...", flush=True)
                # The checkbox is usually inside an iframe
                iframes = page.frames
                for frame in iframes:
                    if "captcha" in frame.url.lower():
                        # Try to find the checkbox by its typical class or structure
                        # It's often a div with class 'checkbox__content' or similar
                        checkbox = await frame.query_selector('.checkbox__content, .checkbox, #captcha-checkbox')
                        if checkbox:
                            # Move mouse to the checkbox with some randomization
                            box = await checkbox.bounding_box()
                            if box:
                                x = box['x'] + box['width'] / 2 + (asyncio.get_event_loop().time() % 5)
                                y = box['y'] + box['height'] / 2 + (asyncio.get_event_loop().time() % 3)
                                await frame.mouse.move(x, y, steps=10)
                                await asyncio.sleep(0.5)
                                await frame.mouse.click(x, y)
                                print("Checkbox clicked. Waiting for transition...", flush=True)
                                await asyncio.sleep(5) # Wait for page to reload or map to appear
                                break
        except Exception as e:
            print(f"Auto-click failed: {e}", flush=True)

        # Human-like movement after potential captcha/load
        await page.mouse.wheel(0, 200)
        await asyncio.sleep(1)
        await page.mouse.wheel(0, -200)
        
        # Give enough time for the routes to load
        await asyncio.sleep(5)
        
        # Hide cookie banners and any leftovers
        await page.evaluate("""
            const hideElements = () => {
                const selectors = [
                    '[class*="banner"]', 
                    '[class*="cookie"]', 
                    '[class*="popup"]',
                    '.dist-banner-container',
                    '.Swithcer-Content',
                    '.MapActionControls-Swithcer',
                    '.Dialog-Content'
                ];
                selectors.forEach(selector => {
                    try {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            el.style.display = 'none';
                        });
                    } catch (e) {}
                });
            };
            hideElements();
            setInterval(hideElements, 1500);
        """)
        
        # Take a screenshot of the center of the map
        # We use a 400x800 clip from the center of the 1280x800 page
        await page.screenshot(
            path=filename, 
            clip={"x": 440, "y": 0, "width": 400, "height": 800}
        )
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
