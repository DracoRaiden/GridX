import pandas as pd
import numpy as np
import os

# Get simulation mode from env (full or test)
SIM_MODE = os.getenv("SIMULATION_MODE", "test").lower()

if SIM_MODE == "full":
    # Time range: 24 hours in 5-minute intervals
    times = pd.date_range("2026-02-14 00:00:00", "2026-02-14 23:55:00", freq="5min")
else:
    # Time range: 2 hours in 5-minute intervals (24 steps for quick testing)
    times = pd.date_range("2026-02-14 00:00:00", "2026-02-14 02:00:00", freq="5min")

data = []

for t in times:
    hour = t.hour
    
    # --- 1. GRID STATUS & PRICE ---
    # Load Shedding from 7 PM to 9 PM (19:00 - 21:00)
    is_load_shedding = 1 if (19 <= hour < 21) else 0
    grid_voltage = 0 if is_load_shedding else 220

    # Peak Hours: 6 PM - 10 PM (Rs 46), Off-Peak (Rs 38)
    is_peak = True if (18 <= hour < 22) else False
    grid_price = 46.0 if is_peak else 38.0
    if is_load_shedding:
        grid_price = 0  # Irrelevant, but 0 indicates no grid

    # --- 2. HOUSE A (The Producer - Rich Solar) ---
    # Solar Curve (Bell shape peak at 1pm)
    solar_a = max(0, 5 * np.exp(-0.5 * ((hour - 13) / 3)**2)) 
    # Basic Load (Fridge, Fans)
    load_a = 0.5 + (0.5 if 18 <= hour <= 22 else 0) 
    # Battery logic (Simplified for data generation)
    battery_a = 50 # Will be dynamic in simulation, start middle
    
    # --- 3. HOUSE B (The Consumer - Poor/No Solar) ---
    solar_b = 0 # No panels
    load_b = 1.0 + (1.5 if 18 <= hour <= 22 else 0) # AC turns on at night

    data.append({
        "timestamp": t.strftime("%H:%M:%S"),
        "grid_status": "OFF" if is_load_shedding else "ON",
        "grid_price": grid_price,
        "peak_period": "PEAK" if is_peak else "OFF_PEAK",
        "house_a_solar": round(solar_a, 2),
        "house_a_load": round(load_a, 2),
        "house_b_solar": 0.0,
        "house_b_load": round(load_b, 2)
    })

df = pd.DataFrame(data)
df.to_csv("simulation_data.csv", index=False)
print(f"✅ Dataset generated: simulation_data.csv ({SIM_MODE} mode, {len(df)} steps)")
print(f"⏱️  Duration: {len(df) * 0.25 / 60:.1f} minutes")
print(df.head(10))