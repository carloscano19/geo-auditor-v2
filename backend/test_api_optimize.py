
import asyncio
import requests
import json

def test_api():
    print("Testing /api/optimize endpoint (Integration)...")
    
    url = "http://localhost:8000/api/optimize"
    
    # Mock payload
    payload = {
        "content_text": "This is some test content.",
        "audit_results": {
            "detector_results": [
                {
                    "dimension": "freshness",
                    "score": 0,
                    "breakdown": [
                        {
                            "name": "Date Currency",
                            "explanation": "No date found",
                            "recommendations": ["Add date"]
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API Success!")
            print("Optimized Content (Preview):")
            print(data.get("optimized_content", "")[:100] + "...")
        else:
            print(f"❌ API Error: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    test_api()
