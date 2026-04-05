import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- 初期設定 ---
# 1. 認証設定
scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# secret.jsonを読み込む
try:
    credentials = Credentials.from_service_account_file('secret.json', scopes=scopes)
    gc = gspread.authorize(credentials)
except FileNotFoundError:
    st.error("エラー: 'secret.json' が見つかりません。ファイル名と保存場所を確認してください。")
    st.stop()

# 2. スプレッドシートのURL（★ここを自分のURLに書き換えてください！）
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1C9xD5xD3ZvGEV6IPuD2_dj9f_oqAIz_v923PMRabBu4/edit?gid=0#gid=0"

# スプレッドシートを開く
try:
    workbook = gc.open_by_url(SPREADSHEET_URL)
    worksheet_main = workbook.worksheet("メイン")
    worksheet_backup = workbook.worksheet("バックアップ")
except Exception as e:
    st.error(f"エラー: スプレッドシートの読み込みに失敗しました。URLやシート名（メイン・バックアップ）を確認してください。詳細: {e}")
    st.stop()

# --- データ読み書き関数 ---
def load_data(sheet):
    data = sheet.get_all_records()
    if data:
        df = pd.DataFrame(data)
        df['日付'] = pd.to_datetime(df['日付'])
        return df
    else:
        return pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])

def save_data(sheet, df):
    sheet.clear()
    if not df.empty:
        save_df = df.copy()
        save_df['日付'] = pd.to_datetime(save_df['日付']).dt.strftime('%Y-%m-%d')
        save_df = save_df.fillna("") # 空欄を安全に処理
        data_to_upload = [save_df.columns.tolist()] + save_df.values.tolist()
        sheet.update(range_name="A1", values=data_to_upload)
    else:
        headers = [['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']]
        sheet.update(range_name="A1", values=headers)

st.title("自習室 利用時間記録＆ランキング")

# --- サイドバー（データ管理） ---
st.sidebar.header("⚙️ データ管理")
st.sidebar.write("※管理用メニューです")

if st.sidebar.button("⚠️ データをリセットする"):
    main_df = load_data(worksheet_main)
    if not main_df.empty:
        save_data(worksheet_backup, main_df) # バックアップに保存
        empty_df = pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）'])
        save_data(worksheet_main, empty_df) # メインを空にする
        st.sidebar.success("データをリセットし、バックアップを作成しました。")
        st.rerun()
    else:
        st.sidebar.warning("リセットするデータがありません。")

if st.sidebar.button("🔄 直前のデータを復元する"):
    backup_df = load_data(worksheet_backup)
    if not backup_df.empty:
        save_data(worksheet_main, backup_df) # メインに上書き
        st.sidebar.success("データを復元しました。")
        st.rerun()
    else:
        st.sidebar.error("復元できるバックアップデータがありません。")

st.sidebar.divider()

# --- メイン画面 ---
df = load_data(worksheet_main)

# --- 記録入力セクション ---
st.header("📝 記録の入力")
with st.form("record_form"):
    col1, col2 = st.columns(2)
    with col1:
        date = st.date_input("日付")
        name = st.text_input("名前")
        grade = st.selectbox("学年", ["小1", "小2", "小3", "小4", "小5", "小6", "中1", "中2", "中3", "高1", "高2", "高3", "既卒/その他"])
    with col2:
        start_time = st.time_input("入室時間")
        end_time = st.time_input("退室時間")
    
    submitted = st.form_submit_button("記録を追加")

    if submitted:
        if name == "":
            st.error("名前を入力してください。")
        else:
            start_dt = datetime.combine(date, start_time)
            end_dt = datetime.combine(date, end_time)
            
            if end_dt < start_dt:
                end_dt = datetime.combine(date + pd.Timedelta(days=1), end_time)
                
            duration = (end_dt - start_dt).total_seconds() / 3600

            new_record = pd.DataFrame([{
                '日付': pd.to_datetime(date),
                '名前': name,
                '学年': grade,
                '入室時間': start_time.strftime('%H:%M'),
                '退室時間': end_time.strftime('%H:%M'),
                '利用時間（時間）': round(duration, 2)
            }])
            
            df = pd.concat([df, new_record], ignore_index=True)
            save_data(worksheet_main, df)
            st.success(f"{name}さん（{grade}）の記録を追加しました。")
            st.rerun()

# --- ランキング表示セクション ---
st.header("🏆 利用時間ランキング")

if not df.empty:
    def create_ranking_table(target_df):
        if target_df.empty:
            return None
        ranking_df = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        ranking_df = ranking_df.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)
        ranking_df.index = ranking_df.index + 1
        ranking_df.index.name = '順位'
        return ranking_df

    tab1, tab2, tab3 = st.tabs(["1ヶ月(月別)", "直近3ヶ月", "累計(全期間)"])

    with tab1:
        df['年月'] = df['日付'].dt.strftime('%Y-%m')
        months = df['年月'].unique().tolist()
        months.sort(reverse=True)
        selected_month = st.selectbox("集計月を選択してください", months)
        
        monthly_df = df[df['年月'] == selected_month]
        ranking_1m = create_ranking_table(monthly_df)
        
        if ranking_1m is not None:
            st.dataframe(ranking_1m, width='stretch')
        else:
            st.write("選択された月の記録はありません。")

    with tab2:
        today = pd.Timestamp.today().normalize()
        three_months_ago = today - pd.Timedelta(days=90)
        recent_3m_df = df[df['日付'] >= three_months_ago]
        
        st.write(f"集計期間: {three_months_ago.strftime('%Y-%m-%d')} 〜 今日")
        ranking_3m = create_ranking_table(recent_3m_df)
        
        if ranking_3m is not None:
            st.dataframe(ranking_3m, width='stretch')
        else:
            st.write("直近3ヶ月の記録はありません。")

    with tab3:
        st.write("記録開始からの全期間の合計です。")
        ranking_all = create_ranking_table(df)
        st.dataframe(ranking_all, width='stretch')

    st.subheader("すべての記録履歴")
    display_df = df.copy()
    display_df['日付'] = display_df['日付'].dt.strftime('%Y-%m-%d')
    if '年月' in display_df.columns:
        display_df = display_df.drop(columns=['年月'])
    st.dataframe(display_df, width='stretch')

else:
    st.write("まだ記録がありません。")
