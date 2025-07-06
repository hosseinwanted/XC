import os
import json
import base64
import requests
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- بخش تنظیمات ---

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
                # تلاش برای دیکود کردن محتوای Base64
                if len(content) % 4 != 0: content += '=' * (4 - len(content) % 4)
                decoded_content = base64.b64decode(content).decode('utf-8', errors='ignore')
                all_configs.update(decoded_content.splitlines())
            except Exception:
                # اگر دیکود نشد، محتوا را به صورت خام اضافه کن
                all_configs.update(content.splitlines())
        except requests.RequestException as e:
            print(f"خطا در دریافت منبع {url}: {e}")
    
    return list(filter(None, all_configs))

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
                port = 443 # پورت پیش‌فرض برای TLS
            
            start_time = time.time()
            sock = socket.create_connection((host, port), timeout=self.timeout)
            ping_ms = int((time.time() - start_time) * 1000)
            sock.close()
            return {'config': config, 'ping': ping_ms}
        except (socket.timeout, ConnectionRefusedError, OSError):
            return None
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
                
                # نمایش پیشرفت
                print(f"\rتست کانفیگ‌ها: {i+1}/{total} | سالم: {len(reachable_configs)}", end="")

        print(f"\nتست کامل شد. {len(reachable_configs)} کانفیگ سالم پیدا شد.")
        return sorted(reachable_configs, key=lambda x: x['ping'])

def main():
    start_time = time.time()
    setup_directories()

    all_links = get_sources()
    unique_configs = sorted(list(set(filter(None, all_links))))
    
    print(f"تعداد {len(unique_configs)} کانفیگ یکتا برای تست آماده شد.")

    tester = V2RayPingTester(unique_configs, timeout=SETTINGS.get("timeout", 5))
    final_results = tester.run()

    if final_results:
        all_final_links = [res['config'] for res in final_results]
        
        base_dir = SETTINGS.get("out_dir", "subscriptions")
        v2ray_dir = os.path.join(base_dir, "v2ray")
        base64_dir = os.path.join(base_dir, "base64")

        with open(os.path.join(v2ray_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(all_final_links))
        
        with open(os.path.join(base64_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(all_final_links).encode()).decode())
    else:
        print("هیچ کانفیگ سالمی پیدا نشد.")

    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
