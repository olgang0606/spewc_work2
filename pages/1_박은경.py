import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import re

WORKER_NAME = "박은경"
HIRE_DATE = date(2016, 3, 1)

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

@st.cache_data(ttl=3)
def load_data():
    target_cols = ["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]
    try:
        gc = get_gspread_client()
        sh = gc.open_by_url(st.secrets["SPREADSHEET_URL"])
        worksheet = sh.worksheet(WORKER_NAME)
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

df, worksheet = load_data()

# 화면 출력 전 총시간 자동 보완
if not df.empty:
    for idx, row in df.iterrows():
        m = calculate_net_minutes(row["시작시간"], row["종료시간"])
        df.at[idx, "총시간"] = minutes_to_hhmm(m)

st.title(f"👤 {WORKER_NAME} 근태 관리")
p_start, p_end = get_current_period(HIRE_DATE)
st.caption(f"📅 현재 산정주기: {p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}")

categories = ["연차", "대체휴무", "병가", "공가"]
totals = {cat: 0 for cat in categories}

if not df.empty and "날짜" in df.columns:
    clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
    df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce').dt.date
    
    period_df = df[(df['date_dt'] >= p_start) & (df['date_dt'] <= p_end)]
    
    for cat in categories:
        cat_df = period_df[period_df["구분"].astype(str).str.strip() == cat]
        total_m = sum(calculate_net_minutes(r["시작시간"], r["종료시간"]) for _, r in cat_df.iterrows())
        totals[cat] = total_m

cols = st.columns(4)
for i, cat in enumerate(categories):
    with cols[i]:
        st.metric(f"총 {cat} 시간", minutes_to_hhmm(totals[cat]))

st.markdown("---")

st.subheader("📝 근무 / 휴가 신청 작성")

with st.form("leave_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        req_date = st.date_input("날짜", date.today())
    with col2:
        time_options = [f"{h:02d}:{m:02d}" for h in range(8, 21) for m in (0, 30)]
        start_time = st.selectbox("시작시간", time_options, index=2)
    with col3:
        end_time = st.selectbox("종료시간", time_options, index=20)
        
    col4, col5, col6 = st.columns(3)
    with col4:
        category = st.selectbox("구분", ["연차", "대체휴무", "병가", "공가"])
    with col5:
        destination = st.text_input("목적지", placeholder="-")
    with col6:
        reason = st.text_input("사유", placeholder="사유 입력")
        
    submitted = st.form_submit_button("시트에 저장하기")
    
    if submitted:
        if worksheet is None:
            st.error("구글 시트에 연결할 수 없습니다.")
        else:
            net_m = calculate_net_minutes(start_time, end_time)
            calc_total_str = minutes_to_hhmm(net_m)
            
            new_row = [
                req_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                calc_total_str,
                category,
                destination if destination else "-",
                reason if reason else "-"
            ]
            
            try:
                worksheet.append_row(new_row)
                st.success(f"성공적으로 저장되었습니다! (산정 시간: {calc_total_str})")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"저장 중 오류 발생: {e}")

st.markdown("---")

st.subheader(f"📋 {WORKER_NAME} 신청 전체 기록")

if not df.empty:
    display_df = df[["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]].copy()
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 기록이 없습니다.")
