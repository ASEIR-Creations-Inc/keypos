const express = require('express');
const { chromium } = require('/pos/tests/node_modules/playwright');
const app = express();
app.use(express.json());

let browser = null;
let context = null;
let page = null;
let logs = [];

(async () => {
    console.log("[Browser Server] Starting...");
    try {
        browser = await chromium.launch({ headless: true });
        context = await browser.newContext({ viewport: null, ignoreHTTPSErrors: true });
        page = await context.newPage();
        page.on("request", req => logs.push({ method: req.method(), url: req.url() }));
        page.on("response", res => logs.push({ method: res.request().method(), url: res.url(), status: res.status() }));
        console.log("[Browser Server] Ready on port 9002");
    } catch (error) {
        console.error("[Browser Server] Failed to launch:", error.message);
    }
})();

app.post("/launch", (req, res) => res.json({ success: true }));

app.post("/navigate", async (req, res) => { 
    try {
        await page.goto(req.body.url, { waitUntil: "domcontentloaded" }); 
        logs = []; 
        res.json({ success: true, message: "Navigated" }); 
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post("/screenshot", async (req, res) => { 
    try {
        await page.screenshot({ path: "/tmp/screenshot.png", fullPage: true });
        res.json({ success: true, path: "/tmp/screenshot.png" }); 
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post("/click", async (req, res) => { 
    try {
        await page.click(req.body.selector, { timeout: 5000 });
        await page.waitForTimeout(500); 
        res.json({ success: true }); 
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post("/type", async (req, res) => { 
    try {
        await page.fill(req.body.selector, req.body.text); 
        res.json({ success: true }); 
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post("/verify-api", async (req, res) => { 
    try {
        await page.click("body"); 
        await page.waitForTimeout(1000);
        const found = logs.find(l => l.url.includes(req.body.url)); 
        res.json({ success: !!found, found: !!found }); 
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post("/close", async (req, res) => { 
    if(browser) await browser.close(); 
    res.json({ success: true }); 
});

app.listen(9002);
