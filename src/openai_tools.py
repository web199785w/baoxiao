# from settings import PRINTING_KEY
import os
from openai import OpenAI
import logging

# 创建应用日志记录器
logger = logging.getLogger('imageleuth')

class OpenAITools:
    def __init__(self):
        # 从环境变量获取API密钥
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("请设置环境变量 OPENAI_API_KEY")
        
        self.client = OpenAI(api_key=api_key)

    def send_message(self, url):
        
        text = (
            "你是一个财务截图智能识别助手，请分析我提供的付款截图，提取以下字段（如无内容请返回空字符串）：\n"
            "\n"
            "1. 金额：必须包含金额数值及货币符号，例如：¥117.17 或 $15.00\n"
            "2. 币种：请明确返回币种名称，例如：人民币、美元、日元、越南盾等。即使图片中只有货币符号（¥、$），也要根据内容判断币种，不得遗漏！\n"
            "3. 付款时间：如 2025-05-05 14:19:21\n"
            "4. 付款账户：如 中国银行信用卡(0297)、支付宝账号、零钱通、微信等\n"
            "5. 费用用途：如 iproyal、滴滴、美团外卖等\n"
            "6. 起点：出行类截图中的出发地\n"
            "7. 终点：出行类截图中的目的地\n"
            "8. 费用类别：四选一（办公用品、差旅费、软件费、资产），请根据截图内容合理判断最合适分类\n"
            "\n"
            "【输出格式】\n"
            "{\n"
            "  \"code\": 200,\n"
            "  \"data\": {\n"
            "    \"文件名\": \"xxx.jpg\",\n"
            "    \"金额\": \"$15.00\",\n"
            "    \"币种\": \"美元\",\n"
            "    \"付款时间\": \"2025-05-05 14:19:21\",\n"
            "    \"付款账户\": \"招商银行信用卡(8888)\",\n"
            "    \"费用用途\": \"iproyal\",\n"
            "    \"起点\": \"杭州萧山机场T3\",\n"
            "    \"终点\": \"绍兴万达中心\",\n"
            "    \"费用类别\": \"软件费\"\n"
            "  }\n"
            "}\n"
            "\n"
            "若识别失败请返回：{\"code\": 400, \"data\": {}}\n"
            "请严格只返回 JSON，不要添加解释或 Markdown。"
        )


        
        # 支持图片URL的消息内容
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                # 如果需要添加图片URL
                {"type": "image_url", "image_url": {"url": url}}
            ]
        }]
        
        response = self.client.chat.completions.with_raw_response.create(
            messages=messages,
            # model="gpt-3.5-turbo",
            # model="gpt-4o-mini",
            # model="gpt-4o",
            model="gpt-4.1",
            # model="o4-mini",
            # model="o3",
            max_tokens=500
        )

        # get the object that `chat.completions.create()` would have returned
        completion = response.parse()
        logger.info(f"OpenAI返回结果: {completion}")
        return completion.choices[0].message.content
    

    def send_message_with_base64(self, image_base64):
        
        text = (
            "你是一个财务截图智能识别助手，请分析我提供的付款截图，提取以下字段（如无内容请返回空字符串）：\n"
            "\n"
            "1. 金额：必须包含金额数值及货币符号，例如：¥117.17 或 $15.00\n"
            "2. 币种：请明确返回币种名称，例如：人民币、美元、日元、越南盾等。即使图片中只有货币符号（¥、$），也要根据内容判断币种，不得遗漏！\n"
            "3. 付款时间：如 2025-05-05 14:19:21\n"
            "4. 付款账户：如 中国银行信用卡(0297)、支付宝账号、零钱通、微信等\n"
            "5. 费用用途：如 iproyal、滴滴、美团外卖等\n"
            "6. 起点：出行类截图中的出发地\n"
            "7. 终点：出行类截图中的目的地\n"
            "8. 费用类别：四选一（办公用品、差旅费、软件费、资产），请根据截图内容合理判断最合适分类\n"
            "\n"
            "【输出格式】\n"
            "{\n"
            "  \"code\": 200,\n"
            "  \"data\": {\n"
            "    \"文件名\": \"xxx.jpg\",\n"
            "    \"金额\": \"$15.00\",\n"
            "    \"币种\": \"美元\",\n"
            "    \"付款时间\": \"2025-05-05 14:19:21\",\n"
            "    \"付款账户\": \"招商银行信用卡(8888)\",\n"
            "    \"费用用途\": \"iproyal\",\n"
            "    \"起点\": \"杭州萧山机场T3\",\n"
            "    \"终点\": \"绍兴万达中心\",\n"
            "    \"费用类别\": \"软件费\"\n"
            "  }\n"
            "}\n"
            "\n"
            "若识别失败请返回：{\"code\": 400, \"data\": {}}\n"
            "请严格只返回 JSON，不要添加解释或 Markdown。"
        )
        
        # 支持base64图片的消息内容
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url", 
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        }]
        
        response = self.client.chat.completions.with_raw_response.create(
            messages=messages,
            # model="gpt-3.5-turbo",
            # model="gpt-4o-mini",
            # model="gpt-4o",
            model="gpt-4.1",
            max_tokens=500
        )

        # get the object that `chat.completions.create()` would have returned
        completion = response.parse()
        logger.info(f"OpenAI返回结果: {completion}")
        return completion.choices[0].message.content

