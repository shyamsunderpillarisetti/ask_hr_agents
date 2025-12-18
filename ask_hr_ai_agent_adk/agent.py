import json
import os
import pickle
import re
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional

from google import genai
from google.genai import types

from workday_api import complete_oauth_flow, get_valid_time_off_dates, submit_time_off_request
from doc_generator import generate_docx_from_template, get_document_from_cache

CONFIG_PATH = str(Path(__file__).parent / "config.json")
TOKEN_CACHE_PATH = str(Path(__file__).parent / ".token_cache.pkl")


@lru_cache(maxsize=1)
def _get_cached_workday_data() -> Dict[str, Any]:
    """Get cached workday data with OAuth token expiration checking."""
    try:
        if os.path.exists(TOKEN_CACHE_PATH):
            with open(TOKEN_CACHE_PATH, 'rb') as f:
                cached_data = pickle.load(f)
                token_timestamp = cached_data.get('_token_timestamp', 0)
                token_expires_in = cached_data.get('_token_expires_in', 3600)
                if (time.time() - token_timestamp) < (token_expires_in - 120):
                    return cached_data
    except Exception:
        pass
    
    try:
        result = complete_oauth_flow(config_path=CONFIG_PATH)
        result['_token_timestamp'] = time.time()
        result['_token_expires_in'] = result.get('_token_expires_in', 3600)
        with open(TOKEN_CACHE_PATH, 'wb') as f:
            pickle.dump(result, f)
        return result
    except Exception as e:
        _get_cached_workday_data.cache_clear()
        raise ValueError(f"OAuth flow failed: {e}") from e


def _get_workday_data() -> Dict[str, Any]:
    """Get cached workday data."""
    try:
        return _get_cached_workday_data()
    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"Error retrieving Workday data: {e}") from e


def reset_auth_cache() -> bool:
    """Clear cached OAuth token and in-memory cache to force re-auth on next call."""
    global _user_context, _chat_history, _submission_complete
    try:
        try:
            _get_cached_workday_data.cache_clear()
        except Exception:
            pass
        _user_context = None
        _chat_history = []
        _submission_complete = False
        if os.path.exists(TOKEN_CACHE_PATH):
            os.remove(TOKEN_CACHE_PATH)
            print("✓ Token cache cleared (.token_cache.pkl deleted)")
        else:
            print("✓ No token cache found (already clear)")
        print("✓ Session state reset (context + history cleared)")
        return True
    except Exception as e:
        print(f"✗ Failed to reset auth cache: {e}")
        return False


def _format_balances(balance_data: Dict) -> list:
    """Format balance data."""
    balances = []
    for item in balance_data.get('data', []):
        plan = item.get('absencePlan', {})
        quantity = item.get('quantity', 'N/A')
        if quantity != 'N/A':
            balances.append({
                "plan": plan.get('descriptor'),
                "balance": quantity,
                "unit": item.get('unit', {}).get('descriptor', 'Hours')
            })
    return balances


def _format_absence_types(absence_data: Dict) -> list:
    """Format absence types."""
    types_list = []
    for item in absence_data.get('data', []):
        types_list.append({
            "name": item.get('descriptor'),
            "id": item.get('id'),
            "default_hours": item.get('dailyDefaultQuantity', '8')
        })
    return types_list


def _extract_manager_name(manager_descriptor: str) -> Optional[str]:
    """Extract manager name from descriptor like 'Engineering (Name)'."""
    if not manager_descriptor:
        return None
    match = re.search(r'\((.*?)\)', manager_descriptor)
    return match.group(1) if match else manager_descriptor


def _resolve_time_off_type_id(identifier: str) -> str:
    """Resolve a time-off type identifier to a valid ID.

    Accepts either a 32-char hex ID or a human-friendly name like "Vacation".
    If a name is provided, this looks up the corresponding ID from
    available eligible absence types.
    """
    try:
        ident = (identifier or '').strip()
        if not ident:
            raise ValueError("Empty time off type provided")

        import re
        if re.fullmatch(r"[0-9a-fA-F]{32}", ident):
            return ident.lower()
        data = _get_workday_data()
        raw_types = data.get('user_data', {}).get('eligible_absence_types', {}).get('data', [])
        if not raw_types:
            raise ValueError("No eligible time-off types available to resolve name")
        name_lower = ident.lower()
        exact_matches = [t for t in raw_types if str(t.get('descriptor', '')).lower() == name_lower]
        def is_time_off_group(t: dict) -> bool:
            return str(t.get('absenceTypeGroup', {}).get('descriptor', '')).lower() == 'time off'
        candidates = exact_matches or [t for t in raw_types if name_lower in str(t.get('descriptor', '')).lower()]
        if not candidates:
            raise ValueError(f"Could not resolve time off type name '{identifier}' to an ID")
        preferred = [t for t in candidates if is_time_off_group(t)] or candidates
        resolved_id = preferred[0].get('id')
        if not resolved_id or not re.fullmatch(r"[0-9a-fA-F]{32}", resolved_id):
            raise ValueError(f"Resolved ID for '{identifier}' is invalid")
        return resolved_id.lower()
    except Exception as e:
        raise


def get_workday_id() -> str:
    """Get user's Workday ID, name, job details, and leave information."""
    try:
        result = _get_workday_data()
        user_data = result.get('user_data', {})
        primary_job = user_data.get('primaryJob', {})
        person = user_data.get('person', {})
        
        legal_name_data = user_data.get('legalName', {}).get('data', [{}])[0]
        service_dates_data = user_data.get('serviceDates', {}).get('data', [{}])[0]
        
        def _pick_hire_date(d: Dict[str, Any]) -> Optional[str]:
            for key in ('hireDate', 'originalHireDate', 'firstDayOfWork', 'companyStartDate', 'reHireDate'):
                if d.get(key):
                    return d.get(key)
            return None

        extracted = {
            "workday_id": user_data.get('workerId'),
            "name": user_data.get('descriptor'),
            "legal_name": legal_name_data.get('descriptor') or f"{legal_name_data.get('first', '')} {legal_name_data.get('last', '')}".strip(),
            "email": person.get('email'),
            "hire_date": _pick_hire_date(service_dates_data),
            "continuous_service_date": service_dates_data.get('continuousServiceDate'),
            "job_title": primary_job.get('businessTitle'),
            "location": primary_job.get('location', {}).get('descriptor'),
            "manager": _extract_manager_name(primary_job.get('supervisoryOrganization', {}).get('descriptor')),
            "worker_type": user_data.get('workerType', {}).get('descriptor'),
            "leave_balances": _format_balances(user_data.get('absence_balances', {})),
            "available_time_off_types": _format_absence_types(user_data.get('eligible_absence_types', {}))
        }
        
        full_data = {
            "summary": extracted,
            "raw_data": {
                "worker_info": user_data,
                "legal_name": legal_name_data,
                "service_dates": service_dates_data,
                "primary_job": primary_job,
                "person": person,
                "absence_balances": user_data.get('absence_balances', {}),
                "eligible_absence_types": user_data.get('eligible_absence_types', {})
            }
        }
        
        return json.dumps(full_data, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def check_valid_dates(time_off_type_id: str, dates: list) -> str:
    """Check if dates are valid for a time off request."""
    try:
        workday_data = _get_workday_data()
        base_url = workday_data['debug']['base_url']
        tenant = workday_data['debug']['tenant']
        access_token = workday_data['access_token']
        workday_id = workday_data['workday_id']
        
        if not access_token:
            raise ValueError("No access token available")

        resolved_type_id = _resolve_time_off_type_id(time_off_type_id)
        result = get_valid_time_off_dates(base_url, tenant, access_token, workday_id, resolved_type_id, dates)
        return json.dumps(result)
    except ValueError as e:
        error_msg = str(e).lower()
        if 'auth' in error_msg or 'token' in error_msg:
            _get_cached_workday_data.cache_clear()
            return json.dumps({"success": False, "error": f"Authentication error. Please try again. ({str(e)})"})
        _get_cached_workday_data.cache_clear()
        return json.dumps({"success": False, "error": f"Validation error: {str(e)}"})
    except Exception as e:
        error_str = str(e).lower()
        if 'unauthorized' in error_str or 'forbidden' in error_str or '401' in error_str or '403' in error_str:
            _get_cached_workday_data.cache_clear()
            return json.dumps({"success": False, "error": "Authentication expired. Please try again."})
        return json.dumps({"success": False, "error": str(e)})


def submit_time_off(time_off_type_id: str, start_date: str, end_date: str, 
                     hours_per_day: float, comment: Optional[str] = None) -> str:
    """Submit a time off request."""
    try:
        workday_data = _get_workday_data()
        base_url = workday_data['debug']['base_url']
        tenant = workday_data['debug']['tenant']
        access_token = workday_data['access_token']
        workday_id = workday_data['workday_id']

        resolved_type_id = _resolve_time_off_type_id(time_off_type_id)
        result = submit_time_off_request(base_url, tenant, access_token, workday_id, 
                                         resolved_type_id, start_date, end_date, 
                                         hours_per_day, comment)
        return json.dumps(result)
    except ValueError as e:
        _get_cached_workday_data.cache_clear()
        return json.dumps({"success": False, "error": "Authentication expired. Please try again."})
    except Exception as e:
        error_str = str(e).lower()
        if 'unauthorized' in error_str or 'forbidden' in error_str or '401' in error_str or '403' in error_str:
            _get_cached_workday_data.cache_clear()
            return json.dumps({"success": False, "error": "Authentication expired. Please try again."})
        return json.dumps({"success": False, "error": str(e)})


def get_workday_id_tool() -> str:
    """Get the current user's Workday ID, name, email, title, and organization through OAuth 2.0 authentication"""
    return get_workday_id()


def check_valid_dates_tool(time_off_type_id: str, dates: list[str]) -> str:
    """Check if specific dates are valid for submitting a time off request."""
    return check_valid_dates(time_off_type_id, dates)


def submit_time_off_tool(time_off_type_id: str, start_date: str, end_date: str, 
                         hours_per_day: float, comment: Optional[str] = None) -> str:
    """Submit a time off request. Only call after user confirms."""
    return submit_time_off(time_off_type_id, start_date, end_date, hours_per_day, comment)


def generate_employment_verification_letter_tool() -> str:
    """Generate an employment verification letter for the current user using the template and auto-filled context."""
    try:
        context = get_template_context()
        # Use legal_name if available, otherwise fall back to employee_name, then 'Employee'
        legal_name = context.get('legal_name') or context.get('employee_name') or 'Employee'
        result = generate_docx_from_template(
            template_name="evl_template.docx",
            context=context,
            filename=f"Employment Verification Letter - {legal_name}.docx"
        )
        filename = result.get("filename")
        doc_key = result.get("download_key")
        download_url = f"/download_doc/{doc_key}"
        message = f"Your employment verification letter has been generated. **[Download here]({download_url})** - opens in a new tab."
        return json.dumps({
            "success": True,
            "filename": filename,
            "download_key": doc_key,
            "download_url": download_url,
            "message": message
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


tools = [
    get_workday_id_tool,
    check_valid_dates_tool,
    submit_time_off_tool,
    generate_employment_verification_letter_tool,
]


def get_template_context(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a default context mapping for templates from Workday user summary.

    Keys provided:
    employee_name, legal_name, email, job_title, manager, location,
    hire_date, worker_type, workday_id, today_date (and alias Today_Date).
    """
    try:
        data = json.loads(get_workday_id())
        summary = data.get('summary', {}) if isinstance(data, dict) else {}
        raw = data.get('raw_data', {}) if isinstance(data, dict) else {}
        raw_legal = raw.get('legal_name', {}) if isinstance(raw, dict) else {}
        from datetime import date
        today_str = date.today().strftime("%B %d, %Y")
        ctx = {
            "employee_name": summary.get("name"),
            "legal_name": summary.get("legal_name"),
            "email": summary.get("email"),
            "job_title": summary.get("job_title"),
            "manager": summary.get("manager"),
            "location": summary.get("location"),
            "hire_date": summary.get("hire_date"),
            "worker_type": summary.get("worker_type"),
            "workday_id": summary.get("workday_id"),
            "today_date": today_str,
            "Today_Date": today_str,
        }
        # auto-generate common alias variations (Title_Snake and PascalCase)
        def add_alias_variants(key: str):
            val = ctx.get(key)
            if val is None:
                return
            parts = key.split("_")
            title_snake = "_".join(p.capitalize() for p in parts)
            pascal = "".join(p.capitalize() for p in parts)
            ctx[title_snake] = val
            ctx[pascal] = val
        for base_key in [
            "employee_name","legal_name","email","job_title","manager",
            "location","hire_date","worker_type","workday_id","today_date"
        ]:
            add_alias_variants(base_key)
        # common alias mappings for template variables
        ctx.update({
            "Employee_Legal_Name": ctx.get("legal_name"),
            "Employee_Name": ctx.get("employee_name"),
            "Employee_Email": ctx.get("email"),
            "Employee_Position": ctx.get("job_title"),
            "Manager_Name": ctx.get("manager"),
            "Employee_Location": ctx.get("location"),
            "Hire_Date": ctx.get("hire_date"),
            "Worker_Type": ctx.get("worker_type"),
            "Employee_Workday_ID": ctx.get("workday_id"),
            "legal_first_name": raw_legal.get("first"),
            "legal_last_name": raw_legal.get("last"),
            "Legal_First_Name": raw_legal.get("first"),
            "Legal_Last_Name": raw_legal.get("last"),
        })
        if overrides and isinstance(overrides, dict):
            ctx.update(overrides)
        return ctx
    except Exception:
        return overrides or {}


client = genai.Client()

SYSTEM_INSTRUCTION = """You are AskHR AI, an HR assistant powered by Workday. You have access to the user's HR data and can answer questions about their profile, leave balances, time-off requests, and document generation. Respond naturally and helpfully using the information you have.

When users mention dates in natural language, convert them to YYYY-MM-DD format for any tools that require dates. You understand:
- Relative dates: "today", "tomorrow", "next Monday", "this Friday", "in 3 days", "in 2 weeks", "next month"
- Named dates: "Christmas", "New Year", "Thanksgiving", "Labor Day", "Memorial Day"
- Month-Day format: "December 25", "Dec 25", "12/25"
- Full dates: "12/25/2025", "December 25, 2025"
- Ranges: "next week", "end of month", "beginning of next week", "last 2 weeks"

DOCUMENT GENERATION:
- If the user asks for an employment verification letter, use generate_employment_verification_letter_tool() to create it.
- The tool auto-fills fields from their Workday profile (legal name, job title, manager, etc.) and returns a download link.
- Always provide the download URL to the user in your response so they can access the letter immediately.

CRITICAL - Time-Off Submission Rules (MANDATORY):

⛔ DO NOT CALL submit_time_off_tool UNLESS:
   - You have already shown the user a complete summary (type, dates, hours)
   - You have already asked "Would you like me to proceed with submitting this request?"
   - The user's MOST RECENT message is EXACTLY one of these words: "yes", "confirm", "submit", "go ahead", "proceed"

⛔ NEVER SUBMIT if the user's message:
   - Says "not yet", "wait", "hold on", "cancel", "no"
   - Says "thanks", "thank you", "ok", "okay", "sure" (NOT confirmations)
   - Is anything other than the explicit confirmation words listed above

✅ ACCEPT MODIFICATIONS:
   - If user wants to change hours ("make it 12", "only 2 hrs"), ACCEPT the change
   - If user wants different dates ("actually next week"), ACCEPT the change
   - After any modification: Show UPDATED summary with new values
   - Then ask for confirmation AGAIN: "Would you like me to proceed with submitting this request?"
   - Only then submit if they say "yes"/"confirm"/"submit"/"go ahead"/"proceed"

✅ Required Workflow for EVERY time-off submission:
   Step 1: Validate dates with check_valid_dates_tool using current hours/dates
   Step 2: Show summary: "I can submit [TYPE] for [DATES] ([HOURS] hours). Would you like me to proceed with submitting this request?"
   Step 3: STOP and WAIT for user response
   Step 4: IF user says explicit confirmation → Call submit_time_off_tool
           IF user modifies request (change hours/dates) → Accept the change, go back to Step 1 with new values
           IF user says anything else → DO NOT SUBMIT, just acknowledge and wait

Never reject user modifications. Always accept modifications, show updated summary, and ask for fresh confirmation."""

_chat_history = []
_user_context = None
_submission_complete = False


def get_user_context() -> str:
    """Fetch user context once and cache it"""
    global _user_context
    if _user_context:
        return _user_context
    
    try:
        user_data_json = get_workday_id()
        user_data = json.loads(user_data_json)
        if user_data.get('error'):
            return f"[Unable to fetch data: {user_data.get('error')}]"
        summary = user_data.get('summary', {})
        _user_context = f"""USER CONTEXT:
- Name: {summary.get('name')}
- Legal Name: {summary.get('legal_name')}
- Email: {summary.get('email')}
- Job Title: {summary.get('job_title')}
- Manager: {summary.get('manager')}
- Location: {summary.get('location')}
- Hire Date: {summary.get('hire_date')}
- Worker Type: {summary.get('worker_type')}

LEAVE BALANCES:
{json.dumps(summary.get('leave_balances', []), indent=2)}

AVAILABLE TIME-OFF TYPES:
{json.dumps(summary.get('available_time_off_types', []), indent=2)}"""
        return _user_context
    except Exception as e:
        return f"[Error fetching context: {str(e)}]"


def chat_with_workday(user_message: str) -> str:
    """Send a message to the agent with user context"""
    global _chat_history, _submission_complete
    
    try:
        # Reset chat history if previous submission completed
        if _submission_complete:
            _chat_history = []
            _submission_complete = False
        
        context = get_user_context()
        today_str = date.today().isoformat()
        full_message = f"{context}\n\nTODAY: {today_str}\n\nUSER MESSAGE: {user_message}"
        _chat_history.append(full_message)
        
        while True:
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=_chat_history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=tools,
                    temperature=0.7
                )
            )
            
            if hasattr(response, 'text') and response.text:
                _chat_history.append(response.text)
                return response.text
            
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    text_parts = []
                    tool_calls = []
                    
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                        elif hasattr(part, 'function_call'):
                            tool_calls.append(part.function_call)
                    
                    if text_parts:
                        result = ''.join(text_parts)
                        _chat_history.append(result)
                        return result
                    
                    if tool_calls:
                        _chat_history.append(candidate.content)
                        
                        for tool_call in tool_calls:
                            tool_name = tool_call.name
                            tool_args = tool_call.args
                            
                            if tool_name == 'get_workday_id_tool':
                                result = get_workday_id_tool()
                            elif tool_name == 'check_valid_dates_tool':
                                result = check_valid_dates_tool(
                                    tool_args.get('time_off_type_id'),
                                    tool_args.get('dates', [])
                                )
                            elif tool_name == 'submit_time_off_tool':
                                result = submit_time_off_tool(
                                    tool_args.get('time_off_type_id'),
                                    tool_args.get('start_date'),
                                    tool_args.get('end_date'),
                                    tool_args.get('hours_per_day'),
                                    tool_args.get('comment')
                                )
                                _submission_complete = True
                            else:
                                result = json.dumps({"error": f"Unknown tool: {tool_name}"})
                            
                            if isinstance(result, str):
                                try:
                                    result_data = json.loads(result)
                                except json.JSONDecodeError:
                                    result_data = {"result": result}
                            else:
                                result_data = result
                            
                            _chat_history.append({
                                "role": "user",
                                "parts": [{
                                    "function_response": {
                                        "name": tool_name,
                                        "response": result_data
                                    }
                                }]
                            })
                        continue
            
            return "I apologize, but I couldn't process that request. Please try again."
            
    except Exception as e:
        error_str = str(e).lower()
        if '429' in error_str or 'resource exhausted' in error_str or 'quota' in error_str:
            return "I'm temporarily out of capacity. Please retry in a minute."
        if 'unauthorized' in error_str or 'forbidden' in error_str or '401' in error_str or '403' in error_str:
            _get_cached_workday_data.cache_clear()
        raise
