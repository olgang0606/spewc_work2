import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import re

st.set_page_config(page_title="근태 관리 시스템", page_icon="🏢", layout="wide")

WORKERS = [
    {"name": "박은경", "hire_date": date(2017, 3, 1), "page": "pages/1_박은경.py"},
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "page": "pages/2_채미혜.py"},
    {"name": "박인미", "hire_date": date(2019, 3, 1), "page": "pages/3_박인미.py"},
    {"name": "조윤희", "hire_date": date(2020, 3, 1), "page": "pages/4_조윤희.py"},
    {"name": "성지영", "hire_date": date(2021, 3, 1), "page": "pages/5_성지영.py"},
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
    except Exception as e:
        return pd.DataFrame(columns=target_cols)

def extract_time_str(val):
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else s

def hhmm_to_minutes(s):
    try:
        val_str = extract_time_str(s)
        if not val_str or ":" not in val_str:
            return 0
        parts = val_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

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
st.markdown("전체 근로자의 근태 현황을 한눈에 확인하고 각 근로자 페이지로 이동할 수 있습니다.")

col_btn, _ = st.columns([2, 8])
with col_btn:
    if st.button("🔄 전체 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()

st.markdown("---")

summary_list = []
categories = ["연차", "대체휴무", "병가", "공가"]

for w in WORKERS:
    df = load_worker_data(w["name"])
    p_start, p_end = get_current_period(w["hire_date"])
    
    cat_mins = {cat: 0 for cat in categories}
    
    if not df.empty and "날짜" in df.columns:
        df['date_dt'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
        period_df = df[(df['date_dt'] >= p_start) & (df['date_dt'] <= p_end)]
        
        for cat in categories:
            cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
            total_m = sum(hhmm_to_minutes(val) for val in cat_df["총시간"])
            cat_mins[cat] = total_m

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

summary_df = pd.DataFrame(summary_list)
st.subheader("📊 근로자별 산정주기 누적 사용 현황")
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.subheader("👉 근로자 선택 (바로가기)")
cols = st.columns(5)
for idx, w in enumerate(WORKERS):
    with cols[idx]:
        st.markdown(f"### {w['name']}")
        st.page_link(w["page"], label=f"{w['name']} 근태 관리", icon="👤")
