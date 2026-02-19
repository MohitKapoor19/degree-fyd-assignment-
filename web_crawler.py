import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import time
import json
import os
import threading

BASE_URL = "https://degreefyd.com"
SITEMAP_INDEX = f"{BASE_URL}/sitemap.xml"
OUTPUT_FILE = "degreefyd_data.jsonl"

HEADERS = {
    "User-Agent": "DegreefydRAGBot/1.0 (+contact: youremail@example.com)"
}

CRAWL_DELAY = 1.0
MAX_WORKERS = 5
visited_lock = threading.Lock()
visited_urls = set()

DISALLOWED_PATHS = [
    "/checkout/", "/cart/", "/dashboard/", "/enquiry/"
]

# --------------------------
# Helpers
# --------------------------

def is_allowed(url):
    if not url.startswith(BASE_URL):
        return False
    for path in DISALLOWED_PATHS:
        if path in url:
            return False
    return True


def get_xml_locs(xml_url):
    try:
        r = requests.get(xml_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "xml")
        return [loc.text.strip() for loc in soup.find_all("loc")]
    except:
        return []


def get_all_sitemap_urls():
    print("Fetching sitemap index...")
    sitemap_urls = get_xml_locs(SITEMAP_INDEX)

    all_page_urls = []

    for sm in sitemap_urls:
        print("Reading:", sm)
        urls = get_xml_locs(sm)
        all_page_urls.extend(urls)

    return list(set(all_page_urls))


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script","style","nav","footer",
        "header","aside","noscript","svg"
    ]):
        tag.decompose()

    main = soup.find("main")
    if main:
        text = main.get_text(" ")
    else:
        text = soup.get_text(" ")

    return " ".join(text.split())


def detect_page_type(url):
    if "college" in url:
        return "college"
    if "course" in url:
        return "course"
    if "exam" in url:
        return "exam"
    if "blog" in url:
        return "blog"
    if "location" in url:
        return "location"
    if "comparison" in url:
        return "comparison"
    return "page"


def crawl_page(url):
    global visited_urls

    with visited_lock:
        if url in visited_urls:
            return None
        visited_urls.add(url)

    if not is_allowed(url):
        return None

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None

        content = clean_html(r.text)

        return {
            "url": url,
            "type": detect_page_type(url),
            "content": content
        }

    except:
        return None
    finally:
        time.sleep(CRAWL_DELAY)


# --------------------------
# Main
# --------------------------

def main():
    urls = get_all_sitemap_urls()

    print(f"Total URLs found: {len(urls)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(crawl_page, url): url for url in urls}

            for future in tqdm(as_completed(futures), total=len(futures)):
                result = future.result()
                if result and result["content"]:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")

    print("Crawl completed.")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
