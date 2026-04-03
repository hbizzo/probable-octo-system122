def scrape_ebay_listings(search_query):
    query_formatted = urllib.parse.quote_plus(search_query) 
    # Using ebay.com.au for local Australian results
    sold_url = f"https://www.ebay.com.au/sch/i.html?_nkw={query_formatted}&LH_Complete=1&LH_Sold=1&LH_PrefLoc=0"
    
    try:
        client = ZenRowsClient(ZENROWS_API_KEY)
        params = {
            "premium_proxy": "true",
            "proxy_country": "au", # Force AU proxy to match your local results
            "antibot": "true",
            "js_render": "true",  
            "wait": 5000 # Increased to 5s to ensure heavy eBay JS loads
        }
        
        response = client.get(sold_url, params=params)
        if response.status_code != 200:
            st.error(f"ZenRows Error: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        # Using a broader selector for items
        items = soup.select('.s-item')
        data_points = []
        
        for item in items:
            # FIX: Removed the 's-item__pl-on-bottom' skip logic
            
            title = item.select_one('.s-item__title')
            price = item.select_one('.s-item__price')
            link = item.select_one('.s-item__link')
            
            if title and price and link:
                price_text = price.text.replace(',', '')
                # Filter out 'Price Ranges' (e.g., $10 to $20)
                if "to" not in price_text.lower() and "$" in price_text:
                    # FIX: Regex now handles $85 AND $85.00
                    match = re.search(r'\d+(?:\.\d+)?', price_text)
                    if match:
                        data_points.append({
                            "Keep": True, 
                            "Title": title.text.replace("New Listing", "").strip(), 
                            "Price": float(match.group()), 
                            "Link": link['href']
                        })
        
        # Filter out the generic 'Shop on eBay' placeholder often found at index 0
        return [d for d in data_points if "shop on ebay" not in d['Title'].lower()][:15]
        
    except Exception as e:
        st.error(f"Scraping Error: {e}")
        return []
