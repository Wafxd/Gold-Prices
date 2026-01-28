from flask import Flask, render_template, jsonify
import importlib
import sys
import os

# Menambahkan folder saat ini ke path agar importlib bisa menemukan modul lokal di serverless environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

def get_full_data(vendor):
    try:
        # Menggunakan import_module untuk memanggil file .py secara dinamis
        if vendor == 'antam':
            module = importlib.import_module('antam')
            return module.crawl_antam()
        elif vendor == 'g24':
            module = importlib.import_module('g24')
            return module.crawl_g24_only()
        elif vendor == 'hrta':
            module = importlib.import_module('hrta')
            return module.crawl_hartadinata()
        elif vendor == 'ubs':
            module = importlib.import_module('ubs')
            return module.crawl_ubs_complete()
        return []
    except Exception as e:
        # Output error ke log server untuk debugging
        print(f"Error fetching {vendor}: {str(e)}")
        return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_price/<vendor>')
def get_price(vendor):
    data = get_full_data(vendor)
    # Menambahkan header agar browser tidak menyimpan cache data yang lama
    response = jsonify(data)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# Penting untuk Vercel: Objek 'app' harus tersedia di level global
# Vercel menggunakan WSGI server untuk menjalankan aplikasi ini
app = app

if __name__ == '__main__':
    # Local development run
    app.run(debug=True)