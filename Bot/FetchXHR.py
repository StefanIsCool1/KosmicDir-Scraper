from playwright.sync_api import sync_playwright, Playwright
from urllib.parse import urlparse
#import dependencies
import random
import time
import json
import os
import threading

def find_directory_url(page, link):
    page.goto(link)
    # Grab all links from the page
    links = page.eval_on_selector_all("a", "els => els.map(el => ({text: el.innerText, href: el.href}))")
    # Check for directory first, then fallback to membership
    priority_keywords = ["directory", "find a member", "company directory", "member directory"]
    fallback_keywords = ["membership", "contractor"]
    
    # First pass - priority keywords
    for l in links:
        if any(kw in l["text"].lower() for kw in priority_keywords):
            print("Found directory link:", l["href"])
            return l["href"]
    
    # Second pass - fallback keywords
    for l in links:
        if any(kw in l["text"].lower() for kw in fallback_keywords):
            print("Found directory link:", l["href"])
            return l["href"]
    
    return link

def responsepull(playwright: Playwright, link):
    xhr_list=[]
    results = []
    done = threading.Event()
    idle_timer = None
    browser = playwright.chromium.launch(headless=False)
    #no headless becauses lots of websites will stop this
    page = browser.new_page()
    # Only capture XHR + fetch
    def reset_idle_timer():
        #purpose of this function is to save energy (called evertime a json response)
        nonlocal idle_timer
        if idle_timer:
            idle_timer.cancel()
        # Close browser after 2 seconds of no new JSON responses
        idle_timer = threading.Timer(2.0, done.set) # change this value here to change the amount of idle between json response before closure
        idle_timer.start()
    def on_response(response):
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = response.json()
                # Look for directory-like keys
                if any(key in str(data).lower() for key in ["member", "user", "directory", "contact"]):
                    print("Likely directory data at:", response.url)
                    print(data)
                    results.append({
                        "url": response.url,
                        "data": data
                    })
                    reset_idle_timer()
            except:
                pass
    def human_scroll(page, scroll_target="body", times = 20):
        #purpose of this function is to bypass anti bot stuff
        for _ in range(times):
            if done.is_set():
                break
            distance = random.randint(300,600)
            page.evaluate(f"""document.querySelector('{scroll_target}').scrollBy(0, {distance});""")
            page.mouse.wheel(0,distance)
            #add realism so idk cuz prob anti boy stuff is bad
            time.sleep(random.uniform(0.15,1))
        try:
            container = page.get_by_test_id("scrolling-container")
            container.hover()
            page.mouse.wheel(0, 300)
        except:
            #scrolling-container not found on this site, skip
            pass
    page.on("response", on_response)
    # Find and navigate to directory page
    directory_url = find_directory_url(page, link)
    page.goto(directory_url)
    page.wait_for_load_state("networkidle")
    reset_idle_timer() #starts regardless of page load
    human_scroll(page, scroll_target='body')
    # Wait until idle timer fires or 30 second max timeout
    done.wait(timeout=15)
    browser.close()
    # Save results to file

    print(f"Total results captured: {len(results)}")
    if not results:
        print("No JSON responses were captured!")

    domain = urlparse(link).netloc.replace(".", "_")

    
    current_dir = os.path.dirname(__file__)  # This is bot directory
    parent_dir = os.path.dirname(current_dir)  # This goes up one level above make sure parentg

    # Create Data-dump in the parent directory
    data_dump_dir = os.path.join(parent_dir, "Data-dump")

    # Create the directory if it doesn't exist
    os.makedirs(data_dump_dir, exist_ok=True)

    # Create the full file path
    output_path = os.path.join(data_dump_dir, f"{domain}.json")

    print(f"Attempting to save to: {output_path}")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=4)
    print(f"Saved {len(results)} responses to {output_path}")