import os
import base64
import json
import pandas as pd
from PIL import Image
from io import BytesIO
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import uuid
import shutil
import zipfile

from openai_tools import OpenAITools
from dotenv import load_dotenv

from db_utils import get_conn, get_client_ip
from datetime import timezone          # 用于带时区时间戳
import pymysql                         # finally 里 close 连接用
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# 加载环境变量
load_dotenv()

# app = Flask(__name__)
# CORS(app)  # 允许前端跨域访问

app = Flask(__name__)

# 配置 CORS - 只允许特定域名访问
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://reim-apply.fivepointtex.com"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Disposition"]  # 重要：允许前端读取下载文件名
    }
})

# 配置路径
PROJECT_ROOT = Path(__file__).parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "input" / "payment_images"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "results"
TEMP_DIR = PROJECT_ROOT / "data" / "temp"

# 确保目录存在
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 全局变量存储当前处理结果
current_results = []
current_temp_dir = None

# 字段输出顺序
column_order = [
    "费用日期", "费用类别", "费用内容",
    "起点", "终点",
    "支出金额", "货币", "支付渠道",
    "文件名"
]

def cleanup_temp_dir(temp_dir):
    """删除临时目录"""
    try:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"🧹 删除临时目录: {temp_dir}")
    except Exception as e:
        print(f"⚠️ 删除临时目录失败: {e}")

def infer_payment_channel(币种, 付款账户):
    """推断支付渠道"""
    if "信用卡" in 付款账户 or "银行" in 付款账户:
        return "信用卡"
    if "零钱通" in 付款账户 or "微信" in 付款账户:
        return "微信"
    if "支付宝" in 付款账户 or "蚂蚁" in 付款账户:
        return "支付宝"
    if 币种 == "美元":
        return "信用卡"
    return ""

def process_single_image(file_path, filename):
    """处理单张图片的识别逻辑"""
    print(f"📄 正在处理：{filename}")
    
    # 初始化默认结果
    default_result = {
        "费用日期": "1900/01/01 00:00:00", 
        "费用类别": "", 
        "费用内容": "",
        "起点": "", 
        "终点": "",
        "支出金额": "", 
        "货币": "", 
        "支付渠道": "",
        "文件名": filename,
        "识别状态": "失败"
    }

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
        default_result["错误信息"] = f"图片处理失败: {str(e)}"
        return default_result

    # 调用 AI 接口
    try:
        ai_tool = OpenAITools()
        response = ai_tool.send_message_with_base64(img_base64)
    except Exception as e:
        print(f"❌ API 调用失败 {filename}: {e}")
        default_result["错误信息"] = f"AI识别失败: {str(e)}"
        return default_result

    # 解析 JSON
    try:
        data = json.loads(response)
        if data.get("code") == 200:
            d = data["data"]
            d["文件名"] = filename
            d["支付渠道"] = infer_payment_channel(d.get("币种", ""), d.get("付款账户", ""))
            d["识别状态"] = "成功"
            
            # 处理时间格式
            raw_time = d.get("付款时间", "")
            if raw_time:
                try:
                    dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                    d["费用日期"] = dt.strftime("%Y/%m/%d %H:%M:%S")
                except:
                    d["费用日期"] = raw_time
            else:
                d["费用日期"] = "1900/01/01 00:00:00"

            # 金额处理（去除符号）
            amount = d.get("金额", "")
            d["支出金额"] = amount.replace("¥", "").replace("$", "").strip() if amount else ""

            # 字段映射
            d["费用内容"] = d.get("费用用途", "")
            d["货币"] = d.get("币种", "")
            
            # 补充缺失字段
            for field in column_order:
                if field not in d:
                    d[field] = ""
            
            print(f"✅ 识别成功：{d}")
            return d
        else:
            print(f"⚠️ 识别失败：{filename}")
            default_result["错误信息"] = "AI识别返回失败代码"
            return default_result
    except Exception as e:
        print(f"❌ JSON 解析失败 {filename}: {e}")
        default_result["错误信息"] = f"结果解析失败: {str(e)}"
        return default_result

@app.route('/api/batch-rename', methods=['POST'])
def api_batch_rename():
    """批量重命名接口 - 支持上传前后的重命名"""
    try:
        data = request.json
        prefix = data.get('prefix', '').strip()
        files_info = data.get('files', [])
        
        if not prefix:
            return jsonify({"error": "请提供文件名前缀"}), 400
        
        # 生成重命名映射，不管文件是否已上传
        renamed_files = []
        for index, file_info in enumerate(files_info):
            old_name = file_info.get('originalName', '')
            file_extension = Path(old_name).suffix
            new_name = f"{prefix}_{str(index + 1).zfill(2)}{file_extension}"
            
            renamed_files.append({
                "id": file_info.get('id'),
                "oldName": old_name,
                "newName": new_name,
                "success": True
            })
        
        return jsonify({
            "success": True,
            "files": renamed_files,
            "successCount": len(renamed_files),
            "totalCount": len(files_info),
            "message": f"重命名规则已设置，将应用到 {len(files_info)} 个文件（上传时会使用新文件名）"
        })
        
    except Exception as e:
        print(f"❌ 批量重命名失败: {e}")
        return jsonify({"error": str(e)}), 500


def cleanup_output_dir():
    """删除输出目录中的旧文件"""
    try:
        if OUTPUT_DIR.exists():
            deleted_count = 0
            for file_path in OUTPUT_DIR.glob('*'):
                if file_path.is_file():
                    file_path.unlink()
                    print(f"🗑️ 删除旧文件: {file_path.name}")
                    deleted_count += 1
            
            if deleted_count > 0:
                print(f"🧹 已清理 {deleted_count} 个旧文件")
            else:
                print("📁 输出目录为空，无需清理")
                
    except Exception as e:
        print(f"⚠️ 清理输出目录失败: {e}")

@app.route('/api/recognize-expenses', methods=['POST'])
def api_recognize_expenses():
    """批量识别票据，自动写 session / detail 表"""
    global current_results, current_temp_dir

    # ---------- 0. 会话初始化 ----------
    start_at     = datetime.now(timezone.utc)
    session_uuid = str(uuid.uuid4())
    client_ip    = get_client_ip()

    conn        = get_conn()
    session_id  = None
    success_cnt = 0
    failed_cnt  = 0
    current_results = []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO expense_ocr_session
                   (request_uuid,total_files,success_files,failed_files,
                    started_at,status,client_ip)
                   VALUES (%s,0,0,0,%s,'processing',%s)""",
                (session_uuid, start_at, client_ip)
            )
            session_id = cur.lastrowid

        # ---------- 1. 清理目录 ----------
        print("🧹 开始清理旧文件...")
        cleanup_output_dir()  # 🔥 新增：清理输出目录
        
        if current_temp_dir:
            cleanup_temp_dir(current_temp_dir)

        current_temp_dir = TEMP_DIR / str(uuid.uuid4())
        current_temp_dir.mkdir(exist_ok=True)

        # ---------- 2. 获取上传文件 ----------
        files      = request.files.getlist('files')
        file_names = request.form.getlist('fileNames[]')
        if not files:
            return jsonify({"error": "没有收到文件"}), 400

        print(f"📷 开始处理 {len(files)} 个图片文件")

        # ---------- 3. 循环识别 ----------
        for i, file in enumerate(files):
            if not (file and file.filename):
                continue

            renamed_filename = (
                file_names[i] if i < len(file_names) and file_names[i]
                else secure_filename(file.filename)
            )
            file_path = current_temp_dir / renamed_filename
            file.save(file_path)

            result = process_single_image(file_path, renamed_filename)
            current_results.append(result)

            # —— 中文状态 → 英文枚举 —— #
            status_cn = result.get('识别状态', '失败')
            status_en = 'success' if status_cn == '成功' else 'failed'

            # 3-1 写明细
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO expense_ocr_detail
                       (session_id,file_name,expense_date,expense_category,
                        expense_content,origin,destination,amount,currency,
                        pay_channel,ocr_status,error_message,raw_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        session_id,
                        renamed_filename,
                        result.get('费用日期'),
                        result.get('费用类别'),
                        result.get('费用内容'),
                        result.get('起点'),
                        result.get('终点'),
                        result.get('支出金额') or None,
                        result.get('货币'),
                        result.get('支付渠道'),
                        status_en,
                        result.get('错误信息'),
                        json.dumps(result, ensure_ascii=False)
                    )
                )

            if result.get("识别状态") == "成功":
                success_cnt += 1
            else:
                failed_cnt  += 1

        # ---------- 4. 更新会话 done ----------
        finish_at   = datetime.now(timezone.utc)
        duration_ms = int((finish_at - start_at).total_seconds() * 1000)

        with conn.cursor() as cur:
            cur.execute(
                """UPDATE expense_ocr_session
                   SET total_files=%s,success_files=%s,failed_files=%s,
                       finished_at=%s,duration_ms=%s,status='done'
                   WHERE id=%s""",
                (len(files), success_cnt, failed_cnt,
                 finish_at, duration_ms, session_id)
            )

        print(f"✅ 完成：成功 {success_cnt}/{len(files)}")

        return jsonify({
            "success": True,
            "sessionId": session_id,          # 方便前端追踪
            "processedCount": success_cnt,
            "totalCount": len(files),
            "results": current_results[:5]    # 预览前 5 条
        })

    except Exception as e:
        # ---------- 5. 标记 error ----------
        if session_id:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE expense_ocr_session SET status='error',"
                    "error_message=%s WHERE id=%s",
                    (str(e), session_id)
                )
        print(f"❌ 处理失败: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            conn.close()
        except pymysql.MySQLError:
            pass
@app.route('/api/download-renamed-files', methods=['GET'])
def api_download_renamed_files():
    """下载重命名后的文件包"""
    global current_temp_dir
    
    try:
        if not current_temp_dir or not current_temp_dir.exists():
            return jsonify({"error": "没有找到文件会话，请先进行图片识别"}), 400
        
        # 检查是否有文件
        image_files = list(current_temp_dir.glob('*'))
        if not image_files:
            return jsonify({"error": "没有找到可下载的文件"}), 400
        
        print(f"📁 准备打包的文件:")
        for file_path in image_files:
            if file_path.is_file():
                print(f"  - {file_path.name}")
        
        # 🔥 修改：使用英文文件名
        today = datetime.today().strftime('%Y%m%d_%H%M%S')
        zip_filename = f"{today}_renamed_files.zip"
        zip_path = OUTPUT_DIR / zip_filename
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in image_files:
                if file_path.is_file() and not file_path.name.startswith('.'):
                    zipf.write(file_path, file_path.name)
                    print(f"📦 添加到ZIP: {file_path.name}")
        
        print(f"✅ ZIP文件创建成功: {zip_path}")
        print(f"📁 包含 {len([f for f in image_files if f.is_file()])} 个文件")
        print(f"🏷️ 文件名将设置为: {zip_filename}")
        
        # 🔥 修改：添加 CORS 响应头
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name=zip_filename,
            mimetype='application/zip'
        )
        
        # 🔥 关键：添加 CORS 头，让前端能读取 Content-Disposition
        response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
        response.headers['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
        
        print(f"📤 设置Content-Disposition: attachment; filename=\"{zip_filename}\"")
        
        return response
        
    except Exception as e:
        print(f"❌ 文件打包失败: {e}")
        return jsonify({"error": f"文件打包失败: {str(e)}"}), 500

@app.route('/api/download-excel', methods=['GET'])
def api_download_excel():
    """下载Excel文件接口"""
    global current_results
    
    try:
        if not current_results:
            return jsonify({"error": "没有可导出的数据，请先进行图片识别"}), 400
        
        # 生成Excel文件到输出目录
        today = datetime.today().strftime('%Y%m%d_%H%M%S')
        excel_filename = f"{today}_expense_report.xlsx"
        excel_path = OUTPUT_DIR / excel_filename
        
        # 创建DataFrame并写入Excel
        df = pd.DataFrame(current_results)
        
        # 确保列顺序正确
        final_columns = []
        for col in column_order:
            if col in df.columns:
                final_columns.append(col)
        
        # 添加其他可能有用的列
        for col in df.columns:
            if col not in final_columns and col not in ['错误信息']:
                final_columns.append(col)
        
        df = df[final_columns]
        df.to_excel(excel_path, index=False)
        
        print(f"✅ Excel文件已生成：{excel_path}")
        print(f"📊 共导出 {len(current_results)} 条记录")
        print(f"🏷️ 文件名将设置为: {excel_filename}")
        
        response = send_file(
            excel_path,
            as_attachment=True,
            download_name=excel_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
        # 🔥 关键：添加 CORS 头，让前端能读取 Content-Disposition
        response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
        response.headers['Content-Disposition'] = f'attachment; filename="{excel_filename}"'
        
        print(f"📤 设置Content-Disposition: attachment; filename=\"{excel_filename}\"")
        
        return response
        
    except Exception as e:
        print(f"❌ Excel导出失败: {e}")
        return jsonify({"error": f"Excel导出失败: {str(e)}"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "strategy": "immediate_cleanup"
    })

@app.route('/api/results', methods=['GET'])
def get_results():
    """获取当前识别结果"""
    global current_results
    return jsonify({
        "results": current_results,
        "count": len(current_results)
    })

if __name__ == '__main__':
    # 检查API密钥
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ 错误：未找到 OPENAI_API_KEY 环境变量")
        print("请创建 .env 文件并设置: OPENAI_API_KEY=你的密钥")
        exit(1)
    
    print("🚀 AI报销识别系统 API 服务启动")
    print(f"📁 输入目录: {INPUT_DIR}")
    print(f"📄 输出目录: {OUTPUT_DIR}")
    print(f"🔄 临时目录: {TEMP_DIR}")
    print("🧹 策略：下次识别时清理上次残留")
    
    # 🧹 启动时清理一次临时目录
    try:
        for temp_folder in TEMP_DIR.iterdir():
            if temp_folder.is_dir():
                shutil.rmtree(temp_folder)
                print(f"🧹 启动清理: {temp_folder}")
    except Exception as e:
        print(f"⚠️ 启动清理失败: {e}")
    
    # 启动Flask服务器
    app.run(debug=True, host='0.0.0.0', port=5000)