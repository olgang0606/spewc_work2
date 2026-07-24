import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date, timedelta
import time

st.set_page_config(page_title="근무 관리", layout="wide")

# ---------------------------------------------------------
# 
# ---------------------------------------------------------
WORKER_NAME = "박은경"
HIRE_DATE = date(2016, 3, 1)
# ---------------------------------------------------------
# 시간 및 연차 계산 함수
# ---------------------------------------------------------
def calculate_net_minutes(start_str, end_str):
    try:
        fmt = "%H:%M"
        t_start = datetime.strptime(start_str, fmt)
        t_end = datetime.strptime(end_str, fmt)
        
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

def minutes_to_hhmm(mins):
    h = mins // 60
    m = mins % 60
    return f"{h:02d}:{m:02d}"

def hhmm_to_minutes(s):
    try:
        parts = str(s).split(":")
        return int(parts[0]) * 60 + int(parts[1])
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
# 구글 시트 연동 함수 (캐시 타임아웃 2초 설정)
# ---------------------------------------------------------
@st.cache_data(ttl=2)
def load_data():
    try:
        sheet_url = st.secrets["SHEET_URL"]
        res = requests.get(sheet_url)
        data = res.json()
        if not data or len(data) < 2:
            return pd.DataFrame()
        return pd.DataFrame(data[1:], columns=data[0])
    except:
        return pd.DataFrame()

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

df = load_data()

# 근로자 데이터 필터링
if not df.empty and "근로자명" in df.columns:
    w_df = df[df["근로자명"] == WORKER_NAME]
else:
    w_df = pd.DataFrame()

categories = ["연차", "대체휴무", "병가", "공가"]

# 요약 지표 출력
cols = st.columns(4)
for i, cat in enumerate(categories):
    if not w_df.empty and "구분" in w_df.columns and "총시간" in w_df.columns:
        cat_records = w_df[w_df["구분"] == cat]
        t_mins = sum(hhmm_to_minutes(v) for v in cat_records["총시간"])
    else:
        t_mins = 0
    cols[i].metric(f"총 {cat} 시간", minutes_to_hhmm(t_mins))

st.markdown("---")

# 입력 폼 (시간 단위 step=1800 적용 -> 30분 단위)
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
        st.error("종료시간은 시작시간보다 나중이어야 합니다.")
    else:
        total_hhmm = minutes_to_hhmm(net_mins)
        payload = {
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
                st.cache_data.clear()  # 캐시 강제 비우기
                time.sleep(1)          # 구글 시트 반영 대기
                st.success(f"성공적으로 저장되었습니다! (인정 시간: {total_hhmm})")
                st.rerun()
            else:
                st.error("저장에 실패했습니다. SHEET_URL을 확인하세요.")

st.markdown("---")

# 개인 신청 기록
st.subheader("📋 개인 신청 전체 기록")
if not w_df.empty:
    st.dataframe(w_df, use_container_width=True)
else:
    st.info("등록된 기록이 없습니다.")
