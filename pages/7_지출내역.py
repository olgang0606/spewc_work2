import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import re

st.set_page_config(page_title="월별 지출내역", page_icon="💳", layout="wide")

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
# 유틸리티 함수
# ---------------------------------------------------------
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

def extract_time_str(val):
    if pd.isna(val) or val is None:
        return ""
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
        
        # 휴게시간 (12:00~13:00) 차감
        lunch_start = datetime.strptime("12:00", "%H:%M")
        lunch_end = datetime.strptime("13:00", "%H:%M")
        if s_dt <= lunch_start and e_dt >= lunch_end:
            total_mins -= 60
        return max(0, total_mins)
    except Exception:
        return 0

# ---------------------------------------------------------
# 사이드바: 단가 설정
# ---------------------------------------------------------
st.sidebar.header("⚙️ 근로자별 수당 단가 설정")
wage_rates = {}

with st.sidebar.expander("근로자별 통상/시간외 단가 입력", expanded=True):
    for w in WORKERS:
        st.markdown(f"**[{w}]**")
        col1, col2 = st.columns(2)
        with col1:
            ot_r = st.number_input(f"{w} 시간외단가", value=20000, step=1000, key=f"ot_{w}")
        with col2:
            ord_r = st.number_input(f"{w} 통상단가", value=15000, step=1000, key=f"ord_{w}")
        wage_rates[w] = {"ot_rate": ot_r, "ord_rate": ord_r}

st.title("💳 월별 근로자 수당 지출내역")

# ---------------------------------------------------------
# 연산 로직: 전체 시트에서 월단위 수당 집계 (버림/절사 규칙 반영)
# ---------------------------------------------------------
@st.cache_data(ttl=1)
def calculate_monthly_expense():
    sh = get_spreadsheet()
    
    # 1. 개별 근로자 탭 주간(월~일) 총시간 산출
    worker_weekly_mins = {name: {} for name in WORKERS}
    for name in WORKERS:
        try:
            ws = sh.worksheet(name)
            recs = ws.get_all_records()
            if recs:
                df_w = pd.DataFrame(recs)
                if "날짜" in df_w.columns:
                    clean_dates = df_w['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
                    df_w['date_dt'] = pd.to_datetime(clean_dates, errors='coerce')
                    
                    for _, r in df_w.dropna(subset=['date_dt']).iterrows():
                        d = r['date_dt'].date()
                        monday = d - timedelta(days=d.weekday())
                        week_key = monday.strftime("%Y-%m-%d")
                        net_m = calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", ""))
                        worker_weekly_mins[name][week_key] = worker_weekly_mins[name].get(week_key, 0) + net_m
        except Exception:
            pass

    # 2. 시간외근무 탭 데이터 집계
    monthly_payouts = {}
    try:
        ws_ot = sh.worksheet("시간외근무")
        recs_ot = ws_ot.get_all_records()
        if recs_ot:
            df_ot = pd.DataFrame(recs_ot)
            if "날짜" in df_ot.columns:
                clean_ot_dates = df_ot['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.strip()
                df_ot['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce')
                
                monthly_acc = {}
                
                for _, r in df_ot.dropna(subset=['date_dt']).iterrows():
                    name = str(r.get("이름", "")).strip()
                    if name not in WORKERS:
                        continue
                        
                    d_val = r['date_dt'].date()
                    month_str = d_val.strftime("%Y-%m")
                    monday = d_val - timedelta(days=d_val.weekday())
                    week_key = monday.strftime("%Y-%m-%d")
                    
                    ord_mins = worker_weekly_mins[name].get(week_key, 0)
                    tot_mins = calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", ""))
                    ot_pay_mins = max(0, tot_mins - ord_mins)
                    alt_vac_mins = parse_time_to_minutes(r.get("대체휴무시간", 0))
                    
                    key = (name, month_str)
                    if key not in monthly_acc:
                        monthly_acc[key] = {'ot_mins': 0, 'ord_mins': 0, 'alt_vac_equals_ord': True}
                        
                    monthly_acc[key]['ot_mins'] += ot_pay_mins
                    monthly_acc[key]['ord_mins'] += ord_mins
                    if alt_vac_mins != ord_mins:
                        monthly_acc[key]['alt_vac_equals_ord'] = False

                # 3. 월 단위 1시간 미만 버림 (절사) 및 수당 계산
                for (name, month_str), acc in monthly_acc.items():
                    rates = wage_rates.get(name, {"ot_rate": 20000, "ord_rate": 15000})
                    
                    ot_hours = acc['ot_mins'] // 60
                    ord_hours = acc['ord_mins'] // 60
                    
                    if acc['alt_vac_equals_ord'] and acc['ord_mins'] > 0:
                        payout = ot_hours * rates['ot_rate']
                    else:
                        payout = (ot_hours * rates['ot_rate']) + (ord_hours * rates['ord_rate'])
                        
                    if month_str not in monthly_payouts:
                        monthly_payouts[month_str] = {}
                    monthly_payouts[month_str][name] = payout
    except Exception as e:
        st.error(f"데이터 계산 중 오류 발생: {e}")

    return monthly_payouts

# ---------------------------------------------------------
# 상단 동작 버튼
# ---------------------------------------------------------
col_act1, col_act2 = st.columns([1, 4])
with col_act1:
    if st.button("🔄 지출내역 새로고침"):
        st.cache_data.clear()
        st.rerun()

monthly_payouts = calculate_monthly_expense()

# ---------------------------------------------------------
# 구글 시트에 지출내역 탭 자동 연동
# ---------------------------------------------------------
with col_act1:
    if st.button("💾 구글 시트에 지출내역 동구화"):
        try:
            sh = get_spreadsheet()
            try:
                ws_exp = sh.worksheet("지출내역")
            except gspread.exceptions.WorksheetNotFound:
                ws_exp = sh.add_worksheet(title="지출내역", rows="100", cols="10")

            # 헤더 준비
            headers = ["월"] + WORKERS + ["총 지출합계"]
            all_rows = [headers]

            all_months = sorted(monthly_payouts.keys(), reverse=True)
            for m in all_months:
                row = [m]
                tot = 0
                for w_name in WORKERS:
                    amt = monthly_payouts[m].get(w_name, 0)
                    row.append(f"{amt:,}원")
                    tot += amt
                row.append(f"{tot:,}원")
                all_rows.append(row)

            ws_exp.clear()
            ws_exp.update("A1", all_rows)
            st.success("구글 시트 '지출내역' 탭에 결과가 업데이트 되었습니다!")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"지출내역 탭 동기화 실패: {e}")

st.markdown("---")

# ---------------------------------------------------------
# 데이터 표 출력
# ---------------------------------------------------------
st.subheader("📋 월별 지출내역 요약표")

expense_table_rows = []
all_months = sorted(monthly_payouts.keys(), reverse=True)

for m in all_months:
    row = {"월": m}
    tot = 0
    for w_name in WORKERS:
        amt = monthly_payouts[m].get(w_name, 0)
        row[w_name] = f"{amt:,}원"
        tot += amt
    row["총 지출합계"] = f"{tot:,}원"
    expense_table_rows.append(row)

if expense_table_rows:
    df_expense = pd.DataFrame(expense_table_rows)
    st.dataframe(df_expense, use_container_width=True, hide_index=True)
    
    # 선택 월 세부 분석
    st.markdown("---")
    st.subheader("🔍 선택 월 상세 내역")
    selected_month = st.selectbox("조회할 월을 선택하세요", all_months)
    
    col_chart, col_stat = st.columns([3, 2])
    with col_chart:
        chart_data = pd.DataFrame([
            {"근로자": w, "지급수당": monthly_payouts[selected_month].get(w, 0)}
            for w in WORKERS
        ])
        st.bar_chart(chart_data.set_index("근로자"))
        
    with col_stat:
        st.markdown(f"#### **[{selected_month}] 지출 현황**")
        month_total = sum(monthly_payouts[selected_month].get(w, 0) for w in WORKERS)
        st.metric("총 지출액", f"{month_total:,} 원")
        
        for w in WORKERS:
            val = monthly_payouts[selected_month].get(w, 0)
            st.write(f"- **{w}**: {val:,} 원")
else:
    st.info("집계된 지출내역 데이터가 없습니다.")
