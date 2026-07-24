import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import time
import re

WORKER_NAME = "박인미"
SHEET_NAME = WORKER_NAME
HIRE_DATE = date(2023, 8, 1)

st.set_page_config(page_title=f"{WORKER_NAME} 근태 관리", page_icon="👤", layout="wide")

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
def load_data(sheet_name):
    target_cols = ["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=target_cols)
        df_res = pd.DataFrame(records)
        for c in target_cols:
            if c not in df_res.columns:
                df_res[c] = ""
        return df_res[target_cols].copy()
    except Exception as e:
        return pd.DataFrame(columns=target_cols)

def save_to_sheet(sheet_name, row_data):
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(sheet_name)
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        st.error(f"저장 오류: {e}")
        return False

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

def calculate_net_minutes(start_str, end_str):
    try:
        fmt = "%H:%M"
        t_start = datetime.strptime(start_str, fmt)
        t_end = datetime.strptime(end_str, fmt)
        if t_end <= t_start:
            return 0
        total_mins = int((t_end - t_start).total_seconds() // 60)
        lunch_start = datetime.strptime("12:00", fmt)
        lunch_end = datetime.strptime("13:00", fmt)
        overlap_start = max(t_start, lunch_start)
        overlap_end = min(t_end, lunch_end)
        if overlap_start < overlap_end:
            overlap_mins = int((overlap_end - overlap_start).total_seconds() // 60)
            total_mins -= overlap_mins
        return max(0, total_mins)
    except:
        return 0

# UI 구성
st.title(f"👤 {WORKER_NAME} 근태 관리")

if st.button("🔄 구글 시트 데이터 즉시 동기화"):
    st.cache_data.clear()
    st.rerun()

period_start, period_end = get_current_period(HIRE_DATE)
st.caption(f"📅 **입사일:** {HIRE_DATE.strftime('%Y-%m-%d')} | **현재 산정 주기 (1년):** {period_start.strftime('%Y-%m-%d')} ~ {period_end.strftime('%Y-%m-%d')}")
st.markdown("---")

df = load_data(SHEET_NAME)
categories = ["연차", "대체휴무", "병가", "공가"]

cols = st.columns(4)
if not df.empty and "날짜" in df.columns:
    df['date_dt'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
    period_df = df[(df['date_dt'] >= period_start) & (df['date_dt'] <= period_end)]
else:
    period_df = pd.DataFrame()

for i, cat in enumerate(categories):
    t_mins = 0
    if not period_df.empty and "구분" in period_df.columns and "총시간" in period_df.columns:
        cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
        for val in cat_df["총시간"]:
            t_mins += hhmm_to_minutes(val)
    cols[i].metric(f"총 {cat} 시간", minutes_to_hhmm(t_mins))

st.markdown("---")

st.subheader("📝 근무 / 휴가 신청 작성")

with st.form("entry_form"):
    r1_1, r1_2, r1_3 = st.columns(3)
    with r1_1:
        req_date = st.date_input("날짜", date.today())
    with r1_2:
        start_t = st.time_input("시작시간", datetime.strptime("09:00", "%H:%M").time(), step=1800)
    with r1_3:
        end_t = st.time_input("종료시간", datetime.strptime("18:00", "%H:%M").time(), step=1800)

    r2_1, r2_2, r2_3 = st.columns(3)
    with r2_1:
        category = st.selectbox("구분", categories)
    with r2_2:
        destination = st.text_input("목적지")
    with r2_3:
        reason = st.text_input("사유")

    submit = st.form_submit_button("시트에 저장하기")

if submit:
    s_str = start_t.strftime("%H:%M")
    e_str = end_t.strftime("%H:%M")
    net_mins = calculate_net_minutes(s_str, e_str)
    
    if net_mins <= 0:
        st.error("종료시간은 시작시간보다 나중이어야 하며, 점심시간(12:00~13:00) 외 실근무 시간이 포함되어야 합니다.")
    else:
        total_hhmm = minutes_to_hhmm(net_mins)
        row_data = [
            req_date.strftime("%Y-%m-%d"),
            s_str,
            e_str,
            total_hhmm,
            category,
            destination,
            reason
        ]
        
        with st.spinner("구글 시트에 기록 중입니다..."):
            if save_to_sheet(SHEET_NAME, row_data):
                st.cache_data.clear()
                time.sleep(0.5)
                st.success(f"성공적으로 저장되었습니다! (인정 시간: {total_hhmm})")
                st.rerun()

st.markdown("---")

st.subheader(f"📋 {WORKER_NAME} 신청 전체 기록")
if not df.empty:
    disp_df = df.drop(columns=['date_dt'], errors='ignore')
    st.dataframe(disp_df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 신청 기록이 없습니다.")
