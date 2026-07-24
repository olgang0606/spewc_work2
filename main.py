import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re
from streamlit_calendar import calendar
import holidays

st.set_page_config(page_title="근태 및 시간외근무 관리 시스템", page_icon="🏢", layout="wide")

# 근로자 정보 및 수당 단가
WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE", "wage": 29740}, # 파란색
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169", "wage": 24540}, # 초록색
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8", "wage": 20890}, # 하늘색
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20", "wage": 21270}, # 주황색
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5", "wage": 18960}, # 보라색
]

WORKER_WAGE_MAP = {w["name"]: w["wage"] for w in WORKERS}
WORKER_COLOR_MAP = {w["name"]: w["color"] for w in WORKERS}

# 대한민국 공휴일 정보
kr_holidays = holidays.KR()

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
# 시간 계산 및 유틸리티 함수
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
        
        # 12:00 ~ 13:00 점심시간 차감
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
            
        return max(0, total_mins)
    except Exception:
        return 0

def calculate_overtime_minutes(work_date, start_str, end_str):
    """
    시간외근무 인정 분(Minutes) 계산 규칙
    - 평일: 09:00~18:00 제외 / 최대 4시간(240분)
    - 주말 및 공휴일: 제한 없이 전체 인정 / 최대 8시간(480분)
    """
    s_hhmm = extract_time_str(start_str)
    e_hhmm = extract_time_str(end_str)
    if not s_hhmm or not e_hhmm or not work_date:
        return 0

    try:
        s_dt = datetime.strptime(f"{work_date} {s_hhmm}", "%Y-%m-%d %H:%M")
        e_dt = datetime.strptime(f"{work_date} {e_hhmm}", "%Y-%m-%d %H:%M")
        if e_dt <= s_dt:
            return 0

        is_weekend_or_holiday = (work_date.weekday() >= 5) or (work_date in kr_holidays)

        if is_weekend_or_holiday:
            valid_mins = int((e_dt - s_dt).total_seconds() // 60)
            return min(valid_mins, 480) # 최대 8시간
        else:
            # 평일: 09:00~18:00 규정근무시간 제외
            work_start = datetime.strptime(f"{work_date} 09:00", "%Y-%m-%d %H:%M")
            work_end = datetime.strptime(f"{work_date} 18:00", "%Y-%m-%d %H:%M")

            overlap_start = max(s_dt, work_start)
            overlap_end = min(e_dt, work_end)
            
            overlap_mins = 0
            if overlap_start < overlap_end:
                overlap_mins = int((overlap_end - overlap_start).total_seconds() // 60)

            total_mins = int((e_dt - s_dt).total_seconds() // 60)
            net_overtime = total_mins - overlap_mins
            return min(max(0, net_overtime), 240) # 최대 4시간
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
# 화면 구현
# ---------------------------------------------------------
st.title("🏢 근태 및 시간외근무 종합 대시보드")
st.markdown("전체 근로자의 휴가 및 시간외근무 현황을 한눈에 확인합니다.")

if st.button("🔄 전체 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.markdown("---")

# 시간외근무 데이터 불러오기
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
    # 1. 근로자별 개인 근태 데이터 처리
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

    # 2. 근로자별 시간외근무 데이터 처리
    ot_worker_df = ot_df[(ot_df["이름"].astype(str).str.strip() == w["name"]) & (ot_df["date_dt"] >= p_start) & (ot_df["date_dt"] <= p_end)]
    
    total_ot_pay_mins = 0
    total_ot_allowance = 0
    
    for _, row in ot_worker_df.iterrows():
        pay_mins = hhmm_to_minutes(row["수당적용시간"])
        total_ot_pay_mins += pay_mins
        
        # 지급수당 누적
        try:
            pay_val = int(str(row["지급수당"]).replace(",", "").replace("원", "").strip())
        except Exception:
            pay_val = int((pay_mins / 60) * w["wage"])
        total_ot_allowance += pay_val

    # 3. 요약 정보 구축
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

# 3. 달력에 시간외근무 이벤트 전체 추가
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

st.subheader("📊 근로자별 산정주기 누적 사용 현황 (휴가 및 시간외 수당)")
st.dataframe(pd.DataFrame(summary_list), use_container_width=True, hide_index=True)

st.markdown("---")

st.subheader("📅 월간 통합 일정표 (휴가 & 시간외근무)")
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
