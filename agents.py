import time
import os
from google import genai
from firebase_manager import db, get_full_state, reset_simulation

# --- CONFIGURATION ---
# Load API key from environment variable
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable not set. Copy .env.example to .env and fill in your API key.")
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LIST_MODELS = os.getenv("GEMINI_LIST_MODELS")
USE_MOCK = os.getenv("USE_MOCK_AGENTS", "false").lower() == "true"
LOOP_DELAY = int(os.getenv("LOOP_DELAY", "15"))  # Seconds between iterations

class EnergyAgent:
    def __init__(self, name, role):
        self.name = name
        self.role = role

    def generate_prompt(self, world_state):
        grid = world_state['grid']
        grid_price = grid.get("price", grid.get("price_per_unit", 0))
        me = world_state[self.name]
        sim_time = world_state['simulation'].get('clock', '12:00')
        
        # Calculate Net Energy (Solar - Load)
        net_energy = me.get('solar_input', 0) - me.get('current_load', 0)
        battery = me.get('battery_level', 50)
        
        system_instruction = f"""
        You are the AI Energy Manager for {self.name} ({self.role}) in Pakistan.
        Current Time: {sim_time}
        
        STATUS:
        - Grid Status: {grid['status']} (Price: Rs {grid_price})
        - My Battery: {battery}%
        - Net Generation: {net_energy:.2f} kW (Positive=Excess, Negative=Deficit)
        
        CRITICAL RULES:
        1. LOAD SHEDDING (Grid OFF): You CANNOT sell to Grid.
        2. MASJID CHARITY: If Grid is OFF, Battery > 90%, and you have Excess Energy -> DONATE to "Masjid".
        3. P2P TRADING: If Grid is ON but Expensive (>40), sell to neighbor cheaper.
        
        DECISION:
        Return strict format: "ACTION | REASONING"
        Allowed Actions: "HOLD", "CHARGE_FROM_GRID", "SELL_TO_GRID", "OFFER_P2P", "BUY_P2P", "DONATE_MASJID"
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
            
            # Update Log
            print(f"🤖 {self.name}: {action}")
            db.reference(f'/{self.name}').update({
                "agent_log": reasoning.strip(),
                "last_action": action.strip()
            })
            return action.strip()
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
            
            # 1. AI THINKING
            agent_a = EnergyAgent("house_a", "PRODUCER")
            act_a = agent_a.reason_and_act(state)
            
            agent_b = EnergyAgent("house_b", "CONSUMER")
            act_b = agent_b.reason_and_act(state)
            
            # 2. MARKET MATCHING LOGIC
            # --- MASJID DONATION ---
            if act_a == "DONATE_MASJID":
                print("🕌 SubhanAllah! Energy donated to Masjid.")
                current_donated = state.get('community', {}).get('total_donated_kwh', 0)
                db.reference('/community').update({"total_donated_kwh": current_donated + 0.5})
                db.reference('/visuals').update({"led_mode": "MASJID_FLOW"})
            
            # --- P2P TRADE ---
            elif act_a == "OFFER_P2P" and (act_b == "BUY_P2P" or state['house_b']['battery_level'] < 30):
                print("⚡ P2P MATCH! Executing Trade.")
                # Financials
                price = 35
                db.reference('/house_a/wallet_balance').set(state['house_a']['wallet_balance'] + price)
                db.reference('/house_b/wallet_balance').set(state['house_b']['wallet_balance'] - price)
                # Visuals
                db.reference('/market').update({"active_contract": True, "latest_transaction": "P2P DEAL: Rs 35/unit"})
                db.reference('/visuals').update({"led_mode": "A_TO_B"})
                time.sleep(3) # Let the LED flow
                db.reference('/market').update({"active_contract": False})
                db.reference('/visuals').update({"led_mode": "IDLE"})

            time.sleep(LOOP_DELAY)  # Longer delay to avoid quota exhaustion
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
            time.sleep(LOOP_DELAY)

if __name__ == "__main__":
    if LIST_MODELS:
        for model in client.models.list():
            print(model.name)
    else:
        run_marketplace_loop()