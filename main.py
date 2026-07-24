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
    if pd.isna(val) or val is None:
        return 0
    s = str(val).strip().replace("'", "").replace('"', '')
    if not s or s == "-":
        return 0
    if ":" in s:
        try:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0
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
        
        # 점심시간(12:00~13:00) 포함 시 자동 제외
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

    # 3. 시간외근무 데이터 (시작시간~종료시간 기반 자동 계산)
    total_ot_pay_mins = 0
    total_ordinary_mins = 0
    total_ot_allowance = 0

    if not ot_df.empty and "이름" in ot_df.columns:
        # 날짜 정제 및 개인 입사주기(산정주기) 범위 필터링
        clean_ot_dates = ot_df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
        ot_df['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce')
        
        ot_worker_df = ot_df[
            (ot_df["이름"].astype(str).str.strip() == w["name"]) &
            (ot_df["date_dt"] >= p_start_dt) &
            (ot_df["date_dt"] <= p_end_dt)
        ]
        
        for _, row in ot_worker_df.iterrows():
            # 1) 열에 직접 숫자가 적혀있으면 사용
            ot_pay_val = parse_time_to_minutes(row.get("시간외수당적용시간", 0))
            ord_val = parse_time_to_minutes(row.get("통상임금적용시간", 0))
            allowance_val = parse_currency(row.get("지급수당", 0))
            
            # 2) 만약 열이 빈칸이면 '시작시간'과 '종료시간' 차이로 자동 계산
            if ot_pay_val == 0 and ord_val == 0:
                calc_mins = calculate_net_minutes(row.get("시작시간", ""), row.get("종료시간", ""))
                total_ot_pay_mins += calc_mins
            else:
                total_ot_pay_mins += ot_pay_val
                total_ordinary_mins += ord_val
                
            total_ot_allowance += allowance_val

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

# 4. 달력 이벤트 등록 (시간외근무)
if not ot_df.empty and "날짜" in ot_df.columns:
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
