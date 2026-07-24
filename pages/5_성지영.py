import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
import re

# ==========================================
# 1. 근로자 개인 정보 설정
# ==========================================
WORKER_NAME = "성지영"
HIRE_DATE = date(2026, 7, 1) # 입사일

st.set_page_config(page_title=f"{WORKER_NAME} 근태 관리", page_icon="👤", layout="wide")

# ==========================================
# 2. Google Sheets API 연동 & Helper 함수
# ==========================================
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
    """'16:30:00' 또는 '16:30'에서 초를 제외한 '16:30'만 추출"""
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
    return match.group(1) if match else ""

def calculate_net_minutes(start_str, end_str):
    """
    시작시간~종료시간 실근무/휴가 분(Minutes) 계산
    - 12:00~13:00(점심시간)이 포함되어 있으면 60분(1시간) 차감
    """
    s_hhmm = extract_time_str(start_str)
    e_hhmm = extract_time_str(end_str)
    
    if not s_hhmm or not e_hhmm:
        return 0
        
    try:
        s_dt = datetime.strptime(s_hhmm, "%H:%M")
        e_dt = datetime.strptime(e_hhmm, "%H:%M")
        
        if e_dt <= s_dt:
            return 0
            
        # 총시간(분)
        total_mins = int((e_dt - s_dt).total_seconds() // 60)
        
        # 점심시간(12:00~13:00) 포함 여부 체크
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        
        # 시작이 12:00 이전이고 종료가 13:00 이후이면 점심시간 60분 제외
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
            
        return max(0, total_mins)
    except Exception:
        return 0

def minutes_to_hhmm(mins):
    """분을 HH:MM 형식의 문자열로 변환"""
    mins = max(0, int(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"

def get_current_period(hire_d, ref_date=None):
    """입사일 기준 현재 산정주기 계산"""
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

# ==========================================
# 3. 데이터 로드 및 보완 로직
# ==========================================
@st.cache_data(ttl=5)
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
    except Exception as e:
        return pd.DataFrame(columns=target_cols), None

df, worksheet = load_data()

# ✨ 핵심: 총시간이 누락되었거나 '18:00:00' 형태인 기존 데이터를 자동 보완
if not df.empty:
    for idx, row in df.iterrows():
        # 총시간 계산
        m = calculate_net_minutes(row["시작시간"], row["종료시간"])
        df.at[idx, "총시간"] = minutes_to_hhmm(m)

# ==========================================
# 4. 상단 요약 카드 (총 사용 시간)
# ==========================================
st.title(f"👤 {WORKER_NAME} 근태 관리")

p_start, p_end = get_current_period(HIRE_DATE)
st.caption(f"📅 현재 산정주기: {p_start.strftime('%Y-%m-%d')} ~ {p_end.strftime('%Y-%m-%d')}")

# 현재 산정주기 내 데이터만 필터링하여 합산
categories = ["연차", "대체휴무", "병가", "공가"]
totals = {cat: 0 for cat in categories}

if not df.empty and "날짜" in df.columns:
    # 다양한 날짜 형식(2026.3.5 / 2026-03-05) 호환 파싱
    clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-")
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

# ==========================================
# 5. 근무 / 휴가 신청 작성 폼
# ==========================================
st.subheader("📝 근무 / 휴가 신청 작성")

with st.form("leave_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        req_date = st.date_input("날짜", date.today())
    with col2:
        # 30분 단위 시간 선택 옵션
        time_options = [f"{h:02d}:{m:02d}" for h in range(8, 21) for m in (0, 30)]
        start_time = st.selectbox("시작시간", time_options, index=2) # 09:00
    with col3:
        end_time = st.selectbox("종료시간", time_options, index=20) # 18:00
        
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
            # ✨ 저장할 때 점심시간 제외 및 총시간 자동 산출
            net_m = calculate_net_minutes(start_time, end_time)
            calc_total_str = minutes_to_hhmm(net_m)
            
            new_row = [
                req_date.strftime("%Y-%m-%d"),
                start_time,
                end_time,
                calc_total_str, # 총시간 자동 채움
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

# ==========================================
# 6. 신청 전체 기록 테이블
# ==========================================
st.subheader(f"📋 {WORKER_NAME} 신청 전체 기록")

if not df.empty:
    # 화면 표사용 컬럼만 정리
    display_df = df[["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]].copy()
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("등록된 기록이 없습니다.")
