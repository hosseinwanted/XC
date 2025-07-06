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
from pathlib import Path

# --- بخش تنظیمات ---
V2RAY_CORE_PATH = "v2ray_core/v2ray"
TEMP_CONFIG_DIR = "temp_configs"
MAX_THREADS = 100
TEST_TIMEOUT = 10  # به ثانیه

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
        os.path.join(base_dir, "v2ray"),
        os.path.join(base_dir, "base64"),
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
            print(f"خطا در دریافت منبع {url}: {e}")
    
    return list(filter(None, all_configs))

def test_config(config_link, index):
    """یک کانفیگ را با استفاده از v2ray test تست می‌کند."""
    config_path = os.path.join(TEMP_CONFIG_DIR, f"config_{index}.json")
    
    # استفاده از v2ray convert برای ساخت کانفیگ
    try:
        convert_proc = subprocess.run(
            [V2RAY_CORE_PATH, "convert", "-format", "json", config_link],
            capture_output=True, text=True, check=True, timeout=5
        )
        config_json = json.loads(convert_proc.stdout)
        
        # حذف لاگ برای جلوگیری از خروجی اضافی
        if 'log' in config_json:
            del config_json['log']
            
        with open(config_path, 'w') as f:
            json.dump(config_json, f)
            
    except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        # print(f"خطا در ساخت کانفیگ برای {config_link[:30]}... : {e}")
        return None, -1
    
    # اجرای تست با کانفیگ ساخته شده
    try:
        test_cmd = [V2RAY_CORE_PATH, "test", "-c", config_path]
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT)
        
        if result.returncode == 0:
            # استخراج پینگ از خروجی
            match = re.search(r'Success: (\d+) ms', result.stdout)
            if match:
                return config_link, int(match.group(1))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    finally:
        if os.path.exists(config_path):
            os.remove(config_path)
            
    return None, -1

def worker(config_queue, result_queue):
    """تابع کارگر برای تست موازی."""
    while not config_queue.empty():
        try:
            index, config_link = config_queue.get_nowait()
            link, latency = test_config(config_link, index)
            if link:
                result_queue.put({'config': link, 'ping': latency})
        except queue.Empty:
            break
        except Exception as e:
            print(f"خطای ناشناخته در ترد: {e}")

def main():
    start_time = time.time()
    setup_directories()

    all_links = get_sources()
    print(f"تعداد {len(all_links)} کانفیگ برای تست آماده شد.")

    config_q = queue.Queue()
    for i, link in enumerate(all_links):
        config_q.put((i, link))
    
    result_q = queue.Queue()
    threads = []
    num_threads = min(MAX_THREADS, len(all_links))

    for i in range(num_threads):
        thread = threading.Thread(target=worker, args=(config_q, result_q))
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

