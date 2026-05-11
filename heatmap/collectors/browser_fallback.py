import asyncio
import logging
import random

LOG = logging.getLogger("heatmap.browser_fallback")


class BrowserFallback:
    """Playwright-based headless browser fallback with stealth for tough anti-crawl sites."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._browser = None
        self._context = None
        self._pw = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright is required for browser fallback. "
                "Install with: pip install playwright && playwright install chromium"
            )

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

    async def _create_context(self):
        await self._ensure_browser()
        width = random.randint(1280, 1920)
        height = random.randint(800, 1080)
        ua = random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ])
        self._context = await self._browser.new_context(
            viewport={"width": width, "height": height},
            user_agent=ua,
            locale=random.choice(["zh-CN", "en-US"]),
        )
        # Inject stealth scripts
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

    async def fetch(self, url: str, wait_selector: str | None = None) -> str:
        """Fetch rendered page content via headless browser."""
        await self._create_context()
        page = await self._context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._human_delay(2.0, 5.0)

        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=10000)
            except Exception:
                LOG.warning("Browser fallback: selector '%s' not found", wait_selector)

        # Scroll slowly like a human
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100 + Math.random() * 50;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= scrollHeight / 2) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 200 + Math.random() * 300);
                });
            }
        """)

        content = await page.content()
        await page.close()
        return content

    async def _human_delay(self, min_s: float, max_s: float):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
