import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache
import google.generativeai as genai

from workday_api import complete_oauth_flow, get_valid_time_off_dates, submit_time_off_request

genai.configure()

CONFIG_PATH = str(Path(__file__).parent / "config.json")


def _friendly_rate_limit_message(error: Exception) -> Optional[str]:
    """Return a user-friendly note when Vertex AI returns a 429/quota error."""
    err = str(error).lower()
    if '429' in err or 'resource exhausted' in err or 'quota' in err:
        return "I’m temporarily out of capacity (429: Resource exhausted). Please retry in a minute."
    return None

@lru_cache(maxsize=1)
def _get_cached_workday_data() -> Dict[str, Any]:
    """Cached OAuth result to avoid re-authenticating"""
    try:
        return complete_oauth_flow(config_path=CONFIG_PATH)
    except Exception as e:
        _get_cached_workday_data.cache_clear()
        raise ValueError(f"OAuth flow failed: {e}") from e

def get_workday_data() -> Dict[str, Any]:
    """Internal helper to get cached workday data"""
    try:
        return _get_cached_workday_data()
    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"Unexpected error retrieving Workday data: {e}") from e

def get_workday_id() -> str:
    """Get the current user's Workday ID, name, email, title, and organization"""
    try:
        result = get_workday_data()
        return json.dumps(result) if result else json.dumps({"error": "Failed to retrieve Workday info"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

def check_valid_dates(time_off_type_id: str, dates: list) -> str:
    """Check if specific dates are valid for a time off request
    
    Args:
        time_off_type_id: The ID of the absence/time off type from eligible absence types
        dates: List of dates to check in YYYY-MM-DD format
    
    Returns:
        JSON with validation results for each date
    """
    try:
        workday_data = get_workday_data()
        base_url = workday_data['debug']['base_url']
        tenant = workday_data['debug']['tenant']
        access_token = workday_data['access_token']
        workday_id = workday_data['workday_id']
        
        result = get_valid_time_off_dates(base_url, tenant, access_token, workday_id, time_off_type_id, dates)
        return json.dumps(result)
    except ValueError as e:
        # Token might be expired, clear cache
        _get_cached_workday_data.cache_clear()
        return json.dumps({"success": False, "error": f"Authentication expired. Please try again. ({str(e)})"})
    except KeyError as e:
        return json.dumps({"success": False, "error": f"Missing required field: {e}"})
    except Exception as e:
        # Check if it's an auth error
        error_str = str(e).lower()
        if 'unauthorized' in error_str or 'forbidden' in error_str or '401' in error_str or '403' in error_str:
            _get_cached_workday_data.cache_clear()
            return json.dumps({"success": False, "error": "Authentication expired. Please try again."})
        return json.dumps({"success": False, "error": str(e)})

def submit_time_off(time_off_type_id: str, start_date: str, end_date: str, 
                     hours_per_day: float, comment: Optional[str] = None) -> str:
    """Submit a time off request
    
    Args:
        time_off_type_id: The ID of the absence/time off type
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        hours_per_day: Number of hours per day (typically 8)
        comment: Optional comment for the request
    
    Returns:
        JSON with submission result
    """
    try:
        workday_data = get_workday_data()
        base_url = workday_data['debug']['base_url']
        tenant = workday_data['debug']['tenant']
        access_token = workday_data['access_token']
        workday_id = workday_data['workday_id']
        
        result = submit_time_off_request(base_url, tenant, access_token, workday_id, 
                                         time_off_type_id, start_date, end_date, 
                                         hours_per_day, comment)
        return json.dumps(result)
    except ValueError as e:
        # Token might be expired, clear cache
        _get_cached_workday_data.cache_clear()
        return json.dumps({"success": False, "error": f"Authentication expired. Please try again. ({str(e)})"})
    except KeyError as e:
        return json.dumps({"success": False, "error": f"Missing required field: {e}"})
    except Exception as e:
        # Check if it's an auth error
        error_str = str(e).lower()
        if 'unauthorized' in error_str or 'forbidden' in error_str or '401' in error_str or '403' in error_str:
            _get_cached_workday_data.cache_clear()
            return json.dumps({"success": False, "error": "Authentication expired. Please try again."})
        return json.dumps({"success": False, "error": str(e)})

# Define tools for Gemini using proper FunctionDeclaration format
tools = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="get_workday_id",
                description="Get the current user's Workday ID, name, email, title, and organization through OAuth 2.0 authentication",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={}
                )
            ),
            genai.protos.FunctionDeclaration(
                name="check_valid_dates",
                description="Check if specific dates are valid for submitting a time off request. Returns validation info including daily default hours for each date.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "time_off_type_id": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The ID of the time off/absence type (e.g., from eligible absence types like Vacation, Sick, etc.)"
                        ),
                        "dates": genai.protos.Schema(
                            type=genai.protos.Type.ARRAY,
                            items=genai.protos.Schema(type=genai.protos.Type.STRING),
                            description="List of dates to validate in YYYY-MM-DD format (e.g., ['2025-12-22', '2025-12-23'])"
                        )
                    },
                    required=["time_off_type_id", "dates"]
                )
            ),
            genai.protos.FunctionDeclaration(
                name="submit_time_off",
                description="Submit a time off request to Workday. ONLY call this after user explicitly confirms they want to submit the request.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "time_off_type_id": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The ID of the time off/absence type"
                        ),
                        "start_date": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Start date in YYYY-MM-DD format"
                        ),
                        "end_date": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="End date in YYYY-MM-DD format"
                        ),
                        "hours_per_day": genai.protos.Schema(
                            type=genai.protos.Type.NUMBER,
                            description="Number of hours per day (typically 8)"
                        ),
                        "comment": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Optional comment for the request"
                        )
                    },
                    required=["time_off_type_id", "start_date", "end_date", "hours_per_day"]
                )
            )
        ]
    )
]

# Create Gemini model with tool use
model = genai.GenerativeModel(
    "gemini-2.0-flash",
    tools=tools,
    system_instruction="""You are AskHR AI, a professional HR assistant powered by Workday.

**Available Tools:**
- get_workday_id: Retrieves comprehensive worker information including:
  • Personal details (name, email, worker ID)
  • Job information (title, department, manager, location)
  • Service dates and tenure
  • Leave/absence balances (vacation, sick leave, etc.)
  • Organization details
  
- check_valid_dates: Validates dates for time-off requests
  • Use when user asks about taking time off
  • Validates if specific dates are available
  
- submit_time_off: Submits time-off requests
  • Use only after confirming details with the user
  • Requires: time off type ID, start date, end date, hours per day, optional comment

**How to Respond:**
- Remember the conversation context - if user mentioned sick leave earlier, keep that in mind
- Listen to what the user asks and call the appropriate tool(s) to get information
- Extract and present only the relevant information they need
- Be conversational and helpful
- NEVER introduce yourself or say "I'm AskHR" - the user already knows who you are
- NEVER repeat greetings like "How can I help you today?" in responses
- If user just says "Hi" or "Hello", simply acknowledge briefly (e.g., "Hello! What can I help you with?") without re-introducing yourself
- When showing leave balances, ONLY show items with actual numeric values - skip any that are "Not specified" or empty

**For Time-Off Requests:**
When user wants to apply for time off:
1. First, call get_workday_id to get their eligible absence types and find the correct time off type ID
2. Ask for missing details (dates, duration) if not provided
3. When you have the time off type ID and dates, call check_valid_dates to validate
4. Present validation results and ask for confirmation
5. Only call submit_time_off after explicit user confirmation
6. Remember: sick leave = find "Sick" in eligible types, vacation = find "Vacation", etc.

Answer questions naturally based on the data you retrieve. Maintain conversation context."""
)

_chat_session = None

def get_chat_session():
    """Get or create a chat session"""
    global _chat_session
    if _chat_session is None:
        _chat_session = model.start_chat(history=[])
    return _chat_session

TOOL_HANDLERS: Dict[str, callable] = {
    "get_workday_id": lambda params: get_workday_id(),
    "check_valid_dates": lambda params: check_valid_dates(
        params.get('time_off_type_id'),
        list(params.get('dates', []))
    ),
    "submit_time_off": lambda params: submit_time_off(
        params.get('time_off_type_id'),
        params.get('start_date'),
        params.get('end_date'),
        params.get('hours_per_day'),
        params.get('comment')
    )
}

def chat_with_workday(user_message: str) -> str:
    """Send a message to Gemini and get a response"""
    chat = get_chat_session()
    try:
        response = chat.send_message(user_message)
    except Exception as e:
        friendly = _friendly_rate_limit_message(e)
        if friendly:
            return friendly
        raise
    
    while response.candidates and response.candidates[0].content.parts:
        function_called = False
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                function_name = part.function_call.name
                params = dict(part.function_call.args)
                
                handler = TOOL_HANDLERS.get(function_name)
                if handler:
                    try:
                        result = handler(params)
                        result_dict = json.loads(result) if isinstance(result, str) else result
                    except Exception as e:
                        result_dict = {"success": False, "error": str(e)}
                    
                    try:
                        response = chat.send_message(
                            genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=function_name,
                                    response=result_dict
                                )
                            )
                        )
                    except Exception as e:
                        friendly = _friendly_rate_limit_message(e)
                        if friendly:
                            return friendly
                        raise
                    function_called = True
                    break
        
        if not function_called:
            break
    
    return response.text


