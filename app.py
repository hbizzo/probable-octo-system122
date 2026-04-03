import urllib.parse
import streamlit as st
import base64
import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from zenrows import ZenRowsClient

# --- CONFIGURATION & SESSION STATE ---
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

# --- HELPER FUNCTIONS ---
def get_search_query_from_image(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "Identify the item. Output ONLY a concise keyword string for eBay (e.g. 'EA Sports FC 25 PS5'). No quotes, no extra text."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
        ],
        "max_tokens": 30
    }
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        return response.json()['choices'][0]['message']['content'].strip().replace('"', '')
    except: return None

def scrape_ebay_listings(search_query):
    query_formatted = urllib.parse.quote_plus(search_query) 
    # Use ebay.com.au and force Australia proxy location
    sold_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}&LH_Complete=1&LH_Sold=1"
    
    try:
        client = ZenRowsClient(ZENROWS_API_KEY)
        params = {
            "premium_proxy": "true",
            "proxy_country": "au", # Force AU proxy to ensure we see AUD prices
            "antibot": "true",
            "js_render": "true",  
            "wait": 5000 
        }
        
        response = client.get(sold_url, params=params)
        if response.status_code != 200:
            st.sidebar.error(f"ZenRows Error: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Broaden item selection (li or div with s-item class)
        items = soup.select('.s-item')
        st.sidebar.info(f"Raw items found: {len(items)}")
        
        data_points = []
        skip_reasons = {"No Price/Title": 0, "Range/To": 0, "No $": 0, "Regex Fail": 0}

        for item in items:
            # Flexible selectors: Find by class regardless of tag
            title_el = item.select_one('.s-item__title')
            price_el = item.select_one('.s-item__price')
            link_el = item.select_one('.s-item__link')
            
            if not title_el or not price_el:
                skip_reasons["No Price/Title"] += 1
                continue
                
            price_text = price_el.text.replace(',', '')
            
            # Filter out price ranges (e.g. $10 to $20)
            if "to" in price_text.lower():
                skip_reasons["Range/To"] += 1
                continue
            
            # Ensure price contains a currency symbol (supports $ or AU $)
            if "$" not in price_text:
                skip_reasons["No $"] += 1
                continue
            
            # Robust regex: handles $70, $70.00, AU $70.00
            match = re.search(r'\d+(?:\.\d+)?', price_text)
            if match:
                data_points.append({
                    "Keep": True, 
                    "Title": title_el.text.replace("New Listing", "").strip(), 
                    "Price": float(match.group()), 
                    "Link": link_el['href'] if link_el else "#"
                })
            else:
                skip_reasons["Regex Fail"] += 1
        
        # Log diagnostics to sidebar
        st.sidebar.write("Skip Diagnostics:", skip_reasons)
        
        # Filter out the 'Shop on eBay' placeholder listing if present
        return [d for d in data_points if "shop on ebay" not in d['Title'].lower()][:15]
        
    except Exception as e:
        st.sidebar.error(f"Scraper Exception: {e}")
        return []

# --- STREAMLIT UI ---
st.set_page_config(page_title="Arbitrage Scanner", layout="centered")
st.title("📸 Arbitrage Scanner")

with st.sidebar:
    st.header("📦 Shipping (LiDAR)")
    l_cm = st.number_input("Length (cm):", min_value=0.0, value=None)
    w_cm = st.number_input("Width (cm):", min_value=0.0, value=None)
    h_cm = st.number_input("Height (cm):", min_value=0.0, value=None)
    weight_kg = st.number_input("Weight (kg):", min_value=0.0, value=None)
    
    if st.button("🧮 Calculate Shipping", use_container_width=True):
        if all([l_cm, w_cm, h_cm, weight_kg]):
            # Basic AU Post style calculation
            chargeable = max(weight_kg, (l_cm * w_cm * h_cm) / 4000)
            st.session_state.shipping_cost = 11.30 if chargeable <= 0.5 else 15.0 + (chargeable * 2.5)
            
    st.metric("Est. Shipping", f"${st.session_state.shipping_cost:.2f}")

picture = st.camera_input("Scan Item")
store_price = st.number_input("Store Price (AUD):", min_value=0.0, value=0.0, format="%.2f")

if st.button("🚀 GO - Analyze Item", type="primary", use_container_width=True):
    if picture:
        with st.spinner("AI Identifying..."):
            query = get_search_query_from_image(picture.getvalue())
            st.session_state.search_query = query
            
        if query:
            with st.spinner(f"Scraping Sold '{query}'..."):
                st.session_state.raw_data = scrape_ebay_listings(query)
        else:
            st.error("Identification failed.")

if st.session_state.raw_data:
    st.success(f"Market Data for: **{st.session_state.search_query}**")
    df = pd.DataFrame(st.session_state.raw_data)
    edited_df = st.data_editor(df, use_container_width=True, hide_index=True)
    
    verified = edited_df[edited_df["Keep"]]
    if not verified.empty:
        avg = verified["Price"].mean()
        profit = (avg * 0.85) - store_price - st.session_state.shipping_cost
        c1, c2 = st.columns(2)
        c1.metric("Avg Sold Price", f"${avg:.2f}")
        c2.metric("Est. Net Profit", f"${profit:.2f}", delta=f"{profit:.2f}")
    
    if st.button("💾 Save to History"):
        st.session_state.history.append({"Item": st.session_state.search_query, "Profit": profit})
        st.toast("Saved!")
