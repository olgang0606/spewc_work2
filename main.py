import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re
from streamlit_calendar import calendar

st.set_page_config(page_title="근태 및 시간외근무 관리 시스템", page_icon="🏢", layout="wide")

# 근로자 정보
WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE"},
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169"},
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8"},
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20"},
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5"},
]

WORKER_COLOR_MAP = {w["name"]: w["color"] for w in WORKERS}

# ---------------------------------------------------------
# Google Sheets API 연동
# ---------------------------------------------------------
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    return gspread.authorize(credentials)

@st.cache_data(ttl=1)
def load_sheet_raw_data(sheet_name):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"'{sheet_name}' 시트 로드 실패: {e}")
        return pd.DataFrame()

# ---------------------------------------------------------
# 시간 및 유틸리티 안전 변환 함수
# ---------------------------------------------------------
def extract_time_str(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

def parse_time_to_minutes(val):
    """02:30, 2:30, 2.5, 2 등 모든 포맷을 분(Minutes)으로 정밀 변환"""
    if pd.isna(val) or val is None:
        return 0
    s = str(val).strip().replace("'", "").replace('"', '')
    if not s or s == "-":
        return 0
    
    # "HH:MM" 형식
    if ":" in s:
        try:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0
    # 일반 숫자인 경우
    try:
        val_float = float(s)
        return int(val_float * 60) if val_float < 24 else int(val_float)
    except Exception:
        return 0

def calculate_net_minutes(start_str, end_str):
    s_hhmm = extract_time_str(start_str)
    e_hhmm = extract_time_str(end_str)
    if not s_hhmm or not e_hhmm:
        return 0
    try:
        s_dt = datetime.strptime(s_hhmm, "%H:%M")
        e_dt = datetime.strptime(e_hhmm, "%H:%M")
        if e_dt <= s_dt:
            return 0
        total_mins = int((e_dt - s_dt).total_seconds() // 60)
        
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
        return max(0, total_mins)
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

def parse_currency(val):
    if pd.isna(val) or val is None:
        return 0
    s = str(val).replace(",", "").replace("원", "").strip()
    try:
        return int(float(s))
    except Exception:
        return 0

def get_current_period(hire_d, ref_date=None):
    if ref_date is None:
        ref_date = date.today()
    try:
        this_year_hire = date(ref_date.year, hire_d.month, hire_d.day)
    except ValueError:
        this_year_hire = date(ref_date.year, hire_d.month, 28)
        
    if ref_date >= this_year_hire:
        start_date = this_year_hire
        try:
            end_date = date(ref_date.year + 1, hire_d.month, hire_d.day) - timedelta(days=1)
        except ValueError:
            end_date = date(ref_date.year + 1, hire_d.month, 28) - timedelta(days=1)
    else:
        try:
            start_date = date(ref_date.year - 1, hire_d.month, hire_d.day)
        except ValueError:
            start_date = date(ref_date.year - 1, hire_d.month, 28)
        end_date = this_year_hire - timedelta(days=1)
        
    return start_date, end_date

# ---------------------------------------------------------
# UI 화면 구성
# ---------------------------------------------------------
st.title("🏢 근태 및 시간외근무 종합 대시보드")

if st.button("🔄 전체 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")

# 1. 원본 데이터 로드
ot_df = load_sheet_raw_data("시간외근무")

# 디버깅 영역 (접이식)
with st.expander("🔍 구글시트 읽어온 '시간외근무' 원본 데이터 확인 (디버깅용)", expanded=False):
    if not ot_df.empty:
        st.write("컬럼 목록:", ot_df.columns.tolist())
        st.dataframe(ot_df)
    else:
        st.warning("구글 시트 '시간외근무' 탭 데이터를 읽어오지 못했거나 비어있습니다.")

summary_list = []
calendar_events = []
categories = ["연차", "대체휴무", "병가", "공가"]

for w in WORKERS:
    # 2. 휴가 데이터 (개인별)
    df = load_sheet_raw_data(w["name"])
    p_start, p_end = get_current_period(w["hire_date"])
    p_start_dt = pd.to_datetime(p_start)
    p_end_dt = pd.to_datetime(p_end)
    
    cat_mins = {cat: 0 for cat in categories}
    
    if not df.empty and "날짜" in df.columns:
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce')
        
        period_df = df[(df['date_dt'] >= p_start_dt) & (df['date_dt'] <= p_end_dt)]
        for cat in categories:
            if "구분" in period_df.columns:
                cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
                total_m = sum(calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", "")) for _, r in cat_df.iterrows())
                cat_mins[cat] = total_m

        for idx, row in df.iterrows():
            if pd.isna(row.get('date_dt')):
                continue
            d_str = row['date_dt'].strftime("%Y-%m-%d")
            s_time = extract_time_str(row.get('시작시간', ''))
            e_time = extract_time_str(row.get('종료시간', ''))
            cat = str(row.get('구분', '')).strip()
            
            if ":" in s_time and ":" in e_time:
                calendar_events.append({
                    "title": f"[{w['name']}] {cat} ({s_time}~{e_time})",
                    "start": f"{d_str}T{s_time:0>5}:00",
                    "end": f"{d_str}T{e_time:0>5}:00",
                    "color": w["color"],
                    "textColor": "#FFFFFF"
                })

    # 3. 시간외근무 데이터 무조건 매칭 집계
    total_ot_pay_mins = 0
    total_ordinary_mins = 0
    total_ot_allowance = 0

    if not ot_df.empty:
        # 근로자 이름 필터링 (띄어쓰기 제거 후 비교)
        name_col = [c for c in ot_df.columns if "이름" in c or "근로자" in c]
        
        if name_col:
            target_col = name_col[0]
            ot_worker_df = ot_df[ot_df[target_col].astype(str).str.strip() == w["name"]]
            
            for _, row in ot_worker_df.iterrows():
                # 모든 컬럼 값을 탐색하여 '시간외수당 적용시간', '통상임금 적용시간', '지급수당' 수치 추출
                for col_name, val in row.items():
                    col_clean = str(col_name).replace(" ", "").strip()
                    
                    if "시간외수당" in col_clean or "수당적용" in col_clean:
                        total_ot_pay_mins += parse_time_to_minutes(val)
                    elif "통상임금" in col_clean:
                        total_ordinary_mins += parse_time_to_minutes(val)
                    elif "지급수당" in col_clean or "수당" in col_clean and "적용" not in col_clean:
                        total_ot_allowance += parse_currency(val)

    summary_list.append({
        "근로자명": w["name"],
        "입사일": w["hire_date"].strftime("%Y-%m-%d"),
        "현재 산정주기": f"{p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}",
        "연차 시간": minutes_to_hhmm(cat_mins["연차"]),
        "대체휴무 시간": minutes_to_hhmm(cat_mins["대체휴무"]),
        "병가 시간": minutes_to_hhmm(cat_mins["병가"]),
        "공가 시간": minutes_to_hhmm(cat_mins["공가"]),
        "시간외수당 적용시간": minutes_to_hhmm(total_ot_pay_mins),
        "통상임금 적용시간": minutes_to_hhmm(total_ordinary_mins),
        "시간외 총 지급수당": f"{total_ot_allowance:,}원"
    })

# 달력 이벤트 등록
if not ot_df.empty and "날짜" in ot_df.columns:
    clean_ot_dates = ot_df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
    ot_df['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce')
    
    for _, row in ot_df.iterrows():
        if pd.isna(row.get('date_dt')):
            continue
        w_name = str(row.get("이름", "")).strip()
        d_str = row['date_dt'].strftime("%Y-%m-%d")
        s_time = extract_time_str(row.get('시작시간', ''))
        e_time = extract_time_str(row.get('종료시간', ''))
        w_color = WORKER_COLOR_MAP.get(w_name, "#4A5568")
        
        if ":" in s_time and ":" in e_time:
            calendar_events.append({
                "title": f"[{w_name}] 시간외 ({s_time}~{e_time})",
                "start": f"{d_str}T{s_time:0>5}:00",
                "end": f"{d_str}T{e_time:0>5}:00",
                "color": w_color,
                "textColor": "#FFFFFF"
            })

st.subheader("📊 근로자별 산정주기 누적 사용 현황 (휴가, 통상임금 및 시간외 수당)")
st.dataframe(pd.DataFrame(summary_list), use_container_width=True, hide_index=True)

st.markdown("---")

st.subheader("📅 월간 통합 일정표")
st.markdown("""
<div style="display: flex; gap: 15px; margin-bottom: 15px; font-weight: bold;">
    <span style="color: #3182CE;">■ 박은경</span>
    <span style="color: #38A169;">■ 채미혜</span>
    <span style="color: #00B5D8;">■ 박인미</span>
    <span style="color: #DD6B20;">■ 조윤희</span>
    <span style="color: #805AD5;">■ 성지영</span>
</div>
""", unsafe_allow_html=True)

calendar_options = {
    "editable": False,
    "selectable": True,
    "headerToolbar": {
        "left": "prev,next today",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek"
    },
    "initialView": "dayGridMonth",
    "locale": "ko",
    "eventTimeFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
    "slotLabelFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False}
}

calendar(events=calendar_events, options=calendar_options, key="total_attendance_calendar")
