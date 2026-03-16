import requests
import time
import random
import csv
import os
import sys
from bs4 import BeautifulSoup
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 全局配置（无需修改）
BASE_URL = "http://kaijiang.zhcw.com/zhcw/html/ssq/list_{}.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://kaijiang.zhcw.com/zhcw/html/ssq/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cookie": "your_cookie_here"  # 替换为浏览器中该网站的真实Cookie（F12-网络-请求头复制）
}
CSV_FILE = "ssq_history.csv"
RETRY_TIMES = 3  # 失败重试次数
DELAY_RANGE = (3, 6)  # 延长请求间隔，降低反爬风险
DEBUG_SAVE_HTML = True  # 是否保存调试页面


def get_page_content(url):
    """使用Selenium获取动态页面"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # 无头模式（不显示浏览器）
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    try:
        driver.get(url)
        time.sleep(3)  # 等待JS加载完成
        html = driver.page_source
        print(f"✅ 成功获取动态页面，长度：{len(html)}")
        if DEBUG_SAVE_HTML:
            with open("debug_selenium_page.html", "w", encoding="utf-8") as f:
                f.write(html)
        return html
    except Exception as e:
        print(f"❌ Selenium获取页面失败：{e}")
        return None
    finally:
        driver.quit()


def init_csv():
    """初始化CSV文件（首次运行自动创建表头）"""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["期号", "开奖日期", "红球", "蓝球"])
        print(f"✅ 初始化CSV文件成功：{CSV_FILE}")


def get_existing_periods():
    """获取已爬取的期号（优先GBK，减少失败提示）"""
    if not os.path.exists(CSV_FILE):
        return set()
    periods = set()
    encodings = ["gbk", "utf-8", "gb2312", "utf-8-sig"]
    for idx, encoding in enumerate(encodings):
        try:
            with open(CSV_FILE, "r", encoding=encoding) as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if row and len(row) >= 1:
                        period = row[0].strip()
                        if period:
                            periods.add(period)
            print(f"✅ 成功读取已有期号（编码：{encoding}），共{len(periods)}条")
            return periods
        except Exception as e:
            if idx > 0:
                print(f"⚠️  尝试{encoding}编码读取失败：{str(e)[:50]}，继续尝试下一种编码")
            continue
    print("❌ 所有编码都无法读取CSV，将重新爬取所有数据")
    return set()


def parse_page(html, existing_periods, page_num=1):
    """解析页面数据（极简日志版）"""
    soup = BeautifulSoup(html, "html.parser")
    new_data = []
    table = soup.find("table", class_="t_tr1") or soup.find("table", class_="t_tr2") or soup.find("table")
    if not table:
        print("❌ 未找到开奖表格")
        return new_data

    all_trs = table.find_all("tr")
    for tr in all_trs:
        row_text = tr.text.strip().replace("\n", " ").replace("  ", " ").replace("\r", "")
        filter_keywords = ["开奖日期", "一等奖", "二等奖", "共", "页", "当前第", "首页", "上一页", "下一页", "末页"]
        if not row_text or any(keyword in row_text for keyword in filter_keywords):
            continue

        parts = row_text.split()
        if len(parts) < 9:
            continue

        date = parts[0]
        period = parts[1]
        red_balls = parts[2:8]
        blue_ball = parts[8]

        if not period.isdigit() or len(period) < 6:
            continue
        if len(red_balls) != 6 or not all(ball.isdigit() for ball in red_balls) or not blue_ball.isdigit():
            continue

        red_balls_str = ",".join(red_balls)
        if period not in existing_periods:
            new_data.append([period, date, red_balls_str, blue_ball])

    if new_data:
        print(f"✅ 第{page_num}页解析到 {len(new_data)} 条新增数据")
    else:
        print(f"ℹ️  第{page_num}页无新增数据")
    return new_data


def extract_total_pages(html):
    """从页面分页文本中提取真实总页数"""
    soup = BeautifulSoup(html, "html.parser")
    all_trs = soup.find_all("tr")
    for tr in all_trs:
        row_text = tr.text.strip().replace(" ", "").replace("\n", "")
        if "共" in row_text and "页" in row_text:
            import re
            match = re.search(r"共(\d+)页", row_text)
            if match:
                total_pages = int(match.group(1))
                print(f"✅ 从页面提取到真实总页数：{total_pages}")
                return total_pages
    print("⚠️  提取总页数失败，默认爬取200页")
    return 200


def full_crawl():
    """全量爬取（极简日志版）"""
    print("\n=============== 开始全量爬取 ===============")
    init_csv()
    existing_periods = get_existing_periods()
    initial_count = len(existing_periods)

    print("🔍 爬取第1页，提取总页数...")
    first_page_html = get_page_content(BASE_URL.format(1))
    if not first_page_html:
        print("❌ 无法获取第1页数据，爬取终止")
        return
    total_pages = extract_total_pages(first_page_html)

    all_new_data = []
    for page_num in range(1, total_pages + 1):
        print(f"\n🔍 正在爬取第 {page_num}/{total_pages} 页...")
        html = first_page_html if page_num == 1 else get_page_content(BASE_URL.format(page_num))

        if not html:
            print(f"⚠️  第{page_num}页爬取失败，跳过")
            continue

        new_data = parse_page(html, existing_periods, page_num=page_num)
        all_new_data.extend(new_data)
        existing_periods.update(item[0] for item in new_data)

        if page_num % 10 == 0 and all_new_data:
            with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(all_new_data)
            print(f"💾 已保存前{page_num}页数据，累计新增{len(all_new_data)}条")
            all_new_data = []

    remaining_count = len(all_new_data)
    if all_new_data:
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(all_new_data)
        print(f"💾 保存最后一批数据，新增{remaining_count}条")

    total_added = len(existing_periods) - initial_count
    print("\n🎉 全量爬取完成！")
    print(f"📊 累计新增 {total_added} 条有效数据（去重后）")
    print(f"📁 数据文件：{CSV_FILE}")


def incremental_crawl():
    """增量爬取（日常更新）"""
    print(f"\n=============== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始增量爬取 ===============")
    init_csv()
    existing_periods = get_existing_periods()

    html = get_page_content(BASE_URL.format(1))
    if not html:
        print("❌ 增量爬取失败：无法获取最新页数据")
        return

    new_data = parse_page(html, existing_periods, page_num=1)
    if new_data:
        with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(new_data)
        print(f"✅ 增量爬取完成！新增 {len(new_data)} 条数据")
    else:
        print("✅ 增量爬取完成，暂无新数据")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 请指定运行模式：")
        print("   首次全量爬取：python ssq_crawler.py full")
        print("   日常增量爬取：python ssq_crawler.py inc")
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode == "full":
        full_crawl()
    elif mode == "inc":
        incremental_crawl()
    else:
        print("❌ 无效参数！支持的参数：full（全量）、inc（增量）")
        sys.exit(1)
