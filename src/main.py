import os
import json
import base64
import requests
import socket
import ssl
import time
import re
import subprocess
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

def get_all_sources_content():
    """تمام کانفیگ‌ها را از منابع جمع‌آوری می‌کند."""
    all_configs = []
    sources = SETTINGS.get("sources", {})
    for file_path in sources.get("files", []):
        url = f"https://raw.githubusercontent.com/{file_path}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            all_configs.extend(response.text.splitlines())
        except requests.RequestException as e:
            print(f"خطا در دریافت محتوا از {url}: {e}")
            
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

class FastHandshakeTester:
    """مرحله اول: تست سریع برای حذف سرورهای مرده."""
    def __init__(self, configs, timeout=3):
        self.configs = configs
        self.timeout = timeout
        self.max_threads = 400

    def test_single(self, config):
        try:
            # --- رفع اشکال: متغیر از config به config_link تغییر نام داده شده بود ---
            if "://" not in config: return None
            uri_part = config.split('://')[1]
            host_part = uri_part.split('#')[0].split('?')[0]
            if '@' in host_part: host_port_str = host_part.split('@')[1]
            else: host_port_str = host_part
            if ':' in host_port_str:
                host = host_port_str.rsplit(':', 1)[0].strip("[]")
                port = int(host_port_str.rsplit(':', 1)[1])
            else:
                host = host_port_str
                port = 443
            sock = socket.create_connection((host, port), timeout=self.timeout)
            sock.close()
            return config
        except Exception:
            return None

    def run(self):
        passed_configs = []
        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            future_to_config = {executor.submit(self.test_single, config): config for config in self.configs}
            for i, future in enumerate(as_completed(future_to_config)):
                if future.result():
                    passed_configs.append(future.result())
                print(f"\rمرحله ۱ (فیلتر سریع): {i+1}/{len(self.configs)}", end="")
        print("\nفیلتر سریع کامل شد.")
        return passed_configs

def deep_test_with_sing_box(configs):
    """مرحله دوم: تست عمیق با ابزار sing-box."""
    print("مرحله ۲ (تست عمیق با sing-box) شروع شد...")
    
    # ساخت فایل کانفیگ برای sing-box
    outbounds = []
    config_map = {}
    for i, config_link in enumerate(configs):
        tag = f"proxy_{i}"
        # برای تست URL، هر کانفیگ باید در یک outbound جداگانه باشد
        outbounds.append({"type": "selector", "tag": tag, "outbounds": [config_link]})
        config_map[tag] = config_link

    singbox_config = {
        "outbounds": outbounds
    }

    # ایجاد یک فایل کانفیگ موقت برای sing-box
    with open("singbox_config.json", "w") as f:
        json.dump(singbox_config, f)

    # ایجاد فایل کانفیگ دیگر برای urltest
    urltest_config = {
        "outbounds": [item['tag'] for item in outbounds],
        "url": "http://www.gstatic.com/generate_204",
        "interval": "10s"
    }

    with open("urltest_config.json", "w") as f:
        json.dump(urltest_config, f)


    try:
        # اجرای دستور urltest با استفاده از کانفیگ‌های ساخته شده
        command = ['./sing-box', 'urltest', '-c', 'singbox_config.json', '-config-test', 'urltest_config.json']
        process = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"خطای بحرانی در اجرای sing-box: {e}")
        return []

    results = []
    output_lines = process.stdout.strip().split('\n')
    
    # مثال خروجی: proxy_10 	 245 ms
    result_regex = re.compile(r"(\w+)\s+(\d+)\s+ms")
    
    for line in output_lines:
        match = result_regex.search(line)
        if match:
            tag = match.group(1)
            ping_ms = int(match.group(2))
            if tag in config_map:
                results.append({'config': config_map[tag], 'ping': ping_ms})

    print(f"تست عمیق کامل شد. {len(results)} کانفیگ سالم تایید شد.")
    return sorted(results, key=lambda x: x['ping'])

# --- بخش اصلی و اجرای برنامه ---

def main():
    start_time = time.time()
    base_out_dir = create_output_dirs()
    
    raw_configs = get_all_sources_content()
    decoded_configs = decode_base64_configs(raw_configs)
    unique_configs = sorted(list(set(filter(None, decoded_configs))))
    
    warp_configs = [c for c in unique_configs if c.startswith("warp://")]
    v2ray_configs = [c for c in unique_configs if not c.startswith("warp://") and any(p in c for p in SETTINGS.get("protocols", []))]
    
    limit = SETTINGS.get("all_configs_limit", 4000)
    configs_to_fast_test = v2ray_configs[:limit]
    
    print(f"تعداد {len(configs_to_fast_test)} کانفیگ برای فیلتر سریع آماده شد.")

    fast_tester = FastHandshakeTester(configs_to_fast_test)
    passed_fast_test = fast_tester.run()
    
    if not passed_fast_test:
        print("هیچ کانفیگی از فیلتر سریع عبور نکرد.")
    else:
        final_results = deep_test_with_sing_box(passed_fast_test)
        if not final_results:
            print("هیچ کانفیگی در تست عمیق سالم نبود.")
        else:
            # نوشتن فایل‌های خروجی بر اساس نتایج دقیق
            all_final_configs = [res['config'] for res in final_results]
            v2ray_dir = os.path.join(base_out_dir, "v2ray")
            base64_dir = os.path.join(base_out_dir, "base64")
            all_v2_str = "\n".join(all_final_configs)
            with open(os.path.join(v2ray_dir, "all_sub.txt"), "w", encoding="utf-8") as f: f.write(all_v2_str)
            with open(os.path.join(base64_dir, "all_sub.txt"), "w", encoding="utf-8") as f: f.write(base64.b64encode(all_v2_str.encode("utf-8")).decode("utf-8"))
            lines_per_file = SETTINGS.get("lines_per_file", 200)
            save_split_files(all_final_configs, os.path.join(v2ray_dir, "subs"), lines_per_file)
            save_split_files(all_final_configs, os.path.join(base64_dir, "subs"), lines_per_file, is_base64=True)
            super_limit = SETTINGS.get("supersub_configs_limit", 200)
            super_configs = all_final_configs[:super_limit]
            super_configs_str = "\n".join(super_configs)
            with open(os.path.join(v2ray_dir, "super-sub.txt"), "w", encoding="utf-8") as f: f.write(super_configs_str)
            filtered_dir = os.path.join(base_out_dir, "filtered", "subs")
            protocol_groups = {}
            for config_link in all_final_configs:
                try:
                    protocol = config_link.split("://")[0]
                    if protocol not in protocol_groups: protocol_groups[protocol] = []
                    protocol_groups[protocol].append(config_link)
                except IndexError: continue
            for protocol, configs in protocol_groups.items():
                if configs:
                    protocol_str = "\n".join(configs)
                    with open(os.path.join(filtered_dir, f"{protocol}.txt"), "w", encoding="utf-8") as f: f.write(protocol_str)
                    print(f"✅ فایل اشتراک برای پروتکل '{protocol}' با {len(configs)} کانفیگ ساخته شد.")

    if warp_configs:
        warp_str = "\n".join(warp_configs)
        with open(os.path.join(base_out_dir, "warp", "all_sub.txt"), "w", encoding="utf-8") as f: f.write(warp_str)
        print(f"✅ فایل اشتراک Warp با {len(warp_configs)} کانفیگ ساخته شد.")

    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
