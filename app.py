import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成とエグゼクティブ・デザイン ---
st.set_page_config(page_title="自習室プレミアム", page_icon="icon.png", layout="wide")

# CSSによる徹底的なリデザイン
st.markdown("""
    <style>
    .stApp { background-color: #f0f2f6; }
    .main-header { font-size: 2.5rem; font-weight: 800; color: #0f172a; margin-bottom: 1rem; }
    
    /* カード・コンテナ */
    .stMetric, .css-1r6slb0, .stDataFrame {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 16px;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.04), 0 4px 6px -2px rgba(0,0,0,0.02);
        border: 1px solid #f1f5f9;
    }
    
    /* 入室・退室のプレビュー表示 */
    .time-preview {
        font-size: 0.85rem;
        color: #64748b;
        margin-top: -15px;
        margin-bottom: 10px;
        font-weight: 600;
    }
    
    /* ボタンデザイン */
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3rem;
        background-color: #2563eb;
        color: white;
        border: none;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. バックエンド（スプレッドシート連携） ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
else:
    st.error("Secretsの設定が未完了です。")
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

# --- 3. スマート・タイム・デコーダー ---
def smart_time_parse(t_str):
    """'2100' も '21:00' も適切に変換する魔法の関数"""
    if not t_str: return None
    clean_t = re.sub(r'[^0-9]', '', t_str) # 数字だけ抽出
    
    if len(clean_t) == 3: clean_t = "0" + clean_t # 900 -> 0900
    if len(clean_t) == 4:
        hh, mm = int(clean_t[:2]), int(clean_t[2:])
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hh, mm)
    
    # 既に ':' が入っている場合のフォールバック
    try:
        return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. インターフェース ---

# サイドバー（管理・入力）
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=80)
    st.title("Registration")
    
    # 入力フォーム（あえて st.form を使わず、入力の即時性を優先）
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="名前を入力")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in:
        f_start_raw = st.text_input("入室 (例:1700)", key="in")
        t_start = smart_time_parse(f_start_raw)
        if t_start: st.markdown(f"<p class='time-preview'>→ {t_start.strftime('%H:%M')}</p>", unsafe_allow_html=True)
    
    with col_out:
        f_end_raw = st.text_input("退室 (例:2130)", key="out")
        t_end = smart_time_parse(f_end_raw)
        if t_end: st.markdown(f"<p class='time-preview'>→ {t_end.strftime('%H:%M')}</p>", unsafe_allow_html=True)
    
    if st.button("記録を保存する"):
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
            st.error("入力内容を確認してください")

    st.markdown("---")
    admin_pass = st.text_input("Admin Password", type="password")
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
            st.info("集計可能なデータがまだありません")
            return
        
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        # トップ3の特別カード
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
    with tab3: render_board(df) # これが累計（殿堂入り）

    with st.expander("📝 履歴を確認する"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True)
else:
    st.info("データがありません。最初の記録を登録しましょう！")
    /* 入室・退室のプレビュー表示 */
    .time-preview {
        font-size: 0.9rem;
        color: #93c5fd; /* 薄い青のアクセント */
        margin-top: -15px;
        margin-bottom: 10px;
        font-weight: 700;
    }

    /* ボタンデザイン */
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3.5rem;
        background-color: #1e3a8a; /* 藍色 */
        color: white;
        border: none;
        box-shadow: 0 4px 6px -1px rgba(30, 58, 138, 0.3);
        font-weight: 700;
        font-size: 1.1rem;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #152c66; /* ホバー時は少し濃い藍色 */
        box-shadow: 0 6px 8px -1px rgba(30, 58, 138, 0.4);
        transform: translateY(-2px); /* 少し浮き上がる効果 */
    }

    /* プログレスバー（学習時間） */
    div[data-testid="stProgress"] > div > div > div > div {
        background-color: #1e3a8a; /* 藍色 */
    }

    /* タブのデザイン */
    .stTabs [data-baseweb="tab-list"] {
        gap: 15px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #ffffff;
        border-radius: 10px 10px 0 0;
        padding: 12px 25px;
        color: #64748b;
        font-weight: 600;
        border: 1px solid #d1e3f3;
        border-bottom: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1e3a8a;
        color: #ffffff;
    }

    </style>
    """, unsafe_allow_html=True)

# --- 2. バックエンド（スプレッドシート連携） ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
else:
    st.error("Secretsの設定が未完了です。")
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

# --- 3. スマート・タイム・デコーダー ---
def smart_time_parse(t_str):
    """'2100' も '21:00' も適切に変換する魔法の関数"""
    if not t_str: return None
    clean_t = re.sub(r'[^0-9]', '', t_str) # 数字だけ抽出
    
    if len(clean_t) == 3: clean_t = "0" + clean_t # 900 -> 0900
    if len(clean_t) == 4:
        hh, mm = int(clean_t[:2]), int(clean_t[2:])
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hh, mm)
    
    # 既に ':' が入っている場合のフォールバック
    try:
        return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. インターフェース ---

# サイドバー（管理・入力）
with st.sidebar:
    # アイコン表示（塾ロゴに変える場合は、ここに st.image("logo.png") とする）
    if os.path.exists("icon.png"): st.image("icon.png", width=80)
    st.title("業務システム")
    
    st.markdown("### ✍️ 記録の登録")
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="名前を入力")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in:
        f_start_raw = st.text_input("入室 (例:1700)", key="in")
        t_start = smart_time_parse(f_start_raw)
        if t_start: st.markdown(f"<p class='time-preview'>→ {t_start.strftime('%H:%M')}</p>", unsafe_allow_html=True)
    
    with col_out:
        f_end_raw = st.text_input("退室 (例:2130)", key="out")
        t_end = smart_time_parse(f_end_raw)
        if t_end: st.markdown(f"<p class='time-preview'>→ {t_end.strftime('%H:%M')}</p>", unsafe_allow_html=True)
    
    if st.button("記録を保存する"):
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
            st.error("入力内容を確認してください")

    st.markdown("---")
    admin_pass = st.text_input("Admin Password", type="password")
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
            st.info("集計可能なデータがまだありません")
            return
        
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        # トップ3の特別カード
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
    st.info("データがありません。最初の記録を登録しましょう！")
