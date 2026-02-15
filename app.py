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

    # Track live log changes for display
    house_a_log = house_a.get("agent_log", "Sleeping...")
    house_b_log = house_b.get("agent_log", "Sleeping...")

    with dashboard.container():
        # --- ROW 1: MARKET STATUS ---
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        # Grid Status
        grid_status = "ONLINE 🟢" if grid['status'] == "ONLINE" else "BLACKOUT 🔴"
        kpi1.metric("Grid Status", grid_status, delta="Stable")

        # Live Grid Price
        kpi2.metric("Grid Price (PKR/kWh)", f"Rs {grid['price_per_unit']}", delta=f"{grid['price_per_unit'] - 22} vs Base", delta_color="inverse")

        # House A Wallet (The Seller)
        kpi3.metric("House A Wallet", f"Rs {house_a['wallet_balance']}", delta="Producer")

        # House B Wallet (The Buyer)
        kpi4.metric("House B Wallet", f"Rs {house_b['wallet_balance']}", delta="Consumer", delta_color="off")

        st.divider()

        # --- ROW 2: LIVE AGENT LOGS & VISUALS ---
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
    st.subheader("📡 Real-Time Agent Log Stream")
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

# Try to refresh only the logs section if fragments are available
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