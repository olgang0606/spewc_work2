import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re
from streamlit_calendar import calendar

st.set_page_config(page_title="근태 및 시간외근무 관리 시스템", page_icon="🏢", layout="wide")

WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE", "wage": 29740},
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169", "wage": 24540},
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8", "wage": 20890},
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20", "wage": 21270},
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5", "wage": 18960},
]

WORKER_WAGE_MAP = {w["name"]: w["wage"] for w in WORKERS}
WORKER_COLOR_MAP = {w["name"]: w["color"] for w in WORKERS}

# ---------------------------------------------------------
# 한국 주요 법정/대체 공휴일 판별 함수 (패키지 미사용)
# ---------------------------------------------------------
def is_korean_holiday(target_date):
    """주요 고정 공휴일 및 명절/대체공휴일 판별"""
    if isinstance(target_date, datetime):
        target_date = target_date.date()
        
    m, d = target_date.month, target_date.day
    
    # 1. 고정 양력 공휴일
    fixed_holidays = [
        (1, 1),   # 신정
        (3, 1),   # 삼일절
        (5, 5),   # 어린이날
        (6, 6),   # 현충일
        (8, 15),  # 광복절
        (10, 3),  # 개천절
        (10, 9),  # 한글날
        (12, 25)  # 성탄절
    ]
    if (m, d) in fixed_holidays:
        return True
        
    # 2. 연도별 주요 음력 명절/석가탄신일/대체공휴일 지정 (필요시 연도 추가 가능)
    variable_holidays = {
        2024: [(2, 9), (2, 10), (2, 12), (4, 10), (5, 15), (9, 16), (9, 17), (9, 18)],
        2025: [(1, 28), (1, 29), (1, 30), (3, 3), (5, 5), (5, 6), (10, 5), (10, 6), (10, 7), (10, 8)],
        2026: [(2, 16), (2, 17), (2, 18), (3, 2), (5, 24), (5, 25), (9, 24), (9, 25), (9, 26), (10, 5)]
    }
    
    year_holidays = variable_holidays.get(target_date.year, [])
    return (m, d) in year_holidays

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

@st.cache_data(ttl=3)
def load_sheet_data(sheet_name, target_cols):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=target_cols)
        df = pd.DataFrame(records)
        for col in target_cols:
            if col not in df.columns:
                df[col] = ""
        return df[target_cols]
    except Exception:
        return pd.DataFrame(columns=target_cols)

# ---------------------------------------------------------
# 시간 및 유틸리티 함수
# ---------------------------------------------------------
def extract_time_str(val):
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

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

def hhmm_to_minutes(hhmm_str):
    s = extract_time_str(hhmm_str)
    if not s:
        return 0
    try:
        h, m = map(int, s.split(":"))
        return h * 60 + m
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
        
    if isinstance(end_date, pd.Timestamp):
        end_date = end_date.date()
    return start_date, end_date

# ---------------------------------------------------------
# UI 화면
# ---------------------------------------------------------
st.title("🏢 근태 및 시간외근무 종합 대시보드")

if st.button("🔄 전체 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")

ot_cols = ["이름", "날짜", "시작시간", "종료시간", "근무시간", "근무내용", "수당적용시간", "대체휴무시간", "지급수당"]
ot_df = load_sheet_data("시간외근무", ot_cols)

if not ot_df.empty and "날짜" in ot_df.columns:
    clean_ot_dates = ot_df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
    ot_df['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce').dt.date
else:
    ot_df['date_dt'] = pd.NaT

summary_list = []
calendar_events = []
categories = ["연차", "대체휴무", "병가", "공가"]
leave_cols = ["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]

for w in WORKERS:
    df = load_sheet_data(w["name"], leave_cols)
    p_start, p_end = get_current_period(w["hire_date"])
    cat_mins = {cat: 0 for cat in categories}
    
    if not df.empty and "날짜" in df.columns:
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce').dt.date
        
        period_df = df[(df['date_dt'] >= p_start) & (df['date_dt'] <= p_end)]
        for cat in categories:
            cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
            total_m = sum(calculate_net_minutes(r["시작시간"], r["종료시간"]) for _, r in cat_df.iterrows())
            cat_mins[cat] = total_m

        for idx, row in df.iterrows():
            if pd.isna(row['date_dt']):
                continue
            d_str = row['date_dt'].strftime("%Y-%m-%d")
            s_time = extract_time_str(row['시작시간'])
            e_time = extract_time_str(row['종료시간'])
            cat = str(row['구분']).strip()
            
            if ":" in s_time and ":" in e_time:
                calendar_events.append({
                    "title": f"[{w['name']}] {cat} ({s_time}~{e_time})",
                    "start": f"{d_str}T{s_time:0>5}:00",
                    "end": f"{d_str}T{e_time:0>5}:00",
                    "color": w["color"],
                    "textColor": "#FFFFFF"
                })

    ot_worker_df = ot_df[(ot_df["이름"].astype(str).str.strip() == w["name"]) & (ot_df["date_dt"] >= p_start) & (ot_df["date_dt"] <= p_end)]
    
    total_ot_pay_mins = 0
    total_ot_allowance = 0
    
    for _, row in ot_worker_df.iterrows():
        pay_mins = hhmm_to_minutes(row["수당적용시간"])
        total_ot_pay_mins += pay_mins
        
        try:
            pay_val = int(str(row["지급수당"]).replace(",", "").replace("원", "").strip())
        except Exception:
            pay_val = int((pay_mins / 60) * w["wage"])
        total_ot_allowance += pay_val

    summary_list.append({
        "근로자명": w["name"],
        "입사일": w["hire_date"].strftime("%Y-%m-%d"),
        "현재 산정주기": f"{p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}",
        "연차 시간": minutes_to_hhmm(cat_mins["연차"]),
        "대체휴무 시간": minutes_to_hhmm(cat_mins["대체휴무"]),
        "병가 시간": minutes_to_hhmm(cat_mins["병가"]),
        "공가 시간": minutes_to_hhmm(cat_mins["공가"]),
        "시간외 수당적용시간": minutes_to_hhmm(total_ot_pay_mins),
        "시간외 총 지급수당": f"{total_ot_allowance:,}원"
    })

if not ot_df.empty:
    for _, row in ot_df.iterrows():
        if pd.isna(row['date_dt']):
            continue
        w_name = str(row["이름"]).strip()
        d_str = row['date_dt'].strftime("%Y-%m-%d")
        s_time = extract_time_str(row['시작시간'])
        e_time = extract_time_str(row['종료시간'])
        w_color = WORKER_COLOR_MAP.get(w_name, "#4A5568")
        
        if ":" in s_time and ":" in e_time:
            calendar_events.append({
                "title": f"[{w_name}] 시간외 ({s_time}~{e_time})",
                "start": f"{d_str}T{s_time:0>5}:00",
                "end": f"{d_str}T{e_time:0>5}:00",
                "color": w_color,
                "textColor": "#FFFFFF"
            })

st.subheader("📊 근로자별 산정주기 누적 사용 현황")
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
