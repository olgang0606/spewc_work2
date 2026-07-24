import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
import time
import re

st.set_page_config(page_title="박은경 근무 관리", layout="wide")

# ---------------------------------------------------------
# 근로자 정보 및 시트 설정
# ---------------------------------------------------------
WORKER_NAME = "박은경"
SHEET_NAME = "박은경"
HIRE_DATE = date(2016, 3, 1)

# ---------------------------------------------------------
# 시간 정제 및 연산 함수 (정밀 보완)
# ---------------------------------------------------------
def clean_str(val):
    """문자열 공백 및 따옴표 완전 정제"""
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip().replace("'", "").replace('"', '')

def hhmm_to_minutes(s):
    """'8:00', '08:00', '7:30' 등의 시간 표현을 분(Minutes) 단위 정수로 변환"""
    try:
        val_str = clean_str(s)
        if not val_str or ":" not in val_str:
            return 0
        
        # 정규식으로 시, 분 추출
        match = re.search(r'(\d{1,2}):(\d{1,2})', val_str)
        if match:
            h = int(match.group(1))
            m = int(match.group(2))
            return h * 60 + m
        return 0
    except:
        return 0

def minutes_to_hhmm(mins):
    """분(Minutes) 정수를 HH:MM 문자열로 변환"""
    mins = max(0, int(mins))
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def calculate_net_minutes(start_str, end_str):
    try:
        fmt = "%H:%M"
        s_clean = minutes_to_hhmm(hhmm_to_minutes(start_str))
        e_clean = minutes_to_hhmm(hhmm_to_minutes(end_str))
        
        t_start = datetime.strptime(s_clean, fmt)
        t_end = datetime.strptime(e_clean, fmt)
        
        if t_end <= t_start:
            return 0
        
        total_mins = int((t_end - t_start).total_seconds() // 60)
        
        # 12:00~13:00 점심시간 차감
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

def get_annual_leave_hours(hire_d, target_d=None):
    if target_d is None:
        target_d = date.today()
        
    years = target_d.year - hire_d.year
    if (target_d.month, target_d.day) < (hire_d.month, hire_d.day):
        years -= 1
        
    if years < 0:
        return 0
    elif years == 0:
        months = (target_d.year - hire_d.year) * 12 + target_d.month - hire_d.month
        if target_d.day < hire_d.day:
            months -= 1
        return min(max(0, months), 11) * 8
    else:
        add_days = (years - 1) // 2
        return min(15 + add_days, 25) * 8

# ---------------------------------------------------------
# 구글 시트 연동 함수
# ---------------------------------------------------------
@st.cache_data(ttl=1)
def load_data(sheet_name):
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url, params={"sheetName": sheet_name})
        data = res.json()
        if not data or len(data) < 2:
            return pd.DataFrame(columns=["근로자명", "날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"])
        
        headers = [clean_str(h) for h in data[0]]
        df_res = pd.DataFrame(data[1:], columns=headers)
        
        # 컬럼 및 데이터 전체 공백 정제
        for col in df_res.columns:
            df_res[col] = df_res[col].apply(clean_str)
            
        # 유효 데이터 필터링 (근로자명이나 날짜가 존재하는 행)
        if "근로자명" in df_res.columns and "날짜" in df_res.columns:
            df_res = df_res[(df_res["근로자명"] != "") | (df_res["날짜"] != "")].copy()
            
        return df_res
    except:
        return pd.DataFrame(columns=["근로자명", "날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"])

def save_to_sheet(payload):
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url, params=payload)
        return res.status_code == 200
    except:
        return False

# ---------------------------------------------------------
# UI 구성
# ---------------------------------------------------------
st.title(f"👤 {WORKER_NAME} 근태 및 휴가 관리")
st.write(f"**입사일:** {HIRE_DATE.strftime('%Y-%m-%d')}")

annual_hours = get_annual_leave_hours(HIRE_DATE)
st.metric("해당연도 부여 연차시간", f"{annual_hours}시간 (08:00 기준 {annual_hours // 8}일)")

st.markdown("---")

# 시트 데이터 불러오기
df = load_data(SHEET_NAME)

categories = ["연차", "대체휴무", "병가", "공가"]

# 요약 지표 출력 (강화된 연산 로직)
cols = st.columns(4)
for i, cat in enumerate(categories):
    t_mins = 0
    if not df.empty and "구분" in df.columns and "총시간" in df.columns:
        # 구분명 공백 제거 비교
        cat_records = df[df["구분"].str.strip() == cat]
        for val in cat_records["총시간"]:
            t_mins += hhmm_to_minutes(val)
            
    cols[i].metric(f"총 {cat} 시간", minutes_to_hhmm(t_mins))

st.markdown("---")

# 입력 폼
st.subheader("📝 근무 / 휴가 신청 작성")
with st.form("entry_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        req_date = st.date_input("날짜", date.today())
        category = st.selectbox("구분", categories)
    with c2:
        start_t = st.time_input("시작시간", datetime.strptime("09:00", "%H:%M").time(), step=1800)
        end_t = st.time_input("종료시간", datetime.strptime("18:00", "%H:%M").time(), step=1800)
    with c3:
        destination = st.text_input("목적지")
        reason = st.text_input("사유")
        
    submit = st.form_submit_button("시트에 저장하기")

if submit:
    s_str = start_t.strftime("%H:%M")
    e_str = end_t.strftime("%H:%M")
    net_mins = calculate_net_minutes(s_str, e_str)
    
    if net_mins <= 0:
        st.error("종료시간은 시작시간보다 나중이어야 하며, 점심시간(12:00~13:00) 외 근무시간이 포함되어야 합니다.")
    else:
        total_hhmm = minutes_to_hhmm(net_mins)
        payload = {
            "sheetName": SHEET_NAME,
            "근로자명": WORKER_NAME,
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
                st.error("저장에 실패했습니다. SHEET_URL 배포 상태를 확인하세요.")

st.markdown("---")

# 개인 신청 기록
st.subheader("📋 개인 신청 전체 기록")
if not df.empty:
    st.dataframe(df, use_container_width=True)
else:
    st.info("등록된 기록이 없습니다.")
