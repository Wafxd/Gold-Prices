import re
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL = "https://hrtagold.id/id/gold-price"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.7,en;q=0.6",
}

def clean_currency(price_str: str) -> int:
    """'Rp 364.500' -> 364500"""
    if not price_str:
        return 0
    digits = re.sub(r"[^\d]", "", str(price_str))
    return int(digits) if digits else 0

def clean_gram(gram_str: str) -> float:
    """'0.1 gr' / '0.1\xa0gr' -> 0.1"""
    if not gram_str:
        return 0.0
    s = str(gram_str).replace("\xa0", " ").strip().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except:
        return 0.0

def fetch_html_rendered(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers=HEADERS)

        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # tunggu sampai tabel muncul (ini kunci)
        page.wait_for_selector('table[data-slot="table"]', timeout=60_000)

        # sedikit delay biar isi tabel lengkap
        page.wait_for_timeout(1500)

        html = page.content()
        browser.close()
        return html

def crawl_hartadinata() -> list[dict]:
    print(f"Sedang mengambil data Hartadinata dari: {URL} ... (Playwright)")

    html = fetch_html_rendered(URL)
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one('table[data-slot="table"]')
    if not table:
        raise RuntimeError("Tabel masih tidak ditemukan. (selector table[data-slot='table'])")

    tbody = table.select_one('tbody[data-slot="table-body"]') or table.find("tbody")
    if not tbody:
        raise RuntimeError("tbody tidak ditemukan.")

    rows = tbody.select('tr[data-slot="table-row"]')

    data_list = []
    current_category = "General"
    tanggal = datetime.now().strftime("%Y-%m-%d")

    for row in rows:
        cols = row.select('td[data-slot="table-cell"]')
        if not cols:
            continue

        # kategori: 1 kolom, colspan=3
        if len(cols) == 1 and (cols[0].get("colspan") == "3" or cols[0].get("colspan") == 3):
            current_category = cols[0].get_text(" ", strip=True).title()
            continue

        # data: minimal 3 kolom
        if len(cols) >= 3:
            gram_txt = cols[0].get_text(" ", strip=True)
            dasar_txt = cols[1].get_text(" ", strip=True)
            buyback_txt = cols[2].get_text(" ", strip=True)

            gram = clean_gram(gram_txt)
            harga_beli = clean_currency(dasar_txt)       # Harga Dasar
            harga_buyback = clean_currency(buyback_txt)  # Buyback

            if gram > 0:
                data_list.append({
                    "Vendor": f"HARTADINATA ({current_category})",
                    "Tanggal": tanggal,
                    "Gramasi": gram,
                    "Harga Beli": harga_beli,
                    "Harga Buyback": harga_buyback,
                })

    # dedup (kadang dobel)
    dedup = {}
    for r in data_list:
        key = (r["Vendor"], r["Gramasi"])
        dedup[key] = r

    out = [dedup[k] for k in sorted(dedup.keys(), key=lambda x: (x[0], x[1]))]
    print(f"Berhasil mendapatkan {len(out)} data.")
    return out

def main():
    print("=== START HARTADINATA CRAWLER (PLAYWRIGHT) ===\n")

    try:
        data = crawl_hartadinata()
    except Exception as e:
        print(f"[ERROR] {e}")
        print("\nGAGAL mengambil data.")
        return

    df = pd.DataFrame(data)
    df = df.sort_values(by=["Vendor", "Gramasi"]).reset_index(drop=True)

    filename = f"Harga_Hartadinata_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df.to_excel(filename, index=False)

    print("\n" + "="*40)
    print(f"SUKSES! Data tersimpan di: {filename}")
    print("="*40)
    print(df)

if __name__ == "__main__":
    main()
