import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import os

# --- 1. ページ設定とプロフェッショナル・デザイン (CSS) ---
st.set_page_config(page_title="自習室プレミアムランキング", page_icon="icon.png", layout="wide")

st.markdown("""
    <style>
    /* 全体の背景とフォント */
    .stApp { background-color: #f4f7f9; }
    h1, h2, h3 { color: #1e3a8a; font-family: 'Helvetica Neue', sans-serif; }
    
    /* カード風のデザイン */
    .stMetric {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #e5e7eb;
    }
    
    /* ボタンのカスタマイズ */
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        transition: 0.3s;
    }
    
    /* 入力フォームの背景 */
    [data-testid="stForm"] {
        background-color: #ffffff;
        border-radius: 15px;
        padding: 25px;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 認証・スプレッドシート設定 ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
elif os.path.exists('secret.json'):
    credentials = Credentials.from_service_account_file('secret.json', scopes=scopes)
else:
    st.error("認証設定が不足しています。")
    st.stop()

gc = gspread.authorize(credentials)
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit"

@st.cache_data(ttl=60)
def load_data():
    try:
        workbook = gc.open_by_url(SPREADSHEET_URL)
        worksheet = workbook.worksheet("メイン")
        data = worksheet.get_all_records()
        if not data: return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])
        df = pd.DataFrame(data)
        df['日付'] = pd.to_datetime(df['日付'])
        return df
    except: return pd.DataFrame()

def save_to_gs(df, sheet_name="メイン"):
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet = workbook.worksheet(sheet_name)
    worksheet.clear()
    if not df.empty:
        save_df = df.copy()
        save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("")
        data_to_upload = [save_df.columns.tolist()] + save_df.values.tolist()
        worksheet.update(range_name="A1", values=data_to_upload)
    else:
        worksheet.update(range_name="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])

# --- 3. サイドバー：入力と管理者設定 ---
with st.sidebar:
    # アイコン表示
    if os.path.exists("icon.png"): st.image("icon.png", width=100)
    st.title("Study Room Admin")
    
    # 記録入力フォーム
    st.markdown("### ✍️ 利用記録")
    with st.form("record_form", clear_on_submit=True):
        f_date = st.date_input("日付", datetime.now())
        f_name = st.text_input("名前")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        f_grade = st.selectbox("学年", grades)
        f_start = st.time_input("入室", datetime.strptime("17:00", "%H:%M"))
        f_end = st.time_input("退室", datetime.strptime("21:00", "%H:%M"))
        
        if st.form_submit_button("この内容で登録する"):
            if f_name:
                start_dt = datetime.combine(f_date, f_start)
                end_dt = datetime.combine(f_date, f_end)
                if end_dt < start_dt: end_dt += timedelta(days=1)
                duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                
                df = load_data()
                new_data = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': f_start.strftime('%H:%M'), '退室時間': f_end.strftime('%H:%M'), '利用時間（時間）': duration}])
                df = pd.concat([df, new_data], ignore_index=True)
                save_to_gs(df)
                st.success(f"登録完了: {f_name}さん")
                st.cache_data.clear()
                st.rerun()
    
    st.markdown("---")
    # 管理者専用メニュー
    st.markdown("### 🔐 管理者設定")
    admin_password = st.text_input("パスワードを入力", type="password")
    
    # パスワードが合っている時だけボタンを出す（パスワードは 'admin123' に設定しています）
    if admin_password == "admin123":
        st.warning("管理者認証に成功しました")
        if st.button("🚨 データをリセット"):
            current_df = load_data()
            save_to_gs(current_df, "バックアップ")
            save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
            st.cache_data.clear()
            st.rerun()
        if st.button("⏪ データを復元"):
            workbook = gc.open_by_url(SPREADSHEET_URL)
            backup_df = pd.DataFrame(workbook.worksheet("バックアップ").get_all_records())
            save_to_gs(backup_df, "メイン")
            st.cache_data.clear()
            st.rerun()
    elif admin_password != "":
        st.error("パスワードが違います")

# --- 4. メイン画面：ランキングと統計 ---
st.title("🏆 自習室利用ランキング")
df = load_data()

if not df.empty:
    # 統計タブ
    tab1, tab2, tab3 = st.tabs(["📊 今月の記録", "逆転狙い！直近3ヶ月", "👑 殿堂入り（全期間）"])
    
    def display_leaderboard(target_df):
        if target_df.empty:
            st.info("集計対象のデータがまだありません。")
            return
            
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        # トップ3の特別表示
        st.markdown("### 🏆 Top 3 Students")
        top_cols = st.columns(3)
        medals = ["🥇 Gold", "🥈 Silver", "🥉 Bronze"]
        for i in range(min(3, len(agg))):
            with top_cols[i]:
                st.metric(label=f"{medals[i]}: {agg.iloc[i]['名前']} ({agg.iloc[i]['学年']})", 
                          value=f"{agg.iloc[i]['利用時間（時間）']}時間")
        
        st.markdown("### 📜 順位表")
        st.dataframe(agg, use_container_width=True, column_config={
            "利用時間（時間）": st.column_config.ProgressColumn("学習時間", format="%.2f h", min_value=0, max_value=float(agg['利用時間（時間）'].max()))
        })

    with tab1:
        month_df = df[df['日付'].dt.month == datetime.now().month]
        display_leaderboard(month_df)
    with tab2:
        three_months_ago = datetime.now() - timedelta(days=90)
        recent_df = df[df['日付'] >= three_months_ago]
        display_leaderboard(recent_df)
    with tab3:
        display_leaderboard(df)

    with st.expander("🕒 全ての利用履歴を詳しく見る"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True)
else:
    st.info("自習室の利用を開始して、最初の記録を登録しましょう！")        worksheet.update(range_name="A1", values=[['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']])

# --- メイン画面 ---
st.title("🥇 自習室 利用時間ランキング")
df = load_data_from_gs()

# サイドバー
with st.sidebar:
    st.header("📋 新規記録")
    with st.form("record_form", clear_on_submit=True):
        f_date = st.date_input("日付", datetime.now())
        f_name = st.text_input("名前")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        f_grade = st.selectbox("学年", grades)
        col_t1, col_t2 = st.columns(2)
        f_start = col_t1.time_input("入室", datetime.strptime("17:00", "%H:%M"))
        f_end = col_t2.time_input("退室", datetime.strptime("21:00", "%H:%M"))
        
        if st.form_submit_button("記録を保存"):
            if f_name:
                start_dt = datetime.combine(f_date, f_start)
                end_dt = datetime.combine(f_date, f_end)
                if end_dt < start_dt: end_dt += timedelta(days=1)
                duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                
                new_data = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': f_start.strftime('%H:%M'), '退室時間': f_end.strftime('%H:%M'), '利用時間（時間）': duration}])
                df = pd.concat([df, new_data], ignore_index=True)
                save_to_gs(df)
                st.success(f"{f_name}さんの記録を保存しました")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("名前を入力してください")

    st.divider()
    st.header("⚙️ 管理メニュー")
    if st.button("復元（バックアップから戻す）"):
        workbook = gc.open_by_url(SPREADSHEET_URL)
        backup_df = pd.DataFrame(workbook.worksheet("バックアップ").get_all_records())
        save_to_gs(backup_df, "メイン")
        st.cache_data.clear()
        st.rerun()

# メインコンテンツ
if not df.empty:
    tabs = st.tabs(["🗓 今月", "直近3ヶ月", "🏆 全期間"])
    
    def render_ranking(target_df):
        if target_df.empty:
            st.info("データがありません")
            return
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        cols = st.columns(3)
        medals = ["🥇 1位", "🥈 2位", "🥉 3位"]
        for i in range(min(3, len(agg))):
            with cols[i]:
                st.metric(label=f"{medals[i]}：{agg.iloc[i]['名前']}さん", value=f"{agg.iloc[i]['利用時間（時間）']}h")
        st.write("---")
        st.dataframe(agg, use_container_width=True)

    with tabs[0]:
        this_month_df = df[df['日付'].dt.month == datetime.now().month]
        render_ranking(this_month_df)
    with tabs[1]:
        recent_df = df[df['日付'] >= (datetime.now() - timedelta(days=90))]
        render_ranking(recent_df)
    with tabs[2]:
        render_ranking(df)

    with st.expander("📝 履歴一覧"):
        st.table(df.sort_values(by='日付', ascending=False))
else:
    st.info("データがありません。")
