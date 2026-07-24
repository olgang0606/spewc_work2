import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re

st.set_page_config(page_title="시간외근무 신청 및 현황", page_icon="⏰", layout="wide")

WORKERS = ["박은경", "채미혜", "박인미", "조윤희", "성지영"]

# ---------------------------------------------------------
# 한국 주요 법정/대체 공휴일 판별 함수
# ---------------------------------------------------------
def is_korean_holiday(target_date):
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    m, d = target_date.month, target_date.day
    fixed_holidays = [(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)]
    if (m, d) in fixed_holidays:
        return True
    variable_holidays = {
        2024: [(2, 9), (2, 10), (2, 12), (4, 10), (5, 15), (9, 16), (9, 17), (9, 18)],
        2025: [(1, 28), (1, 29), (1, 30), (3, 3), (5, 5), (5, 6), (10, 5), (10, 6), (10, 7), (10, 8)],
        2026: [(2, 16), (2, 17), (2, 18), (3, 2), (5, 24), (5, 25), (9, 24), (9, 25), (9, 26), (10, 5)]
    }
    return (m, d) in variable_holidays.get(target_date.year, [])

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
        
        # 점심시간(12:00~13:00) 포함 시 차감
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
        return max(0, total_mins)
    except Exception:
        return 0

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

        is_weekend_or_holiday = (work_date.weekday() >= 5) or is_korean_holiday(work_date)

        if is_weekend_or_holiday:
            valid_mins = int((e_dt - s_dt).total_seconds() // 60)
            return min(valid_mins, 480) # 주말/공휴일 최대 8시간
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
            return min(max(0, net_overtime), 240) # 평일 최대 4시간
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

# ---------------------------------------------------------
# 주간(월~일) 휴무시간(연차, 대체휴무, 병가, 공가) 자동 조회
# ---------------------------------------------------------
def get_weekly_leave_minutes(worker_name, work_date):
    """선택한 시간외근무일이 속한 주(월요일~일요일)의 총 휴무 시간 산출"""
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(worker_name)
        records = worksheet.get_all_records()
        if not records:
            return 0
        df = pd.DataFrame(records)
        if "날짜" not in df.columns:
            return 0
            
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce').dt.date
        
        # 월요일(0) ~ 일요일(6) 범위 계산
        start_of_week = work_date - timedelta(days=work_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        week_df = df[(df['date_dt'] >= start_of_week) & (df['date_dt'] <= end_of_week)]
        
        total_leave_mins = 0
        for _, r in week_df.iterrows():
            cat = str(r.get("구분", "")).strip()
            if cat in ["연차", "대체휴무", "병가", "공가"]:
                total_leave_mins += calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", ""))
        return total_leave_mins
    except Exception:
        return 0

@st.cache_data(ttl=3)
def load_overtime_data():
    target_cols = [
        "이름", "날짜", "시작시간", "종료시간", "근무시간", "근무내용",
        "시간외수당수당적용시간", "통상임금적용시간", "대체휴무시간", "지급수당"
    ]
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet("시간외근무")
        records = worksheet.get_all_records()
        
        # 레코드가 없거나 빈 시트인 경우
        if not records:
            return pd.DataFrame(columns=target_cols), worksheet
            
        df = pd.DataFrame(records)
        
        # 필수 컬럼이 누락되어 있다면 빈 문자열로 채워줌
        for col in target_cols:
            if col not in df.columns:
                df[col] = ""
                
        # 컬럼 순서 맞춤
        df = df[target_cols]
        
        # '이름'이나 '날짜'가 모두 비어있는 유령 행 제거
        df = df[df["이름"].astype(str).str.strip() != ""]
        
        return df, worksheet
    except Exception as e:
        # 에러 발생 시 UI에 원인 표시
        st.error(f"구글 시트 '시간외근무' 데이터 읽기 실패: {e}")
        return pd.DataFrame(columns=target_cols), None

st.title("⏰ 시간외근무 신청 및 현황")

# ---------------------------------------------------------
# 3. 근로자별 시간외수당 / 통상임금 단가 설정 (사이드바)
# ---------------------------------------------------------
st.sidebar.header("⚙️ 근로자별 수당 단가 설정")
ot_wages = {}
ord_wages = {}

with st.sidebar.expander("근로자별 통상/시간외 단가 입력", expanded=True):
    for w in WORKERS:
        st.markdown(f"**[{w}]**")
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            ot_wages[w] = st.number_input(f"{w} 시간외단가", value=20000, step=1000, key=f"ot_{w}")
        with col_w2:
            ord_wages[w] = st.number_input(f"{w} 통상단가", value=15000, step=1000, key=f"ord_{w}")

df, worksheet = load_overtime_data()

# ---------------------------------------------------------
# 시간외근무 작성 폼
# ---------------------------------------------------------
st.subheader("📝 시간외근무 작성하기")

with st.form("overtime_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        worker_name = st.selectbox("근로자 선택", WORKERS)
    with col2:
        req_date = st.date_input("근무 날짜", date.today())
    with col3:
        time_options = [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
        start_time = st.selectbox("시작시간", time_options, index=36) # 18:00
    with col4:
        end_time = st.selectbox("종료시간", time_options, index=42) # 21:00

    col5, col6 = st.columns([6, 4])
    with col5:
        work_content = st.text_input("근무내용", placeholder="시간외근무 내용 작성")
    with col6:
        off_time_options = ["00:00"] + [f"{h:02d}:{m:02d}" for h in range(0, 9) for m in (0, 30) if not (h == 0 and m == 0)]
        off_time_str = st.selectbox("대체휴무 사용 시간 (비어있으면 00:00)", off_time_options, index=0)

    submitted = st.form_submit_button("시간외근무 시트 저장")

    if submitted:
        if worksheet is None:
            st.error("구글 시트 '시간외근무' 탭 연결 실패! 구글 시트에 '시간외근무' 탭이 있는지 확인해 주세요.")
        else:
            # 1. 근무시간 계산
            total_work_mins = calculate_overtime_minutes(req_date, start_time, end_time)
            work_time_str = minutes_to_hhmm(total_work_mins)

            # 2. 통상임금적용시간 자동계산 (해당 날짜 주간의 연차, 대체휴무, 병가, 공가 시간 합산)
            weekly_leave_mins = get_weekly_leave_minutes(worker_name, req_date)
            ordinary_pay_mins = min(total_work_mins, weekly_leave_mins)
            ordinary_time_str = minutes_to_hhmm(ordinary_pay_mins)

            # 3. 대체휴무 시간 분(Minutes) 변환 (비어있으면 0시간)
            if not off_time_str:
                off_time_str = "00:00"
            off_h, off_m = map(int, off_time_str.split(":"))
            off_mins = off_h * 60 + off_m

            # 4. 시간외수당 적용시간 자동계산 = 근무시간 - 통상임금적용시간 - 대체휴무시간
            overtime_pay_mins = max(0, total_work_mins - ordinary_pay_mins - off_mins)
            overtime_pay_time_str = minutes_to_hhmm(overtime_pay_mins)

            # 5. 근로자별 단가를 이용한 지급수당 계산
            ot_wage = ot_wages.get(worker_name, 0)
            ord_wage = ord_wages.get(worker_name, 0)
            calculated_pay = int((overtime_pay_mins / 60) * ot_wage) + int((ordinary_pay_mins / 60) * ord_wage)
            pay_str = f"{calculated_pay:,}원"

            # 6. 구글 시트 저장 데이터 구성
            new_row = [
                worker_name,
                req_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                work_time_str,
                work_content if work_content else "-",
                overtime_pay_time_str,  # 시간외수당수당적용시간
                ordinary_time_str,      # 통상임금적용시간
                off_time_str,          # 대체휴무시간
                pay_str                 # 지급수당
            ]

            try:
                worksheet.append_row(new_row)
                st.success(f"저장 완료! (근무시간: {work_time_str}, 시간외수당적용: {overtime_pay_time_str}, 통상임금적용: {ordinary_time_str}, 지급수당: {pay_str})")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"저장 중 오류 발생: {e}")

st.markdown("---")

st.subheader("📋 전체 시간외근무 기록 목록")

if not df.empty:
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 시간외근무 기록이 없습니다.")
