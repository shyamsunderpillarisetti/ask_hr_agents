from postman_simulator import PostmanSimulator


def test_send_request_echo():
    sim = PostmanSimulator()
    res = sim.send_request("GET", "https://example.com", headers={"Accept": "*/*"}, body=None)
    assert res["method"] == "GET"
    assert res["url"] == "https://example.com"
    assert res["headers"]["Accept"] == "*/*"
    assert res["status"] == 200
    assert res["response"]["echo"]["method"] == "GET"
