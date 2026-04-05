import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成（システムUIのオーバーライド） ---
st.set_page_config(page_title="Study Room Analytics", page_icon="icon.png", layout="wide")

st.markdown("""
<style>
    /* 不要なシステムUIを非表示 */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}

    /* アプリ全体のデザイン */
    .stApp {
        background-color: #F8FAFC;
        font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif;
    }

    /* メインタイトル */
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #0F172A;
        margin-bottom: 25px;
        padding-bottom: 15px;
        border-bottom: 3px solid #E2E8F0;
    }

    /* 部門ごとのサブタイトル */
    .section-title {
        font-size: 1.5rem;
        font-weight: 700;
        color: #1E293B;
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding-left: 10px;
        border-left: 5px solid #3B82F6;
    }

    /* サイドバー */
    [data-testid="stSidebar"] { background-color: #1E293B; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {
        color: #F8FAFC !important;
    }

    /* データフレーム（表）のヘッダー背景色 */
    [data-testid="stDataFrame"] table th { background-color: #F1F5F9 !important; color: #334155 !important; }

    /* 印刷時の専用スタイル */
    @media print {
        header, footer, [data-testid="stSidebar"], div.stButton, .stTabs [data-baseweb="tab-list"], [data-testid="stExpander"] {
            display: none !important;
        }
        .stApp { background-color: white !important; }
        .print-area { display: block !important; }
        .section-title { color: black !important; border-left: none; border-bottom: 2px solid black; }
    }
</style>
""", unsafe_allow_html=True)

# --- 2. バックエンド設定 ---
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
if "GCP_SERVICE_ACCOUNT" in st.secrets:
    secret_data = st.secrets["GCP_SERVICE_ACCOUNT"]
    service_account_info = json.loads(secret_data) if isinstance(secret_data, str) else dict(secret_data)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
else:
    st.error("システムエラー: Secrets設定がありません")
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

# --- 3. 時刻フォーマット関数（1900 -> 19:00 の魔法） ---
if "in_time" not in st.session_state: st.session_state.in_time = ""
if "out_time" not in st.session_state: st.session_state.out_time = ""

def auto_format_times():
    for key in ["in_time", "out_time"]:
        val = st.session_state[key]
        if not val: continue
        if ":" in val: continue # 既にコロンがあれば何もしない
        clean = re.sub(r'[^0-9]', '', str(val))
        if len(clean) == 3: clean = "0" + clean
        if len(clean) == 4:
            st.session_state[key] = f"{clean[:2]}:{clean[2:]}"

def parse_final_time(t_str):
    try: return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. ユーザーインターフェース（サイドバー） ---
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=60)
    
    st.markdown("### 📝 ENTRY PANEL")
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="山田 太郎")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in:
        st.text_input("入室", placeholder="19:00", key="in_time", on_change=auto_format_times)
    with col_out:
        st.text_input("退室", placeholder="21:30", key="out_time", on_change=auto_format_times)
    
    # 入力欄のすぐ下に時間をプレビュー表示
    disp_in = st.session_state.in_time if st.session_state.in_time else "--:--"
    disp_out = st.session_state.out_time if st.session_state.out_time else "--:--"
    st.markdown(f"<div style='color: #94A3B8; font-size: 0.9rem; margin-top: -10px; margin-bottom: 15px;'>🕒 確認: {disp_in} ～ {disp_out}</div>", unsafe_allow_html=True)
    
    if st.button("記録を保存する", type="primary", use_container_width=True):
        t_start = parse_final_time(st.session_state.in_time)
        t_end = parse_final_time(st.session_state.out_time)
        
        if f_name and t_start and t_end:
            start_dt = datetime.combine(f_date, t_start)
            end_dt = datetime.combine(f_date, t_end)
            if end_dt < start_dt: end_dt += timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 3600, 2)
            
            df = load_data()
            new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name, '学年': f_grade, '入室時間': st.session_state.in_time, '退室時間': st.session_state.out_time, '利用時間（時間）': duration}])
            df = pd.concat([df, new_row], ignore_index=True)
            save_to_gs(df)
            
            st.session_state.in_time = ""
            st.session_state.out_time = ""
            st.success(f"{f_name}さんの記録を保存しました。")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("入力内容に誤りがあります（時刻は 1900 または 19:00）")

    st.markdown("<hr>", unsafe_allow_html=True)
    
    # --- パスワードなしで使える個別データ削除 ---
    st.markdown("#### 🗑️ 直近の記録を取り消す")
    df_for_delete = load_data()
    if not df_for_delete.empty:
        options = [("-1", "-- 取り消す記録を選択 --")]
        # 直近のデータ（最大30件）を削除候補として表示
        recent_indices = reversed(df_for_delete.index[-30:])
        for i in recent_indices:
            row = df_for_delete.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            disp = f"{d_str} | {row['名前']} ({row['入室時間']}-{row['退室時間']})"
            options.append((str(i), disp))
        
        selected_del = st.selectbox("間違えた記録を消す", options, format_func=lambda x: x[1])
        if st.button("🗑️ この記録を削除", use_container_width=True):
            if selected_del[0] != "-1":
                df_for_delete = df_for_delete.drop(int(selected_del[0])).reset_index(drop=True)
                save_to_gs(df_for_delete)
                st.success("削除しました。")
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("記録を選択してください。")
    else:
        st.info("削除できるデータがありません。")

    st.markdown("<hr>", unsafe_allow_html=True)
    
    # --- 管理者専用：全データリセット ---
    st.markdown("#### 🚨 システム全体リセット")
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "admin123":
        if st.button("全データをリセット", use_container_width=True):
            save_to_gs(load_data(), "バックアップ")
            save_to_gs(pd.DataFrame(columns=['日付', '名前', '学年', '入室時間', '退室時間', '利用時間（時間）']), "メイン")
            st.cache_data.clear()
            st.rerun()

# --- 5. メインパネル（部門別ランキング） ---
st.markdown("<div class='main-title'>🏆 塾生学習時間ランキング</div>", unsafe_allow_html=True)
df = load_data()

# オリジナルデザインのトップ3カード描画関数
def render_premium_cards(agg):
    if agg.empty: return
    html = '<div style="display: flex; gap: 20px; margin-bottom: 30px; flex-wrap: wrap;">'
    medals = [("🥇 1位", "#3B82F6"), ("🥈 2位", "#64748B"), ("🥉 3位", "#F59E0B")]
    
    for i in range(min(3, len(agg))):
        rank_text, border_color = medals[i]
        name = agg.iloc[i]['名前']
        grade = agg.iloc[i]['学年']
        time_val = agg.iloc[i]['利用時間（時間）']
        
        html += f"<div style='flex: 1; min-width: 250px; background: #FFFFFF; padding: 25px; border-radius: 12px; border-left: 6px solid {border_color}; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border-top: 1px solid #E2E8F0; border-right: 1px solid #E2E8F0; border-bottom: 1px solid #E2E8F0;'>"
        html += f"<div style='font-size: 0.95rem; color: #64748B; font-weight: bold; margin-bottom: 8px;'>{rank_text} / {grade}</div>"
        html += f"<div style='font-size: 2.2rem; font-weight: 800; color: #0F172A; margin-bottom: 12px;'>{name} <span style='font-size: 1.2rem; font-weight: 600; color: #475569;'>さん</span></div>"
        html += f"<div style='display: inline-block; background-color: #ECFDF5; color: #059669; padding: 4px 16px; border-radius: 20px; font-weight: 700; font-size: 1.1rem;'>↑ {time_val:.2f} 時間</div>"
        html += "</div>"
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

# 部門別にランキングを描画する関数
def render_section_ranking(full_agg, target_grades, section_title, icon):
    section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
    st.markdown(f"<div class='section-title'>{icon} {section_title}</div>", unsafe_allow_html=True)
    
    if section_df.empty:
        st.info(f"{section_title}のデータはまだありません。")
        return
        
    render_premium_cards(section_df)
    section_df.index += 1
    st.dataframe(section_df, use_container_width=True, hide_index=True, column_config={
        "名前": st.column_config.TextColumn("氏名"),
        "学年": st.column_config.TextColumn("学年"),
        "利用時間（時間）": st.column_config.ProgressColumn("トータル学習時間", format="%.2f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max()))
    })

# 印刷用テーブル描画関数
def render_printable_table(full_agg, target_grades, title):
    section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
    if section_df.empty: return
    
    print_html = f"<h3 style='color: black; margin-top: 30px; border-bottom: 2px solid #000; padding-bottom: 5px;'>{title}</h3>"
    print_html += "<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; color: black; margin-bottom: 20px; font-size: 0.9rem;'>"
    print_html += "<tr><th style='border: 1px solid #000; padding: 8px; background-color: #f1f5f9; text-align: center; width: 15%;'>順位</th><th style='border: 1px solid #000; padding: 8px; background-color: #f1f5f9; width: 45%;'>氏名</th><th style='border: 1px solid #000; padding: 8px; background-color: #f1f5f9; text-align: center; width: 15%;'>学年</th><th style='border: 1px solid #000; padding: 8px; background-color: #f1f5f9; text-align: right; width: 25%;'>学習時間</th></tr>"
    for i, row in section_df.iterrows():
        print_html += f"<tr><td style='border: 1px solid #000; padding: 6px; text-align: center;'>{i+1}位</td><td style='border: 1px solid #000; padding: 6px; font-weight: bold;'>{row['名前']}</td><td style='border: 1px solid #000; padding: 6px; text-align: center;'>{row['学年']}</td><td style='border: 1px solid #000; padding: 6px; text-align: right;'>{row['利用時間（時間）']:.2f} h</td></tr>"
    print_html += "</table>"
    st.markdown(print_html, unsafe_allow_html=True)

if not df.empty:
    tab1, tab2, tab3, tab4 = st.tabs(["🗓 今月の集計", "🔥 直近3ヶ月", "👑 殿堂入り（累計）", "🖨️ 印刷用画面"])
    
    elem_grades = [f"小{i}" for i in range(1, 7)]
    jh_grades = [f"中{i}" for i in range(1, 4)]
    hs_grades = [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    
    def get_agg_data(target_df):
        if target_df.empty: return pd.DataFrame()
        agg = target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index()
        return agg.sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)

    agg_month = get_agg_data(df[df['日付'].dt.month == datetime.now().month])
    agg_3months = get_agg_data(df[df['日付'] >= (datetime.now() - timedelta(days=90))])
    agg_all = get_agg_data(df)

    for tab, agg_data in zip([tab1, tab2, tab3], [agg_month, agg_3months, agg_all]):
        with tab:
            if agg_data.empty: 
                st.info("データがありません。")
            else:
                render_section_ranking(agg_data, elem_grades, "小学生の部", "🎒")
                render_section_ranking(agg_data, jh_grades, "中学生の部", "📓")
                render_section_ranking(agg_data, hs_grades, "高校生・その他の部", "🎓")

    with tab4:
        st.markdown("### 🖨️ 張り出し用ランキング印刷")
        st.info("ブラウザの印刷機能（`Ctrl + P` または `Cmd + P`）を利用してください。白黒で表のみが綺麗に出力されます。")
        st.markdown("<div class='print-area'>", unsafe_allow_html=True)
        
        st.markdown("<h2 style='text-align: center; border-bottom: 3px solid black; padding-bottom: 10px;'>🏆 今月の学習時間ランキング</h2>", unsafe_allow_html=True)
        render_printable_table(agg_month, elem_grades, "🎒 小学生の部")
        render_printable_table(agg_month, jh_grades, "📓 中学生の部")
        render_printable_table(agg_month, hs_grades, "🎓 高校生・その他の部")
        
        st.markdown("<br><br><h2 style='text-align: center; border-bottom: 3px solid black; padding-bottom: 10px;'>🔥 直近3ヶ月 学習時間ランキング</h2>", unsafe_allow_html=True)
        render_printable_table(agg_3months, elem_grades, "🎒 小学生の部")
        render_printable_table(agg_3months, jh_grades, "📓 中学生の部")
        render_printable_table(agg_3months, hs_grades, "🎓 高校生・その他の部")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("📝 過去のすべての履歴を確認する"):
        st.dataframe(df.sort_values(by='日付', ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("データがありません。")
