"""Exercise the admin/representative/signup flows only against a disposable local fixture."""
import argparse,json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18091');p.add_argument('--password-file',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('test-results/representatives-browser'));a=p.parse_args()
base=a.base_url.rstrip('/');assert urlsplit(base).hostname in {'localhost','127.0.0.1'}
pw=a.password_file.read_text();a.output.mkdir(parents=True,exist_ok=True);errors=[];assets=[]
def fits(page):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),page.url
def login(page,user):
    page.goto(base+'/login/');page.locator('[name=username]').fill(user);page.locator('[name=password]').fill(pw)
    page.locator('[data-login-form] button[type=submit]').click();page.wait_for_url(base+'/')
def card(page,user):return page.locator('.staff-card').filter(has=page.locator('.staff-card-head small',has_text=user))
def submit(page,form):
    form.get_by_role('button').click();expect(page.locator('#confirmation')).to_be_visible()
    page.locator('#confirmation-go').click();page.wait_for_load_state('networkidle')
with sync_playwright() as pwtool:
    b=pwtool.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    c=b.new_context(viewport={'width':1366,'height':950},locale='ko-KR',timezone_id='Asia/Seoul');page=c.new_page()
    page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:assets.append(r.url) if '/static/' in r.url and r.status>=400 else None)
    login(page,'admin');page.goto(base+'/staff/?department=전략기획팀');target=card(page,'representative')
    target.locator('.representative-settings summary').click();form=target.locator('.representative-form')
    expect(form.locator('[name=show_birthday]')).to_be_checked();expect(form.locator('[name=view_documents]')).not_to_be_checked()
    submit(page,form);expect(page.locator('.staff-tabs .selected')).to_contain_text('대표이사실')
    expect(card(page,'representative')).to_contain_text('현재 조회 전용');fits(page)
    page.screenshot(path=str(a.output/'admin-representative-desktop.png'),full_page=True)
    # Replacement is explicit and restores the former assignment.
    page.goto(base+'/staff/?department=전략기획팀');target=card(page,'candidate2');target.locator('.representative-settings summary').click()
    form=target.locator('.representative-form');expect(form.locator('[name=replace_confirm]')).to_have_attribute('required','');form.locator('[name=replace_confirm]').check();submit(page,form)
    expect(card(page,'candidate2')).to_contain_text('회사 대표 설정 저장')
    page.goto(base+'/staff/?department=전략기획팀');target=card(page,'representative');target.locator('.representative-settings summary').click();form=target.locator('.representative-form');form.locator('[name=replace_confirm]').check();form.locator('[name=view_documents]').check();submit(page,form)
    # Relative navigation includes repeated forward/back and year transitions.
    page.goto(base+'/welfare/?tab=birthdays&year=2026&month=12');page.get_by_role('link',name='다음 달 생일',exact=True).click();expect(page.locator('.birthday-heading h2')).to_have_text('2027년 1월 생일자')
    page.get_by_role('link',name='다음 달 생일',exact=True).click();expect(page.locator('.birthday-heading h2')).to_have_text('2027년 2월 생일자')
    for label,heading in [('이전 달 생일','2027년 1월 생일자'),('이전 달 생일','2026년 12월 생일자')]:
        page.get_by_role('link',name=label,exact=True).click();expect(page.locator('.birthday-heading h2')).to_have_text(heading)
    page.get_by_role('link',name='이번 달 생일',exact=True).click();expect(page.locator('.birthday-heading h2')).to_have_text('2026년 10월 생일자')
    for width in [320,390,768,1366]:
        page.set_viewport_size({'width':width,'height':950});page.goto(base+'/staff/?department=대표이사실');fits(page)
        page.screenshot(path=str(a.output/f'admin-role-{width}.png'),full_page=True)
        rc=b.new_context(viewport={'width':width,'height':900},locale='ko-KR',timezone_id='Asia/Seoul',is_mobile=width<600,has_touch=width<1080);rp=rc.new_page();rp.on('pageerror',lambda e:errors.append(str(e)))
        login(rp,'representative');expect(rp.locator('.main')).to_contain_text('회사 대표 · 조회 전용');expect(rp.locator('.mint-balance')).to_have_count(0);expect(rp.locator('.mint-quick')).to_have_count(0);fits(rp)
        expect(rp.locator('.birthday-banner')).to_contain_text('가상대표님')
        rp.screenshot(path=str(a.output/f'representative-home-{width}.png'),full_page=True)
        rp.goto(base+'/documents/?mode=all');expect(rp.locator('.page-heading h1')).to_have_text('전체 문서');expect(rp.get_by_role('link',name='새 기안 작성')).to_have_count(0);fits(rp)
        response=rp.goto(base+'/compose/');assert response.status==403
        rp.goto(base+'/welfare/');fits(rp);expect(rp.get_by_role('link',name='이전 달 생일',exact=True)).to_be_visible()
        rp.screenshot(path=str(a.output/f'birthday-months-{width}.png'),full_page=True)
        rp.goto(base+'/signup/');fits(rp)
        assert '대표이사실' not in rp.locator('[name=department]').inner_text()
        assert '대표' not in rp.locator('[name=rank]').inner_text()
        expect(rp.locator('[name=department] option')).to_have_count(6);expect(rp.locator('[name=rank] option')).to_have_count(7)
        rp.screenshot(path=str(a.output/f'signup-{width}.png'),full_page=True);rc.close()
    c.close();b.close()
assert not errors,errors
assert not assets,assets
result={'passed':True,'viewports':[320,390,768,1366],'admin_designation_and_explicit_replacement':True,'relative_birthday_months':True,'ordinary_signup_preserved':True,'representative_readonly':True,'birthday_banner':True,'js_errors':errors,'failed_assets':assets}
(a.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result))
