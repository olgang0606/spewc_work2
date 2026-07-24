import streamlit as st
import pandas as pd
import requests
from datetime import datetime, date
import calendar

st.set_page_config(page_title="송파교육복지센터 근무 현황", layout="wide")

# ---------------------------------------------------------
# 공통 데이터 로드 함수
# ---------------------------------------------------------
@st.cache_data(ttl=10)
def load_data():
    try:
        sheet_url = st.secrets["SHEET_URL"]
        response = requests.get(sheet_url)
        data = response.json()
        if not data or len(data) < 2:
            return pd.DataFrame(columns=["근로자명", "날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"])
        
        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        return df
    except Exception as e:
        st.error(f"구글 시트 데이터를 불러오는 중 오류 발생: {e}")
        return pd.DataFrame(columns=["근로자명", "날짜", "시작시간", "종료시간", "총시간", "구분", "목적지", "사유"])

def minutes_to_hhmm(total_minutes):
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"

def hhmm_to_minutes(hhmm_str):
    try:
        parts = str(hhmm_str).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return 0

# ---------------------------------------------------------
# 메인 화면 구성
# ---------------------------------------------------------
st.title("🏛️ 송파교육복지센터 근무 및 휴가 관리 현황")
st.markdown("---")

df = load_data()

workers = ["박은경", "채미혜", "박인미", "조윤희", "성지영"]
categories = ["연차", "대체휴무", "병가", "공가"]

# --- 1. 근로자별 구분 합계 요약 (전체) ---
st.subheader("📊 근로자별 구분 합계 요약")

summary_data = []
for w in workers:
    w_df = df[df["근로자명"] == w] if "근로자명" in df.columns else pd.DataFrame()
    row = {"근로자명": w}
    for cat in categories:
        cat_df = w_df[w_df["구분"] == cat] if not w_df.empty else pd.DataFrame()
        total_mins = sum(hhmm_to_minutes(val) for val in cat_df["총시간"]) if not cat_df.empty else 0
        row[cat] = minutes_to_hhmm(total_mins)
    summary_data.append(row)

summary_df = pd.DataFrame(summary_data)
st.dataframe(summary_df, use_container_width=True)

st.markdown("---")

# --- 2. 월간 달력 일정표 ---
st.subheader("📅 월간 일정 달력")

col_y, col_m = st.columns(2)
today = date.today()
with col_y:
    selected_year = st.selectbox("연도 선택", range(today.year - 2, today.year + 3), index=2)
with col_m:
    selected_month = st.selectbox("월 선택", range(1, 13), index=today.month - 1)

# 날짜 필터링
if not df.empty and "날짜" in df.columns:
    df["날짜_dt"] = pd.to_datetime(df["날짜"], errors='coerce')
    month_df = df[(df["날짜_dt"].dt.year == selected_year) & (df["날짜_dt"].dt.month == selected_month)]
else:
    month_df = pd.DataFrame()

# 달력 매트릭스 생성
cal = calendar.monthcalendar(selected_year, selected_month)
week_days = ["월", "화", "수", "목", "금", "토", "일"]

# 달력 헤더
cols = st.columns(7)
for i, day_name in enumerate(week_days):
    cols[i].markdown(f"**{day_name}**")

# 달력 본문
for week in cal:
    cols = st.columns(7)
    for i, day in enumerate(week):
        if day == 0:
            cols[i].write(" ")
        else:
            day_str = f"{selected_year}-{selected_month:02d}-{day:02d}"
            cell_content = f"**{day}**\n\n"
            
            if not month_df.empty:
                day_records = month_df[month_df["날짜_dt"].dt.strftime('%Y-%m-%d') == day_str]
                for _, r in day_records.iterrows():
                    w_name = r.get("근로자명", "")
                    cat = r.get("구분", "")
                    t_time = r.get("총시간", "")
                    cell_content += f"- {w_name}: {cat}({t_time})\n"
            
            cols[i].info(cell_content)
