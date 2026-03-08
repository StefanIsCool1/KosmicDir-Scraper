import FetchXHR as xhr


with xhr.sync_playwright() as playwright:
    xhr.responsepull(playwright, "https://www.mbaks.com")