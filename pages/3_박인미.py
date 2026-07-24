import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date

st.set_page_config(page_title="박인미 근무 관리", layout="wide")

WORKER_NAME = "박인미"
HIRE_DATE = date(2023, 8, 1)

def calculate_net_minutes(start_str, end_str):
    fmt = "%H:%M"
    t_start, t_end = datetime.strptime(start_str, fmt), datetime.strptime(end_str, fmt)
    if t_end <= t_start: return 0
    total_mins = int((t_end - t_start).total_seconds() // 60)
    lunch_start, lunch_end = datetime.strptime("12:00", fmt), datetime.strptime("13:00", fmt)
    overlap_start, overlap_end = max(t_start, lunch_start), min(t_end, lunch_end)
    if overlap_start < overlap_end:
        total_mins -= int((overlap_end - overlap_start).total_seconds() // 60)
    return max(0, total_mins)

def minutes_to_hhmm(mins): return f"{mins // 60:02d}:{mins % 60:02d}"
def hhmm_to_minutes(s):
    try:
        p = str(s).split(":")
        return int(p[0]) * 60 + int(p[1])
    except: return 0

def get_annual_leave_hours(hire_d, target_d=None):
    if target_d is None: target_d = date.today()
    years = target_d.year - hire_d.year - ((target_d.month, target_d.day) < (hire_d.month, hire_d.day))
    if years < 0: return 0
    elif years == 0:
        months = (target_d.year - hire_d.year) * 12 + target_d.month - hire_d.month - (target_d.day < hire_d.day)
        return min(max(0, months), 11) * 8
    else: return min(15 + (years - 1) // 2, 25) * 8

def load_data():
    try:
        res = requests.get(st.secrets["SHEET_URL"])
        d = res.json()
        return pd.DataFrame(d[1:], columns=d[0]) if d and len(d) >= 2 else pd.DataFrame()
    except: return pd.DataFrame()

def save_to_sheet(payload):
    try: return requests.get(st.secrets["SHEET_URL"], params=payload).status_code == 200
    except: return False

st.title(f"👤 {WORKER_NAME} 근태 및 휴가 관리")
st.write(f"**입사일:** {HIRE_DATE.strftime('%Y-%m-%d')}")
annual_hours = get_annual_leave_hours(HIRE_DATE)
st.metric("해당연도 부여 연차시간", f"{annual_hours}시간 (08:00 기준 {annual_hours // 8}일)")
st.markdown("---")

df = load_data()
w_df = df[df["근로자명"] == WORKER_NAME] if not df.empty and "근로자명" in df.columns else pd.DataFrame()
categories = ["연차", "대체휴무", "병가", "공가"]

cols = st.columns(4)
for i, cat in enumerate(categories):
    t_mins = sum(hhmm_to_minutes(v) for v in w_df[w_df["구분"] == cat]["총시간"]) if not w_df.empty else 0
    cols[i].metric(f"총 {cat} 시간", minutes_to_hhmm(t_mins))

st.markdown("---")
st.subheader("📝 근무 / 휴가 신청 작성")
with st.form("entry_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        req_date = st.date_input("날짜", date.today())
        category = st.selectbox("구분", categories)
    with c2:
        start_t = st.time_input("시작시간", datetime.strptime("09:00", "%H:%M").time())
        end_t = st.time_input("종료시간", datetime.strptime("18:00", "%H:%M").time())
    with c3:
        destination, reason = st.text_input("목적지"), st.text_input("사유")
    submit = st.form_submit_button("시트에 저장하기")

if submit:
    s_str, e_str = start_t.strftime("%H:%M"), end_t.strftime("%H:%M")
    net_mins = calculate_net_minutes(s_str, e_str)
    if net_mins <= 0:
        st.error("종료시간은 시작시간보다 나중이어야 합니다.")
    else:
        total_hhmm = minutes_to_hhmm(net_mins)
        payload = {"근로자명": WORKER_NAME, "날짜": req_date.strftime("%Y-%m-%d"), "시작시간": s_str, "종료시간": e_str, "총시간": total_hhmm, "구분": category, "목적지": destination, "사유": reason}
        if save_to_sheet(payload):
            st.success("성공적으로 저장되었습니다!")
            st.rerun()
        else: st.error("저장에 실패했습니다.")

st.markdown("---")
st.subheader("📋 개인 신청 전체 기록")
st.dataframe(w_df, use_container_width=True) if not w_df.empty else st.info("등록된 기록이 없습니다.")
