// Attach only to the smoke test's WebView2 debugging port, never a user browser.
const {chromium, expect} = require('@playwright/test');
const [endpoint, phase, output] = process.argv.slice(2);
(async () => {
    const browser = await chromium.connectOverCDP(endpoint);
    try {
        const context = browser.contexts()[0];
        const page = context.pages().find(page => page.url().includes('127.0.0.1:')) || await context.waitForEvent('page');
        await expect(page.locator('#theme')).toBeVisible();
        if (phase === 'save') await page.locator('#theme').selectOption('mint');
        await expect(page.locator('html')).toHaveAttribute('data-theme', 'mint');
        await page.screenshot({path: output});
        console.log(`PASS: desktop dashboard rendered; theme ${phase === 'save' ? 'saved' : 'persisted after restart'}`);
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
