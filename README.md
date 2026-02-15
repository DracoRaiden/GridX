# ⚡ ECHO-GRID: The Autonomous Peer-to-Peer Energy Trading Network

> **"The Energy Crisis is not a Supply Problem; it’s a Distribution Problem."**

---

## 🌍 The Problem (Pakistan Context)

In Pakistan, the energy sector is paralyzed by three critical failures:

1. **Hyper-Inflation:** Consumers pay exorbitant rates (**Rs 65/unit**) during peak hours, while solar owners sell excess power back to the grid for pennies (**Rs 22/unit**).
2. **Grid Instability:** Frequent load shedding leaves entire neighborhoods in the dark, even if adjacent houses have full batteries.
3. **Inefficiency:** Solar energy produced at noon is often curtailed (wasted) because the grid cannot accept it.

## 💡 The Solution: ECHO-GRID

**ECHO-GRID** is a decentralized, **Agentic AI-driven Microgrid Layer** that allows households to trade electricity with each other automatically.

* **Virtual Wheeling:** We use existing utility wires to transport energy but settle transactions digitally.
* **Agentic Negotiation:** Every house gets a **Gemini-Powered AI Agent**. The Agent monitors consumption, predicts prices, and negotiates deals in real-time.
* **Social Good Mode:** If the grid fails and batteries are full, the AI automatically routes excess power to the local **Masjid or Community Center** to prevent waste.

---

## 🏗️ System Architecture

The system consists of three synchronized layers:

1. **The Nervous System (Firebase):** A Realtime Database acting as the single source of truth.
2. **The Brain (Python + Gemini 1.5 Flash):** An Agentic loop that perceives state (Battery, Price, Time) and executes trades.
3. **The Body (ESP32 + LEDs):** Physical hardware that visualizes energy flow and switches relays based on AI commands.

---

## 🚀 Key Features

### 1. 🤖 True Agentic AI

Unlike simple automation (`if price > 50`), our agents **reason**.

> *Agent Log:* "Grid price is Rs 65 (High). My battery is 90%. I will undercut the grid and offer power to my neighbor at Rs 45 to maximize profit."

### 2. 🕌 The "Masjid Mode" (Community Impact)

We address **SDG 11 (Sustainable Cities)**. During load shedding, if a producer has excess energy that cannot be sold to the grid, the AI automatically donates it to a communal load (Masjid/Hospital) rather than letting it go to waste.

### 3. 📱 Fintech Dashboard

A live **Streamlit Dashboard** simulating a banking app, showing real-time wallet balances, energy flow graphs, and the internal thought process of the AI agents.

---

## 🛠️ Hardware Setup (The Physical Twin)

We use an **ESP32** to simulate the smart meter and switchgear.

| Component | Pin (ESP32) | Function |
| --- | --- | --- |
| **LED 1 (Green)** | GPIO 14 | **P2P Trade:** House A  House B |
| **LED 2 (Gold)** | GPIO 25 | **Charity Flow:** House A  Masjid |
| **LED 3 (Red)** | GPIO 26 | **Grid Charge:** Grid  House A |
| **GND** | GND | Common Ground |

---

## 💻 Installation & Usage

### Prerequisites

* Python 3.8+
* ESP32 Dev Board
* Google Gemini API Key
* Firebase Project Credentials

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/echo-grid.git
cd echo-grid

```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
# Or manually:
pip install firebase-admin pandas google-generativeai streamlit plotly watchdog

```

### 3. Configure Credentials

* Place your `serviceAccountKey.json` (Firebase) in the root folder.
* Update `agents.py` with your `GEMINI_API_KEY`.
* Update `ESP32_Final_Fixed.ino` with your WiFi & Firebase Secrets.

### 4. Run the Ecosystem (3 Terminals)

**Terminal 1: The Simulation Clock (Timekeeper)**

```bash
python simulation_clock.py

```

**Terminal 2: The AI Brain (Agents)**

```bash
python agents.py

```

**Terminal 3: The Dashboard (Frontend)**

```bash
streamlit run app.py

```

---

## 📊 Sustainable Development Goals (SDGs)

This project directly targets:

* **SDG 7: Affordable and Clean Energy** (By lowering costs via P2P trading).
* **SDG 11: Sustainable Cities and Communities** (By powering communal centers during blackouts).
* **SDG 12: Responsible Consumption and Production** (By eliminating energy curtailment/waste).

---

## 👥 The Team

**Team Name:** The Grid Guardians (GIKI)

* **Software Lead:** [Your Name] - AI Agents & Backend Logic
* **App Developer:** Ahsan - Streamlit Dashboard & UI/UX
* **Hardware Lead:** Yamman - ESP32 Firmware & Circuitry
* **Hardware Engineer:** Omer - Physical Model Construction

---

*Built with ❤️ at the GitHub x Google Developer Club GIKI Hackathon 2026.*
