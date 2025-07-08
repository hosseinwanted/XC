import os
import json
import base64
import requests
import socket
import time
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote_plus, quote
from collections import defaultdict
from pathlib import Path
import geoip2.database
from bs4 import BeautifulSoup

# --- بخش تنظیمات ---

def load_settings():
    """فایل تنظیمات را بارگذاری می‌کند."""
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ خطا در خواندن settings.json: {e}")
        exit()

SETTINGS = load_settings()
GEOIP_DB_PATH = Path("GeoLite2-Country.mmdb")
# خواندن لیست برندها و اموجی‌ها از تنظیمات
BRANDS_LIST = SETTINGS.get("brands", ["V2XCore"]) 
EMOJIS_LIST = SETTINGS.get("emojis", ["⚡️"])
REPORTS_DIR = "reports"

def setup_directories():
    """پوشه‌های مورد نیاز را ایجاد می‌کند."""
    base_dir = SETTINGS.get("out_dir", "subscriptions")
    dirs_to_create = [
        base_dir,
        os.path.join(base_dir, "v2ray"),
        os.path.join(base_dir, "base64"),
        os.path.join(base_dir, "filtered", "subs"),
        os.path.join(base_dir, "regions"),
        REPORTS_DIR
    ]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

def get_sources_from_files():
    """کانفیگ‌ها را از فایل‌های مخازن گیت‌هاب دریافت می‌کند."""
    all_configs = set()
    sources = SETTINGS.get("sources", {}).get("files", [])
    print("📥 شروع جمع‌آوری کانفیگ‌ها از فایل‌ها...")
    for source_path in sources:
        url = f"https://raw.githubusercontent.com/{source_path.strip()}"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            content = response.text
            try:
                if len(content) % 4 != 0: content += '=' * (4 - len(content) % 4)
                decoded_content = base64.b64decode(content).decode('utf-8', errors='ignore')
                all_configs.update(decoded_content.splitlines())
            except Exception:
                all_configs.update(content.splitlines())
        except requests.RequestException as e:
            print(f"⚠️ خطا در دریافت منبع {url}: {e}")
    return all_configs

def scrape_telegram_channels():
    """کانفیگ‌ها را از کانال‌های تلگرام استخراج می‌کند."""
    all_configs = set()
    channels = SETTINGS.get("sources", {}).get("channels", [])
    print("✈️ شروع جمع‌آوری کانفیگ‌ها از کانال‌های تلگرام...")
    
    patterns = {
        'vmess': r'vmess://[^\s<>"\'`]+',
        'vless': r'vless://[^\s<>"\'`]+',
        'trojan': r'trojan://[^\s<>"\'`]+',
        'ss': r'ss://[^\s<>"\'`]+'
    }

    for channel in channels:
        url = f"https://t.me/s/{channel.strip()}"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            page_text = soup.get_text()
            for proto, pattern in patterns.items():
                matches = re.findall(pattern, page_text)
                all_configs.update(matches)
        except requests.RequestException as e:
            print(f"⚠️ خطا در دسترسی به کانال {channel}: {e}")
    
    return all_configs

class V2RayPingTester:
    """تست سریع اتصال برای سنجش در دسترس بودن و پینگ اولیه."""
    def __init__(self, configs, timeout=4):
        self.configs = configs
        self.timeout = timeout
        self.max_threads = 200

    def test_single(self, config):
        """تست اتصال TCP ساده."""
        try:
            if "://" not in config: return None
            uri_part = config.split('://')[1]
            host_part = uri_part.split('#')[0].split('?')[0]
            
            if '@' in host_part:
                host_port_str = host_part.split('@')[1]
            else:
                host_port_str = host_part

            if ':' in host_port_str:
                host = host_port_str.rsplit(':', 1)[0].strip("[]")
                port = int(host_port_str.rsplit(':', 1)[1])
            else:
                host = host_port_str
                port = 443
            
            start_time = time.time()
            with socket.create_connection((host, port), timeout=self.timeout) as sock:
                ping_ms = int((time.time() - start_time) * 1000)
                return {'config': config, 'ping': ping_ms, 'host': host}
        except Exception:
            return None

    def run(self):
        """تمام کانفیگ‌ها را به صورت موازی تست می‌کند."""
        reachable_configs = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_config = {executor.submit(self.test_single, config): config for config in self.configs}
            
            total = len(future_to_config)
            for i, future in enumerate(as_completed(future_to_config)):
                result = future.result()
                if result:
                    reachable_configs.append(result)
                print(f"\r🧪 تست کانفیگ‌ها: {i+1}/{total} | ✅ سالم: {len(reachable_configs)}", end="")

        print(f"\n\n✅ تست کامل شد. {len(reachable_configs)} کانفیگ سالم پیدا شد.")
        return sorted(reachable_configs, key=lambda x: x['ping'])

def get_country_and_flag(ip_address, geo_reader):
    """کشور و پرچم را بر اساس آدرس IP تشخیص می‌دهد."""
    if not ip_address or not geo_reader:
        return "Unknown", "🌐"
    try:
        response = geo_reader.country(ip_address)
        country_code = response.country.iso_code
        if country_code:
            flag = "".join(chr(ord(c) + 127397) for c in country_code.upper())
            return country_code, flag
        return "Unknown", "🌐"
    except Exception:
        return "Unknown", "🌐"

def main():
    start_time = time.time()
    setup_directories()

    file_configs = get_sources_from_files()
    channel_configs = scrape_telegram_channels()
    unique_configs = list(file_configs.union(channel_configs))
    print(f"🔬 تعداد {len(unique_configs)} کانفیگ یکتا برای تست آماده شد.\n")

    tester = V2RayPingTester(unique_configs, timeout=SETTINGS.get("timeout", 5))
    final_results = tester.run()

    if final_results:
        geo_reader = geoip2.database.Reader(GEOIP_DB_PATH) if GEOIP_DB_PATH.exists() else None
        
        by_country = defaultdict(list)
        by_protocol = defaultdict(list)
        
        print("\n🎨 شروع نام‌گذاری و دسته‌بندی...")
        named_results = []
        for i, res in enumerate(final_results, 1):
            try:
                ip = socket.gethostbyname(res['host'])
                country, flag = get_country_and_flag(ip, geo_reader)
            except socket.gaierror:
                country, flag = "Unknown", "🌐"

            selected_brand = random.choice(BRANDS_LIST)
            selected_emoji = random.choice(EMOJIS_LIST)
            new_name = f"{flag} {country} #{i:04d} | {selected_brand} {selected_emoji}"
            
            original_link = res['config'].split('#')[0]
            named_config = f"{original_link}#{quote(new_name)}"
            
            # ذخیره نتیجه نام‌گذاری شده برای استفاده‌های بعدی
            res['named_config'] = named_config
            res['country'] = country
            named_results.append(res)
            
            by_country[country].append(named_config)
            by_protocol[named_config.split("://")[0]].append(named_config)

        if geo_reader: geo_reader.close()
        
        base_dir = SETTINGS.get("out_dir", "subscriptions")
        
        for country, configs in by_country.items():
            with open(os.path.join(base_dir, "regions", f"{country}.txt"), "w", encoding="utf-8") as f: f.write("\n".join(configs))
        
        for protocol, configs in by_protocol.items():
            with open(os.path.join(base_dir, "filtered", "subs", f"{protocol}.txt"), "w", encoding="utf-8") as f: f.write("\n".join(configs))
        
        print("💾 ذخیره‌سازی فایل‌ها...")
        all_final_links = [res['named_config'] for res in named_results]
        with open(os.path.join(base_dir, "v2ray", "all_sub.txt"), "w") as f: f.write("\n".join(all_final_links))
        with open(os.path.join(base_dir, "base64", "all_sub.txt"), "w") as f: f.write(base64.b64encode("\n".join(all_final_links).encode()).decode())
        print("✅ تمام فایل‌ها با موفقیت ذخیره شدند.")

        # --- بخش جدید: ساخت گزارش کامل برای README و صفحه وب ---
        report_data = {
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "total_configs": len(final_results),
            "countries": {country: len(configs) for country, configs in by_country.items()},
            "configs": [{'name': res['named_config'].split('#')[1], 'ping': res['ping'], 'link': res['named_config']} for res in named_results]
        }
        with open(os.path.join(REPORTS_DIR, "stats.json"), "w") as f: json.dump(report_data, f)
        print("📊 گزارش کامل برای داشبورد ساخته شد.")
    else:
        print("🔴 هیچ کانفیگ سالمی پیدا نشد.")

    print(f"\n✨ کل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
