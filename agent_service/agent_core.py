import os
import re
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from openai import OpenAI

app = FastAPI(title="智择通 Agent Core", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 环境变量 ---
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
TOOLS_URL = os.getenv("TOOLS_API_URL", "http://localhost:8000")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# --- 用户数据结构 ---
class UserProfile(BaseModel):
    province: str
    score: int
    subject: str
    target_major: str
    target_university: Optional[str] = ""
    family_budget: str
    personality: str
    career_goal: Optional[str] = "产业就业"

class ConsultRequest(BaseModel):
    user_id: Optional[str] = ""
    profile: UserProfile
    history: Optional[List[dict]] = []

# --- 5个工具定义 ---
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_admission_stats",
            "description": "评估【升学竞争】维度必须调用的工具。查询高校专业的历年录取分数、位次和竞争热度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "province": {"type": "string", "description": "考生所在省份"},
                    "university": {"type": "string", "description": "目标高校"},
                    "major": {"type": "string", "description": "目标专业"},
                    "year": {"type": "integer", "description": "预测年份"}
                },
                "required": ["province", "university", "major", "year"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_industry_trend",
            "description": "评估【行业周期】维度必须调用的工具。获取行业的康波周期阶段和AI替代风险。",
            "parameters": {
                "type": "object",
                "properties": {
                    "industry_name": {"type": "string", "description": "产业名称"}
                },
                "required": ["industry_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_location_value",
            "description": "评估【地域价值】维度时调用的工具。获取目标城市的落户门槛、生活成本及时间价值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_name": {"type": "string", "description": "目标城市名称"}
                },
                "required": ["city_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_fri",
            "description": "评估【家庭资源】时调用的工具。通过经济、社会、认知资本计算FRI指数，判断家庭资源能否承接目标路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "economic_capital": {"type": "integer", "description": "经济资本评分1-10"},
                    "social_capital": {"type": "integer", "description": "社会人脉资本评分1-10"},
                    "cultural_capital": {"type": "integer", "description": "认知文化资本评分1-10"},
                    "target_path": {"type": "string", "description": "目标路径，如'体制内','出国留学','创业'"}
                },
                "required": ["economic_capital", "social_capital", "cultural_capital", "target_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_mentor",
            "description": "提供高端择校规划时调用的核心工具。检索目标院校的导师人脉网络及产学研背景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "university": {"type": "string", "description": "目标高校名称"},
                    "major": {"type": "string", "description": "目标专业名称"},
                    "career_goal": {"type": "string", "description": "职业诉求：'学术科研' 或 '产业就业'"}
                },
                "required": ["university", "major", "career_goal"]
            }
        }
    }
]

# --- 工具路由表 ---
TOOL_PATH_MAP = {
    "get_admission_stats": "/api/tools/admission_stats",
    "get_industry_trend": "/api/tools/industry_trend",
    "evaluate_location_value": "/api/tools/location_value",
    "calculate_fri": "/api/tools/fri",
    "search_mentor": "/api/tools/mentor_search",
}

# --- 系统Prompt ---
SYSTEM_PROMPT = """你现在是"智泽通"核心大脑——一位基于AI Agent与康波周期理论的顶级升学与职业规划专家。

你的核心任务是严格按照"6维决策逻辑"分析，为学生提供极具现实穿透力的结构化择校与择业报告。

## 6维SOP标准操作流

### Step 1: 穿透【性格特质】与【兴趣深度】
- 识别学生的底层决策风格（理性/感性、稳健/激进）
- 评估兴趣强度层级（Level 1说说而已 → Level 5真正的Passion，愿意放弃稳定）

### Step 2: 盘点【家庭资源】(FRI指数)
- 调用calculate_fri工具评估经济/社会/认知资本
- 判断学生的能力是否足以承接家族资源

### Step 3: 判断【行业周期】(康波周期)
- 调用get_industry_trend工具获取行业周期数据
- 强制评估AI替代风险（5-10年内）

### Step 4: 核算【地域价值】
- 调用evaluate_location_value工具获取目标城市数据
- 决定策略：本地化/目标城市/国际跳板

### Step 5: 评估【升学竞争】
- 调用get_admission_stats工具获取历年录取数据
- 结合出生年份竞争密度和户籍省份评估难度

### Step 6: 制定【容错规划】
- 必须提供三级路径：Plan A(最优) + Plan B(次优/平替) + Plan C(保底止损)

## 反思约束（Reflection）
在生成最终报告前，必须内部审查：
1. 家庭资源能否支撑Plan A？不能则必须调整
2. 推荐专业是否有高AI替代风险？有则给出转型建议
3. 竞争极惨烈的省份是否给了Plan B（如中外合作、跨省考研）？
如果reflection_check三个字段不全为true，不允许输出Plan A。

## 输出格式
最终结果必须是纯JSON对象，禁止输出任何多余的Markdown标记：
{
  "step1_personality": {"decision_style": "...", "interest_depth": "Level X", "evidence": "..."},
  "step2_fri": {"fri_index": X.X, "resource_level": "...", "carrying_capacity": "..."},
  "step3_kondratiev": {"industry_phase": "...", "ai_risk": "...", "trend_advice": "..."},
  "step4_location": {"city_tier": "...", "time_value": "...", "strategy": "..."},
  "step5_competition": {"difficulty": "...", "roi": "...", "rank_analysis": "..."},
  "step6_contingency": {"Plan_A": {...}, "Plan_B": {...}, "Plan_C": {...}},
  "reflection_check": {"resource_supportable": true, "ai_risk_addressed": true, "red_sea_bypassed": true},
  "risk_warning": "..."
}"""

# --- 通用工具调用路由 ---
def execute_tool_call(tool_name, arguments):
    path = TOOL_PATH_MAP.get(tool_name)
    if not path:
        return json.dumps({"error": f"未知工具: {tool_name}"})
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        res = requests.post(f"{TOOLS_URL}{path}", json=args, timeout=15)
        return res.text
    except Exception as e:
        return json.dumps({"error": f"工具调用失败: {str(e)}"})

# --- JSON提取 ---
def extract_json(text):
    # 直接解析
    try:
        return json.loads(text)
    except:
        pass
    # 提取 ```json ... ``` 代码块
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except:
            pass
    # 尝试找最外层 { }
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    raise ValueError("无法从模型输出中提取有效JSON")

# --- OpenAI message对象转dict ---
def message_to_dict(msg):
    """将OpenAI返回的message对象转成可序列化的dict"""
    d = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = []
        for tc in msg.tool_calls:
            d["tool_calls"].append({
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}
            })
    return d

# --- 启动验证 ---
@app.on_event("startup")
def startup():
    if not API_KEY:
        print("[⚠️ 警告] DEEPSEEK_API_KEY 未设置，所有AI请求将失败！")
    else:
        print(f"[✅ 启动] Agent Core 就绪，模型: {MODEL}，工具服务: {TOOLS_URL}")

# --- 核心接口 ---
@app.post("/api/v1/consult")
def generate_consultation_report(req: ConsultRequest):
    p = req.profile
    user_query = (
        f"我是{p.province}的{p.subject}考生，考了{p.score}分。"
        f"我想学{p.target_major}。"
        f"{'目标学校：' + p.target_university + '。' if p.target_university else ''}"
        f"家庭预算：{p.family_budget}。我的性格：{p.personality}。"
        f"职业方向：{p.career_goal}。请为我做一份完整的6维规划报告。"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if req.history:
        messages.extend(req.history)
    messages.append({"role": "user", "content": user_query})

    # ReAct循环，最多6轮（5个工具调用 + 1轮最终生成）
    max_iterations = 6
    for i in range(max_iterations):
        print(f"[思考] 第{i+1}轮...")
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.3
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"DeepSeek API调用失败: {str(e)}")

        response_msg = response.choices[0].message
        # 转成dict存入messages，确保序列化安全
        messages.append(message_to_dict(response_msg))

        if response_msg.tool_calls:
            for tool_call in response_msg.tool_calls:
                print(f"[工具调用] {tool_call.function.name}")
                tool_result = execute_tool_call(tool_call.function.name, tool_call.function.arguments)
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_call.function.name,
                    "content": tool_result
                })
        else:
            # 模型给出最终答案
            try:
                final_report = extract_json(response_msg.content)
                return {"status": "success", "data": final_report}
            except ValueError:
                # JSON解析失败，重试最多2次
                print(f"[重试] 第{i+1}轮JSON解析失败，尝试重新请求...")
                retry_max = 2
                for retry in range(retry_max):
                    # 追加提示要求纯JSON输出
                    messages.append({"role": "user", "content": "你的上一次输出不是有效的JSON格式。请严格按照系统提示中的输出格式，只输出纯JSON对象，不要加任何Markdown标记或额外文字。"})
                    try:
                        retry_resp = client.chat.completions.create(
                            model=MODEL,
                            messages=messages,
                            temperature=0.1,
                        )
                        retry_msg = retry_resp.choices[0].message
                        messages.append(message_to_dict(retry_msg))
                        if retry_msg.tool_calls:
                            # 重试时模型又调工具了，继续循环
                            for tc in retry_msg.tool_calls:
                                print(f"[重试工具调用] {tc.function.name}")
                                tr = execute_tool_call(tc.function.name, tc.function.arguments)
                                messages.append({"tool_call_id": tc.id, "role": "tool", "name": tc.function.name, "content": tr})
                            continue  # 继续重试循环
                        final_report = extract_json(retry_msg.content)
                        return {"status": "success", "data": final_report}
                    except ValueError:
                        print(f"[重试] 第{retry+1}次重试仍无法解析JSON")
                        continue
                    except Exception as e:
                        print(f"[重试] 第{retry+1}次重试异常: {str(e)}")
                        continue
                # 所有重试都失败
                return {
                    "status": "error",
                    "message": "模型返回格式异常，无法解析为JSON，请重试",
                    "raw_content": response_msg.content[:500] if response_msg.content else ""
                }

    raise HTTPException(status_code=500, detail="Agent思考超时（6轮未得出结论）")

# --- 聊天模式接口（简单对话，不调工具） ---
class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = []
    role: Optional[str] = "student"

CHAT_SYSTEM_PROMPT = """你是"智择通"升学规划顾问，正在和学生或家长进行一对一的深度对话。

## 核心规则
1. **每次只问1个问题**，最多2个。不要一次抛出多个问题。
2. **一问一答**，像朋友聊天一样自然推进，不要像查户口。
3. **必须按顺序覆盖以下6个维度**，每个维度都要问到位才能进入下一个：

### 维度1：性格特质与兴趣
- 决策风格（理性/感性、稳健/激进）
- 兴趣深度（只是说说还是真正的热爱）

### 维度2：家庭资源
- 家庭经济状况（大致预算范围）
- 家人能否提供社会资源或人脉
- 家长的教育观念和期望

### 维度3：职业方向
- 未来想做哪类工作（学术科研/体制内/大厂/创业/自由职业）
- 对AI替代风险有没有意识

### 维度4：地域偏好
- 想去哪个城市/区域读书
- 是否考虑出国
- 对生活成本的承受力

### 维度5：升学基础
- 省份、高考预估分数、文理科/选科
- 目标专业和学校
- 目前年级

### 维度6：容错底线
- 最差情况能接受什么
- 家庭对风险的承受能力
- 有没有Plan B的心理准备

## 重要约束
- **6个维度没有全部聊完，绝对不要提"生成报告"**
- 只有6个维度都聊到后，才说"我已经充分了解你的情况了，可以为你生成6维评估报告"
- 回复简洁，2-4句话即可，不要长篇大论
- 不要输出JSON，用自然语言回复
- 如果用户回答含糊，温和追问一次，不要跳过"""

@app.post("/api/v1/chat")
def chat_endpoint(req: ChatRequest):
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    # 加入历史对话
    for h in (req.history or []):
        if h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h.get("content", "")})
    messages.append({"role": "user", "content": req.message})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content or "抱歉，我暂时无法回复"
        # 检查是否收集到足够信息
        can_report = _check_can_report(messages, req.message)
        return {"code": 0, "data": {"reply": reply, "canReport": can_report}}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DeepSeek API调用失败: {str(e)}")

def _check_can_report(messages, latest_msg):
    """检查6个维度的信息是否都已覆盖——只看用户消息，不看AI回复"""
    # 只提取用户发送的消息内容
    user_texts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    user_text = " ".join(user_texts)
    
    # 没有用户消息就不行
    if not user_texts:
        return False

    # 维度1：性格特质
    d1 = any(kw in user_text for kw in ["性格", "感性", "理性", "稳健", "冲动", "热爱", "喜欢", "爱好", "擅长", "执着", "坚持", "自律", "随性"])

    # 维度2：家庭资源
    d2 = any(kw in user_text for kw in ["家庭", "预算", "经济", "收入", "家境", "家里", "父母", "万块", "万元", "花钱", "负担", "条件"])

    # 维度3：职业方向
    d3 = any(kw in user_text for kw in ["职业", "就业", "体制", "创业", "大厂", "科研", "方向", "想做", "打算做", "程序员", "工程师", "老师", "医生", "律师"])

    # 维度4：地域偏好
    d4 = any(kw in user_text for kw in ["城市", "广州", "深圳", "地域", "地方", "出国", "留学", "留在", "去北京", "去上海", "回老家"])

    # 维度5：升学基础
    d5_province = any(p in user_text for p in ["内蒙古", "北京", "上海", "广东", "浙江", "江苏", "山东", "河南", "河北", "四川", "湖北", "湖南", "安徽", "福建", "陕西", "重庆", "辽宁", "吉林", "黑龙江", "广西", "云南", "贵州", "甘肃", "新疆", "西藏", "宁夏", "青海", "海南", "天津"])
    d5_score = any(kw in user_text for kw in ["分", "成绩", "高考"])
    d5 = d5_province and d5_score

    # 维度6：容错底线
    d6 = any(kw in user_text for kw in ["保底", "最差", "底线", "退路", "备选", "不行就", "实在不行"])

    result = d1 and d2 and d3 and d4 and d5 and d6
    print(f"[报告就绪检查] 用户消息数:{len(user_texts)} 维度1性格:{d1} 维度2家庭:{d2} 维度3职业:{d3} 维度4地域:{d4} 维度5升学:{d5} 维度6容错:{d6} → 可出报告:{result}")
    return result

# --- Health Check ---
@app.get("/health")
def health():
    api_status = "ok" if API_KEY else "missing_key"
    return {"status": "ok", "version": "1.0", "tools": len(TOOLS), "model": MODEL, "api_key": api_status}
