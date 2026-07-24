import streamlit as st
import pandas as pd
from datetime import datetime, date, time
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
# 2. 로직 함수 (연차 계산, 시간 연산, 점심시간 차감)
# -----------------------------------------------------------------------------
def calculate_annual_leave_hours(hire_date: date, target_year: int) -> int:
    """
    근로기준법 기준 연차 시간 계산 (1일 = 8시간)
    - 1년 미만: 1개월 개근 시 1일 (최대 11일 = 88시간)
    - 1년 이상: 기본 15일 + 2년마다 1일 가산 (최대 25일 = 200시간)
    """
    years_of_service = target_year - hire_date.year
    
    if years_of_service < 1:
        today = date.today()
        months = (today.year - hire_date.year) * 12 + today.month - hire_date.month
        days = min(max(months, 0), 11)
    else:
        additional_days = (years_of_service - 1) // 2
        days = min(15 + additional_days, 25)
        
    return days * 8  # 총 시간(Hours) 반환

def minutes_to_hhmm(minutes: int) -> str:
    """분 단위를 hh:mm 문자열 형식으로 변환"""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"

def calculate_work_minutes(start_t: time, end_t: time) -> int:
    """
    시작시간과 종료시간 사이의 총 분(minute)을 계산하며,
    12:00~13:00(점심시간)과 겹치는 시간이 있으면 제외함.
    """
    start_dt = datetime.combine(date.today(), start_t)
    end_dt = datetime.combine(date.today(), end_t)
    
    if end_dt <= start_dt:
        return 0
        
    total_minutes = int((end_dt - start_dt).total_seconds() // 60)
    
    # 점심시간 범위 (12:00 ~ 13:00)
    lunch_start = datetime.combine(date.today(), time(12, 0))
    lunch_end = datetime.combine(date.today(), time(13, 0))
    
    # 점심시간과 입력된 시간 사이의 겹치는 구간 계산
    overlap_start = max(start_dt, lunch_start)
    overlap_end = min(end_dt, lunch_end)
    
    if overlap_start < overlap_end:
        lunch_overlap_mins = int((overlap_end - overlap_start).total_seconds() // 60)
        total_minutes -= lunch_overlap_mins
        
    return max(total_minutes, 0)

# -----------------------------------------------------------------------------
# 3. 세션 상태(Session State) 초기화
# -----------------------------------------------------------------------------
if "records" not in st.session_state:
    st.session_state.records = pd.DataFrame([
        {
            "근로자": "박은경",
            "날짜": date(2026, 7, 10),
            "시작시간": "09:00",
            "종료시간": "18:00",
            "총시간": "08:00",  # 점심시간 1시간 제외됨
            "총시간_분": 480,
            "구분": "연차",
            "목적지": "-",
            "사유": "개인사유"
        },
        {
            "근로자": "채미혜",
            "날짜": date(2026, 7, 15),
            "시작시간": "13:00",
            "종료시간": "17:00",
            "총시간": "04:00",
            "총시간_분": 240,
            "구분": "병가",
            "목적지": "병원",
            "사유": "진료"
        }
    ])

# -----------------------------------------------------------------------------
# 4. 사이드바 메뉴 (근로자 5명 나열)
# -----------------------------------------------------------------------------
st.sidebar.title("📌 송파교육복지센터")

menu_options = ["메인 (월간 달력)"] + list(EMPLOYEES.keys())
selected_menu = st.sidebar.radio("메뉴 이동", menu_options)

# -----------------------------------------------------------------------------
# PAGE 1: 메인 페이지 (월간 달력)
# -----------------------------------------------------------------------------
if selected_menu == "메인 (월간 달력)":
    st.header("🗓️ 근로자별 월간 근무 현황 달력")
    
    # 1. 근로자별 구분 합계 요약 표
    st.subheader("📊 근로자별 구분 합계 (hh:mm)")
    
    summary_data = []
    df_all = st.session_state.records
    
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
    
    # 2. 월간 일정표
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
            "start": record["날짜"].strftime("%Y-%m-%d"),
            "end": record["날짜"].strftime("%Y-%m-%d"),
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
# PAGE 2~6: 근로자별 개별 페이지 (메뉴 클릭 시 이동)
# -----------------------------------------------------------------------------
else:
    selected_emp = selected_menu
    hire_date = EMPLOYEES[selected_emp]
    current_year = date.today().year
    
    st.header(f"👤 {selected_emp} 근로자 현황")
    
    # 근로자 기본 정보 및 연차 계산 (시간 단위)
    annual_hours = calculate_annual_leave_hours(hire_date, current_year)
    annual_hhmm = minutes_to_hhmm(annual_hours * 60)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("입사일", hire_date.strftime("%Y-%m-%d"))
    with col2:
        st.metric(f"{current_year}년 산정 연차 시간", f"{annual_hours}시간 ({annual_hhmm})")
    with col3:
        # 사용한 총 연차 시간 계산
        emp_records = st.session_state.records[st.session_state.records["근로자"] == selected_emp]
        used_annual_mins = emp_records[emp_records["구분"] == "연차"]["총시간_분"].sum()
        st.metric("사용 연차 시간", minutes_to_hhmm(used_annual_mins))
        
    st.markdown("---")
    
    # 근무 기록 입력 폼
    with st.expander("➕ 근무/휴무 기록 추가하기", expanded=False):
        st.caption("ℹ️ 12:00~13:00(점심시간)이 포함된 경우 1시간이 자동으로 차감됩니다.")
        with st.form("add_record_form"):
            c1, c2, c3 = st.columns(3)
            rec_date = c1.date_input("날짜", date.today())
            start_t = c2.time_input("시작시간", value=datetime.strptime("09:00", "%H:%M").time())
            end_t = c3.time_input("종료시간", value=datetime.strptime("18:00", "%H:%M").time())
            
            c4, c5, c6 = st.columns(3)
            category = c4.selectbox("구분", CATEGORIES)
            destination = c5.text_input("목적지", "-")
            reason = c6.text_input("사유", "-")
            
            submit = st.form_submit_button("저장")
            
            if submit:
                diff_mins = calculate_work_minutes(start_t, end_t)
                
                if diff_mins <= 0:
                    st.error("종료시간은 시작시간보다 나중이어야 하며, 점심시간 외 유효한 근로시간이 있어야 합니다.")
                else:
                    new_row = {
                        "근로자": selected_emp,
                        "날짜": rec_date,
                        "시작시간": start_t.strftime("%H:%M"),
                        "종료시간": end_t.strftime("%H:%M"),
                        "총시간": minutes_to_hhmm(diff_mins),
                        "총시간_분": diff_mins,
                        "구분": category,
                        "목적지": destination,
                        "사유": reason
                    }
                    st.session_state.records = pd.concat(
                        [st.session_state.records, pd.DataFrame([new_row])], 
                        ignore_index=True
                    )
                    st.success(f"성공적으로 등록되었습니다. (차감 적용 후 총시간: {minutes_to_hhmm(diff_mins)})")
                    st.rerun()

    # 개인별 상세 총괄표
    st.subheader(f"📋 {selected_emp} 근무/휴무 총괄표")
    
    emp_df = st.session_state.records[st.session_state.records["근로자"] == selected_emp].copy()
    
    if not emp_df.empty:
        # 시간 합계 현황 카드
        cat_cols = st.columns(4)
        for idx, cat in enumerate(CATEGORIES):
            cat_mins = emp_df[emp_df["구분"] == cat]["총시간_분"].sum()
            cat_cols[idx].metric(f"총 {cat}", minutes_to_hhmm(cat_mins))
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 상세 데이터 테이블 표시
        display_df = emp_df[["날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"]].sort_values(by="날짜", ascending=False)
        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("등록된 근무 현황이 없습니다.")
