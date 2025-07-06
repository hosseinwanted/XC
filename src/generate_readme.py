import os
import json

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

    # --- بخش جدید: ساخت جدول سه ستونه برای کشورها ---
    sorted_countries = sorted(stats["countries"].items(), key=lambda item: item[1], reverse=True)
    
    # تقسیم لیست کشورها به سه ستون
    num_countries = len(sorted_countries)
    col_len = (num_countries + 2) // 3
    cols = [sorted_countries[i:i + col_len] for i in range(0, num_countries, col_len)]
    
    # ساخت هدر جدول
    country_table = "| کشور | تعداد | لینک | کشور | تعداد | لینک | کشور | تعداد | لینک |\n"
    country_table += "| :--- | :---: | :---: | :--- | :---: | :---: | :--- | :---: | :---: |\n"
    
    # پر کردن ردیف‌های جدول
    for i in range(col_len):
        row_items = []
        for col_idx in range(3):
            if i < len(cols[col_idx]):
                country, count = cols[col_idx][i]
                if country == "Unknown": continue
                link = f"[`{country}`](https://raw.githubusercontent.com/{repo_name}/main/subscriptions/regions/{country}.txt)"
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
