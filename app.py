import streamlit as st
import base64
import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd

# --- CONFIGURATION ---
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
except KeyError:
    st.error("API Key not found. Please configure your .streamlit/secrets.toml file.")
    st.stop()

# Initialize Session State for History
if 'history' not in st.session_state:
    st.session_state.history = []

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://www.google.com.au/"
}

# --- HELPER FUNCTIONS ---
def get_search_query_from_image(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "Identify the brand and model. Output ONLY a concise eBay search string. If unsure, output 'ITEM_NOT_RECOGNIZED'."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}}]}
        ],
        "max_tokens": 30
    }
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content'].strip()
    except:
        return None

def scrape_ebay_listings(search_query):
    query_formatted = search_query.replace(" ", "+")
    sold_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}&LH_Complete=1&LH_Sold=1&LH_PrefLoc=0"
    try:
        response = requests.get(sold_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('li', class_='s-item')
        data_points = []
        for item in items:
            if "s-item__pl-on-bottom" in item.get('class', []): continue
            title = item.find('div', class_='s-item__title')
            price = item.find('span', class_='s-item__price')
            link = item.find('a', class_='s-item__link')
            if title and price and link:
                price_text = price.text.replace(',', '')
                if "to" not in price_text and "$" in price_text:
                    match = re.search(r'\d+\.\d+', price_text)
                    if match:
                        data_points.append({"Keep": True, "Title": title.text, "Price": float(match.group()), "Link": link['href']})
        return data_points[:15]
    except:
        return []

# --- STREAMLIT UI ---
st.set_page_config(page_title="Arbitrage Scanner", layout="centered")
st.title("📸 Arbitrage Scanner")

# 1. SIDEBAR: LiDAR SHIPPING CALCULATOR
with st.sidebar:
    st.header("📦 Shipping (LiDAR)")
    l_cm = st.number_input("Length (cm):", min_value=1.0, value=20.0)
    w_cm = st.number_input("Width (cm):", min_value=1.0, value=15.0)
    h_cm = st.number_input("Height (cm):", min_value=1.0, value=10.0)
    weight_kg = st.number_input("Weight (kg):", min_value=0.1, value=0.5)
    
    cubic_kg = (l_cm * w_cm * h_cm) / 4000
    chargeable_kg = max(weight_kg, cubic_kg)
    
    if chargeable_kg <= 5:
        vol = l_cm * w_cm * h_cm
        if vol <= 2400: final_ship = 11.30
        elif vol <= 7300: final_ship = 15.20
        elif vol <= 16500: final_ship = 19.50
        else: final_ship = 23.30
    else:
        final_ship = 15.00 + ((chargeable_kg - 5) * 2.50)
    st.metric("Est. Shipping", f"${final_ship:.2f}")

# 2. MAIN INPUTS
picture = st.camera_input("Scan Item")
store_price = st.number_input("Store Price (AUD):", min_value=0.0, format="%.2f")

# 3. ANALYSIS LOGIC
if picture and store_price > 0:
    with st.spinner("Analyzing..."):
        search_query = get_search_query_from_image(picture.getvalue())
        
    if search_query and search_query != "ITEM_NOT_RECOGNIZED":
        st.success(f"Identified: **{search_query}**")
        raw_data = scrape_ebay_listings(search_query)
            
        if raw_data:
            st.subheader("🔍 Verify Market Data")
            df = pd.DataFrame(raw_data)
            edited_df = st.data_editor(df, column_config={"Keep": st.column_config.CheckboxColumn(default=True), "Link": st.column_config.LinkColumn("View"), "Price": st.column_config.NumberColumn(format="$%.2f")}, disabled=["Title", "Price", "Link"], hide_index=True, use_container_width=True)

            verified_points = edited_df[edited_df["Keep"]]
            if not verified_points.empty:
                avg_val = verified_points["Price"].mean()
                profit = (avg_val * 0.85) - store_price - final_ship
                
                st.divider()
                c1, c2 = st.columns(2)
                c1.metric("Market Value", f"${avg_val:.2f}")
                c2.metric("Arbitrage Value", f"${profit:.2f}", delta=f"{profit:.2f}")

                # --- NEW: SAVE TO HISTORY BUTTON ---
                if st.button("💾 Save to History"):
                    st.session_state.history.append({
                        "Item": search_query,
                        "Sticker Price": store_price,
                        "Market Value": round(avg_val, 2),
                        "Shipping": round(final_ship, 2),
                        "Profit": round(profit, 2)
                    })
                    st.toast(f"Saved {search_query} to history!")
            else:
                st.warning("Please keep at least one listing.")
        else:
            st.warning("No listings found.")

# --- 4. HISTORY SECTION ---
st.divider()
st.subheader("📜 Sourcing History")
if st.session_state.history:
    history_df = pd.DataFrame(st.session_state.history)
    
    # Display the history table with fancy formatting
    st.dataframe(
        history_df,
        column_config={
            "Sticker Price": st.column_config.NumberColumn(format="$%.2f"),
            "Market Value": st.column_config.NumberColumn(format="$%.2f"),
            "Shipping": st.column_config.NumberColumn(format="$%.2f"),
            "Profit": st.column_config.NumberColumn(format="$%.2f"),
        },
        hide_index=True,
        use_container_width=True
    )
    
    if st.button("🗑️ Clear History"):
        st.session_state.history = []
        st.rerun()
else:
    st.info("Your history is empty. Save a calculation to see it here.")                "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}}]
            }
        ],
        "max_tokens": 30
    }
    
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        st.error(f"OpenAI API Error: {e}")
        return None

def get_result_count(soup):
    count_heading = soup.find('h1', class_='srp-controls__count-heading')
    if count_heading:
        # Extracts numbers and commas
        match = re.search(r'([\d,]+)', count_heading.text)
        if match:
            return int(match.group(1).replace(',', ''))
    return 0

def analyze_market(search_query):
    query_formatted = search_query.replace(" ", "+")
    active_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}"
    sold_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}&LH_Complete=1&LH_Sold=1"

    # 1. Fetch Active Listings
    response_active = requests.get(active_url, headers=HEADERS)
    active_count = get_result_count(BeautifulSoup(response_active.text, 'html.parser'))

    # Anti-bot delay
    time.sleep(1)

    # 2. Fetch Sold Listings
    response_sold = requests.get(sold_url, headers=HEADERS)
    soup_sold = BeautifulSoup(response_sold.text, 'html.parser')
    sold_count = get_result_count(soup_sold)

    # 3. Robust Price Parsing & Relevance Filtering
    items = soup_sold.find_all('li', class_='s-item')
    sold_prices = []
    query_words = search_query.lower().split()

    for item in items:
        # Skip the "Shop on eBay" hidden first element
        if "s-item__pl-on-bottom" not in item.get('class', []):
            title_elem = item.find('div', class_='s-item__title')
            price_elem = item.find('span', class_='s-item__price')
            
            if not title_elem or not price_elem: 
                continue

            title_text = title_elem.text.lower()
            
            # RELEVANCE FILTER: Ensure at least 50% of our search terms are in the listing title
            match_score = sum(1 for word in query_words if word in title_text)
            if match_score / len(query_words) < 0.5:
                continue

            price_text = price_elem.text
            # Skip price ranges, extract only the clean float
            if "to" not in price_text and "$" in price_text:
                price_match = re.search(r'\d+\.\d+', price_text.replace(',', ''))
                if price_match:
                    sold_prices.append(float(price_match.group()))

    # Return top 10 relevant prices (skipping index 0 to be safe from hidden items)
    return active_count, sold_count, sold_prices[:10]

# --- STREAMLIT UI ---
st.set_page_config(page_title="Arbitrage Scanner", layout="centered")

st.title("📸 Arbitrage Scanner + LiDAR Calc")
st.write("Snap a photo to check liquidity. Use your iPhone's 'Measure' app for precise shipping costs.")

# --- SIDEBAR: LiDAR SHIPPING CALCULATOR ---
with st.sidebar:
    st.header("📦 Dimensions (LiDAR)")
    st.info("Input the L, W, H from your iPhone Measure app.")
    l = st.number_input("Length (cm):", min_value=1.0, value=20.0)
    w = st.number_input("Width (cm):", min_value=1.0, value=15.0)
    h = st.number_input("Height (cm):", min_value=1.0, value=10.0)
    actual_kg = st.number_input("Actual Weight (kg):", min_value=0.1, value=0.5)

# --- CORE SHIPPING LOGIC ---
cubic_kg = (l * w * h) / 4000
chargeable_kg = max(actual_kg, cubic_kg)

if chargeable_kg <= 5:
    volume_cm3 = l * w * h
    if volume_cm3 <= 2400: final_ship = 11.30
    elif volume_cm3 <= 7300: final_ship = 15.20
    elif volume_cm3 <= 16500: final_ship = 19.50
    else: final_ship = 23.30
else:
    final_ship = 15.00 + ((chargeable_kg - 5) * 2.50)

# --- 1. INPUTS ---
picture = st.camera_input("Scan Item")
store_price = st.number_input("Sticker Price (AUD):", min_value=0.0, format="%.2f")

# --- 2. PROCESS THE DATA ---
if picture and store_price > 0:
    with st.spinner("AI is analyzing the image..."):
        image_bytes = picture.getvalue()
        search_query = get_search_query_from_image(image_bytes)
        
    if search_query and search_query != "ITEM_NOT_RECOGNIZED":
        st.success(f"Identified: **{search_query}**")
        
        # Display shipping stats
        st.write(f"📏 **Chargeable Weight:** {chargeable_kg:.2f}kg (Actual: {actual_kg}kg, Cubic: {cubic_kg:.2f}kg)")
        st.write(f"🚚 **Estimated AusPost Shipping:** ${final_ship:.2f}")
        
        with st.spinner("Scraping market data..."):
            active_count, sold_count, valid_prices = analyze_market(search_query)
            
        if valid_prices and active_count is not None and sold_count is not None:
            average_price = sum(valid_prices) / len(valid_prices)
            str_percentage = (sold_count / active_count) * 100 if active_count > 0 else 1000.0
            
            # Financial Logic
            estimated_fees = average_price * 0.15
            net_revenue = average_price - estimated_fees
            profit = net_revenue - store_price - final_ship
            roi = (profit / store_price) * 100 if store_price > 0 else 0
            
            # --- DISPLAY THE DASHBOARD ---
            st.divider()
            st.subheader("Market Health (90-Day)")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Active Supply", active_count)
            col2.metric("Sold Demand", sold_count)
            col3.metric("Sell-Through", f"{str_percentage:.0f}%")
            
            if sold_count < 4:
                st.warning("⚠️ **Low Data Volume:** Proceed with extreme caution. Averages may be skewed.")
            elif str_percentage < 50:
                st.error("🛑 **Poor Liquidity:** High risk of this item sitting unsold.")
            else:
                st.info("✅ **Healthy Market Speed**")

            st.divider()
            st.subheader("Arbitrage Breakdown")
            
            f_col1, f_col2 = st.columns(2)
            f_col1.write("Estimated Market Value:")
            f_col2.write(f"**${average_price:.2f}**")
            
            f_col1.write("eBay Fees (15%):")
            f_col2.write(f"-${estimated_fees:.2f}")
            
            f_col1.write("Est. Shipping:")
            f_col2.write(f"-${final_ship:.2f}")

            f_col1.write("Cost of Goods:")
            f_col2.write(f"-${store_price:.2f}")
            
            st.divider()
            if profit > 0:
                st.success(f"### Expected Profit: +${profit:.2f} \n **ROI:** {roi:.0f}%")
            else:
                st.error(f"### Expected Loss: ${profit:.2f} \n **DO NOT BUY**")
                
        else:
            st.warning("Not enough relevant market data to analyze this item securely.")
    else:
        st.error("Could not confidently identify the item. Try a clearer angle.")
