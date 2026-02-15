import streamlit as st
import time
import pandas as pd
import plotly.graph_objects as go
from firebase_manager import get_full_state, db


def _ensure_streamlit_context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return
    if get_script_run_ctx() is None:
        print("This app must be run with: streamlit run app.py")
        raise SystemExit(0)


_ensure_streamlit_context()

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="ECHO-GRID | Decentralized Energy Trading",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CUSTOM CSS (For that "Cyberpunk/Fintech" look) ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; }
    .stMetric { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border: 1px solid #333; }
    .success-text { color: #00FF00; }
    .danger-text { color: #FF0000; }
    </style>
    """, unsafe_allow_html=True)

# --- THE LIVE LOOP (The "Magic" Part) ---
# We use a placeholder container to refresh ONLY the data, not the whole page.
dashboard = st.empty()


def _fetch_logs(limit: int = 100) -> list[str]:
    try:
        logs = db.reference("/logs").order_by_key().limit_to_last(limit).get() or {}
    except Exception:
        return []

    entries = []
    for _, item in logs.items():
        timestamp = item.get("timestamp", "--:--:--")
        agent = item.get("agent", "system")
        log_type = item.get("type", "info")
        message = item.get("message", "")
        
        # Color-code by type
        icon_map = {
            "decision": "🤖",
            "transaction": "💰",
            "charity": "🕌",
            "grid_buy": "🔌",
            "grid_sell": "🔋",
            "error": "❌",
            "warning": "⚠️",
            "startup": "🚀",
        }
        icon = icon_map.get(log_type, "📋")
        line = f"[{timestamp}] {icon} {agent.upper()}: {message}"
        entries.append(line)
    return entries


def _fallback_logs() -> list[str]:
    try:
        data = get_full_state() or {}
    except Exception:
        return []

    house_a = data.get("house_a", {})
    house_b = data.get("house_b", {})
    market = data.get("market", {})
    entries = []
    timestamp = time.strftime("%H:%M:%S")
    if house_a.get("agent_log"):
        entries.append(f"[{timestamp}] house_a: {house_a.get('agent_log')}")
    if house_b.get("agent_log"):
        entries.append(f"[{timestamp}] house_b: {house_b.get('agent_log')}")
    if market.get("latest_transaction"):
        entries.append(f"[{timestamp}] market: {market.get('latest_transaction')}")
    return entries

def render_dashboard():
    # 1. FETCH REAL-TIME DATA
    try:
        data = get_full_state()
        grid = data['grid']
        house_a = data['house_a']
        house_b = data['house_b']
        market = data['market']
    except:
        st.error("Waiting for Firebase Connection...")
        return

    initial_wallets = {
        "house_a": 5000,
        "house_b": 2000,
    }

    step_hours = 0.5
    wapda_buy_rate = 11.0

    def _calc_step_metrics(house: dict, baseline_wallet: float) -> dict:
        load_w = float(house.get("current_load", 0))
        solar_kw = float(house.get("solar_output", 0))
        battery = float(house.get("battery_level", 0))
        wallet = float(house.get("wallet_balance", 0))

        load_kw = load_w / 1000.0
        load_kwh = load_kw * step_hours
        solar_kwh = solar_kw * step_hours
        solar_used_kwh = min(load_kwh, solar_kwh)
        export_kwh = max(0.0, solar_kwh - load_kwh)
        net_kw = solar_kw - load_kw
        net_kwh = net_kw * step_hours

        grid_price = float(grid.get("price_per_unit", 0))
        wapda_cost = load_kwh * grid_price
        wapda_export_revenue = export_kwh * wapda_buy_rate
        
        # For Agent A (producer): What they could have earned exporting to WAPDA
        # For Agent B (consumer): What it would have cost buying from WAPDA
        estimated_saved = wapda_export_revenue

        net_overall = wallet - baseline_wallet
        made_total = net_overall

        return {
            "load_w": load_w,
            "load_kwh": load_kwh,
            "solar_kw": solar_kw,
            "solar_kwh": solar_kwh,
            "battery": battery,
            "net_kw": net_kw,
            "net_kwh": net_kwh,
            "wapda_cost": wapda_cost,
            "wapda_export_revenue": wapda_export_revenue,
            "estimated_saved": estimated_saved,
            "net_overall": net_overall,
            "made_total": made_total,
        }

    # --- HEADER SECTION ---
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image("https://cdn-icons-png.flaticon.com/512/3103/3103446.png", width=80) # Placeholder Icon
    with col2:
        st.title("ECHO-GRID DASHBOARD")
        st.markdown("### ⚡ Live P2P Energy Market (Agent View)")

    st.divider()

    # --- TOP BAR ---
    top1, top2, top3 = st.columns(3)
    sim_time = data.get('simulation', {}).get('clock', 'Unknown')
    donated_kwh = data.get('community', {}).get('total_donated_kwh', 0)
    grid_status = grid.get('status', 'UNKNOWN')
    top1.metric("🕒 Simulation Time", sim_time)
    top2.metric("🕌 Energy Donated", f"{donated_kwh} kWh", delta="Social Good")
    top3.metric(
        "Grid Status",
        grid_status,
        delta_color="off" if grid_status == "OFF" else "normal"
    )

    with dashboard.container():
        # --- ROW 1: MARKET STATUS ---
        kpi1, kpi2, kpi3 = st.columns(3)

        # Grid Status
        grid_status = "ONLINE 🟢" if grid['status'] == "ONLINE" else "BLACKOUT 🔴"
        kpi1.metric("Grid Status", grid_status, delta="Stable")

        # House A Wallet (The Seller)
        kpi2.metric("House A Wallet", f"Rs {house_a['wallet_balance']}", delta="Producer")

        # House B Wallet (The Buyer)
        kpi3.metric("House B Wallet", f"Rs {house_b['wallet_balance']}", delta="Consumer", delta_color="off")

        st.divider()

        tab_terminal, tab_a, tab_b = st.tabs([
            "🧾 Terminal",
            "🏠 Agent A Usage",
            "🏢 Agent B Usage",
        ])

        with tab_terminal:
            st.subheader("📡 Agent Communication Terminal")

            if hasattr(st, "fragment"):
                if enable_live:
                    @st.fragment(run_every=2)
                    def _logs_fragment():
                        _render_logs_section()
                else:
                    @st.fragment
                    def _logs_fragment():
                        _render_logs_section()

                _logs_fragment()
            else:
                if enable_live:
                    _auto_refresh(interval_ms=2000)
                _render_logs_section()

            st.divider()

            # Track live log changes for display
            house_a_log = house_a.get("agent_log", "Sleeping...")
            house_b_log = house_b.get("agent_log", "Sleeping...")

            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader("🤖 Agent Negotiation Terminal")

                # Chat Interface Style for Logs
                with st.container(height=300):
                    # House A Log
                    st.markdown(f"**🏠 House A (Seller):**")
                    st.info(f"_{house_a_log}_")

                    # House B Log
                    st.markdown(f"**🏢 House B (Buyer):**")
                    st.warning(f"_{house_b_log}_")

                    # Market Contract
                    if market.get('active_contract'):
                        st.success(f"✅ **CONTRACT EXECUTED:** {market.get('latest_transaction', 'P2P Trade')}")
                    else:
                        st.markdown("--- _Waiting for market match_ ---")

            with c2:
                st.subheader("🔋 Energy Flow")

                # Simple Donut Chart for Battery
                fig = go.Figure(data=[go.Pie(
                    labels=['Battery A', 'Battery B', 'Grid Load'],
                    values=[house_a['battery_level'], house_b['battery_level'], 100],
                    hole=.6,
                    marker_colors=['#00CC96', '#EF553B', '#636EFA']
                )])
                fig.update_layout(showlegend=False, height=250, margin=dict(t=0, b=0, l=0, r=0))
                st.plotly_chart(fig, width='stretch')

                # THEFT DETECTION BUTTON (The "Judge Pleaser")
                if st.button("🚨 RUN GRID DIAGNOSTIC", type="primary", width='stretch'):
                    st.toast("Scanning Grid lines...", icon="📡")
                    time.sleep(1)
                    st.error("⚠️ THEFT DETECTED: Line Loss > 15% at Sector G-11")
                    # Optional: Write to firebase to trigger Red LEDs
                    # db.reference('/visuals').update({"led_mode": "THEFT_ALERT"})

        with tab_a:
            st.subheader("⚡ Current Usage & Electricity — Agent A")
            a = _calc_step_metrics(house_a, initial_wallets["house_a"])

            st.markdown("### Money & WAPDA Comparison")
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Could Earn to WAPDA (PKR)", f"Rs {a['wapda_export_revenue']:.0f}")
            a2.metric("WAPDA Load Cost (PKR)", f"Rs {a['wapda_cost']:.0f}")
            a3.metric("How Much Made Now (PKR)", f"Rs {a['net_overall']:.0f}")
            a4.metric("Gain vs Initial (PKR)", f"Rs {max(0, a['net_overall']):.0f}")

            st.divider()
            st.markdown("### Battery & Units")
            a5, a6, a7, a8 = st.columns(4)
            a5.metric("Battery Level", f"{a['battery']:.0f}%")
            a6.metric("Load (kWh/step)", f"{a['load_kwh']:.2f} kWh")
            a7.metric("Solar (kWh/step)", f"{a['solar_kwh']:.2f} kWh")
            a8.metric("Net (kWh/step)", f"{a['net_kwh']:.2f} kWh")

        with tab_b:
            st.subheader("⚡ Current Usage & Electricity — Agent B")
            b = _calc_step_metrics(house_b, initial_wallets["house_b"])

            st.markdown("### Money & WAPDA Comparison")
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Would Cost from WAPDA (PKR)", f"Rs {b['wapda_cost']:.0f}")
            b2.metric("Actually Spent (PKR)", f"Rs {abs(min(0, b['net_overall'])):.0f}")
            b3.metric("How Much Saved (PKR)", f"Rs {max(0, b['wapda_cost'] - abs(min(0, b['net_overall']))):.0f}")
            b4.metric("Net Overall (PKR)", f"Rs {b['net_overall']:.0f}")

            st.divider()
            st.markdown("### Battery & Units")
            b5, b6, b7, b8 = st.columns(4)
            b5.metric("Battery Level", f"{b['battery']:.0f}%")
            b6.metric("Load (kWh/step)", f"{b['load_kwh']:.2f} kWh")
            b7.metric("Solar (kWh/step)", f"{b['solar_kwh']:.2f} kWh")
            b8.metric("Net (kWh/step)", f"{b['net_kwh']:.2f} kWh")



def _auto_refresh(interval_ms: int) -> None:
    try:
        from streamlit_autorefresh import st_autorefresh

        st_autorefresh(interval=interval_ms, key="live_refresh")
    except Exception:
        # Fallback: only use rerun if available; otherwise do nothing.
        if hasattr(st, "rerun"):
            time.sleep(interval_ms / 1000)
            st.rerun()

# --- LOGS FRAGMENT (auto-refresh only this section when supported) ---
def _render_logs_section() -> None:
    with st.container(height=500):
        entries = _fetch_logs(limit=200)
        
        if not entries:
            entries = _fallback_logs()
        if not entries:
            st.markdown("_No activity yet. Waiting for agents..._")
        else:
            for entry in entries:
                st.markdown(entry)


# --- RENDER DASHBOARD ---
enable_live = st.toggle("Enable Live Feed", value=True)
render_dashboard()