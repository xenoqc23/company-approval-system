"""Exercise login/logout using only a local server with fictional seed_demo data."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:18085')
parser.add_argument('--output', type=Path, default=Path('test-results/authentication'))
args = parser.parse_args()
base = args.base_url.rstrip('/')
if urlsplit(base).hostname not in {'127.0.0.1', 'localhost'}:
    parser.error('Use an isolated local server and fictional seed_demo accounts only.')
args.output.mkdir(parents=True, exist_ok=True)
results = []


def fill_login(page, password='mobile-ui-test-only'):
    page.locator('[name=username]').fill('employee')
    page.locator('[name=password]').fill(password)


def submit(page):
    page.locator('[data-login-form] button[type=submit]').click()
    page.wait_for_url(base + '/')


def logout(page):
    page.locator('.topbar .logout').click()
    page.wait_for_url(base + '/login/')


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    for width in [390, 1366]:
        context = browser.new_context(
            viewport={'width': width, 'height': 844}, is_mobile=width == 390,
            has_touch=width == 390, locale='ko-KR')
        page = context.new_page()
        js_errors = []
        page.on('pageerror', lambda error: js_errors.append(str(error)))
        for cycle in range(4):
            response = page.goto(base + '/login/')
            assert 'no-store' in response.headers['cache-control']
            fill_login(page)
            submit(page)
            logout(page)
        results.append({'width': width, 'scenario': 'four login/logout/relogin cycles', 'passed': True})

        # A second tab logs in and out, leaving the first login form's token stale.
        page.goto(base + '/login/')
        original = page.locator('[name=csrfmiddlewaretoken]').input_value()
        other = context.new_page()
        other.goto(base + '/login/')
        fill_login(other)
        submit(other)
        logout(other)
        rejected = context.request.post(base + '/login/', form={
            'username': 'employee', 'password': 'mobile-ui-test-only',
            'csrfmiddlewaretoken': original,
        }, headers={'Origin': base, 'Referer': base + '/login/'}, max_redirects=0)
        assert rejected.status == 403, 'The stale POST must remain blocked by CSRF'
        fill_login(page)
        submit(page)
        results.append({'width': width, 'scenario': 'stale cross-tab form refreshed before POST', 'passed': True})
        logout(page)

        # Other applications on the same hostname can overwrite the default names.
        page.goto(base + '/login/')
        context.add_cookies([
            {'name': 'csrftoken', 'value': 'F' * 32, 'url': base},
            {'name': 'sessionid', 'value': 'foreign-app-session', 'url': base},
        ])
        fill_login(page)
        submit(page)
        results.append({'width': width, 'scenario': 'foreign default cookie names isolated', 'passed': True})
        logout(page)

        # A connection failure must allow retry without sending credentials.
        page.goto(base + '/login/')
        fill_login(page)
        page.route('**/login/csrf/', lambda route: route.abort())
        posts = []
        page.on('request', lambda request: posts.append(request.url)
                if request.method == 'POST' else None)
        page.locator('[data-login-form] button').click()
        expect(page.locator('[data-login-error]')).to_be_visible()
        expect(page.locator('[data-login-form] button')).to_be_enabled()
        assert not posts
        page.unroute('**/login/csrf/')
        submit(page)
        results.append({'width': width, 'scenario': 'refresh network failure and retry', 'passed': True})
        logout(page)

        # Going back to an earlier login page is safe without reusing a stale token.
        page.goto(base + '/login/')
        fill_login(page)
        submit(page)
        logout(page)
        page.go_back()
        page.goto(base + '/login/')
        fill_login(page)
        submit(page)
        results.append({'width': width, 'scenario': 'login after navigation history', 'passed': True})
        assert not js_errors, js_errors
        context.close()

    # The normal GET/POST flow also works with JavaScript disabled.
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    for _ in range(3):
        page.goto(base + '/login/')
        fill_login(page)
        submit(page)
        logout(page)
    results.append({'scenario': 'three native form cycles without JavaScript', 'passed': True})
    context.close()
    browser.close()

report = {'passed': len(results), 'results': results, 'javascript_errors': []}
(args.output / 'browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
