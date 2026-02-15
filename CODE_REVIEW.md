# ECHO-GRID Code Review & Issues

## CRITICAL ISSUES ⚠️

### 1. **P2P Trade Economics BROKEN** 🔴

**Problem**: Transmission rent makes P2P unviable

- Grid price: Rs 38-46/kWh
- Transmission rent: Rs 18/kWh (PER UNIT)
- Buyer total cost: `seller_price + 18`
- Even seller's min bid (Rs 12) → buyer pays Rs 30, which is nearly grid price of Rs 38
- **Result**: Very few P2P deals will execute because buyer has insufficient savings

**Impact**: Main feature (P2P trading) rarely happens
**Fix**: Lower transmission rent to Rs 2-5, or make it a percentage instead of fixed

### 2. **Battery State Inconsistency** 🔴

**Problem**: Battery updated twice per cycle

- Line 1 in `_process_negotiation`: Battery changes from `_apply_battery_dynamics(state)`
- Line 2: P2P trade modifies battery again
- Line 3: Grid actions modify battery again
- **Result**: Battery level doesn't reflect true energy balance

**Impact**: Could cause battery to go negative or exceed 100% in edge cases
**Fix**: Calculate all energy flows first, THEN apply to battery once

### 3. **Hardcoded Baseline Wallets** 🟡

**Problem**: In app.py, initial_wallets are hardcoded

```python
initial_wallets = {
    "house_a": 5000,
    "house_b": 2000,
}
```

- Reset simulation resets wallets but app hardcodes baseline
- If agents restart mid-simulation, shown "profit" is wrong

**Impact**: Financial metrics become unreliable
**Fix**: Read initial state from Firebase at app start, not hardcode

### 4. **Step Time Mismatch** 🟡

**Problem**: Inconsistent time calculations

- `agents.py`: `STEP_MINUTES = 0.1s (configurable)`
- `app.py`: `step_hours = 0.5` (hardcoded to 30 min)
- If STEP_MINUTES changes to 5, app calculations break

**Impact**: WAPDA savings calculations wrong
**Fix**: Read STEP_MINUTES from Firebase or .env

---

## LOGIC ISSUES

### 5. **Donation Window Too Narrow** 🟡

```python
hour, minute = map(int, sim_time.split(":"))
is_donation_window = (hour == 15)  # Only EXACTLY hour 15
```

- User requested "3 PM to 4 PM" (15:00 to 16:00)
- Current code only triggers if hour == 15
- With 30-min steps: triggers at 15:00 and 15:30, misses 16:00

**Fix**: Should be `is_donation_window = (hour == 15 or hour == 16 and minute < 30)`

### 6. **Donation Doesn't Deduct Energy** 🟡

```python
if is_donation_window and solar_available and net_a > 0.5:
    donation_amount = min(net_a, state["house_a"].get("solar_output", 0))
    db.reference("/community").update({"total_donated_kwh": current_donated + donation_amount})
```

- Increments donation counter BUT doesn't deduct from House A battery/wallet
- House A gets free energy credit → unfair advantage
- No transaction logged

**Fix**: Should deduct battery or apply wallet credit

### 7. **Mock Agent Always Optimistic** 🟡

```python
if USE_MOCK:
    if self.role == "PRODUCER":
        action = "OFFER_P2P"  # Always tries to sell
    else:
        action = "BUY_P2P"    # Always tries to buy
```

- Mock agents never hold energy
- Mock agents ignore grid price, battery level, time of day
- Should respect night-time and grid conditions

**Fix**: Add logic to check time/conditions before deciding

### 8. **House A Initial Battery Doesn't Match CSV** 🟡

- `firebase_manager.py`: House A starts with 85% battery
- `simulation_data.csv`: Starts at 00:00 (midnight) with 0.0 kW solar
- At midnight, House A should be discharging battery, not starting full

**Impact**: First few steps show unrealistic battery behavior
**Fix**: Start House A at 50% battery or adjust CSV to start at sunrise

### 9. **Grid Interaction Missing Error Handling** 🟡

```python
if net_a < 0 and not p2p_trade_happened:
    cost = grid_price * (-net_a)
    db.reference("/house_a/wallet_balance").set(
        state["house_a"].get("wallet_balance", 0) - cost
    )
```

- What if wallet goes negative? No check!
- What if grid is BLACKOUT? Agents still try to buy

**Fix**: Add guards for wallet < 0 and grid status checks

### 10. **Night Selling Prevention Incomplete** 🟠

- Agent prompt says "never sell at night"
- Code validates `solar_available > 0.1` AFTER agent decides
- If agent outputs OFFER_P2P despite no solar, it's rejected silently with warning
- Better: Prevent agent from suggesting it in first place

**Impact**: Wasted LLM call, poor agent training
**Fix**: Embed time-of-day check earlier in prompt or state

---

## MISSING FEATURES

### 11. **No Energy Debt/Loan System** 🔵

- Agents can't go into debt with grid
- This is fine for MVP but limits realism

### 12. **No Charging/Discharging Rate Limits** 🔵

- Battery can charge/discharge unlimited kWh per step
- Real hardware has limits (e.g., max 2kW charger)

### 13. **No Peak/Offpeak Agent Behavior** 🔵

- Agents don't prioritize selling during peak hours
- Should boost bids during PEAK_PERIOD

### 14. **No Load Forecast** 🔵

- Agents react to current state, don't predict future loads
- Real agents would pre-charge before peak

---

## FRONTEND ISSUES

### 15. **Battery Level Chart Misleading** 🟡

```python
fig = go.Figure(data=[go.Pie(
    labels=['Battery A', 'Battery B', 'Grid Load'],
    values=[house_a['battery_level'], house_b['battery_level'], 100],
```

- Compares battery % directly to 100 (grid load fixed)
- Pie chart is not right visualization for time-series energy
- User gets false sense of relative storage

**Fix**: Use bar chart or line chart for battery trends

### 16. **No Transaction History Tab** 🔵

- No way to see past P2P trades, only current state
- Users can't analyze "did I get good deals?"

### 17. **Logs Only Show Last 200** 🟡

- Very active simulation will miss early events
- Should either store more or have pagination

---

## ARCHITECTURAL ISSUES

### 18. **Simulation Clock Not Synchronized** 🟡

- `simulation_clock.py` exists but is UNUSED
- Main flow uses CSV timestamps in `agents.py`
- Two separate time systems?

**Fix**: Remove unused `simulation_clock.py` or use it consistently

### 19. **Orchestrator Empty** 🟡

- `orchestrator.py` file exists but is empty
- Should contain main entry point or it's duplication

---

## POSITIVE ASPECTS ✅

✅ Firebase for real-time state sync  
✅ Mock mode for testing without API quota  
✅ P2P negotiation logic with profit checking  
✅ Night-time solar detection in agent prompt  
✅ Community charity tracking  
✅ Organized CSV simulation data  
✅ LED control for physical hardware integration

---

## RECOMMENDATIONS (Priority Order)

1. **FIX**: Transmission rent economics (enable viable P2P)
2. **FIX**: Battery state consistency (single update per cycle)
3. **FIX**: Donation window to cover full hour
4. **FIX**: Add wallet < 0 guards
5. **IMPROVE**: Mock agent logic (respect grid and time)
6. **IMPROVE**: Sync STEP_MINUTES between agents.py and app.py
7. **ADD**: Transaction history view in dashboard
8. **REMOVE**: Dead code (orchestrator.py, simulation_clock.py)
9. **ADD**: Peak-period pricing strategy for agents
10. **ADD**: Energy debt system (optional for later)

---

## Test Scenarios to Verify

- [ ] House B buys from House A during day (should save money vs grid)
- [ ] Agents hold energy during night (no selling)
- [ ] Masjid donation triggers between 15:00-16:00 with solar
- [ ] Wallet never goes negative
- [ ] Battery syncs across P2P + grid + natural discharge
- [ ] BLACKOUT prevents grid transactions
- [ ] Transmission rent < 4 rupees to make P2P viable
