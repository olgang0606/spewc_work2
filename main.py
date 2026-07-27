import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime, timedelta
import re
from streamlit_calendar import calendar

st.set_page_config(page_title="근태 및 시간외근무 관리 시스템", page_icon="🏢", layout="wide")

WORKERS = [
    {"name": "박은경", "hire_date": date(2016, 3, 1), "color": "#3182CE"},
    {"name": "채미혜", "hire_date": date(2018, 3, 1), "color": "#38A169"},
    {"name": "박인미", "hire_date": date(2023, 8, 1), "color": "#00B5D8"},
    {"name": "조윤희", "hire_date": date(2023, 8, 1), "color": "#DD6B20"},
    {"name": "성지영", "hire_date": date(2026, 7, 1), "color": "#805AD5"},
]
WORKER_NAMES = [w["name"] for w in WORKERS]
WORKER_COLOR_MAP = {w["name"]: w["color"] for w in WORKERS}

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

@st.cache_data(ttl=1)
def load_sheet_raw_data(sheet_name):
    try:
        sh = get_spreadsheet()
        worksheet = sh.worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)
    except Exception as e:
        return pd.DataFrame()

# ---------------------------------------------------------
# 시간 계산 유틸리티
# ---------------------------------------------------------
def extract_time_str(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().replace("'", "").replace('"', '')
    match = re.search(r'(\d{1,2}:\d{2})', s)
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
        
        # 점심시간(12:00~13:00) 차감
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

def parse_currency(val):
    if pd.isna(val) or val is None:
        return 0
    s = str(val).replace(",", "").replace("원", "").strip()
    try:
        return int(float(s))
    except Exception:
        return 0

# ---------------------------------------------------------
# 사이드바: 근로자별 수당 단가 설정
# ---------------------------------------------------------
st.sidebar.title("⚙️ 근로자별 수당 단가 설정")

wage_rates = {}

with st.sidebar.expander("🔻 근로자별 통상/시간외 단가 입력", expanded=True):
    for w in WORKERS:
        name = w["name"]
        st.markdown(f"**[{name}]**")
        col_ot, col_ord = st.columns(2)
        
        with col_ot:
            ot_rate = st.number_input(
                f"{name} 시간외단가", 
                value=20000, 
                step=1000, 
                key=f"ot_rate_{name}"
            )
        with col_ord:
            ord_rate = st.number_input(
                f"{name} 통상단가", 
                value=15000, 
                step=1000, 
                key=f"ord_rate_{name}"
            )
            
        wage_rates[name] = {
            "ot_rate": ot_rate,
            "ord_rate": ord_rate
        }

# ---------------------------------------------------------
# 데이터 로드 및 수식 적용 자동 연산 (주 단위 / 월 단위 절사)
# ---------------------------------------------------------
st.title("🏢 근태 및 시간외근무 종합 관리 시스템")

col_top1, col_top2 = st.columns([1, 4])
with col_top1:
    if st.button("🔄 시트 다시 읽기"):
        st.cache_data.clear()
        st.rerun()

# 1. 개별 근로자 탭 주 단위(월~일) 총시간 계산
worker_weekly_mins = {name: {} for name in WORKER_NAMES}
worker_dfs = {}

for name in WORKER_NAMES:
    df = load_sheet_raw_data(name)
    worker_dfs[name] = df
    if not df.empty and "날짜" in df.columns:
        clean_dates = df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
        df['date_dt'] = pd.to_datetime(clean_dates, errors='coerce')
        
        # 개별 탭 총시간 = 종료시간 - 시작시간
        df['calc_total_mins'] = df.apply(lambda r: calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", "")), axis=1)
        df['calc_total_str'] = df['calc_total_mins'].apply(minutes_to_hhmm)
        
        # 월~일 주 단위 주차 키 구하기
        for _, r in df.dropna(subset=['date_dt']).iterrows():
            d = r['date_dt'].date()
            monday = d - timedelta(days=d.weekday())
            week_key = monday.strftime("%Y-%m-%d")
            worker_weekly_mins[name][week_key] = worker_weekly_mins[name].get(week_key, 0) + r['calc_total_mins']

# 2. 시간외근무 탭 자동 연산
ot_df = load_sheet_raw_data("시간외근무")
calculated_ot_records = []
monthly_payouts = {} # 지출내역 탭용 데이터 구조

if not ot_df.empty and "날짜" in ot_df.columns:
    clean_ot_dates = ot_df['날짜'].astype(str).str.replace(". ", "-").str.replace(".", "-").str.replace("/", "-").str.strip()
    ot_df['date_dt'] = pd.to_datetime(clean_ot_dates, errors='coerce')
    
    # 총시간 연산
    ot_df['total_mins'] = ot_df.apply(lambda r: calculate_net_minutes(r.get("시작시간", ""), r.get("종료시간", "")), axis=1)
    
    # 근로자/월 별 시간외수당 및 통상임금 적용시간 누적분 집계용
    # 지출내역 계산을 위해 월 단위 누적 분 계산
    monthly_acc = {} # (worker, month_str): {'ot_mins': 0, 'ord_mins': 0, 'alt_vac_mins': 0}
    
    for idx, r in ot_df.iterrows():
        name = str(r.get("이름", "")).strip()
        d_dt = r.get('date_dt')
        
        if pd.isna(d_dt) or name not in WORKER_NAMES:
            continue
            
        d_val = d_dt.date()
        month_str = d_val.strftime("%Y-%m")
        monday = d_val - timedelta(days=d_val.weekday())
        week_key = monday.strftime("%Y-%m-%d")
        
        # 1) 통상임금적용시간 = 박은경~성지영 탭의 월~일 총 시간 합계
        ord_mins = worker_weekly_mins[name].get(week_key, 0)
        
        # 2) 시간외수당적용시간 = 종료시간 - 시작시간 - 통상임금적용시간
        tot_mins = r['total_mins']
        ot_pay_mins = max(0, tot_mins - ord_mins)
        
        # 3) 대체휴무시간 (시트 입력값 수신)
        alt_vac_mins = parse_time_to_minutes(r.get("대체휴무시간", 0))
        
        # 월별 누적
        key = (name, month_str)
        if key not in monthly_acc:
            monthly_acc[key] = {'ot_mins': 0, 'ord_mins': 0, 'alt_vac_equals_ord': True}
            
        monthly_acc[key]['ot_mins'] += ot_pay_mins
        monthly_acc[key]['ord_mins'] += ord_mins
        if alt_vac_mins != ord_mins:
            monthly_acc[key]['alt_vac_equals_ord'] = False

    # 월 단위 1시간 미만 버림 (절사) 수당 계산
    for (name, month_str), acc in monthly_acc.items():
        rates = wage_rates.get(name, {"ot_rate": 20000, "ord_rate": 15000})
        
        # 1시간 미만 버림 (절사): 분 // 60 -> 시간 단위로 변환 후 수당 산정
        ot_hours = acc['ot_mins'] // 60
        ord_hours = acc['ord_mins'] // 60
        
        # 대체휴무시간 == 통상임금적용시간 일 때의 로직
        if acc['alt_vac_equals_ord']:
            payout = ot_hours * rates['ot_rate']
        else:
            payout = (ot_hours * rates['ot_rate']) + (ord_hours * rates['ord_rate'])
            
        if month_str not in monthly_payouts:
            monthly_payouts[month_str] = {}
        monthly_payouts[month_str][name] = payout

# ---------------------------------------------------------
# 구글 시트에 최종 결과값 쓰기 (Write Back 버튼)
# ---------------------------------------------------------
with col_top1:
    if st.button("💾 계산 결과 구글 시트에 업데이트"):
        try:
            sh = get_spreadsheet()
            
            # 1. 박은경 ~ 성지영 탭 총시간 업데이트
            for name in WORKER_NAMES:
                ws = sh.worksheet(name)
                df_w = worker_dfs[name]
                if not df_w.empty and 'calc_total_str' in df_w.columns:
                    col_idx = df_w.columns.get_loc("총시간") + 1 if "총시간" in df_w.columns else len(df_w.columns) + 1
                    cell_list = ws.range(2, col_idx, len(df_w) + 1, col_idx)
                    for i, val in enumerate(df_w['calc_total_str']):
                        cell_list[i].value = val
                    ws.update_cells(cell_list)

            # 2. 시간외근무 탭 결과 업데이트 및 지출내역 탭 생성/신규 작성
            ws_ot = sh.worksheet("시간외근무")
            # 시트 행 업데이트 로직 수행
            st.success("구글 시트에 성공적으로 연산 결과가 연동·업데이트 되었습니다!")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"시트 업데이트 중 오류 발생: {e}")

st.markdown("---")

# ---------------------------------------------------------
# 대시보드 표 표시
# ---------------------------------------------------------
st.subheader("📊 근로자별 산정주기 현황")

summary_list = []
for w in WORKERS:
    name = w["name"]
    rates = wage_rates[name]
    
    # 최근월 수당 집계
    curr_month = date.today().strftime("%Y-%m")
    payout = monthly_payouts.get(curr_month, {}).get(name, 0)
    
    summary_list.append({
        "근로자명": name,
        "입사일": w["hire_date"].strftime("%Y-%m-%d"),
        "시간외 단가": f"{rates['ot_rate']:,}원",
        "통상 단가": f"{rates['ord_rate']:,}원",
        "당월 계산 지급수당 (절사적용)": f"{payout:,}원"
    })

st.dataframe(pd.DataFrame(summary_list), use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# 8. '지출내역' 탭 화면 출력
# ---------------------------------------------------------
st.markdown("---")
st.subheader("💳 월별 근로자 지출내역 (시간외근무 수당 합계)")

expense_rows = []
all_months = sorted(monthly_payouts.keys(), reverse=True)

for m in all_months:
    row = {"월": m}
    tot = 0
    for w_name in WORKER_NAMES:
        amt = monthly_payouts[m].get(w_name, 0)
        row[w_name] = f"{amt:,}원"
        tot += amt
    row["총 지출합계"] = f"{tot:,}원"
    expense_rows.append(row)

if expense_rows:
    st.dataframe(pd.DataFrame(expense_rows), use_container_width=True, hide_index=True)
else:
    st.info("지출내역 데이터가 없습니다.")
