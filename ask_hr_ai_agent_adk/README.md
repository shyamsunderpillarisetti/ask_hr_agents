# ask_hr_ai_agent_adk

Small Flask app where a Google GenAI agent (Gemini) uses tool calls to access Workday: fetch user context, validate time‑off dates, and submit requests.

## At a Glance
- Purpose: Chat UI for Workday self‑service with AI assistance.
- Tech: Flask, Google GenAI (Gemini), Selenium/ChromeDriver, Workday REST.
- Entry points: server (flask routes), agent (LLM + tools), Workday API client.
- Tools: get_workday_id_tool, check_valid_dates_tool, submit_time_off_tool.
- State: OAuth token + minimal context cached in `.token_cache.pkl`.
- Browser: Google Chrome (as implemented via Selenium ChromeDriver).

## Architecture
```
Browser UI
  │
  ▼
Flask server (/chat, /reset)
  │
  ▼
Agent (Gemini + tools)
  │           ├─ get_workday_id_tool
  │           ├─ check_valid_dates_tool
  │           └─ submit_time_off_tool
  ▼
Workday REST APIs
```

## Components
- UI: [ask_hr_ai_agent_adk/templates/index.html](ask_hr_ai_agent_adk/templates/index.html) — minimal chat page
- Server: [ask_hr_ai_agent_adk/flask_server.py](ask_hr_ai_agent_adk/flask_server.py) — routes `/`, `/chat`, `/reset`
  - `/` → [index](ask_hr_ai_agent_adk/flask_server.py#L12)
  - `/chat` → [chat handler](ask_hr_ai_agent_adk/flask_server.py#L18)
  - `/reset` → [reset handler](ask_hr_ai_agent_adk/flask_server.py#L54)
- Agent: [ask_hr_ai_agent_adk/agent.py](ask_hr_ai_agent_adk/agent.py) — Gemini config, tools, chat loop, caching
  - Entry: [chat_with_workday](ask_hr_ai_agent_adk/agent.py#L352), [get_user_context](ask_hr_ai_agent_adk/agent.py#L320)
  - Tools: [get_workday_id_tool](ask_hr_ai_agent_adk/agent.py#L255), [check_valid_dates_tool](ask_hr_ai_agent_adk/agent.py#L260), [submit_time_off_tool](ask_hr_ai_agent_adk/agent.py#L265)
- Workday: [ask_hr_ai_agent_adk/workday_api.py](ask_hr_ai_agent_adk/workday_api.py) — OAuth via Selenium + REST calls
  - OAuth: [get_auth_code](ask_hr_ai_agent_adk/workday_api.py#L29), [get_access_token](ask_hr_ai_agent_adk/workday_api.py#L103), [complete_oauth_flow](ask_hr_ai_agent_adk/workday_api.py#L191)
  - Data: [get_workday_data_merged](ask_hr_ai_agent_adk/workday_api.py#L161)
  - Absence: [get_valid_time_off_dates](ask_hr_ai_agent_adk/workday_api.py#L279), [submit_time_off_request](ask_hr_ai_agent_adk/workday_api.py#L288)
- Config: [ask_hr_ai_agent_adk/config.json](ask_hr_ai_agent_adk/config.json) — OAuth and tenant settings

## Authentication
- Uses OAuth2 Authorization Code flow launched via Selenium Chrome.
- Cache: `.token_cache.pkl` stored in project root.
- Reset: `POST /reset` (or set `ASKHR_RESET_AUTH_ON_STARTUP=true`) to force re‑auth.

## Configuration
- Update `config.json` with your Workday values (auth/token URLs, tenant, client id/secret, redirect URI).
- Chrome is required as implemented; other browsers would need small code changes.

## Endpoints
- Base: `{base_url}` (from `config.json`)
- Placeholders: `{tenant}`, `{workday_id}`, `{type_id}`, `{date}`

Staffing v7
```
GET  /api/staffing/v7/{tenant}/workers/me
GET  /api/staffing/v7/{tenant}/workers/me/serviceDates
```

Person v4
```
GET  /api/person/v4/{tenant}/people/me/legalName
```

Absence Management v3
```
GET  /api/absenceManagement/v3/{tenant}/balances?worker={workday_id}
GET  /api/absenceManagement/v3/{tenant}/workers/{workday_id}/eligibleAbsenceTypes
GET  /api/absenceManagement/v3/{tenant}/workers/{workday_id}/validTimeOffDates?timeOff={type_id}&date={date}
POST /api/absenceManagement/v3/{tenant}/workers/{workday_id}/requestTimeOff
```

OAuth
```
GET  {auth_url}        # authorize (returns code)
POST {token_url}       # exchange code → access_token
```

### Endpoint References (Code)
- Staffing: workers/me → [defined in primary_endpoints](ask_hr_ai_agent_adk/workday_api.py#L213)
- Staffing: serviceDates → [defined in primary_endpoints](ask_hr_ai_agent_adk/workday_api.py#L214), [explicit GET](ask_hr_ai_agent_adk/workday_api.py#L233)
- Person: legalName → [defined in primary_endpoints](ask_hr_ai_agent_adk/workday_api.py#L215), [explicit GET](ask_hr_ai_agent_adk/workday_api.py#L226)
- Absence: balances → [requested](ask_hr_ai_agent_adk/workday_api.py#L243), [debug reference](ask_hr_ai_agent_adk/workday_api.py#L270)
- Absence: eligibleAbsenceTypes → [requested](ask_hr_ai_agent_adk/workday_api.py#L251), [debug reference](ask_hr_ai_agent_adk/workday_api.py#L271)
- Absence: validTimeOffDates → [function endpoint](ask_hr_ai_agent_adk/workday_api.py#L283), [debug template](ask_hr_ai_agent_adk/workday_api.py#L272)
- Absence: requestTimeOff → [function endpoint](ask_hr_ai_agent_adk/workday_api.py#L292), [debug reference](ask_hr_ai_agent_adk/workday_api.py#L273)
- OAuth: authorize → [built `full_auth_url`](ask_hr_ai_agent_adk/workday_api.py#L52), [navigated](ask_hr_ai_agent_adk/workday_api.py#L65)
- OAuth: token → [POST token_url](ask_hr_ai_agent_adk/workday_api.py#L138)

## Troubleshooting
- If OAuth doesn’t pop up, verify Chrome is installed and accessible.
- If token expires, hit `/reset` or restart with `ASKHR_RESET_AUTH_ON_STARTUP=true`.
- Ensure `GOOGLE_API_KEY` is set in the environment before starting the server.
