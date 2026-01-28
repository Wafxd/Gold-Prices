import re
import urllib3
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Disable warning SSL (kadang Galeri24 bermasalah SSL chain di beberapa network)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://galeri24.co.id/harga-emas"  # fragment #... tidak perlu untuk requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.7,en;q=0.6",
}

BULAN_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12
}

def clean_currency(price_str: str) -> int:
    """Rp1.555.000 -> 1555000"""
    if not price_str:
        return 0
    digits = re.sub(r"[^\d]", "", str(price_str))
    return int(digits) if digits else 0

def clean_gram(gram_str: str) -> float:
    """'0.5' -> 0.5"""
    if not gram_str:
        return 0.0
    s = re.sub(r"[^\d\.,]", "", str(gram_str)).replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def parse_tanggal_update(text: str) -> str:
    """
    Ambil dari: "Diperbarui Selasa, 27 Januari 2026"
    fallback: yyyy-mm-dd hari ini
    """
    # cari "27 Januari 2026"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.IGNORECASE)
    if not m:
        return datetime.now().strftime("%Y-%m-%d")

    d = int(m.group(1))
    bulan = m.group(2).lower()
    y = int(m.group(3))
    if bulan not in BULAN_ID:
        return datetime.now().strftime("%Y-%m-%d")

    try:
        return datetime(y, BULAN_ID[bulan], d).strftime("%Y-%m-%d")
    except:
        return datetime.now().strftime("%Y-%m-%d")

def crawl_g24_only() -> list[dict]:
    print(f"Ambil data G24 dari: {URL}")
    resp = requests.get(URL, headers=HEADERS, verify=False, timeout=25)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # target persis: <div id="GALERI 24">
    container = soup.find("div", id="GALERI 24")
    if not container:
        raise RuntimeError("Container <div id='GALERI 24'> tidak ditemukan. Struktur halaman mungkin berubah / belum ke-render.")

    # tanggal update ada di div: class "text-lg font-semibold mb-4"
    date_elem = container.find("div", class_=re.compile(r"\bfont-semibold\b"))
    tanggal = parse_tanggal_update(date_elem.get_text(" ", strip=True) if date_elem else "")

    # header row punya "Berat", jadi kita skip
    # baris data adalah div dengan class mengandung 'grid-cols-5' + punya 3 kolom utama (berat/jual/buyback)
    rows = container.find_all("div", class_=re.compile(r"\bgrid-cols-5\b"))

    data = []
    for row in rows:
        txt = row.get_text(" ", strip=True)
        if not txt:
            continue
        # skip header
        if "Berat" in txt and "Harga Jual" in txt:
            continue

        cols = row.find_all("div", recursive=False)
        if len(cols) < 3:
            continue

        gram_txt = cols[0].get_text(strip=True)
        jual_txt = cols[1].get_text(strip=True)
        buyback_txt = cols[2].get_text(strip=True)

        gram = clean_gram(gram_txt)
        harga_beli = clean_currency(jual_txt)        # Harga Jual = harga beli customer
        harga_buyback = clean_currency(buyback_txt)  # Harga Buyback

        # filter noise
        if gram <= 0 or (harga_beli == 0 and harga_buyback == 0):
            continue

        data.append({
            "Vendor": "GALERI 24",
            "Tanggal": tanggal,
            "Gramasi": gram,
            "Harga Beli": harga_beli,
            "Harga Buyback": harga_buyback
        })

    # dedup (kadang ada baris kebaca dobel)
    # key: (Gramasi)
    dedup = {}
    for r in data:
        dedup[r["Gramasi"]] = r
    result = [dedup[k] for k in sorted(dedup.keys())]

    print(f"Berhasil ambil {len(result)} baris.")
    return result

def main():
    data = crawl_g24_only()
    df = pd.DataFrame(data, columns=["Vendor", "Tanggal", "Gramasi", "Harga Beli", "Harga Buyback"])
    df = df.sort_values("Gramasi").reset_index(drop=True)

    filename = f"Harga_GALERI24_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df.to_excel(filename, index=False)

    print(f"SUKSES -> {filename}")
    print(df)

if __name__ == "__main__":
    main()
