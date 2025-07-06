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

# --- بخش تنظیمات ---
V2RAY_CORE_PATH = "v2ray_core/v2ray"
TEMP_CONFIG_DIR = "temp_configs"
MAX_THREADS = 150
START_PORT = 10800
TEST_TIMEOUT = 10
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

def parse_link(link):
    """تجزیه هوشمند انواع لینک‌ها."""
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
        b64_part = link.replace("vmess://", "")
        if len(b64_part) % 4 != 0: b64_part += '=' * (4 - len(b64_part) % 4)
        data = json.loads(base64.b64decode(b64_part).decode('utf-8'))
        return {'type': 'vmess', 'data': data, 'original_link': link}
    except Exception: return None

def parse_vless(link):
    try:
        parsed = urlparse(link)
        params = parse_qs(parsed.query)
        data = {
            'add': parsed.hostname, 'port': parsed.port, 'id': parsed.username,
            'ps': unquote(parsed.fragment) if parsed.fragment else f"vless-{parsed.hostname}",
            'params': params
        }
        return {'type': 'vless', 'data': data, 'original_link': link}
    except Exception: return None

def parse_trojan(link):
    try:
        parsed = urlparse(link)
        params = parse_qs(parsed.query)
        data = {
            'add': parsed.hostname, 'port': parsed.port, 'password': unquote(parsed.username),
            'ps': unquote(parsed.fragment) if parsed.fragment else f"trojan-{parsed.hostname}",
            'params': params
        }
        return {'type': 'trojan', 'data': data, 'original_link': link}
    except Exception: return None

class V2RayTester:
    def __init__(self, config_info, port):
        self.config_info = config_info
        self.port = port
        self.proc = None
        self.config_path = os.path.join(TEMP_CONFIG_DIR, f"config_{port}.json")

    def build_config(self):
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
            outbound_settings['vnext'] = [{'address': data.get('add'), 'port': int(data.get('port', 0)), 'users': [{'id': data.get('id'), 'alterId': int(data.get('aid', 0)), 'security': data.get('scy', 'auto')}]}]
            stream_settings.update({'network': data.get('net', 'tcp'), 'security': data.get('tls', 'none')})
            if data.get('net') == 'ws': stream_settings['wsSettings'] = {'path': data.get('path', '/'), 'headers': {'Host': data.get('host', data.get('add'))}}
            if data.get('tls') == 'tls': stream_settings['tlsSettings'] = {'serverName': data.get('sni', data.get('host', data.get('add')))}
        
        elif protocol in ['vless', 'trojan']:
            params = data.get('params', {})
            if protocol == 'vless':
                outbound_settings['vnext'] = [{'address': data['add'], 'port': int(data['port']), 'users': [{'id': data['id'], 'flow': params.get('flow', [''])[0]}]}]
            else:
                outbound_settings['servers'] = [{'address': data['add'], 'port': int(data['port']), 'password': data['password']}]

            stream_settings.update({'network': params.get('type', ['tcp'])[0], 'security': params.get('security', ['none'])[0]})
            if stream_settings['network'] == 'ws': stream_settings['wsSettings'] = {'path': params.get('path', ['/'])[0], 'headers': {'Host': params.get('host', [data['add']])[0]}}
            if stream_settings['security'] == 'tls': stream_settings['tlsSettings'] = {'serverName': params.get('sni', [data['add']])[0], "allowInsecure": True}
            elif stream_settings['security'] == 'reality': stream_settings['realitySettings'] = {'publicKey': params.get('pbk', [''])[0], 'shortId': params.get('sid', [''])[0], 'serverName': params.get('sni', [data['add']])[0]}
        
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return True

    def run_test(self):
        if not self.build_config(): return None, -1
        cmd = [V2RAY_CORE_PATH, "run", "-c", self.config_path]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.5)
            if self.proc.poll() is not None: return None, -1
            proxies = {'http': f'socks5://127.0.0.1:{self.port}', 'https': f'socks5://127.0.0.1:{self.port}'}
            start_req_time = time.time()
            response = requests.get(TEST_URL, proxies=proxies, timeout=TEST_TIMEOUT)
            if response.status_code == 204:
                latency = int((time.time() - start_req_time) * 1000)
                return self.config_info['original_link'], latency
        except Exception:
            return None, -1
        finally:
            if self.proc: self.proc.terminate(); self.proc.wait()
            if os.path.exists(self.config_path): os.remove(self.config_path)
        return None, -1

def worker(config_queue, result_queue, port):
    while not config_queue.empty():
        try:
            config_info = config_queue.get_nowait()
            tester = V2RayTester(config_info, port)
            link, latency = tester.run_test()
            if link:
                result_queue.put({'config': link, 'ping': latency})
        except queue.Empty: break

def main():
    start_time = time.time()
    setup_directories()

    all_links = get_sources()
    valid_configs = [parse_link(link) for link in all_links if parse_link(link)]
    print(f"تعداد {len(valid_configs)} کانفیگ معتبر برای تست آماده شد.")

    config_q = queue.Queue()
    for config in valid_configs: config_q.put(config)
    
    result_q = queue.Queue()
    threads = [threading.Thread(target=worker, args=(config_q, result_q, START_PORT + i)) for i in range(min(MAX_THREADS, len(valid_configs)))]
    for t in threads: t.start()
    for t in threads: t.join()

    final_results = []
    while not result_q.empty(): final_results.append(result_q.get())
    final_results.sort(key=lambda x: x['ping'])
    print(f"تست کامل شد. {len(final_results)} کانفیگ سالم پیدا شد.")

    if final_results:
        all_final_links = [res['config'] for res in final_results]
        
        base_dir = SETTINGS.get("out_dir", "subscriptions")
        v2ray_dir = os.path.join(base_dir, "v2ray")
        base64_dir = os.path.join(base_dir, "base64")

        with open(os.path.join(v2ray_dir, "all_sub.txt"), "w", encoding="utf-8") as f: f.write("\n".join(all_final_links))
        with open(os.path.join(base64_dir, "all_sub.txt"), "w", encoding="utf-8") as f: f.write(base64.b64encode("\n".join(all_final_links).encode()).decode())
    
    print(f"\nکل فرآیند در {time.time() - start_time:.2f} ثانیه به پایان رسید.")

if __name__ == "__main__":
    main()
