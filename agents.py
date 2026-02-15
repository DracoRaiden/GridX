import time
import os
import csv
from google import genai
from firebase_manager import db, get_full_state, reset_simulation


def _load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()

# --- CONFIGURATION ---
# Load API key from environment variable
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable not set. Copy .env.example to .env and fill in your API key.")
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LIST_MODELS = os.getenv("GEMINI_LIST_MODELS")
USE_MOCK = os.getenv("USE_MOCK_AGENTS", "false").lower() == "true"
_loop_delay_raw = os.getenv("LOOP_DELAY", "15").strip()
LOOP_DELAY = int(_loop_delay_raw) if _loop_delay_raw else 15  # Seconds between iterations
SIM_DATA_PATH = os.getenv("SIMULATION_DATA_PATH", "simulation_data.csv")
STEP_MINUTES = float(os.getenv("SIMULATION_STEP_MINUTES", "0.25"))

BATTERY_CAPACITY_KWH = float(os.getenv("BATTERY_CAPACITY_KWH", "10"))
P2P_TRADE_KWH = float(os.getenv("P2P_TRADE_KWH", "0.5"))
GRID_CHARGE_KWH = float(os.getenv("GRID_CHARGE_KWH", "0.5"))

class EnergyAgent:
    def __init__(self, name, role):
        self.name = name
        self.role = role

    def generate_prompt(self, world_state):
        grid = world_state['grid']
        grid_price = grid.get("price", grid.get("price_per_unit", 0))
        grid_status = grid.get("status", "ONLINE")
        me = world_state[self.name]
        sim_time = world_state['simulation'].get('clock', '12:00')

          # Calculate Net Energy (Solar - Load)
        solar = me.get('solar_output', me.get('solar_input', 0))
        load = me.get('current_load', 0)
        net_energy = solar - load
        battery = me.get('battery_level', 50)
        is_night = solar < 0.1
        
        system_instruction = f"""
          You are the Smart Energy Agent for {self.name} ({self.role}) in Pakistan.
        Current Time: {sim_time}
        
          DATA:
          - Grid Status: {grid_status} (Price: Rs {grid_price})
          - Solar Output: {solar:.2f} kW
          - House Load: {load:.2f} kW
          - Battery: {battery}%
          - Net Generation: {net_energy:.2f} kW (Positive=Excess, Negative=Deficit)
          - Night Mode: {is_night}

          STRICT RULES:
          1. NIGHT MODE (Solar ~ 0): DO NOT sell. You are consuming.
              - If Battery < 40% and Price is Cheap -> ACTION: "CHARGE_FROM_GRID"
              - If Battery is fine -> ACTION: "HOLD"

          2. DAY MODE (Solar > Load): You have excess power.
              - If Grid is Expensive (>40) -> ACTION: "OFFER_P2P" (Sell to neighbor).
              - If Grid is Cheap (<30) -> ACTION: "CHARGE_BATTERY" (Store it).

          3. LOAD SHEDDING (Grid OFF):
              - If Battery > 90% -> ACTION: "DONATE_MASJID"
              - Else -> ACTION: "HOLD" (Conserve power).

          DECISION FORMAT:
          Return exactly: "ACTION | REASONING"
          Allowed Actions: "HOLD", "CHARGE_FROM_GRID", "CHARGE_BATTERY", "SELL_TO_GRID", "OFFER_P2P", "BUY_P2P", "DONATE_MASJID"
        """
        return system_instruction

    def reason_and_act(self, world_state):
        prompt = self.generate_prompt(world_state)
        try:
            if USE_MOCK:
                # Use mock responses to avoid API quota
                if self.role == "PRODUCER":
                    action = "OFFER_P2P"
                    reasoning = "Battery high, offering P2P trade"
                else:
                    action = "BUY_P2P"
                    reasoning = "Battery low, seeking P2P purchase"
            else:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                )
                raw_output = (response.text or "").strip()
                if "|" in raw_output:
                    action, reasoning = raw_output.split("|", 1)
                else:
                    action = "HOLD"
                    reasoning = raw_output

            action = action.strip()
            reasoning = reasoning.strip()

            # Update Log
            if action == "OFFER_P2P":
                print(f"🟢 {self.name}: SELLING  | {reasoning[:50]}...")
            elif action == "CHARGE_FROM_GRID":
                print(f"🔌 {self.name}: CHARGING | {reasoning[:50]}...")
            elif action == "DONATE_MASJID":
                print(f"🕌 {self.name}: CHARITY  | {reasoning[:50]}...")
            elif action == "CHARGE_BATTERY":
                print(f"🔋 {self.name}: STORING  | {reasoning[:50]}...")
            else:
                print(f"⚪ {self.name}: {action}     | {reasoning[:50]}...")
            db.reference(f'/{self.name}').update({
                "agent_log": reasoning,
                "last_action": action
            })
            db.reference("/logs").push({
                "timestamp": time.strftime("%H:%M:%S"),
                "agent": self.name,
                "action": action,
                "message": reasoning,
            })
            return action
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print(f"⚠️ Quota exhausted. Using fallback mock response.")
                # Return mock response on quota error
                if self.role == "PRODUCER":
                    return "OFFER_P2P"
                else:
                    return "BUY_P2P"
            else:
                print(f"❌ Error: {e}")
                return "HOLD"

def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _battery_delta_percent(net_kw, step_minutes):
    step_hours = step_minutes / 60.0
    delta_kwh = net_kw * step_hours
    return (delta_kwh / BATTERY_CAPACITY_KWH) * 100.0


def _negotiate_p2p_price(grid_price, grid_status, seller_battery, buyer_battery):
    if grid_status == "ONLINE":
        base = grid_price
    else:
        base = max(grid_price, 70.0)

    seller_floor = max(15.0, base * 0.75)
    if seller_battery < 40:
        seller_floor += (40 - seller_battery) * 0.4

    buyer_ceiling = base * (0.95 if grid_status == "ONLINE" else 1.15)
    if buyer_battery < 30:
        buyer_ceiling += (30 - buyer_battery) * 0.6

    if buyer_ceiling < seller_floor:
        return None

    price = (seller_floor + buyer_ceiling) / 2.0
    return round(price, 1)


def _load_simulation_rows(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Simulation dataset not found: {path}")

    with open(path, "r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        return list(reader)


def _update_world_from_row(row, state):
    grid_status = "ONLINE" if row["grid_status"].strip().upper() == "ON" else "BLACKOUT"
    grid_price = float(row["grid_price"])
    voltage = 220 if grid_status == "ONLINE" else 0

    house_a_solar = float(row["house_a_solar"])
    house_a_load = float(row["house_a_load"])
    house_b_solar = float(row["house_b_solar"])
    house_b_load = float(row["house_b_load"])

    updates = {
        "/grid/status": grid_status,
        "/grid/price_per_unit": grid_price,
        "/grid/voltage": voltage,
        "/house_a/solar_output": house_a_solar,
        "/house_a/current_load": house_a_load,
        "/house_b/solar_output": house_b_solar,
        "/house_b/current_load": house_b_load,
        "/simulation/clock": row["timestamp"].strip(),
    }

    state["grid"]["status"] = grid_status
    state["grid"]["price_per_unit"] = grid_price
    state["grid"]["voltage"] = voltage
    state["house_a"]["solar_output"] = house_a_solar
    state["house_a"]["current_load"] = house_a_load
    state["house_b"]["solar_output"] = house_b_solar
    state["house_b"]["current_load"] = house_b_load
    state["simulation"]["clock"] = row["timestamp"].strip()

    return updates


def _apply_battery_dynamics(state):
    updates = {}
    for house_key in ("house_a", "house_b"):
        house = state[house_key]
        net_kw = house.get("solar_output", 0) - house.get("current_load", 0)
        delta_percent = _battery_delta_percent(net_kw, STEP_MINUTES)
        new_level = _clamp(house.get("battery_level", 50) + delta_percent, 0, 100)
        house["battery_level"] = new_level
        updates[f"/{house_key}/battery_level"] = new_level

    return updates


def _apply_grid_action(state, house_key, action):
    grid = state["grid"]
    if grid.get("status") != "ONLINE":
        return

    grid_price = grid.get("price_per_unit", 0)
    house = state[house_key]
    wallet = house.get("wallet_balance", 0)

    if action == "CHARGE_FROM_GRID":
        cost = grid_price * GRID_CHARGE_KWH
        house["wallet_balance"] = wallet - cost
        db.reference(f"/{house_key}/wallet_balance").set(house["wallet_balance"])
        house["battery_level"] = _clamp(house.get("battery_level", 50) + (GRID_CHARGE_KWH / BATTERY_CAPACITY_KWH) * 100, 0, 100)
        db.reference(f"/{house_key}/battery_level").set(house["battery_level"])
    elif action == "SELL_TO_GRID":
        revenue = grid_price * GRID_CHARGE_KWH
        house["wallet_balance"] = wallet + revenue
        db.reference(f"/{house_key}/wallet_balance").set(house["wallet_balance"])
        house["battery_level"] = _clamp(house.get("battery_level", 50) - (GRID_CHARGE_KWH / BATTERY_CAPACITY_KWH) * 100, 0, 100)
        db.reference(f"/{house_key}/battery_level").set(house["battery_level"])


def _execute_p2p_trade(state, price):
    house_a = state["house_a"]
    house_b = state["house_b"]

    total_cost = price * P2P_TRADE_KWH
    house_a["wallet_balance"] = house_a.get("wallet_balance", 0) + total_cost
    house_b["wallet_balance"] = house_b.get("wallet_balance", 0) - total_cost
    db.reference("/house_a/wallet_balance").set(house_a["wallet_balance"])
    db.reference("/house_b/wallet_balance").set(house_b["wallet_balance"])

    battery_delta = (P2P_TRADE_KWH / BATTERY_CAPACITY_KWH) * 100
    house_a["battery_level"] = _clamp(house_a.get("battery_level", 50) - battery_delta, 0, 100)
    house_b["battery_level"] = _clamp(house_b.get("battery_level", 50) + battery_delta, 0, 100)
    db.reference("/house_a/battery_level").set(house_a["battery_level"])
    db.reference("/house_b/battery_level").set(house_b["battery_level"])

    db.reference("/market").update({
        "active_contract": True,
        "transaction_price": price,
        "latest_transaction": f"P2P DEAL: Rs {price}/kWh for {P2P_TRADE_KWH} kWh",
    })
    db.reference("/visuals").update({"led_mode": "A_TO_B"})
    time.sleep(1)
    db.reference("/market").update({"active_contract": False})
    db.reference("/visuals").update({"led_mode": "IDLE"})


def _calculate_power_flow(state):
    """Calculate net power for each house and determine energy flow."""
    house_a_solar = state["house_a"].get("solar_output", 0)
    house_a_load = state["house_a"].get("current_load", 0)
    house_b_solar = state["house_b"].get("solar_output", 0)
    house_b_load = state["house_b"].get("current_load", 0)
    
    net_a = house_a_solar - house_a_load
    net_b = house_b_solar - house_b_load
    
    return {
        "house_a_solar": house_a_solar,
        "house_a_load": house_a_load,
        "house_b_solar": house_b_solar,
        "house_b_load": house_b_load,
        "net_a": net_a,
        "net_b": net_b,
    }


def _process_negotiation(state, act_a, act_b):
    grid_status = state["grid"].get("status", "ONLINE")
    grid_price = state["grid"].get("price_per_unit", 0)
    battery_a = state["house_a"].get("battery_level", 50)
    battery_b = state["house_b"].get("battery_level", 50)
    
    power_flow = _calculate_power_flow(state)
    net_a = power_flow["net_a"]
    net_b = power_flow["net_b"]

    # --- AUTOMATIC POWER FLOW (ESP32-like logic) ---
    # If House A has excess and House B has deficit: direct P2P trade
    if net_a > 0 and net_b < 0:
        trade_amount = min(net_a, -net_b)
        price = _negotiate_p2p_price(grid_price, grid_status, battery_a, battery_b)
        
        if price is not None:
            print(f"⚡ AUTO P2P TRADE: {trade_amount:.2f} kW @ Rs {price}/kWh")
            
            # Update wallets
            total_cost = price * trade_amount
            house_a_wallet = state["house_a"].get("wallet_balance", 0) + total_cost
            house_b_wallet = state["house_b"].get("wallet_balance", 0) - total_cost
            
            updates = {
                "/house_a/wallet_balance": house_a_wallet,
                "/house_b/wallet_balance": house_b_wallet,
                "/market/active_contract": True,
                "/market/transaction_price": price,
                "/market/latest_transaction": f"P2P DEAL: {trade_amount:.2f} kWh @ Rs {price}/kWh",
                "/visuals/led_mode": "A_TO_B",
            }
            db.reference("/").update(updates)
            db.reference("/market").update({"active_contract": False})
            db.reference("/visuals").update({"led_mode": "IDLE"})
            return

    # --- MASJID DONATION (if excess energy and grid off) ---
    if act_a == "DONATE_MASJID" and grid_status == "BLACKOUT" and net_a > 0.5:
        print("🕌 SubhanAllah! Energy donated to Masjid.")
        current_donated = state.get("community", {}).get("total_donated_kwh", 0)
        db.reference("/community").update({"total_donated_kwh": current_donated + net_a})
        db.reference("/visuals").update({"led_mode": "MASJID_FLOW"})
        return

    # --- GRID INTERACTION (if no P2P match) ---
    if grid_status == "ONLINE":
        if net_a < 0:  # House A needs power
            print(f"🔌 House A charging from grid: {-net_a:.2f} kW")
            cost = grid_price * (-net_a)
            db.reference("/house_a/wallet_balance").set(
                state["house_a"].get("wallet_balance", 0) - cost
            )
            db.reference("/visuals").update({"led_mode": "GRID_TO_A"})
        elif net_a > 0:  # House A has excess
            print(f"🔋 House A selling to grid: {net_a:.2f} kW @ Rs {grid_price}")
            revenue = grid_price * net_a
            db.reference("/house_a/wallet_balance").set(
                state["house_a"].get("wallet_balance", 0) + revenue
            )
        
        if net_b < 0:  # House B needs power
            print(f"🔌 House B charging from grid: {-net_b:.2f} kW")
            cost = grid_price * (-net_b)
            db.reference("/house_b/wallet_balance").set(
                state["house_b"].get("wallet_balance", 0) - cost
            )
            db.reference("/visuals").update({"led_mode": "GRID_TO_B"})
    else:
        db.reference("/visuals").update({"led_mode": "BLACKOUT"})


def run_marketplace_loop():
    print("🚀 ECHO-GRID: Agentic Layer Initialized...")
    print(f"📊 Loop delay: {LOOP_DELAY}s | Mock mode: {USE_MOCK}")
    while True:
        try:
            state = get_full_state()
            if not state or "grid" not in state or "simulation" not in state:
                print("⚠️ Missing world state. Resetting simulation...")
                reset_simulation()
                time.sleep(1)
                continue

            _apply_battery_dynamics(state)

            agent_a = EnergyAgent("house_a", "PRODUCER")
            act_a = agent_a.reason_and_act(state)

            agent_b = EnergyAgent("house_b", "CONSUMER")
            act_b = agent_b.reason_and_act(state)

            _process_negotiation(state, act_a, act_b)

            time.sleep(LOOP_DELAY)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
            time.sleep(LOOP_DELAY)


def run_simulation_from_csv(path=SIM_DATA_PATH):
    print("🚀 ECHO-GRID: Dataset Simulation Initialized...")
    print(f"📁 Dataset: {path} | Step: {STEP_MINUTES} min | Mock mode: {USE_MOCK}")
    rows = _load_simulation_rows(path)
    if not rows:
        raise RuntimeError("Simulation dataset is empty.")

    reset_simulation()

    try:
        for idx, row in enumerate(rows):
            state = get_full_state() or {}
            if not state:
                reset_simulation()
                state = get_full_state() or {}

            updates = _update_world_from_row(row, state)
            updates.update(_apply_battery_dynamics(state))
            db.reference("/").update(updates)

            # Get agent decisions
            agent_a = EnergyAgent("house_a", "PRODUCER")
            act_a = agent_a.reason_and_act(state)

            agent_b = EnergyAgent("house_b", "CONSUMER")
            act_b = agent_b.reason_and_act(state)

            # Process negotiation with power-flow awareness (ESP32 model)
            _process_negotiation(state, act_a, act_b)

            print(f"[Step {idx+1}/{len(rows)}] {row['timestamp']} | Grid: {row['grid_status']} @ Rs {row['grid_price']}")
            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        print("⏹️ Simulation stopped by user.")

if __name__ == "__main__":
    if LIST_MODELS:
        for model in client.models.list():
            print(model.name)
    else:
        if os.path.exists(SIM_DATA_PATH):
            run_simulation_from_csv(SIM_DATA_PATH)
        else:
            run_marketplace_loop()