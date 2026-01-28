import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import re
import urllib3

# Disable warning SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

def clean_currency(price_str):
    """Mengubah format 'Rp 1.724.700' menjadi integer 1724700"""
    if not price_str: return 0
    clean_str = re.sub(r'[^\d]', '', str(price_str))
    return int(clean_str) if clean_str else 0

def clean_gram_from_title(title):
    """Ekstrak angka gram dari judul produk katalog."""
    if not title: return 0.0
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:gram|gr)', title.lower())
    if match:
        num_str = match.group(1).replace(',', '.')
        return float(num_str)
    return 0.0

def clean_gram_simple(gram_str):
    """Membersihkan format '0,5 Gram' dari tabel menjadi 0.5 (float)"""
    if not gram_str: return 0.0
    # Ambil angka saja, buang teks "Gram" dan whitespace
    clean = re.sub(r'[^\d,.]', '', str(gram_str)).replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

def crawl_ubs_complete():
    print("=== MULAI CRAWLING UBS LIFESTYLE (FIXED BUYBACK) ===")
    
    # --- STEP 1: AMBIL HARGA JUAL (Dari Katalog Search) ---
    url_catalog = "https://ubslifestyle.com/products/?s=classic"
    print(f"[1/2] Mengambil Katalog Harga Beli dari: {url_catalog}...")
    
    catalog_data = {} # Dictionary {gram: harga_beli}
    
    try:
        response = requests.get(url_catalog, headers=HEADERS, verify=False, timeout=30)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        product_cards = soup.find_all('div', class_='as-producttile')
        
        for card in product_cards:
            title_tag = card.find('h3', class_='as-producttile-name')
            if not title_tag: continue
            
            title_text = title_tag.get_text(strip=True)
            gram = clean_gram_from_title(title_text)
            
            if gram == 0: continue 
            
            price_tag = card.find('span', class_='woocommerce-Price-amount')
            if price_tag:
                price = clean_currency(price_tag.get_text())
                catalog_data[gram] = price
                print(f"   -> Katalog: {gram}g = Rp {price:,}")
                
    except Exception as e:
        print(f"   [Error Catalog] {e}")

    # --- STEP 2: AMBIL HARGA BUYBACK (Dari Link Buyback Khusus) ---
    url_buyback = "https://ubslifestyle.com/harga-buyback-hari-ini/"
    print(f"\n[2/2] Mengambil Daftar Buyback dari: {url_buyback}...")
    
    buyback_data = {} # Dictionary {gram: harga_buyback}
    
    try:
        response = requests.get(url_buyback, headers=HEADERS, verify=False, timeout=30)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Cari tabel (biasanya tabel pertama atau yang punya class 'table-price')
        table = soup.find('table')
        
        if table:
            # Cari body tabel
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
            else:
                rows = table.find_all('tr')

            for row in rows:
                cols = row.find_all('td')
                
                # PERBAIKAN DI SINI:
                # Kolom 0 = Gramasi
                # Kolom 1 = Harga Beli
                # Kolom 2 = Harga Buyback (Target Kita)
                if len(cols) >= 3: 
                    gram_txt = cols[0].get_text(strip=True)     # "0.05 Gram"
                    # price_beli_txt = cols[1].get_text(strip=True) 
                    buyback_txt = cols[2].get_text(strip=True)  # "Rp136.000"
                    
                    gram = clean_gram_simple(gram_txt)
                    price_bb = clean_currency(buyback_txt)
                    
                    if gram > 0:
                        buyback_data[gram] = price_bb
                        # print(f"      Debug: {gram}g -> Buyback Rp {price_bb:,}") # Uncomment utk debug
                        
        print(f"   -> Berhasil ambil {len(buyback_data)} data harga buyback.")
        
    except Exception as e:
        print(f"   [Error Buyback] {e}")

    # --- STEP 3: GABUNGKAN DATA (MERGE) ---
    print("\n[3/3] Menggabungkan Data...")
    final_list = []
    
    # Gunakan data gramasi dari Katalog sebagai acuan utama
    sorted_grams = sorted(catalog_data.keys())
    
    for gram in sorted_grams:
        harga_beli = catalog_data[gram]
        
        # Cari pasangan buyback-nya. Kalau tidak ada, set 0
        harga_buyback = buyback_data.get(gram, 0)
        
        final_list.append({
            'Vendor': 'UBS LIFESTYLE',
            'Tanggal': datetime.now().strftime('%Y-%m-%d'),
            'Gramasi': gram,
            'Harga Beli': harga_beli,
            'Harga Buyback': harga_buyback
        })
        
    return final_list

def main():
    data = crawl_ubs_complete()
    
    if data:
        df = pd.DataFrame(data)
        filename = f"Harga_UBS_{datetime.now().strftime('%Y%m%d')}.xlsx"
        df.to_excel(filename, index=False)
        
        print("\n" + "="*50)
        print(f"SUKSES! Data UBS tersimpan di: {filename}")
        print("="*50)
        print(df)
    else:
        print("Gagal mendapatkan data.")

if __name__ == "__main__":
    main()