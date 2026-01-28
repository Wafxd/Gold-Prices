import re
import urllib3
from datetime import datetime, date
from typing import Dict, List, Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.7,en;q=0.6",
}

BULAN_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12
}

NUM_ONLY_RE = re.compile(r"[^\d]")
GRAM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
RP_RE = re.compile(r"Rp\.?\s*([0-9][0-9\.\,]*)", re.IGNORECASE)

def today_iso() -> str:
    return date.today().isoformat()

def clean_currency(s: str) -> int:
    """'Rp 1.420.000.000' -> 1420000000"""
    if not s:
        return 0
    # kalau ada Rp, ambil grup angka dekat Rp dulu
    m = RP_RE.search(str(s))
    if m:
        digits = NUM_ONLY_RE.sub("", m.group(1))
        return int(digits) if digits else 0
    digits = NUM_ONLY_RE.sub("", str(s))
    return int(digits) if digits else 0

def clean_gram(s: str) -> float:
    """'0.1 gr' / '0,5' / '1' -> float"""
    if not s:
        return 0.0
    s = str(s).replace("\xa0", " ").strip().replace(",", ".")
    m = GRAM_RE.search(s)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except:
        return 0.0

def parse_tanggal_update(text: str) -> str:
    """Ambil tanggal dari teks: 'Diperbarui Selasa, 27 Januari 2026'"""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.IGNORECASE)
    if not m:
        return today_iso()
    d = int(m.group(1))
    bulan = m.group(2).lower()
    y = int(m.group(3))
    if bulan not in BULAN_ID:
        return today_iso()
    try:
        return date(y, BULAN_ID[bulan], d).isoformat()
    except:
        return today_iso()

# =========================
# Playwright helper
# =========================
def fetch_html_playwright(url: str, wait_selector: str = "body", wait_ms: int = 1200) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers=HEADERS)
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(wait_selector, timeout=60_000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
        return html

# =========================
# ANTAM (FIX)
# =========================
def antam_parse_table(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    tanggal = parse_tanggal_update(soup.get_text(" ", strip=True))
    rows = table.find_all("tr")
    out = []

    # ambil kolom harga pertama setelah gramasi
    for row in rows[1:]:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        gram_txt = tds[0].get_text(" ", strip=True)
        price_txt = tds[1].get_text(" ", strip=True)

        gram = clean_gram(gram_txt)
        price = clean_currency(price_txt)

        if gram > 0 and price > 0:
            out.append({
                "Vendor": "ANTAM",
                "Tanggal": tanggal,
                "Gramasi": gram,
                "Harga Beli": price,
                "Harga Buyback": 0
            })
    # dedup per gram
    dedup = {r["Gramasi"]: r for r in out}
    return [dedup[g] for g in sorted(dedup.keys())]

def antam_parse_fallback_regex(html: str) -> List[Dict]:
    """
    Fallback kalau tidak ada <table>:
    tangkap pola per 'row' yang biasanya tampil sebagai: [gram] ... Rp[price]
    Bisa tanpa kata 'gram'.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    tanggal = parse_tanggal_update(text)

    # cari kandidat gramasi umum, lalu cari Rp terdekat setelahnya
    # ini lebih robust dari pattern "gram"
    candidates = [
        0.5, 1, 2, 3, 5, 10, 25, 50, 100, 250, 500, 1000
    ]

    out = []
    for g in candidates:
        # coba cari " 0.5 " atau " 0,5 " dan ambil Rp setelahnya dekat-dekat
        g_str_dot = str(g).replace(".0", "")
        g_str_comma = g_str_dot.replace(".", ",")
        pat = re.compile(rf"(?<!\d)({re.escape(g_str_dot)}|{re.escape(g_str_comma)})(?!\d).{{0,80}}?(Rp\.?\s*[0-9][0-9\.\,]*)", re.IGNORECASE)
        m = pat.search(text)
        if m:
            gram = clean_gram(m.group(1))
            price = clean_currency(m.group(2))
            if gram > 0 and price > 0:
                out.append({
                    "Vendor": "ANTAM",
                    "Tanggal": tanggal,
                    "Gramasi": gram,
                    "Harga Beli": price,
                    "Harga Buyback": 0
                })

    dedup = {r["Gramasi"]: r for r in out}
    return [dedup[g] for g in sorted(dedup.keys())]

def crawl_antam() -> List[Dict]:
    url = "https://emasantam.id/harga-emas-antam-harian/"
    print(f"[ANTAM] Fetch: {url}")

    html = ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception:
        # fallback playwright
        html = fetch_html_playwright(url, wait_selector="body")

    # 1) coba parse table dari html yang didapat
    out = antam_parse_table(html)
    if out:
        print(f"[ANTAM] OK {len(out)} baris (from <table>)")
        return out

    # 2) kalau belum ada table, coba render pakai playwright lalu parse table lagi
    try:
        html2 = fetch_html_playwright(url, wait_selector="body")
        out2 = antam_parse_table(html2)
        if out2:
            print(f"[ANTAM] OK {len(out2)} baris (playwright + <table>)")
            return out2

        # 3) terakhir: regex fallback
        out3 = antam_parse_fallback_regex(html2)
        print(f"[ANTAM] OK {len(out3)} baris (regex fallback)")
        return out3

    except Exception as e:
        print(f"[ANTAM] WARNING: playwright gagal: {e}")
        out3 = antam_parse_fallback_regex(html)
        print(f"[ANTAM] OK {len(out3)} baris (regex fallback no-playwright)")
        return out3

# =========================
# GALERI 24 (vendor GALERI 24 saja)
# =========================
def crawl_g24() -> List[Dict]:
    url = "https://galeri24.co.id/harga-emas"
    print(f"[GALERI24] Fetch: {url}")

    r = requests.get(url, headers=HEADERS, verify=False, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    container = soup.find("div", id="GALERI 24")
    if not container:
        print("[GALERI24] WARNING: div id='GALERI 24' tidak ditemukan.")
        return []

    date_elem = container.find("div", class_=re.compile(r"\bfont-semibold\b"))
    tanggal = parse_tanggal_update(date_elem.get_text(" ", strip=True) if date_elem else "")

    rows = container.find_all("div", class_=re.compile(r"\bgrid-cols-5\b"))
    data = []
    for row in rows:
        txt = row.get_text(" ", strip=True)
        if not txt:
            continue
        if "Berat" in txt and "Harga Jual" in txt:
            continue
        cols = row.find_all("div", recursive=False)
        if len(cols) < 3:
            continue

        gram = clean_gram(cols[0].get_text(strip=True))
        jual = clean_currency(cols[1].get_text(strip=True))
        buyback = clean_currency(cols[2].get_text(strip=True))

        if gram > 0 and (jual > 0 or buyback > 0):
            data.append({
                "Vendor": "GALERI 24",
                "Tanggal": tanggal,
                "Gramasi": gram,
                "Harga Beli": jual,
                "Harga Buyback": buyback,
            })

    dedup = {d["Gramasi"]: d for d in data}
    out = [dedup[g] for g in sorted(dedup.keys())]
    print(f"[GALERI24] OK {len(out)} baris")
    return out

# =========================
# HARTADINATA (Playwright)
# =========================
def crawl_hartadinata() -> List[Dict]:
    url = "https://hrtagold.id/id/gold-price"
    print(f"[HARTADINATA] Fetch: {url} (Playwright)")

    html = fetch_html_playwright(url, wait_selector='table[data-slot="table"]', wait_ms=1500)
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one('table[data-slot="table"]')
    if not table:
        print("[HARTADINATA] WARNING: table tidak ditemukan.")
        return []

    tbody = table.select_one('tbody[data-slot="table-body"]') or table.find("tbody")
    if not tbody:
        print("[HARTADINATA] WARNING: tbody tidak ditemukan.")
        return []

    rows = tbody.select('tr[data-slot="table-row"]')

    tanggal = today_iso()
    current_category = "General"
    out: List[Dict] = []

    for row in rows:
        cols = row.select('td[data-slot="table-cell"]')
        if not cols:
            continue

        if len(cols) == 1 and (cols[0].get("colspan") == "3" or cols[0].get("colspan") == 3):
            current_category = cols[0].get_text(" ", strip=True).title()
            continue

        if len(cols) >= 3:
            gram = clean_gram(cols[0].get_text(" ", strip=True))
            dasar = clean_currency(cols[1].get_text(" ", strip=True))
            buyback = clean_currency(cols[2].get_text(" ", strip=True))

            if gram > 0:
                out.append({
                    "Vendor": f"HARTADINATA ({current_category})",
                    "Tanggal": tanggal,
                    "Gramasi": gram,
                    "Harga Beli": dasar,
                    "Harga Buyback": buyback,
                })

    dedup = {(r["Vendor"], r["Gramasi"]): r for r in out}
    out2 = [dedup[k] for k in sorted(dedup.keys(), key=lambda x: (x[0], x[1]))]
    print(f"[HARTADINATA] OK {len(out2)} baris")
    return out2

# =========================
# UBS (catalog + buyback merge)
# =========================
def clean_gram_from_title(title: str) -> float:
    if not title:
        return 0.0
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:gram|gr)\b", title.lower())
    if not m:
        return 0.0
    return clean_gram(m.group(1))

def crawl_ubs() -> List[Dict]:
    print("[UBS] Fetch catalog + buyback")

    url_catalog = "https://ubslifestyle.com/products/?s=classic"
    url_buyback = "https://ubslifestyle.com/harga-buyback-hari-ini/"

    catalog_data: Dict[float, int] = {}
    try:
        r = requests.get(url_catalog, headers=HEADERS, verify=False, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.find_all("div", class_="as-producttile")
        for card in cards:
            title_tag = card.find("h3", class_="as-producttile-name")
            if not title_tag:
                continue
            gram = clean_gram_from_title(title_tag.get_text(strip=True))
            if gram <= 0:
                continue
            price_tag = card.find("span", class_="woocommerce-Price-amount")
            if price_tag:
                price = clean_currency(price_tag.get_text(" ", strip=True))
                if price > 0:
                    catalog_data[gram] = price
    except Exception as e:
        print(f"[UBS] WARNING catalog gagal: {e}")

    buyback_data: Dict[float, int] = {}
    try:
        r = requests.get(url_buyback, headers=HEADERS, verify=False, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        table = soup.find("table")
        if table:
            tbody = table.find("tbody")
            rows = (tbody.find_all("tr") if tbody else table.find_all("tr"))
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 3:
                    gram = clean_gram(cols[0].get_text(strip=True))
                    bb = clean_currency(cols[2].get_text(strip=True))
                    if gram > 0 and bb > 0:
                        buyback_data[gram] = bb
    except Exception as e:
        print(f"[UBS] WARNING buyback gagal: {e}")

    tanggal = today_iso()
    out: List[Dict] = []
    for gram in sorted(catalog_data.keys()):
        out.append({
            "Vendor": "UBS LIFESTYLE",
            "Tanggal": tanggal,
            "Gramasi": gram,
            "Harga Beli": catalog_data.get(gram, 0),
            "Harga Buyback": buyback_data.get(gram, 0),
        })

    print(f"[UBS] OK {len(out)} baris")
    return out

# =========================
# MAIN: multi-sheet excel
# =========================
def main():
    print("=== START CRAWLER 4 VENDOR (MULTI SHEET) ===\n")

    antam = crawl_antam()
    g24 = crawl_g24()
    hrta = crawl_hartadinata()
    ubs = crawl_ubs()

    all_rows = antam + g24 + hrta + ubs
    if not all_rows:
        print("\nGAGAL: tidak ada data yang berhasil diambil.")
        return

    df_all = pd.DataFrame(all_rows, columns=["Vendor", "Tanggal", "Gramasi", "Harga Beli", "Harga Buyback"])
    df_all["Gramasi"] = pd.to_numeric(df_all["Gramasi"], errors="coerce")
    df_all["Harga Beli"] = pd.to_numeric(df_all["Harga Beli"], errors="coerce")
    df_all["Harga Buyback"] = pd.to_numeric(df_all["Harga Buyback"], errors="coerce")
    df_all = df_all.dropna(subset=["Gramasi"]).sort_values(["Vendor", "Gramasi"]).reset_index(drop=True)

    df_antam = pd.DataFrame(antam, columns=df_all.columns).sort_values(["Gramasi"]).reset_index(drop=True) if antam else pd.DataFrame(columns=df_all.columns)
    df_g24   = pd.DataFrame(g24,   columns=df_all.columns).sort_values(["Gramasi"]).reset_index(drop=True) if g24 else pd.DataFrame(columns=df_all.columns)
    df_hrta  = pd.DataFrame(hrta,  columns=df_all.columns).sort_values(["Vendor","Gramasi"]).reset_index(drop=True) if hrta else pd.DataFrame(columns=df_all.columns)
    df_ubs   = pd.DataFrame(ubs,   columns=df_all.columns).sort_values(["Gramasi"]).reset_index(drop=True) if ubs else pd.DataFrame(columns=df_all.columns)

    filename = f"Harga_Emas_4Vendor_{datetime.now().strftime('%Y%m%d')}.xlsx"
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df_all.to_excel(writer, index=False, sheet_name="ALL")
        df_antam.to_excel(writer, index=False, sheet_name="ANTAM")
        df_g24.to_excel(writer, index=False, sheet_name="GALERI24")
        df_hrta.to_excel(writer, index=False, sheet_name="HARTADINATA")
        df_ubs.to_excel(writer, index=False, sheet_name="UBS")

    print("\n" + "="*70)
    print(f"SUKSES! Data tersimpan di: {filename}")
    print("="*70)
    print("Ringkasan baris:")
    print(f"  ANTAM       : {len(df_antam)}")
    print(f"  GALERI24    : {len(df_g24)}")
    print(f"  HARTADINATA : {len(df_hrta)}")
    print(f"  UBS         : {len(df_ubs)}")
    print(f"  ALL         : {len(df_all)}")

if __name__ == "__main__":
    main()
