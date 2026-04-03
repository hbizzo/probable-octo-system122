import urllib.parse
import streamlit as st
import base64
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from zenrows import ZenRowsClient

# --- 1. PAGE SETUP ---
st.set_page_config(page_title="ScanAnalytics", layout="centered")

# --- 2. CONFIGURATION & SESSION STATE ---
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    ZENROWS_API_KEY = st.secrets["ZENROWS_API_KEY"]
except KeyError:
    st.error("API Key not found. Please configure your .streamlit/secrets.toml file.")
    st.stop()

if 'history' not in st.session_state: st.session_state.history = []
if 'shipping_cost' not in st.session_state: st.session_state.shipping_cost = 0.0
if 'raw_data' not in st.session_state: st.session_state.raw_data = None
if 'search_query' not in st.session_state: st.session_state.search_query = None

# --- 3. HELPER FUNCTIONS ---
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
    except Exception as e:
        st.error(f"AI Vision Error: {e}")
        return None

def scrape_ebay_listings(search_query):
    query_formatted = urllib.parse.quote_plus(search_query) 
    # Added LH_PrefLoc=1 to filter for "Australia Only"
    sold_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}&LH_Complete=1&LH_Sold=1&LH_PrefLoc=1"
    
    try:
        client = ZenRowsClient(ZENROWS_API_KEY)
        
        params = {
            "premium_proxy": "true",
            "proxy_country": "au", # Ensures the request comes from an AU IP
            "antibot": "true",
            "js_render": "true", 
            "wait_for": ".s-card, .s-item"
        }
        
        # Single request to ZenRows
        response = client.get(sold_url, params=params)
        
        if response.status_code != 200:
            st.error(f"ZenRows Error: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Select items using both current eBay class standards
        items = soup.select('.s-item, .s-card')
        data_points = []
        
        for item in items:
            title = item.select_one('.s-item__title, .s-card__title, [role="heading"]')
            price = item.select_one('.s-item__price, .s-card__price')
            link = item.select_one('.s-item__link, .s-card__link, a[href*="/itm/"]')
            
            if title and price and link:
                price_text = price.get_text(strip=True).replace(',', '')
                # Filter out price ranges to keep data clean
                if "to" not in price_text.lower() and "$" in price_text:
                    match = re.search(r'\d+(?:\.\d+)?', price_text)
                    if match:
                        data_points.append({
                            "Keep": True, 
                            "Title": title.text.replace("New Listing", "").strip(), 
                            "Price": float(match.group()), 
                            "Link": link['href'] if link.has_attr('href') else ""
                        })
        
        # Filter out "Shop on eBay" and promotional blocks
        return [d for d in data_points if "shop on" not in d['Title'].lower()][:15]
        
    except Exception as e:
        st.error(f"Scraping Error: {e}")
        return []
        
# --- 4. STREAMLIT UI ---
st.title("ScanAnalytics")

with st.sidebar:
    st.header("📦 Shipping (LiDAR)")
    l_cm = st.number_input("Length (cm):", min_value=0.0, value=None)
    w_cm = st.number_input("Width (cm):", min_value=0.0, value=None)
    h_cm = st.number_input("Height (cm):", min_value=0.0, value=None)
    weight_kg = st.number_input("Weight (kg):", min_value=0.0, value=None)
    
    if st.button("Calculate Shipping", use_container_width=True):
        if None in [l_cm, w_cm, h_cm, weight_kg]:
            st.error("Please enter all measurements.")
        else:
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
                
            st.session_state.shipping_cost = final_ship 
            
    st.metric("Est. Shipping (AU)", f"${st.session_state.shipping_cost:.2f}")

picture = st.camera_input("Scan Item")
store_price = st.number_input("Store Price (AUD):", min_value=0.0, value=None, format="%.2f")

if st.button("Analyze Item", type="primary", use_container_width=True):
    if not picture:
        st.warning("⚠️ Please take a photo first.")
    elif store_price is None:
        st.warning("⚠️ Please enter the Store Price.")
    else:
        with st.spinner("AI Identifying item..."):
            query = get_search_query_from_image(picture.getvalue())
            st.session_state.search_query = query
            
        if query and query != "ITEM_NOT_RECOGNIZED":
            with st.spinner(f"Searching eBay Australia for: {query}..."):
                st.session_state.raw_data = scrape_ebay_listings(query)
        else:
            st.session_state.raw_data = None
            st.error("Could not identify the item.")

if st.session_state.raw_data is not None:
    if len(st.session_state.raw_data) > 0: 
        st.success(f"Results for: **{st.session_state.search_query}** (Australia Only)")
        
        df = pd.DataFrame(st.session_state.raw_data)
        edited_df = st.data_editor(
            df, 
            column_config={
                "Keep": st.column_config.CheckboxColumn(default=True), 
                "Link": st.column_config.LinkColumn("View"), 
                "Price": st.column_config.NumberColumn(format="$%.2f")
            }, 
            disabled=["Title", "Price", "Link"], 
            hide_index=True, 
            use_container_width=True
        )
    
        verified_points = edited_df[edited_df["Keep"]]
        
        if not verified_points.empty:
            avg_val = verified_points["Price"].mean()
            # Calculation: (Avg Market * 0.85 fees) - Cost - Shipping
            profit = (avg_val * 0.85) - store_price - st.session_state.shipping_cost
            
            st.divider()
            c1, c2 = st.columns(2)
            c1.metric("Avg Market (AU)", f"${avg_val:.2f}")
            c2.metric("Estimated Profit", f"${profit:.2f}", delta=f"{profit:.2f}")
    
            if st.button("💾 Save to History"):
                st.session_state.history.append({
                    "Item": st.session_state.search_query,
                    "Sticker Price": store_price,
                    "Market Value": round(avg_val, 2),
                    "Shipping": round(st.session_state.shipping_cost, 2),
                    "Profit": round(profit, 2)
                })
                st.toast("Saved to history!")
                st.session_state.raw_data = None
                st.rerun()
        else:
            st.warning("Select at least one listing.")
    else:
        st.warning(f"No local Australian sold listings found for: **{st.session_state.search_query}**.")

st.divider()
st.subheader("📜 Sourcing History")

if st.session_state.history:
    history_df = pd.DataFrame(st.session_state.history)
    st.dataframe(
        history_df,
        column_config={
            "Sticker Price": st.column_config.NumberColumn(format="$%.2f"),
            "Market Value": st.column_config.NumberColumn(format="$%.2f"),
            "Shipping": st.column_config.NumberColumn(format="$%.2f"),
            "Profit": st.column_config.NumberColumn(format="$%.2f")
        },
        hide_index=True,
        use_container_width=True
    )
    if st.button("🗑️ Clear History"):
        st.session_state.history = []
        st.rerun()
else:
    st.info("Your history is empty.")
