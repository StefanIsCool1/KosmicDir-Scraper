from playwright.sync_api import sync_playwright, Playwright
#import dependencies
import random
import time
def xhrpull(playwright: Playwright, link):
    xhr_list=[]
    browser = playwright.chromium.launch(headless=False)
    #no headless becauses lots of websites will stop this
    page = browser.new_page()
    # Only capture XHR + fetch
    def on_response(response):
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = response.json()
                # Look for directory-like keys
                if any(key in str(data).lower() for key in ["member", "user", "directory", "contact"]):
                    print("Likely directory data at:", response.url)
                    print(data)
            except:
                pass
    def human_scroll(page, scroll_target="body", times = 20):
        #purpose of this function is to bypass anti bot stuff
        for _ in range(times):
            distance = random.randint(300,600) 
            page.evaluate(f"""document.querySelector('{scroll_target}').scrollBy(0, {distance});""")
            page.mouse.wheel(0,distance)
            #add realism so idk cuz prob anti boy stuff is bad
            time.sleep(random.uniform(0.15,1))
        container = page.get_by_test_id("scrolling-container")
        container.hover()
        page.mouse.wheel(0, 300)
    page.on("response", on_response)
    page.goto(link)
    human_scroll(page, scroll_target='body')
    page.wait_for_timeout(2000)
    browser.close()