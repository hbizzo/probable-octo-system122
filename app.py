import streamlit as st
import base64
import requests
from bs4 import BeautifulSoup
import re
import time

# --- CONFIGURATION ---
# IMPORTANT: Remove hardcoded API keys. 
# Use Streamlit's secrets management: .streamlit/secrets.toml
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
except KeyError:
    st.error("API Key not found. Please configure your .streamlit/secrets.toml file.")
    st.stop()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

# --- HELPER FUNCTIONS ---
def get_search_query_from_image(image_bytes):
    """Sends the image buffer to OpenAI."""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": "You are an expert e-commerce appraiser. Look at the item in this image. Identify the brand and specific model. Output ONLY a highly accurate search string suitable for finding this exact item on eBay. Do not include any quotes, punctuation, or conversational text. Keep it concise. If you are entirely unsure, output 'ITEM_NOT_RECOGNIZED'."
            },
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}}]
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
            # This fixes the "suggested item" bug
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

st.title("📸 Arbitrage Scanner")
st.write("Snap a photo to instantly check market liquidity and margins.")

# 1. Inputs
picture = st.camera_input("Scan Item")

col_a, col_b = st.columns(2)
store_price = col_a.number_input("Sticker Price (AUD):", min_value=0.0, format="%.2f")
shipping_cost = col_b.number_input("Est. Shipping Cost (AUD):", min_value=0.0, value=10.00, format="%.2f")

# 2. Process the Data
if picture and store_price > 0:
    with st.spinner("AI is analyzing the image..."):
        image_bytes = picture.getvalue()
        search_query = get_search_query_from_image(image_bytes)
        
    if search_query and search_query != "ITEM_NOT_RECOGNIZED":
        st.success(f"Identified: **{search_query}**")
        
        with st.spinner("Scraping market data..."):
            active_count, sold_count, valid_prices = analyze_market(search_query)
            
        if valid_prices and active_count is not None and sold_count is not None:
            average_price = sum(valid_prices) / len(valid_prices)
            str_percentage = (sold_count / active_count) * 100 if active_count > 0 else 1000.0
            
            # Financial Logic
            estimated_fees = average_price * 0.15
            net_revenue = average_price - estimated_fees
            profit = net_revenue - store_price - shipping_cost
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
            f_col2.write(f"-${shipping_cost:.2f}")

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