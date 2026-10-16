"""Chromium regression check. Requires Playwright 1.58 and a seeded local QA server.

See docs/UI_MOBILE_20261016.md for isolated test data and server setup.
"""
from playwright.sync_api import sync_playwright, expect
from pathlib import Path
import json, sys
import argparse
from urllib.parse import urlsplit
parser=argparse.ArgumentParser(description='Check only an isolated, locally seeded mobile UI server.')
parser.add_argument('--base-url',default='http://127.0.0.1:18084')
parser.add_argument('--output',type=Path,default=Path('test-results/mobile'))
args=parser.parse_args()
BASE=args.base_url.rstrip('/')
if urlsplit(BASE).hostname not in ('127.0.0.1','localhost'):
 parser.error('Use a local test server with fictional seed_demo accounts only.')
OUT=args.output; OUT.mkdir(parents=True,exist_ok=True); report=[]; errors=[]
WIDTHS=[320,360,390,430,600,768,1024]
ROUTES={
 'employee':['/','/documents/','/documents/?mode=pending','/documents/?mode=search&q=A4','/compose/?kind=leave','/compose/?kind=office','/compose/?kind=stock','/documents/1/','/calendar/','/welfare/','/policy/','/account/','/notices/','/calendar/absence/new/'],
 'accounting':['/balances/','/company-holidays/','/regulations/','/regulations/?tab=annual','/regulations/?tab=benefits','/regulations/?tab=awards','/balances/recalculate/','/documents/?mode=accounting&kind=office','/balances/2/history/'],
 'admin':['/staff/','/staff/?department=개발팀','/backups/','/documents/?mode=all']}

def login(page,user):
 page.goto(BASE+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill('mobile-ui-test-only')
 page.locator('.auth-form button').click();page.wait_for_url(BASE+'/')

def measure(page,role,width,url):
 response=page.goto(BASE+url);page.evaluate('document.fonts.ready')
 assert response.status==200,(role,url,response.status)
 assert page.url.split('?')[0]==(BASE+url).split('?')[0],(role,url,page.url)
 info=page.evaluate('''() => ({viewport:innerWidth,scroll:document.documentElement.scrollWidth,
  smallInputs:[...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea')].filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<16).map(e=>[e.id,e.name,getComputedStyle(e).fontSize]),
  clipped:[...document.querySelectorAll('input:not([type=hidden]),select,textarea,.btn')].filter(e=>e.getClientRects().length&&!e.closest('.table-wrap')).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>[e.id,e.className])})''')
 row={'role':role,'width':width,'url':url,**info};report.append(row)
 assert info['scroll']<=info['viewport']+1,row
 if width<=1079: assert not info['smallInputs'],row
 assert not info['clipped'],row
 return row

with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 for role,routes in ROUTES.items():
  context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='ko-KR')
  page=context.new_page();page.on('pageerror',lambda e: errors.append(str(e)))
  page.on('response',lambda r: errors.append(f'{r.status} {r.url}') if r.status>=400 and '/static/' in r.url else None)
  login(page,role)
  for width in WIDTHS:
   page.set_viewport_size({'width':width,'height':844})
   for url in routes:
    measure(page,role,width,url)
   print(role,width,'OK',flush=True)
  page.set_viewport_size({'width':390,'height':844});page.goto(BASE+'/')
  page.locator('[data-mobile-menu-open]').click()
  expect(page.locator('#mobile-navigation')).to_be_visible()
  expect(page.locator('#mobile-navigation [data-mobile-menu-close]')).to_be_focused()
  if role=='employee': assert page.locator('#mobile-navigation a[href="/staff/"]').count()==0
  if role=='admin':
   menu=page.locator('#mobile-navigation')
   menu.locator('a[href="/backups/"]').scroll_into_view_if_needed()
   expect(menu.locator('a[href="/backups/"]')).to_be_visible()
  # Escape restores focus and navigation to its desktop location.
  page.keyboard.press('Escape');expect(page.locator('[data-mobile-menu-open]')).to_be_focused()
  assert page.locator('body > #workspace-navigation').count()==1
  page.locator('[data-mobile-menu-open]').click()
  page.set_viewport_size({'width':1366,'height':900});expect(page.locator('#mobile-navigation')).not_to_be_visible()
  expect(page.locator('body > #workspace-navigation')).to_be_visible()
  # Compare the desktop pixels with the original desktop files and markup.
  for width in [1080,1366,1920,2560]:
   page.set_viewport_size({'width':width,'height':900})
   for url in (['/','/documents/','/compose/','/documents/1/'] if role=='employee' else routes[:2]):
    measure(page,role,width,url)
    page.locator('.topbar-date').evaluate_all('(els)=>els.forEach(e=>e.textContent="2026.10.16")')
    before=page.screenshot(full_page=True,animations='disabled')
    page.evaluate('''() => {
      document.querySelector('link[href*="mobile.css"]').remove();
      document.querySelectorAll('.mobile-menu-toggle,.mobile-brand,.mobile-tabbar,.mobile-calendar-agenda,.mobile-selection-label,#mobile-navigation').forEach(e=>e.remove());
    }''')
    assert before==page.screenshot(full_page=True,animations='disabled'),('desktop pixels changed',role,width,url)
  context.close()
 # Authentication screens, without authenticated redirects.
 context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='ko-KR')
 page=context.new_page();page.on('pageerror',lambda e: errors.append(str(e)))
 for width in WIDTHS:
  page.set_viewport_size({'width':width,'height':844})
  for url in ['/login/','/signup/']:
   measure(page,'anonymous',width,url)
 # Navigation works even with JS disabled.
 context.close();context=browser.new_context(java_script_enabled=False,viewport={'width':360,'height':800})
 page=context.new_page();login(page,'employee')
 expect(page.locator('body > #workspace-navigation')).to_be_visible()
 assert page.locator('body > #workspace-navigation a[href="/calendar/"]').is_visible()
 browser.close()
assert not errors,errors
result={'layout_checks':len(report),'desktop_pixel_comparisons':32,'menu_roles':['employee','accounting','admin'],'javascript_errors':errors,'checks':report}
(OUT/'matrix-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('PASS',len(report),'layouts; desktop pixels unchanged; menu close, resize, focus, permissions and no-JS fallback OK')
