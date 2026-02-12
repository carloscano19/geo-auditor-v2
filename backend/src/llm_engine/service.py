
import os
import json
from typing import Dict, Any, Optional
from config.settings import get_settings
from src.llm_engine.prompts import OPTIMIZATION_SYSTEM_PROMPT

settings = get_settings()

# Optional imports for LLM SDKs
try:
    import openai
except ImportError:
    openai = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

class LLMService:
    def __init__(self):
        # We no longer hardcode provider/key in constructor
        pass

    async def optimize_content(self, original_text: str, audit_results: Dict[str, Any], provider: str, api_key: str) -> str:
        """
        Send content and audit results to LLM for optimization.
        """
        if not api_key:
            return "Error: No API Key provided."

        # Construct the user prompt with findings
        findings_summary = self._summarize_findings(audit_results)
        
        user_prompt = f"""
        ORIGINAL CONTENT:
        {original_text[:10000]}  # Truncate if too long to avoid token limits

        AUDIT FINDINGS (Issues to address):
        {findings_summary}
        
        Generate the ACTION PLAN BRIEFING now.
        """

        try:
            if provider == "openai" and openai:
                 client = openai.AsyncOpenAI(api_key=api_key)
                 response = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": OPTIMIZATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                 return response.choices[0].message.content

            elif provider == "perplexity" and openai:
                 # Perplexity uses OpenAI-compatible SDK
                 client = openai.AsyncOpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
                 response = await client.chat.completions.create(
                    model="sonar-pro", # Perplexity model
                    messages=[
                        {"role": "system", "content": OPTIMIZATION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.2 # Lower temperature for better accuracy in citations
                )
                 return response.choices[0].message.content
                 
            elif provider == "gemini" and genai:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-pro')
                combined_prompt = f"{OPTIMIZATION_SYSTEM_PROMPT}\n\n{user_prompt}"
                response = model.generate_content(combined_prompt)
                return response.text
                
            else:
                 return f"Error: Provider '{provider}' SDK not installed or configured correctly."
                 
        except Exception as e:
            return f"Error generating content: {str(e)}"

    def _summarize_findings(self, audit_results: Dict[str, Any]) -> str:
        """Convert simplified audit JSON into a readable list for the LLM."""
        summary = []
        results = audit_results.get("detector_results", [])
        
        for detector in results:
            dimension = detector.get("dimension", "Unknown")
            for item in detector.get("breakdown", []):
                # Only include items that didn't score 100 or have specific recommendations
                if item.get("weighted_score", 0) < item.get("weight", 1) * 100:
                    name = item.get("name")
                    explanation = item.get("explanation")
                    recs = item.get("recommendations", [])
                    
                    summary.append(f"- [{dimension}] {name}: {explanation}")
                    if recs:
                        summary.append(f"  Recommendation: {'; '.join(recs)}")
                        
        if not summary:
            return "No critical errors found, but please polish the content for better flow and authority."
            
        return "\n".join(summary)
