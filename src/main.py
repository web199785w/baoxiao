import os
import base64
import json
import pandas as pd
from PIL import Image
from io import BytesIO
from datetime import datetime
from pathlib import Path
from openai_tools import OpenAITools

from dotenv import load_dotenv

# 在程序开始时加载环境变量
load_dotenv()

# 检查API密钥
if not os.getenv('OPENAI_API_KEY'):
    print("❌ 错误：未找到 OPENAI_API_KEY 环境变量")
    print("请创建 .env 文件并设置: OPENAI_API_KEY=你的密钥")
    exit(1)

# 程序开始时间
start_time = datetime.now()
print(f"程序开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}")

# 项目路径设置
PROJECT_ROOT = Path(__file__).parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "input" / "payment_images"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "results"

# 确保目录存在
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 输出文件名
today = datetime.today().strftime('%Y%m%d')
OUTPUT_FILE = OUTPUT_DIR / f"{today}_财务识别结果.xlsx"

print(f"📁 输入目录: {INPUT_DIR}")
print(f"📄 输出文件: {OUTPUT_FILE}")

# 字段输出顺序
column_order = [
    "费用日期", "费用类别", "费用内容",
    "起点", "终点",
    "支出金额", "货币", "支付渠道",
    "文件名"
]

# 推断支付渠道：信用卡 / 支付宝 / 微信
def infer_payment_channel(币种, 付款账户):
    if "信用卡" in 付款账户 or "银行" in 付款账户:
        return "信用卡"
    if "零钱通" in 付款账户 or "微信" in 付款账户:
        return "微信"
    if "支付宝" in 付款账户 or "蚂蚁" in 付款账户:
        return "支付宝"
    if 币种 == "美元":
        return "信用卡"
    return ""

# 检查输入目录
if not INPUT_DIR.exists():
    print(f"❌ 输入目录不存在: {INPUT_DIR}")
    exit(1)

# 获取图片文件列表
image_files = [f for f in os.listdir(INPUT_DIR) 
               if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]

if not image_files:
    print(f"⚠️ 在 {INPUT_DIR} 中没有找到图片文件")
    exit(1)

print(f"📷 找到 {len(image_files)} 个图片文件")

# 初始化 OpenAI 工具类
ai_tool = OpenAITools()
results = []

# 遍历图片文件
for filename in image_files:
    file_path = INPUT_DIR / filename
    print(f"📄 正在处理：{filename}")

    # 转 base64，处理透明通道
    try:
        with Image.open(file_path) as img:
            if img.mode == "RGBA":
                img = img.convert("RGB")
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        print(f"❌ 图片处理失败 {filename}: {e}")
        results.append({
            "费用日期": "", "费用类别": "", "费用内容": "",
            "起点": "", "终点": "",
            "支出金额": "", "货币": "", "支付渠道": "",
            "文件名": filename
        })
        continue

    # 调用 AI 接口
    try:
        response = ai_tool.send_message_with_base64(img_base64)
    except Exception as e:
        print(f"❌ API 调用失败 {filename}: {e}")
        results.append({
            "费用日期": "", "费用类别": "", "费用内容": "",
            "起点": "", "终点": "",
            "支出金额": "", "货币": "", "支付渠道": "",
            "文件名": filename
        })
        continue

    # 解析 JSON
    try:
        data = json.loads(response)
        if data.get("code") == 200:
            d = data["data"]
            d["文件名"] = filename
            d["支付渠道"] = infer_payment_channel(d.get("币种", ""), d.get("付款账户", ""))
            print(f"✅ 识别成功：{d}")
            results.append(d)
        else:
            print(f"⚠️ 识别失败：{filename}")
            results.append({
                "费用日期": "", "费用类别": "", "费用内容": "",
                "起点": "", "终点": "",
                "支出金额": "", "货币": "", "支付渠道": "",
                "文件名": filename
            })
    except Exception as e:
        print(f"❌ JSON 解析失败 {filename}: {e}")
        continue

# 补字段 + 映射字段 + 格式化
for row in results:
    for field in column_order:
        if field not in row:
            row[field] = ""

    # 处理时间格式
    raw_time = row.get("付款时间", "")
    if raw_time:
        try:
            dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            row["费用日期"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        except:
            row["费用日期"] = raw_time
    else:
        row["费用日期"] = "1900/01/01 00:00:00"

    # 金额处理（去除符号）
    amount = row.get("金额", "")
    row["支出金额"] = amount.replace("¥", "").replace("$", "").strip() if amount else ""

    # 字段映射
    row["费用内容"] = row.get("费用用途", "")
    row["货币"] = row.get("币种", "")

# 写入 Excel
try:
    df = pd.DataFrame(results)
    df = df[column_order]
    df.to_excel(OUTPUT_FILE, index=False)
    print(f"\n✅ 已生成 Excel 文件：{OUTPUT_FILE}")
    print(f"📊 共处理 {len(results)} 个文件")
except Exception as e:
    print(f"❌ Excel 文件写入失败: {e}")

# 程序结束时间
end_time = datetime.now()
print(f"程序结束时间：{end_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"总耗时：{(end_time - start_time).total_seconds():.2f} 秒")