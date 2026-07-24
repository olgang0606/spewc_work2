import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import re
from streamlit_calendar import calendar

st.set_page_config(page_title="근태 관리 시스템", page_icon="🏢", layout="wide")

# 근로자 설정 및 지정 색상
WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE"}, # 파란색
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169"}, # 초록색
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8"}, # 하늘색
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20"}, # 주황색
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5"}, # 보라색
]

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

@st.cache_data(ttl=5)
def load_worker_data(sheet_name):
    target_cols = ["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]
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
# 시간 및 날짜 처리 함수 (24시간제 적용)
# ---------------------------------------------------------
def extract_time_str(val):
    """HH:MM:SS 또는 HH:MM 형태에서 24시간제 HH:MM만 추출"""
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

def calculate_net_minutes(start_str, end_str):
    """
    시작시간~종료시간 실근무/휴가 분(Minutes) 계산
    12:00~13:00(점심시간)이 포함되어 있으면 60분 차감
    """
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
        
        # 12:00 ~ 13:00 점심시간 포함 여부 체크
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
            
        return max(0, total_mins)
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    """분을 24시간제 HH:MM 형식으로 변환"""
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

def get_current_period(hire_d, ref_date=None):
    """입사일 기준 현재 산정주기 계산"""
    if ref_date is None:
        ref_date = date.today()
    try:
        this_year_hire = date(ref_date.year, hire_d.month, hire_d.day)
    except ValueError:
        this_year_hire = date(ref_date.year, hire_d.month, 28)
        
    if ref_date >= this_year_hire:
        start_date = this_year_hire
        try:
            end_date = date(ref_date.year + 1, hire_d.month, hire_d.day) - pd.Timedelta(days=1)
        except ValueError:
            end_date = date(ref_date.year + 1, hire_d.month, 28) - pd.Timedelta(days=1)
    else:
        try:
            start_date = date(ref_date.year - 1, hire_d.month, hire_d.day)
        except ValueError:
            start_date = date(ref_date.year - 1, hire_d.month, 28)
        end_date = this_year_hire - pd.Timedelta(days=1)
        
    if isinstance(end_date, pd.Timestamp):
        end_date = end_date.date()
    return start_date, end_date

# ---------------------------------------------------------
# UI 화면
# ---------------------------------------------------------
st.title("🏢 근태 관리 종합 대시보드")
st.markdown("전체 근로자의 근태 현황을 확인하고, 월간 달력 일정표에서 근로자별 근태를 조회할 수 있습니다.")

col_btn, _ = st.columns([2, 8])
with col_btn:
    if st.button("🔄 전체 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

summary_list = []
calendar_events = []
categories = ["연차", "대체휴무", "병가", "공가"]

for w in WORKERS:
    df = load_worker_data(w["name"])
    p_start, p_end = get_current_period(w["hire_date"])
    
    cat_mins = {cat: 0 for cat in categories}
    
    if not df.empty and "날짜" in df.columns:
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce').dt.date
        
        # 1. 산정주기별 누적 시간 계산
        period_df = df[(df['date_dt'] >= p_start) & (df['date_dt'] <= p_end)]
        for cat in categories:
            cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
            total_m = sum(calculate_net_minutes(r["시작시간"], r["종료시간"]) for _, r in cat_df.iterrows())
            cat_mins[cat] = total_m

        # 2. 달력 일정 이벤트 데이터 생성 (24시간제 표시)
        for idx, row in df.iterrows():
            if pd.isna(row['date_dt']):
                continue
            
            d_str = row['date_dt'].strftime("%Y-%m-%d")
            s_time = extract_time_str(row['시작시간'])
            e_time = extract_time_str(row['종료시간'])
            cat = str(row['구분']).strip()
            
            if ":" in s_time and ":" in e_time:
                start_iso = f"{d_str}T{s_time:0>5}:00"
                end_iso = f"{d_str}T{e_time:0>5}:00"
                title_str = f"[{w['name']}] {cat} ({s_time}~{e_time})"
            else:
                start_iso = d_str
                end_iso = d_str
                title_str = f"[{w['name']}] {cat}"

            calendar_events.append({
                "title": title_str,
                "start": start_iso,
                "end": end_iso,
                "color": w["color"],
                "textColor": "#FFFFFF"
            })

    row = {
        "근로자명": w["name"],
        "입사일": w["hire_date"].strftime("%Y-%m-%d"),
        "현재 산정주기": f"{p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}",
        "연차 시간": minutes_to_hhmm(cat_mins["연차"]),
        "대체휴무 시간": minutes_to_hhmm(cat_mins["대체휴무"]),
        "병가 시간": minutes_to_hhmm(cat_mins["병가"]),
        "공가 시간": minutes_to_hhmm(cat_mins["공가"]),
    }
    summary_list.append(row)

# 누적 현황 요약 테이블
summary_df = pd.DataFrame(summary_list)
st.subheader("📊 근로자별 산정주기 누적 사용 현황")
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ---------------------------------------------------------
# 📅 월간 달력 일정표 (24시간제 표기 적용)
# ---------------------------------------------------------
st.subheader("📅 월간 근태 일정표")

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
    # ✨ 24시간제 표기 옵션 추가
    "eventTimeFormat": {
        "hour": "2-digit",
        "minute": "2-digit",
        "hour12": False
    },
    "slotLabelFormat": {
        "hour": "2-digit",
        "minute": "2-digit",
        "hour12": False
    }
}

calendar(events=calendar_events, options=calendar_options, key="attendance_calendar")
