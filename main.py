import streamlit as st
import pandas as pd
from datetime import datetime, date
from streamlit_calendar import calendar as st_calendar

# -----------------------------------------------------------------------------
# 1. 기본 설정 및 데이터 정의
# -----------------------------------------------------------------------------
st.set_page_config(page_title="송파교육복지센터 근무 현황", layout="wide")

EMPLOYEES = {
    "박은경": date(2016, 3, 1),
    "채미혜": date(2018, 3, 1),
    "박인미": date(2023, 8, 1),
    "조윤희": date(2023, 8, 1),
    "성지영": date(2026, 7, 1)
}

CATEGORIES = ["연차", "대체휴무", "병가", "공가"]

# -----------------------------------------------------------------------------
# 2. 구글 시트(CSV URL) 데이터 불러오기 함수 (무료/비인증 방식)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)  # 60초마다 구글 시트 데이터 자동 캐시 갱신
def load_data_from_csv():
    """구글 시트에서 공개한 CSV URL을 통해 데이터 읽어오기"""
    try:
        csv_url = st.secrets["gsheets"]["csv_url"]
        df = pd.read_csv(csv_url)
        
        # 필수 칼럼 확인 및 데이터 전처리
        if not df.empty:
            df["날짜"] = pd.to_datetime(df["날짜"]).dt.date
            df["총시간_분"] = pd.to_numeric(df["총시간_분"], errors='coerce').fillna(0).astype(int)
            return df
    except Exception as e:
        st.error(f"구글 시트 데이터를 불러오는데 실패했습니다: {e}")
        
    return pd.DataFrame(columns=["근로자", "날짜", "시작시간", "종료시간", "총시간", "총시간_분", "구분", "목적지", "사유"])

def calculate_annual_leave_hours(hire_date: date, target_year: int) -> int:
    """근로기준법 기준 연차 시간 계산 (1일 = 8시간)"""
    years_of_service = target_year - hire_date.year
    if years_of_service < 1:
        today = date.today()
        months = (today.year - hire_date.year) * 12 + today.month - hire_date.month
        days = min(max(months, 0), 11)
    else:
        additional_days = (years_of_service - 1) // 2
        days = min(15 + additional_days, 25)
    return days * 8

def minutes_to_hhmm(minutes: int) -> str:
    """분 단위를 hh:mm 문자열 형식으로 변환"""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

# -----------------------------------------------------------------------------
# 3. 데이터 로드
# -----------------------------------------------------------------------------
df_all = load_data_from_csv()

# -----------------------------------------------------------------------------
# 4. 사이드바 메뉴
# -----------------------------------------------------------------------------
st.sidebar.title("📌 송파교육복지센터")

menu_options = ["메인 (월간 달력)"] + list(EMPLOYEES.keys())
selected_menu = st.sidebar.radio("메뉴 이동", menu_options)

# 데이터 수동 새로고침 버튼
if st.sidebar.button("🔄 구글 시트 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

# -----------------------------------------------------------------------------
# PAGE 1: 메인 페이지 (월간 달력 및 전체 현황)
# -----------------------------------------------------------------------------
if selected_menu == "메인 (월간 달력)":
    st.header("🗓️ 근로자별 월간 근무 현황 달력")
    
    # 1. 근로자별 구분 합계 요약 표
    st.subheader("📊 근로자별 구분 합계 (hh:mm)")
    
    summary_data = []
    for emp_name in EMPLOYEES.keys():
        emp_df = df_all[df_all["근로자"] == emp_name]
        row = {"근로자": emp_name}
        for cat in CATEGORIES:
            total_mins = emp_df[emp_df["구분"] == cat]["총시간_분"].sum()
            row[cat] = minutes_to_hhmm(total_mins)
        summary_data.append(row)
        
    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True)
    
    st.markdown("---")
    
    # 2. 월간 일정표 (Calendar)
    st.subheader("📅 월간 일정표")
    
    calendar_events = []
    color_map = {
        "연차": "#FF4B4B",
        "대체휴무": "#31333F",
        "병가": "#FFA500",
        "공가": "#008000"
    }
    
    for _, record in df_all.iterrows():
        calendar_events.append({
            "title": f"[{record['근로자']}] {record['구분']} ({record['총시간']})",
            "start": str(record["날짜"]),
            "end": str(record["날짜"]),
            "color": color_map.get(record["구분"], "#3D5A80")
        })
        
    calendar_options = {
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek"
        },
        "initialView": "dayGridMonth",
        "selectable": True,
    }
    
    st_calendar(events=calendar_events, options=calendar_options)

# -----------------------------------------------------------------------------
# PAGE 2~6: 근로자별 개별 페이지
# -----------------------------------------------------------------------------
else:
    selected_emp = selected_menu
    hire_date = EMPLOYEES[selected_emp]
    current_year = date.today().year
    
    st.header(f"👤 {selected_emp} 근로자 현황")
    
    # 근로자 연차 기준 계산
    annual_hours = calculate_annual_leave_hours(hire_date, current_year)
    annual_hhmm = minutes_to_hhmm(annual_hours * 60)
    
    # 개인별 사용 연차 계산
    emp_records = df_all[df_all["근로자"] == selected_emp]
    used_annual_mins = emp_records[emp_records["구분"] == "연차"]["총시간_분"].sum()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("입사일", hire_date.strftime("%Y-%m-%d"))
    with col2:
        st.metric(f"{current_year}년 산정 연차 시간", f"{annual_hours}시간 ({annual_hhmm})")
    with col3:
        st.metric("사용 연차 시간", minutes_to_hhmm(used_annual_mins))
        
    st.markdown("---")
    
    # 개인별 상세 총괄표
    st.subheader(f"📋 {selected_emp} 근무/휴무 총괄표")
    
    if not emp_records.empty:
        # 구분별 총합계 카드
        cat_cols = st.columns(4)
        for idx, cat in enumerate(CATEGORIES):
            cat_mins = emp_records[emp_records["구분"] == cat]["총시간_분"].sum()
            cat_cols[idx].metric(f"총 {cat}", minutes_to_hhmm(cat_mins))
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 상세 데이터 테이블 표시
        display_df = emp_records[["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]].sort_values(by="날짜", ascending=False)
        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("구글 시트에 등록된 근무/휴무 내역이 없습니다.")
