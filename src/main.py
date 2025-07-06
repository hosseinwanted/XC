import os
import json
import base64
import requests
import re
import subprocess
import threading
import queue
import time
from urllib.parse import urlparse, parse_qs, unquote
from collections import defaultdict

# --- بخش تنظیمات ---
V2RAY_CORE_PATH = "v2ray_core/v2ray"
CONFIG_DIR = "subscriptions"
TEMP_CONFIG_DIR = "temp_configs"
MAX_THREADS = 100
START_PORT = 10800
TEST_TIMEOUT = 8
TEST_URL = "http://www.gstatic.com/generate_204"

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
    os.makedirs(TEMP_CONFIG_DIR, exist_ok=True)
    base_dir = SETTINGS.get("out_dir", "subscriptions")
    dirs_to_create = [
        base_dir,
        os.path.join(base_dir, "v2ray", "subs"),
        os.path.join(base_dir, "base64", "subs"),
        os.path.join(base_dir, "filtered", "subs"),
        os.path.join(base_dir, "warp")
    ]
    for d in dirs_to_create:
        os.makedirs(d, exist_ok=True)

def get_sources():
    """کانفیگ‌ها را از منابع دریافت می‌کند."""
    all_configs = set()
    sources = SETTINGS.get("sources", {}).get("files", [])
    for source_path in sources:
        url = f"https://raw.githubusercontent.com/{source_path}"
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            content = response.text
            try:
                if len(content) % 4 != 0: content += '=' * (4 - len(content) % 4)
                decoded_content = base64.b64decode(content).decode('utf-8')
                all_configs.update(decoded_content.splitlines())
            except Exception:
                all_configs.update(content.splitlines())
        except requests.RequestException as e:
            print(f"خطا در دریافت منبع {url}: {e}")
    
    return list(filter(None, all_configs))

def parse_link(link):
    """پارس کردن انواع لینک‌ها."""
    link = link.strip()
    if link.startswith("vmess://"):
        return {'type': 'vmess', 'link': link}
    elif link.startswith("vless://"):
        return {'type': 'vless', 'link': link}
    elif link.startswith("trojan://"):
        return {'type': 'trojan', 'link': link}
    return None

class V2RayTester:
    """تست یک کانفیگ با استفاده از هسته V2Ray."""
    def __init__(self, config_info, port):
        self.config_info = config_info
        self.port = port
        self.proc = None
        self.config_path = os.path.join(TEMP_CONFIG_DIR, f"config_{port}.json")

    def generate_config(self):
        """ساخت فایل کانفیگ JSON برای v2ray-core."""
        link = self.config_info['link']
        
        # اجرای v2ray برای تبدیل لینک به فرمت JSON
        try:
            result = subprocess.run([V2RAY_CORE_PATH, "convert", "-format", "json", link], capture_output=True, text=True, check=True)
            config = json.loads(result.stdout)
            
            # تنظیم پورت inbound
            config['inbounds'] = [{'port': self.port, 'protocol': 'socks', 'listen': '127.0.0.1'}]
            config['log'] = {'loglevel': 'warning'} # کاهش لاگ‌های اضافی
            
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            print(f"خطا در ساخت کانفیگ برای لینک {link[:30]}...: {e}")
            return False

    def run_test(self):
        """اجرای تست."""
        if not self.generate_config():
            return None, -1

        cmd = [V2RAY_CORE_PATH, "run", "-c", self.config_path]
        
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)

            if self.proc.poll() is not None:
                return None, -1

            proxies = {'http': f'socks5://127.0.0.1:{self.port}', 'https': f'socks5://127.0.0.1:{self.port}'}
            start_req_time = time.time()
            response = requests.get(TEST_URL, proxies=proxies, timeout=TEST_TIMEOUT)
            
            if response.status_code == 204:
                latency = int((time.time() - start_req_time) * 1000)
                return self.config_info['link'], latency
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
    """تابع کارگر برای تست موازی."""
    while not config_queue.empty():
        try:
            config_info = config_queue.get_nowait()
            tester = V2RayTester(config_info, port)
            link, latency = tester.run_test()
            if link:
                result_queue.put({'config': link, 'ping': latency})
        except queue.Empty:
            break

def main():
    start_time = time.time()
    setup_directories()

    all_links = get_sources()
    valid_configs = [parse_link(link) for link in all_links if parse_link(link)]
    print(f"تعداد {len(valid_configs)} کانفیگ معتبر برای تست آماده شد.")

    config_q = queue.Queue()
    for config in valid_configs:
        config_q.put(config)
    
    result_q = queue.Queue()
    threads = []
    for i in range(MAX_THREADS):
        port = START_PORT + i
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

    if final_results:
        all_final_links = [res['config'] for res in final_results]
        
        # ذخیره فایل‌ها
        base_dir = SETTINGS.get("out_dir", "subscriptions")
        v2ray_dir = os.path.join(base_dir, "v2ray")
        base64_dir = os.path.join(base_dir, "base64")

        with open(os.path.join(v2ray_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(all_final_links))
        
        with open(os.path.join(base64_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(all_final_links).encode()).decode())
    
    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
