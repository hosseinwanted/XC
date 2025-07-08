import os
import json

# این دیکشنری باید با دیکشنری main.py هماهنگ باشد
COUNTRY_NAMES = {
    "US": "ایالات متحده", "DE": "آلمان", "FR": "فرانسه", "NL": "هلند",
    "GB": "بریتانیا", "CA": "کانادا", "JP": "ژاپن", "SG": "سنگاپور",
    "IR": "ایران", "RU": "روسیه", "TR": "ترکیه", "AE": "امارات", "IN": "هند",
    "HK": "هنگ کنگ", "ID": "اندونزی", "KR": "کره جنوبی", "VN": "ویتنام",
    "AU": "استرالیا", "CH": "سوئیس", "SE": "سوئد", "FI": "فنلاند",
    "NO": "نروژ", "DK": "دانمارک", "IE": "ایرلند", "IT": "ایتالیا",
    "ES": "اسپانیا", "PL": "لهستان", "UA": "اوکراین", "RO": "رومانی",
    "CZ": "جمهوری چک", "AT": "اتریش", "BE": "بلژیک", "LU": "لوکزامبورگ",
    "PT": "پرتغال", "HU": "مجارستان", "BG": "بلغارستان", "RS": "صربستان",
    "GR": "یونان", "LT": "لیتوانی", "LV": "لتونی", "EE": "استونی",
    "MD": "مولداوی", "SI": "اسلوونی", "SK": "اسلواکی", "HR": "کرواسی",
    "BA": "بوسنی و هرزگوین", "AL": "آلبانی", "CY": "قبرس", "MT": "مالت",
    "IS": "ایسلند", "MX": "مکزیک", "BR": "برزیل", "AR": "آرژانتین",
    "CL": "شیلی", "CO": "کلمبیا", "PE": "پرو", "ZA": "آفریقای جنوبی",
    "EG": "مصر", "SA": "عربستان سعودی", "IL": "اسرائیل", "JO": "اردن",
    "KZ": "قزاقستان", "TH": "تایلند", "MY": "مالزی", "PH": "فیلیپین",
    "NZ": "نیوزیلند", "TW": "تایوان", "VG": "جزایر ویرجین بریتانیا",
    "MU": "موریس", "SC": "سیشل", "NP": "نپال"
}

def main():
    try:
        with open("reports/stats.json", "r", encoding="utf-8") as f:
            stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("فایل گزارش 'stats.json' پیدا نشد یا معتبر نیست.")
        return

    try:
        with open("README.template.md", "r", encoding="utf-8") as f:
            readme_template = f.read()
    except FileNotFoundError:
        print("فایل قالب 'README.template.md' پیدا نشد.")
        return

    repo_name = os.getenv('GITHUB_REPOSITORY', 'YOUR_USERNAME/YOUR_REPO')
    
    readme_content = readme_template.replace("{{UPDATE_TIME}}", stats["update_time"])
    readme_content = readme_content.replace("{{TOTAL_CONFIGS}}", str(stats["total_configs"]))
    readme_content = readme_content.replace("YOUR_USERNAME/YOUR_REPO", repo_name)

    sorted_countries = sorted(stats["countries"].items(), key=lambda item: item[1], reverse=True)
    
    num_countries = len(sorted_countries)
    col_len = (num_countries + 2) // 3
    cols = [sorted_countries[i:i + col_len] for i in range(0, num_countries, col_len)]
    
    country_table = "| کشور | تعداد | لینک | کشور | تعداد | لینک | کشور | تعداد | لینک |\n"
    country_table += "| :--- | :---: | :---: | :--- | :---: | :---: | :--- | :---: | :---: |\n"
    
    for i in range(col_len):
        row_items = []
        for col_idx in range(3):
            if i < len(cols[col_idx]):
                country, count = cols[col_idx][i]
                if country == "Unknown": continue
                country_code = next((code for code, name in COUNTRY_NAMES.items() if name == country), country)
                link = f"[`{country}`](https://raw.githubusercontent.com/{repo_name}/main/subscriptions/regions/{country_code}.txt)"
                row_items.extend([link, f"`{count}`", "✅"])
            else:
                row_items.extend(["", "", ""])
        country_table += f"| {' | '.join(row_items)} |\n"

    readme_content = readme_content.replace("{{COUNTRY_TABLE}}", country_table)
    
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ فایل README.md با موفقیت به‌روزرسانی شد.")

if __name__ == "__main__":
    main()
