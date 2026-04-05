import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import os

# --- 1. ページ設定（モダンなアイコンとワイドレイアウト） ---
st.set_page_config(page_title="自習室プレミアムランキング", page_icon="icon.png", layout="wide")

# プロフェッショナルなデザインを適用 (CSS)
st.markdown("""
    <style>
    .stApp { background-color: #f4f7f9; }
    h1, h2, h3 { color: #1e3a8a; font-family: 'Helvetica Neue', sans-serif; }
    .stMetric {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #e5e7eb;
    }
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
    st.error("認証設定（Secrets）が不足しています。")
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
    except: return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])

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

# --- 3. サイドバー設定 ---
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=100)
    st.title("Admin Menu")
    
    # 記録入力
    st.markdown("### ✍️ 利用記録の登録")
    with st.form("record_form", clear_on_submit=True):
        f_date = st.date_input("日付", datetime.now())
        f_name = st.text_input("名前")
        grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
        f_grade = st.selectbox("学年", grades)
        f_start = st.time_input("入室", datetime.strptime("17:00", "%H:%M"))
        f_end = st.time_input("退室", datetime.strptime("21:00", "%H:%M"))
        
        if st.form_submit_button("登録する"):
            if f_name:
                start_dt = datetime.combine(f_date, f_start)
                end_dt = datetime.combine(f_date, f_end)
                if end_dt < start_dt: end_dt += timedelta(days=1)
                duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
                
                df = load_data()
                new_data = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': f_start.strftime('%H:%M'), '退室時間': f_end.strftime('%H:%M'), '利用時間（時間）': duration}])
                df = pd.concat([df, new_data], ignore_index=True)
                save_to_gs(df)
                st.success(f"登録完了！")
                st.cache_data.clear()
                st.rerun()

    st.divider()
    # 管理者用パスワード
    st.markdown("### 🔐 管理者認証")
    admin_password = st.text_input("Password", type="password")
    if admin_password == "admin123":
        st.success("認証済み")
        if st.button("🚨 全データをリセット"):
            current_df = load_data()
            save_to_gs(current_df, "バックアップ")
            save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
            st.cache_data.clear()
            st.rerun()
        if st.button("⏪ バックアップから復元"):
            workbook = gc.open_by_url(SPREADSHEET_URL)
            backup_df = pd.DataFrame(workbook.worksheet("バックアップ").get_all_records())
            save_to_gs(backup_df, "メイン")
            st.cache_data.clear()
            st.rerun()

# --- 4. メイン画面 ---
st.title("🏆 自習室利用ランキング")
df = load_data()

if not df.empty:
    tab1, tab2, tab3 = st.tabs(["🗓 今月", "🔥 直近3ヶ月", "👑 殿堂入り"])
    
    def display_leaderboard(target_df):
        if target_df.empty:
            st.info("集計対象のデータがありません。")
            return
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        agg = agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        agg.index += 1
        
        # トップ3表示
        st.markdown("#### 🥇 今のトップ3")
        top_cols = st.columns(3)
        medals = ["🥇 1位", "🥈 2位", "🥉 3位"]
        for i in range(min(3, len(agg))):
            with top_cols[i]:
                st.metric(label=f"{medals[i]}: {agg.iloc[i]['名前']} ({agg.iloc[i]['学年']})", value=f"{agg.iloc[i]['利用時間（時間）']}時間")
        
        # 順位表（プログレスバー付き）
        st.dataframe(agg, use_container_width=True, column_config={
            "利用時間（時間）": st.column_config.ProgressColumn("学習量", format="%.2f h", min_value=0, max_value=float(agg['利用時間（時間）'].max()))
        })

    with tab1:
        display_leaderboard(df[df['日付'].dt.month == datetime.now().month])
    with tab2:
        display_leaderboard(df[df['日付'] >= (datetime.now() - timedelta(days=90))])
    with tab3:
        display_leaderboard(df)

    with st.expander("📝 詳細履歴"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True)
else:
    st.info("記録がまだありません。サイドバーから入力してください。")
