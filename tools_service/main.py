import os
import re
import json
import random
import sqlite3
import hashlib
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI(title="智择通 Agent 外部工具箱", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SQLite 本地数据库 ---
DB_PATH = os.getenv("DB_PATH", "/data/zhizetong_local_data.db")
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "/data/zzt_vector_db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS admission_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        province TEXT, university TEXT, major TEXT,
        year INTEGER, min_score INTEGER, min_rank INTEGER
    )''')
    # 注入初始mock数据（仅首次）
    count = conn.execute("SELECT COUNT(*) FROM admission_scores").fetchone()[0]
    if count == 0:
        mock_data = [
            ("内蒙古", "北京邮电大学", "计算机科学与技术", 2023, 620, 1500),
            ("内蒙古", "北京邮电大学", "计算机科学与技术", 2024, 635, 1200),
            ("山东", "电子科技大学", "通信工程", 2024, 650, 3000),
        ]
        conn.executemany(
            "INSERT INTO admission_scores (province, university, major, year, min_score, min_rank) VALUES (?,?,?,?,?,?)",
            mock_data
        )
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()
    print(f"[启动] 工具箱就绪，数据库: {DB_PATH}")

# --- 通用防反爬请求框架 ---
def fetch_html_content(url: str) -> str:
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15"
        ]),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.baidu.com"
    }
    for attempt in range(3):
        try:
            with httpx.Client(timeout=10.0) as http_client:
                response = http_client.get(url, headers=headers)
                response.raise_for_status()
                return response.text
        except Exception as e:
            if attempt == 2:
                print(f"[爬虫报错] 抓取 {url} 失败: {str(e)}")
                return None
            time.sleep(1)

# ==========================================
# 工具一：【升学竞争】高校历年分数查询
# ==========================================
class AdmissionQuery(BaseModel):
    province: str
    university: str
    major: str
    year: int

@app.post("/api/tools/admission_stats")
def get_admission_stats(query: AdmissionQuery):
    # 优先查SQLite
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM admission_scores WHERE province=? AND university=? AND major=? ORDER BY year DESC",
        (query.province, query.university, query.major)
    ).fetchall()
    conn.close()

    if rows:
        return {"status": "success", "data": [dict(r) for r in rows]}

    # 降级：本地动态算法（同参数同结果，seed固定）
    seed = int(hashlib.md5(f"{query.university}{query.major}{query.province}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    base_score = 500
    if any(kw in query.university for kw in ["北京大学", "清华"]):
        base_score = 680
    elif any(kw in query.university for kw in ["邮电", "电子科技"]):
        base_score = 630
    elif "职业" in query.university:
        base_score = 350

    if any(kw in query.major for kw in ["计算机", "人工智能"]):
        base_score += 15
    elif any(kw in query.major for kw in ["土木", "生化环材"]):
        base_score -= 10

    history_data = []
    for y in range(query.year - 3, query.year):
        fluctuation = rng.randint(-5, 5)
        history_data.append({
            "year": y,
            "min_score": base_score + fluctuation,
            "min_rank": int((750 - (base_score + fluctuation)) * 15.5)
        })

    return {
        "status": "success",
        "data": {
            "university": query.university,
            "major": query.major,
            "province": query.province,
            "admission_history": history_data,
            "competition_trend": "分数线呈逐年微涨趋势，建议结合位次而非绝对分填报。" if "计算机" in query.major else "热度有所下降，可作为低分高就的抄底选择。"
        }
    }

# ==========================================
# 工具二：【行业周期】康波与AI替代风险评估
# ==========================================
class IndustryQuery(BaseModel):
    industry_name: str

def _query_rag(industry: str):
    """尝试RAG检索，不可用则返回None"""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        chroma_client = chromadb.PersistentClient(path=VECTOR_DB_PATH)
        ef = embedding_functions.DefaultEmbeddingFunction()
        collection = chroma_client.get_collection(name="industry_reports", embedding_function=ef)
        results = collection.query(query_texts=[f"{industry} 行业康波周期趋势AI替代"], n_results=1)
        if results['documents'] and len(results['documents'][0]) > 0:
            return results['documents'][0][0], results['metadatas'][0][0].get('source', '未知')
    except Exception as e:
        print(f"[RAG] ChromaDB不可用: {e}")
    return None, None

@app.post("/api/tools/industry_trend")
def get_industry_trend(query: IndustryQuery):
    industry = query.industry_name

    # 尝试RAG检索
    rag_context, rag_source = _query_rag(industry)
    if rag_context:
        return {
            "status": "success",
            "data": {
                "industry": industry,
                "source": f"本地向量知识库 ({rag_source})",
                "expert_insight": rag_context,
                "system_instruction": "请将上述expert_insight作为核心依据撰写行业分析"
            }
        }

    # 降级：本地规则库
    if any(kw in industry for kw in ["AI", "人工智能", "大数据", "新能源", "芯片"]):
        cycle, ai_risk, advice = "繁荣期（上升通道）", "极低（AI创造者序列）", "国家战略红利期，但需注重底层能力避免沦为调参工。"
    elif any(kw in industry for kw in ["土木", "建筑", "房地产"]):
        cycle, ai_risk, advice = "萧条期（下行通道）", "低（实体但行业萎缩）", "存量博弈，增量极少。除非FRI极高有工程人脉，否则坚决劝退。"
    elif any(kw in industry for kw in ["金融", "投资"]):
        cycle, ai_risk, advice = "成熟期（分化加剧）", "两极：前端销售/基础核算→极高；量化/风控→极低", "必须走复合路线（金融+数学/编程），纯金融本科已无竞争力。"
    elif any(kw in industry for kw in ["会计", "翻译", "法学"]):
        cycle, ai_risk, advice = "成熟期（存量博弈）", "极高（标准化脑力劳动易被大模型替代）", "两极分化严重，只有高端证书或复合背景才有出路。"
    else:
        cycle, ai_risk, advice = "平稳期", "中等", "传统万金油专业，就业面广但天花板明显，建议作为Plan B。"

    return {
        "status": "success",
        "data": {
            "industry": industry,
            "kondratiev_cycle": cycle,
            "ai_replacement_risk": ai_risk,
            "core_insight": advice
        }
    }

# ==========================================
# 工具三：【地域价值】政策与红利探测
# ==========================================
class LocationQuery(BaseModel):
    city_name: str

@app.post("/api/tools/location_value")
def evaluate_location_value(query: LocationQuery):
    city = query.city_name

    if city in ["北京", "上海", "广州", "深圳"]:
        tier, cost, policy, tv = "一线城市", "极高", "落户门槛极高，非985硕士极难留存。", "高投入高回报，适合资源充足或极度抗压的学生。"
    elif city in ["杭州", "成都", "武汉", "南京", "苏州", "西安", "重庆", "长沙"]:
        tier, cost, policy, tv = "新一线城市", "中等偏高", "抢人阶段，本科可落户，购房有补贴。", "性价比最高，建议作为Plan A核心主攻地域。"
    elif city in ["包头", "呼和浩特", "洛阳", "芜湖", "赣州"]:
        tier, cost, policy, tv = "三线城市", "低", "零门槛落户，地方政府发补贴。", "产业单一，除非体制内或家族生意，不建议回流。"
    else:
        tier, cost, policy, tv = "二线城市", "中等", "本科可落户，有一定人才补贴。", "性价比尚可，适合本地家庭资源复用。"

    return {
        "status": "success",
        "data": {
            "target_city": city,
            "city_tier": tier,
            "living_cost_index": cost,
            "settlement_policy": policy,
            "strategic_advice": tv
        }
    }

# ==========================================
# 工具四：【家庭资源指数】FRI评估
# ==========================================
class FRIQuery(BaseModel):
    economic_capital: int
    social_capital: int
    cultural_capital: int
    target_path: str

@app.post("/api/tools/fri")
def calculate_fri(query: FRIQuery):
    total_score = (query.economic_capital * 0.4) + (query.social_capital * 0.4) + (query.cultural_capital * 0.2)
    match_warning = ""
    strategy = ""

    if "出国" in query.target_path and query.economic_capital < 6:
        match_warning = "高风险：经济资本不足以支撑该路径，存在资金断裂风险。"
        strategy = "建议降级为中外合作办学，或转向高额奖学金的欧洲/亚洲公立项目。"
    elif any(kw in query.target_path for kw in ["考公", "体制"]):
        if query.social_capital >= 7:
            match_warning = "完美匹配：社会资本极高，具备极强的体制内资源转化潜力。"
            strategy = "建议选择本地强势高校，全力复用家族人脉网络。"
        else:
            match_warning = "资源错配：缺乏体制内人脉，将面临极高的隐性竞争成本。"
            strategy = "建议转向技术壁垒高、市场化程度深的技术型岗位。"
    elif total_score >= 8:
        match_warning = "资源溢出：家庭属于高净值/高阶层群体。"
        strategy = "无视短期就业波动，重点布局具有长远康波红利、高护城河的顶级赛道。"
    else:
        match_warning = "普通家庭模型：需依靠极强的个人素质打破壁垒。"
        strategy = "必须选择【上升期】且【实用性强】的工科/技术专业，以硬核技能为杠杆。"

    return {
        "status": "success",
        "data": {
            "fri_total_score": round(total_score, 1),
            "resource_level": "高净值家庭" if total_score >= 8 else "中产家庭" if total_score >= 5 else "普通工薪家庭",
            "match_warning": match_warning,
            "actionable_strategy": strategy
        }
    }

# ==========================================
# 工具五：【导师资源】深度检索匹配
# ==========================================
class MentorQuery(BaseModel):
    university: str
    major: str
    career_goal: str

@app.post("/api/tools/mentor_search")
def search_mentor(query: MentorQuery):
    mentors = []

    if query.career_goal == "学术科研":
        mentors.append({
            "name": "张教授（学术大牛）",
            "title": "国家杰青 / 重点实验室主任",
            "research_focus": "底层算法优化，发顶会概率极高",
            "alumni_network": "大量弟子在海外名校任教",
            "recommendation_index": "适合极其自律、走科研路线的学生。平时放养，需要主观能动性极强。"
        })
    else:
        mentors.append({
            "name": "王教授（产业大拿）",
            "title": "横向课题之王 / 某AI独角兽技术顾问",
            "research_focus": "产学研结合，接大量真实商业项目",
            "alumni_network": "大量弟子在大厂核心业务线，内推资源极其丰富",
            "recommendation_index": "适合以就业、赚钱为核心目标。跟着他能直接积累商业项目经验，毕业即入行。"
        })

    return {
        "status": "success",
        "data": {
            "university": query.university,
            "major": query.major,
            "matched_mentors": mentors,
            "insight": "择校不如择师！选对导师直接跨越社会阶层。"
        }
    }

# --- Health Check ---
@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0", "tools": 5}
