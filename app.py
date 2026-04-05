import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成とエグゼクティブ・デザイン ---
st.set_page_config(page_title="自習室利用管理システム", page_icon="icon.png", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #e3f2fd; font-family: 'Noto Sans JP', sans-serif; }
    .main-header { font-size: 3rem; font-weight: 800; color: #1e3a8a; border-bottom: 4px solid #1e3a8a; padding-bottom: 15px; margin-bottom: 2rem; }
    [data-testid="stSidebar"] { background-color: #1e3a8a; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color: #ffffff !important; }
    .stMetric, div[data-testid="stExpander"], div[data-testid="stDataFrameContainer"] { background-color: #ffffff; padding: 25px; border-radius: 20px; box-shadow: 0 10px 15px -3px rgba(30, 58, 138, 0.1); border: 1px solid #d1e3f3; }
    .stButton>button { width: 100%; border-radius: 12px; height: 3.5rem; background-color: #1e3a8a; color: white; font-weight: 700; border: none; transition: 0.3s; }
    .stButton>button:hover { background-color: #152c66; transform: translateY(-2px); }
</style>
""", unsafe_allow_html=True)

# --- 2. バックエンド設定 ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
else:
    st.error("Secretsの設定が完了していません。")
    st.stop()

gc = gspread.authorize(credentials)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit"

@st.cache_data(ttl=60)
def load_data():
    try:
        workbook = gc.open_by_url(SPREADSHEET_URL)
        df = pd.DataFrame(workbook.worksheet("メイン").get_all_records())
        if not df.empty: df['日付'] = pd.to_datetime(df['日付'])
        return df
    except: return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])

def save_to_gs(df, sheet_name="メイン"):
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet = workbook.worksheet(sheet_name)
    worksheet.clear()
    if not df.empty:
        save_df = df.copy()
        save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("")
        worksheet.update(range_name="A1", values=[save_df.columns.tolist()] + save_df.values.tolist())
    else:
        worksheet.update(range_name="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])

# --- 3. 時刻フォーマット関数 ---
def format_time_str(t_str):
    """'1900' を '19:00' に自動補完する"""
    if not t_str: return ""
    clean = re.sub(r'[^0-9]', '', t_str)
    if len(clean) == 3: clean = "0" + clean
    if len(clean) == 4:
        return f"{clean[:2]}:{clean[2:]}"
    return t_str # すでにコロンがある場合などはそのまま

def smart_time_parse(t_str):
    """文字列をtimeオブジェクトに変換"""
    if not t_str: return None
    fmt = format_time_str(t_str)
    try:
        return datetime.strptime(fmt, "%H:%M").time()
    except: return None

# --- 4. ユーザーインターフェース ---
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=80)
    st.title("業務メニュー")
    
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="名前を入力")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    # 入力後に自動で書き換えるためのセッション管理
    col_in, col_out = st.columns(2)
    with col_in:
        raw_in = st.text_input("入室時刻", placeholder="19:00", key="raw_in")
        formatted_in = format_time_str(raw_in)
    with col_out:
        raw_out = st.text_input("退室時刻", placeholder="21:30", key="raw_out")
        formatted_out = format_time_str(raw_out)
    
    # 入力プレビューを表示（自作感を消すためにおしゃれに）
    if formatted_in or formatted_out:
        st.markdown(f"🕒 **確認:** `{formatted_in if formatted_in else '--:--'}` ～ `{formatted_out if formatted_out else '--:--'}`")

    if st.button("記録を保存する"):
        t_start = smart_time_parse(formatted_in)
        t_end = smart_time_parse(formatted_out)
        
        if f_name and t_start and t_end:
            start_dt = datetime.combine(f_date, t_start)
            end_dt = datetime.combine(f_date, t_end)
            if end_dt < start_dt: end_dt += timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            
            df = load_data()
            new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': t_start.strftime('%H:%M'), '退室時間': t_end.strftime('%H:%M'), '利用時間（時間）': duration}])
            df = pd.concat([df, new_row], ignore_index=True)
            save_to_gs(df)
            st.success("保存完了！")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("入力内容（特に時刻）を正しく入力してください")

    st.markdown("---")
    admin_pass = st.text_input("管理者パスワード", type="password")
    if admin_pass == "admin123":
        if st.button("🚨 データをリセット"):
            save_to_gs(load_data(), "バックアップ")
            save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
            st.cache_data.clear()
            st.rerun()

# メインパネル
st.markdown("<h1 class='main-header'>🏆 Study Hours Ranking</h1>", unsafe_allow_html=True)
df = load_data()

if not df.empty:
    tab1, tab2, tab3 = st.tabs(["🗓 今月の戦い", "🔥 直近3ヶ月（逆転圏内）", "👑 殿堂入り（累計）"])
    
    def render_board(target_df):
        if target_df.empty:
            st.info("データがまだありません")
            return
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        m_cols = st.columns(3)
        medals = ["🥇 Champion", "🥈 Runner-up", "🥉 3rd Place"]
        for i in range(min(3, len(agg))):
            with m_cols[i]:
                st.metric(label=f"{medals[i]}: {agg.iloc[i]['名前']}さん", value=f"{agg.iloc[i]['利用時間（時間）']}h")
        
        st.write("---")
        st.dataframe(agg, use_container_width=True, column_config={
            "利用時間（時間）": st.column_config.ProgressColumn("学習時間", format="%.2f h", min_value=0, max_value=float(agg['利用時間（時間）'].max() if not agg.empty else 1))
        })

    with tab1: render_board(df[df['日付'].dt.month == datetime.now().month])
    with tab2: render_board(df[df['日付'] >= (datetime.now() - timedelta(days=90))])
    with tab3: render_board(df)

    with st.expander("📝 履歴を確認する"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True)
else:
    st.info("最初の記録を登録しましょう！")
