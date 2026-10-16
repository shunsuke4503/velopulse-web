from __future__ import annotations

import hashlib
import io
import os
from datetime import date

import fitparse
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from supabase import Client, create_client
from supabase.client import ClientOptions
BUCKET = "velopulse-fit-files"
DATA_COLUMNS = ["Session", "Interval start", "CAD(rpm)", "HR(bpm)", "Watts(W)", "Slope(%)", "Temperature(C)", "Source file"]

st.set_page_config(page_title="VeloPulse 3D", page_icon="🚴", layout="wide")
st.title("VeloPulse 3D")
st.caption("FITトレーニング記録をクラウドに蓄積し、区間ごとの傾向を確認できます。")


def get_secret(name: str) -> str:
    try:
        return str(st.secrets[name])
    except Exception:
        return os.getenv(name, "")


url, key = get_secret("SUPABASE_URL"), get_secret("SUPABASE_ANON_KEY")
if not url or not key:
    st.error("Supabase接続設定がありません。READMEの手順を確認してください。")
    st.stop()
access_token = st.session_state.get("access_token")
client_options = ClientOptions(headers={"Authorization": f"Bearer {access_token}"}) if access_token else None
sb: Client = create_client(url, key, client_options)


def clear_login():
    for name in ("access_token", "user"):
        st.session_state.pop(name, None)
    st.rerun()


if "access_token" not in st.session_state:
    login, signup = st.tabs(["ログイン", "新規登録"])
    with login, st.form("login_form"):
        email = st.text_input("メールアドレス")
        password = st.text_input("パスワード", type="password")
        submit = st.form_submit_button("ログイン", type="primary")
        if submit:
            try:
                auth = sb.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.access_token, st.session_state.user = auth.session.access_token, auth.user
                st.rerun()
            except Exception as exc:
                st.error(f"ログインできませんでした: {exc}")
    with signup, st.form("signup_form"):
        email = st.text_input("メールアドレス", key="new_email")
        password = st.text_input("パスワード（6文字以上）", type="password", key="new_password")
        submit = st.form_submit_button("新規登録")
        if submit:
            try:
                result = sb.auth.sign_up({"email": email, "password": password})
                if result.session:
                    st.session_state.access_token, st.session_state.user = result.session.access_token, result.user
                    st.rerun()
                st.success("確認メールを送りました。メールのリンクを開いた後、ログインしてください。")
            except Exception as exc:
                st.error(f"登録できませんでした: {exc}")
    st.stop()

# Attach the user's JWT to PostgREST and Storage requests; the database and bucket RLS policies enforce ownership.

user = st.session_state.user
with st.sidebar:
    st.write(f"ログイン中: {user.email}")
    if st.button("ログアウト"):
        clear_login()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_fit(data: bytes, interval_seconds: int) -> tuple[pd.DataFrame, list[str]]:
    records = []
    fit = fitparse.FitFile(io.BytesIO(data), check_crc=False)
    for message in fit.get_messages("record"):
        record = {field.name: field.value for field in message}
        records.append({
            "Time": record.get("timestamp"), "HR(bpm)": record.get("heart_rate"),
            "CAD(rpm)": record.get("cadence"), "Watts(W)": record.get("power"),
            "Altitude(m)": record.get("enhanced_altitude", record.get("altitude")),
            "Distance(m)": record.get("distance"), "Temperature(C)": record.get("temperature"),
        })
    if not records:
        raise ValueError("FITファイルに記録データがありません。")
    frame = pd.DataFrame(records)
    frame["Time"] = pd.to_datetime(frame["Time"], errors="coerce")
    for column in ["HR(bpm)", "CAD(rpm)", "Watts(W)", "Altitude(m)", "Distance(m)", "Temperature(C)"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["Time"]).sort_values("Time")
    if frame.empty:
        raise ValueError("有効な時刻データがありません。")
    labels = {"CAD(rpm)": "ケイデンス", "HR(bpm)": "心拍数", "Watts(W)": "パワー"}
    missing = [labels[c] for c in labels if frame[c].isna().all()]
    distance_delta, altitude_delta = frame["Distance(m)"].diff(), frame["Altitude(m)"].diff()
    frame["Slope(%)"] = altitude_delta / distance_delta.where(distance_delta > 0) * 100
    frame.loc[frame["Slope(%)"].abs() > 40, "Slope(%)"] = np.nan
    start = frame["Time"].iloc[0]
    groups = ((frame["Time"] - start).dt.total_seconds() // interval_seconds).astype(int)
    averaged = frame.groupby(groups)[["CAD(rpm)", "HR(bpm)", "Watts(W)", "Slope(%)", "Temperature(C)"]].mean()
    averaged.insert(0, "Interval start", [start + pd.Timedelta(seconds=interval_seconds * int(i)) for i in averaged.index])
    averaged.insert(0, "Session", start)
    averaged["Source file"] = ""
    return averaged.reset_index(drop=True)[DATA_COLUMNS], missing


def load_rows():
    return sb.table("training_records").select("id,user_id,activity_date,file_name,file_hash,summary,created_at").order("activity_date", desc=True).execute().data or []


def save_intervals(record_id: int, summary: dict):
    sb.table("training_records").update({"summary": summary}).eq("id", record_id).eq("user_id", user.id).execute()
def row_frame(row: dict) -> pd.DataFrame:
    summary = row.get("summary") or {}
    intervals = summary.get("intervals", [])
    if isinstance(intervals, str):
        frame = pd.read_json(io.StringIO(intervals))
    else:
        frame = pd.DataFrame(intervals)
    for column in DATA_COLUMNS:
        if column not in frame:
            frame[column] = pd.NA
    if not frame.empty:
        frame["Session"] = pd.to_datetime(frame["Session"], errors="coerce")
        frame["Interval start"] = pd.to_datetime(frame["Interval start"], errors="coerce")
        for column in DATA_COLUMNS[2:7]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[DATA_COLUMNS]




with st.sidebar:
    st.subheader("区間平均の設定")
    minutes = st.number_input("分", min_value=0, max_value=1440, value=2, step=1)
    seconds = st.number_input("秒", min_value=0, max_value=59, value=0, step=5)
interval_seconds = int(minutes * 60 + seconds)
if interval_seconds < 1:
    st.sidebar.warning("区間は1秒以上にしてください。")
    st.stop()

with st.sidebar:
    st.subheader("FITファイルを追加")
    uploads = st.file_uploader("FITファイル（複数選択可）", type=["fit"], accept_multiple_files=True)
    save_uploads = uploads and st.button("選択したFITを保存", type="primary")
if save_uploads:
    existing = {r.get("file_hash") for r in load_rows()}
    for uploaded in uploads:
        raw = uploaded.getvalue()
        digest = sha256(raw)
        if digest in existing:
            st.info(f"重複のためスキップしました: {uploaded.name}")
            continue
        try:
            averages, missing = parse_fit(raw, interval_seconds)
            start_time = pd.to_datetime(averages["Session"].iloc[0]).isoformat()
            object_path = f"{user.id}/{digest}.fit"
            sb.storage.from_(BUCKET).upload(object_path, raw, {"content-type": "application/octet-stream", "upsert": "false"})
            summary = {"interval_seconds": interval_seconds, "intervals": averages.to_json(orient="records", date_format="iso")}
            sb.table("training_records").insert({"user_id": user.id, "activity_date": start_time,
                "file_name": uploaded.name, "file_hash": digest, "summary": summary}).execute()
            st.success(f"保存しました: {uploaded.name}（{len(averages)}区間）")
            if missing:
                st.warning(f"{uploaded.name}: {', '.join(missing)}の記録がありません。")
            existing.add(digest)
        except Exception as exc:
            st.error(f"{uploaded.name}: 保存できませんでした: {exc}")

try:
    rows = load_rows()
except Exception as exc:
    st.error(f"履歴を読み込めません: {exc}")
    rows = []

if rows:
    st.subheader("履歴と3Dグラフ")
    current_intervals = {r.get("summary", {}).get("interval_seconds") for r in rows if (r.get("summary") or {}).get("intervals")}
    if current_intervals != {interval_seconds}:
        with st.sidebar:
            st.subheader("再集計")
            reaggregate = st.button("保存済みFITをこの区間で再集計")
            st.caption("区間設定を変えた場合は、保存済みFITを再集計してください。")
        if reaggregate:
            bar = st.progress(0)
            for i, row in enumerate(rows):
                object_path = f"{user.id}/{row['file_hash']}.fit"
                try:
                    raw = sb.storage.from_(BUCKET).download(object_path)
                    averages, _ = parse_fit(raw, interval_seconds)
                    summary = {"interval_seconds": interval_seconds, "intervals": averages.to_json(orient="records", date_format="iso")}
                    save_intervals(row["id"], summary)
                except Exception as exc:
                    st.error(f"{row['file_name']}を再集計できません: {exc}")
                bar.progress((i + 1) / len(rows))
            st.rerun()

    all_data = pd.concat([row_frame(r).assign(_id=r["id"], _file=r["file_name"]) for r in rows], ignore_index=True)
    all_data["Interval start"] = pd.to_datetime(all_data["Interval start"], errors="coerce")
    if all_data["Interval start"].notna().any():
        dt = all_data["Interval start"].dropna()
        max_power_value = all_data["Watts(W)"].max(skipna=True)
        power_max = max(100, int(max_power_value)) if pd.notna(max_power_value) else 100
        hr_value = all_data["HR(bpm)"].max(skipna=True)
        hrmax = max(220, int(hr_value)) if pd.notna(hr_value) else 220
        temp_min_value, temp_max_value = all_data["Temperature(C)"].min(skipna=True), all_data["Temperature(C)"].max(skipna=True)
        temp_min = float(temp_min_value) if pd.notna(temp_min_value) else -10.0
        temp_max = float(temp_max_value) if pd.notna(temp_max_value) else 40.0
        with st.sidebar:
            st.subheader("グラフの絞り込み")
            date_range = st.date_input("期間", value=(dt.min().date(), dt.max().date()))
            power_cols = st.columns(2)
            power_min = power_cols[0].number_input("パワー最小 W", value=0, step=1)
            power_max_filter = power_cols[1].number_input("パワー最大 W", value=power_max, step=1)
            cad_cols = st.columns(2)
            cad_min = cad_cols[0].number_input("ケイデンス最小 rpm", value=0, step=1)
            cad_max = cad_cols[1].number_input("ケイデンス最大 rpm", value=200, step=1)
            hr_cols = st.columns(2)
            hr_min = hr_cols[0].number_input("心拍最小 bpm", value=0, step=1)
            hr_max_filter = hr_cols[1].number_input("心拍最大 bpm", value=hrmax, step=1)
            slope_cols = st.columns(2)
            slope_min = slope_cols[0].number_input("傾斜最小 %", value=-40.0, step=0.1, format="%.1f")
            slope_max = slope_cols[1].number_input("傾斜最大 %", value=40.0, step=0.1, format="%.1f")
            temp_cols = st.columns(2)
            temp_min_filter = temp_cols[0].number_input("気温最小 °C", value=-20.0, step=0.1, format="%.1f")
            temp_max_filter = temp_cols[1].number_input("気温最大 °C", value=50.0, step=0.1, format="%.1f")
        filtered = all_data.copy()
        if isinstance(date_range, tuple) and len(date_range) == 2:
            filtered = filtered[filtered["Interval start"].dt.date.between(date_range[0], date_range[1])]
        filter_ranges = [
            ("Watts(W)", power_min, power_max_filter),
            ("CAD(rpm)", cad_min, cad_max),
            ("HR(bpm)", hr_min, hr_max_filter),
            ("Slope(%)", slope_min, slope_max),
            ("Temperature(C)", temp_min_filter, temp_max_filter),
        ]
        invalid_range = False
        for col, minimum, maximum in filter_ranges:
            if minimum > maximum:
                invalid_range = True
            else:
                filtered = filtered[filtered[col].isna() | filtered[col].between(minimum, maximum)]
            filtered = filtered[filtered[col].isna() | filtered[col].between(bounds[0], bounds[1])]

        # Session level duration filter mirrors the desktop app's ride duration control.
        durations = all_data.groupby("_id")["Interval start"].agg(lambda s: (s.max() - s.min()).total_seconds() / 60 + interval_seconds / 60)
        with st.sidebar:
            st.markdown("**走行時間（分）**")
            duration_cols = st.columns(2)
            duration_min = duration_cols[0].number_input("走行時間最小 分", value=0, step=1)
            duration_max = duration_cols[1].number_input("走行時間最大 分", value=max(10, int(durations.max() if len(durations) else 10)), step=1)
        if duration_min > duration_max:
            invalid_range = True
        else:
            keep_ids = durations[durations.between(duration_min, duration_max)].index
            filtered = filtered[filtered["_id"].isin(keep_ids)]
        if invalid_range:
            st.sidebar.warning("各項目の最小値は最大値以下にしてください。")
            filtered = filtered.iloc[0:0]

        has_hr = filtered["HR(bpm)"].notna().any()
        ycol, ylabel = ("HR(bpm)", "心拍 (bpm)") if has_hr else ("elapsed_min", "経過時間 (分)")
        if not has_hr:
            filtered = filtered.copy()
            filtered["elapsed_min"] = (filtered["Interval start"] - filtered["Session"]).dt.total_seconds() / 60
        graph = filtered.dropna(subset=["CAD(rpm)", ycol, "Watts(W)"])
        if len(graph):
            fig = go.Figure()
            unique = graph.groupby(["CAD(rpm)", ycol], as_index=False)["Watts(W)"].mean()
            if len(unique) >= 3:
                try:
                    fig.add_trace(go.Mesh3d(x=unique["CAD(rpm)"], y=unique[ycol], z=unique["Watts(W)"],
                        intensity=unique["Watts(W)"], colorscale="Jet", opacity=0.72, showscale=True,
                        delaunayaxis="z", colorbar={"title": "Watts"}, name="平均曲面"))
                except Exception:
                    pass
            fig.update_layout(scene={
                "xaxis": {"title": "CAD (rpm)", "showgrid": True, "gridcolor": "#b8bec8", "gridwidth": 1},
                "yaxis": {"title": ylabel, "showgrid": True, "gridcolor": "#b8bec8", "gridwidth": 1},
                "zaxis": {"title": "Watts (W)", "showgrid": True, "gridcolor": "#b8bec8", "gridwidth": 1},
            }, height=650, margin={"l": 0, "r": 0, "t": 25, "b": 0})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("この条件で3D表示できる区間がありません。心拍データがない場合はケイデンスとパワーが必要です。")

    with st.sidebar:
        st.subheader("保存済みライド")
        for row in rows:
            summary = row.get("summary") or {}
            label = f"{str(row.get('activity_date', ''))[:10]} · {row['file_name']} · {summary.get('intervals') and len(pd.read_json(io.StringIO(summary['intervals'])))}区間"
            with st.expander(label):
                st.caption(f"SHA-256: {row['file_hash']}")
                if st.button("このライドを削除（FIT原本も削除）", key=f"delete_{row['id']}"):
                    try:
                        sb.table("training_records").delete().eq("id", row["id"]).eq("user_id", user.id).execute()
                        sb.storage.from_(BUCKET).remove([f"{user.id}/{row['file_hash']}.fit"])
                        st.rerun()
                    except Exception as exc:
                        st.error(f"削除できませんでした: {exc}")
else:
    st.sidebar.info("記録はありません。FITファイルを追加してください。")
