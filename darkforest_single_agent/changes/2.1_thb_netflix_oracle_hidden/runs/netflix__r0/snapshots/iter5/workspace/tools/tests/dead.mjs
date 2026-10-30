// Clicks every visible control on each page and reports those with no URL change, DOM mutation or request.
import { chromium } from 'playwright';
const B = 'http://localhost:5173';
const SEL = process.env.SEL || 'button:visible, a:visible, [role=button]:visible';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(B + '/');
const tok = await page.evaluate(async () => (await (await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({email:'demo@netflix.local', password:'netflix123'})})).json()).access_token);
const login = async () => { await page.goto(B + '/'); await page.evaluate((t) => { localStorage.setItem('nf_token', t); localStorage.setItem('nf_profile', '2'); }, tok); };
for (const path of process.argv.slice(2)) {
  await login(); await page.goto(B + path); await page.waitForTimeout(1500);
  const n = await page.locator(SEL).count(); const dead = [];
  for (let i = 0; i < n; i++) {
    await login(); await page.goto(B + path); await page.waitForTimeout(900);
    const el = page.locator(SEL).nth(i); if (!(await el.count())) continue;
    const label = ((await el.getAttribute('aria-label')) || (await el.innerText().catch(()=>''))).trim().slice(0,40);
    if (/sign out/i.test(label)) continue;
    await page.evaluate(() => { window.__mut = 0; new MutationObserver((m) => { window.__mut += m.length; }).observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true }); });
    let reqs = 0; const onReq = () => reqs++; page.on('request', onReq); const url0 = page.url();
    try { await el.click({ timeout: 2000 }); } catch { dead.push(`[unclickable] ${label}`); page.off('request', onReq); continue; }
    await page.waitForTimeout(500);
    const mut = await page.evaluate(() => window.__mut).catch(() => 1); page.off('request', onReq);
    if (page.url() === url0 && !mut && !reqs) dead.push(label);
  }
  console.log(path, 'controls', n, 'DEAD:', JSON.stringify(dead));
}
await browser.close();
