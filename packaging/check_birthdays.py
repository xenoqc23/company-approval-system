"""Actual browser verification against an isolated local seed_demo installation."""
import argparse,json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit
from korean_lunar_calendar import KoreanLunarCalendar
from playwright.sync_api import expect,sync_playwright

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:18090')
parser.add_argument('--password-file',type=Path,required=True)
parser.add_argument('--output',type=Path,default=Path('test-results/birthdays-browser'))
args=parser.parse_args();base=args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'localhost','127.0.0.1'}:parser.error('Only local fictional fixtures are supported.')
password=args.password_file.read_text();args.output.mkdir(parents=True,exist_ok=True)
today=datetime.now(ZoneInfo('Asia/Seoul')).date();next_year,next_month=(today.year+1,1) if today.month==12 else (today.year,today.month+1)
converter=KoreanLunarCalendar();assert converter.setSolarDate(today.year,today.month,today.day)
errors=[];failed=[]
def fits(page):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),page.url
def login(page,user):
    page.goto(base+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill(password)
    page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/')
def save(page,user,month,day,calendar='solar',leap=False):
    page.goto(base+f'/balances/#birthday-employee-{user}');form=page.locator(f'#birthday-employee-{user} .birthday-editor')
    expect(page.locator(f'#birthday-employee-{user}')).to_have_attribute('open','')
    form.locator('[name=birthday_calendar]').select_option(calendar)
    form.locator('[name=birthday_month]').select_option(str(month));form.locator('[name=birthday_day]').select_option(str(day))
    if leap:form.locator('[name=birthday_lunar_leap]').check()
    form.get_by_role('button',name='생일 저장',exact=True).click();page.wait_for_url(base+'/balances/?*')
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    manager=browser.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul')
    page=manager.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:failed.append(r.url) if '/static/' in r.url and r.status>=400 else None)
    login(page,'accounting');page.goto(base+'/welfare/')
    expect(page.locator('.list-tabs a').first).to_have_text('생일자');expect(page.locator('.birthday-missing')).to_be_visible()
    save(page,2,today.month,today.day)
    save(page,3,converter.lunarMonth,converter.lunarDay,'lunar',converter.isIntercalation)
    save(page,4,next_month,1)
    # The management editor has original dates and supports invalid-date feedback.
    page.goto(base+'/balances/#birthday-employee-3');fits(page)
    expect(page.locator('#birthday-employee-3 [name=birthday_calendar]')).to_have_value('lunar')
    page.screenshot(path=str(args.output/'manager-editor-desktop.png'),full_page=True)
    page.goto(base+'/welfare/');expect(page.locator('.birthday-person.is-today')).to_have_count(2)
    page.get_by_role('link',name='다음 달 생일',exact=True).click();expect(page.locator('.birthday-heading h2')).to_have_text(f'{next_year}년 {next_month}월 생일자')
    expect(page.locator('.birthday-roster')).to_contain_text('박지훈')
    page.get_by_role('link',name='이번 달 생일',exact=True).click();page.screenshot(path=str(args.output/'birthday-list-desktop.png'),full_page=True)
    page.goto(base+'/welfare/?tab=awards');expect(page.locator('.award-celebration')).to_contain_text('연말 종무식에서 일괄 포상')
    expect(page.locator('table')).not_to_contain_text('대상일 도래');page.screenshot(path=str(args.output/'awards-desktop.png'),full_page=True)
    for width in [320,390,768,1366]:
        c=browser.new_context(viewport={'width':width,'height':900},locale='ko-KR',timezone_id='Asia/Seoul',is_mobile=width<600,has_touch=width<1080)
        p=c.new_page();p.on('pageerror',lambda e:errors.append(str(e)));p.on('response',lambda r:failed.append(r.url) if '/static/' in r.url and r.status>=400 else None)
        login(p,'employee');expect(p.locator('.birthday-banner')).to_contain_text('이서연님');expect(p.locator('.birthday-banner')).to_contain_text('김민준님');fits(p)
        p.screenshot(path=str(args.output/f'home-{width}.png'),full_page=False)
        p.goto(base+'/welfare/');expect(p.locator('.birthday-missing')).to_have_count(0);expect(p.locator('.birthday-person.is-today')).to_have_count(2);fits(p)
        p.screenshot(path=str(args.output/f'birthdays-{width}.png'),full_page=True)
        p.goto(base+'/signup/');p.locator('[name=birthday_calendar]').select_option('lunar');expect(p.locator('[name=birthday_lunar_leap]')).to_be_enabled();fits(p)
        p.screenshot(path=str(args.output/f'signup-{width}.png'),full_page=True)
        c.close()
    page.set_viewport_size({'width':390,'height':900});page.goto(base+'/balances/#birthday-employee-2');fits(page)
    page.screenshot(path=str(args.output/'manager-editor-390.png'),full_page=True)
    manager.close();browser.close()
assert not errors,errors
assert not failed,failed
result={'passed':True,'viewports':[320,390,768,1366],'manager_solar_lunar_save':True,'today_banner_multiple_names':True,'monthly_filters':True,'manager_only_missing':True,'year_end_awards':True,'js_errors':errors,'failed_assets':failed}
(args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result))
