import streamlit as st
import pandas as pd
import requests
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
# 2. 구글 시트 연동 함수 (비밀금고 SHEET_URL 활용)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_data_from_sheet():
    """SHEET_URL을 사용하여 구글 시트 데이터를 CSV 형태로 로드"""
    try:
        if "SHEET_URL" not in st.secrets:
            st.error("secrets.toml에 'SHEET_URL'이 설정되어 있지 않습니다.")
            return pd.DataFrame(columns=["시각", "팀원", "메뉴", "구분", "날짜"])
            
        sheet_url = st.secrets["SHEET_URL"]
        
        # /exec 기반 웹앱 주소일 경우 웹 공개 CSV 주소로 자동 변환 시도
        if "/exec" in sheet_url:
            csv_url = sheet_url.replace("/exec", "/pub?output=csv")
        else:
            csv_url = sheet_url
            
        df = pd.read_csv(csv_url)
        
        if not df.empty and "시각" in df.columns:
            # 시각 칼럼에서 날짜 데이터 추출
            df["날짜"] = pd.to_datetime(df["시각"]).dt.date
            return df
    except Exception as e:
        st.warning(f"구글 시트 데이터 로드 안내: {e}")
        
    return pd.DataFrame(columns=["시각", "팀원", "메뉴", "구분", "날짜"])

def send_to_google_sheet(member: str, menu_val: str, type_val: str) -> bool:
    """
    requests 모듈을 통해 Google Apps Script 웹 앱으로 데이터 전송
    파라미터: member, menu, type
    """
    try:
        if "SHEET_URL" not in st.secrets:
            st.error("secrets.toml에 'SHEET_URL'이 누락되었습니다.")
            return False
            
        sheet_url = st.secrets["SHEET_URL"]
        params = {
            "member": member,
            "menu": menu_val,
            "type": type_val
        }
        # GAS 웹앱 302 리다이렉트 대응을 위해 allow_redirects=True 사용
        response = requests.get(sheet_url, params=params, allow_redirects=True, timeout=10)
        return response.status_code == 200
    except Exception as e:
        st.error(f"전송 실패: {e}")
        return False

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
# 3. 데이터 로드 및 사이드바 메뉴
# -----------------------------------------------------------------------------
df_all = load_data_from_sheet()

st.sidebar.title("📌 송파교육복지센터")

menu_options = ["메인 (월간 달력)"] + list(EMPLOYEES.keys())
selected_menu = st.sidebar.radio("메뉴 이동", menu_options)

if st.sidebar.button("🔄 구글 시트 새로고침"):
    st.cache_data.clear()
    st.rerun()

# -----------------------------------------------------------------------------
# PAGE 1: 메인 페이지 (월간 달력)
# -----------------------------------------------------------------------------
if selected_menu == "메인 (월간 달력)":
    st.header("🗓️ 근로자별 월간 근무 현황 달력")
    
    st.subheader("📊 근로자별 구분 현황")
    
    summary_data = []
    for emp_name in EMPLOYEES.keys():
        emp_df = df_all[df_all["팀원"] == emp_name] if "팀원" in df_all.columns else pd.DataFrame()
        row = {"팀원": emp_name}
        for cat in CATEGORIES:
            count = len(emp_df[emp_df["구분"] == cat]) if not emp_df.empty else 0
            row[cat] = f"{count}건"
        summary_data.append(row)
        
    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True)
    
    st.markdown("---")
    
    st.subheader("📅 월간 일정표")
    
    calendar_events = []
    color_map = {
        "연차": "#FF4B4B",
        "대체휴무": "#31333F",
        "병가": "#FFA500",
        "공가": "#008000"
    }
    
    if not df_all.empty and "팀원" in df_all.columns:
        for _, record in df_all.iterrows():
            event_date = str(record["날짜"]) if "날짜" in record and pd.notnull(record["날짜"]) else date.today().strftime("%Y-%m-%d")
            calendar_events.append({
                "title": f"[{record.get('팀원', '')}] {record.get('구분', '')} - {record.get('메뉴', '')}",
                "start": event_date,
                "end": event_date,
                "color": color_map.get(record.get("구분", ""), "#3D5A80")
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
# PAGE 2~6: 근로자별 개별 페이지 및 입력 폼
# -----------------------------------------------------------------------------
else:
    selected_emp = selected_menu
    hire_date = EMPLOYEES[selected_emp]
    current_year = date.today().year
    
    st.header(f"👤 {selected_emp} 근로자 현황")
    
    annual_hours = calculate_annual_leave_hours(hire_date, current_year)
    annual_hhmm = minutes_to_hhmm(annual_hours * 60)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("입사일", hire_date.strftime("%Y-%m-%d"))
    with col2:
        st.metric(f"{current_year}년 산정 연차 시간", f"{annual_hours}시간 ({annual_hhmm})")
        
    st.markdown("---")
    
    # 근무/휴무 기록 추가 폼
    with st.expander("➕ 근무/휴무 기록 접수하기", expanded=True):
        with st.form("add_record_form"):
            c1, c2 = st.columns(2)
            menu_input = c1.text_input("메뉴 (내용/사유)", placeholder="예: 오전 연차, 병가 신청 등")
            type_input = c2.selectbox("구분", CATEGORIES)
            
            submit = st.form_submit_button("구글 시트로 전송")
            
            if submit:
                if not menu_input.strip():
                    st.error("메뉴(내용)를 입력해주세요.")
                else:
                    success = send_to_google_sheet(
                        member=selected_emp,
                        menu_val=menu_input,
                        type_val=type_input
                    )
                    
                    if success:
                        st.success("구글 시트에 성공적으로 접수되었습니다!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("전송 중 오류가 발생했습니다. SHEET_URL을 확인해주세요.")

    # 개별 총괄표
    st.subheader(f"📋 {selected_emp} 접수 내역")
    
    if not df_all.empty and "팀원" in df_all.columns:
        emp_df = df_all[df_all["팀원"] == selected_emp]
        if not emp_df.empty:
            st.dataframe(emp_df[["시각", "팀원", "메뉴", "구분"]], use_container_width=True)
        else:
            st.info("접수된 기록이 없습니다.")
    else:
        st.info("데이터를 불러오는 중이거나 기록이 없습니다.")
