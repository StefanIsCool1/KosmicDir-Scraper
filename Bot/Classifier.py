import FetchXHR as xhr


with xhr.sync_playwright() as playwright:
    xhr.xhrpull(playwright, "https://my.mbaks.com/eBizUI/directory/CompanyDirectory")