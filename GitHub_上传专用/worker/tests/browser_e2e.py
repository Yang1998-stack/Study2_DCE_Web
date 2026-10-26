"""Optional UI verification: start node worker/tests/serve-browser.mjs first. No external POSTs."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

base = 'http://127.0.0.1:8788'
with sync_playwright() as p:
    browser = p.chromium.launch()
    for group in range(1, 5):
        context = browser.new_context(viewport={'width': 390 if group % 2 else 1440, 'height': 900})
        page = context.new_page()
        failures = []
        page.on('pageerror', lambda error: failures.append(str(error)))
        page.goto(base + '/admin')
        page.locator('#username').fill('researcher')
        page.locator('#password').fill('local-test-password-never-production')
        page.locator('#login-form button').click()
        expect(page.locator('#demo')).to_be_visible()
        page.locator('#demo-group').select_option(str(group))
        page.locator('#demo-block').select_option('A' if group % 2 else 'B')
        page.locator('#demo').click()
        expect(page.locator('.study-picture')).to_be_visible()
        image = page.locator('.study-picture')
        assert ('chart' if group % 2 else 'nature') in image.get_attribute('src')
        assert page.locator('.disclosure').count() == int(group >= 3)
        page.locator('#next').click()
        expect(page.get_by_text('读懂这几项商品信息')).to_be_visible()
        page.locator('#next').click()
        for i in range(8):
            expect(page.locator('.products')).to_be_visible()
            assert page.locator('#next').is_disabled()
            for kind in ['environment', 'quality']:
                page.locator(f'.document-link[data-kind="{kind}"][data-alternative="A"]').click()
                expect(page.locator('#detail-dialog')).to_be_visible()
                expect(page.locator('.simulation-notice')).to_be_visible()
                page.locator('#detail-close').click()
            if i == 2:
                page.reload()
                expect(page.locator('.products')).to_be_visible()
            page.locator('[data-choice="'+['A','B','N'][i % 3]+'"]').click()
            with page.expect_response(lambda r: '/api/answer' in r.url and r.request.method == 'POST') as saved:
                page.locator('#next').click()
            assert saved.value.status == 200
            page.wait_for_function('!busy')
        expect(page.locator('#age')).to_be_visible()
        page.locator('#age').fill('24')
        for field, value in {'gender':'male','education':'college','online_purchase':'monthly1','plant_based_purchase':'unsure','manip_visual':'chart','manip_ai':'no'}.items():
            page.locator('#'+field).select_option(value)
        page.locator('#next').click()
        expect(page.get_by_text('感谢您的参与')).to_be_visible()
        page.reload()
        expect(page.get_by_text('感谢您的参与')).to_be_visible()
        assert not failures, failures
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'horizontal overflow'
        Path('.worker-build').mkdir(exist_ok=True)
        page.screenshot(path=f'.worker-build/browser-G{group}.png', full_page=True)
        context.close()
    browser.close()
print('PASS: 四组广告、桌面/手机、详情、8题、刷新恢复、最终问卷与后台登录。')
