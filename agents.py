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
_loop_delay_raw = os.getenv("LOOP_DELAY", "3").strip()
LOOP_DELAY = int(_loop_delay_raw) if _loop_delay_raw else 3  # Seconds between iterations (3s per 30-min step)
SIM_DATA_PATH = os.getenv("SIMULATION_DATA_PATH", "simulation_data.csv")
STEP_MINUTES = float(os.getenv("SIMULATION_STEP_MINUTES", "30"))  # 30-minute simulation steps

BATTERY_CAPACITY_KWH = float(os.getenv("BATTERY_CAPACITY_KWH", "10"))
P2P_TRADE_KWH = float(os.getenv("P2P_TRADE_KWH", "0.5"))
GRID_CHARGE_KWH = float(os.getenv("GRID_CHARGE_KWH", "0.5"))

# --- WAPDA PRICING & TRANSMISSION ---
WAPDA_GENERATION_COST = 11.0  # WAPDA buys 1 unit for 11 rupees
WAPDA_PEAK_PRICE = 48.0       # WAPDA sells 1 unit at 48 rupees during peak
WAPDA_OFFPEAK_PRICE = 38.0    # WAPDA sells 1 unit at 38 rupees off-peak
TRANSMISSION_RENT_PER_UNIT = 18.0  # Wire rental charged to buyer


def _log_to_firebase(message: str, log_type: str = "info", agent: str = "system") -> None:
    """Push console messages to Firebase in real-time."""
    try:
        timestamp = time.strftime("%H:%M:%S")
        db.reference("/logs").push({
            "timestamp": timestamp,
            "agent": agent,
            "type": log_type,
            "message": message,
        })
        print(message)  # Also print to terminal
    except Exception as e:
        print(f"[LOG ERROR] {e}")
        print(message)  # Fallback: just print if Firebase fails


def _write_action_to_firebase(action_code: int, action_label: str, reason: str) -> None:
    """Write the single action code (1-4) to Firebase for ESP consumption."""
    try:
        db.reference("/controls").update({
            "action": int(action_code),
            "action_label": action_label,
            "reason": reason,
            "timestamp": time.strftime("%H:%M:%S"),
        })
    except Exception as e:
        _log_to_firebase(f"❌ Failed to update controls: {e}", "error", "system")


class EnergyAgent:
    def __init__(self, name, role):
        self.name = name
        self.role = role

    def calculate_optimal_price(self, world_state):
        """AI-driven price calculation for P2P selling/buying with mutual profit."""
        grid = world_state['grid']
        grid_price = grid.get("price_per_unit", WAPDA_OFFPEAK_PRICE)
        grid_status = grid.get("status", "ONLINE")
        is_peak = grid_price >= 46.0
        
        # WAPDA reference price (what grid charges)
        wapda_ref = grid_price  # Use actual grid price instead of hardcoded peak/offpeak
        
        if self.role == "PRODUCER":
            # Seller wants profit while keeping buyer profitable
            # Buyer pays: seller_price + transmission_rent
            # For buyer to profit (save money vs WAPDA):
            #   seller_price + transmission_rent < WAPDA_ref - minimum_savings
            
            minimum_buyer_savings = 1.0  # At least 1 rupee profit for buyer (reduced)
            max_seller_price = wapda_ref - TRANSMISSION_RENT_PER_UNIT - minimum_buyer_savings
            
            # Seller wants profit > generation cost
            min_seller_price = WAPDA_GENERATION_COST + 1.0  # At least 1 rupee profit (reduced)
            
            # Seller's bid: take the average of min and max, leaning toward lower to close deals
            seller_bid = round((min_seller_price * 2 + max_seller_price) / 3.0, 1)
            seller_bid = min(seller_bid, max_seller_price)
            seller_bid = max(seller_bid, min_seller_price)
            
            return seller_bid
        
        else:
            # Buyer wants to maximize savings while offering fair price
            # Buyer's total cost: seller_price + transmission_rent
            # Buyer saves if: seller_price + transmission_rent < WAPDA_ref
            
            # Buyer is willing to pay up to WAPDA - 0.5 rupee savings minimum
            max_buyer_bid = wapda_ref - TRANSMISSION_RENT_PER_UNIT - 0.5
            
            # Buyer wants to pay minimum, but not less than generation cost
            # (to be fair to seller, at least seller breaks even)
            min_buyer_bid = WAPDA_GENERATION_COST + 0.5
            
            # Buyer's bid: average, leaning toward max to ensure deal happens
            buyer_bid = round((min_buyer_bid + max_buyer_bid * 2) / 3.0, 1)
            buyer_bid = min(buyer_bid, max_buyer_bid)
            buyer_bid = max(buyer_bid, min_buyer_bid)
            
            return buyer_bid

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
                _log_to_firebase(f"🟢 {self.name}: SELLING  | {reasoning[:50]}...", "decision", self.name)
            elif action == "CHARGE_FROM_GRID":
                _log_to_firebase(f"🔌 {self.name}: CHARGING | {reasoning[:50]}...", "decision", self.name)
            elif action == "DONATE_MASJID":
                _log_to_firebase(f"🕌 {self.name}: CHARITY  | {reasoning[:50]}...", "decision", self.name)
            elif action == "CHARGE_BATTERY":
                _log_to_firebase(f"🔋 {self.name}: STORING  | {reasoning[:50]}...", "decision", self.name)
            else:
                _log_to_firebase(f"⚪ {self.name}: {action}     | {reasoning[:50]}...", "decision", self.name)
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
                _log_to_firebase(f"⚠️ Quota exhausted. Using fallback mock response.", "warning", self.name)
                # Return mock response on quota error
                if self.role == "PRODUCER":
                    return "OFFER_P2P"
                else:
                    return "BUY_P2P"
            else:
                _log_to_firebase(f"❌ Error: {e}", "error", self.name)
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


def _negotiate_p2p_deal(state, agent_a, agent_b, trade_amount):
    """Intelligent negotiation between seller and buyer for mutual profit."""
    grid_price = state["grid"].get("price_per_unit", WAPDA_OFFPEAK_PRICE)
    wapda_ref = grid_price  # Use actual grid price
    
    # Get each party's bid
    seller_bid = agent_a.calculate_optimal_price(state)
    buyer_bid = agent_b.calculate_optimal_price(state)
    
    # Check if deal is possible (buyer willing to pay at least seller's minimum)
    if buyer_bid < seller_bid:
        _log_to_firebase(f"❌ NO P2P DEAL: Seller wants Rs {seller_bid}/unit, Buyer offers Rs {buyer_bid}/unit (no overlap)", "negotiation_failed", "market")
        return None
    
    # Negotiate: meet in the middle
    agreed_price = round((seller_bid + buyer_bid) / 2.0, 1)
    
    # Validate both parties profit
    buyer_total_with_rent = agreed_price + TRANSMISSION_RENT_PER_UNIT
    seller_profit_per_unit = agreed_price - WAPDA_GENERATION_COST
    buyer_savings_per_unit = wapda_ref - buyer_total_with_rent
    
    # Total profit/savings
    seller_total_profit = seller_profit_per_unit * trade_amount
    buyer_total_savings = buyer_savings_per_unit * trade_amount
    
    # Validate profitability (allow zero or small negative for buyer to enable trades)
    if seller_profit_per_unit < -0.5:
        _log_to_firebase(f"❌ NO DEAL: Seller would lose Rs {abs(seller_profit_per_unit):.1f}/unit at price Rs {agreed_price}", "negotiation_failed", "market")
        return None
    
    if buyer_savings_per_unit < -2.0:  # Allow small loss for buyer if grid price is close
        _log_to_firebase(f"❌ NO DEAL: Buyer would lose Rs {abs(buyer_savings_per_unit):.1f}/unit at price Rs {buyer_total_with_rent} (WAPDA: Rs {wapda_ref})", "negotiation_failed", "market")
        return None
    
    # Successful negotiation!
    deal = {
        "agreed_price": agreed_price,
        "seller_bid": seller_bid,
        "buyer_bid": buyer_bid,
        "trade_amount": trade_amount,
        "buyer_total_with_rent": buyer_total_with_rent,
        "wapda_ref": wapda_ref,
        "seller_profit_per_unit": seller_profit_per_unit,
        "seller_total_profit": seller_total_profit,
        "buyer_savings_per_unit": buyer_savings_per_unit,
        "buyer_total_savings": buyer_total_savings,
    }
    
    return deal


def _process_negotiation(state, act_a, act_b):
    grid_status = state["grid"].get("status", "ONLINE")
    grid_price = state["grid"].get("price_per_unit", 0)
    battery_a = state["house_a"].get("battery_level", 50)
    battery_b = state["house_b"].get("battery_level", 50)
    
    power_flow = _calculate_power_flow(state)
    net_a = power_flow["net_a"]
    net_b = power_flow["net_b"]

    action_code = 0
    action_label = "IDLE"
    action_reason = "No profitable or required transfer."

    # --- AUTOMATIC POWER FLOW (ESP32-like logic) ---
    # P2P TRADE: If both agents want to trade AND it's profitable
    # Allow trade if: A wants to sell OR A has higher battery, AND B wants to buy
    p2p_possible = (act_a == "OFFER_P2P" or act_a == "SELL_TO_GRID") and act_b == "BUY_P2P"
    p2p_possible = p2p_possible and (battery_a > 30)  # A must have some battery reserve
    
    if p2p_possible and net_b < 0:
        # House A can sell from battery even if solar deficit
        # Trade amount: what B needs OR what A can spare from battery
        available_from_battery_a = (battery_a - 20) / 100.0 * BATTERY_CAPACITY_KWH  # Keep 20% reserve
        available_from_battery_a = max(0, available_from_battery_a)
        
        trade_amount = min(-net_b, available_from_battery_a, P2P_TRADE_KWH)
        
        if trade_amount < 0.1:
            _write_action_to_firebase(action_code, action_label, "Insufficient battery for P2P.")
            # Fall through to grid purchase
        else:
            # Negotiate a deal
            agent_a = EnergyAgent("house_a", "PRODUCER")
            agent_b = EnergyAgent("house_b", "CONSUMER")
            deal = _negotiate_p2p_deal(state, agent_a, agent_b, trade_amount)
            
            if deal is None:
                _write_action_to_firebase(action_code, action_label, "Negotiation failed.")
                # Fall through to grid purchase
            else:
                # Extract deal terms
                agreed_price = deal["agreed_price"]
                seller_bid = deal["seller_bid"]
                buyer_bid = deal["buyer_bid"]
                buyer_total_with_rent = deal["buyer_total_with_rent"]
                seller_total_profit = deal["seller_total_profit"]
                buyer_total_savings = deal["buyer_total_savings"]
                wapda_ref = deal["wapda_ref"]
                
                # Log detailed negotiation
                _log_to_firebase(
                    f"💰 P2P NEGOTIATION:\n"
                    f"  Seller bid: Rs {seller_bid}/unit | Buyer bid: Rs {buyer_bid}/unit\n"
                    f"  ✅ DEAL @ Rs {agreed_price}/unit\n"
                    f"  Seller profit: Rs {seller_total_profit:.1f} (Rs {deal['seller_profit_per_unit']:.1f}/unit)\n"
                    f"  Buyer saves: Rs {buyer_total_savings:.1f} vs WAPDA (Rs {deal['buyer_savings_per_unit']:.1f}/unit)\n"
                    f"  Buyer pays: Rs {buyer_total_with_rent}/unit | WAPDA: Rs {wapda_ref}/unit",
                    "transaction",
                    "market"
                )
                
                # Update wallets
                seller_gross = agreed_price * trade_amount
                buyer_gross = buyer_total_with_rent * trade_amount
                house_a_wallet = state["house_a"].get("wallet_balance", 0) + seller_gross
                house_b_wallet = state["house_b"].get("wallet_balance", 0) - buyer_gross
                
                # Update batteries (A loses, B gains)
                battery_delta = (trade_amount / BATTERY_CAPACITY_KWH) * 100
                new_battery_a = max(0, battery_a - battery_delta)
                new_battery_b = min(100, battery_b + battery_delta)
                
                updates = {
                    "/house_a/wallet_balance": house_a_wallet,
                    "/house_b/wallet_balance": house_b_wallet,
                    "/house_a/battery_level": new_battery_a,
                    "/house_b/battery_level": new_battery_b,
                    "/market/active_contract": True,
                    "/market/transaction_price": agreed_price,
                    "/market/seller_bid": seller_bid,
                    "/market/buyer_bid": buyer_bid,
                    "/market/latest_transaction": f"P2P: {trade_amount:.2f}kWh @ Rs {agreed_price}/unit | Seller profit: Rs {seller_total_profit:.1f} | Buyer saves: Rs {buyer_total_savings:.1f}",
                    "/market/transaction_details": {
                        "seller": "house_a",
                        "buyer": "house_b",
                        "kwh": trade_amount,
                        "seller_price": agreed_price,
                        "buyer_total_cost": buyer_total_with_rent,
                        "transmission_rent": TRANSMISSION_RENT_PER_UNIT,
                        "seller_profit": round(seller_total_profit, 1),
                        "buyer_savings": round(buyer_total_savings, 1),
                        "wapda_reference": wapda_ref,
                    },
                    "/visuals/led_mode": "A_TO_B",
                }
                db.reference("/").update(updates)
                
                # Update local state
                state["house_a"]["battery_level"] = new_battery_a
                state["house_b"]["battery_level"] = new_battery_b
                state["house_a"]["wallet_balance"] = house_a_wallet
                state["house_b"]["wallet_balance"] = house_b_wallet

                action_code = 1
                action_label = "A_TO_B"
                action_reason = "P2P trade agreed and executed."
                _write_action_to_firebase(action_code, action_label, action_reason)
        
                time.sleep(1)
                db.reference("/market").update({"active_contract": False})
                db.reference("/visuals").update({"led_mode": "IDLE"})
                return
    # --- MASJID DONATION (if excess energy and grid off) ---
    if act_a == "DONATE_MASJID" and grid_status == "BLACKOUT" and net_a > 0.5:
        _log_to_firebase(f"🕌 SubhanAllah! Energy {net_a:.2f} kWh donated to Masjid.", "charity", "house_a")
        current_donated = state.get("community", {}).get("total_donated_kwh", 0)
        db.reference("/community").update({"total_donated_kwh": current_donated + net_a})
        db.reference("/visuals").update({"led_mode": "MASJID_FLOW"})
        action_code = 2
        action_label = "A_TO_MASJID"
        action_reason = "Charity flow enabled during blackout and excess available."
        _write_action_to_firebase(action_code, action_label, action_reason)
        return

    # --- GRID INTERACTION (if no P2P match) ---
    if grid_status == "ONLINE":
        if net_a < 0:  # House A needs power
            cost = grid_price * (-net_a)
            _log_to_firebase(f"🔌 House A charging from grid: {-net_a:.2f} kW @ Rs {grid_price}/unit = Rs {cost:.1f}", "grid_buy", "house_a")
            db.reference("/house_a/wallet_balance").set(
                state["house_a"].get("wallet_balance", 0) - cost
            )
            db.reference("/visuals").update({"led_mode": "GRID_TO_A"})
            action_code = 3
            action_label = "GRID_TO_A"
            action_reason = "House A deficit covered by grid."
        elif net_a > 0 and act_a == "SELL_TO_GRID":  # House A has excess
            revenue = grid_price * net_a
            _log_to_firebase(f"🔋 House A selling to grid: {net_a:.2f} kW @ Rs {grid_price}/unit = Rs {revenue:.1f}", "grid_sell", "house_a")
            db.reference("/house_a/wallet_balance").set(
                state["house_a"].get("wallet_balance", 0) + revenue
            )
        
        if net_b < 0:  # House B needs power
            cost = grid_price * (-net_b)
            _log_to_firebase(f"🔌 House B charging from grid: {-net_b:.2f} kW @ Rs {grid_price}/unit = Rs {cost:.1f}", "grid_buy", "house_b")
            db.reference("/house_b/wallet_balance").set(
                state["house_b"].get("wallet_balance", 0) - cost
            )
            db.reference("/visuals").update({"led_mode": "GRID_TO_B"})
            if action_code == 0:
                action_code = 4
                action_label = "GRID_TO_B"
                action_reason = "House B deficit covered by grid."
    else:
        db.reference("/visuals").update({"led_mode": "BLACKOUT"})

    _write_action_to_firebase(action_code, action_label, action_reason)


def run_marketplace_loop():
    _log_to_firebase("🚀 ECHO-GRID: Agentic Layer Initialized...", "startup", "system")
    _log_to_firebase(f"📊 Loop delay: {LOOP_DELAY}s | Mock mode: {USE_MOCK}", "startup", "system")
    while True:
        try:
            state = get_full_state()
            if not state or "grid" not in state or "simulation" not in state:
                _log_to_firebase("⚠️ Missing world state. Resetting simulation...", "warning", "system")
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
            _log_to_firebase("🛑 Simulation stopped by user.", "info", "system")
            break
        except Exception as e:
            _log_to_firebase(f"⚠️ Loop Error: {e}", "error", "system")
            time.sleep(LOOP_DELAY)


def run_simulation_from_csv(path=SIM_DATA_PATH):
    _log_to_firebase("🚀 ECHO-GRID: Dataset Simulation Initialized...", "startup", "system")
    _log_to_firebase(f"📁 Dataset: {path} | Step: {STEP_MINUTES} min | Mock mode: {USE_MOCK}", "startup", "system")
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
            updates["/simulation/current_row"] = {
                "timestamp": row.get("timestamp", ""),
                "grid_status": row.get("grid_status", ""),
                "grid_price": row.get("grid_price", ""),
                "house_a_solar": row.get("house_a_solar", ""),
                "house_a_load": row.get("house_a_load", ""),
                "house_b_solar": row.get("house_b_solar", ""),
                "house_b_load": row.get("house_b_load", ""),
                "index": idx,
            }
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