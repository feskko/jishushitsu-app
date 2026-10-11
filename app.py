import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import base64
import unicodedata

# 日本時間の「今」を取得
jst_now = datetime.now(timezone.utc) + timedelta(hours=9)

# 講習期間の判定
def is_special_period(dt_date):
    if dt_date is None: return False
    m = dt_date.month
    d = dt_date.day
    # 春季講習: 3/15 〜 4/7
    if (m == 3 and d >= 15) or (m == 4 and d <= 7): return True
    # 夏期講習: 7/15 〜 8/31
    if (m == 7 and d >= 15) or m == 8: return True
    # 冬季講習: 12/1 〜 1/7
    if m == 12 or (m == 1 and d <= 7): return True
    return False

def get_time_slots_for_period(period_str):
    if period_str == "累計": return [f"{h:02d}:00" for h in range(9, 23)]
    try:
        m = int(period_str.split("年")[1].replace("月", ""))
        if m in [1, 3, 4, 7, 8, 12]: return [f"{h:02d}:00" for h in range(9, 23)]
        else: return [f"{h:02d}:00" for h in range(12, 23)]
    except: return [f"{h:02d}:00" for h in range(9, 23)]

def parse_custom_time(t_str):
    if not t_str: return None
    t_str = unicodedata.normalize('NFKC', str(t_str)).strip()
    if t_str == "" or "コマ" in t_str: return None
    if ":" in t_str:
        try: return datetime.strptime(t_str[:5], "%H:%M").time()
        except: return None
    elif t_str.isdigit() and (len(t_str) == 3 or len(t_str) == 4):
        try:
            h, m = int(t_str[:-2]), int(t_str[-2:])
            if 0 <= h <= 23 and 0 <= m <= 59: return datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()
        except: return None
    return None

def calc_duration(in_time, out_time):
    def to_dt(t):
        if isinstance(t, str):
            parsed = parse_custom_time(t)
            return datetime.combine(datetime.today(), parsed) if parsed else None
        elif t is not None: return datetime.combine(datetime.today(), t)
        return None
    dt_in, dt_out = to_dt(in_time), to_dt(out_time)
    if dt_in and dt_out:
        if dt_out >= dt_in: return (dt_out - dt_in).total_seconds() / 3600.0
        else: return ((dt_out + timedelta(days=1)) - dt_in).total_seconds() / 3600.0
    return 0.0

def format_time_input(key):
    val = st.session_state.get(key, "")
    parsed = parse_custom_time(val)
    if parsed: st.session_state[key] = parsed.strftime("%H:%M")

# =====================================================================
# 混雑予測モデル
#   学年グループ別の「罰則付きポアソン回帰」。2026年10月に、過去データでの
#   答え合わせ（時系列の交差検証）をして設定を決めたもの。
#   講習・テスト・休館の日付は、下の「期間の設定」を毎年見直してください。
# =====================================================================

# ---------- 期間の設定（月, 日） ----------
KOSHU_RULE = [("春期講習", (3, 20), (4, 5)), ("夏期講習", (7, 20), (8, 31)), ("冬期講習", (12, 20), (1, 7))]
TEST_RULE = [("1学期中間", (5, 11), (5, 31)), ("1学期期末", (6, 21), (7, 10)), ("2学期中間", (10, 1), (10, 20)),
             ("2学期期末", (11, 11), (11, 30)), ("学年末", (2, 11), (2, 28))]
CLOSED_RULE = [("お盆", (8, 11), (8, 15)), ("年末年始", (12, 29), (1, 3))]  # ほかにGW(5/3〜5/5と振替休日)、講習期間以外の日曜
PERIOD_OVERRIDES = {("夏期講習", 2026): ("2026-07-18", "2026-08-31")}     # 実際の日付が目安とずれた年はここに書く
KOU3_EXAM = ((1, 18), (2, 28))     # 高3の受験期（データがないので倍率は画面で選ぶ）
KOU3_AFTER = ((3, 1), (3, 31))     # 高3の卒業後
TRAIN_START = "2026-06-04"         # これより前は試用期間（コマ記録）なので学習に使わない
SEATS_DEFAULT = 20
KOU3_SCENARIOS = {"そのまま来る": (1.0, 1.0), "受験期は半分・3月はほぼ来ない": (0.5, 0.1), "受験期から来ない": (0.0, 0.0)}

# ---------- モデルの設定（交差検証で選んだ値） ----------
MODEL_SETTINGS = dict(lam_dev=2.0, lam_dow=2.0, lam_trend=20.0, knot_days=28,
                      lam_test=0.05, lam_test_dev=4.0, lam_ramp=2.0, half_life=42)
# 予測の80%範囲: (実際 − 予測) / √(予測+1) の10%点・90%点（何日先かで変わる）
PRED_BANDS = [(7, -1.096, 1.158), (14, -1.050, 1.485), (10**6, -1.014, 1.679)]
GROUPS = ["小学生", "中学生", "高1・高2", "高3・既卒"]
GRADE_GROUP = {**{f"小{i}": "小学生" for i in range(1, 7)}, **{f"中{i}": "中学生" for i in range(1, 4)},
               "高1": "高1・高2", "高2": "高1・高2", "高3": "高3・既卒", "既卒/その他": "高3・既卒"}
OPEN_HOURS = {"平日": range(12, 22), "土曜祝日": range(12, 22), "講習": range(9, 22), "講習日曜": range(9, 21)}
PRED_HOURS = list(range(9, 22))
KOMA_TABLE = {3: ("10:55", "12:15"), 4: ("13:10", "14:30"), 5: ("14:40", "16:00"),
              6: ("17:00", "18:20"), 7: ("18:30", "19:50"), 8: ("20:00", "21:20")}
T0 = pd.Timestamp("2026-05-01")
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _nth_monday(y, m, n):
    first = datetime(y, m, 1)
    return (first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))).date()


def jp_holidays(y):
    """日本の祝日（振替休日・国民の休日を含む）"""
    d = lambda m, dd: datetime(y, m, dd).date()  # noqa: E731
    shunbun = int(20.8431 + 0.242194 * (y - 1980) - int((y - 1980) / 4))
    shubun = int(23.2488 + 0.242194 * (y - 1980) - int((y - 1980) / 4))
    hol = {d(1, 1), _nth_monday(y, 1, 2), d(2, 11), d(2, 23), d(3, shunbun), d(4, 29), d(5, 3), d(5, 4), d(5, 5),
           _nth_monday(y, 7, 3), d(8, 11), _nth_monday(y, 9, 3), d(9, shubun), _nth_monday(y, 10, 2),
           d(11, 3), d(11, 23)}
    for h in sorted(hol):
        if h.weekday() == 6:  # 振替休日
            nxt = h + timedelta(days=1)
            while nxt in hol:
                nxt += timedelta(days=1)
            hol.add(nxt)
    for h in sorted(hol):  # 国民の休日（祝日にはさまれた日）
        mid = h + timedelta(days=1)
        if mid not in hol and (h + timedelta(days=2)) in hol and mid.weekday() != 6:
            hol.add(mid)
    return hol


def _md_date(y, md):
    m, dd = md
    last = (datetime(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return pd.Timestamp(datetime(y, m, min(dd, last)))


def _expand(rule, years):
    out = []
    for name, s, e in rule:
        for y in years:
            a = _md_date(y, s)
            b = _md_date(y + (e < s), e)
            if (name, y) in PERIOD_OVERRIDES:
                a, b = map(pd.Timestamp, PERIOD_OVERRIDES[(name, y)])
            out.append((name, a, b))
    return out


def crowd_calendar(start, end):
    """日ごとの曜日タイプ・休館・講習・テスト期間"""
    c = pd.DataFrame({"date": pd.date_range(start, end)})
    years = range(c.date.min().year - 1, c.date.max().year + 2)
    hol = set().union(*[jp_holidays(y) for y in years])
    c["dow"] = c.date.dt.dayofweek
    c["holiday"] = c.date.dt.date.isin(hol)
    c["koshu"], c["koshu_prog"] = False, 0
    for _, a, b in _expand(KOSHU_RULE, years):
        m = c.date.between(a, b)
        c.loc[m, "koshu"] = True
        c.loc[m, "koshu_prog"] = (c.loc[m, "date"] - a).dt.days
    c["test_name"], c["test_day"] = "", -1
    for name, a, b in _expand(TEST_RULE, years):
        m = c.date.between(a, b)
        c.loc[m, "test_name"] = name
        c.loc[m, "test_day"] = (c.loc[m, "date"] - a).dt.days
    c["test_early"] = c.test_day.between(0, 13)   # テスト期間の最初の2週間
    c["test_late"] = c.test_day >= 14
    c["daytype"] = np.select([c.koshu & (c.dow == 6), c.koshu, c.dow == 6, c.holiday | (c.dow == 5)],
                             ["講習日曜", "講習", "休館", "土曜祝日"], default="平日")
    c["closed_reason"] = np.where(c.daytype == "休館", "日曜", "")
    md = c.date.dt.month * 100 + c.date.dt.day
    gw = md.between(503, 505) | (md.between(506, 506) & c.holiday)
    c.loc[gw, "closed_reason"] = "GW"
    for name, a, b in _expand(CLOSED_RULE, years):
        c.loc[c.date.between(a, b), "closed_reason"] = name
    c["closed"] = c.closed_reason != ""
    c["t"] = (c.date - T0).dt.days
    return c


def _to_min(s, is_exit):
    s = unicodedata.normalize("NFKC", str(s)).strip()
    if s.endswith("コマ"):
        try:
            n = int(s[:-2])
        except ValueError:
            return np.nan
        if n in KOMA_TABLE:
            hm = KOMA_TABLE[n][1 if is_exit else 0]
            return int(hm[:2]) * 60 + int(hm[3:])
        start = 17 * 60 + (n - 6) * 90
        return start + (80 if is_exit else 0)
    parts = s.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return np.nan


def _occupancy(df):
    """利用記録 → 日付×時間帯×学年グループの平均在室人数（1時間の在室分数/60）"""
    v = pd.DataFrame({"date": pd.to_datetime(df["日付"]).dt.normalize(),
                      "group": df["学年"].map(GRADE_GROUP).fillna("不明"),
                      "in": [_to_min(x, False) for x in df["入室時間"]],
                      "out": [_to_min(x, True) for x in df["退室時間"]]})
    v = v[v["in"].notna() & v["out"].notna() & (v["out"] > v["in"]) & (v["out"] - v["in"] <= 13 * 60)]
    hs = np.array(PRED_HOURS) * 60
    ov = np.clip(np.minimum(v["out"].to_numpy()[:, None], hs + 60) - np.maximum(v["in"].to_numpy()[:, None], hs), 0, 60) / 60
    occ = pd.DataFrame(ov, columns=PRED_HOURS)
    occ["date"], occ["group"] = v["date"].to_numpy(), v["group"].to_numpy()
    occ = occ.melt(id_vars=["date", "group"], var_name="hour", value_name="occ")
    occ = occ[occ.occ > 0].groupby(["date", "hour", "group"], as_index=False).occ.sum()
    occ["hour"] = occ["hour"].astype(int)
    # 学年未入力の在室は、同じ日・時間の学年構成（なければ全期間の時間別構成）で按分
    known, unk = occ[occ.group != "不明"], occ[occ.group == "不明"]
    if len(unk):
        base = known.groupby(["hour", "group"]).occ.sum() / known.groupby("hour").occ.sum()
        add = []
        for r in unk.itertuples(index=False):
            same = known[(known.date == r.date) & (known.hour == r.hour)]
            share = same.set_index("group").occ / same.occ.sum() if same.occ.sum() > 0 else base.loc[r.hour]
            add += [(r.date, r.hour, g, r.occ * s) for g, s in share.items()]
        occ = pd.concat([known, pd.DataFrame(add, columns=["date", "hour", "group", "occ"])])
        occ = occ.groupby(["date", "hour", "group"], as_index=False).occ.sum()
    return occ, set(v["date"])


def _rows_for(cal):
    days = cal[~cal.closed]
    rows = [(d.date, h, g) for d in days.itertuples() for h in OPEN_HOURS[d.daytype] for g in GROUPS]
    return pd.DataFrame(rows, columns=["date", "hour", "group"]).merge(cal, on="date")


def _obj(s):
    return s.astype(str).to_numpy(dtype=object)


class CrowdModel:
    """log(平均在室人数) = 曜日タイプ×時間帯 + 学年ごとのずれ + 曜日 + 学年別トレンド
                         + 講習中の盛り上がり + テスト期間（前半・後半）  をリッジ罰則つきで推定"""

    def __init__(self, s):
        self.s = s

    def _cols(self, d):
        s, F = self.s, {}
        g, dt, h = _obj(d.group), _obj(d.daytype_fb), _obj(d.hour)
        dow, tnum = d.dow.to_numpy(), d.t.to_numpy(dtype=float)
        F["切片"] = (np.ones(len(d)), 1e-6)
        dth, gdt = dt + "|" + h, g + "|" + dt
        gdth = gdt + "|" + h
        for k in sorted(self.dt_h):
            F["形" + k] = ((dth == k).astype(float), 1e-4)
        for k in sorted(self.g_dt):
            F["水準" + k] = ((gdt == k).astype(float), 1e-4)
        for k in sorted(self.g_dt_h):
            F["学年差" + k] = ((gdth == k).astype(float), s["lam_dev"])
        tt = np.minimum(tnum, self.t_max) / 30
        kp = np.minimum(d.koshu_prog.to_numpy(dtype=float), self.kp_max) / 30
        no3 = ~((g == "高3・既卒") & (_obj(d.test_name) == "学年末"))   # 学年末テストは高3には無い
        te = d.test_early.to_numpy(dtype=bool) & no3
        tl = d.test_late.to_numpy(dtype=bool) & no3
        F["講習の伸び"] = (kp, 0.1)
        F["テスト前半"] = (te.astype(float), s["lam_test"])
        F["テスト後半"] = (tl.astype(float), s["lam_test"])
        for gg in GROUPS:
            ig = (g == gg)
            for dw in range(1, 5):
                F[f"曜日{gg}{dw}"] = ((dt == "平日") & ig & (dow == dw)).astype(float), s["lam_dow"]
            F[f"トレンド{gg}"] = (ig * tt, 0.5)
            for k in self.knots:
                F[f"トレンド{gg}>{k}"] = (ig * np.maximum(0, tt - k / 30), s["lam_trend"])
            F[f"講習の伸び{gg}"] = (ig * kp, s["lam_ramp"])
            F[f"テスト前半{gg}"] = ((te & ig).astype(float), s["lam_test_dev"])
            F[f"テスト後半{gg}"] = ((tl & ig).astype(float), s["lam_test_dev"])
        return F

    def _X(self, d):
        d = d.assign(daytype_fb=d.daytype.where(d.daytype.isin(list(self.daytypes)), "土曜祝日"))
        F = self._cols(d)
        return np.column_stack([F[c][0] for c in self.names]), np.array([F[c][1] for c in self.names])

    def fit(self, d):
        s = self.s
        self.daytypes = set(d.daytype)
        h = d.hour.astype(str)
        self.dt_h = set(d.daytype + "|" + h)
        self.g_dt = set(d.group + "|" + d.daytype)
        self.g_dt_h = set(d.group + "|" + d.daytype + "|" + h)
        self.t_max, self.kp_max = int(d.t.max()), int(d.koshu_prog.max())
        koshu_t = set(d.t[d.koshu])
        self.knots = [k for k in range(int(d.t.min()) + s["knot_days"], self.t_max - 7, s["knot_days"]) if k not in koshu_t]
        self.names = list(self._cols(d.assign(daytype_fb=d.daytype)))
        X, pen = self._X(d)
        y = d.y.to_numpy(dtype=float)
        w = 0.5 ** ((self.t_max - d.t.to_numpy(dtype=float)) / s["half_life"])
        beta = np.zeros(X.shape[1])
        for _ in range(100):   # IRLS
            mu = np.exp(np.clip(X @ beta, -20, 8))
            z = X @ beta + (y - mu) / mu
            W = w * mu
            new = np.linalg.solve(X.T @ (X * W[:, None]) + np.diag(pen), X.T @ (W * z))
            done = np.max(np.abs(new - beta)) < 1e-9
            beta = new
            if done:
                break
        self.beta = beta
        return self

    def predict(self, d):
        X, _ = self._X(d)
        return np.exp(np.clip(X @ self.beta, -20, 8))


def _ref_days(model, last_date):
    """係数（倍率）を出すための基準日: データ最終日の水準の平日など"""
    def day(daytype, dow, **kw):
        base = dict(date=last_date, daytype=daytype, dow=dow, test_early=False, test_late=False,
                    test_name="", koshu=False, koshu_prog=0, t=model.t_max)
        base.update(kw)
        rows = [(h, g) for h in OPEN_HOURS[daytype] for g in GROUPS]
        return pd.DataFrame(rows, columns=["hour", "group"]).assign(**base)

    def total(days):
        out = {g: 0.0 for g in GROUPS + ["全体"]}
        for d in days:
            p = model.predict(d)
            for g in GROUPS:
                out[g] += p[(d.group == g).to_numpy()].sum()
            out["全体"] += p.sum()
        return {g: v / len(days) for g, v in out.items()}

    base = total([day("平日", w) for w in range(5)])
    cases = {
        "テスト期間・前半（最初の2週間）": [day("平日", w, test_early=True, test_name="2学期中間") for w in range(5)],
        "テスト期間・後半": [day("平日", w, test_late=True, test_name="2学期中間") for w in range(5)],
        "講習・はじめ": [day("講習", w, koshu=True) for w in range(5)],
        "講習・3週目": [day("講習", w, koshu=True, koshu_prog=14) for w in range(5)],
        "土曜・祝日": [day("土曜祝日", 5)],
    }
    rows = []
    for name, days in cases.items():
        t = total(days)
        rows.append({"期間": name, **{g: t[g] / base[g] for g in ["全体"] + GROUPS}})
    return pd.DataFrame(rows).set_index("期間")


@st.cache_data(ttl=600, show_spinner="混雑予測を計算しています…")
def crowd_forecast(records, train_end, pred_start, pred_end, with_effects=True):
    """train_end より前のデータで学習し、pred_start〜pred_end を予測する。
    戻り値: (学年別の予測 DataFrame[date,hour,group,pred], 倍率の表, 学習の情報)。データ不足なら None"""
    rec = records[(pd.to_datetime(records["日付"]) >= TRAIN_START) & (pd.to_datetime(records["日付"]) < train_end)]
    if rec.empty:
        return None
    occ, rec_days = _occupancy(rec)
    cal = crowd_calendar(TRAIN_START, pd.Timestamp(train_end) - timedelta(days=1))
    cal = cal[cal.date.isin(rec_days)]
    if (~cal.closed).sum() < 28:
        return None
    panel = _rows_for(cal).merge(occ, how="left").fillna({"occ": 0.0}).rename(columns={"occ": "y"})
    model = CrowdModel(MODEL_SETTINGS).fit(panel)
    fut = _rows_for(crowd_calendar(pred_start, pred_end))
    fut["pred"] = model.predict(fut)
    effects = _ref_days(model, panel.date.max()) if with_effects else None
    info = dict(last_date=panel.date.max(), n_days=int(panel.date.nunique()))
    return fut[["date", "hour", "group", "pred"]], effects, info


def apply_kou3_scenario(fut, factor_exam, factor_after):
    """高3・既卒の受験期・卒業後の倍率をかける"""
    f = fut.copy()
    md = f.date.dt.month * 100 + f.date.dt.day
    k3 = f.group == "高3・既卒"
    exam = md.between(KOU3_EXAM[0][0] * 100 + KOU3_EXAM[0][1], KOU3_EXAM[1][0] * 100 + KOU3_EXAM[1][1])
    after = md.between(KOU3_AFTER[0][0] * 100 + KOU3_AFTER[0][1], KOU3_AFTER[1][0] * 100 + KOU3_AFTER[1][1])
    f.loc[k3 & exam, "pred"] *= factor_exam
    f.loc[k3 & after, "pred"] *= factor_after
    return f


def forecast_totals(fut, data_last_date):
    """日付×時間の全体予測と80%の範囲"""
    tot = fut.groupby(["date", "hour"], as_index=False).pred.sum()
    ahead = (tot.date - pd.Timestamp(data_last_date)).dt.days
    q10 = np.select([ahead <= b[0] for b in PRED_BANDS], [b[1] for b in PRED_BANDS])
    q90 = np.select([ahead <= b[0] for b in PRED_BANDS], [b[2] for b in PRED_BANDS])
    tot["lo"] = np.maximum(0, tot.pred + q10 * np.sqrt(tot.pred + 1))
    tot["hi"] = tot.pred + q90 * np.sqrt(tot.pred + 1)
    return tot


st.set_page_config(page_title="TKG Study Room Analytics", page_icon="icon.png", layout="wide")
img_b64 = ""
if os.path.exists("icon.png"):
    with open("icon.png", "rb") as f: img_b64 = base64.b64encode(f.read()).decode()

js_code = f"""
<script>
    const doc = window.parent.document;
    if ("{img_b64}" !== "") {{
        let links = doc.querySelectorAll("link[rel~='apple-touch-icon']");
        links.forEach(link => link.remove());
        let newLink = doc.createElement('link'); newLink.rel = 'apple-touch-icon'; newLink.href = 'data:image/png;base64,{img_b64}'; doc.head.appendChild(newLink);
    }}
    
    const blockEnter = function(e) {{
        if (e.key === 'Enter' || e.keyCode === 13) {{
            const t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) {{
                if (t.type === 'password' || t.getAttribute('role') === 'combobox') return;
                e.stopPropagation();
                e.stopImmediatePropagation();
            }}
        }}
    }};
    
    doc.addEventListener('keydown', blockEnter, true);
    doc.addEventListener('keypress', blockEnter, true);
    doc.addEventListener('keyup', blockEnter, true);

    function formatTimeInput(target) {{
        let val = target.value; if (!val) return;
        let halfVal = val.replace(/[０-９]/g, function(s) {{ return String.fromCharCode(s.charCodeAt(0) - 0xFEE0); }});
        if (/^\\d{{3,4}}$/.test(halfVal)) {{
            let h = halfVal.length === 3 ? '0' + halfVal.slice(0,1) : halfVal.slice(0,2);
            let m = halfVal.slice(-2);
            let hNum = parseInt(h, 10); let mNum = parseInt(m, 10);
            if (hNum >= 0 && hNum <= 23 && mNum >= 0 && mNum <= 59) {{
                let formatted = h + ':' + m;
                let prototype = target.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
                let nativeInputValueSetter = Object.getOwnPropertyDescriptor(prototype, "value").set;
                if(nativeInputValueSetter) {{ nativeInputValueSetter.call(target, formatted); target.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            }}
        }}
    }}
    
    doc.addEventListener('keydown', function(e) {{ 
        if (e.key === 'Tab') {{ 
            if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {{ 
                formatTimeInput(e.target); 
            }} 
        }} 
    }}, true);
    doc.addEventListener('focusout', function(e) {{ 
        if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {{ 
            formatTimeInput(e.target); 
        }} 
    }}, true);
</script>
"""
st.markdown(js_code, unsafe_allow_html=True)

st.markdown("""
<style>
    #MainMenu, header, footer, [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
    .stApp { background-color: #F4F7FB; font-family: 'Helvetica Neue', Arial, sans-serif; }
    .main-title { font-weight: 900; color: #0A2B56; letter-spacing: 2px; margin-bottom: 25px; padding-bottom: 10px; border-bottom: 3px solid #E2E8F0; position: relative; font-size: 2.4rem; text-transform: uppercase;}
    .main-title::after { content: ''; position: absolute; left: 0; bottom: -3px; width: 100px; height: 3px; background: linear-gradient(90deg, #0A2B56, #005BAB); }
    .section-title { font-weight: 800; color: #0A2B56; margin-top: 2rem; margin-bottom: 1rem; padding-left: 10px; border-left: 5px solid #005BAB; font-size: 1.6rem; }
    div[role="radiogroup"] { display: flex; background-color: #FFFFFF; padding: 5px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px; margin-top: 5px; }
    div[role="radiogroup"] label { flex: 1; text-align: center; justify-content: center; padding: 10px 5px !important; margin: 0 !important; border-radius: 8px; transition: 0.2s; cursor: pointer; }
    div[role="radiogroup"] label[data-checked="true"] { background-color: #0A2B56; }
    div[role="radiogroup"] label[data-checked="true"] p { color: #FFFFFF !important; font-weight: 800; }
    div[role="radiogroup"] label p { color: #64748B; font-weight: 700; font-size: 0.85rem; }
    div[data-testid="stWidgetLabel"] p, div[data-testid="stWidgetLabel"] label, .stTextInput label p, .stSelectbox label p, .stDateInput label p { color: #0A2B56 !important; font-weight: 800 !important; font-size: 1.05rem !important; }
    button[data-baseweb="tab"] p { color: #0A2B56 !important; font-weight: bold !important; font-size: 1.1rem !important; }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div { background-color: #FFFFFF !important; border-radius: 8px !important; border: 1px solid #CBD5E1 !important; height: 3.2rem; }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div { color: #1E293B !important; font-weight: 700; font-size: 1.05rem; }
    div[data-baseweb="input"] input::placeholder { color: #94A3B8 !important; font-weight: 500; }
    button[kind="secondary"] { background-color: #FFFFFF !important; color: #0A2B56 !important; border: 2px solid #E2E8F0 !important; font-weight: 700 !important; border-radius: 6px !important; min-height: 3.5rem !important; }
    button[kind="primary"] { background: linear-gradient(135deg, #0A2B56 0%, #005BAB 100%) !important; color: #FFFFFF !important; border: none !important; font-weight: 800 !important; border-radius: 6px !important; min-height: 3.5rem !important; }
    div[data-testid="stMetric"] { background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 12px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    [data-testid="stMetricValue"] > div, [data-testid="stMetricValue"] { color: #0A2B56 !important; font-weight: 900 !important; font-size: 2.4rem !important; }
    [data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] { color: #475569 !important; font-size: 1.05rem !important; font-weight: bold !important; }
    @media (min-width: 768px) { div[role="radiogroup"] { max-width: 600px; } .rank-card { flex: 1; min-width: 30%; padding: 25px; border-radius: 16px; border: 1px solid #E2E8F0; } }
    @media (max-width: 767px) { div[role="radiogroup"] { width: 100%; } .rank-card { width: 100%; padding: 20px; border-radius: 12px; margin-bottom: 15px; } }
</style>
""", unsafe_allow_html=True)

if "sys_msg" not in st.session_state: st.session_state.sys_msg = None
if "sys_err" not in st.session_state: st.session_state.sys_err = None

APP_PASSWORD = "tkg-1985" 
if "authenticated" not in st.session_state: st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h3 style='text-align: center; color: #0A2B56; margin-top: 15vh; margin-bottom: 30px; font-weight: 900; font-size: 2.5rem; letter-spacing: 2px;'>Study Room System</h3>", unsafe_allow_html=True)
    with st.form("login_form", clear_on_submit=False):
        st.markdown("<p style='color: #0A2B56; font-weight: bold; margin-bottom: 5px;'>管理用パスワードを入力してください</p>", unsafe_allow_html=True)
        pwd = st.text_input("パスワード", type="password", placeholder="例: password123", label_visibility="collapsed")
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("システムにログイン", type="primary", use_container_width=True)
        if submitted:
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else: st.error("パスワードが違います")
    st.stop()

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
        if not df.empty: 
            df['日付'] = pd.to_datetime(df['日付'])
            df['名前'] = df['名前'].astype(str).apply(lambda x: "".join(x.split()))
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

if "form_key" not in st.session_state: st.session_state.form_key = 0

GRADES = ["--選択--"] + [f"小{i}" for i in range(1, 7)] + [f"中{i}" for i in range(1, 4)] + [f"高{i}" for i in range(1, 4)] + ["既卒/その他"]

menu = st.radio("メニュー", ["一括入力", "1件ずつ", "ランキング", "分析", "管理"], horizontal=True, label_visibility="collapsed")

if st.session_state.sys_msg:
    st.success(st.session_state.sys_msg)
    st.session_state.sys_msg = None
if st.session_state.sys_err:
    st.error(st.session_state.sys_err)
    st.session_state.sys_err = None

# --- 入力漏れチェック (今月の1日から昨日まで) ---
df_check = load_data()
today_date = jst_now.date()
first_day = today_date.replace(day=1)
recorded_dates = set(pd.to_datetime(df_check['日付']).dt.date) if not df_check.empty else set()

missing_dates = []
curr_d = first_day
while curr_d < today_date:
    if curr_d.weekday() != 6:  # 6 is Sunday
        if curr_d not in recorded_dates: missing_dates.append(curr_d)
    curr_d += timedelta(days=1)

missing_warning_html = ""
if missing_dates:
    weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
    missing_str = "、 ".join([f"{d.month}/{d.day}({weekdays_ja[d.weekday()]})" for d in missing_dates])
    missing_warning_html = f"<div style='background-color: #FEF2F2; border-left: 5px solid #DC2626; padding: 12px 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'><p style='color:#DC2626; font-weight:bold; margin:0; font-size: 1.05rem;'>⚠️ 今月の未入力日: {missing_str}</p></div>"

if menu == "一括入力":
    st.markdown("<div class='main-title'>BATCH ENTRY PANEL</div>", unsafe_allow_html=True)
    if missing_warning_html: st.markdown(missing_warning_html, unsafe_allow_html=True)
    f_date_batch = st.date_input("利用日 (全員共通)", jst_now.date(), max_value=jst_now.date())
    
    # --- 一括入力用の過去ユーザーリスト (直近90日) ---
    batch_user_list = ["-- 手入力 --"]
    df_history_batch = load_data()
    grade_lookup = {}
    if not df_history_batch.empty:
        limit_date_batch = pd.Timestamp(jst_now.date() - timedelta(days=90))
        recent_df_batch = df_history_batch[df_history_batch['日付'] >= limit_date_batch]
        batch_user_list += recent_df_batch['名前'].drop_duplicates().dropna().tolist()
        
        # 学年の自動補完用データ
        recent_grades = df_history_batch[['名前', '学年']].drop_duplicates(subset=['名前'], keep='last')
        grade_lookup = dict(zip(recent_grades['名前'], recent_grades['学年']))

    st.markdown("<p style='color:#64748B; font-weight:bold; margin-bottom:10px;'>過去の利用者から選ぶか、新規の場合は手入力欄に記入してください（選択した場合は学年が自動補完されます）。</p>", unsafe_allow_html=True)
    
    # ヘッダー
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([1.5, 2.5, 2.5, 1.5, 1.5])
    col_h1.markdown("<span style='color:#0A2B56; font-weight:bold; font-size:0.9rem;'>学年</span>", unsafe_allow_html=True)
    col_h2.markdown("<span style='color:#0A2B56; font-weight:bold; font-size:0.9rem;'>氏名(過去の利用者)</span>", unsafe_allow_html=True)
    col_h3.markdown("<span style='color:#0A2B56; font-weight:bold; font-size:0.9rem;'>氏名(新規手入力)</span>", unsafe_allow_html=True)
    col_h4.markdown("<span style='color:#0A2B56; font-weight:bold; font-size:0.9rem;'>開始時間</span>", unsafe_allow_html=True)
    col_h5.markdown("<span style='color:#0A2B56; font-weight:bold; font-size:0.9rem;'>終了時間</span>", unsafe_allow_html=True)

    batch_data_inputs = []
    for i in range(10): # 10行分の入力枠
        c1, c2, c3, c4, c5 = st.columns([1.5, 2.5, 2.5, 1.5, 1.5])
        with c1:
            grade_val = st.selectbox("学年", GRADES, key=f"b_grade_{i}_{st.session_state.form_key}", label_visibility="collapsed")
        with c2:
            old_name_val = st.selectbox("過去氏名", batch_user_list, key=f"b_old_{i}_{st.session_state.form_key}", label_visibility="collapsed")
        with c3:
            new_name_val = st.text_input("新規氏名", key=f"b_new_{i}_{st.session_state.form_key}", label_visibility="collapsed", placeholder="山田太郎")
        
        in_k = f"b_in_{i}_{st.session_state.form_key}"
        out_k = f"b_out_{i}_{st.session_state.form_key}"
        with c4:
            in_time_val = st.text_input("開始", key=in_k, label_visibility="collapsed", placeholder="1223", on_change=format_time_input, args=(in_k,))
        with c5:
            out_time_val = st.text_input("終了", key=out_k, label_visibility="collapsed", placeholder="1530", on_change=format_time_input, args=(out_k,))
        
        batch_data_inputs.append({
            "学年": grade_val,
            "氏名(過去)": old_name_val,
            "氏名(新規)": new_name_val,
            "開始": in_time_val,
            "終了": out_time_val
        })

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("この10件のデータを保存する", type="primary", use_container_width=True):
        new_records, error_msgs = [], []
        df_current = load_data()
        has_input = False

        for row in batch_data_inputs:
            name_sel = row["氏名(過去)"]
            name_man = str(row["氏名(新規)"]).strip()
            
            if name_sel != "-- 手入力 --" and name_man != "":
                error_msgs.append(f"過去の利用者（{name_sel}）と新規手入力（{name_man}）の両方が入力されています。どちらか一方のみにしてください。")
                has_input = True
                continue
                
            raw_name = name_sel if name_sel != "-- 手入力 --" else name_man
            name = "".join(str(raw_name).split())
            
            if not name: continue
            has_input = True
            
            grade_input = row["学年"]
            # 選択済みのユーザーで学年が未選択の場合、自動で補完する
            if pd.isna(grade_input) or grade_input == "--選択--" or not grade_input:
                if name in grade_lookup and grade_lookup[name] and grade_lookup[name] != "--選択--":
                    grade_input = grade_lookup[name]
                else:
                    error_msgs.append(f"{name}さん (学年が選択されていません)"); continue

            in_dt_time, out_dt_time = parse_custom_time(row["開始"]), parse_custom_time(row["終了"])
            if in_dt_time is None or out_dt_time is None:
                error_msgs.append(f"{name}さん (開始・終了時間を正しく入力してください)"); continue
            if not is_special_period(f_date_batch) and in_dt_time.hour < 12:
                error_msgs.append(f"{name}さん (通常期間は12時以降を入力してください)"); continue
            duration = calc_duration(in_dt_time, out_dt_time)
            if duration <= 0:
                error_msgs.append(f"{name}さん (終了時間が開始時間より前になっています)"); continue
            in_str, out_str = in_dt_time.strftime("%H:%M"), out_dt_time.strftime("%H:%M")
            
            is_dup_current = not df_current[(df_current['日付'] == pd.to_datetime(f_date_batch)) & (df_current['名前'] == name) & (df_current['入室時間'] == in_str) & (df_current['退室時間'] == out_str)].empty
            is_dup_new = any(r['名前'] == name and r['入室時間'] == in_str and r['退室時間'] == out_str for r in new_records)
            
            if is_dup_current or is_dup_new:
                error_msgs.append(f"{name}さん (既に同じ記録が登録されています)"); continue
                
            new_records.append({'日付': pd.to_datetime(f_date_batch), '名前': name, '学年': grade_input, '入室時間': in_str, '退室時間': out_str, '利用時間（時間）': duration})
        
        if not has_input:
            st.error("氏名が入力されている行がありません。")
        else:
            if error_msgs:
                for err in error_msgs: st.error(f"エラー: {err}")
            if new_records:
                df = pd.concat([df_current, pd.DataFrame(new_records)], ignore_index=True)
                save_to_gs(df)
                st.session_state.form_key += 1
                st.session_state.sys_msg = f"{len(new_records)}名分の記録を一括保存しました。（入力欄をリセットしました）"
                st.cache_data.clear()
                st.rerun()

elif menu == "1件ずつ":
    st.markdown("<div class='main-title'>SINGLE ENTRY PANEL</div>", unsafe_allow_html=True)
    if missing_warning_html: st.markdown(missing_warning_html, unsafe_allow_html=True)
    
    df_history = load_data()
    user_list = ["-- 新規入力 (直接入力してください) --"]
    recent_users = pd.DataFrame()
    if not df_history.empty:
        limit_date = pd.Timestamp(jst_now.date() - timedelta(days=90))
        recent_df = df_history[df_history['日付'] >= limit_date]
        recent_users = recent_df[['名前', '学年']].drop_duplicates(subset=['名前']).dropna()
        user_list += recent_users['名前'].tolist()

    st.markdown("<p style='color:#3B82F6; font-weight:bold; margin-bottom:5px; font-size: 1.05rem;'>過去の利用者から選ぶと自動入力されます</p>", unsafe_allow_html=True)
    selected_user = st.selectbox("過去の利用者検索", user_list, label_visibility="collapsed")
    
    if selected_user != "-- 新規入力 (直接入力してください) --":
        default_name = selected_user
        try:
            default_grade = recent_users[recent_users['名前'] == selected_user]['学年'].values[0]
            if not default_grade: default_grade = "--選択--"
        except: default_grade = "--選択--"
    else:
        default_name, default_grade = "", "--選択--"

    col1, col2 = st.columns([1, 1])
    with col1: f_date = st.date_input("利用日", jst_now.date(), max_value=jst_now.date())
    with col2: 
        g_index = GRADES.index(default_grade) if default_grade in GRADES else 0
        f_grade = st.selectbox("学年 (必須)", GRADES, index=g_index)
        
    k_name = f"name_{st.session_state.form_key}"
    f_name = st.text_input("氏名 (必須)", value=default_name, key=k_name, placeholder="例: 山田太郎")

    in_key, out_key = f"single_in_{st.session_state.form_key}", f"single_out_{st.session_state.form_key}"
    if in_key not in st.session_state: st.session_state[in_key] = (jst_now - timedelta(hours=1)).strftime("%H:%M")
    if out_key not in st.session_state: st.session_state[out_key] = jst_now.strftime("%H:%M")

    col_in, col_out = st.columns(2)
    with col_in: in_time_str = st.text_input("開始時間 (必須)", key=in_key, on_change=format_time_input, args=(in_key,))
    with col_out: out_time_str = st.text_input("終了時間 (必須)", key=out_key, on_change=format_time_input, args=(out_key,))

    st.markdown("<hr style='margin-top:20px; margin-bottom:20px;'>", unsafe_allow_html=True)
    if st.button("この内容で1件記録する", use_container_width=True, type="primary"):
        f_name_clean = "".join(f_name.split())
        in_time, out_time = parse_custom_time(in_time_str), parse_custom_time(out_time_str)
        if not f_name_clean: st.error("氏名を入力してください。")
        elif f_grade == "--選択--": st.error("学年を選択してください。")
        elif in_time is None or out_time is None: st.error("開始時間と終了時間を正しく入力してください。")
        elif not is_special_period(f_date) and in_time.hour < 12: st.error("通常期間は12時以降を入力してください。")
        else:
            duration = calc_duration(in_time, out_time)
            if duration <= 0: st.error("終了時間は開始時間以降に設定してください")
            else:
                df = load_data()
                in_str, out_str = in_time.strftime("%H:%M"), out_time.strftime("%H:%M")
                is_dup = not df[(df['日付'] == pd.to_datetime(f_date)) & (df['名前'] == f_name_clean) & (df['入室時間'] == in_str) & (df['退室時間'] == out_str)].empty
                if is_dup: st.error("この記録は既に登録されています。")
                else:
                    new_row = pd.DataFrame([{'日付': pd.to_datetime(f_date), '名前': f_name_clean, '学年': f_grade, '入室時間': in_str, '退室時間': out_str, '利用時間（時間）': duration}])
                    df = pd.concat([df, new_row], ignore_index=True)
                    save_to_gs(df)
                    st.session_state.form_key += 1 
                    st.session_state.sys_msg = f"{f_name_clean}さんの記録（{in_str} 〜 {out_str}）を保存しました。"
                    st.cache_data.clear()
                    st.rerun()

elif menu == "ランキング":
    st.markdown("<div class='main-title'>STUDY HOURS RANKING</div>", unsafe_allow_html=True)
    df = load_data()

    def render_premium_cards(agg):
        if agg.empty: return
        html = '<div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">'
        top_rows = agg[agg['順位'] <= 3]
        for i, row in top_rows.iterrows():
            rank_val, name, time_val = row['順位'], row['名前'], row['利用時間（時間）']
            grade_disp = row['学年'] if pd.notnull(row['学年']) and row['学年'] != "" else "学年未設定"
            if rank_val == 1: rank_text, icon, border_color, bg_grad = "1st", "", "#F59E0B", "linear-gradient(135deg, #FFFFFF 0%, #FFFBEB 100%)"
            elif rank_val == 2: rank_text, icon, border_color, bg_grad = "2nd", "", "#94A3B8", "linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%)"
            elif rank_val == 3: rank_text, icon, border_color, bg_grad = "3rd", "", "#B45309", "linear-gradient(135deg, #FFFFFF 0%, #FFF7ED 100%)"
            else: rank_text, icon, border_color, bg_grad = f"{rank_val}th", "", "#64748B", "linear-gradient(135deg, #FFFFFF 0%, #F1F5F9 100%)"
            html += f"<div class='rank-card' style='background: {bg_grad}; border-top: 5px solid {border_color}; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'><div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;'><span style='font-size: 1.1rem; color: #475569; font-weight: 900; letter-spacing: 1px;'>{rank_text} PLACE</span><span style='font-size: 1.5rem;'>{icon}</span></div><div style='font-size: 0.9rem; color: #64748B; font-weight: bold; margin-bottom: 5px;'>{grade_disp}</div><div style='font-size: 2.2rem; font-weight: 900; color: #0F172A; margin-bottom: 15px;'>{name} <span style='font-size: 1rem; font-weight: 600; color: #64748B;'>さん</span></div><div style='display: inline-block; background-color: #FFFFFF; color: #1D4ED8; padding: 6px 16px; border-radius: 8px; font-weight: 900; font-size: 1.2rem; border: 1px solid #BFDBFE;'>{time_val:.1f} <span style='font-size: 0.9rem;'>HOURS</span></div></div>"
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)

    def render_section_ranking(full_agg, target_grades, section_title):
        section_df = full_agg[full_agg['学年'].isin(target_grades)].reset_index(drop=True)
        st.markdown(f"<div class='section-title'>{section_title}</div>", unsafe_allow_html=True)
        if section_df.empty: st.info("集計データがありません。"); return
        section_df['順位'] = section_df['利用時間（時間）'].rank(method='min', ascending=False).astype(int)
        render_premium_cards(section_df)
        st.dataframe(section_df[['順位', '名前', '学年', '利用時間（時間）']], use_container_width=True, hide_index=True, column_config={
            "順位": st.column_config.NumberColumn("順位"), "名前": st.column_config.TextColumn("氏名"), "学年": st.column_config.TextColumn("学年"),
            "利用時間（時間）": st.column_config.ProgressColumn("累計学習時間", format="%.1f h", min_value=0, max_value=float(section_df['利用時間（時間）'].max() if section_df['利用時間（時間）'].max() > 0 else 1))
        })

    if not df.empty:
        jst_today = pd.Timestamp(jst_now.date())
        first_day_of_this_month = jst_today.replace(day=1)
        last_day_of_last_month = first_day_of_this_month - pd.Timedelta(days=1)
        last_month_num = last_day_of_last_month.month

        tab1, tab2, tab3, tab4 = st.tabs(["今月の集計", f"{last_month_num}月の集計", "直近3ヶ月", "累計"])
        def get_agg(target_df):
            if target_df.empty: return pd.DataFrame()
            return target_df.groupby(['名前', '学年'])['利用時間（時間）'].sum().reset_index().sort_values(by='利用時間（時間）', ascending=False).reset_index(drop=True)

        df_vp = df[df['日付'] <= jst_today]
        df_this_month = df_vp[(df_vp['日付'].dt.year == jst_today.year) & (df_vp['日付'].dt.month == jst_today.month)]
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        df_last_month = df_vp[(df_vp['日付'] >= first_day_of_last_month) & (df_vp['日付'] <= last_day_of_last_month)]
        df_3months = df_vp[df_vp['日付'] >= (jst_today - pd.DateOffset(months=3))]
        
        for tab, agg_data, period_name in zip([tab1, tab2, tab3, tab4], [get_agg(df_this_month), get_agg(df_last_month), get_agg(df_3months), get_agg(df_vp)], ["今月", f"{last_month_num}月", "直近3ヶ月", "累計"]):
            with tab:
                if agg_data.empty: st.info("データがありません。")
                else:
                    render_section_ranking(agg_data, [f"小{i}" for i in range(1, 7)], "小学生の部")
                    render_section_ranking(agg_data, [f"中{i}" for i in range(1, 4)], "中学生の部")
                    render_section_ranking(agg_data, ["高1", "高2"], "高1・高2の部")
                    render_section_ranking(agg_data, ["高3", "既卒/その他", ""], "高3・その他の部")
                    st.markdown("---")
                    st.markdown("##### 📋 PowerPoint貼り付け用データ (上位5名)")
                    copy_text = f"期間：{period_name}度\n\n"
                    sections = [("【 小学生の部 】", [f"小{i}" for i in range(1, 7)]), ("【 中学生の部 】", [f"中{i}" for i in range(1, 4)]), ("【 高1・高2の部 】", ["高1", "高2"]), ("【 高3・その他の部 】", ["高3", "既卒/その他", ""])]
                    for sec_name, grades in sections:
                        sec_df = agg_data[agg_data['学年'].isin(grades)].reset_index(drop=True)
                        if not sec_df.empty:
                            sec_df['順位'] = sec_df['利用時間（時間）'].rank(method='min', ascending=False).astype(int)
                            top5 = sec_df[sec_df['順位'] <= 5].sort_values('順位')
                            copy_text += f"{sec_name}\n順位\t名前\t学年\t時間\n"
                            for _, row in top5.iterrows(): copy_text += f"{row['順位']}位\t{row['名前']}さん\t{row['学年']}\t{row['利用時間（時間）']:.1f}h\n"
                        copy_text += "\n"
                    st.code(copy_text, language="text")
    else: st.info("データがありません。最初の記録を登録してください。")

elif menu == "分析":
    st.markdown("<div class='main-title'>ANALYTICS DASHBOARD</div>", unsafe_allow_html=True)
    df_ana = load_data()
    jst_today = pd.Timestamp(jst_now.date())
    fc_main, records_for_model = None, None
    if not df_ana.empty:
        records_for_model = df_ana[['日付', '学年', '入室時間', '退室時間']].copy()
        _next_last = ((jst_today.replace(day=1) + timedelta(days=32)).replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        try:
            fc_main = crowd_forecast(records_for_model, str(jst_today.date()), str(jst_today.date()),
                                     str(max(_next_last, jst_today + timedelta(days=62)).date()))
        except Exception as e:
            st.warning(f"混雑予測の計算でエラーが起きました（{e}）。予測以外の画面はそのまま使えます。")
            fc_main = None

    if not df_ana.empty:
        # --- 月間利用トレンドグラフの追加 ---
        st.markdown("<div class='section-title'>月間利用時間トレンド</div>", unsafe_allow_html=True)
        df_trend = df_ana.copy()
        df_trend['年月'] = df_trend['日付'].dt.strftime('%Y-%m')
        trend_agg = df_trend.groupby('年月')['利用時間（時間）'].sum().reset_index()
        st.bar_chart(trend_agg.set_index('年月')['利用時間（時間）'])

        this_month_start = jst_today.replace(day=1)
        last_month_start = (this_month_start - pd.Timedelta(days=1)).replace(day=1)
        last_month_end = this_month_start - pd.Timedelta(days=1)
        
        two_months_ago_start = (last_month_start - pd.Timedelta(days=1)).replace(day=1)
        two_months_ago_end = last_month_start - pd.Timedelta(days=1)
        
        last_month_today = jst_today - pd.DateOffset(months=1)

        # 1. 先月の確定実績（前々月との比較）
        st.markdown(f"<div class='section-title'>先月の確定実績（前々月比）</div>", unsafe_allow_html=True)
        df_last_f = df_ana[(df_ana['日付'] >= last_month_start) & (df_ana['日付'] <= last_month_end)]
        df_2mo_f = df_ana[(df_ana['日付'] >= two_months_ago_start) & (df_ana['日付'] <= two_months_ago_end)]
        
        hours_last = df_last_f['利用時間（時間）'].sum()
        hours_2mo = df_2mo_f['利用時間（時間）'].sum()
        diff_hours_last = hours_last - hours_2mo
        pct_hours_last = (diff_hours_last / hours_2mo * 100) if hours_2mo > 0 else (100 if hours_last > 0 else 0)
        
        users_last = df_last_f['名前'].nunique()
        users_2mo = df_2mo_f['名前'].nunique()
        diff_users_last = users_last - users_2mo
        pct_users_last = (diff_users_last / users_2mo * 100) if users_2mo > 0 else (100 if users_last > 0 else 0)
        
        col_met_l1, col_met_l2, col_met_l3 = st.columns(3)
        col_met_l1.metric(f"{last_month_start.month}月の総学習時間", f"{hours_last:.1f} 時間", f"{pct_hours_last:+.1f}% ({diff_hours_last:+.1f} 時間)")
        col_met_l2.metric(f"{last_month_start.month}月の利用者数", f"{users_last} 名", f"{pct_users_last:+.1f}% ({diff_users_last:+d} 名)")
        if users_last > 0:
            avg_last = hours_last / users_last
            avg_2mo = hours_2mo / users_2mo if users_2mo > 0 else 0
            diff_avg_last = avg_last - avg_2mo
            pct_avg_last = (diff_avg_last / avg_2mo * 100) if avg_2mo > 0 else (100 if avg_last > 0 else 0)
            col_met_l3.metric("1人あたり平均学習時間", f"{avg_last:.1f} 時間", f"{pct_avg_last:+.1f}% ({diff_avg_last:+.1f} 時間)")

        # 2. 今月の進捗速報（前月同日時点との比較）
        st.markdown("<div class='section-title'>今月の進捗速報（前月同日時点との比較）</div>", unsafe_allow_html=True)
        df_this_p = df_ana[(df_ana['日付'] >= this_month_start) & (df_ana['日付'] <= jst_today)]
        df_last_p = df_ana[(df_ana['日付'] >= last_month_start) & (df_ana['日付'] <= last_month_today)]
        
        hours_this_p = df_this_p['利用時間（時間）'].sum()
        hours_last_p = df_last_p['利用時間（時間）'].sum()
        diff_hours_p = hours_this_p - hours_last_p
        pct_hours_p = (diff_hours_p / hours_last_p * 100) if hours_last_p > 0 else (100 if hours_this_p > 0 else 0)
        
        users_this_p = df_this_p['名前'].nunique()
        users_last_p = df_last_p['名前'].nunique()
        diff_users_p = users_this_p - users_last_p
        pct_users_p = (diff_users_p / users_last_p * 100) if users_last_p > 0 else (100 if users_this_p > 0 else 0)
        
        col_met_p1, col_met_p2, col_met_p3 = st.columns(3)
        col_met_p1.metric(f"{this_month_start.month}月(本日迄)の総学習時間", f"{hours_this_p:.1f} 時間", f"{pct_hours_p:+.1f}% ({diff_hours_p:+.1f} 時間)")
        col_met_p2.metric(f"{this_month_start.month}月(本日迄)の利用者数", f"{users_this_p} 名", f"{pct_users_p:+.1f}% ({diff_users_p:+d} 名)")
        if users_this_p > 0:
            avg_this_p = hours_this_p / users_this_p
            avg_last_p = hours_last_p / users_last_p if users_last_p > 0 else 0
            diff_avg_p = avg_this_p - avg_last_p
            pct_avg_p = (diff_avg_p / avg_last_p * 100) if avg_last_p > 0 else (100 if avg_this_p > 0 else 0)
            col_met_p3.metric("1人あたり平均学習時間", f"{avg_this_p:.1f} 時間", f"{pct_avg_p:+.1f}% ({diff_avg_p:+.1f} 時間)")

        # --- 翌月の利用予測（混雑予測モデル） ---
        today_d = jst_today.day
        next_month_first = (jst_today.replace(day=1) + timedelta(days=32)).replace(day=1)
        next_month_last = (next_month_first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        days_in_month = (next_month_first - timedelta(days=1)).day
        next_month_u = users_this_p * (1 + max(min((pct_users_p / 100.0), 0.1), -0.1))
        if fc_main is not None:
            fut_nm = fc_main[0][(fc_main[0]["date"] >= next_month_first) & (fc_main[0]["date"] <= next_month_last)]
            next_month_h = fut_nm["pred"].sum()
            h_note = "時間はテスト・講習期間と最近の伸びを反映した混雑予測モデルの値、人数は今月のペースからの見込みです。"
        else:
            proj_hours_this_month = hours_this_p / today_d * days_in_month if today_d > 0 else 0
            growth_rate_h = pct_hours_p / 100.0 if pct_hours_p != 100 else 0
            next_month_h = proj_hours_this_month * (1 + max(min(growth_rate_h, 0.15), -0.15))
            h_note = "データが少ないため、今月のペースからの見込みです。"

        st.markdown(f"""
        <div style='background-color: #FFFFFF; border-left: 6px solid #F59E0B; padding: 20px; border-radius: 12px; margin-top: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
            <div style='font-weight: 900; color: #0F172A; margin-bottom: 8px; font-size: 1.2rem;'>翌月（{next_month_first.month}月）の着地予測</div>
            <div style='color: #475569; font-size: 1.05rem;'>
                来月は <b style='color: #B45309; font-size: 1.3rem;'>約 {next_month_h:.0f} 時間</b> の利用と、<b style='color: #B45309; font-size: 1.3rem;'>約 {int(next_month_u)} 名</b> の生徒の来室が見込まれます。
            </div>
            <div style='color: #94A3B8; font-size: 0.85rem; margin-top: 6px;'>{h_note}</div>
        </div>
        """, unsafe_allow_html=True)

        # --- 先月の予測の振り返り（前々月末までのデータで予測した先月 と 実績の比較） ---
        try:
            fc_prev = crowd_forecast(records_for_model, str(last_month_start.date()), str(last_month_start.date()),
                                     str(last_month_end.date()), False)
        except Exception:
            fc_prev = None
        if fc_prev is not None and hours_last > 0:
            predicted_last_month_h = fc_prev[0]["pred"].sum()
            diff_pred_last = hours_last - predicted_last_month_h
            diff_pct_last = (diff_pred_last / predicted_last_month_h) * 100 if predicted_last_month_h > 0 else 0

            if abs(diff_pct_last) <= 5:
                eval_msg_last = "🎯 <b>非常に高い精度</b>で予測が的中しました（ほぼ予測通り）。"
            elif abs(diff_pct_last) <= 15:
                eval_msg_last = "✅ <b>概ね予測通り</b>の着地となりました。"
            elif diff_pred_last > 0:
                eval_msg_last = "🚀 実際の利用が予測を<b>大きく上回る伸び</b>を見せました。"
            else:
                eval_msg_last = "📉 実際の利用が予測を<b>下回る結果</b>となりました。"

            st.markdown(f"""
            <div style='background-color: #F8FAFC; border-left: 6px solid #64748B; padding: 15px; border-radius: 8px; margin-top: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);'>
                <div style='font-weight: 800; color: #475569; margin-bottom: 5px; font-size: 1.05rem;'>📊 先月の予測の振り返り</div>
                <div style='color: #475569; font-size: 0.95rem; line-height: 1.6;'>
                    前々月末までのデータで混雑予測モデルが出した先月（{last_month_start.month}月）の総学習時間の予測は <b>約 {predicted_last_month_h:.0f} 時間</b> でした。<br>
                    実際の総学習時間（<b>{hours_last:.1f} 時間</b>）との差は <b>{diff_pct_last:+.1f}%</b> で、{eval_msg_last}
                </div>
            </div>
            """, unsafe_allow_html=True)

    else: st.info("データが蓄積されると前月比の利用率が表示されます。")
        
    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["混雑状況", "生徒個別", "混雑予測"])
    def get_active_slots(in_str, out_str, slots_list):
        def parse_time(t_str):
            t_str = str(t_str).strip()
            if "コマ" in t_str:
                try: return datetime.strptime(f"{13 + int((int(t_str.replace('コマ', '')) - 1) * 1.5):02d}:00", "%H:%M").time()
                except: return None
            try:
                parts = t_str.split(":")
                if len(parts) >= 2: return datetime.strptime(f"{int(parts[0]):02d}:{int(parts[1]):02d}", "%H:%M").time()
            except: pass
            return None
        in_t, out_t = parse_time(in_str), parse_time(out_str)
        if not in_t or not out_t: return []
        slots = []
        for slot_str in slots_list:
            h = int(slot_str[:2])
            slot_start = datetime.strptime(f"{h:02d}:00", "%H:%M").time()
            slot_end = datetime.strptime(f"{h+1:02d}:00", "%H:%M").time() if h < 22 else datetime.strptime("23:59", "%H:%M").time()
            if in_t < slot_end and out_t > slot_start: slots.append(slot_str)
        return slots

    with tab1:
        st.markdown("<div class='section-title'>曜日・時間帯別の混雑状況</div>", unsafe_allow_html=True)
        if not df_ana.empty:
            df_ana['年月'] = pd.to_datetime(df_ana['日付']).dt.strftime('%Y年%m月')
            month_options = ["累計"] + sorted(df_ana['年月'].dropna().unique().tolist(), reverse=True)
            selected_period = st.selectbox("集計対象を選択", month_options)
            target_df = df_ana if selected_period == "累計" else df_ana[df_ana['年月'] == selected_period]
            current_time_slots = get_time_slots_for_period(selected_period)
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            heatmap_data = pd.DataFrame(0, index=weekdays, columns=current_time_slots)
            for _, row in target_df.iterrows():
                if pd.isnull(row['日付']) or not row['入室時間'] or not row['退室時間']: continue
                try:
                    wd = weekdays[pd.to_datetime(row['日付']).weekday()]
                    for slot in get_active_slots(row['入室時間'], row['退室時間'], current_time_slots): heatmap_data.loc[wd, slot] += 1
                except: continue
            max_val = max(heatmap_data.values.max(), 1)
            html = "<div style='overflow-x: auto; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #E2E8F0;'><table style='width:100%; border-collapse: collapse; min-width: 600px;'>"
            html += "<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>曜日</th>"
            for tb in current_time_slots: html += f"<th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; font-size:0.85rem;'>{tb[:2]}時台</th>"
            html += "</tr>"
            for wd in weekdays:
                html += f"<tr><th style='border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A; position: sticky; left: 0; z-index: 1;'>{wd}</th>"
                for tb in current_time_slots:
                    val = heatmap_data.loc[wd, tb]
                    ratio = val / max_val if max_val > 0 else 0
                    bg_color = f"rgba(37, 99, 235, {ratio * 0.8})" if val > 0 else "transparent"
                    font_color = "white" if ratio > 0.5 else "#1E293B"
                    html += f"<td style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; font-weight: bold; background-color: {bg_color}; color: {font_color};'>{val}</td>"
                html += "</tr>"
            html += "</table></div>"
            st.markdown(html, unsafe_allow_html=True)
        else: st.info("集計するデータがありません。")

    with tab2:
        st.markdown("<div class='section-title'>生徒個別 学習時間データ</div>", unsafe_allow_html=True)
        if not df_ana.empty:
            unique_names = [n for n in df_ana['名前'].dropna().unique().tolist() if str(n).strip() != ""]
            if unique_names:
                selected_name = st.selectbox("生徒名で検索", ["-- 選択してください --"] + unique_names)
                if selected_name != "-- 選択してください --":
                    student_df = df_ana[df_ana['名前'] == selected_name].copy()
                    student_df['日付'] = pd.to_datetime(student_df['日付'])
                    sm_df = student_df[student_df['日付'] >= jst_today.replace(day=1)]
                    total_h = sm_df['利用時間（時間）'].sum()
                    st.markdown(f"<div style='background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%); padding: 25px; border-radius: 12px; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'><h4 style='margin:0; font-size: 1.1rem; color: #94A3B8; font-weight: bold;'>{selected_name} さんの今月の学習時間</h4><div style='font-size: 3rem; font-weight: 900; margin-top: 5px; color: #FFFFFF;'>{total_h:.1f} <span style='font-size: 1.2rem; font-weight: bold; color: #94A3B8;'>時間</span></div></div>", unsafe_allow_html=True)
                    st.markdown("##### 日別の学習推移（今月）")
                    if not sm_df.empty:
                        daily_sum = sm_df.groupby('日付')['利用時間（時間）'].sum().reset_index()
                        daily_sum['日付ラベル'] = daily_sum['日付'].dt.strftime('%m/%d')
                        st.bar_chart(daily_sum.set_index('日付ラベル')['利用時間（時間）'])
                    else: st.info("今月の記録はまだありません。")
                    st.markdown("##### 直近の記録一覧")
                    display_history = student_df.sort_values('日付', ascending=False).head(10)
                    display_history['日付'] = display_history['日付'].dt.strftime('%Y/%m/%d')
                    st.dataframe(display_history[['日付', '入室時間', '退室時間', '利用時間（時間）']], use_container_width=True, hide_index=True)
            else: st.info("検索できる生徒データがありません。")
        else: st.info("集計するデータがありません。")

    with tab3:
        st.markdown("<div class='section-title'>混雑予測</div>", unsafe_allow_html=True)
        st.markdown("<p style='color:#64748B; font-size:1rem; font-weight: bold;'>過去の利用データから、曜日・時間帯・学年ごとのパターンに、テスト期間・講習期間・生徒数の増減を掛け合わせて予測しています。数字は「その1時間に平均して何人いるか」です。</p>", unsafe_allow_html=True)
        if fc_main is None:
            st.info("予測には、6/4以降のデータが4週間分以上必要です。")
        else:
            fut_all, effects, fc_info = fc_main
            col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
            with col_s1: seats = int(st.number_input("座席数", min_value=1, max_value=200, value=SEATS_DEFAULT, step=1))
            with col_s2: week_sel = st.selectbox("表示する期間", ["この先7日", "8〜14日後"])
            with col_s3: scen_sel = st.selectbox("1月中旬以降の高3（受験期）の見通し", list(KOU3_SCENARIOS.keys()))
            fut_s = apply_kou3_scenario(fut_all, *KOU3_SCENARIOS[scen_sel])
            tot = forecast_totals(fut_s, fc_info["last_date"])
            tot_idx = tot.set_index(["date", "hour"])

            view_start = jst_today + timedelta(days=0 if week_sel == "この先7日" else 7)
            cal7 = crowd_calendar(view_start, view_start + timedelta(days=6))

            # --- 期間のお知らせ（テスト・講習） ---
            def day_note(r):
                if r.closed: return ""
                if r.test_early: return f"{r.test_name}テストの前半（混みやすい時期）"
                if r.test_late: return f"{r.test_name}テストの後半（空きやすい時期）"
                if r.koshu: return "講習期間（朝から利用が増えます）"
                return ""
            notes, run = [], None
            for r in cal7.itertuples():
                lab = day_note(r)
                if run and run[2] == lab: run[1] = r.date
                else:
                    if run and run[2]: notes.append(run)
                    run = [r.date, r.date, lab]
            if run and run[2]: notes.append(run)
            if notes:
                lines = "<br>".join(f"{a.month}/{a.day}" + (f"〜{b.month}/{b.day}" if b != a else "") + f"：{lab}" for a, b, lab in notes)
                st.markdown(f"<div style='background-color: #FEF2F2; border-left: 5px solid #DC2626; padding: 15px; margin-bottom: 20px; border-radius: 8px;'><p style='color:#DC2626; font-weight:bold; margin:0; line-height:1.7;'>{lines}</p></div>", unsafe_allow_html=True)

            # --- 日付×時間帯の表 ---
            show_hours = list(range(9, 22)) if cal7.daytype.isin(["講習", "講習日曜"]).any() else list(range(12, 22))
            th = "border: 1px solid #CBD5E1; padding: 10px; background-color: #F8FAFC; color: #0F172A;"
            html = "<div style='overflow-x: auto; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #E2E8F0;'><table style='width:100%; border-collapse: collapse; min-width: 640px;'>"
            html += f"<tr><th style='{th} position: sticky; left: 0; z-index: 1;'>日付</th>"
            for h in show_hours: html += f"<th style='{th} font-size:0.85rem;'>{h}時台</th>"
            html += "</tr>"
            for r in cal7.itertuples():
                tags = ""
                if (r.test_early or r.test_late) and not r.closed: tags += "<span style='display:inline-block; margin-left:6px; padding:1px 6px; border-radius:999px; border:1px solid #DC2626; color:#DC2626; font-size:0.7rem;'>テスト</span>"
                if r.koshu and not r.closed: tags += "<span style='display:inline-block; margin-left:6px; padding:1px 6px; border-radius:999px; border:1px solid #D97706; color:#B45309; font-size:0.7rem;'>講習</span>"
                label = f"{r.date.month}/{r.date.day}({WEEKDAYS_JA[r.dow]}{'・祝' if r.holiday else ''})"
                html += f"<tr><th style='{th} position: sticky; left: 0; z-index: 1; white-space: nowrap; text-align:left;'>{label}{tags}</th>"
                if r.closed:
                    html += f"<td colspan='{len(show_hours)}' style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; color: #94A3B8; font-weight: bold;'>休館（{r.closed_reason}）</td></tr>"
                    continue
                for h in show_hours:
                    if (r.date, h) not in tot_idx.index:
                        html += "<td style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; color: #CBD5E1;'>-</td>"
                        continue
                    row = tot_idx.loc[(r.date, h)]
                    val, n = row["pred"], int(round(row["pred"]))
                    tip = f"80%の範囲 {row['lo']:.0f}〜{row['hi']:.0f}人"
                    if val >= seats: bg, fg, disp = "rgba(220, 38, 38, 0.9)", "white", f"満席 約{n}人"
                    elif val >= seats - 3: bg, fg, disp = "rgba(234, 88, 12, 0.8)", "white", f"約{n}人"
                    elif n > 0:
                        ratio = min(val / seats, 1.0)
                        bg, fg, disp = f"rgba(37, 99, 235, {ratio * 0.8:.2f})", ("white" if ratio > 0.45 else "#1E293B"), f"約{n}人"
                    else: bg, fg, disp = "transparent", "#94A3B8", "-"
                    html += f"<td title='{tip}' style='border: 1px solid #CBD5E1; padding: 10px; text-align: center; font-size:0.85rem; font-weight: bold; background-color: {bg}; color: {fg};'>{disp}</td>"
                html += "</tr>"
            html += "</table></div>"
            st.markdown(html, unsafe_allow_html=True)
            st.markdown(f"<p style='color:#64748B; font-size:0.85rem; margin-top:6px;'>赤＝座席数（{seats}席）以上、オレンジ＝残り3席以内。マスにカーソルを合わせると80%の範囲が出ます。</p>", unsafe_allow_html=True)

            # --- この先8週間の見通し ---
            st.markdown("<div class='section-title'>この先8週間の見通し</div>", unsafe_allow_html=True)
            horizon_end = jst_today + timedelta(days=55)
            t8 = tot[(tot.date >= jst_today) & (tot.date <= horizon_end)]
            if not t8.empty:
                pk = t8.loc[t8.groupby("date").pred.idxmax()].copy()
                pk["日付"] = pk.date.dt.strftime("%m/%d") + "(" + pk.date.dt.dayofweek.map(lambda i: WEEKDAYS_JA[i]) + ")"
                pk["ピーク"] = pk.hour.astype(str) + "時台 約" + pk.pred.round().astype(int).astype(str) + "人"
                cal8 = crowd_calendar(jst_today, horizon_end)
                spans, cur = [], None
                for r in cal8.itertuples():
                    kind = "テスト期間" if (r.test_early or r.test_late) else ("講習期間" if r.koshu else None)
                    if cur and cur[2] == kind: cur[1] = r.date + timedelta(days=1)
                    else:
                        if cur and cur[2]: spans.append(cur)
                        cur = [r.date, r.date + timedelta(days=1), kind]
                if cur and cur[2]: spans.append(cur)
                try:
                    import altair as alt
                    x = alt.X("date:T", title=None, axis=alt.Axis(format="%m/%d"))
                    layers = []
                    if spans:
                        sp = pd.DataFrame(spans, columns=["start", "end", "期間"])
                        layers.append(alt.Chart(sp).mark_rect(opacity=0.12).encode(
                            x=alt.X("start:T", title=None), x2="end:T",
                            color=alt.Color("期間:N", scale=alt.Scale(domain=["テスト期間", "講習期間"], range=["#DC2626", "#F59E0B"]),
                                            legend=alt.Legend(title=None, orient="top"))))
                    base = alt.Chart(pk).encode(x=x)
                    layers.append(base.mark_area(opacity=0.18, color="#005BAB").encode(y=alt.Y("lo:Q", title="その日のピーク（人）"), y2="hi:Q"))
                    layers.append(base.mark_line(point=True, color="#0A2B56").encode(
                        y="pred:Q", tooltip=[alt.Tooltip("日付:N"), alt.Tooltip("ピーク:N"),
                                             alt.Tooltip("lo:Q", title="80%の範囲 下", format=".0f"), alt.Tooltip("hi:Q", title="80%の範囲 上", format=".0f")]))
                    layers.append(alt.Chart(pd.DataFrame({"y": [seats]})).mark_rule(color="#DC2626", strokeDash=[4, 4]).encode(y="y:Q"))
                    st.altair_chart(alt.layer(*layers).properties(height=280), use_container_width=True)
                except Exception:
                    st.line_chart(pk.set_index("date")[["pred", "lo", "hi"]])
                st.markdown("<p style='color:#64748B; font-size:0.85rem;'>各日でいちばん混む時間帯の予測人数。帯は80%の範囲、点線は座席数。4週間より先は目安です。</p>", unsafe_allow_html=True)

            with st.expander("期間ごとの係数（データから推定した倍率）"):
                if effects is not None:
                    st.markdown("同じ時期のふつうの平日（月〜金）を1としたときの、1日の延べ在室時間の倍率です。データが増えると自動で推定し直されます。")
                    st.dataframe(effects.apply(lambda col: col.map(lambda v: f"×{v:.2f}")), use_container_width=True)
            with st.expander("予測の仕組みと精度"):
                st.markdown(f"""
- 学習に使っているのは {TRAIN_START} 以降の記録です（それより前は試用期間）。最新は {fc_info['last_date']:%m/%d} までの {fc_info['n_days']} 日分。
- 学年グループ（小学生・中学生・高1/高2・高3/既卒）ごとに、曜日タイプ×時間帯のパターン、生徒数のトレンド、テスト期間（前半2週間・後半）、講習期間中の盛り上がりを掛け合わせたポアソン回帰です。直近6週間のデータを重めに見ています。
- 2026年10月の答え合わせ（8/1〜10/3の各週末までのデータで2週間先までを予測）では、時間帯ごとの誤差が平均2.5人（以前の方式は3.3人）、その日のピーク人数の誤差が平均3.1人（以前は5.1人）でした。
- 満席の見張りには、オレンジ（残り3席以内）を目安にすると、実際に満席になった枠の約4分の3を事前に拾えます。
- 講習・テスト・休館の日付は、コードの「期間の設定」で変えられます。1月中旬以降の高3はデータがないので、上の見通しで切り替えてください。
""")

elif menu == "管理":
    st.markdown("<div class='main-title'>ADMIN PANEL</div>", unsafe_allow_html=True)
    df_manage = load_data()
    
    if not df_manage.empty:
        tab_edit, tab_del = st.tabs(["1件ずつ編集", "複数の一括削除"])
        options = []
        for i in reversed(df_manage.index):
            row = df_manage.loc[i]
            d_str = row['日付'].strftime('%m/%d') if pd.notnull(row['日付']) else "不明"
            options.append((str(i), f"{d_str} | {row['名前']} ({row['入室時間']} - {row['退室時間']})"))
            
        with tab_del:
            st.markdown("##### まとめて削除")
            selected_dels = st.multiselect("削除する記録を選択してください", options, format_func=lambda x: x[1])
            if st.button("選択した記録を完全に削除", type="primary"):
                if selected_dels:
                    indices_to_drop = [int(x[0]) for x in selected_dels]
                    df_manage = df_manage.drop(indices_to_drop).reset_index(drop=True)
                    save_to_gs(df_manage)
                    st.session_state.sys_msg = f"{len(indices_to_drop)}件の記録を削除しました。"
                    st.cache_data.clear()
                    st.rerun()
                else: st.warning("削除する記録が選択されていません。")

        with tab_edit:
            st.markdown("##### 記録の編集")
            selected_mng = st.selectbox("編集する記録", [("-1", "-- 選択してください --")] + options[:50], format_func=lambda x: x[1])
            if selected_mng[0] != "-1":
                target_idx = int(selected_mng[0])
                target_row = df_manage.loc[target_idx]
                st.markdown("<div style='margin-top: 10px; padding: 25px; border-radius: 12px; background-color: #FFFFFF; border: 1px solid #E2E8F0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
                
                default_date = target_row['日付'].date() if pd.notnull(target_row['日付']) else jst_now.date()
                edit_date = st.date_input("利用日", default_date)
                edit_name = st.text_input("氏名 (必須)", value=str(target_row['名前']), placeholder="例: 山田太郎")
                
                edit_in_key, edit_out_key = f"edit_in_{target_idx}_{target_row['名前']}", f"edit_out_{target_idx}_{target_row['名前']}"
                if edit_in_key not in st.session_state: st.session_state[edit_in_key] = str(target_row['入室時間'])
                if edit_out_key not in st.session_state: st.session_state[edit_out_key] = str(target_row['退室時間'])

                col_in, col_out = st.columns(2)
                with col_in: edit_in_str = st.text_input("開始時間 (例: 1223, 全角OK)", key=edit_in_key, on_change=format_time_input, args=(edit_in_key,))
                with col_out: edit_out_str = st.text_input("終了時間 (例: 1530, 全角OK)", key=edit_out_key, on_change=format_time_input, args=(edit_out_key,))

                current_grade = str(target_row['学年']) if str(target_row['学年']) else "--選択--"
                edit_grade = st.selectbox("学年 (必須)", GRADES, index=(GRADES.index(current_grade) if current_grade in GRADES else 0))
                
                st.markdown("<br>", unsafe_allow_html=True)
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("この内容で上書き保存", use_container_width=True, type="primary"):
                        edit_name_clean = "".join(edit_name.split())
                        edit_in, edit_out = parse_custom_time(edit_in_str), parse_custom_time(edit_out_str)
                        if edit_name_clean:
                            if edit_grade == "--選択--": st.error("学年を選択してください。")
                            elif edit_in is None or edit_out is None: st.error("開始と終了時間を正しく入力してください。")
                            elif not is_special_period(edit_date) and edit_in.hour < 12: st.error("通常期間は12時以降を入力してください。")
                            else:
                                duration = calc_duration(edit_in, edit_out)
                                if duration <= 0: st.error("終了時間は開始時間以降に設定してください")
                                else:
                                    df_manage.at[target_idx, '日付'] = pd.to_datetime(edit_date)
                                    df_manage.at[target_idx, '名前'] = edit_name_clean
                                    df_manage.at[target_idx, '学年'] = edit_grade
                                    df_manage.at[target_idx, '入室時間'] = edit_in.strftime("%H:%M")
                                    df_manage.at[target_idx, '退室時間'] = edit_out.strftime("%H:%M")
                                    df_manage.at[target_idx, '利用時間（時間）'] = duration
                                    save_to_gs(df_manage)
                                    st.session_state.sys_msg = "記録を更新しました。"
                                    st.cache_data.clear()
                                    st.rerun()
                        else: st.error("氏名を入力してください。")
                with col_btn2:
                    if st.button("この記録を完全に削除", use_container_width=True):
                        df_manage = df_manage.drop(target_idx).reset_index(drop=True)
                        save_to_gs(df_manage)
                        st.session_state.sys_msg = "削除しました。"
                        st.cache_data.clear()
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
    else: st.info("変更・削除できるデータがありません。")
