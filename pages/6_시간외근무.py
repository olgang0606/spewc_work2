import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re

st.set_page_config(page_title="시간외근무 신청 및 현황", page_icon="⏰", layout="wide")

WORKERS = ["박은경", "채미혜", "박인미", "조윤희", "성지영"]

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

def get_spreadsheet():
    gc = get_gspread_client()
    return gc.open_by_url(st.secrets["SPREADSHEET_URL"])

# ---------------------------------------------------------
# 시간 및 수당 계산 유틸리티 (HH:MM:SS 초 단위 지원)
# ---------------------------------------------------------
def extract_time_str(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().replace("'", "").replace('"', '')
    # HH:MM 또는 HH:MM:SS 모두 감지
    match = re.search(r'(\d{1,2}:\d{2})(?::\d{2})?', s)
    return match.group(1) if match else ""

def parse_time_to_minutes(val):
    if pd.isna(val) or val is None:
        return 0
    s = str(val).strip().replace("'", "").replace('"', '')
    if not s or s == "-":
        return 0
    if ":" in s:
        try:
            parts = s.split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0
    try:
        val_float = float(s)
        return int(val_float * 60) if val_float < 24 else int(val_float)
    except Exception:
        return 0

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
        
        # 휴게시간(12:00~13:00) 차감
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
        return max(0, total_mins)
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

# ---------------------------------------------------------
# 개별 근로자 탭 주간 총시간 자동 계산
# ---------------------------------------------------------
def get_weekly_worker_total_minutes(worker_name, work_date):
    try:
        sh = get_spreadsheet()
        worksheet = sh.worksheet(worker_name)
        records = worksheet.get_all_records()
        if not records:
            return 0
        df = pd.DataFrame(records)
        if "날짜" not in df.columns:
            return 0
            
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce').dt.date
        
        start_of_week = work_date - timedelta(days=work_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        week_df = df[(df['date_dt'] >= start_of_week) & (df['date_dt'] <= end_of_week)]
        
        total_mins = 0
        for _, r in week_df.iterrows():
            total_mins += calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", ""))
        return total_mins
    except Exception:
        return 0

# ---------------------------------------------------------
# 사이드바: 단가 설정
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

# ---------------------------------------------------------
# 시간외근무 데이터 로드 및 불러온 즉시 계산 보완
# ---------------------------------------------------------
@st.cache_data(ttl=1)
def load_and_recalculate_overtime_data():
    target_cols = [
        "이름", "날짜", "시작시간", "종료시간", "근무시간", "근무내용",
        "시간외수당적용시간", "통상임금적용시간", "대체휴무시간", "지급수당"
    ]
    try:
        sh = get_spreadsheet()
        worksheet = sh.worksheet("시간외근무")
        records = worksheet.get_all_records()
        
        if not records:
            return pd.DataFrame(columns=target_cols), worksheet
            
        df = pd.DataFrame(records)
        
        # 컬럼 존재 확인
        for col in target_cols:
            if col not in df.columns:
                df[col] = ""
                
        df = df[df["이름"].astype(str).str.strip() != ""].copy()
        
        # 데이터가 있지만 수당/시간 계산이 비어있는 경우 즉시 실시간 연산
        for idx, r in df.iterrows():
            w_name = str(r["이름"]).strip()
            d_str = str(r["날짜"]).replace(". ", "-").replace(".", "-").strip()
            
            try:
                w_date = pd.to_datetime(d_str).date()
            except Exception:
                w_date = date.today()

            # 1. 근무시간
            tot_mins = calculate_net_minutes(r["시작시간"], r["종료시간"])
            df.at[idx, "근무시간"] = minutes_to_hhmm(tot_mins)
            
            # 2. 통상임금적용시간
            ord_mins = get_weekly_worker_total_minutes(w_name, w_date)
            df.at[idx, "통상임금적용시간"] = minutes_to_hhmm(ord_mins)
            
            # 3. 시간외수당적용시간
            ot_pay_mins = max(0, tot_mins - ord_mins)
            df.at[idx, "시간외수당적용시간"] = minutes_to_hhmm(ot_pay_mins)
            
            # 4. 대체휴무시간 파싱
            alt_vac_mins = parse_time_to_minutes(r.get("대체휴무시간", 0))
            if not str(r.get("대체휴무시간", "")).strip():
                df.at[idx, "대체휴무시간"] = "00:00"
                
            # 5. 지급수당 연산 (월 단위 절사)
            ot_w = ot_wages.get(w_name, 20000)
            ord_w = ord_wages.get(w_name, 15000)
            
            ot_h = ot_pay_mins // 60
            ord_h = ord_mins // 60
            
            if alt_vac_mins == ord_mins and ord_mins > 0:
                pay = ot_h * ot_w
            else:
                pay = (ot_h * ot_w) + (ord_h * ord_w)
                
            df.at[idx, "지급수당"] = f"{pay:,}원"

        return df[target_cols], worksheet
    except Exception as e:
        st.error(f"데이터 연동 실패: {e}")
        return pd.DataFrame(columns=target_cols), None

st.title("⏰ 시간외근무 신청 및 현황")

df, worksheet = load_and_recalculate_overtime_data()

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
        start_time = st.selectbox("시작시간", time_options, index=36)
    with col4:
        end_time = st.selectbox("종료시간", time_options, index=42)

    col5, col6 = st.columns([6, 4])
    with col5:
        work_content = st.text_input("근무내용", placeholder="시간외근무 내용 작성")
    with col6:
        off_time_options = ["00:00"] + [f"{h:02d}:{m:02d}" for h in range(0, 9) for m in (0, 30) if not (h == 0 and m == 0)]
        off_time_str = st.selectbox("대체휴무 사용 시간", off_time_options, index=0)

    submitted = st.form_submit_button("시간외근무 시트 저장")

    if submitted:
        if worksheet is None:
            st.error("구글 시트 연결 실패!")
        else:
            total_mins = calculate_net_minutes(start_time, end_time)
            work_time_str = minutes_to_hhmm(total_mins)

            ord_mins = get_weekly_worker_total_minutes(worker_name, req_date)
            ordinary_time_str = minutes_to_hhmm(ord_mins)

            ot_pay_mins = max(0, total_mins - ord_mins)
            overtime_pay_time_str = minutes_to_hhmm(ot_pay_mins)

            alt_vac_mins = parse_time_to_minutes(off_time_str)

            ot_wage = ot_wages.get(worker_name, 20000)
            ord_wage = ord_wages.get(worker_name, 15000)
            
            ot_hours = ot_pay_mins // 60
            ord_hours = ord_mins // 60
            
            if alt_vac_mins == ord_mins and ord_mins > 0:
                calculated_pay = ot_hours * ot_wage
            else:
                calculated_pay = (ot_hours * ot_wage) + (ord_hours * ord_wage)
                
            pay_str = f"{calculated_pay:,}원"

            new_row = [
                worker_name,
                req_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                work_time_str,
                work_content if work_content else "-",
                overtime_pay_time_str,
                ordinary_time_str,
                off_time_str,
                pay_str
            ]

            try:
                worksheet.append_row(new_row)
                st.success(f"저장 완료!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"저장 실패: {e}")

st.markdown("---")

st.subheader("📋 전체 시간외근무 기록 목록")

if not df.empty:
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 시간외근무 기록이 없습니다.")
