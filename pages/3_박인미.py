import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
import time
import re

# =========================================================
# 👤 근로자 및 입사일 설정
# =========================================================
WORKER_NAME = "박인미"
SHEET_NAME = WORKER_NAME
HIRE_DATE = date(2023, 8, 1)

st.set_page_config(page_title=f"{WORKER_NAME} 근태 관리", page_icon="👤", layout="wide")

# ---------------------------------------------------------
# 입사일 기준 현재 산정 주기(1년) 계산
# ---------------------------------------------------------
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
# 시간 정제 및 계산 헬퍼 함수
# ---------------------------------------------------------
def clean_str(val):
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip().replace("'", "").replace('"', '')

def extract_time_str(val):
    s = clean_str(val)
    match = re.search(r'(\d{1,2}:\d{2})', s)
    if match:
        return match.group(1)
    return s

def extract_date_str(val):
    s = clean_str(val)
    match = re.search(r'(\d{4}-\d{2}-\d{2})', s)
    if match:
        return match.group(1)
    return s

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

# ---------------------------------------------------------
# 구글 시트 연동 함수
# ---------------------------------------------------------
@st.cache_data(ttl=1)
def load_data(sheet_name):
    target_cols = ["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url, params={"sheetName": sheet_name})
        data = res.json()
        if not data or len(data) < 2:
            return pd.DataFrame(columns=target_cols)
        
        df_res = pd.DataFrame(data[1:], columns=data[0])
        
        for col in df_res.columns:
            df_res[col] = df_res[col].apply(clean_str)
            
        for c in target_cols:
            if c not in df_res.columns:
                df_res[c] = ""
                
        df_res = df_res[target_cols].copy()
        
        df_res["날짜"] = df_res["날짜"].apply(extract_date_str)
        df_res["시작시간"] = df_res["시작시간"].apply(extract_time_str)
        df_res["종료시간"] = df_res["종료시간"].apply(extract_time_str)
        df_res["총시간"] = df_res["총시간"].apply(extract_time_str)
        
        df_res = df_res[df_res["날짜"] != ""].copy()
        return df_res
    except:
        return pd.DataFrame(columns=target_cols)

def save_to_sheet(payload):
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url, params=payload)
        return res.status_code == 200
    except:
        return False

# ---------------------------------------------------------
# UI 화면 구성
# ---------------------------------------------------------
st.title(f"👤 {WORKER_NAME} 근태 관리")

period_start, period_end = get_current_period(HIRE_DATE)
st.caption(f"📅 **입사일:** {HIRE_DATE.strftime('%Y-%m-%d')} | **현재 산정 주기 (1년):** {period_start.strftime('%Y-%m-%d')} ~ {period_end.strftime('%Y-%m-%d')}")
st.markdown("---")

df = load_data(SHEET_NAME)
categories = ["연차", "대체휴무", "병가", "공가"]

# 1. 상단 누적 요약 지표
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

# 2. 근무 / 휴가 신청 작성 폼
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
        payload = {
            "sheetName": SHEET_NAME,
            "날짜": req_date.strftime("%Y-%m-%d"),
            "시작시간": s_str,
            "종료시간": e_str,
            "총시간": total_hhmm,
            "구분": category,
            "목적지": destination,
            "사유": reason
        }
        
        with st.spinner("구글 시트에 기록 중입니다..."):
            if save_to_sheet(payload):
                st.cache_data.clear()
                time.sleep(1)
                st.success(f"성공적으로 저장되었습니다! (인정 시간: {total_hhmm})")
                st.rerun()
            else:
                st.error("저장에 실패했습니다.")

st.markdown("---")

# 3. 개인별 신청 전체 기록
st.subheader(f"📋 {WORKER_NAME} 신청 전체 기록")
if not df.empty:
    disp_df = df.drop(columns=['date_dt'], errors='ignore')
    st.dataframe(disp_df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 신청 기록이 없습니다.")
