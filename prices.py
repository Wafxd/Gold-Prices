import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import re
import urllib3
from playwright.sync_api import sync_playwright
import time

# --- KONFIGURASI GLOBAL ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

# --- HELPER FUNCTIONS ---
def clean_currency(price_str):
    if not price_str: return 0
    clean_str = re.sub(r'[^\d]', '', str(price_str))
    return int(clean_str) if clean_str else 0

def clean_gram(gram_str):
    if not gram_str: return 0.0
    s = str(gram_str).replace("\xa0", " ").strip()
    clean = re.sub(r'[^\d,.]', '', s).replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

# ==========================================
# 1. CRAWLER ANTAM (Requests)
# ==========================================
def crawl_antam():
    print(f"[1/4] Crawling ANTAM (Requests)...")
    url = "https://emasantam.id/harga-emas-antam-harian/"
    data = []
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table')
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    gram_txt = cols[0].get_text(strip=True)
                    price_txt = cols[1].get_text(strip=True)
                    if any(char.isdigit() for char in gram_txt):
                        data.append({
                            'Vendor': 'ANTAM',
                            'Tanggal': datetime.now().strftime('%Y-%m-%d'),
                            'Gramasi': clean_gram(gram_txt),
                            'Harga Beli': clean_currency(price_txt),
                            'Harga Buyback': 0 
                        })
    except Exception as e:
        print(f"   [Error Antam] {e}")
    return data

# ==========================================
# 2. CRAWLER UBS (Requests)
# ==========================================
def crawl_ubs():
    print(f"[2/4] Crawling UBS (Requests)...")
    final_list = []
    buyback_map = {}
    
    # A. Buyback
    try:
        res = requests.get("https://ubslifestyle.com/harga-buyback-hari-ini/", headers=HEADERS, verify=False, timeout=20)
        soup = BeautifulSoup(res.content, 'html.parser')
        table = soup.find('table')
        if table:
            tbody = table.find('tbody') or table
            for row in tbody.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) >= 3:
                    g = clean_gram(cols[0].get_text(strip=True))
                    p = clean_currency(cols[2].get_text(strip=True))
                    if g > 0: buyback_map[g] = p
    except Exception as e:
        print(f"   [Error UBS Buyback] {e}")

    # B. Catalog
    try:
        res = requests.get("https://ubslifestyle.com/products/?s=classic", headers=HEADERS, verify=False, timeout=20)
        soup = BeautifulSoup(res.content, 'html.parser')
        cards = soup.find_all('div', class_='as-producttile')
        temp_data = {}
        for card in cards:
            title = card.find('h3', class_='as-producttile-name')
            price = card.find('span', class_='woocommerce-Price-amount')
            if title and price:
                t_text = title.get_text(strip=True)
                match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:gram|gr)', t_text.lower())
                if match:
                    g = float(match.group(1).replace(',', '.'))
                    p = clean_currency(price.get_text())
                    temp_data[g] = {
                        'Vendor': 'UBS',
                        'Tanggal': datetime.now().strftime('%Y-%m-%d'),
                        'Gramasi': g,
                        'Harga Beli': p,
                        'Harga Buyback': buyback_map.get(g, 0)
                    }
        final_list = list(temp_data.values())
    except Exception as e:
        print(f"   [Error UBS Catalog] {e}")
        
    return final_list

# ==========================================
# 3 & 4. DYNAMIC SITES (Playwright)
# ==========================================
def crawl_dynamic_sites():
    data_hrta = []
    data_g24 = []
    
    print("[3/4] & [4/4] Membuka Browser untuk Hartadinata & Galeri 24...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # FIX UTAMA DISINI: ignore_https_errors=True
        # Ini bikin browser "tutup mata" kalau sertifikat SSL G24 error/expired
        context = browser.new_context(
            user_agent=HEADERS['User-Agent'],
            ignore_https_errors=True  
        )
        page = context.new_page()
        
        # --- A. CRAWL HARTADINATA ---
        try:
            print("   -> Mengakses Hartadinata...")
            page.goto("https://hrtagold.id/id/gold-price", timeout=60000, wait_until="domcontentloaded")
            try:
                page.wait_for_selector('table[data-slot="table"]', timeout=30000)
            except:
                print("      Timeout waiting for HRTA table.")
            
            soup = BeautifulSoup(page.content(), 'html.parser')
            rows = soup.find_all('tr', attrs={'data-slot': 'table-row'})
            current_cat = "General"
            
            for row in rows:
                cols = row.find_all('td', attrs={'data-slot': 'table-cell'})
                if len(cols) == 1 and cols[0].get('colspan') == '3':
                    current_cat = cols[0].get_text(strip=True).title()
                    continue
                if len(cols) >= 3:
                    g = clean_gram(cols[0].get_text(strip=True))
                    if g > 0:
                        data_hrta.append({
                            'Vendor': f'HARTADINATA ({current_cat})',
                            'Tanggal': datetime.now().strftime('%Y-%m-%d'),
                            'Gramasi': g,
                            'Harga Beli': clean_currency(cols[1].get_text(strip=True)),
                            'Harga Buyback': clean_currency(cols[2].get_text(strip=True))
                        })
            print(f"      Sukses: {len(data_hrta)} data Hartadinata.")
            
        except Exception as e:
            print(f"   [Error HRTA] {e}")

        # --- B. CRAWL GALERI 24 ---
        try:
            print("   -> Mengakses Galeri 24 (Bypass SSL)...")
            # Navigate ke G24
            page.goto("https://www.galeri24.co.id/harga-emas", timeout=60000, wait_until="domcontentloaded")
            
            try:
                # Tunggu elemen ID 'GALERI 24'
                page.wait_for_selector('//*[@id="GALERI 24"]', state="visible", timeout=30000)
                time.sleep(3) # Extra wait buat render angka
            except:
                print("      Timeout waiting for G24 container.")

            soup = BeautifulSoup(page.content(), 'html.parser')
            container = soup.find('div', id='GALERI 24')
            
            if container:
                rows = container.find_all('div', class_=re.compile(r'grid.*cols-5'))
                for row in rows:
                    if 'Berat' in row.get_text(): continue
                    cols = row.find_all('div', recursive=False)
                    if len(cols) >= 3:
                        g = clean_gram(cols[0].get_text(strip=True))
                        if g > 0:
                            data_g24.append({
                                'Vendor': 'GALERI 24',
                                'Tanggal': datetime.now().strftime('%Y-%m-%d'),
                                'Gramasi': g,
                                'Harga Beli': clean_currency(cols[1].get_text(strip=True)),
                                'Harga Buyback': clean_currency(cols[2].get_text(strip=True))
                            })
                
                # Dedup
                data_g24 = list({d['Gramasi']: d for d in data_g24}.values())
                print(f"      Sukses: {len(data_g24)} data Galeri 24.")
            else:
                print("      Container GALERI 24 tidak ketemu di HTML.")
                
        except Exception as e:
            print(f"   [Error G24] {e}")

        browser.close()
        
    return data_hrta, data_g24

# ==========================================
# MAIN
# ==========================================
def main():
    print("\n=== START CRAWLING ===")
    
    # 1. Crawl
    d_antam = crawl_antam()
    d_ubs = crawl_ubs()
    d_hrta, d_g24 = crawl_dynamic_sites()
    
    # 2. DataFrame
    df_antam = pd.DataFrame(d_antam)
    df_ubs = pd.DataFrame(d_ubs)
    df_hrta = pd.DataFrame(d_hrta)
    df_g24 = pd.DataFrame(d_g24)
    
    # 3. Sort
    if not df_antam.empty: df_antam = df_antam.sort_values(by='Gramasi')
    if not df_ubs.empty: df_ubs = df_ubs.sort_values(by='Gramasi')
    if not df_hrta.empty: df_hrta = df_hrta.sort_values(by=['Vendor', 'Gramasi'])
    if not df_g24.empty: df_g24 = df_g24.sort_values(by='Gramasi')

    # 4. Save
    filename = f"Harga_Emas_Lengkap_{datetime.now().strftime('%Y%m%d')}.xlsx"
    print(f"\n[SAVE] Menyimpan ke {filename}...")
    
    try:
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            if not df_antam.empty: df_antam.to_excel(writer, sheet_name='ANTAM', index=False)
            if not df_g24.empty: df_g24.to_excel(writer, sheet_name='GALERI_24', index=False)
            if not df_hrta.empty: df_hrta.to_excel(writer, sheet_name='HARTADINATA', index=False)
            if not df_ubs.empty: df_ubs.to_excel(writer, sheet_name='UBS', index=False)
        print("SUKSES SEMUA!")
    except Exception as e:
        print(f"Error Save Excel: {e}")

if __name__ == "__main__":
    main()