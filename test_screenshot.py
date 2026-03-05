import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 400, "height": 800})
        await page.goto("https://yandex.com/maps/-/CPq-mANv")
        await asyncio.sleep(5)
        
        # Take full screenshot to see how it looks natively
        await page.screenshot(path="full.png")
        
        # Attempt 1: clip
        await page.screenshot(path="clipped.png", clip={"x": 0, "y": 300, "width": 400, "height": 500})
        
        # Attempt 2: scroll down
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(1)
        await page.screenshot(path="scrolled.png")
        
        await browser.close()

asyncio.run(main())
