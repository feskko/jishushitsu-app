import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re

# --- 1. ページ構成（TKGブルーホライズン・コンセプト） ---
st.set_page_config(page_title="TKG Study Room Analytics", page_icon="icon.png", layout="wide")

st.markdown("""
<style>
    /* ========== システムUIの完全非表示 ========== */
    #MainMenu, header, footer, [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}

    /* ========== 全体テーマ（知的で清潔感のある背景） ========== */
    .stApp {
        background-color: #F4F7FB;
        font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif;
    }

    /* ========== メインタイトル（TKGネイビー） ========== */
    .main-title {
        font-size: 2.4rem;
        font-weight: 900;
        color: #0A2B56;
        letter-spacing: 2px;
        margin-bottom: 30px;
        padding-bottom: 15px;
        border-bottom: 4px solid #E2E8F0;
        position: relative;
    }
    .main-title::after {
        content: '';
        position: absolute;
        left: 0;
        bottom: -4px;
        width: 120px;
        height: 4px;
        background: linear-gradient(90deg, #0A2B56, #005BAB);
    }

    /* ========== 部門ごとのサブタイトル ========== */
    .section-title {
        font-size: 1.6rem;
        font-weight: 800;
        color: #0A2B56;
        margin-top: 2.5rem;
        margin-bottom: 1.5rem;
        padding-left: 12px;
        border-left: 6px solid #005BAB;
        display: flex;
        align-items: center;
        gap: 10px;
    }

    /* ========== サイドバー（プロフェッショナルな濃紺） ========== */
    [data-testid="stSidebar"] { 
        background-color: #0A2B56; 
        box-shadow: 2px 0 10px rgba(0,0,0,0.1);
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {
        color: #FFFFFF !important;
        font-weight: 600;
    }
    
    /* 入力フォームの洗練 */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        border-radius: 6px !important;
        border: 1px solid #CBD5E1 !important;
        box-shadow: inset 0 1px 2px rgba(0,0,0,0.05);
    }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div {
        color: #1E293B !important;
        font-weight: 700;
        font-size: 1.05rem;
    }

    /* ========== ボタンデザイン（重なり合う青のグラデーション） ========== */
    .stButton>button {
        background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%);
        color: #FFFFFF !important;
        font-weight: bold;
        font-size: 1.1rem;
        letter-spacing: 1px;
        border-radius: 8px;
        border: none;
        height: 3.5rem;
        width: 100%;
        box-shadow: 0 4px 6px -1px rgba(0, 91, 171, 0.3);
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 12px -2px rgba(0, 91, 171, 0.4);
        background: linear-gradient(135deg, #0C3469 0%, #006DCC 100%);
    }

    /* ========== タブのデザイン ========== */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #E2E8F0;
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
        color: #475569;
        font-weight: 700;
        border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0A2B56 !important;
        color: #FFFFFF !important;
    }

    /* ========== 印刷用（白黒・インク節約・美しい表） ========== */
    @media print {
        @page { margin: 10mm; size: A4 portrait; }
        header, footer, [data-testid="stSidebar"], div.stButton, .stTabs [data-baseweb="tab-list"], [data-testid="stExpander"] { display: none !important; }
        .stApp { background-color: #FFFFFF !important; }
        .print-area { display: block !important; }
        .section-title { color: #000000 !important; border-left: none; border-bottom: 2px solid #000000; padding-left: 0; }
        * { box-shadow: none !important; border-radius: 0 !important; background: transparent !important; color: #000 !important; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #000 !important; padding: 8px; }
        th { background-color: #EEEEEE !important; -webkit-print-color-adjust: exact; }
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

# --- 3. 時刻フォーマット（1900 -> 19:00 の魔法） ---
if "in_time" not in st.session_state: st.session_state.in_time = ""
if "out_time" not in st.session_state: st.session_state.out_time = ""

def auto_format_times():
    for key in ["in_time", "out_time"]:
        val = st.session_state[key]
        if not val: continue
        if ":" in val: continue
        clean = re.sub(r'[^0-9]', '', str(val))
        if len(clean) == 3: clean = "0" + clean
        if len(clean) == 4:
            st.session_state[key] = f"{clean[:2]}:{clean[2:]}"

def parse_final_time(t_str):
    try: return datetime.strptime(t_str, "%H:%M").time()
    except: return None

# --- 4. ユーザーインターフェース（サイドバー） ---
with st.sidebar:
    if os.path.exists("icon.png"): st.image("icon.png", width=70)
    
    st.markdown("<h2 style='color:white; margin-bottom: 20px;'>TKG RECORD PANEL</h2>", unsafe_allow_html=True)
    
    f_date = st.date_input("利用日", datetime.now())
    f_name = st.text_input("氏名", placeholder="山田 太郎")
    grades = [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]
    f_grade = st.selectbox("学年", grades)
    
    col_in, col_out = st.columns(2)
    with col_in:
        st.text_input("入室", placeholder="19:00", key="in_time", on_change=auto_format_times)
    with col_out:
        st.text_input("退室", placeholder="21:30", key="out_time", on_change=auto_format_times)
    
    disp_in = st.session_state.in_time if st.session_state.in_time else "--:--"
    disp_out = st.session_state.out_time if st.session_state.out_time else "--:--"
    st.markdown(f"<div style='background-color: rgba(255,255,255,0.1); padding: 8px; border-radius: 6px; color: #E2E8F0; font-size: 0.95rem; text-align: center; margin-top: -10px; margin-bottom: 20px; font-weight: bold;'>🕒 {disp_in} 〜 {disp_out}</div>", unsafe_allow_html=True)
    
    if st.button("記録を登録する", use_container_width=True):
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
            st.success(f"✓ {f_name}さんの記録を保存しました。")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("入力内容に誤りがあります（時刻は 1900 または 19:00）")

    st.markdown("<hr style='border-color: rgba(255,255,255,0.2);'>", unsafe_allow_html=True)
    
    st.markdown("#### 🗑️ 直近の記録を取り消す")
    df_for_delete = load_data()
    if not df_for_delete.empty:
        options = [("-1", "-- 取り消す記録を選択 --")]
        recent_indices = reversed(df_for_delete.index[-30:])
        for i in recent_indices:
            row = df_for_delete.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            disp = f"{d_str} | {row['名前']} ({row['入室時間']}-{row['退室時間']})"
            options.append((str(i), disp))
        
        selected_del = st.selectbox("間違えた記録を消す", options, format_func=lambda x: x[1], label_visibility="collapsed")
        if st.button("データを削除", use_container_width=True):
            if selected_del[0] != "-1":
                df_for_delete = df_for_delete.drop(int(selected_del[0])).reset_index(drop=True)
                save_to_gs(df_for_delete)
                st.success("削除しました。")
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("記録を選択してください。")
    
    st.markdown("<div style='text-align: center; font-size: 0.75rem; color: #94A3B8; margin-top: 40px;'>Tokyo Kobetsu Shido Gakuin<br>Study Room System v3.0</div>", unsafe_allow_html=True)

# --- 5. メインパネル（部門別ランキング） ---
st.markdown("<div class='main-title'>STUDY HOURS RANKING</div>", unsafe_allow_html=True)
df = load_data()

# 究極の高級感：トップ3カード
def render_premium_cards(agg):
    if agg.empty: return
    html = '<div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">'
    medals = [("1st", "🥇", "#C9B037", "linear-gradient(135deg, #FFFFFF 0%, #FFFDF0 100%)"), 
              ("2nd", "🥈", "#B4B4B4", "linear-gradient(135deg, #FFFFFF 0%, #F8F9FA 100%)"), 
              ("3rd", "🥉", "#AD8A56", "linear-gradient(135deg, #FFFFFF 0%, #FCF9F5 100%)")]
    
    for i in range(min(3, len(agg))):
        rank_text, icon, border_color, bg_grad = medals[i]
        name = agg.iloc[i]['名前']
        grade = agg.iloc[i]['学年']
        time_val = agg.iloc[i]['利用時間（時間）']
        
        # HTMLを1行にまとめることでStreamlitのMarkdown誤作動を防止します
        html += f"<div style='flex: 1; min-width: 250px; background: {bg_grad}; padding: 25px; border-radius: 16px; box-shadow: 0 10px 15px -3px rgba(10, 43, 86, 0.08); border: 1px solid #E2E8F0; border-top: 5px solid {border_color};'>"
        html += f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><span style='font-size: 1rem; color: #64748B; font-weight: 800; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div>"
        html += f"<div style='font-size: 0.9rem; color: #0A2B56; font-weight: bold; margin-bottom: 5px;'>{grade}</div>"
        html += f"<div style='font-size: 2.2rem; font-weight: 900; color: #0F172A; margin-bottom: 15px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div>"
        html += f"<div style='display: inline-block; background-color: #F1F5F9; color: #0A2B56; padding: 6px 16px; border-radius: 8px; font-weight: 800; font-size: 1.2rem; border: 1px solid #E2E8F0;'>{time_val:.2f} <span style='font-size: 0.9rem;'>HOURS</span></div>"
        html += "</div>"
        
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

# 部門別にランキングを描画
def render_section_ranking(full_agg, target_grades, section_title):
    section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
    st.markdown(f"<div class='section-title'>{section_title}</div>", unsafe_allow_html=True)
    
    if section_df.empty:
        st.info("集計データがありません。")
        return
        
    render_premium_cards(section_df)
    section_df.index += 1
    st.dataframe(section_df, use_container_width=True, hide_index=True, column_config={
        "名前": st.column_config.TextColumn("氏名"),
        "学年": st.column_config.TextColumn("学年"),
        "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.2f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max()))
    })

# 印刷用テーブル描画
def render_printable_table(full_agg, target_grades, title):
    section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
    if section_df.empty: return
    
    print_html = f"<h3 style='color: black; margin-top: 30px; border-bottom: 2px solid #000; padding-bottom: 5px; font-size: 18px;'>{title}</h3>"
    print_html += "<table style='width: 100%; border-collapse: collapse; font-family: sans-serif; color: black; margin-bottom: 20px; font-size: 14px;'>"
    print_html += "<tr><th style='border: 1px solid #000; padding: 8px; text-align: center; width: 12%;'>順位</th><th style='border: 1px solid #000; padding: 8px; width: 48%;'>氏名</th><th style='border: 1px solid #000; padding: 8px; text-align: center; width: 15%;'>学年</th><th style='border: 1px solid #000; padding: 8px; text-align: right; width: 25%;'>学習時間</th></tr>"
    for i, row in section_df.iterrows():
        print_html += f"<tr><td style='border: 1px solid #000; padding: 6px; text-align: center;'>{i+1}</td><td style='border: 1px solid #000; padding: 6px; font-weight: bold;'>{row['名前']}</td><td style='border: 1px solid #000; padding: 6px; text-align: center;'>{row['学年']}</td><td style='border: 1px solid #000; padding: 6px; text-align: right;'>{row['利用時間（時間）']:.2f} h</td></tr>"
    print_html += "</table>"
    st.markdown(print_html, unsafe_allow_html=True)

if not df.empty:
    tab1, tab2, tab3, tab4 = st.tabs(["🗓 今月の集計", "🔥 直近3ヶ月", "👑 殿堂入り（全期間）", "🖨️ 張り出し印刷"])
    
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
            if agg_data.empty: st.info("データがありません。")
            else:
                render_section_ranking(agg_data, elem_grades, "小学生の部")
                render_section_ranking(agg_data, jh_grades, "中学生の部")
                render_section_ranking(agg_data, hs_grades, "高校生・その他")

    with tab4:
        st.info("ブラウザの印刷機能（Ctrl+P / Cmd+P）を使用してください。自動的にインクを節約した白黒の美しい表が出力されます。")
        st.markdown("<div class='print-area'>", unsafe_allow_html=True)
        
        st.markdown("<h2 style='text-align: center; margin-bottom: 0;'>🏆 学習時間ランキング（今月）</h2>", unsafe_allow_html=True)
        render_printable_table(agg_month, elem_grades, "🎒 小学生の部")
        render_printable_table(agg_month, jh_grades, "📓 中学生の部")
        render_printable_table(agg_month, hs_grades, "🎓 高校生・その他")
        
        st.markdown("<div style='page-break-before: always;'></div>", unsafe_allow_html=True)
        
        st.markdown("<h2 style='text-align: center; margin-bottom: 0; margin-top: 20px;'>🔥 学習時間ランキング（直近3ヶ月）</h2>", unsafe_allow_html=True)
        render_printable_table(agg_3months, elem_grades, "🎒 小学生の部")
        render_printable_table(agg_3months, jh_grades, "📓 中学生の部")
        render_printable_table(agg_3months, hs_grades, "🎓 高校生・その他")
        st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("データがありません。")
