cd app/frontend && npm ci --no-audit --no-fund && npm run build
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health; test -d /tmp/node_modules/playwright && echo PW_YES || echo PW_NO; pwd
cd /tmp && npm init -y >/dev/null 2>&1 && npm install --no-audit --no-fund playwright >/dev/null && echo PW_INSTALLED
cat > /tmp/hover_test.js <<'JS'
const { chromium } = require('playwright');
(async()=>{
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1107 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('http://127.0.0.1:3000/login', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Get Help' }).click();
  await page.getByRole('button', { name: 'Sign in with the demo account' }).click();
  await page.waitForURL('**/profiles');
  await page.locator('.profile-tile').first().click();
  await page.waitForURL('**/browse');
  await page.waitForTimeout(900);
  await page.locator('.title-card').first().hover();
  await page.waitForTimeout(500);
  console.log('float count', await page.locator('.card-hover-float').count());
  console.log('float rect', await page.locator('.card-hover-float').boundingBox());
  console.log('actions', await page.locator('.card-hover-float .round-action').count());
  await page.screenshot({ path: '/tmp/hover_float.png' });
  await page.locator('.card-hover-float .round-action').nth(2).click();
  await page.waitForTimeout(300);
  console.log('rate dialog', await page.locator('.rate-dialog').count());
  console.log('errors', errors);
  await browser.close();
})();
JS

node /tmp/hover_test.js
python3 - <<'PY'
from rapidocr_onnxruntime import RapidOCR
engine=RapidOCR()
res,_=engine('/tmp/hover_float.png')
for box,text,score in (res or []):
    xs=[p[0] for p in box]; ys=[p[1] for p in box]
    if score>.6:
        print(f'{min(xs):.0f},{min(ys):.0f}: {text}')
PY

exit
rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__
du -sh app
exit
cd app/frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null && echo WEB_OK
cd /workspace && rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__ && du -sh app
exit
cd app/frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null && echo WEB_OK
cd /workspace && rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__ && du -sh app
exit
grep -n "player-title-overlay\|language-controls\|languages-page-body" app/frontend/src/styles.css | head -20
python3 - <<'PY'
p='app/frontend/src/styles.css'
s=open(p).read()
old='.language-controls { display: flex; flex-direction: column; justify-content: flex-start; gap: 10px; width: min(520px, calc(100% - 40px)); margin-left: auto; padding: 5px 3.4% 8px; position: relative; z-index: 35; }'
new='.languages-page-body { position: relative; }\n.language-controls { display: flex; flex-direction: column; justify-content: flex-start; gap: 10px; width: min(520px, calc(100% - 40px)); margin: 0; padding: 0; position: absolute; top: -42px; right: 3.4%; z-index: 35; }\n.languages-page-body > .language-note { display: none; }\n.languages-page-body > .poster-grid { padding-top: 8px; }'
assert old in s
s=s.replace(old,new,1)
old2='.player-title-overlay { display: flex; flex-direction: column; gap: 7px; padding-top: 2px; max-width: 68%; }\n.player-title-name { font-size: 20px; font-weight: 600; text-shadow: 0 2px 5px #000; }\n.player-episode-copy { font-size: 12px; color: #c7c7c7; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 680px; }'
new2='.player-title-overlay { position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 4px; max-width: 70vw; z-index: 4; pointer-events: none; }\n.player-title-name { font-size: 16px; font-weight: 600; text-shadow: 0 2px 5px #000; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70vw; }\n.player-episode-copy { font-size: 11px; color: #c7c7c7; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 680px; }'
assert old2 in s
s=s.replace(old2,new2,1)
open(p,'w').write(s)
print('css updated')
PY

python3 - <<'PY'
p='app/frontend/src/styles.css'
s=open(p).read()
old='  .language-controls { flex-direction: column; gap: 14px; padding-left: 18px; padding-right: 18px; }'
new='  .language-controls { position: static; width: 100%; flex-direction: column; gap: 14px; padding: 10px 18px 8px; margin: 0; }\n  .languages-page-body > .language-note { display: block; }'
assert old in s
s=s.replace(old,new,1)
old2='  .player-title-overlay { max-width: 80%; }'
new2='  .player-title-overlay { bottom: 66px; max-width: 88%; }\n  .player-title-name { max-width: 88vw; font-size: 14px; }'
assert old2 in s
s=s.replace(old2,new2,1)
open(p,'w').write(s)
print('mobile updated')
PY

cd app/frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null && echo WEB_OK
cd /workspace && rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__ && du -sh app
exit
cd app/frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null && echo WEB_OK
cd /workspace && rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__ && du -sh app
exit
python3 - <<'PY'
p='app/frontend/src/styles.css'
s=open(p).read()
old='  position: absolute; top: 41px; right: 0; width: 520px; background: rgba(10,10,10,.98);'
new='  position: absolute; top: 41px; left: 0; width: 520px; background: rgba(10,10,10,.98);'
assert old in s
s=s.replace(old,new,1)
old2='.language-option-menu { position: absolute; z-index: 320; right: 0; top: calc(100% + 4px); width: 100%; max-height: 520px; overflow-y: auto; background: #0b0b0b; border: 1px solid rgba(255,255,255,.2); box-shadow: 0 16px 38px rgba(0,0,0,.7); padding: 5px 0; }'
new2='.language-option-menu { position: absolute; z-index: 320; right: 0; top: calc(100% + 4px); width: min(320px, 100%); max-height: 520px; overflow-y: auto; background: #0b0b0b; border: 1px solid rgba(255,255,255,.2); box-shadow: 0 16px 38px rgba(0,0,0,.7); padding: 5px 0; }'
assert old2 in s
s=s.replace(old2,new2,1)
open(p,'w').write(s)
print('updated')
PY

cd app/frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null && echo WEB_OK
cd /workspace && rm -rf app/frontend/node_modules app/frontend/dist app/backend/__pycache__ && du -sh app
exit
