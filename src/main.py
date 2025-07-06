import os
import json
import base64
import requests
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- بخش تنظیمات و بارگذاری اولیه ---

def load_settings():
    """فایل تنظیمات را بارگذاری می‌کند."""
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("خطا: فایل settings.json پیدا نشد.")
        exit()
    except json.JSONDecodeError:
        print("خطا: فایل settings.json معتبر نیست.")
        exit()

SETTINGS = load_settings()

# --- بخش جمع‌آوری کانفیگ‌ها از منابع ---

def get_content_from_url(url):
    """محتوا را از یک URL دریافت می‌کند."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # بررسی خطاهای HTTP
        return response.text
    except requests.RequestException as e:
        print(f"خطا در دریافت محتوا از {url}: {e}")
        return None

def get_all_sources_content():
    """تمام کانفیگ‌ها را از منابع تعریف شده در settings.json جمع‌آوری می‌کند."""
    all_configs = []
    sources = SETTINGS.get("sources", {})
    
    # پردازش منابع از نوع file
    for file_path in sources.get("files", []):
        url = f"https://raw.githubusercontent.com/{file_path}"
        content = get_content_from_url(url)
        if content:
            all_configs.extend(content.splitlines())
            
    print(f"مجموعاً {len(all_configs)} کانفیگ از منابع مختلف جمع‌آوری شد.")
    return all_configs

def decode_base64_configs(configs):
    """لیستی از کانفیگ‌ها را می‌گیرد و محتوای Base64 را دیکود می‌کند."""
    decoded_configs = []
    for config in configs:
        # اگر خط یک لینک اشتراک Base64 بود
        if not any(proto in config for proto in SETTINGS.get("protocols", [])):
            try:
                # اضافه کردن padding در صورت نیاز
                padding = '=' * (-len(config) % 4)
                decoded_content = base64.b64decode(config + padding).decode('utf-8')
                decoded_configs.extend(decoded_content.splitlines())
            except (base64.binascii.Error, UnicodeDecodeError):
                # اگر دیکود نشد، احتمالا لینک مستقیم است
                decoded_configs.append(config)
        else:
            decoded_configs.append(config)
    return decoded_configs

# --- بخش تست و ارزیابی کانفیگ‌ها ---

class V2RayPingTester:
    """
    این کلاس کانفیگ‌های V2Ray را برای اتصال TCP (و TLS) تست می‌کند.
    """
    def __init__(self, configs, timeout=5):
        self.configs = configs
        self.timeout = timeout
        self.max_threads = 200 # افزایش تعداد تردها برای سرعت بیشتر

    def parse_config(self, config_link):
        """هاست، پورت و وضعیت TLS را از لینک کانفیگ استخراج می‌کند."""
        try:
            if "://" not in config_link:
                return None
                
            protocol = config_link.split("://")[0]
            if protocol not in SETTINGS.get("protocols", []):
                return None

            uri_part = config_link.split('://')[1]
            main_part = uri_part.split('#')[0]
            host_part = main_part.split('?')[0]

            if '@' in host_part:
                host_port_str = host_part.split('@')[1]
            else:
                host_port_str = host_part

            if ':' in host_port_str:
                host = host_port_str.rsplit(':', 1)[0].strip("[]") # حذف براکت برای آدرس IPv6
                port = int(host_port_str.rsplit(':', 1)[1])
            else:
                host = host_port_str
                port = 443 # پورت پیش‌فرض برای TLS

            use_tls = 'security=tls' in main_part.lower() or port == 443
            return host, port, use_tls
        except Exception:
            return None

    def test_single(self, config):
        """یک کانفیگ را تست می‌کند."""
        parsed_data = self.parse_config(config)
        if not parsed_data or not parsed_data[0]:
            return None

        host, port, use_tls = parsed_data
        try:
            start_time = time.time()
            sock = socket.create_connection((host, port), timeout=self.timeout)
            if use_tls:
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=host)
            sock.close()
            ping_ms = int((time.time() - start_time) * 1000)
            return {'config': config, 'ping': ping_ms}
        except Exception:
            return None

    def test_all(self):
        """تمام کانفیگ‌ها را به صورت موازی تست می‌کند."""
        reachable_configs = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_config = {executor.submit(self.test_single, config): config for config in self.configs}
            for i, future in enumerate(as_completed(future_to_config)):
                result = future.result()
                if result:
                    reachable_configs.append(result)
                # نمایش پیشرفت
                print(f"\rتست کانفیگ‌ها: {i+1}/{len(self.configs)}", end="")
        print("\nتست کامل شد.")
        
        # مرتب‌سازی نتایج بر اساس پینگ از کم به زیاد
        return sorted(reachable_configs, key=lambda x: x['ping'])

# --- بخش اصلی و اجرای برنامه ---

def main():
    """تابع اصلی برای اجرای کل فرآیند."""
    start_time = time.time()
    
    # ۱. دریافت و پاک‌سازی کانفیگ‌ها
    raw_configs = get_all_sources_content()
    decoded_configs = decode_base64_configs(raw_configs)
    
    unique_configs = sorted(list(set(filter(None, decoded_configs))))
    valid_protocol_configs = [
        c for c in unique_configs if any(p in c for p in SETTINGS.get("protocols", []))
    ]
    
    limit = SETTINGS.get("all_configs_limit", 3000)
    configs_to_test = valid_protocol_configs[:limit]
    
    print(f"تعداد {len(configs_to_test)} کانفیگ یکتا برای تست آماده شد.")

    # ۲. تست کانفیگ‌ها
    tester = V2RayPingTester(configs_to_test, timeout=SETTINGS.get("timeout", 5))
    reachable_results = tester.test_all()
    
    print(f"تعداد {len(reachable_results)} کانفیگ سالم پیدا شد.")

    # ۳. نوشتن فایل‌های خروجی
    out_dir = SETTINGS.get("out_dir", "subscriptions")
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # ساخت فایل all_sub.txt
    all_configs_str = "\n".join([res['config'] for res in reachable_results])
    with open(os.path.join(out_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
        f.write(all_configs_str)
    with open(os.path.join(out_dir, "all_sub_b64.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode(all_configs_str.encode("utf-8")).decode("utf-8"))

    # ساخت فایل super_sub.txt
    super_limit = SETTINGS.get("supersub_configs_limit", 200)
    super_configs = reachable_results[:super_limit]
    super_configs_str = "\n".join([res['config'] for res in super_configs])
    with open(os.path.join(out_dir, "super_sub.txt"), "w", encoding="utf-8") as f:
        f.write(super_configs_str)
    with open(os.path.join(out_dir, "super_sub_b64.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode(super_configs_str.encode("utf-8")).decode("utf-8"))

    # --- بخش جدید: ساخت فایل‌های اشتراک بر اساس پروتکل ---
    print("\nدر حال ساخت فایل‌های اشتراک بر اساس پروتکل...")
    protocol_configs = {}
    for res in reachable_results:
        config_link = res['config']
        try:
            protocol = config_link.split("://")[0]
            if protocol not in protocol_configs:
                protocol_configs[protocol] = []
            protocol_configs[protocol].append(config_link)
        except IndexError:
            continue # اگر کانفیگ فرمت درستی نداشته باشد، از آن رد شو

    for protocol, configs in protocol_configs.items():
        if configs:
            protocol_str = "\n".join(configs)
            # ساخت فایل متنی
            file_path = os.path.join(out_dir, f"{protocol}_sub.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(protocol_str)
            # ساخت نسخه Base64
            b64_file_path = os.path.join(out_dir, f"{protocol}_sub_b64.txt")
            with open(b64_file_path, "w", encoding="utf-8") as f:
                f.write(base64.b64encode(protocol_str.encode("utf-8")).decode("utf-8"))
            print(f"✅ فایل اشتراک برای پروتکل '{protocol}' با {len(configs)} کانفیگ ساخته شد.")
    # --- پایان بخش جدید ---

    print(f"\nفایل‌های اشتراک در پوشه '{out_dir}' ذخیره شدند.")
    
    end_time = time.time()
    print(f"کل فرآیند در {end_time - start_time:.2f} ثانیه به پایان رسید.")


if __name__ == "__main__":
    main()
