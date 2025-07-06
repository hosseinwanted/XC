import os
import json
import base64
import requests
import re
import subprocess
import threading
import queue
import time
import socket
from urllib.parse import urlparse, parse_qs, unquote
from collections import defaultdict
from pathlib import Path
import geoip2.database

# --- بخش تنظیمات کلی ---
PROTOCOLS_DIR = "subscriptions/filtered/subs"
REGIONS_DIR = "subscriptions/regions"
REPORTS_DIR = "reports"
MERGED_DIR = "subscriptions/v2ray"
BASE64_DIR = "subscriptions/base64"
GEOIP_DB_PATH = Path("GeoLite2-Country.mmdb")
V2RAY_CORE_PATH = Path("v2ray_core/v2ray")

# --- کلاس‌ها و توابع اصلی ---

def load_settings():
    """فایل تنظیمات را بارگذاری می‌کند."""
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"خطا در خواندن settings.json: {e}")
        exit()

SETTINGS = load_settings()

def setup_directories():
    """پوشه‌های مورد نیاز را ایجاد می‌کند."""
    for d in [PROTOCOLS_DIR, REGIONS_DIR, REPORTS_DIR, MERGED_DIR, BASE64_DIR, f"{MERGED_DIR}/subs", f"{BASE64_DIR}/subs"]:
        os.makedirs(d, exist_ok=True)

def get_sources():
    """کانفیگ‌ها را از منابع تعریف شده در settings.json دریافت می‌کند."""
    all_configs = set()
    sources = SETTINGS.get("sources", {}).get("files", [])
    for source_path in sources:
        url = f"https://raw.githubusercontent.com/{source_path}"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            content = response.text
            try:
                if len(content) % 4 != 0:
                    content += '=' * (4 - len(content) % 4)
                decoded_content = base64.b64decode(content).decode('utf-8')
                all_configs.update(decoded_content.splitlines())
            except Exception:
                all_configs.update(content.splitlines())
        except requests.RequestException as e:
            print(f"خطا در دریافت منبع {url}: {e}")
    
    return list(filter(None, all_configs))

def parse_link(link):
    """لینک کانفیگ را به یک دیکشنری ساختاریافته تبدیل می‌کند."""
    link = link.strip()
    if link.startswith("vmess://"):
        return parse_vmess(link)
    elif link.startswith("vless://"):
        return parse_vless(link)
    elif link.startswith("trojan://"):
        return parse_trojan(link)
    return None

def parse_vmess(link):
    try:
        decoded_part = base64.b64decode(link.replace("vmess://", "")).decode('utf-8')
        data = json.loads(decoded_part)
        return {'type': 'vmess', 'data': data, 'original_link': link}
    except Exception:
        return None

def parse_vless(link):
    try:
        parsed_url = urlparse(link)
        data = {
            'add': parsed_url.hostname,
            'port': parsed_url.port,
            'id': parsed_url.username,
            'ps': unquote(parsed_url.fragment) if parsed_url.fragment else f"vless-{parsed_url.hostname}",
            'params': parse_qs(parsed_url.query)
        }
        return {'type': 'vless', 'data': data, 'original_link': link}
    except Exception:
        return None

def parse_trojan(link):
    try:
        parsed_url = urlparse(link)
        data = {
            'add': parsed_url.hostname,
            'port': parsed_url.port,
            'password': unquote(parsed_url.username),
            'ps': unquote(parsed_url.fragment) if parsed_url.fragment else f"trojan-{parsed_url.hostname}",
            'params': parse_qs(parsed_url.query)
        }
        return {'type': 'trojan', 'data': data, 'original_link': link}
    except Exception:
        return None

class V2RayTester:
    """یک کانفیگ را با استفاده از هسته V2Ray تست می‌کند."""
    def __init__(self, config_info, port):
        self.config_info = config_info
        self.port = port
        self.proc = None
        self.config_path = f"temp_config_{self.port}.json"

    def generate_config_file(self):
        protocol = self.config_info['type']
        data = self.config_info['data']
        
        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [{"port": self.port, "protocol": "socks", "listen": "127.0.0.1", "settings": {"udp": True}}],
            "outbounds": [{"protocol": protocol, "settings": {}, "streamSettings": {}}]
        }

        outbound_settings = config['outbounds'][0]['settings']
        stream_settings = config['outbounds'][0]['streamSettings']

        if protocol == 'vmess':
            outbound_settings['vnext'] = [{'address': data['add'], 'port': int(data['port']), 'users': [{'id': data['id'], 'alterId': int(data.get('aid', 0)), 'security': data.get('scy', 'auto')}]}]
            stream_settings['network'] = data.get('net', 'tcp')
            stream_settings['security'] = data.get('tls', 'none')
            if data.get('net') == 'ws':
                stream_settings['wsSettings'] = {'path': data.get('path', '/'), 'headers': {'Host': data.get('host', data['add'])}}
            if data.get('tls') == 'tls':
                stream_settings['tlsSettings'] = {'serverName': data.get('sni', data.get('host', data['add']))}
        
        elif protocol == 'vless':
            params = data.get('params', {})
            outbound_settings['vnext'] = [{'address': data['add'], 'port': int(data['port']), 'users': [{'id': data['id'], 'flow': params.get('flow', [''])[0]}]}]
            stream_settings['network'] = params.get('type', ['tcp'])[0]
            stream_settings['security'] = params.get('security', ['none'])[0]
            if stream_settings['network'] == 'ws':
                stream_settings['wsSettings'] = {'path': params.get('path', ['/'])[0], 'headers': {'Host': params.get('host', [data['add']])[0]}}
            if stream_settings['security'] == 'tls':
                stream_settings['tlsSettings'] = {'serverName': params.get('sni', [data['add']])[0]}
            elif stream_settings['security'] == 'reality':
                stream_settings['realitySettings'] = {'publicKey': params.get('pbk', [''])[0], 'shortId': params.get('sid', [''])[0], 'serverName': params.get('sni', [data['add']])[0]}

        elif protocol == 'trojan':
            params = data.get('params', {})
            outbound_settings['servers'] = [{'address': data['add'], 'port': int(data['port']), 'password': data['password']}]
            stream_settings['security'] = params.get('security', ['tls'])[0]
            if stream_settings['security'] == 'tls':
                 stream_settings['tlsSettings'] = {'serverName': params.get('sni', [data['add']])[0]}

        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)

    def run_test(self):
        try:
            self.generate_config_file()
            cmd = [str(V2RAY_CORE_PATH), "run", "-c", self.config_path]
            
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.5) # زمان برای شروع به کار V2Ray

            if self.proc.poll() is not None:
                return None, -1 # پروسه بلافاصله بسته شده، کانفیگ مشکل دارد

            proxies = {'http': f'socks5://127.0.0.1:{self.port}', 'https': f'socks5://127.0.0.1:{self.port}'}
            start_req_time = time.time()
            response = requests.get("http://www.gstatic.com/generate_204", proxies=proxies, timeout=SETTINGS.get("timeout", 5))
            
            if response.status_code == 204:
                latency = int((time.time() - start_req_time) * 1000)
                return self.config_info['original_link'], latency
        except Exception:
            return None, -1
        finally:
            if self.proc:
                self.proc.terminate()
                self.proc.wait()
            if os.path.exists(self.config_path):
                os.remove(self.config_path)
        return None, -1

def worker(config_queue, result_queue, port):
    """یک ترد کارگر که کانفیگ‌ها را از صف برداشته و تست می‌کند."""
    while not config_queue.empty():
        try:
            config_info = config_queue.get_nowait()
            tester = V2RayTester(config_info, port)
            link, latency = tester.run_test()
            if link:
                result_queue.put({'config': link, 'ping': latency})
        except queue.Empty:
            break
        except Exception as e:
            print(f"خطا در ترد {port}: {e}")

def get_country(ip_address, geo_reader):
    """کشور را بر اساس آدرس IP تشخیص می‌دهد."""
    if not ip_address or not geo_reader:
        return "Unknown"
    try:
        response = geo_reader.country(ip_address)
        return response.country.iso_code
    except (geoip2.errors.AddressNotFoundError, ValueError):
        return "Unknown"

def main():
    start_time = time.time()
    setup_directories()

    all_links = get_sources()
    parsed_configs = [parse_link(link) for link in all_links]
    valid_configs = list(filter(None, parsed_configs))
    print(f"تعداد {len(valid_configs)} کانفیگ معتبر برای تست آماده شد.")

    config_q = queue.Queue()
    for config in valid_configs:
        config_q.put(config)
    
    result_q = queue.Queue()
    threads = []
    num_threads = SETTINGS.get("max_threads", 50)

    for i in range(num_threads):
        port = 10800 + i
        thread = threading.Thread(target=worker, args=(config_q, result_q, port))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    final_results = []
    while not result_q.empty():
        final_results.append(result_q.get())

    final_results.sort(key=lambda x: x['ping'])
    print(f"تست کامل شد. {len(final_results)} کانفیگ سالم پیدا شد.")

    if not final_results:
        print("هیچ کانفیگ سالمی پیدا نشد. خروج از برنامه.")
        return

    all_final_links = [res['config'] for res in final_results]
    
    # ذخیره فایل‌های اصلی
    with open(os.path.join(MERGED_DIR, "all_sub.txt"), "w", encoding="utf-8") as f: f.write("\n".join(all_final_links))
    with open(os.path.join(BASE64_DIR, "all_sub.txt"), "w", encoding="utf-8") as f: f.write(base64.b64encode("\n".join(all_final_links).encode()).decode())
    
    # دسته‌بندی بر اساس پروتکل
    by_protocol = defaultdict(list)
    for res in final_results:
        proto = res['config'].split("://")[0]
        by_protocol[proto].append(res['config'])
    
    for proto, configs in by_protocol.items():
        with open(os.path.join(PROTOCOLS_DIR, f"{proto}.txt"), "w", encoding="utf-8") as f: f.write("\n".join(configs))
        print(f"✅ فایل اشتراک برای پروتکل '{proto}' با {len(configs)} کانفیگ ساخته شد.")

    # دسته‌بندی بر اساس کشور
    geo_reader = geoip2.database.Reader(GEOIP_DB_PATH) if GEOIP_DB_PATH.exists() else None
    by_country = defaultdict(list)
    for res in final_results:
        try:
            host = urlparse(res['config']).hostname
            # Resolve domain to IP for GeoIP lookup
            ip = socket.gethostbyname(host)
            country = get_country(ip, geo_reader)
            by_country[country].append(res['config'])
        except Exception:
            by_country["Unknown"].append(res['config'])
    
    for country, configs in by_country.items():
        with open(os.path.join(REGIONS_DIR, f"{country}.txt"), "w") as f:
            f.write("\n".join(configs))
    
    if geo_reader:
        geo_reader.close()

    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
