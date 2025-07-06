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

# --- بخش ابزارهای کمکی ---

def create_output_dirs():
    """تمام پوشه‌های خروجی مورد نیاز را ایجاد می‌کند."""
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
    return base_dir

def save_split_files(configs, out_path, lines_per_file, is_base64=False):
    """لیست کانفیگ‌ها را به فایل‌های کوچکتر تقسیم و ذخیره می‌کند."""
    for i, chunk_start in enumerate(range(0, len(configs), lines_per_file)):
        chunk = configs[chunk_start:chunk_start + lines_per_file]
        content = "\n".join(chunk)
        if is_base64:
            content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        
        file_name = f"sub{i+1}.txt"
        with open(os.path.join(out_path, file_name), "w", encoding="utf-8") as f:
            f.write(content)

# --- بخش جمع‌آوری کانفیگ‌ها ---

def get_content_from_url(url):
    """محتوا را از یک URL دریافت می‌کند."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"خطا در دریافت محتوا از {url}: {e}")
        return None

def get_all_sources_content():
    """تمام کانفیگ‌ها را از منابع جمع‌آوری می‌کند."""
    all_configs = []
    sources = SETTINGS.get("sources", {})
    for file_path in sources.get("files", []):
        url = f"https://raw.githubusercontent.com/{file_path}"
        content = get_content_from_url(url)
        if content:
            all_configs.extend(content.splitlines())
            
    print(f"مجموعاً {len(all_configs)} کانفیگ از منابع مختلف جمع‌آوری شد.")
    return all_configs

def decode_base64_configs(configs):
    """محتوای Base64 را دیکود می‌کند."""
    decoded_configs = []
    for config in configs:
        if not any(proto in config for proto in SETTINGS.get("protocols", [])):
            try:
                padding = '=' * (-len(config) % 4)
                decoded_content = base64.b64decode(config + padding).decode('utf-8')
                decoded_configs.extend(decoded_content.splitlines())
            except Exception:
                decoded_configs.append(config)
        else:
            decoded_configs.append(config)
    return decoded_configs

# --- بخش تست و ارزیابی کانفیگ‌ها ---

class V2RayPingTester:
    def __init__(self, configs, timeout=5):
        self.configs = configs
        self.timeout = timeout
        self.max_threads = 200

    def parse_config(self, config_link):
        try:
            if "://" not in config_link: return None
            protocol = config_link.split("://")[0]
            if protocol not in SETTINGS.get("protocols", []): return None
            uri_part = config_link.split('://')[1]
            main_part = uri_part.split('#')[0]
            host_part = main_part.split('?')[0]
            if '@' in host_part: host_port_str = host_part.split('@')[1]
            else: host_port_str = host_part
            if ':' in host_port_str:
                host = host_port_str.rsplit(':', 1)[0].strip("[]")
                port = int(host_port_str.rsplit(':', 1)[1])
            else:
                host = host_port_str
                port = 443
            use_tls = 'security=tls' in main_part.lower() or port == 443
            return host, port, use_tls
        except Exception:
            return None

    def test_single(self, config):
        parsed_data = self.parse_config(config)
        if not parsed_data or not parsed_data[0]: return None
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
        reachable_configs = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_config = {executor.submit(self.test_single, config): config for config in self.configs}
            for i, future in enumerate(as_completed(future_to_config)):
                result = future.result()
                if result:
                    reachable_configs.append(result)
                print(f"\rتست کانفیگ‌ها: {i+1}/{len(self.configs)}", end="")
        print("\nتست کامل شد.")
        return sorted(reachable_configs, key=lambda x: x['ping'])

# --- بخش اصلی و اجرای برنامه ---

def main():
    start_time = time.time()
    
    # ۱. ایجاد پوشه‌های خروجی
    base_out_dir = create_output_dirs()
    
    # ۲. دریافت و پاک‌سازی کانفیگ‌ها
    raw_configs = get_all_sources_content()
    decoded_configs = decode_base64_configs(raw_configs)
    
    unique_configs = sorted(list(set(filter(None, decoded_configs))))
    
    # ۳. تفکیک کانفیگ‌های Warp
    warp_configs = [c for c in unique_configs if c.startswith("warp://")]
    v2ray_configs = [c for c in unique_configs if not c.startswith("warp://")]
    
    valid_protocol_configs = [c for c in v2ray_configs if any(p in c for p in SETTINGS.get("protocols", []))]
    
    limit = SETTINGS.get("all_configs_limit", 3000)
    configs_to_test = valid_protocol_configs[:limit]
    
    print(f"تعداد {len(configs_to_test)} کانفیگ V2Ray و {len(warp_configs)} کانفیگ Warp برای پردازش آماده شد.")

    # ۴. تست کانفیگ‌های V2Ray
    tester = V2RayPingTester(configs_to_test, timeout=SETTINGS.get("timeout", 5))
    reachable_results = tester.test_all()
    
    print(f"تعداد {len(reachable_results)} کانفیگ سالم پیدا شد.")

    # ۵. نوشتن فایل‌های خروجی
    
    # --- پردازش و ذخیره کانفیگ‌های V2Ray ---
    v2ray_dir = os.path.join(base_out_dir, "v2ray")
    base64_dir = os.path.join(base_out_dir, "base64")
    
    all_v2_configs = [res['config'] for res in reachable_results]
    all_v2_str = "\n".join(all_v2_configs)
    
    # ذخیره در v2ray/all_sub.txt
    with open(os.path.join(v2ray_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
        f.write(all_v2_str)
    # ذخیره نسخه Base64
    with open(os.path.join(base64_dir, "all_sub.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode(all_v2_str.encode("utf-8")).decode("utf-8"))

    # ذخیره فایل‌های تکه‌تکه شده
    lines_per_file = SETTINGS.get("lines_per_file", 200)
    save_split_files(all_v2_configs, os.path.join(v2ray_dir, "subs"), lines_per_file, is_base64=False)
    save_split_files(all_v2_configs, os.path.join(base64_dir, "subs"), lines_per_file, is_base64=True)
    
    # ذخیره super-sub
    super_limit = SETTINGS.get("supersub_configs_limit", 200)
    super_configs = all_v2_configs[:super_limit]
    super_configs_str = "\n".join(super_configs)
    with open(os.path.join(v2ray_dir, "super-sub.txt"), "w", encoding="utf-8") as f:
        f.write(super_configs_str)

    # --- پردازش و ذخیره کانفیگ‌های Warp ---
    if warp_configs:
        warp_str = "\n".join(warp_configs)
        with open(os.path.join(base_out_dir, "warp", "all_sub.txt"), "w", encoding="utf-8") as f:
            f.write(warp_str)
        print(f"✅ فایل اشتراک Warp با {len(warp_configs)} کانفیگ ساخته شد.")

    # --- پردازش و ذخیره بر اساس پروتکل ---
    filtered_dir = os.path.join(base_out_dir, "filtered", "subs")
    protocol_groups = {}
    for res in reachable_results:
        config_link = res['config']
        try:
            protocol = config_link.split("://")[0]
            if protocol not in protocol_groups:
                protocol_groups[protocol] = []
            protocol_groups[protocol].append(config_link)
        except IndexError:
            continue

    for protocol, configs in protocol_groups.items():
        if configs:
            protocol_str = "\n".join(configs)
            file_path = os.path.join(filtered_dir, f"{protocol}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(protocol_str)
            print(f"✅ فایل اشتراک برای پروتکل '{protocol}' با {len(configs)} کانفیگ ساخته شد.")

    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
