import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None


APP_TITLE = "청구전문컨설팅Medium"
MAKER = "주식회사 메디엄 조정윤"
DB_PATH = Path("medium_claim_review.db")
ADMIN_ID = os.getenv("MEDIUM_ADMIN_ID", "admin")
ADMIN_PASSWORD = os.getenv("MEDIUM_ADMIN_PASSWORD", "medium!2026")
DEFAULT_TIMEOUT = 8


st.set_page_config(
    page_title=APP_TITLE,
    page_icon="M",
    layout="wide",
    initial_sidebar_state="expanded",
)


CUSTOM_CSS = """
<style>
:root {
  --bg: #f6f7f9;
  --ink: #1e242c;
  --muted: #657181;
  --line: #d8dde5;
  --panel: #ffffff;
  --accent: #0f766e;
  --accent2: #b42318;
  --warn: #a15c00;
}
.stApp { background: var(--bg); color: var(--ink); }
[data-testid="stSidebar"] { background: #eef2f5; border-right: 1px solid var(--line); }
h1, h2, h3 { letter-spacing: 0 !important; }
.main-title {
  padding: 18px 0 4px 0;
  border-bottom: 2px solid #26323f;
  margin-bottom: 18px;
}
.maker {
  color: var(--muted);
  font-size: 0.95rem;
  margin-top: -8px;
}
.report-band {
  border-left: 5px solid var(--accent);
  background: var(--panel);
  padding: 16px 18px;
  margin: 10px 0 16px 0;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(20, 30, 40, .05);
}
.danger-band {
  border-left: 5px solid var(--accent2);
  background: #fff;
  padding: 16px 18px;
  margin: 10px 0 16px 0;
  border-radius: 6px;
}
.warn-band {
  border-left: 5px solid var(--warn);
  background: #fff;
  padding: 16px 18px;
  margin: 10px 0 16px 0;
  border-radius: 6px;
}
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr));
  gap: 10px;
}
.metric-box {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 12px 14px;
}
.metric-label { color: var(--muted); font-size: .82rem; }
.metric-value { font-weight: 700; font-size: 1.18rem; margin-top: 4px; }
.small-muted { color: var(--muted); font-size: .88rem; }
.evidence-link a { color: #075985; text-decoration: none; }
.evidence-link a:hover { text-decoration: underline; }
.tag {
  display: inline-block;
  padding: 3px 8px;
  margin: 2px 4px 2px 0;
  border-radius: 999px;
  background: #e7f5f3;
  color: #0f615b;
  font-size: .78rem;
  border: 1px solid #bde2de;
}
.tag-red {
  display: inline-block;
  padding: 3px 8px;
  margin: 2px 4px 2px 0;
  border-radius: 999px;
  background: #fff0ed;
  color: #9f2318;
  font-size: .78rem;
  border: 1px solid #ffc9c2;
}
div[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 6px; }
@media (max-width: 900px) {
  .metric-row { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
}
</style>
"""


SCHEMA = """
CREATE TABLE IF NOT EXISTS prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT NOT NULL,
    procedure_name TEXT,
    order_code TEXT NOT NULL,
    order_name TEXT NOT NULL,
    keywords TEXT,
    category TEXT,
    dose_rule TEXT,
    review_point TEXT,
    special_note_required INTEGER DEFAULT 0,
    special_note_example TEXT,
    caution TEXT,
    hira_keyword TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    department TEXT,
    order_code TEXT,
    order_name TEXT,
    summary TEXT,
    issue TEXT,
    correct_action TEXT,
    evidence TEXT,
    tags TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


SEED_PRESCRIPTIONS = [
    {
        "department": "공통",
        "procedure_name": "외래 처방 검토",
        "order_code": "648602750",
        "order_name": "씨엠쿨산",
        "keywords": "씨엠쿨산,CM쿨산,장정결,대장내시경,648602750,AL300",
        "category": "외래 의약품",
        "dose_rule": "관리자가 실제 심사기준과 병원 약속처방 기준에 맞게 용량/일수 규칙을 등록하세요.",
        "review_point": "처방 목적, 검사 시행 여부, 외래환자의약품관리료 산정 관계를 함께 확인합니다.",
        "special_note_required": 1,
        "special_note_example": "예: 대장내시경 전 처치 목적, 검사일, 관련 상병 또는 시행 사유를 병원 내부 규칙에 맞춰 기재",
        "caution": "검사 목적과 투약일수가 불명확하면 삭감 위험이 있습니다. 실제 고시/심사사례 확인 후 확정하세요.",
        "hira_keyword": "씨엠쿨산 648602750 외래환자의약품관리료",
        "source": "초기 예시 데이터",
    },
    {
        "department": "내과",
        "procedure_name": "소화기 내시경",
        "order_code": "AL300",
        "order_name": "외래환자의약품관리료",
        "keywords": "AL300,외래환자의약품관리료,약품관리료,외래",
        "category": "수가",
        "dose_rule": "약제 처방 및 조제/관리 행위와의 관계를 확인합니다.",
        "review_point": "약제 처방 유무, 원외/원내 처방 구분, 타 행위와 중복 산정 가능성을 검토합니다.",
        "special_note_required": 0,
        "special_note_example": "",
        "caution": "연계 처방과 산정 조건이 맞지 않으면 조정 가능성이 있습니다.",
        "hira_keyword": "AL300 외래환자의약품관리료 심사기준",
        "source": "초기 예시 데이터",
    },
]

SEED_CASES = [
    {
        "title": "대장내시경 전 처치 약제와 외래 산정 동시 검토",
        "department": "내과",
        "order_code": "648602750",
        "order_name": "씨엠쿨산",
        "summary": "검사 전 처치 목적의 약제 처방과 외래 관련 수가를 함께 점검한 사례입니다.",
        "issue": "검사 시행 근거와 약제 처방 목적이 진료기록에서 바로 확인되지 않음",
        "correct_action": "검사일, 처방 목적, 관련 상병 또는 의학적 사유를 특정내역/기록에 명확히 남기도록 안내",
        "evidence": "관리자 확인 필요",
        "tags": "씨엠쿨산,대장내시경,특정내역",
    }
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        count = conn.execute("SELECT COUNT(*) FROM prescriptions").fetchone()[0]
        if count == 0:
            for row in SEED_PRESCRIPTIONS:
                insert_prescription(conn, row, commit=False)
        case_count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        if case_count == 0:
            for row in SEED_CASES:
                insert_case(conn, row, commit=False)
        conn.commit()


def insert_prescription(conn: sqlite3.Connection, row: Dict[str, Any], commit: bool = True) -> None:
    fields = [
        "department",
        "procedure_name",
        "order_code",
        "order_name",
        "keywords",
        "category",
        "dose_rule",
        "review_point",
        "special_note_required",
        "special_note_example",
        "caution",
        "hira_keyword",
        "source",
    ]
    values = [row.get(field, "") for field in fields]
    values[8] = int(bool(values[8]))
    conn.execute(
        f"""
        INSERT INTO prescriptions ({",".join(fields)}, updated_at)
        VALUES ({",".join(["?"] * len(fields))}, ?)
        """,
        [*values, now_text()],
    )
    if commit:
        conn.commit()


def insert_case(conn: sqlite3.Connection, row: Dict[str, Any], commit: bool = True) -> None:
    fields = [
        "title",
        "department",
        "order_code",
        "order_name",
        "summary",
        "issue",
        "correct_action",
        "evidence",
        "tags",
    ]
    conn.execute(
        f"""
        INSERT INTO cases ({",".join(fields)}, updated_at)
        VALUES ({",".join(["?"] * len(fields))}, ?)
        """,
        [*[row.get(field, "") for field in fields], now_text()],
    )
    if commit:
        conn.commit()


def add_audit(action: str, detail: str) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO audit_logs (action, detail, created_at) VALUES (?, ?, ?)",
            (action, detail, now_text()),
        )
        conn.commit()


@st.cache_data(ttl=10)
def load_prescriptions() -> pd.DataFrame:
    with closing(connect()) as conn:
        return pd.read_sql_query(
            "SELECT * FROM prescriptions ORDER BY department, procedure_name, order_name",
            conn,
        )


@st.cache_data(ttl=10)
def load_cases() -> pd.DataFrame:
    with closing(connect()) as conn:
        return pd.read_sql_query("SELECT * FROM cases ORDER BY updated_at DESC", conn)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def split_terms(query: str) -> List[str]:
    normalized = normalize_text(query)
    return [term for term in re.split(r"[\s,;/]+", normalized) if term]


def score_row(row: pd.Series, terms: List[str]) -> int:
    haystacks = {
        "order_code": normalize_text(row.get("order_code")),
        "order_name": normalize_text(row.get("order_name")),
        "keywords": normalize_text(row.get("keywords")),
        "procedure_name": normalize_text(row.get("procedure_name")),
        "department": normalize_text(row.get("department")),
        "review_point": normalize_text(row.get("review_point")),
    }
    score = 0
    for term in terms:
        if term == haystacks["order_code"]:
            score += 80
        if term in haystacks["order_code"]:
            score += 45
        if term in haystacks["order_name"]:
            score += 40
        if term in haystacks["keywords"]:
            score += 35
        if term in haystacks["procedure_name"]:
            score += 20
        if term in haystacks["department"]:
            score += 12
        if term in haystacks["review_point"]:
            score += 8
    return score


def search_prescriptions(df: pd.DataFrame, query: str, department: str, category: str) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df.copy()
    if department != "전체":
        filtered = filtered[filtered["department"].fillna("").eq(department)]
    if category != "전체":
        filtered = filtered[filtered["category"].fillna("").eq(category)]
    terms = split_terms(query)
    if terms:
        filtered["match_score"] = filtered.apply(lambda row: score_row(row, terms), axis=1)
        filtered = filtered[filtered["match_score"] > 0].sort_values(
            ["match_score", "updated_at"], ascending=[False, False]
        )
    else:
        filtered["match_score"] = 0
    return filtered


def search_cases(df: pd.DataFrame, query: str, department: str) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df.copy()
    if department != "전체":
        filtered = filtered[filtered["department"].fillna("").eq(department)]
    terms = split_terms(query)
    if terms:
        text_cols = ["title", "order_code", "order_name", "summary", "issue", "correct_action", "tags"]
        mask = pd.Series(False, index=filtered.index)
        for term in terms:
            term_mask = pd.Series(False, index=filtered.index)
            for col in text_cols:
                term_mask = term_mask | filtered[col].fillna("").str.lower().str.contains(re.escape(term), na=False)
            mask = mask | term_mask
        filtered = filtered[mask]
    return filtered


def build_hira_search_urls(keyword: str) -> List[Tuple[str, str]]:
    quoted = requests.utils.quote(keyword)
    return [
        ("심평원 통합검색에서 직접 확인", f"https://www.hira.or.kr/co/search.do?query={quoted}"),
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_public_hira_snippets(keyword: str) -> List[Dict[str, str]]:
    if not keyword.strip() or BeautifulSoup is None:
        return []
    url = f"https://www.hira.or.kr/co/search.do?query={requests.utils.quote(keyword)}"
    headers = {
        "User-Agent": "Mozilla/5.0 MediumClaimReview/1.0",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    snippets: List[Dict[str, str]] = []
    for item in soup.select("a")[:160]:
        text = " ".join(item.get_text(" ", strip=True).split())
        href = item.get("href", "")
        if len(text) < 8:
            continue
        if text in {"통합검색", "로그인", "회원가입", "전체메뉴", "본문 바로가기"}:
            continue
        if not any(term in text.lower() for term in split_terms(keyword)):
            continue
        if href.startswith("/"):
            href = "https://www.hira.or.kr" + href
        elif href.startswith("javascript"):
            href = url
        snippets.append({"title": text[:120], "url": href or url})
        if len(snippets) >= 5:
            break
    return snippets


def safe_markdown(text: Any) -> str:
    value = str(text or "").strip()
    return value if value else "등록된 내용이 없습니다."


def render_tags(text: str, danger: bool = False) -> None:
    values = [x.strip() for x in str(text or "").split(",") if x.strip()]
    if not values:
        return
    klass = "tag-red" if danger else "tag"
    st.markdown(" ".join([f'<span class="{klass}">{value}</span>' for value in values]), unsafe_allow_html=True)


def risk_level(row: pd.Series) -> Tuple[str, str]:
    caution = normalize_text(row.get("caution"))
    special = bool(row.get("special_note_required"))
    if special and any(word in caution for word in ["삭감", "조정", "위험", "불명확"]):
        return "높음", "특정내역과 진료기록 근거가 함께 필요한 항목입니다."
    if special:
        return "중간", "특정내역 입력 여부를 확인해야 합니다."
    if any(word in caution for word in ["삭감", "조정", "중복"]):
        return "중간", "산정 조건과 중복 여부를 확인하세요."
    return "낮음", "등록된 기준상 즉시 경고 항목은 적습니다."


def local_ai_diagnosis(row: pd.Series, cases_df: pd.DataFrame) -> Dict[str, List[str]]:
    level, reason = risk_level(row)
    actions = [
        "처방 코드와 명칭이 병원 청구 프로그램의 실제 코드와 일치하는지 확인",
        "진료기록에서 처방 목적, 시행 행위, 상병 근거가 한 번에 확인되는지 확인",
    ]
    warnings = []
    note_required = bool(row.get("special_note_required"))
    if note_required:
        actions.append("특정내역 입력란에 목적/시행일/의학적 사유를 병원 표준 문구로 입력")
        warnings.append("특정내역 누락 시 조정 또는 보완 요청 가능성이 있습니다.")
    caution = safe_markdown(row.get("caution"))
    if caution != "등록된 내용이 없습니다.":
        warnings.append(caution)
    related = search_cases(cases_df, f"{row.get('order_code', '')} {row.get('order_name', '')}", "전체")
    case_points = related["issue"].dropna().astype(str).head(3).tolist() if not related.empty else []
    return {
        "risk": [level, reason],
        "actions": actions,
        "warnings": warnings or ["관리자가 등록한 위험 문구는 없습니다. 실제 심사기준 확인 후 확정하세요."],
        "case_points": case_points or ["동일 코드 사례가 아직 충분하지 않습니다. 관리자 사례 등록을 권장합니다."],
    }


def call_openai_diagnosis(row: pd.Series, cases_df: pd.DataFrame) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None
    client = OpenAI(api_key=api_key)
    case_text = cases_df.head(5).to_dict("records")
    prompt = f"""
당신은 한국 요양급여 청구 심사 보조자입니다.
아래 처방 정보와 내부 사례를 근거로, 병원 청구 담당자가 확인해야 할 위험과 보완 문구를 제안하세요.
확정 판단처럼 말하지 말고, 반드시 심평원 고시/심사기준과 병원 내부 기준 확인이 필요하다고 표시하세요.

처방 정보:
{row.to_dict()}

관련 사례:
{case_text}

출력 형식:
1. 핵심 위험
2. 확인할 근거
3. 특정내역/기록 보완 예시
4. 청구 전 체크리스트
"""
    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
            temperature=0.2,
        )
        return response.output_text
    except Exception as exc:
        return f"AI 호출 실패: {exc}"


def call_gemini_diagnosis(row: pd.Series, cases_df: pd.DataFrame) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        import google.generativeai as genai
    except Exception:
        return None
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    prompt = f"""
한국 병원 청구 심사 보조 보고서를 작성하세요.
근거 없는 단정은 금지하고, 확인 필요 항목과 특정내역 문구 예시를 분리하세요.

처방: {row.to_dict()}
내부 사례: {cases_df.head(5).to_dict("records")}
"""
    try:
        response = model.generate_content(prompt)
        return getattr(response, "text", "")
    except Exception as exc:
        return f"Gemini 호출 실패: {exc}"


def import_prescriptions(uploaded_file) -> int:
    if uploaded_file.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    required = {"department", "order_code", "order_name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(sorted(missing))}")
    count = 0
    with closing(connect()) as conn:
        for _, row in df.fillna("").iterrows():
            insert_prescription(conn, row.to_dict(), commit=False)
            count += 1
        conn.commit()
    load_prescriptions.clear()
    add_audit("IMPORT_PRESCRIPTIONS", f"{uploaded_file.name}: {count} rows")
    return count


def import_cases(uploaded_file) -> int:
    if uploaded_file.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    required = {"title", "summary"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(sorted(missing))}")
    count = 0
    with closing(connect()) as conn:
        for _, row in df.fillna("").iterrows():
            insert_case(conn, row.to_dict(), commit=False)
            count += 1
        conn.commit()
    load_cases.clear()
    add_audit("IMPORT_CASES", f"{uploaded_file.name}: {count} rows")
    return count


def export_template(kind: str) -> bytes:
    if kind == "prescriptions":
        columns = [
            "department",
            "procedure_name",
            "order_code",
            "order_name",
            "keywords",
            "category",
            "dose_rule",
            "review_point",
            "special_note_required",
            "special_note_example",
            "caution",
            "hira_keyword",
            "source",
        ]
    else:
        columns = [
            "title",
            "department",
            "order_code",
            "order_name",
            "summary",
            "issue",
            "correct_action",
            "evidence",
            "tags",
        ]
    return pd.DataFrame(columns=columns).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def render_header() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="main-title">
          <h1>{APP_TITLE}</h1>
          <div class="maker">제작자 : {MAKER}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(prescriptions_df: pd.DataFrame) -> Tuple[str, str, str, bool]:
    st.sidebar.subheader("검색 조건")
    query = st.sidebar.text_input(
        "처방명, 코드, 시술명, 키워드",
        value="648602750 씨엠쿨산 AL300",
        placeholder="예: 씨엠쿨산 / 648602750 / AL300",
    )
    departments = ["전체"] + sorted([x for x in prescriptions_df["department"].dropna().unique().tolist() if x])
    categories = ["전체"] + sorted([x for x in prescriptions_df["category"].dropna().unique().tolist() if x])
    department = st.sidebar.selectbox("진료과목", departments)
    category = st.sidebar.selectbox("처방 분류", categories)
    use_external_ai = st.sidebar.toggle("외부 AI 진단 함께 보기", value=False)
    st.sidebar.divider()
    st.sidebar.caption("관리자 기본 계정은 환경변수로 변경하세요.")
    st.sidebar.caption("MEDIUM_ADMIN_ID / MEDIUM_ADMIN_PASSWORD")
    return query, department, category, use_external_ai


def render_metrics(result_df: pd.DataFrame, cases_df: pd.DataFrame) -> None:
    special_count = int(result_df["special_note_required"].fillna(0).astype(int).sum()) if not result_df.empty else 0
    departments = result_df["department"].nunique() if not result_df.empty else 0
    st.markdown(
        f"""
        <div class="metric-row">
          <div class="metric-box"><div class="metric-label">검색 처방</div><div class="metric-value">{len(result_df):,}</div></div>
          <div class="metric-box"><div class="metric-label">특정내역 필요</div><div class="metric-value">{special_count:,}</div></div>
          <div class="metric-box"><div class="metric-label">관련 진료과</div><div class="metric-value">{departments:,}</div></div>
          <div class="metric-box"><div class="metric-label">등록 사례</div><div class="metric-value">{len(cases_df):,}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_order_report(row: pd.Series, cases_df: pd.DataFrame, use_external_ai: bool) -> None:
    level, reason = risk_level(row)
    st.markdown(
        f"""
        <div class="report-band">
          <h3>{row.get("order_name")} <span class="small-muted">({row.get("order_code")})</span></h3>
          <div class="small-muted">{row.get("department")} · {row.get("procedure_name")} · {row.get("category")}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([1.2, 1])
    with col1:
        st.subheader("처방 가이드")
        st.write(safe_markdown(row.get("review_point")))
        st.caption("용량/일수 및 병원 약속처방 기준")
        st.write(safe_markdown(row.get("dose_rule")))
        render_tags(row.get("keywords", ""))

    with col2:
        band_class = "danger-band" if level == "높음" else "warn-band" if level == "중간" else "report-band"
        st.markdown(
            f"""
            <div class="{band_class}">
              <h3>위험도 {level}</h3>
              <p>{reason}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if bool(row.get("special_note_required")):
            st.error("특정내역 입력 필요")
            st.write(safe_markdown(row.get("special_note_example")))
        else:
            st.success("등록 기준상 특정내역 필수 항목 아님")

    st.subheader("심평원 심사기준 확인")
    hira_keyword = row.get("hira_keyword") or f"{row.get('order_code')} {row.get('order_name')}"
    with st.spinner("심평원 공개 검색 결과를 확인하는 중입니다."):
        snippets = fetch_public_hira_snippets(hira_keyword)
    if snippets:
        for item in snippets:
            st.markdown(
                f'<div class="evidence-link">- <a href="{item["url"]}" target="_blank">{item["title"]}</a></div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("자동 조회 결과가 없거나 사이트 접근이 제한되었습니다. 아래 공식 검색 링크로 직접 확인하세요.")
    for label, url in build_hira_search_urls(hira_keyword):
        st.link_button(label, url)

    st.subheader("AI 진단")
    diagnosis = local_ai_diagnosis(row, cases_df)
    st.markdown(f"**핵심 판단:** 위험도 {diagnosis['risk'][0]} - {diagnosis['risk'][1]}")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**청구 전 확인**")
        for item in diagnosis["actions"]:
            st.write(f"- {item}")
    with c2:
        st.markdown("**주의 사항**")
        for item in diagnosis["warnings"]:
            st.write(f"- {item}")
    with c3:
        st.markdown("**사례 포인트**")
        for item in diagnosis["case_points"]:
            st.write(f"- {item}")

    if use_external_ai:
        ai_tabs = st.tabs(["GPT", "Gemini"])
        with ai_tabs[0]:
            text = call_openai_diagnosis(row, cases_df)
            st.write(text or "OPENAI_API_KEY와 openai 패키지가 설정되면 GPT 진단을 표시합니다.")
        with ai_tabs[1]:
            text = call_gemini_diagnosis(row, cases_df)
            st.write(text or "GEMINI_API_KEY와 google-generativeai 패키지가 설정되면 Gemini 진단을 표시합니다.")

    related_cases = search_cases(cases_df, f"{row.get('order_code', '')} {row.get('order_name', '')}", "전체")
    st.subheader("관련 사례")
    if related_cases.empty:
        st.info("등록된 관련 사례가 없습니다.")
    else:
        for _, case in related_cases.head(5).iterrows():
            with st.expander(f"{case.get('title')}"):
                st.write(f"**요약:** {safe_markdown(case.get('summary'))}")
                st.write(f"**쟁점:** {safe_markdown(case.get('issue'))}")
                st.write(f"**권장 조치:** {safe_markdown(case.get('correct_action'))}")
                st.write(f"**근거:** {safe_markdown(case.get('evidence'))}")
                render_tags(case.get("tags", ""), danger=True)


def render_user_screen() -> None:
    prescriptions_df = load_prescriptions()
    cases_df = load_cases()
    query, department, category, use_external_ai = render_sidebar(prescriptions_df)
    result_df = search_prescriptions(prescriptions_df, query, department, category)
    render_metrics(result_df, cases_df)

    st.divider()
    left, right = st.columns([1, 1.45])
    with left:
        st.subheader("처방 리스트")
        if result_df.empty:
            st.warning("검색 결과가 없습니다. 관리자 화면에서 키워드/처방 자료를 추가하세요.")
            selected_id = None
        else:
            display_cols = ["id", "match_score", "department", "procedure_name", "order_code", "order_name", "category"]
            st.dataframe(
                result_df[display_cols],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "id": "ID",
                    "match_score": "일치도",
                    "department": "진료과",
                    "procedure_name": "시술/상황",
                    "order_code": "코드",
                    "order_name": "처방명",
                    "category": "분류",
                },
            )
            selected_id = st.selectbox(
                "보고서로 볼 처방",
                result_df["id"].tolist(),
                format_func=lambda x: f"{result_df.loc[result_df['id'].eq(x), 'order_code'].iloc[0]} · {result_df.loc[result_df['id'].eq(x), 'order_name'].iloc[0]}",
            )
    with right:
        if selected_id:
            row = result_df[result_df["id"].eq(selected_id)].iloc[0]
            render_order_report(row, cases_df, use_external_ai)

    st.divider()
    st.subheader("사례 검색")
    case_query = st.text_input("사례 키워드", value=query, placeholder="코드, 처방명, 쟁점, 태그")
    case_result = search_cases(cases_df, case_query, department)
    if case_result.empty:
        st.info("해당 사례가 없습니다.")
    else:
        st.dataframe(
            case_result[["title", "department", "order_code", "order_name", "summary", "issue", "correct_action"]],
            hide_index=True,
            use_container_width=True,
        )


def render_admin_screen() -> None:
    st.subheader("관리자")
    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False
    if not st.session_state.admin_ok:
        with st.form("admin_login"):
            admin_id = st.text_input("관리자 아이디")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인")
        if submitted:
            if admin_id == ADMIN_ID and password == ADMIN_PASSWORD:
                st.session_state.admin_ok = True
                add_audit("ADMIN_LOGIN", admin_id)
                st.rerun()
            else:
                st.error("관리자 정보가 맞지 않습니다.")
        return

    st.success("관리자 모드입니다.")
    tabs = st.tabs(["처방 자료 등록", "사례 등록", "자료 보기", "사용 기록"])

    with tabs[0]:
        st.markdown("**CSV 또는 Excel 업로드**")
        st.download_button(
            "처방 업로드 양식 다운로드",
            data=export_template("prescriptions"),
            file_name="medium_prescription_template.csv",
            mime="text/csv",
        )
        uploaded = st.file_uploader("처방 자료 파일", type=["csv", "xlsx"], key="prescription_upload")
        if uploaded and st.button("처방 자료 가져오기"):
            try:
                count = import_prescriptions(uploaded)
                st.success(f"{count:,}건을 등록했습니다.")
            except Exception as exc:
                st.error(str(exc))

        st.markdown("**단건 등록**")
        with st.form("single_prescription"):
            c1, c2, c3 = st.columns(3)
            department = c1.text_input("진료과목", value="내과")
            procedure_name = c2.text_input("시술/상황", value="소화기 내시경")
            category = c3.text_input("분류", value="외래 의약품")
            order_code = c1.text_input("처방 코드")
            order_name = c2.text_input("처방명")
            keywords = c3.text_input("검색 키워드")
            dose_rule = st.text_area("용량/일수/산정 규칙")
            review_point = st.text_area("심사 포인트")
            special_note_required = st.checkbox("특정내역 필요")
            special_note_example = st.text_area("특정내역 입력 예시")
            caution = st.text_area("주의 사항")
            hira_keyword = st.text_input("심평원 검색어")
            source = st.text_input("출처/근거")
            submitted = st.form_submit_button("등록")
        if submitted:
            if not order_code or not order_name:
                st.error("처방 코드와 처방명은 필수입니다.")
            else:
                with closing(connect()) as conn:
                    insert_prescription(
                        conn,
                        {
                            "department": department,
                            "procedure_name": procedure_name,
                            "order_code": order_code,
                            "order_name": order_name,
                            "keywords": keywords,
                            "category": category,
                            "dose_rule": dose_rule,
                            "review_point": review_point,
                            "special_note_required": special_note_required,
                            "special_note_example": special_note_example,
                            "caution": caution,
                            "hira_keyword": hira_keyword,
                            "source": source,
                        },
                    )
                load_prescriptions.clear()
                add_audit("CREATE_PRESCRIPTION", f"{order_code} {order_name}")
                st.success("등록했습니다.")

    with tabs[1]:
        st.download_button(
            "사례 업로드 양식 다운로드",
            data=export_template("cases"),
            file_name="medium_case_template.csv",
            mime="text/csv",
        )
        uploaded = st.file_uploader("사례 자료 파일", type=["csv", "xlsx"], key="case_upload")
        if uploaded and st.button("사례 자료 가져오기"):
            try:
                count = import_cases(uploaded)
                st.success(f"{count:,}건을 등록했습니다.")
            except Exception as exc:
                st.error(str(exc))

        with st.form("single_case"):
            title = st.text_input("사례 제목")
            c1, c2, c3 = st.columns(3)
            department = c1.text_input("진료과목", key="case_department")
            order_code = c2.text_input("처방 코드", key="case_order_code")
            order_name = c3.text_input("처방명", key="case_order_name")
            summary = st.text_area("요약")
            issue = st.text_area("쟁점")
            correct_action = st.text_area("권장 조치")
            evidence = st.text_area("근거")
            tags = st.text_input("태그")
            submitted = st.form_submit_button("사례 등록")
        if submitted:
            if not title or not summary:
                st.error("제목과 요약은 필수입니다.")
            else:
                with closing(connect()) as conn:
                    insert_case(
                        conn,
                        {
                            "title": title,
                            "department": department,
                            "order_code": order_code,
                            "order_name": order_name,
                            "summary": summary,
                            "issue": issue,
                            "correct_action": correct_action,
                            "evidence": evidence,
                            "tags": tags,
                        },
                    )
                load_cases.clear()
                add_audit("CREATE_CASE", title)
                st.success("사례를 등록했습니다.")

    with tabs[2]:
        st.markdown("**처방 자료**")
        st.dataframe(load_prescriptions(), hide_index=True, use_container_width=True)
        st.markdown("**사례 자료**")
        st.dataframe(load_cases(), hide_index=True, use_container_width=True)

    with tabs[3]:
        with closing(connect()) as conn:
            logs = pd.read_sql_query("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 200", conn)
        st.dataframe(logs, hide_index=True, use_container_width=True)


def main() -> None:
    init_db()
    render_header()
    mode = st.sidebar.radio("화면", ["청구심사 보고서", "관리자"], horizontal=False)
    if mode == "청구심사 보고서":
        render_user_screen()
    else:
        render_admin_screen()
    st.caption("본 프로그램은 청구 심사 보조 도구입니다. 최종 청구 판단은 최신 고시, 심평원 심사기준, 요양기관 내부 기준 확인 후 진행해야 합니다.")


if __name__ == "__main__":
    main()
