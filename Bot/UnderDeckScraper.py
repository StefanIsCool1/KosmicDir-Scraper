import FetchXHR as xhr
from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    xhr.responsepull(playwright, "https://www.mbaks.com")