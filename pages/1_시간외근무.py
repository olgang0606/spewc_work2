import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import re
import holidays

st.set_page_config(page_title="시간외근무 신청 및 현황", page_icon="⏰", layout="wide")

WORKERS = [
    {"name": "박은경", "wage": 29740},
    {"name": "채미혜", "wage": 24540},
    {"name": "박인미", "wage": 20890},
    {"name": "조윤희", "wage": 21270},
    {"name": "성지영", "wage": 18960},
]

WORKER_WAGE_MAP = {w["name"]: w["wage"] for w in WORKERS}
kr_holidays = holidays.KR()

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

def extract_time_str(val):
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

def calculate_overtime_minutes(work_date, start_str, end_str):
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

@st.cache_data(ttl=3)
def load_overtime_data():
    target_cols = ["이름", "날짜", "시작시간", "종료시간", "근무시간", "근무내용", "수당적용시간", "대체휴무시간", "지급수당"]
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet("시간외근무")
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=target_cols), worksheet
        df = pd.DataFrame(records)
        for col in target_cols:
            if col not in df.columns:
                df[col] = ""
        return df[target_cols], worksheet
    except Exception:
        return pd.DataFrame(columns=target_cols), None

st.title("⏰ 시간외근무 신청 및 등록")
st.markdown("5명의 근로자가 공통으로 작성하는 시간외근무 신청 페이지입니다.")

df, worksheet = load_overtime_data()

# ---------------------------------------------------------
# 시간외근무 작성 폼
# ---------------------------------------------------------
st.subheader("📝 시간외근무 작성하기")

with st.form("overtime_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        worker_name = st.selectbox("근로자 선택", [w["name"] for w in WORKERS])
    with col2:
        req_date = st.date_input("근무 날짜", date.today())
    with col3:
        time_options = [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
        start_time = st.selectbox("시작시간", time_options, index=36) # 18:00 기본값
    with col4:
        end_time = st.selectbox("종료시간", time_options, index=42) # 21:00 기본값

    col5, col6 = st.columns([6, 4])
    with col5:
        work_content = st.text_input("근무내용", placeholder="시간외근무 내용 작성")
    with col6:
        off_time_options = [f"{h:02d}:{m:02d}" for h in range(0, 9) for m in (0, 30)]
        off_time_str = st.selectbox("대체휴무 사용 시간", off_time_options, index=0)

    submitted = st.form_submit_button("시간외근무 시트 저장")

    if submitted:
        if worksheet is None:
            st.error("구글 시트 '시간외근무' 탭 연결 실패! 구글 시트에 '시간외근무' 탭이 있는지 확인해 주세요.")
        else:
            # 1. 근무시간 계산 (규정 제한 적용)
            valid_work_mins = calculate_overtime_minutes(req_date, start_time, end_time)
            work_time_str = minutes_to_hhmm(valid_work_mins)

            # 2. 대체휴무 분(Minutes) 차감
            off_h, off_m = map(int, off_time_str.split(":"))
            off_mins = off_h * 60 + off_m
            
            pay_mins = max(0, valid_work_mins - off_mins)
            pay_time_str = minutes_to_hhmm(pay_mins)

            # 3. 수당 산출
            hourly_wage = WORKER_WAGE_MAP.get(worker_name, 0)
            calculated_pay = int((pay_mins / 60) * hourly_wage)
            pay_str = f"{calculated_pay:,}원"

            new_row = [
                worker_name,
                req_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                work_time_str,
                work_content if work_content else "-",
                pay_time_str,
                off_time_str,
                pay_str
            ]

            try:
                worksheet.append_row(new_row)
                st.success(f"시간외근무 저장 완료! (인정 근무시간: {work_time_str}, 수당적용시간: {pay_time_str}, 지급수당: {pay_str})")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"저장 중 오류 발생: {e}")

st.markdown("---")

# ---------------------------------------------------------
# 전체 시간외근무 목록
# ---------------------------------------------------------
st.subheader("📋 전체 시간외근무 기록 목록")

if not df.empty:
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 시간외근무 기록이 없습니다.")
