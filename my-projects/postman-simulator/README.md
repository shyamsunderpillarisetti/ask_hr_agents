# postman-simulator

A minimal Python package that simulates HTTP requests for testing and development.

Usage

```python
from postman_simulator import PostmanSimulator
sim = PostmanSimulator()
res = sim.send_request("GET", "https://example.com", headers={"Accept": "*/*"})
print(res)
```

Run tests:

```bash
python -m pytest -q
```
