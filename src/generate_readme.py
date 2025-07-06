import os
import json

def main():
    # خواندن آمار از فایل گزارش
    try:
        with open("reports/stats.json", "r") as f:
            stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("فایل گزارش 'stats.json' پیدا نشد یا معتبر نیست.")
        return

    # خواندن قالب README
    try:
        with open("README.template.md", "r", encoding="utf-8") as f:
            readme_template = f.read()
    except FileNotFoundError:
        print("فایل قالب 'README.template.md' پیدا نشد.")
        return

    # جایگزینی مقادیر اصلی
    readme_content = readme_template.replace("{{UPDATE_TIME}}", stats["update_time"])
    readme_content = readme_content.replace("{{TOTAL_CONFIGS}}", str(stats["total_configs"]))
    
    # ساخت جدول کشورها
    country_table = "| کشور | تعداد | لینک اشتراک |\n| :--- | :---: | :---: |\n"
    sorted_countries = sorted(stats["countries"].items(), key=lambda item: item[1], reverse=True)
    
    for country, count in sorted_countries:
        if country == "Unknown": continue # از نمایش کشورهای ناشناس صرف نظر کن
        country_table += f"| **{country}** | `{count}` | [کپی](https://raw.githubusercontent.com/{os.getenv('GITHUB_REPOSITORY')}/main/subscriptions/regions/{country}.txt) |\n"

    readme_content = readme_content.replace("{{COUNTRY_TABLE}}", country_table)
    
    # جایگزینی نام کاربری و مخزن به صورت داینامیک
    repo_name = os.getenv('GITHUB_REPOSITORY', 'YOUR_USERNAME/YOUR_REPO')
    readme_content = readme_content.replace("YOUR_USERNAME/YOUR_REPO", repo_name)
    
    # نوشتن فایل نهایی
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ فایل README.md با موفقیت به‌روزرسانی شد.")

if __name__ == "__main__":
    main()
